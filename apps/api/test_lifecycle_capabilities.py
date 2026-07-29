"""Regression tests for product-lifecycle routing and human control boundaries."""

import json
import tempfile
import unittest
from pathlib import Path

from apps.api import main


class LifecycleCapabilityTests(unittest.TestCase):
    def test_every_specialized_task_kind_has_a_bound_lazy_skill(self):
        definitions = json.loads(main.SKILL_DEFINITIONS_PATH.read_text(encoding="utf-8"))
        bindings = json.loads(main.SKILL_BINDINGS_PATH.read_text(encoding="utf-8"))
        bound = {
            skill_id
            for groups in bindings.values()
            for skill_id in [*groups["required"], *groups["optional"]]
        }
        covered = {
            task_kind
            for skill_id in bound
            for task_kind in definitions[skill_id].get("activation", {}).get("allowed_task_kinds", [])
        }
        specialized = main.TASK_KINDS - {"general"}
        self.assertEqual(specialized - covered, set())

    def test_task_kind_selects_an_explicit_deliverable_standard(self):
        standards = json.loads(main.DELIVERABLE_STANDARDS_PATH.read_text(encoding="utf-8"))
        for task_kind, artifact_kind in main.ARTIFACT_KIND_BY_TASK_KIND.items():
            with self.subTest(task_kind=task_kind):
                selected_kind, selected_standard = main.deliverable_spec("", task_kind)
                self.assertEqual(selected_kind, artifact_kind)
                self.assertEqual(selected_standard, standards[artifact_kind])
                self.assertTrue(selected_standard["required_sections"])
                self.assertTrue(selected_standard["rules"])

    def test_sensitive_task_kinds_require_explicit_user_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            previous_db = main.DB_PATH
            main.DB_PATH = Path(temp) / "lifecycle.sqlite3"
            try:
                main.init_db()
                with main.database() as db:
                    for index, task_kind in enumerate(
                        ("privacy_review", "legal_compliance", "contract_review_draft", "sales_operations", "customer_support"),
                        start=1,
                    ):
                        task_id = f"TASK-SENSITIVE-{index:02d}"
                        now = main.utc_now()
                        db.execute(
                            "INSERT INTO tasks (id, title, request, route, state, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (task_id, task_kind, task_kind, "navi", "executing", now, now),
                        )
                        db.execute(
                            "INSERT INTO task_phases "
                            "(task_id, phase_id, parent_phase_id, department, owner_id, task_kind, "
                            "objective, expected_output, handoff_to, dependencies, skill_ids, status, "
                            "artifact_ids, source, sequence, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                task_id,
                                f"phase-{index}",
                                None,
                                "quality-security",
                                "GUARD",
                                task_kind,
                                task_kind,
                                "FINAL.md",
                                None,
                                "[]",
                                "[]",
                                "running",
                                "[]",
                                "test",
                                index,
                                now,
                                now,
                            ),
                        )
                        self.assertTrue(main.task_requires_user_approval(db, task_id))
            finally:
                main.DB_PATH = previous_db


if __name__ == "__main__":
    unittest.main()
