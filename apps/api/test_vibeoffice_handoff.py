"""Acceptance tests for VibeOffice slice S2 (planning approval -> design package).

Structure follows ``test_vibeoffice_intake.py``: the router is mounted on a
throwaway ``FastAPI()`` app and ``main.DB_PATH`` is repointed at a temp file, so
no test touches the real database or the repository working tree.

Every test maps to a promise in docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md section 7
(S2), reference/product-context/05A_DEPARTMENT_HANDOFF_CONTRACTS.md sections 3/9/10
or 09A_ARTIFACT_QUALITY_GATES.md Gate C:

1. an unapproved draft cannot be handed over
2. the envelope records the *approved* blueprint version
3. the envelope validates against department-handoff.schema.json, is written to
   ``.vibeoffice/handoffs/planning-to-design.json`` and its sha256 matches the DB
4. each of the five 05A section 3 rejection conditions produces a ``rejected``
   handoff with a Korean reason
5. Gate C passes on a generated package and blocks a deliberately broken one
6. a blueprint revision marks the right artifacts stale - and the set differs by
   kind of change
7. a revision supersedes the live handoff and the successor points back at it
8. no undefined handoff status string can reach the DB, and the S1 transition
   table still behaves exactly as S1 asserted
"""

import dataclasses
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.vibeoffice import artifacts as artifact_store
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import design as design_service
from apps.api.vibeoffice import handoff as handoff_service
from apps.api.vibeoffice import intake as intake_rules
from apps.api.vibeoffice import schema as vo_schema
from apps.api.vibeoffice.models import HandoffSchemaError, validate_handoff
from apps.api.vibeoffice.routes import router

IDEA_CAFE = "동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱"
IDEA_READING = "읽은 책과 감상을 기록하고 월별 통계를 보여주는 앱"


