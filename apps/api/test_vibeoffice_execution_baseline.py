"""Acceptance tests for VibeOffice slice S3.5 (Product Execution Baseline).

Structure follows ``test_vibeoffice_contracts.py``. Every test maps to a promise
in docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md section 7 (S3.5):

1. Gate PE fires only once architecture is complete
2. a generated baseline passes Gate PE and lands on disk, IDs cross-reference
   the design/architecture packages
3. each Gate PE rule is independently enforced: broken Requirement->Task/Test
   link, unmeasurable KR, owner-less High risk, a Build-blocking deferred
   decision - all block via ``assert_gate_pe``, and a real Gate PE failure
   through the HTTP endpoint bounces the project to REWORK_REQUIRED and back
"""

import dataclasses
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.vibeoffice import architecture as architecture_service
from apps.api.vibeoffice import design as design_service
from apps.api.vibeoffice import execution_baseline as baseline_service
from apps.api.vibeoffice import handoff as handoff_service
from apps.api.vibeoffice import schema as vo_schema
from apps.api.vibeoffice.routes import router

IDEA_CAFE = "동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱"


class VibeOfficeExecutionBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = main.DB_PATH
        main.DB_PATH = Path(self.temp.name) / "vibeoffice.sqlite3"
        main.init_db()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        main.DB_PATH = self.previous_db
        self.temp.cleanup()

    # ----------------------------------------------------------------- helpers
    def _workspace(self, label: str) -> Path:
        path = Path(self.temp.name) / "workspaces" / label
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _project(self, idea: str = IDEA_CAFE, *, label: str) -> str:
        response = self.client.post(
            "/api/vibe/projects", json={"idea": idea, "workspace_path": str(self._workspace(label))}
        )
        self.assertEqual(response.status_code, 201, response.text)
        project_id = response.json()["id"]
        self.assertEqual(self.client.post(f"/api/vibe/projects/{project_id}/intake", json={}).status_code, 200)
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/blueprint/generate").status_code, 200
        )
        return project_id

    def _architecture_ready(self, idea: str = IDEA_CAFE, *, label: str) -> str:
        """Walk a project all the way to ARCHITECTURE_REVIEW."""
        project_id = self._project(idea, label=label)
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/blueprint/approve").status_code, 200
        )
        handoff = self.client.post(f"/api/vibe/projects/{project_id}/handoffs")
        self.assertEqual(handoff.status_code, 201, handoff.text)
        approve = self.client.post(
            f"/api/vibe/projects/{project_id}/handoffs/{handoff.json()['id']}/approve", json={}
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        run_design = self.client.post(f"/api/vibe/projects/{project_id}/departments/design/run")
        self.assertEqual(run_design.status_code, 200, run_design.text)
        approve_design = self.client.post(f"/api/vibe/projects/{project_id}/artifacts/design/approve")
        self.assertEqual(approve_design.status_code, 200, approve_design.text)
        run_architecture = self.client.post(f"/api/vibe/projects/{project_id}/departments/architecture/run")
        self.assertEqual(run_architecture.status_code, 200, run_architecture.text)
        return project_id

    def _run_baseline(self, project_id: str, *, expect: int = 200) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/departments/execution-baseline/run")
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _blueprint_content(self, project_id: str) -> dict:
        return self.client.get(f"/api/vibe/projects/{project_id}/blueprint").json()["blueprint"]

    def _baseline(self, project_id: str) -> tuple[baseline_service.ExecutionBaseline, dict]:
        content = self._blueprint_content(project_id)
        design_package = design_service.build_design_package(content)
        architecture_package = architecture_service.build_architecture_package(design_package, content)
        return baseline_service.build_execution_baseline(design_package, architecture_package, content), content

    # -------------------------------------------------------- 1. state gating
    def test_baseline_run_blocked_before_architecture_completes(self):
        project_id = self._project(label="early")
        self._run_baseline(project_id, expect=409)

    # -------------------------------------------------------- 2. happy path
    def test_baseline_run_produces_cross_referenced_artifacts(self):
        project_id = self._architecture_ready(label="happy")
        result = self._run_baseline(project_id)
        self.assertEqual(result["state"], vo_schema.ProjectState.ARCHITECTURE_REVIEW.value)
        self.assertGreater(result["requirement_count"], 0)
        self.assertEqual(result["requirement_count"], result["key_result_count"])

        baseline = result["baseline"]
        req_ids = {req["id"] for req in baseline["requirements"]}
        traced_req_ids = {row["requirementId"] for row in baseline["traceability"]}
        self.assertEqual(req_ids, traced_req_ids)
        for row in baseline["traceability"]:
            self.assertIsNotNone(row["taskId"])
            self.assertIsNotNone(row["testId"])

        artifact_types = {artifact["type"] for artifact in result["artifacts"]}
        self.assertEqual(artifact_types, set(baseline_service.artifact_store.EXECUTION_BASELINE_TYPES))
        for artifact_type in artifact_types:
            fetched = self.client.get(f"/api/vibe/projects/{project_id}/artifacts/{artifact_type}")
            self.assertEqual(fetched.status_code, 200, fetched.text)
            self.assertTrue(fetched.json()["body"])

        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.ARCHITECTURE_REVIEW.value)

    def test_baseline_is_pure_function_of_upstream_artifacts(self):
        project_id = self._architecture_ready(label="pure")
        first, _ = self._baseline(project_id)
        second, _ = self._baseline(project_id)
        self.assertEqual(first.to_dict(), second.to_dict())

    # -------------------------------------------------- 3. Gate PE, each rule alone
    def test_gate_pe_passes_on_a_freshly_generated_baseline(self):
        project_id = self._architecture_ready(label="gatepass")
        baseline, _ = self._baseline(project_id)
        baseline_service.assert_gate_pe(baseline)  # must not raise

    def test_gate_pe_blocks_requirement_missing_task_link(self):
        project_id = self._architecture_ready(label="notask")
        baseline, _ = self._baseline(project_id)
        broken_row = dataclasses.replace(baseline.traceability[0], task_id=None)
        broken = dataclasses.replace(baseline, traceability=(broken_row,) + baseline.traceability[1:])
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("Task에 연결되지 않았습니다" in reason for reason in raised.exception.reasons))

    def test_gate_pe_blocks_requirement_missing_test_link(self):
        project_id = self._architecture_ready(label="notest")
        baseline, _ = self._baseline(project_id)
        broken_row = dataclasses.replace(baseline.traceability[0], test_id=None)
        broken = dataclasses.replace(baseline, traceability=(broken_row,) + baseline.traceability[1:])
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("Test에 연결되지 않았습니다" in reason for reason in raised.exception.reasons))

    def test_gate_pe_blocks_requirement_missing_traceability_row(self):
        project_id = self._architecture_ready(label="norow")
        baseline, _ = self._baseline(project_id)
        broken = dataclasses.replace(baseline, traceability=baseline.traceability[1:])
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("traceability 행이 없습니다" in reason for reason in raised.exception.reasons))

    def test_gate_pe_blocks_unmeasurable_kr(self):
        project_id = self._architecture_ready(label="badkr")
        baseline, _ = self._baseline(project_id)
        broken_kr = dataclasses.replace(baseline.key_results[0], requirement_id=None, measurement_source="", judged_at="")
        broken = dataclasses.replace(baseline, key_results=(broken_kr,) + baseline.key_results[1:])
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("측정 계획에도 연결되지 않았습니다" in reason for reason in raised.exception.reasons))

    def test_gate_pe_blocks_kr_referencing_unknown_requirement(self):
        project_id = self._architecture_ready(label="badkrref")
        baseline, _ = self._baseline(project_id)
        broken_kr = dataclasses.replace(baseline.key_results[0], requirement_id="REQ-999")
        broken = dataclasses.replace(baseline, key_results=(broken_kr,) + baseline.key_results[1:])
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("존재하지 않는 Requirement" in reason for reason in raised.exception.reasons))

    def test_gate_pe_blocks_deferred_structural_decision(self):
        project_id = self._architecture_ready(label="deferred")
        baseline, _ = self._baseline(project_id)
        structural_label = handoff_service.STRUCTURAL_DECISION_LABELS[0]
        blocking = baseline_service.Decision(
            id="DEC-999",
            text=f"{structural_label} - {vo_schema.BLUEPRINT_DIRNAME} (사용자가 '나중에 결정'을 선택함)",
            status="deferred",
            affected_artifacts=("PRD.md",),
            revisit_condition="사용자가 값을 확정하면 재검토",
        )
        broken = dataclasses.replace(baseline, decisions=baseline.decisions + (blocking,))
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("Build 전 결정이 필요한" in reason for reason in raised.exception.reasons))

    def test_gate_pe_allows_deferred_non_structural_decision(self):
        """Only *structural* deferred decisions block - guide section 9's own
        distinction (budget/deadline deferrals don't reshape the screen tree)."""
        project_id = self._architecture_ready(label="deferrednonstruct")
        baseline, _ = self._baseline(project_id)
        harmless = baseline_service.Decision(
            id="DEC-998",
            text="예산 - 나중에 결정",
            status="deferred",
            affected_artifacts=("PRD.md",),
            revisit_condition="예산이 확정되면 재검토",
        )
        extended = dataclasses.replace(baseline, decisions=baseline.decisions + (harmless,))
        baseline_service.assert_gate_pe(extended)  # must not raise

    def test_gate_pe_blocks_high_risk_without_owner(self):
        project_id = self._architecture_ready(label="noowner")
        baseline, _ = self._baseline(project_id)
        risky = baseline_service.RiskEntry(
            id="RISK-999", title="치명적 위험", severity="high", mitigation="완화책 있음", owner=""
        )
        broken = dataclasses.replace(baseline, risks=baseline.risks + (risky,))
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("owner 또는 mitigation" in reason for reason in raised.exception.reasons))

    def test_gate_pe_blocks_high_risk_without_mitigation(self):
        project_id = self._architecture_ready(label="nomitigation")
        baseline, _ = self._baseline(project_id)
        risky = baseline_service.RiskEntry(
            id="RISK-998", title="치명적 위험", severity="high", mitigation="", owner="BUILD"
        )
        broken = dataclasses.replace(baseline, risks=baseline.risks + (risky,))
        with self.assertRaises(baseline_service.GatePEError) as raised:
            baseline_service.assert_gate_pe(broken)
        self.assertTrue(any("owner 또는 mitigation" in reason for reason in raised.exception.reasons))

    def test_gate_pe_allows_low_severity_risk_without_owner(self):
        project_id = self._architecture_ready(label="lowok")
        baseline, _ = self._baseline(project_id)
        harmless = baseline_service.RiskEntry(
            id="RISK-997", title="사소한 위험", severity="low", mitigation="", owner=""
        )
        extended = dataclasses.replace(baseline, risks=baseline.risks + (harmless,))
        baseline_service.assert_gate_pe(extended)  # must not raise

    # ---------------------------------------------------- 4. bounce on real failure
    def test_gate_pe_failure_through_the_endpoint_bounces_and_recovers(self):
        project_id = self._architecture_ready(label="bounce")
        original = baseline_service.build_execution_baseline

        def broken_build(design_package, architecture_package, blueprint_content):
            baseline = original(design_package, architecture_package, blueprint_content)
            corrupted = dataclasses.replace(baseline.traceability[0], task_id=None)
            return dataclasses.replace(baseline, traceability=(corrupted,) + baseline.traceability[1:])

        baseline_service.build_execution_baseline = broken_build
        try:
            self._run_baseline(project_id, expect=422)
        finally:
            baseline_service.build_execution_baseline = original

        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.REWORK_REQUIRED.value)

        # Repairable: re-running with the real generator passes and restores state.
        self._run_baseline(project_id, expect=200)
        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.ARCHITECTURE_REVIEW.value)


if __name__ == "__main__":
    unittest.main()
