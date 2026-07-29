"""Acceptance tests for workflow guarantees visible to an AI Office user.

These tests intentionally exercise boundaries between planning, meetings,
execution, and completion.  They do not mock implementation internals away:
each assertion represents a user-facing promise that previously regressed.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api import main, worker


class _OneShotResponses:
    def __init__(self, output: str):
        self.output = output

    def create(self, **_kwargs):
        return SimpleNamespace(
            output_text=self.output,
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


class _OneShotModel:
    def __init__(self, output: str):
        self.responses = _OneShotResponses(output)


class WorkflowAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = main.DB_PATH
        main.DB_PATH = Path(self.temp.name) / "acceptance.sqlite3"
        main.init_db()
        self.client = TestClient(main.app)
        self.workspace = Path(self.temp.name) / "opened-project"
        self.workspace.mkdir()

    def tearDown(self):
        main.DB_PATH = self.previous_db
        self.temp.cleanup()

    def create_task(self, request: str = "새 시장 기회를 조사해 단일 사업안을 결정한다"):
        response = self.client.post(
            "/api/tasks",
            json={"title": "Acceptance task", "request": request, "selected_employees": [], "route": "navi"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        response = self.client.post(
            f"/api/tasks/{task['id']}/contract",
            json={"allowed_paths": ["."], "allowed_commands": [], "acceptance_criteria": ["사용자 요청에 답한다"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        workspace_id = f"WS-{task['id'].split('-')[-1]}"
        with main.database() as db:
            db.execute(
                "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?)",
                (workspace_id, task["id"], str(self.workspace), str(self.workspace), "in_place", "ready", main.utc_now()),
            )
        return task["id"], workspace_id

    def _running_job(self, task_id: str, kind: str, payload: dict) -> dict:
        with main.database() as db:
            job = main.enqueue_job(db, task_id, kind, payload)
            db.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (job["id"],))
        return job

    def test_approval_cannot_complete_without_an_approved_real_file(self):
        """No review/evidence shortcut may complete a task without FINAL.md."""
        task_id, _ = self.create_task()
        with main.database() as db:
            db.execute("UPDATE tasks SET state = 'awaiting_approval' WHERE id = ?", (task_id,))
            db.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("EVD-ACCEPT-REVIEW", task_id, None, "lead_review", "pass", "hash", 0, main.utc_now()),
            )

        response = self.client.post(f"/api/tasks/{task_id}/approval", json={"decision": "approve", "reason": "approve"})

        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotEqual(self.client.get(f"/api/tasks/{task_id}").json()["state"], "completed")

    def test_dependent_phase_does_not_run_before_upstream_artifact_exists(self):
        """A dependency is a gate, not merely optional prompt context."""
        task_id, workspace_id = self.create_task()
        plan = {
            "summary": "research then decision",
            "artifact_kind": "business_document",
            "final_owner": "FRAME",
            "workspace_context": "none",
            "requires_web_research": True,
            "evidence_strategy": "primary sources",
            "reason": "acceptance test",
            "phases": [
                {"id": "research", "department": "growth-marketing", "lead_id": "GROW", "objective": "verify market evidence", "output": "research.md", "handoff_to": "FRAME", "depends_on": [], "skill_ids": []},
                {"id": "decision", "department": "product-experience", "lead_id": "FRAME", "objective": "use research.md to decide", "output": "FINAL.md", "handoff_to": None, "depends_on": ["research"], "skill_ids": []},
            ],
        }
        with main.database() as db:
            main.store_execution_plan(db, task_id, plan)
            db.execute("INSERT INTO task_assignments VALUES (?, ?)", (task_id, "FRAME"))
            db.execute(
                "INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("ACT-001-01", task_id, None, "FRAME", "use research.md to decide", 1, "[]", "proposed"),
            )
        job = self._running_job(task_id, "execute", {"workspace_id": workspace_id, "employee_ids": ["FRAME"], "instruction": "decision"})

        with patch.object(main, "run_agent", return_value={"summary": "must not run without research.md"}) as run_agent:
            worker.process_execute(job)

        run_agent.assert_not_called()

    def test_meeting_worker_proposal_becomes_execution_roster_not_lead_placeholder(self):
        """A valid PULSE proposal from GROW must survive plan-to-meeting handoff."""
        task_id, _ = self.create_task()
        plan = {
            "summary": "market research",
            "artifact_kind": "business_document",
            "final_owner": "GROW",
            "workspace_context": "none",
            "requires_web_research": True,
            "evidence_strategy": "primary sources",
            "reason": "acceptance test",
            "phases": [
                {"id": "research", "department": "growth-marketing", "lead_id": "GROW", "objective": "select required worker", "output": "research.md", "handoff_to": "GROW", "depends_on": [], "skill_ids": []},
            ],
        }
        meeting_id = "MEET-001-LEADS"
        with main.database() as db:
            main.store_execution_plan(db, task_id, plan)
            db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
            db.execute("INSERT INTO task_assignments VALUES (?, ?)", (task_id, "GROW"))
            db.execute(
                "INSERT INTO meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (meeting_id, task_id, "lead_dispatch", "delegate", json.dumps(["GROW"]), json.dumps(["scope"]), "[]", "active", main.utc_now()),
            )
        job = self._running_job(task_id, "meeting", {"meeting_id": meeting_id, "participants": ["GROW"]})
        proposal = json.dumps({
            "message": "PULSE must validate market evidence.",
            "assignments": [{
                "worker_id": "PULSE",
                "description": "Collect and verify market evidence.",
                "skill_ids": ["analytics"],
                "deliverable": "departments/PULSE.md",
                "handoff_to": "GROW",
                "depends_on": [],
            }],
        })

        with patch.object(main, "model_client", return_value=_OneShotModel(proposal)):
            worker.process_meeting(job)

        task = self.client.get(f"/api/tasks/{task_id}").json()
        self.assertEqual([item["owner"] for item in task["action_items"]], ["PULSE"])
        self.assertEqual(task["agent_scopes"][0]["employee_id"], "PULSE")

    def test_market_research_cannot_select_or_preload_ui_skill(self):
        """Skill catalog is lazy; GROW cannot select a Product Experience UI skill."""
        with self.assertRaises(HTTPException) as error:
            main.validate_selected_skills("GROW", ["ui-ux-pro-max"])
        self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as task_error:
            main.validate_selected_skills("MOSS", ["ui-ux-pro-max"], task_kind="market_research")
        self.assertEqual(task_error.exception.status_code, 403)
        context = main.employee_skill_context("GROW", "시장 조사와 경쟁사 검증", selected_skill_ids=[])
        self.assertEqual(context["profile_skill_ids"], [])
        self.assertEqual(context["required_skills"], [])

    def test_additional_user_instruction_is_durable_and_consumed_once(self):
        task_id, _ = self.create_task("기존 계획을 유지하면서 가격 검증도 추가한다")

        response = self.client.post(
            f"/api/tasks/{task_id}/steer",
            json={"content": "기존 조사 결과를 버리지 말고 가격 민감도 검증을 추가해"},
        )

        self.assertEqual(response.status_code, 202, response.text)
        with main.database() as db:
            first = main.consume_steering_messages(db, task_id)
            second = main.consume_steering_messages(db, task_id)
        self.assertEqual([item["content"] for item in first], ["기존 조사 결과를 버리지 말고 가격 민감도 검증을 추가해"])
        self.assertEqual(second, [])
        task = self.client.get(f"/api/tasks/{task_id}").json()
        self.assertEqual(task["steering_messages"][0]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
