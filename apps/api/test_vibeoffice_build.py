"""Acceptance tests for VibeOffice slice S4 (internal MVP build).

Structure follows ``test_vibeoffice_execution_baseline.py``. Every test maps to
a promise in docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md section 7 (S4):

1. Gate F fires only once the Execution Baseline exists
2. a real ``node scripts/build.js`` / ``node scripts/test.js`` run succeeds
   against the generated scaffold, evidence lands on disk, state moves
   ARCHITECTURE_REVIEW -> BUILD -> BUILD_VERIFICATION
3. Gate F's own rules are independently enforced: failing build/test command,
   no scaffolded screens, missing mock-boundary/not-implemented documentation
4. a real Gate F failure (a genuinely broken scaffold, not a hand-built
   fixture) bounces the project to REWORK_REQUIRED and a retry recovers
"""

import dataclasses
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.vibeoffice import architecture as architecture_service
from apps.api.vibeoffice import build as build_service
from apps.api.vibeoffice import design as design_service
from apps.api.vibeoffice import schema as vo_schema
from apps.api.vibeoffice.routes import router

IDEA_CAFE = "동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱"

_NODE_MISSING = shutil.which("node") is None


@unittest.skipIf(_NODE_MISSING, "node is required to execute the S4 build/test scaffold commands")
class VibeOfficeBuildTests(unittest.TestCase):
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

    def _baseline_ready(self, idea: str = IDEA_CAFE, *, label: str) -> str:
        """Walk a project all the way through S3.5 (ARCHITECTURE_REVIEW + PRD)."""
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
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/departments/design/run").status_code, 200
        )
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/artifacts/design/approve").status_code, 200
        )
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/departments/architecture/run").status_code, 200
        )
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/departments/execution-baseline/run").status_code,
            200,
        )
        return project_id

    def _run_build(self, project_id: str, *, expect: int = 200) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/departments/build/run")
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _workspace_path(self, project_id: str) -> Path:
        with vo_schema.s2_database() as db:
            return Path(vo_schema.load_project(db, project_id)["workspace_path"])

    def _packages(self, project_id: str):
        from apps.api.vibeoffice import blueprint as blueprint_service

        content = blueprint_service.get_blueprint(project_id)["blueprint"]
        design_package = design_service.build_design_package(content)
        architecture_package = architecture_service.build_architecture_package(design_package, content)
        return design_package, architecture_package

    # -------------------------------------------------------- 1. state gating
    def test_build_run_blocked_before_execution_baseline_exists(self):
        project_id = self._project(label="early")
        self._run_build(project_id, expect=409)

    # -------------------------------------------------------- 2. happy path
    def test_build_run_executes_real_commands_and_advances_state(self):
        project_id = self._baseline_ready(label="happy")
        result = self._run_build(project_id)
        self.assertEqual(result["state"], vo_schema.ProjectState.BUILD_VERIFICATION.value)
        self.assertTrue(result["build_ok"])
        self.assertTrue(result["test_ok"])
        self.assertGreater(result["screen_count"], 0)
        self.assertGreater(result["entity_count"], 0)

        workspace = self._workspace_path(project_id)
        self.assertTrue((workspace / "app" / "index.html").is_file())
        self.assertTrue((workspace / "app" / "mock-data.json").is_file())
        self.assertTrue((workspace / "app" / "dist" / "index.html").is_file(), "build.js must produce dist/index.html")

        artifact_types = {artifact["type"] for artifact in result["artifacts"]}
        self.assertEqual(artifact_types, set(build_service.artifact_store.BUILD_EVIDENCE_TYPES))
        # PROJECT_STATUS.md must land at the workspace root, not docs/.
        self.assertTrue((workspace / "PROJECT_STATUS.md").is_file())
        self.assertTrue((workspace / "docs" / "BUILD_REPORT.md").is_file())
        self.assertTrue((workspace / ".vibeoffice" / "current-state.json").is_file())

        for artifact_type in artifact_types:
            fetched = self.client.get(f"/api/vibe/projects/{project_id}/artifacts/{artifact_type}")
            self.assertEqual(fetched.status_code, 200, fetched.text)
            self.assertTrue(fetched.json()["body"])

        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.BUILD_VERIFICATION.value)

    def test_build_scaffold_is_pure_function_of_upstream_artifacts(self):
        project_id = self._baseline_ready(label="pure")
        design_package, architecture_package = self._packages(project_id)
        workspace = self._workspace_path(project_id)
        first = build_service.build_scaffold(workspace, design_package, architecture_package)
        second = build_service.build_scaffold(workspace, design_package, architecture_package)
        self.assertEqual(first[0], second[0])
        self.assertEqual([e.to_dict() for e in first[1]], [e.to_dict() for e in second[1]])

    # -------------------------------------------------- 3. Gate F, each rule alone
    def test_gate_f_passes_on_real_command_output(self):
        project_id = self._baseline_ready(label="gatepass")
        design_package, architecture_package = self._packages(project_id)
        workspace = self._workspace_path(project_id)
        screen_ids, entities = build_service.build_scaffold(workspace, design_package, architecture_package)
        build_result, test_result = build_service.run_smoke_commands(workspace)
        evidence = build_service.BuildEvidence(
            screen_ids=screen_ids,
            entities=entities,
            build=build_result,
            test=test_result,
            mock_boundaries=build_service._MOCK_BOUNDARIES,
            not_implemented=build_service._NOT_IMPLEMENTED,
            working=tuple(f"{sid} 화면" for sid in screen_ids),
        )
        build_service.assert_gate_f(evidence)  # must not raise

    def test_gate_f_blocks_a_failing_build_command(self):
        project_id = self._baseline_ready(label="buildfail")
        design_package, architecture_package = self._packages(project_id)
        workspace = self._workspace_path(project_id)
        screen_ids, entities = build_service.build_scaffold(workspace, design_package, architecture_package)
        (workspace / build_service.APP_DIRNAME / "index.html").unlink()  # build.js requires this to exist
        build_result, test_result = build_service.run_smoke_commands(workspace)
        self.assertFalse(build_result.ok)
        evidence = build_service.BuildEvidence(
            screen_ids=screen_ids, entities=entities, build=build_result, test=test_result,
            mock_boundaries=build_service._MOCK_BOUNDARIES, not_implemented=build_service._NOT_IMPLEMENTED,
            working=(),
        )
        with self.assertRaises(build_service.GateFError) as raised:
            build_service.assert_gate_f(evidence)
        self.assertTrue(any("build 명령이 실패했습니다" in reason for reason in raised.exception.reasons))

    def test_gate_f_blocks_a_failing_test_command(self):
        project_id = self._baseline_ready(label="testfail")
        design_package, architecture_package = self._packages(project_id)
        workspace = self._workspace_path(project_id)
        screen_ids, entities = build_service.build_scaffold(workspace, design_package, architecture_package)
        # Corrupt mock-data.json after the scaffold write so build.js's only
        # check (non-empty key set) still passes but test.js's stricter
        # structural assert (exact key count, non-empty arrays) fails.
        (workspace / build_service.APP_DIRNAME / "mock-data.json").write_text(
            '{"only-one-empty-key": []}', encoding="utf-8"
        )
        build_result, test_result = build_service.run_smoke_commands(workspace)
        self.assertTrue(build_result.ok)
        self.assertFalse(test_result.ok)
        evidence = build_service.BuildEvidence(
            screen_ids=screen_ids, entities=entities, build=build_result, test=test_result,
            mock_boundaries=build_service._MOCK_BOUNDARIES, not_implemented=build_service._NOT_IMPLEMENTED,
            working=(),
        )
        with self.assertRaises(build_service.GateFError) as raised:
            build_service.assert_gate_f(evidence)
        self.assertTrue(any("test 명령이 실패했습니다" in reason for reason in raised.exception.reasons))

    def test_gate_f_blocks_missing_mock_boundary_documentation(self):
        project_id = self._baseline_ready(label="nomockdoc")
        design_package, architecture_package = self._packages(project_id)
        workspace = self._workspace_path(project_id)
        screen_ids, entities = build_service.build_scaffold(workspace, design_package, architecture_package)
        build_result, test_result = build_service.run_smoke_commands(workspace)
        evidence = build_service.BuildEvidence(
            screen_ids=screen_ids, entities=entities, build=build_result, test=test_result,
            mock_boundaries=(), not_implemented=build_service._NOT_IMPLEMENTED, working=(),
        )
        with self.assertRaises(build_service.GateFError) as raised:
            build_service.assert_gate_f(evidence)
        self.assertTrue(any("mock 경계가 문서화되지 않았습니다" in reason for reason in raised.exception.reasons))

    def test_gate_f_blocks_missing_not_implemented_documentation(self):
        project_id = self._baseline_ready(label="nonotimpl")
        design_package, architecture_package = self._packages(project_id)
        workspace = self._workspace_path(project_id)
        screen_ids, entities = build_service.build_scaffold(workspace, design_package, architecture_package)
        build_result, test_result = build_service.run_smoke_commands(workspace)
        evidence = build_service.BuildEvidence(
            screen_ids=screen_ids, entities=entities, build=build_result, test=test_result,
            mock_boundaries=build_service._MOCK_BOUNDARIES, not_implemented=(), working=(),
        )
        with self.assertRaises(build_service.GateFError) as raised:
            build_service.assert_gate_f(evidence)
        self.assertTrue(any("미구현 항목이 명시되지 않았습니다" in reason for reason in raised.exception.reasons))

    def test_gate_f_blocks_zero_scaffolded_screens(self):
        evidence = build_service.BuildEvidence(
            screen_ids=(),
            entities=(),
            build=build_service.CommandResult("x", 0, "a", "b", "", True),
            test=build_service.CommandResult("y", 0, "a", "b", "", True),
            mock_boundaries=build_service._MOCK_BOUNDARIES,
            not_implemented=build_service._NOT_IMPLEMENTED,
            working=(),
        )
        with self.assertRaises(build_service.GateFError) as raised:
            build_service.assert_gate_f(evidence)
        self.assertTrue(any("스캐폴드된 화면이 없습니다" in reason for reason in raised.exception.reasons))

    # ---------------------------------------------------- 4. bounce on real failure
    def test_gate_f_failure_through_the_endpoint_bounces_and_recovers(self):
        project_id = self._baseline_ready(label="bounce")
        workspace = self._workspace_path(project_id)
        original = build_service.build_scaffold

        def broken_scaffold(workspace_arg, design_package, architecture_package):
            screen_ids, entities = original(workspace_arg, design_package, architecture_package)
            (workspace_arg / build_service.APP_DIRNAME / "index.html").unlink()
            return screen_ids, entities

        build_service.build_scaffold = broken_scaffold
        try:
            self._run_build(project_id, expect=422)
        finally:
            build_service.build_scaffold = original

        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.REWORK_REQUIRED.value)

        # Repairable: re-running with the real scaffold restores index.html and passes.
        result = self._run_build(project_id, expect=200)
        self.assertEqual(result["state"], vo_schema.ProjectState.BUILD_VERIFICATION.value)


if __name__ == "__main__":
    unittest.main()