class VibeOfficeHandoffTests(unittest.TestCase):
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

    def _project(self, idea: str = IDEA_CAFE, *, label: str = "ws") -> str:
        response = self.client.post(
            "/api/vibe/projects",
            json={"idea": idea, "workspace_path": str(self._workspace(label))},
        )
        self.assertEqual(response.status_code, 201, response.text)
        project_id = response.json()["id"]
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/intake", json={}).status_code, 200
        )
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/blueprint/generate").status_code, 200
        )
        return project_id

    def _approved(self, idea: str = IDEA_CAFE, *, label: str = "ws") -> str:
        project_id = self._project(idea, label=label)
        self._approve_blueprint(project_id)
        return project_id

    def _approve_blueprint(self, project_id: str) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/blueprint/approve")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _create_handoff(self, project_id: str, *, expect: int = 201) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/handoffs")
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _approve_handoff(self, project_id: str, handoff_id: str, *, expect: int = 200) -> dict:
        response = self.client.post(
            f"/api/vibe/projects/{project_id}/handoffs/{handoff_id}/approve", json={}
        )
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _run_design(self, project_id: str, *, expect: int = 200) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/departments/design/run")
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def _blueprint_content(self, project_id: str) -> dict:
        return self.client.get(f"/api/vibe/projects/{project_id}/blueprint").json()["blueprint"]

    def _rewrite_blueprint(self, project_id: str, patch: dict) -> dict:
        """Patch the approved blueprint body in DB *and* file, keeping sha256 in sync.

        Needed because several 05A rejection conditions are only reachable with a
        body that is schema- and Gate-B-valid but product-invalid; going through
        ``generate`` cannot produce one on purpose.
        """
        with vo_schema.s2_database() as db:
            project = vo_schema.load_project(db, project_id)
            row = db.execute(
                "SELECT * FROM vo_blueprints WHERE project_id = ? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            content = json.loads(row["content_json"])
            content.update(patch)
            path = Path(project["workspace_path"]) / row["path"]
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            db.execute(
                "UPDATE vo_blueprints SET content_json = ?, sha256 = ? WHERE id = ?",
                (json.dumps(content, ensure_ascii=False), digest, row["id"]),
            )
        return content

    def _package(self, idea: str = IDEA_CAFE, label: str = "pkg") -> design_service.DesignPackage:
        project_id = self._approved(idea, label=label)
        return design_service.build_design_package(self._blueprint_content(project_id))

    # ------------------------------------------------------- 1. approval gating
    def test_unapproved_draft_cannot_be_handed_to_design(self):
        """Guide section 11 / 05A section 1: no draft crosses a department line."""
        project_id = self._project(label="draft")
        with vo_schema.s2_database() as db:
            self.assertEqual(
                vo_schema.load_project(db, project_id)["state"],
                vo_schema.ProjectState.PLANNING_REVIEW.value,
            )
        response = self.client.post(f"/api/vibe/projects/{project_id}/handoffs")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("승인", response.json()["detail"])
        # Nothing was written and no handoff row exists.
        self.assertEqual(self.client.get(f"/api/vibe/projects/{project_id}/handoffs").json()["handoffs"], [])

    def test_design_run_is_refused_until_the_handoff_is_approved(self):
        project_id = self._approved(label="rundeny")
        self._run_design(project_id, expect=409)
        handoff = self._create_handoff(project_id)
        self.assertEqual(handoff["status"], vo_schema.HandoffStatus.READY_FOR_REVIEW.value)
        self._run_design(project_id, expect=409)
        self._approve_handoff(project_id, handoff["id"])
        self._run_design(project_id)

    # ------------------------------------------------- 2. approved input version
    def test_envelope_records_the_approved_blueprint_version(self):
        project_id = self._approved(label="version")
        approved = self.client.get(f"/api/vibe/projects/{project_id}/blueprint").json()
        handoff = self._create_handoff(project_id)
        envelope = handoff["envelope"]
        self.assertEqual(
            envelope["inputVersions"][handoff_service.INPUT_PROJECT_BLUEPRINT], approved["version"]
        )
        self.assertTrue(approved["approved_at"])
        self.assertEqual(envelope["fromDepartment"], "planning")
        self.assertEqual(envelope["toDepartment"], "design")

    # --------------------------------------------- 3. envelope schema + file/hash
    def test_envelope_validates_against_the_schema_file_and_is_mirrored_on_disk(self):
        project_id = self._approved(label="envelope")
        handoff = self._create_handoff(project_id)
        envelope = handoff["envelope"]
        # Validated by the service already; re-validating catches future drift
        # between the service and the schema file.
        validate_handoff(envelope)

        self.assertEqual(
            handoff["path"],
            f"{vo_schema.HANDOFF_DIRNAME}/{vo_schema.PLANNING_TO_DESIGN_FILENAME}",
        )
        self.assertFalse(Path(handoff["path"]).is_absolute())
        with vo_schema.s2_database() as db:
            project = vo_schema.load_project(db, project_id)
            row = db.execute("SELECT * FROM vo_handoffs WHERE id = ?", (handoff["id"],)).fetchone()
        path = Path(project["workspace_path"]) / handoff["path"]
        self.assertTrue(path.is_file(), path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest, row["sha256"])
        self.assertEqual(digest, handoff["sha256"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), envelope)

        # An extra key is refused: additionalProperties is false in the schema.
        with self.assertRaises(HandoffSchemaError):
            validate_handoff({**envelope, "rejectionReasons": ["새 키"]})
        with self.assertRaises(HandoffSchemaError):
            validate_handoff({**envelope, "status": "almost_approved"})

    def test_envelope_content_is_derived_from_the_blueprint(self):
        """Constraints/acceptance/openDecisions must reflect *this* project."""
        project_id = self._approved(label="derived")
        content = self._blueprint_content(project_id)
        handoff = self._create_handoff(project_id)
        envelope = handoff["envelope"]

        self.assertIn(f"핵심 화면 최대 {vo_schema.GATE_C_MAX_SCREENS}개", envelope["constraints"])
        self.assertIn("loading/empty/error", envelope["constraints"])
        for feature in content["scope"]["out"]:
            self.assertIn(f"{feature['name']} 제외", envelope["constraints"])
        for feature in content["scope"]["must"]:
            self.assertTrue(
                any(feature["id"] in criterion for criterion in envelope["acceptanceCriteria"]),
                envelope["acceptanceCriteria"],
            )
        self.assertEqual(envelope["openDecisions"], content["openQuestions"])
        self.assertIn("USER_FLOWS.md", envelope["requiredOutputs"])
        self.assertIn("SCREEN_SPEC.md", envelope["requiredOutputs"])
        self.assertIn("DESIGN_SYSTEM.md", envelope["requiredOutputs"])
        self.assertEqual(handoff["summary"]["primaryUser"], content["targetUsers"][0])

    # -------------------------------------------- 4. rejection conditions (05A §3)
    def test_rejection_condition_must_over_five_without_rationale(self):
        content = self._blueprint_content(self._approved(label="rej1"))
        must = content["scope"]["must"]
        while len(must) < 6:
            extra = json.loads(json.dumps(must[0]))
            extra["id"] = f"F-9{len(must):02d}"
            extra["reason"] = "-"
            must.append(extra)
        reasons = handoff_service.evaluate_rejection_reasons(content)
        self.assertTrue(any("Must" in reason and "근거" in reason for reason in reasons), reasons)

    def test_rejection_condition_empty_target_users(self):
        content = self._blueprint_content(self._approved(label="rej2"))
        content["targetUsers"] = []
        reasons = handoff_service.evaluate_rejection_reasons(content)
        self.assertTrue(any("대상 사용자" in reason for reason in reasons), reasons)

    def test_rejection_condition_success_moment_is_not_observable(self):
        content = self._blueprint_content(self._approved(label="rej3"))
        content["successMoment"] = "사용자가 전반적으로 만족스러운 기분을 느끼는 상태"
        reasons = handoff_service.evaluate_rejection_reasons(content)
        self.assertTrue(any("성공 장면" in reason for reason in reasons), reasons)

    def test_rejection_condition_conflicting_target_users_rejects_the_handoff(self):
        project_id = self._approved(label="rej4")
        self._rewrite_blueprint(
            project_id, {"targetUsers": ["동네 카페 사장", "혼자 쓰는 개인 사용자"]}
        )
        handoff = self._create_handoff(project_id)
        self.assertEqual(handoff["status"], vo_schema.HandoffStatus.REJECTED.value)
        self.assertTrue(any("충돌" in reason for reason in handoff["rejection_reasons"]))
        self.assertEqual(handoff["project_state"], vo_schema.ProjectState.HANDOFF_REJECTED.value)
        # A refused envelope cannot be approved, and design cannot start.
        self._approve_handoff(project_id, handoff["id"], expect=409)
        self._run_design(project_id, expect=409)

    def test_rejection_condition_out_feature_back_in_must_rejects_the_handoff(self):
        project_id = self._approved(label="rej5")
        content = self._blueprint_content(project_id)
        out_name = content["scope"]["out"][0]["name"]
        scope = json.loads(json.dumps(content["scope"]))
        scope["must"][0]["name"] = out_name
        self._rewrite_blueprint(project_id, {"scope": scope})
        handoff = self._create_handoff(project_id)
        self.assertEqual(handoff["status"], vo_schema.HandoffStatus.REJECTED.value)
        self.assertTrue(
            any(out_name in reason for reason in handoff["rejection_reasons"]),
            handoff["rejection_reasons"],
        )

    def test_rejection_condition_structural_open_decision_rejects_the_handoff(self):
        project_id = self._approved(label="rej6")
        self._rewrite_blueprint(
            project_id,
            {
                "openQuestions": [
                    "데이터 저장 - 데이터를 어디에 저장할까요? (사용자가 '나중에 결정'을 선택함)"
                ]
            },
        )
        handoff = self._create_handoff(project_id)
        self.assertEqual(handoff["status"], vo_schema.HandoffStatus.REJECTED.value)
        self.assertTrue(
            any("핵심 화면 구조" in reason for reason in handoff["rejection_reasons"]),
            handoff["rejection_reasons"],
        )

    def test_a_clean_blueprint_is_not_rejected(self):
        """Guard against over-eager rejection rules blocking the happy path."""
        for index, idea in enumerate((IDEA_CAFE, IDEA_READING)):
            with self.subTest(idea=idea):
                content = self._blueprint_content(self._approved(idea, label=f"clean{index}"))
                self.assertEqual(handoff_service.evaluate_rejection_reasons(content), [])

    # -------------------------------------------------------------- 5. Gate C
    def test_generated_design_package_satisfies_gate_c(self):
        project_id = self._approved(label="gatec")
        content = self._blueprint_content(project_id)
        handoff = self._create_handoff(project_id)
        self._approve_handoff(project_id, handoff["id"])
        result = self._run_design(project_id)

        screens = result["screens"]
        self.assertGreaterEqual(len(screens), vo_schema.GATE_C_MIN_SCREENS)
        self.assertLessEqual(len(screens), vo_schema.GATE_C_MAX_SCREENS)
        for screen in screens:
            self.assertRegex(screen["id"], r"^SCR-[0-9]{3}$")
            self.assertTrue(screen["cta"]["label"] and screen["cta"]["action"])
            self.assertTrue(screen["next"] or screen["exit"], f"{screen['id']} is a dead-end")
            if screen["dataDriven"]:
                for state in ("loading", "empty", "error"):
                    self.assertTrue(screen["states"][state], (screen["id"], state))

        linked = {feature for screen in screens for feature in screen["features"]}
        flow_features = {flow["featureId"] for flow in result["flows"]}
        for feature in content["scope"]["must"]:
            self.assertIn(feature["id"], linked)
            self.assertIn(feature["id"], flow_features)

        self.assertEqual(result["state"], vo_schema.ProjectState.DESIGN_REVIEW.value)

    def test_gate_c_blocks_an_unlinked_must_feature(self):
        package = self._package(label="gate_unlinked")
        broken = dataclasses.replace(
            package,
            must_features=package.must_features
            + ({"id": "F-900", "name": "연결되지 않은 기능"},),
        )
        with self.assertRaises(design_service.GateCError) as error:
            design_service.assert_gate_c(broken)
        self.assertTrue(any("F-900" in reason for reason in error.exception.reasons))

    def test_gate_c_blocks_a_dead_end_screen(self):
        package = self._package(label="gate_deadend")
        screens = list(package.screens)
        screens[-1] = dataclasses.replace(screens[-1], next_screens=(), exit_state=None)
        with self.assertRaises(design_service.GateCError) as error:
            design_service.assert_gate_c(dataclasses.replace(package, screens=tuple(screens)))
        self.assertTrue(any("dead-end" in reason for reason in error.exception.reasons))

    def test_gate_c_blocks_a_data_screen_without_three_states(self):
        package = self._package(label="gate_states")
        screens = list(package.screens)
        data_screen = next(index for index, screen in enumerate(screens) if screen.data_driven)
        states = dict(screens[data_screen].states)
        states["empty"] = ""
        screens[data_screen] = dataclasses.replace(screens[data_screen], states=states)
        with self.assertRaises(design_service.GateCError) as error:
            design_service.assert_gate_c(dataclasses.replace(package, screens=tuple(screens)))
        self.assertTrue(any("empty" in reason for reason in error.exception.reasons))

    def test_gate_c_blocks_a_screen_count_outside_three_to_seven(self):
        package = self._package(label="gate_count")
        with self.assertRaises(design_service.GateCError) as error:
            design_service.assert_gate_c(dataclasses.replace(package, screens=package.screens[:2]))
        self.assertTrue(
            any(str(vo_schema.GATE_C_MAX_SCREENS) in reason for reason in error.exception.reasons),
            error.exception.reasons,
        )

    # ------------------------------------------------- design package artifacts
    def test_design_package_files_carry_headers_and_matching_hashes(self):
        project_id = self._approved(label="artifacts")
        handoff = self._create_handoff(project_id)
        self._approve_handoff(project_id, handoff["id"])
        self._run_design(project_id)

        listing = self.client.get(f"/api/vibe/projects/{project_id}/artifacts").json()
        self.assertEqual(
            {artifact["type"] for artifact in listing["artifacts"]},
            set(artifact_store.DESIGN_PACKAGE_TYPES),
        )
        self.assertEqual(listing["stale_count"], 0)

        with vo_schema.s2_database() as db:
            workspace = Path(vo_schema.load_project(db, project_id)["workspace_path"])
        for artifact_type in artifact_store.DESIGN_PACKAGE_TYPES:
            with self.subTest(artifact=artifact_type):
                detail = self.client.get(
                    f"/api/vibe/projects/{project_id}/artifacts/{artifact_type}"
                )
                self.assertEqual(detail.status_code, 200, detail.text)
                payload = detail.json()
                self.assertEqual(payload["version"], 1)
                self.assertEqual(
                    payload["path"],
                    f"{vo_schema.DOCS_DIRNAME}/{artifact_store.ARTIFACT_FILENAMES[artifact_type]}",
                )
                path = workspace / payload["path"]
                self.assertTrue(path.is_file(), path)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), payload["sha256"])
                body = path.read_text(encoding="utf-8")
                self.assertTrue(body.startswith("---\n"), body[:40])
                for key in ("artifact_id:", "version:", "status:", "source_blueprint_version:", "depends_on:"):
                    self.assertIn(key, body)
                self.assertIn("project-blueprint@1", body)
                self.assertEqual(payload["source_blueprint_version"], 1)

        screen_spec = (workspace / vo_schema.DOCS_DIRNAME / "SCREEN_SPEC.md").read_text(encoding="utf-8")
        self.assertIn("SCR-001", screen_spec)
        self.assertIn("loading:", screen_spec)
        self.assertIn("empty:", screen_spec)
        self.assertIn("error:", screen_spec)
        flows = (workspace / vo_schema.DOCS_DIRNAME / "USER_FLOWS.md").read_text(encoding="utf-8")
        for section in ("주요 진입점", "Happy Path", "대체 흐름", "오류 흐름", "종료 상태"):
            self.assertIn(section, flows)

    def test_design_generation_is_deterministic(self):
        """No model call: the same blueprint always renders the same package."""
        first = self._blueprint_content(self._approved(label="det1"))
        second = self._blueprint_content(self._approved(label="det2"))
        self.assertEqual(first, second)
        self.assertEqual(
            design_service.build_design_package(first).to_dict(),
            design_service.build_design_package(second).to_dict(),
        )

    def test_unknown_project_and_unknown_artifact_type_are_404(self):
        self.assertEqual(self.client.get("/api/vibe/projects/VOP-999/handoffs").status_code, 404)
        self.assertEqual(self.client.post("/api/vibe/projects/VOP-999/handoffs").status_code, 404)
        self.assertEqual(self.client.get("/api/vibe/projects/VOP-999/artifacts").status_code, 404)
        project_id = self._approved(label="notfound")
        self.assertEqual(
            self.client.get(f"/api/vibe/projects/{project_id}/artifacts/nope").status_code, 404
        )
        self.assertEqual(
            self.client.get(
                f"/api/vibe/projects/{project_id}/artifacts/{artifact_store.ARTIFACT_USER_FLOWS}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/handoffs/HO-NOPE/approve", json={}).status_code,
            404,
        )

    # -------------------------------------------------- 5b. GET /handoffs/{id}
    def test_get_handoff_by_id_returns_the_matching_envelope(self):
        project_id = self._approved(label="get_handoff")
        created = self._create_handoff(project_id)

        response = self.client.get(f"/api/vibe/projects/{project_id}/handoffs/{created['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["id"], created["id"])
        self.assertEqual(payload["project_id"], project_id)
        self.assertEqual(payload["envelope"], created["envelope"])
        self.assertEqual(payload["sha256"], created["sha256"])

    def test_get_handoff_unknown_id_is_404(self):
        project_id = self._approved(label="get_handoff_404")
        self._create_handoff(project_id)
        response = self.client.get(f"/api/vibe/projects/{project_id}/handoffs/HO-NOPE")
        self.assertEqual(response.status_code, 404, response.text)

    def test_get_handoff_unknown_project_is_404(self):
        response = self.client.get("/api/vibe/projects/VOP-999/handoffs/HO-ANY")
        self.assertEqual(response.status_code, 404, response.text)

    # ------------------------------------------------------- 6. stale propagation
    def test_stale_impact_differs_by_kind_of_change(self):
        """Guide section 9: 최소 영향 수정. Impact sets must not collapse into one.

        The exact sets were widened after review to match what the renderers in
        ``design.py`` actually read (IA prints Must ids and ``oneLineDefinition``;
        SCREEN_SPEC's data sentences come from ``dataPersistence``).  The load
        bearing assertion is not any single set - it is that the sets stay
        *different*, which is what stops "mark everything stale" from creeping back
        in and destroying the 최소 영향 수정 rule.
        """
        self.assertEqual(
            artifact_store.stale_targets([artifact_store.CHANGE_VISUAL]),
            {
                artifact_store.ARTIFACT_DESIGN_SYSTEM,
                artifact_store.ARTIFACT_SCREEN_SPEC,
                artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE,
            },
        )
        must_targets = artifact_store.stale_targets([artifact_store.CHANGE_MUST])
        user_targets = artifact_store.stale_targets([artifact_store.CHANGE_TARGET_USERS])
        visual_targets = artifact_store.stale_targets([artifact_store.CHANGE_VISUAL])
        tech_targets = artifact_store.stale_targets([artifact_store.CHANGE_TECH_STACK])
        experience_targets = artifact_store.stale_targets([artifact_store.CHANGE_EXPERIENCE])
        self.assertNotEqual(must_targets, visual_targets)
        self.assertNotEqual(user_targets, visual_targets)
        self.assertNotEqual(must_targets, user_targets)
        self.assertNotEqual(tech_targets, must_targets)
        self.assertNotEqual(experience_targets, visual_targets)
        self.assertNotIn(artifact_store.ARTIFACT_DESIGN_SYSTEM, must_targets)
        self.assertNotIn(artifact_store.ARTIFACT_USER_FLOWS, visual_targets)
        self.assertIn(artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE, user_targets)
        # Renderer-dependency additions the review asked for.
        self.assertIn(artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE, must_targets)
        self.assertIn(artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE, visual_targets)
        self.assertIn(artifact_store.ARTIFACT_SCREEN_SPEC, tech_targets)
        # Guide section 9: 기술 스택 변경 -> Architecture·API·Data Model·Tasks. The S3
        # architecture package must be part of the tech-stack impact set now that
        # those artifacts exist, on top of the design-package members it already had.
        self.assertEqual(
            tech_targets,
            {
                artifact_store.ARTIFACT_COMPONENT_INVENTORY,
                artifact_store.ARTIFACT_SCREEN_SPEC,
                artifact_store.ARTIFACT_API_CONTRACT,
                artifact_store.ARTIFACT_DATA_MODEL,
                artifact_store.ARTIFACT_TECHNICAL_TASKS,
            },
        )
        # No impact set is the full package except the deliberate catch-all.
        for kind in (
            artifact_store.CHANGE_TARGET_USERS,
            artifact_store.CHANGE_MUST,
            artifact_store.CHANGE_VISUAL,
            artifact_store.CHANGE_TECH_STACK,
            artifact_store.CHANGE_EXPERIENCE,
        ):
            with self.subTest(kind=kind):
                self.assertNotEqual(
                    artifact_store.stale_targets([kind]),
                    set(artifact_store.DESIGN_PACKAGE_TYPES),
                )
        self.assertEqual(
            artifact_store.stale_targets([artifact_store.CHANGE_OTHER]),
            set(artifact_store.DESIGN_PACKAGE_TYPES),
        )

    def _project_with_design(self, label: str) -> str:
        project_id = self._approved(label=label)
        handoff = self._create_handoff(project_id)
        self._approve_handoff(project_id, handoff["id"])
        self._run_design(project_id)
        return project_id

    def _architecture_ready(self, idea: str = IDEA_CAFE, *, label: str) -> str:
        """Walk a project to ARCHITECTURE_REVIEW, past design approval.

        Same pattern as ``test_vibeoffice_execution_baseline.py``'s helper of the
        same name: needed here because the tech-stack stale-impact fix reaches the
        S3 architecture package, which only exists once a project has gotten this
        far.
        """
        project_id = self._project(idea, label=label)
        self._approve_blueprint(project_id)
        handoff = self._create_handoff(project_id)
        self._approve_handoff(project_id, handoff["id"])
        self._run_design(project_id)
        response = self.client.post(f"/api/vibe/projects/{project_id}/artifacts/design/approve")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/vibe/projects/{project_id}/departments/architecture/run")
        self.assertEqual(response.status_code, 200, response.text)
        return project_id

    def _stale_types(self, project_id: str) -> set[str]:
        listing = self.client.get(f"/api/vibe/projects/{project_id}/artifacts").json()
        return {artifact["type"] for artifact in listing["artifacts"] if artifact["stale"]}

    def test_visual_change_makes_design_screen_and_ia_stale(self):
        """Updated after review: IA renders ``oneLineDefinition``, a visual field."""
        project_id = self._project_with_design("stale_visual")
        result = artifact_store.revise_blueprint(project_id, {"projectName": "카페 재고 도우미"})
        self.assertEqual(result["change_kinds"], [artifact_store.CHANGE_VISUAL])
        self.assertEqual(
            self._stale_types(project_id),
            {
                artifact_store.ARTIFACT_DESIGN_SYSTEM,
                artifact_store.ARTIFACT_SCREEN_SPEC,
                artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE,
            },
        )
        # Still narrower than the whole package: USER_FLOWS and COMPONENT_INVENTORY
        # do not read any visual field.
        self.assertNotIn(artifact_store.ARTIFACT_USER_FLOWS, self._stale_types(project_id))
        self.assertNotIn(artifact_store.ARTIFACT_COMPONENT_INVENTORY, self._stale_types(project_id))
        self.assertEqual(result["project_state"], vo_schema.ProjectState.PLANNING_REVIEW.value)

    def test_must_change_makes_flow_and_screen_stale_but_not_design_system(self):
        project_id = self._project_with_design("stale_must")
        content = self._blueprint_content(project_id)
        scope = json.loads(json.dumps(content["scope"]))
        scope["must"][0]["name"] = scope["must"][0]["name"] + " (개편)"
        result = artifact_store.revise_blueprint(project_id, {"scope": scope})
        self.assertEqual(result["change_kinds"], [artifact_store.CHANGE_MUST])
        stale = self._stale_types(project_id)
        self.assertIn(artifact_store.ARTIFACT_USER_FLOWS, stale)
        self.assertIn(artifact_store.ARTIFACT_SCREEN_SPEC, stale)
        self.assertNotIn(artifact_store.ARTIFACT_DESIGN_SYSTEM, stale)

    def test_target_user_change_makes_ia_flow_and_screen_stale(self):
        project_id = self._project_with_design("stale_users")
        result = artifact_store.revise_blueprint(project_id, {"targetUsers": ["동네 빵집 사장"]})
        self.assertEqual(result["change_kinds"], [artifact_store.CHANGE_TARGET_USERS])
        self.assertEqual(
            self._stale_types(project_id),
            {
                artifact_store.ARTIFACT_INFORMATION_ARCHITECTURE,
                artifact_store.ARTIFACT_USER_FLOWS,
                artifact_store.ARTIFACT_SCREEN_SPEC,
            },
        )
        # Stale carries a Korean reason that says "repair, do not regenerate".
        listing = self.client.get(f"/api/vibe/projects/{project_id}/artifacts").json()
        reasons = [artifact["stale_reason"] for artifact in listing["artifacts"] if artifact["stale"]]
        self.assertTrue(all("대상 사용자 변경" in reason for reason in reasons), reasons)

    def test_tech_stack_revision_marks_s3_architecture_artifacts_stale(self):
        """End-to-end: a real tech-stack revision, past architecture, actually
        marks API_CONTRACT/DATA_MODEL/TECHNICAL_TASKS stale on disk/DB - not just
        the pure ``stale_targets`` classification.

        Guide section 9: "기술 스택 변경 -> Architecture·API·Data Model·Tasks".
        Regression test for the fix to ``artifacts.STALE_IMPACT[CHANGE_TECH_STACK]``.
        """
        project_id = self._architecture_ready(label="stale_tech_e2e")
        content = self._blueprint_content(project_id)
        technical = json.loads(json.dumps(content["technicalDirection"]))
        technical["frontend"] = "flutter"
        result = artifact_store.revise_blueprint(project_id, {"technicalDirection": technical})
        self.assertEqual(result["change_kinds"], [artifact_store.CHANGE_TECH_STACK])
        stale = self._stale_types(project_id)
        self.assertIn(artifact_store.ARTIFACT_API_CONTRACT, stale)
        self.assertIn(artifact_store.ARTIFACT_DATA_MODEL, stale)
        self.assertIn(artifact_store.ARTIFACT_TECHNICAL_TASKS, stale)
        # Design-package members it already had are still marked too.
        self.assertIn(artifact_store.ARTIFACT_SCREEN_SPEC, stale)
        self.assertIn(artifact_store.ARTIFACT_COMPONENT_INVENTORY, stale)
        self.assertEqual(result["project_state"], vo_schema.ProjectState.PLANNING_REVIEW.value)

    # ---------------------------------------------------------- 7. superseded
    def test_blueprint_revision_supersedes_the_live_handoff(self):
        project_id = self._approved(label="supersede")
        first = self._create_handoff(project_id)
        self._approve_handoff(project_id, first["id"])

        revision = artifact_store.revise_blueprint(project_id, {"projectName": "새 이름"})
        self.assertEqual(revision["version"], 2)
        self.assertIn(first["id"], revision["superseded_handoffs"])

        handoffs = {
            item["id"]: item
            for item in self.client.get(f"/api/vibe/projects/{project_id}/handoffs").json()["handoffs"]
        }
        self.assertEqual(handoffs[first["id"]]["status"], vo_schema.HandoffStatus.SUPERSEDED.value)

        # A superseded envelope cannot be approved again or used for design.
        self._approve_handoff(project_id, first["id"], expect=409)

        # The revision has to pass planning approval again before re-handoff.
        self.assertEqual(self.client.post(f"/api/vibe/projects/{project_id}/handoffs").status_code, 409)
        self._approve_blueprint(project_id)
        second = self._create_handoff(project_id)
        self.assertEqual(second["supersedes"], first["id"])
        self.assertEqual(second["envelope"]["supersedes"], first["id"])
        self.assertEqual(
            second["envelope"]["inputVersions"][handoff_service.INPUT_PROJECT_BLUEPRINT], 2
        )
        self.assertEqual(second["status"], vo_schema.HandoffStatus.READY_FOR_REVIEW.value)

    # -------------------------------------------------------- 8. state machines
    def test_handoff_status_machine_refuses_undefined_strings(self):
        with self.assertRaises(ValueError):
            vo_schema.coerce_handoff_status("almost_approved")
        self.assertEqual(
            {status.value for status in vo_schema.HandoffStatus},
            {
                "draft",
                "ready_for_review",
                "changes_requested",
                "approved",
                "in_progress",
                "completed",
                "rejected",
                "superseded",
            },
        )
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_handoff_transition(
                vo_schema.HandoffStatus.REJECTED, vo_schema.HandoffStatus.APPROVED
            )
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_handoff_transition(
                vo_schema.HandoffStatus.SUPERSEDED, vo_schema.HandoffStatus.IN_PROGRESS
            )
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_handoff_transition(
                vo_schema.HandoffStatus.READY_FOR_REVIEW, vo_schema.HandoffStatus.COMPLETED
            )

    def test_only_defined_handoff_statuses_reach_the_database(self):
        project_id = self._project_with_design("statuses")
        with vo_schema.s2_database() as db:
            rows = db.execute("SELECT status FROM vo_handoffs").fetchall()
        self.assertTrue(rows)
        for row in rows:
            vo_schema.coerce_handoff_status(row["status"])

    def test_s1_transition_table_is_extended_not_replaced(self):
        """S1 asserted these; S2 must not loosen them."""
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_s1_transition(
                vo_schema.ProjectState.DRAFT, vo_schema.ProjectState.DESIGN
            )
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_s1_transition(
                vo_schema.ProjectState.DRAFT, vo_schema.ProjectState.PLANNING_APPROVED
            )
        # The merged machine still refuses the same jumps...
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_transition(
                vo_schema.ProjectState.DRAFT, vo_schema.ProjectState.DESIGN
            )
        # ...and PLANNING_APPROVED stays non-idempotent (approving twice is 409).
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_transition(
                vo_schema.ProjectState.PLANNING_APPROVED, vo_schema.ProjectState.PLANNING_APPROVED
            )
        # ...but S2 may now move past it.
        self.assertEqual(
            vo_schema.require_transition(
                vo_schema.ProjectState.PLANNING_APPROVED, vo_schema.ProjectState.DESIGN
            ),
            vo_schema.ProjectState.DESIGN,
        )
        for state, targets in vo_schema.S1_TRANSITIONS.items():
            self.assertTrue(targets <= vo_schema.TRANSITIONS[state], state)

    def test_s2_tables_are_created_idempotently(self):
        with vo_schema.s2_database() as db:
            vo_schema.init_s2_schema(db)
            vo_schema.init_s2_schema(db)
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'vo_%'"
                )
            }
        self.assertEqual(
            tables,
            {"vo_projects", "vo_blueprints", "vo_handoffs", "vo_artifacts", "vo_artifact_versions"},
        )

    def test_artifact_versions_append_instead_of_overwriting(self):
        project_id = self._project_with_design("versions")
        artifact_store.revise_blueprint(project_id, {"projectName": "두 번째 이름"})
        self._approve_blueprint(project_id)
        handoff = self._create_handoff(project_id)
        self._approve_handoff(project_id, handoff["id"])
        self._run_design(project_id)
        detail = self.client.get(
            f"/api/vibe/projects/{project_id}/artifacts/{artifact_store.ARTIFACT_SCREEN_SPEC}"
        ).json()
        self.assertEqual(detail["version"], 2)
        self.assertEqual([item["version"] for item in detail["history"]], [1, 2])
        self.assertEqual(detail["source_blueprint_version"], 2)
        self.assertFalse(detail["stale"], "regenerating clears the stale flag")


    # ------------------------------------------------- S2 review regression set
    def test_two_projects_in_one_database_each_get_their_own_handoff(self):
        """Blocker regression: ``vo_handoffs.id`` is a global PK but id generation
        used to be a per-project sequence, so the second project in the same
        database collided on ``HO-PLN-DES-001`` and ``POST /handoffs`` died with an
        ``IntegrityError``. Every other test in this file uses a fresh temp DB per
        case, which hid the bug structurally - this one deliberately creates two
        projects inside the same ``setUp`` database.
        """
        project_a = self._approved(IDEA_CAFE, label="twoproj_a")
        project_b = self._approved(IDEA_READING, label="twoproj_b")

        handoff_a = self._create_handoff(project_a)
        handoff_b = self._create_handoff(project_b)

        self.assertNotEqual(handoff_a["id"], handoff_b["id"])

        handoffs_a = self.client.get(f"/api/vibe/projects/{project_a}/handoffs").json()["handoffs"]
        handoffs_b = self.client.get(f"/api/vibe/projects/{project_b}/handoffs").json()["handoffs"]
        ids_a = {item["id"] for item in handoffs_a}
        ids_b = {item["id"] for item in handoffs_b}
        self.assertIn(handoff_a["id"], ids_a)
        self.assertIn(handoff_b["id"], ids_b)
        self.assertNotIn(handoff_b["id"], ids_a)
        self.assertNotIn(handoff_a["id"], ids_b)

    def test_ordinary_single_personas_are_not_rejected_as_conflicting(self):
        """Review finding: ``_persona_groups`` used to scan every group keyword out
        of one persona string, so "1인 카페 사장" alone (매칭: 개인 사용자 + 조직
        구성원) was flagged as a conflict. A single, ordinary persona must never
        be rejected; two genuinely different personas still must be.
        """
        ordinary_personas = (
            ["1인 카페 사장"],
            ["개인 병원 담당자"],
            ["혼자 운영하는 학원 원장"],
        )
        for persona in ordinary_personas:
            with self.subTest(persona=persona):
                project_id = self._approved(label=f"persona_ok_{persona[0][:2]}")
                content = self._rewrite_blueprint(project_id, {"targetUsers": persona})
                reasons = handoff_service.evaluate_rejection_reasons(content)
                self.assertFalse(
                    any("충돌" in reason for reason in reasons),
                    (persona, reasons),
                )

        # A genuine conflict (two different personas in two different groups)
        # must still be rejected.
        conflicting_project = self._approved(label="persona_conflict")
        conflicting_content = self._rewrite_blueprint(
            conflicting_project, {"targetUsers": ["동네 카페 사장", "혼자 쓰는 개인 사용자"]}
        )
        reasons = handoff_service.evaluate_rejection_reasons(conflicting_content)
        self.assertTrue(any("충돌" in reason for reason in reasons), reasons)

    def test_success_moment_detection_tolerates_verb_inflection(self):
        """Review finding: matching whole conjugated verb forms rejected ordinary
        sentences like "알림을 받고 바로 주문한다" because the code only matched a
        fixed form, not the stem. Observable-action sentences with varied endings
        must pass; a genuinely non-observable sentence must still be rejected.
        """
        observable_sentences = (
            "알림을 받고 바로 주문한다",
            "등록한 내용을 확인하고 저장한다",
            "목록을 조회하고 원하는 항목을 선택했다",
            "예약을 신청하면 완료된다",
        )
        for sentence in observable_sentences:
            with self.subTest(sentence=sentence):
                self.assertTrue(handoff_service.names_observable_action(sentence), sentence)
                project_id = self._approved(label=f"succ_{abs(hash(sentence)) % 10000}")
                content = self._rewrite_blueprint(project_id, {"successMoment": sentence})
                reasons = handoff_service.evaluate_rejection_reasons(content)
                self.assertFalse(
                    any("성공 장면" in reason for reason in reasons), (sentence, reasons)
                )

        with self.subTest(sentence="non-observable"):
            unobservable = "전반적으로 만족스러운 기분을 느끼는 상태"
            self.assertFalse(handoff_service.names_observable_action(unobservable))
            project_id = self._approved(label="succ_bad")
            content = self._rewrite_blueprint(project_id, {"successMoment": unobservable})
            reasons = handoff_service.evaluate_rejection_reasons(content)
            self.assertTrue(any("성공 장면" in reason for reason in reasons), reasons)

    def test_gate_c_violation_bounces_the_project_and_writes_nothing(self):
        """09A Gate C / guide section 8: a Gate C violation must bounce the
        project to REWORK_REQUIRED and must not leave any Design Package file on
        disk. Patches ``design_service.build_design_package`` (the call
        ``run_design`` makes) to return a package broken with ``dataclasses.replace``
        the same way the existing pure Gate C unit tests break one.
        """
        project_id = self._approved(label="gatec_bounce")
        handoff = self._create_handoff(project_id)
        self._approve_handoff(project_id, handoff["id"])

        good_package = self._package(label="gatec_bounce_ref")
        screens = list(good_package.screens)
        broken_screens = list(screens)
        broken_screens[-1] = dataclasses.replace(
            broken_screens[-1], next_screens=(), exit_state=None
        )
        broken_package = dataclasses.replace(good_package, screens=tuple(broken_screens))

        with vo_schema.s2_database() as db:
            workspace = Path(vo_schema.load_project(db, project_id)["workspace_path"])
        docs_dir = workspace / vo_schema.DOCS_DIRNAME

        with mock.patch.object(
            design_service, "build_design_package", return_value=broken_package
        ):
            with self.assertRaises(design_service.GateCError):
                design_service.run_design(project_id)

        with vo_schema.s2_database() as db:
            project = vo_schema.load_project(db, project_id)
        self.assertEqual(project["state"], vo_schema.ProjectState.REWORK_REQUIRED.value)
        self.assertFalse(docs_dir.exists() and any(docs_dir.iterdir()), "no design artifact should exist")

        # The API route surfaces the same failure as 422 without corrupting state
        # further (the project is already bounced, run again through the route).
        with mock.patch.object(
            design_service, "build_design_package", return_value=broken_package
        ):
            response = self.client.post(f"/api/vibe/projects/{project_id}/departments/design/run")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse(docs_dir.exists() and any(docs_dir.iterdir()), "no design artifact should exist")

    def test_revise_blueprint_before_approval_leaves_files_and_hash_untouched(self):
        """Review finding: ``revise_blueprint`` used to overwrite the blueprint
        file with the new body *before* validating the state transition, so
        calling it on an unapproved (``PLANNING_REVIEW``) project left the file on
        disk out of sync with the still-old DB row and permanently 409'd the
        approval gate. The fix validates the transition first; this test asserts
        the file, its hash, and the ability to approve are all untouched after a
        rejected revision attempt.
        """
        project_id = self._project(label="revise_unapproved")
        with vo_schema.s2_database() as db:
            self.assertEqual(
                vo_schema.load_project(db, project_id)["state"],
                vo_schema.ProjectState.PLANNING_REVIEW.value,
            )
            project = vo_schema.load_project(db, project_id)
            row = db.execute(
                "SELECT * FROM vo_blueprints WHERE project_id = ? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        before_path = Path(project["workspace_path"]) / row["path"]
        before_bytes = before_path.read_bytes()
        before_sha256 = hashlib.sha256(before_bytes).hexdigest()
        self.assertEqual(before_sha256, row["sha256"])

        with self.assertRaises(vo_schema.StateTransitionError):
            artifact_store.revise_blueprint(project_id, {"projectName": "수정 시도"})

        after_bytes = before_path.read_bytes()
        after_sha256 = hashlib.sha256(after_bytes).hexdigest()
        self.assertEqual(after_bytes, before_bytes)
        self.assertEqual(after_sha256, before_sha256)
        with vo_schema.s2_database() as db:
            after_row = db.execute(
                "SELECT * FROM vo_blueprints WHERE project_id = ? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        self.assertEqual(after_row["sha256"], before_sha256)
        self.assertEqual(after_row["version"], row["version"])

        # Approval still works normally after the failed revision attempt.
        self._approve_blueprint(project_id)


if __name__ == "__main__":
    unittest.main()
