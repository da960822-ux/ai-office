"""Acceptance tests for VibeOffice slice S1 (Intake -> Blueprint -> approval).

The router is mounted on a throwaway ``FastAPI()`` app on purpose: ``main.py`` is
owned by another session and must not gain an ``include_router`` line yet, so S1
has to be verifiable without touching it.

Every test here maps to a promise in docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md
section 7 (S1) or reference/product-context/09_ACCEPTANCE_CRITERIA.md:

1. three different short ideas each yield a schema-valid blueprint
2. at most three questions, each with all three answer options
3. Must is 3~5 and Later/Out are non-empty
4. "모름" promotes the recommendation, "나중에 결정" survives as an openQuestion
5. an unapproved blueprint cannot be handed to the next department
6. the workspace file exists and its sha256 matches the DB row
7. inference metadata never leaks into the blueprint body
   (``additionalProperties: false`` regression guard)
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import intake as intake_rules
from apps.api.vibeoffice import schema as vo_schema
from apps.api.vibeoffice.models import BlueprintSchemaError, validate_blueprint
from apps.api.vibeoffice.routes import router

#: Three unrelated short Korean ideas (30~40 characters), matching the S1
#: success condition "30자 입력 1건" but repeated across domains so a single
#: hand-tuned keyword path cannot make the suite pass.
IDEA_CAFE = "동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱"
IDEA_READING = "읽은 책과 감상을 기록하고 월별 통계를 보여주는 앱"
IDEA_EXPENSE = "사내 경비 영수증을 올려 정산 승인을 받는 웹"

ALL_IDEAS = (IDEA_CAFE, IDEA_READING, IDEA_EXPENSE)


def _collect_dicts(node, found=None):
    """Every dict inside a nested JSON structure, for leak scanning."""
    found = [] if found is None else found
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            _collect_dicts(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_dicts(item, found)
    return found


class VibeOfficeIntakeTests(unittest.TestCase):
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

    def _create(self, idea: str, *, start_card_id: str | None = None, label: str = "ws") -> dict:
        response = self.client.post(
            "/api/vibe/projects",
            json={"idea": idea, "start_card_id": start_card_id, "workspace_path": str(self._workspace(label))},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _intake(self, project_id: str) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/intake", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _generate(self, project_id: str) -> dict:
        response = self.client.post(f"/api/vibe/projects/{project_id}/blueprint/generate")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _start(self, idea: str, *, start_card_id: str | None = None, label: str = "ws") -> tuple[str, dict]:
        project = self._create(idea, start_card_id=start_card_id, label=label)
        intake = self._intake(project["id"])
        return project["id"], intake

    # ------------------------------------------------------------------- tests
    def test_start_cards_offer_at_least_four_entry_points(self):
        """P0-01: the first screen is never an empty chat box."""
        response = self.client.get("/api/vibe/start-cards")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreaterEqual(len(payload["cards"]), 4)
        self.assertEqual(payload["max_questions"], intake_rules.MAX_QUESTIONS)
        for card in payload["cards"]:
            self.assertTrue(card["label"])
            self.assertTrue(card["example"], f"card {card['id']} needs a concrete example")

    def test_three_short_ideas_produce_schema_valid_blueprints(self):
        """S1 success condition, run for three unrelated domains."""
        for index, idea in enumerate(ALL_IDEAS):
            with self.subTest(idea=idea):
                self.assertLessEqual(len(idea), 40, "fixture ideas stay short on purpose")
                project_id, _ = self._start(idea, label=f"ws{index}")
                generated = self._generate(project_id)
                content = generated["blueprint"]
                # Validated by the service already; re-validating here catches any
                # future drift between the service and the schema file.
                validate_blueprint(content)
                self.assertEqual(generated["state"], vo_schema.ProjectState.PLANNING_REVIEW.value)
                self.assertTrue(content["targetUsers"])
                self.assertIn(
                    content["projectType"],
                    ["landing_demo", "crud_web", "dashboard", "ai_demo", "portfolio", "existing_project", "other"],
                )
                self.assertGreaterEqual(len(content["risks"]), 1)

    def test_questions_are_capped_at_three_and_always_offer_three_options(self):
        """Guide invariant: <=3 questions, each with 추천값/모름/나중에 결정."""
        expected_actions = {
            intake_rules.ACTION_ACCEPT,
            intake_rules.ACTION_DONT_KNOW,
            intake_rules.ACTION_DECIDE_LATER,
        }
        for index, idea in enumerate(ALL_IDEAS):
            with self.subTest(idea=idea):
                project_id, intake = self._start(idea, label=f"q{index}")
                self.assertLessEqual(intake["question_count"], intake_rules.MAX_QUESTIONS)
                response = self.client.get(f"/api/vibe/projects/{project_id}/intake/questions")
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertLessEqual(len(payload["questions"]), intake_rules.MAX_QUESTIONS)
                self.assertEqual(payload["max_questions"], intake_rules.MAX_QUESTIONS)
                for question in payload["questions"]:
                    self.assertTrue(question["text"])
                    actions = {option["action"] for option in question["options"]}
                    self.assertEqual(actions, expected_actions, question)
                    accept = next(
                        option
                        for option in question["options"]
                        if option["action"] == intake_rules.ACTION_ACCEPT
                    )
                    self.assertIn("추천값으로 진행", accept["label"])
                    self.assertEqual(accept["value"], question["recommendedValue"])
                    labels = {option["label"] for option in question["options"]}
                    self.assertIn("모름", labels)
                    self.assertIn("나중에 결정", labels)

    def test_start_card_selection_reduces_the_number_of_questions(self):
        """Card presets raise confidence, which is how cards cut question count."""
        _, plain = self._start(IDEA_EXPENSE, label="plain")
        _, carded = self._start(IDEA_EXPENSE, start_card_id="team_project", label="carded")
        self.assertLess(carded["question_count"], plain["question_count"])

    def test_scope_keeps_must_between_three_and_five_with_later_and_out(self):
        """Gate B. The schema allows 1 Must; our gate does not."""
        for index, idea in enumerate(ALL_IDEAS):
            with self.subTest(idea=idea):
                project_id, _ = self._start(idea, label=f"scope{index}")
                scope = self._generate(project_id)["blueprint"]["scope"]
                self.assertGreaterEqual(len(scope["must"]), blueprint_service.MUST_MIN)
                self.assertLessEqual(len(scope["must"]), blueprint_service.MUST_MAX)
                self.assertTrue(scope["later"])
                self.assertTrue(scope["out"])
                for bucket in ("must", "should", "later", "out"):
                    for feature in scope[bucket]:
                        self.assertRegex(feature["id"], r"^F-[0-9]{3}$")
                ids = [feature["id"] for bucket in ("must", "should", "later", "out") for feature in scope[bucket]]
                self.assertEqual(len(ids), len(set(ids)), "feature ids must be unique")

    def test_scope_gate_rejects_a_single_must_feature(self):
        """Direct gate check: schema-valid but product-invalid scope is refused."""
        project_id, _ = self._start(IDEA_CAFE, label="gate")
        content = self._generate(project_id)["blueprint"]
        trimmed = json.loads(json.dumps(content))
        trimmed["scope"]["must"] = trimmed["scope"]["must"][:1]
        validate_blueprint(trimmed)  # the JSON Schema is happy with minItems: 1
        with self.assertRaises(blueprint_service.ScopeGateError):
            blueprint_service.assert_scope_gate(trimmed)

    def test_dont_know_confirms_recommendation_and_decide_later_stays_open(self):
        """09: the user is never blocked for not knowing; deferrals stay visible."""
        project_id, intake = self._start(IDEA_CAFE, label="answers")
        questions = intake["questions"]
        self.assertGreaterEqual(len(questions), 2, "fixture should leave at least two open questions")
        unknown_question, deferred_question = questions[0], questions[1]

        response = self.client.post(
            f"/api/vibe/projects/{project_id}/intake/answers",
            json={
                "answers": [
                    {"question_id": unknown_question["id"], "action": intake_rules.ACTION_DONT_KNOW},
                    {"question_id": deferred_question["id"], "action": intake_rules.ACTION_DECIDE_LATER},
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        estimates = response.json()["estimates"]

        promoted = estimates[unknown_question["field"]]
        self.assertEqual(promoted["status"], intake_rules.STATUS_ANSWERED)
        self.assertEqual(promoted["value"], unknown_question["recommendedValue"])
        self.assertGreaterEqual(promoted["confidence"], intake_rules.CONFIDENCE_THRESHOLD)

        deferred = estimates[deferred_question["field"]]
        self.assertEqual(deferred["status"], intake_rules.STATUS_DEFERRED)

        # Answered questions are not asked again.
        remaining = self.client.get(f"/api/vibe/projects/{project_id}/intake/questions").json()["questions"]
        remaining_ids = {question["id"] for question in remaining}
        self.assertNotIn(unknown_question["id"], remaining_ids)
        self.assertNotIn(deferred_question["id"], remaining_ids)

        content = self._generate(project_id)["blueprint"]
        deferred_label = intake_rules.FIELD_LABELS[deferred_question["field"]]
        promoted_label = intake_rules.FIELD_LABELS[unknown_question["field"]]
        self.assertTrue(
            any(deferred_label in entry for entry in content["openQuestions"]),
            content["openQuestions"],
        )
        self.assertFalse(
            any(promoted_label in entry for entry in content["openQuestions"]),
            "a confirmed recommendation must not remain an open question",
        )
        self.assertTrue(
            any("모름" in line and promoted_label in line for line in content["assumptions"]),
            content["assumptions"],
        )

    def test_handoff_is_refused_before_approval_and_allowed_after(self):
        """Guide section 11: no unapproved draft reaches the next department."""
        project_id, _ = self._start(IDEA_READING, label="handoff")

        with self.assertRaises(blueprint_service.HandoffRejected) as before_generate:
            blueprint_service.approved_blueprint_for_handoff(project_id)
        self.assertIn("생성", before_generate.exception.reason)

        self._generate(project_id)
        with self.assertRaises(blueprint_service.HandoffRejected) as before_approval:
            blueprint_service.approved_blueprint_for_handoff(project_id)
        self.assertIn("승인", before_approval.exception.reason)
        self.assertIn(vo_schema.ProjectState.PLANNING_REVIEW.value, before_approval.exception.reason)

        approved = self.client.post(f"/api/vibe/projects/{project_id}/blueprint/approve")
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["state"], vo_schema.ProjectState.PLANNING_APPROVED.value)
        self.assertTrue(approved.json()["approved_at"])

        handoff = blueprint_service.approved_blueprint_for_handoff(project_id)
        self.assertEqual(handoff["project_id"], project_id)
        self.assertTrue(handoff["approved_at"])
        self.assertEqual(handoff["sha256"], approved.json()["sha256"])

        # Approving twice is an illegal transition, not an idempotent no-op:
        # PLANNING_APPROVED is terminal in S1.
        again = self.client.post(f"/api/vibe/projects/{project_id}/blueprint/approve")
        self.assertEqual(again.status_code, 409, again.text)

    def test_handoff_detects_a_file_edited_after_approval(self):
        """The file is the artifact; the recorded hash is the proof."""
        project_id, _ = self._start(IDEA_CAFE, label="tamper")
        self._generate(project_id)
        self.assertEqual(
            self.client.post(f"/api/vibe/projects/{project_id}/blueprint/approve").status_code, 200
        )
        with vo_schema.vibeoffice_database() as db:
            workspace = Path(vo_schema.load_project(db, project_id)["workspace_path"])
        path = workspace / vo_schema.BLUEPRINT_DIRNAME / vo_schema.BLUEPRINT_FILENAME
        content = json.loads(path.read_text(encoding="utf-8"))
        content["projectName"] = "손으로 바꾼 이름"
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(blueprint_service.HandoffRejected) as rejected:
            blueprint_service.approved_blueprint_for_handoff(project_id)
        self.assertIn("변경", rejected.exception.reason)

    def test_blueprint_file_is_written_and_hash_matches_the_database(self):
        """DB record + workspace file are kept together, hash recorded."""
        project_id, _ = self._start(IDEA_EXPENSE, label="file")
        generated = self._generate(project_id)
        self.assertEqual(
            generated["path"],
            f"{vo_schema.BLUEPRINT_DIRNAME}/{vo_schema.BLUEPRINT_FILENAME}",
        )
        with vo_schema.vibeoffice_database() as db:
            project = vo_schema.load_project(db, project_id)
            row = db.execute(
                "SELECT * FROM vo_blueprints WHERE project_id = ? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        path = Path(project["workspace_path"]) / generated["path"]
        self.assertTrue(path.is_file(), path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest, row["sha256"])
        self.assertEqual(digest, generated["sha256"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), generated["blueprint"])
        # The stored path is relative: exported artifacts must not leak local
        # absolute paths (guide section 11).
        self.assertFalse(Path(row["path"]).is_absolute())

    def test_inference_metadata_never_leaks_into_the_blueprint_body(self):
        """``additionalProperties: false`` regression guard.

        InferredValue metadata lives in ``vo_blueprints.inference_json`` only. If
        somebody "helpfully" attaches confidence/status/source to the body, the
        schema validator must reject it.
        """
        project_id, _ = self._start(IDEA_CAFE, label="leak")
        content = self._generate(project_id)["blueprint"]

        for node in _collect_dicts(content):
            self.assertNotIn("status", node)
            self.assertNotIn("source", node)
        for name, value in content["confidence"].items():
            self.assertIsInstance(value, (int, float), name)
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)

        with self.assertRaises(BlueprintSchemaError):
            leaked = json.loads(json.dumps(content))
            leaked["inference"] = {"projectType": {"value": "crud_web", "confidence": 0.8}}
            validate_blueprint(leaked)

        with self.assertRaises(BlueprintSchemaError):
            leaked = json.loads(json.dumps(content))
            leaked["scope"]["must"][0]["confidence"] = 0.8
            validate_blueprint(leaked)

        with self.assertRaises(BlueprintSchemaError):
            leaked = json.loads(json.dumps(content))
            leaked["confidence"]["projectType"] = {"value": "crud_web", "status": "inferred"}
            validate_blueprint(leaked)

        # The metadata does exist - just not in the body.
        stored = self.client.get(f"/api/vibe/projects/{project_id}/blueprint").json()
        for name, estimate in stored["inference"]["values"].items():
            self.assertIn(estimate["status"], intake_rules.ESTIMATE_STATUSES, name)
            self.assertTrue(estimate["source"], name)

    def test_feature_id_pattern_is_enforced_by_the_schema_file(self):
        """``^F-[0-9]{3}$`` comes from the schema file, not from our code."""
        project_id, _ = self._start(IDEA_READING, label="ids")
        content = self._generate(project_id)["blueprint"]
        broken = json.loads(json.dumps(content))
        broken["scope"]["must"][0]["id"] = "F-1"
        with self.assertRaises(BlueprintSchemaError) as error:
            validate_blueprint(broken)
        self.assertIn("pattern", str(error.exception))

    def test_unknown_project_is_404_and_generate_before_intake_is_409(self):
        response = self.client.get("/api/vibe/projects/VOP-999/blueprint")
        self.assertEqual(response.status_code, 404, response.text)
        response = self.client.post("/api/vibe/projects/VOP-999/intake", json={})
        self.assertEqual(response.status_code, 404, response.text)

        project = self._create(IDEA_CAFE, label="early")
        response = self.client.post(f"/api/vibe/projects/{project['id']}/blueprint/generate")
        self.assertEqual(response.status_code, 409, response.text)
        response = self.client.get(f"/api/vibe/projects/{project['id']}/blueprint")
        self.assertEqual(response.status_code, 404, response.text)

    def test_rejects_empty_idea_and_unknown_start_card(self):
        response = self.client.post("/api/vibe/projects", json={"idea": "짧"})
        self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(
            "/api/vibe/projects", json={"idea": IDEA_CAFE, "start_card_id": "nope"}
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_answer_with_an_unknown_action_or_question_is_422(self):
        project_id, intake = self._start(IDEA_CAFE, label="badanswer")
        response = self.client.post(
            f"/api/vibe/projects/{project_id}/intake/answers",
            json={"answers": [{"question_id": "Q99-nope", "action": intake_rules.ACTION_DONT_KNOW}]},
        )
        self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(
            f"/api/vibe/projects/{project_id}/intake/answers",
            json={"answers": [{"question_id": intake["questions"][0]["id"], "action": "make_it_up"}]},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_state_machine_refuses_undefined_state_strings(self):
        """No free-form state string may reach the DB."""
        with self.assertRaises(ValueError):
            vo_schema.coerce_state("PLANNING_DONE_MAYBE")
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_s1_transition(
                vo_schema.ProjectState.DRAFT, vo_schema.ProjectState.PLANNING_APPROVED
            )
        with self.assertRaises(vo_schema.StateTransitionError):
            vo_schema.require_s1_transition(vo_schema.ProjectState.DRAFT, vo_schema.ProjectState.DESIGN)

    def test_schema_tables_are_created_idempotently(self):
        with vo_schema.vibeoffice_database() as db:
            vo_schema.init_vibeoffice_schema(db)
            vo_schema.init_vibeoffice_schema(db)
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'vo_%'")
            }
        self.assertEqual(tables, {"vo_projects", "vo_blueprints"})

    def test_intake_is_repeatable_and_deterministic(self):
        """No model call: the same idea always yields the same estimates."""
        first_id, first = self._start(IDEA_CAFE, label="det1")
        second_id, second = self._start(IDEA_CAFE, label="det2")
        self.assertEqual(first["estimates"], second["estimates"])
        again = self._intake(first_id)
        self.assertEqual(first["estimates"], again["estimates"])
        self.assertEqual(
            self._generate(first_id)["blueprint"], self._generate(second_id)["blueprint"]
        )


if __name__ == "__main__":
    unittest.main()
