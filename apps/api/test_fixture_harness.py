"""Data-driven acceptance harness (docs/RUNTIME_ROADMAP.md P2).

Each fixture under fixtures/cases/*.json drives the real plan-storage,
phase-dependency-gated execution, skill-policy, and completion-invariant
code paths in main.py/worker.py. Only the model boundary (main.run_agent) is
mocked, matching the seam already used by test_workflow_acceptance.py.

Add coverage by adding a fixture JSON file, not by adding a test method.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api import main, worker
from apps.api.artifact_renderer import formats_for_request
from apps.api.fixtures.schema import Fixture, load_all_fixtures


class FixtureHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = main.DB_PATH
        main.DB_PATH = Path(self.temp.name) / "fixtures.sqlite3"
        main.init_db()
        self.client = TestClient(main.app)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        main.DB_PATH = self.previous_db
        self.temp.cleanup()

    def create_task(self, request: str) -> tuple[str, str]:
        response = self.client.post(
            "/api/tasks",
            json={"title": "Fixture task", "request": request, "selected_employees": [], "route": "navi"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        contract = self.client.post(
            f"/api/tasks/{task['id']}/contract",
            json={"allowed_paths": ["."], "allowed_commands": [], "acceptance_criteria": ["fixture acceptance"]},
        )
        self.assertEqual(contract.status_code, 200, contract.text)
        workspace_id = f"WS-{task['id'].split('-')[-1]}"
        with main.database() as db:
            db.execute(
                "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?)",
                (workspace_id, task["id"], str(self.workspace), str(self.workspace), "in_place", "ready", main.utc_now()),
            )
        return task["id"], workspace_id

    def render_final_deliverable(self, fixture: Fixture, task_id: str) -> None:
        """Drive the same format-selection and render path as process_synthesize.

        The formats are not hard-coded in the fixture: formats_for_request reads
        the task request wording, so a fixture asserting .pptx proves the runtime
        actually honoured "슬라이드" in the user's own request.
        """
        artifact_kind = fixture.plan["artifact_kind"]
        formats = formats_for_request(fixture.task_request, artifact_kind)
        with main.database() as db:
            final = db.execute(
                "SELECT owner, path FROM deliverables WHERE task_id = ? AND status = 'final_candidate' "
                "ORDER BY updated_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            self.assertIsNotNone(final, f"{fixture.id}: render step needs a final_candidate deliverable")
            rendered = [
                main.register_existing_deliverable(
                    db, self.workspace, task_id, final["owner"],
                    f"{artifact_kind}:{path.suffix.lstrip('.') or 'manifest'}", path, "rendered_candidate",
                )
                for path in main.render_bundle(self.workspace / final["path"], formats)
            ]
        suffixes = sorted({Path(item["path"]).suffix for item in rendered})
        self.assertEqual(
            suffixes, sorted(fixture.expected_rendered_suffixes),
            f"{fixture.id}: rendered formats did not match what the request asked for",
        )
        for item in rendered:
            self.assertGreater(
                (self.workspace / item["path"]).stat().st_size, 0,
                f"{fixture.id}: rendered {item['path']} is empty",
            )

    def run_fixture(self, fixture: Fixture) -> None:
        task_id, workspace_id = self.create_task(fixture.task_request)
        phases = fixture.plan["phases"]

        with main.database() as db:
            main.store_execution_plan(db, task_id, fixture.plan)
            for sequence, phase in enumerate(phases, 1):
                db.execute(
                    "INSERT OR IGNORE INTO task_assignments VALUES (?, ?)",
                    (task_id, phase["lead_id"]),
                )
                db.execute(
                    "INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"ACT-{task_id.split('-')[-1]}-{sequence:02d}", task_id, None,
                        phase["lead_id"], phase["objective"], sequence, "[]", "proposed",
                    ),
                )

        call_order: list[str] = []

        def fake_run_agent(current_task_id, payload):
            call_order.append(payload.employee_id)
            spec = fixture.phase_outputs[payload.employee_id]
            with main.database() as db:
                deliverable = main.persist_deliverable(
                    db, self.workspace, current_task_id, payload.employee_id,
                    spec.get("kind", "business_document"), spec["content"],
                    filename=spec["path"], status=spec.get("status", "department_draft"),
                )
            return {"summary": spec.get("summary", "fixture output"), "deliverable": deliverable}

        with patch.object(main, "run_agent", side_effect=fake_run_agent):
            for phase in phases:
                employee = phase["lead_id"]
                with main.database() as db:
                    job = main.enqueue_job(
                        db, task_id, "execute",
                        {"workspace_id": workspace_id, "employee_ids": [employee], "instruction": phase["objective"]},
                    )
                    db.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (job["id"],))
                worker.process_execute(job)
                with main.database() as db:
                    db.execute("UPDATE jobs SET state = 'succeeded' WHERE id = ?", (job["id"],))

        self.assertEqual(
            call_order, fixture.expected_phase_order,
            f"{fixture.id}: real execution order diverged from expected phase order",
        )

        with main.database() as db:
            # Fixtures drive each phase's final deliverable directly instead of
            # letting a lead's synthesize job assemble it; close out any
            # follow-up job process_execute auto-queued so it doesn't read as
            # still-active work when we check completion invariants below.
            db.execute(
                "UPDATE jobs SET state = 'succeeded' WHERE task_id = ? "
                "AND state IN ('queued','running','pause_requested','cancel_requested')",
                (task_id,),
            )

        if fixture.expected_rendered_suffixes is not None:
            self.render_final_deliverable(fixture, task_id)

        for employee, spec in fixture.prohibited_skills.items():
            skill_ids = spec.get("skill_ids", []) if isinstance(spec, dict) else spec
            task_kind = spec.get("task_kind") if isinstance(spec, dict) else None
            kwargs = {"task_kind": task_kind} if task_kind else {}
            for skill_id in skill_ids:
                with self.assertRaises(
                    Exception, msg=f"{fixture.id}: {employee} must not select prohibited skill {skill_id}"
                ):
                    main.validate_selected_skills(employee, [skill_id], **kwargs)

        if fixture.verify_run:
            with main.database() as db:
                db.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"RUN-{task_id}", task_id, workspace_id, fixture.verify_run["command"],
                        fixture.verify_run.get("exit_code", 0), "stdout-hash", "stderr-hash",
                        "pass" if fixture.verify_run.get("exit_code", 0) == 0 else "fail", main.utc_now(),
                    ),
                )

        with main.database() as db:
            db.execute(
                "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)",
                (f"REV-{task_id}", task_id, fixture.reviewer_id, "pass", "[]", main.utc_now()),
            )

        with main.database() as db:
            if fixture.expected_completion:
                main.assert_completion_invariants(db, task_id, self.workspace)
            else:
                with self.assertRaises(RuntimeError) as raised:
                    main.assert_completion_invariants(db, task_id, self.workspace)
                if fixture.expected_error_contains:
                    self.assertIn(
                        fixture.expected_error_contains, str(raised.exception),
                        f"{fixture.id}: completion error did not mention expected reason",
                    )

    def test_all_fixtures(self):
        fixtures = load_all_fixtures()
        self.assertGreater(len(fixtures), 0, "no fixtures found under fixtures/cases/")
        for fixture in fixtures:
            with self.subTest(fixture=fixture.id):
                self.run_fixture(fixture)


if __name__ == "__main__":
    unittest.main()
