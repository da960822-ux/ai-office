"""Acceptance tests for VibeOffice slice S3 (design approval -> architecture contract).

Structure follows ``test_vibeoffice_handoff.py``. Every test maps to a promise in
docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md section 7 (S3) or the Gate D/E row of the
section 8 gate table:

1. design approval (승인 2) only fires from DESIGN_REVIEW, once
2. architecture cannot start before design is approved
3. a generated architecture package passes Gate D/E and lands on disk
4. each Gate D/E rule is independently enforced: field mismatch, missing source,
   auth mismatch, missing error handling, secret pattern, task-graph problems,
   Out-scope task - all block via ``assert_gate_d``, and a real Gate D failure
   through the HTTP endpoint bounces the project to REWORK_REQUIRED
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
from apps.api.vibeoffice import schema as vo_schema
from apps.api.vibeoffice.routes import router

IDEA_CAFE = "동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱"


class VibeOfficeContractsTests(unittest.TestCase):
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

    def _design_reviewed(self, idea: str = IDEA_CAFE, *, label: str) -> str:
        """Walk a project up to DESIGN_REVIEW (design package generated, unapproved)."""
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
        run = self.client.post(f"/api/vibe/projects/{project_id}/departments/design/run")
        self.assertEqual(run.status_code, 200, run.text)
        return project_id

    def _design_approved(self, idea: str = IDEA_CAFE, *, label: str) -> str:
        project_id = self._design_reviewed(idea, label=label)
        response = self.client.post(f"/api/vibe/projects/{project_id}/artifacts/design/approve")
        self.assertEqual(response.status_code, 200, response.text)
        return project_id

    def _run_architecture(self, project_id: str, *, expect: int = 200) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/departments/architecture/run")
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _blueprint_content(self, project_id: str) -> dict:
        return self.client.get(f"/api/vibe/projects/{project_id}/blueprint").json()["blueprint"]

    def _package(self, project_id: str) -> tuple[architecture_service.ArchitecturePackage, dict]:
        content = self._blueprint_content(project_id)
        design_package = design_service.build_design_package(content)
        return architecture_service.build_architecture_package(design_package, content), content

    # -------------------------------------------------------- 1. design approval
    def test_design_approve_only_fires_from_design_review(self):
        project_id = self._project(label="early")
        response = self.client.post(f"/api/vibe/projects/{project_id}/artifacts/design/approve")
        self.assertEqual(response.status_code, 409, response.text)

    def test_design_approve_is_not_repeatable(self):
        project_id = self._design_approved(label="onceonly")
        response = self.client.post(f"/api/vibe/projects/{project_id}/artifacts/design/approve")
        self.assertEqual(response.status_code, 409, response.text)

    # -------------------------------------------------------- 2. architecture gating
    def test_architecture_run_blocked_before_design_approved(self):
        project_id = self._design_reviewed(label="notyet")
        self._run_architecture(project_id, expect=409)

    def test_architecture_run_blocked_for_fresh_project(self):
        project_id = self._project(label="fresh")
        self._run_architecture(project_id, expect=409)

    # -------------------------------------------------------- 3. happy path
    def test_architecture_run_produces_matching_contract_and_advances_state(self):
        project_id = self._design_approved(label="happy")
        result = self._run_architecture(project_id)
        self.assertEqual(result["state"], vo_schema.ProjectState.ARCHITECTURE_REVIEW.value)
        self.assertGreater(result["endpoint_count"], 0)
        self.assertEqual(result["endpoint_count"], result["entity_count"])

        endpoints_by_entity = {endpoint["entity"]: endpoint["fields"] for endpoint in result["endpoints"]}
        entities_by_name = {entity["name"]: entity["fields"] for entity in result["entities"]}
        self.assertEqual(endpoints_by_entity, entities_by_name)

        artifact_types = {artifact["type"] for artifact in result["artifacts"]}
        self.assertEqual(artifact_types, set(architecture_service.artifact_store.ARCHITECTURE_PACKAGE_TYPES))

        # Each rendered document reopens from the workspace with real bytes.
        for artifact_type in artifact_types:
            fetched = self.client.get(f"/api/vibe/projects/{project_id}/artifacts/{artifact_type}")
            self.assertEqual(fetched.status_code, 200, fetched.text)
            self.assertTrue(fetched.json()["body"])

        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.ARCHITECTURE_REVIEW.value)

    def test_architecture_run_is_idempotent_in_content(self):
        """Regenerating twice is a pure function of the same approved blueprint."""
        project_id = self._design_approved(label="pure")
        first, _ = self._package(project_id)
        second, _ = self._package(project_id)
        self.assertEqual(first.to_dict(), second.to_dict())

    # -------------------------------------------------- 4. Gate D/E, each rule alone
    def test_gate_d_passes_on_a_freshly_generated_package(self):
        project_id = self._design_approved(label="gatepass")
        package, content = self._package(project_id)
        architecture_service.assert_gate_d(package, content)  # must not raise

    def test_gate_d_blocks_field_mismatch(self):
        project_id = self._design_approved(label="fieldmismatch")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.entities[0], fields=("totally", "different", "fields"))
        entities = (broken,) + package.entities[1:]
        broken_package = dataclasses.replace(package, entities=entities)
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("일치하지 않습니다" in reason for reason in raised.exception.reasons))

    def test_gate_d_blocks_missing_source_for_a_data_screen(self):
        project_id = self._design_approved(label="missingsource")
        package, content = self._package(project_id)
        self.assertTrue(package.endpoints, "fixture assumes at least one data-driven screen")
        broken_package = dataclasses.replace(package, endpoints=package.endpoints[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("연결된 API가 없습니다" in reason for reason in raised.exception.reasons))

    def test_gate_d_blocks_auth_mismatch(self):
        project_id = self._design_approved(label="authmismatch")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.endpoints[0], auth="impossible-auth-value")
        broken_package = dataclasses.replace(package, endpoints=(broken,) + package.endpoints[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("인증 방식" in reason for reason in raised.exception.reasons))

    def test_gate_d_blocks_missing_error_handling(self):
        project_id = self._design_approved(label="noerrorhandling")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.endpoints[0], error_handling="")
        broken_package = dataclasses.replace(package, endpoints=(broken,) + package.endpoints[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("실패 처리 정의가 없습니다" in reason for reason in raised.exception.reasons))

    def test_gate_d_blocks_secret_pattern(self):
        project_id = self._design_approved(label="secretpattern")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.endpoints[0], error_handling="실패 시 password=hunter2로 재시도")
        broken_package = dataclasses.replace(package, endpoints=(broken,) + package.endpoints[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("비밀정보 패턴" in reason for reason in raised.exception.reasons))

    def test_gate_e_blocks_task_referencing_unknown_dependency(self):
        project_id = self._design_approved(label="badtaskdep")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.tasks[-1], depends_on=("TASK-999",))
        broken_package = dataclasses.replace(package, tasks=package.tasks[:-1] + (broken,))
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("존재하지 않는 작업" in reason for reason in raised.exception.reasons))

    def test_gate_e_blocks_self_dependent_task(self):
        project_id = self._design_approved(label="selfdep")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.tasks[0], depends_on=(package.tasks[0].id,))
        broken_package = dataclasses.replace(package, tasks=(broken,) + package.tasks[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("자기 자신에 의존" in reason for reason in raised.exception.reasons))

    def test_gate_e_blocks_multi_session_task(self):
        project_id = self._design_approved(label="multisession")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.tasks[0], session_size="three-sessions")
        broken_package = dataclasses.replace(package, tasks=(broken,) + package.tasks[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("한 세션 크기를 넘습니다" in reason for reason in raised.exception.reasons))

    def test_gate_e_blocks_task_without_definition_of_done(self):
        project_id = self._design_approved(label="nodod")
        package, content = self._package(project_id)
        broken = dataclasses.replace(package.tasks[0], definition_of_done="")
        broken_package = dataclasses.replace(package, tasks=(broken,) + package.tasks[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("done 조건이 없습니다" in reason for reason in raised.exception.reasons))

    def test_gate_e_blocks_out_scope_task(self):
        project_id = self._design_approved(label="outscope")
        package, content = self._package(project_id)
        out_features = (content.get("scope") or {}).get("out") or []
        self.assertTrue(out_features, "fixture assumes the blueprint always carries Out features")
        out_name = str(out_features[0]["name"])
        broken = dataclasses.replace(package.tasks[0], title=f"{out_name} 구현")
        broken_package = dataclasses.replace(package, tasks=(broken,) + package.tasks[1:])
        with self.assertRaises(architecture_service.GateDError) as raised:
            architecture_service.assert_gate_d(broken_package, content)
        self.assertTrue(any("Out)한 기능을 작업으로 만들었습니다" in reason for reason in raised.exception.reasons))

    # ---------------------------------------------------- 5. bounce on real failure
    def test_gate_d_failure_through_the_endpoint_bounces_to_rework_required(self):
        """A real Gate D failure (not a hand-built fixture) must still bounce the
        project, the same way ``design.run_design`` bounces on Gate C."""
        project_id = self._design_approved(label="bounce")
        original = architecture_service.build_architecture_package

        def broken_build(design_package, blueprint_content):
            package = original(design_package, blueprint_content)
            corrupted = dataclasses.replace(package.entities[0], fields=("broken",))
            return dataclasses.replace(package, entities=(corrupted,) + package.entities[1:])

        architecture_service.build_architecture_package = broken_build
        try:
            self._run_architecture(project_id, expect=422)
        finally:
            architecture_service.build_architecture_package = original

        with vo_schema.s2_database() as db:
            state = vo_schema.load_project(db, project_id)["state"]
        self.assertEqual(state, vo_schema.ProjectState.REWORK_REQUIRED.value)

        # The bounce is repairable: re-running with the real generator passes.
        self._run_architecture(project_id, expect=200)


if __name__ == "__main__":
    unittest.main()
