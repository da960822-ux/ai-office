"""Unit tests for apply_stage_ordering -- the department pipeline gate.

No model/network calls: apply_stage_ordering is a pure function over the phase
list the planner LLM would have produced, so these exercise it directly.
"""

import json
import unittest
from pathlib import Path

from apps.api import main

BOUNDARIES = json.loads(Path("registry/department-boundaries.json").read_text(encoding="utf-8"))


def phase(id_, department, depends_on=None):
    return {"id": id_, "department": department, "lead_id": department, "depends_on": list(depends_on or [])}


class ApplyStageOrderingTests(unittest.TestCase):
    def test_registry_stages_are_defined(self):
        for department, policy in BOUNDARIES.items():
            self.assertIsInstance(policy.get("stage"), int, department)

    def test_later_stage_gains_dependency_on_earlier_stage(self):
        phases = [phase("p1", "application"), phase("p2", "product-experience")]
        main.apply_stage_ordering(phases, BOUNDARIES)
        self.assertIn("p2", phases[0]["depends_on"])  # application (stage 2) waits on product-experience (stage 1)
        self.assertNotIn("p1", phases[1]["depends_on"])  # stage 1 never waits on stage 2

    def test_same_stage_phases_stay_independent(self):
        phases = [phase("p1", "application"), phase("p2", "ai-data")]
        main.apply_stage_ordering(phases, BOUNDARIES)
        self.assertEqual(phases[0]["depends_on"], [])
        self.assertEqual(phases[1]["depends_on"], [])

    def test_llm_declared_dependency_survives(self):
        phases = [phase("p1", "quality-security", depends_on=["p2"]), phase("p2", "application")]
        main.apply_stage_ordering(phases, BOUNDARIES)
        self.assertIn("p2", phases[0]["depends_on"])

    def test_department_absent_from_plan_has_no_effect(self):
        phases = [phase("p1", "application")]
        main.apply_stage_ordering(phases, BOUNDARIES)
        self.assertEqual(phases[0]["depends_on"], [])

    def test_three_stage_chain_orders_transitively(self):
        phases = [phase("plan", "product-experience"), phase("build", "application"), phase("review", "quality-security")]
        main.apply_stage_ordering(phases, BOUNDARIES)
        self.assertEqual(phases[0]["depends_on"], [])
        self.assertIn("plan", phases[1]["depends_on"])
        self.assertIn("plan", phases[2]["depends_on"])
        self.assertIn("build", phases[2]["depends_on"])

    def test_operations_planning_stage_zero_never_gains_dependency(self):
        phases = [phase("navi", "operations-planning"), phase("plan", "product-experience")]
        main.apply_stage_ordering(phases, BOUNDARIES)
        self.assertEqual(phases[0]["depends_on"], [])

    def test_deterministic_fallback_plan_also_gets_stage_ordering(self):
        """fallback_execution_plan runs when the model call fails; it must not be a
        bypass for the pipeline gate just because no LLM was involved."""
        roster = ["FRAME", "BUILD"]
        items = [("FRAME", "PRD"), ("BUILD", "implement")]
        plan = main.fallback_execution_plan(roster, items)
        by_lead = {phase["lead_id"]: phase for phase in plan["phases"]}
        self.assertIn("fallback-1", by_lead["BUILD"]["depends_on"])  # application (2) waits on product-experience (1)
        self.assertEqual(by_lead["FRAME"]["depends_on"], [])


if __name__ == "__main__":
    unittest.main()
