"""Blueprint build, persistence, approval and the handoff gate (slice S1).

Invariants this module owns:

* **DB record and workspace file are written together.**  The blueprint body
  lands in ``vo_blueprints.content_json`` *and* in
  ``<workspace>/.vibeoffice/project-blueprint.json``, and the file's sha256 goes
  into the row.  This mirrors how the execution layer treats evidence
  (``main.persist_deliverable``): the file is the artifact, the hash is the proof.
* **Must is 3~5 features.**  ``project-blueprint.schema.json`` only says
  ``minItems: 1`` for ``scope.must``, but the guide (section 8, Gate B) requires
  3~5.  The schema is intentionally the looser contract - it also has to accept
  hand-written blueprints - so our own gate enforces the product rule and
  ``later``/``out`` being non-empty.  Do not "simplify" this away by trusting the
  schema alone; a one-Must blueprint would pass validation and break planning.
* **No unapproved draft ever leaves planning.**  ``approved_blueprint_for_handoff``
  is the only sanctioned way for the next department to read a blueprint, and it
  re-checks state, approval timestamp, schema, scope gate and file hash.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.api.vibeoffice import intake as intake_rules
from apps.api.vibeoffice.models import Blueprint, BlueprintSchemaError, validate_blueprint
from apps.api.vibeoffice.schema import (
    BLUEPRINT_DIRNAME,
    BLUEPRINT_FILENAME,
    MODES,
    ProjectNotFound,
    ProjectState,
    StateTransitionError,
    default_workspace_root,
    load_project,
    next_project_id,
    set_project_state,
    utc_now,
    vibeoffice_database,
)

#: Gate B: Must features must be 3~5. See module docstring for why this is not
#: delegated to the JSON Schema (which allows 1..5).
MUST_MIN = 3
MUST_MAX = 5

#: S1 keeps a single working version per project. Version bumping belongs to S2
#: where an approved blueprint can be superseded through a handoff.
WORKING_VERSION = 1


class ScopeGateError(ValueError):
    """Scope gate (Gate B) violation. Routes map this to 422."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class HandoffRejected(RuntimeError):
    """The blueprint may not be handed to the next department. Routes map to 409."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class BlueprintNotFound(LookupError):
    """No generated blueprint for this project yet. Routes map this to 404."""


# --------------------------------------------------------------------------- #
# Content assembly
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FeatureDraft:
    name: str
    user_value: str
    reason: str
    complexity: str


_LATER_FEATURES = (
    _FeatureDraft(
        "팀 공유와 권한 분리",
        "여러 사람이 같은 기록을 각자 권한으로 본다",
        "1인 사용 흐름이 검증된 뒤에 붙이는 것이 안전하다",
        "medium",
    ),
    _FeatureDraft(
        "모바일 전용 화면",
        "이동 중에도 기록을 남긴다",
        "핵심 흐름을 먼저 웹에서 확정한 뒤 확장한다",
        "medium",
    ),
    _FeatureDraft(
        "외부 서비스 자동 연동",
        "다른 도구에 있는 데이터를 옮겨 적지 않는다",
        "연동 대상은 사용 패턴이 보인 뒤에 정한다",
        "high",
    ),
)

_OUT_FEATURES = (
    _FeatureDraft(
        "결제·구독 기능",
        "이번 범위에서는 제공하지 않는다",
        "수익화는 MVP 성공 장면과 직접 연결되지 않는다",
        "high",
    ),
    _FeatureDraft(
        "다국어 지원",
        "이번 범위에서는 제공하지 않는다",
        "대상 사용자가 단일 언어권이라 우선순위가 낮다",
        "medium",
    ),
    _FeatureDraft(
        "대규모 트래픽 대응",
        "이번 범위에서는 제공하지 않는다",
        "초기 사용자 수가 적어 최적화가 이르다",
        "high",
    ),
)


def _must_drafts(item: str, estimates: dict[str, intake_rules.Estimate]) -> list[_FeatureDraft]:
    drafts = [
        _FeatureDraft(
            f"{item} 등록",
            f"{item}을 앱에서 바로 기록한다",
            "핵심 데이터 입력이 없으면 나머지 기능이 성립하지 않는다",
            "low",
        ),
        _FeatureDraft(
            f"{item} 목록·검색",
            "쌓인 기록을 한 화면에서 훑고 필요한 항목을 찾는다",
            "기록은 다시 찾을 수 있을 때 가치가 생긴다",
            "low",
        ),
        _FeatureDraft(
            f"{item} 현재 상태 표시",
            "지금 처리해야 할 항목이 무엇인지 바로 보인다",
            "성공 장면이 '현재 상태를 30초 안에 확인'이라 필수다",
            "medium",
        ),
    ]
    if estimates[intake_rules.FIELD_AUTH].value in ("required", "mock"):
        drafts.append(
            _FeatureDraft(
                "로그인",
                "내 기록만 보이도록 구분한다",
                "여러 사람이 쓰는 흐름이라 본인 확인이 필요하다",
                "medium",
            )
        )
    if estimates[intake_rules.FIELD_AI_INTEGRATION].value in ("external_api", "mock", "local_model"):
        drafts.append(
            _FeatureDraft(
                f"{item} 자동 정리 도우미",
                "입력한 내용을 자동으로 분류하고 요약해 준다",
                "사용자가 직접 분류하는 수고를 줄이는 것이 차별 가치다",
                "high",
            )
        )
    if estimates[intake_rules.FIELD_PROJECT_TYPE].value == "dashboard":
        drafts.append(
            _FeatureDraft(
                "기간별 통계 화면",
                "월 단위 흐름을 그래프로 확인한다",
                "지표 확인이 이 프로젝트의 주된 사용 목적이다",
                "medium",
            )
        )
    return drafts


def _numbered(drafts: list[_FeatureDraft], start: int) -> tuple[list[dict[str, Any]], int]:
    features: list[dict[str, Any]] = []
    counter = start
    for draft in drafts:
        features.append(
            {
                "id": f"F-{counter:03d}",
                "name": draft.name,
                "userValue": draft.user_value,
                "reason": draft.reason,
                "complexity": draft.complexity,
                "dependencies": [],
            }
        )
        counter += 1
    return features, counter


def _risks(estimates: dict[str, intake_rules.Estimate], must_count: int) -> list[dict[str, str]]:
    risks = [
        {
            "title": "범위 확장 위험",
            "severity": "medium",
            "mitigation": f"Must를 {MUST_MIN}~{MUST_MAX}개로 고정하고 새 요구는 Later로 보낸다",
        }
    ]
    if estimates[intake_rules.FIELD_AUTH].value == "required" and estimates[
        intake_rules.FIELD_SKILL_LEVEL
    ].value == "beginner":
        risks.append(
            {
                "title": "인증 구현 난이도",
                "severity": "medium",
                "mitigation": "1차는 mock 로그인으로 화면 흐름을 확정하고 실제 인증은 별도 작업으로 뺀다",
            }
        )
    if estimates[intake_rules.FIELD_AI_INTEGRATION].value == "external_api":
        risks.append(
            {
                "title": "외부 AI API 비용·실패",
                "severity": "medium",
                "mitigation": "mock 응답 경로를 함께 만들어 API 실패 시에도 화면이 동작하게 한다",
            }
        )
    deadline = estimates[intake_rules.FIELD_DEADLINE].value
    if isinstance(deadline, str) and deadline in ("1 day", "1 week") and must_count >= 4:
        risks.append(
            {
                "title": "기간 대비 범위 과다",
                "severity": "high",
                "mitigation": "가장 뒤에 있는 Must를 Later로 내리고 첫 릴리스는 등록·목록만 목표로 한다",
            }
        )
    return risks


def _open_questions(estimates: dict[str, intake_rules.Estimate]) -> list[str]:
    questions: list[str] = []
    for name in intake_rules.QUESTION_PRIORITY:
        estimate = estimates.get(name)
        if estimate is None:
            continue
        label = intake_rules.FIELD_LABELS[name]
        text = intake_rules.QUESTION_TEXTS[name]
        if estimate.status == intake_rules.STATUS_DEFERRED:
            questions.append(f"{label} - {text} (사용자가 '나중에 결정'을 선택함)")
        elif estimate.status == intake_rules.STATUS_ASKED:
            display = intake_rules.display_value(name, estimate.value)
            questions.append(f"{label} - {text} (답변 없이 추천값 '{display}'으로 진행 중)")
    return questions


def _assumptions(estimates: dict[str, intake_rules.Estimate]) -> list[str]:
    """Inference metadata flattened into the strings the schema allows.

    ``confidence``/``status``/``source`` may not appear in the body
    (``additionalProperties: false``), so the human-readable trace lives here and
    the machine-readable trace lives in ``vo_blueprints.inference_json``.
    """
    lines: list[str] = []
    for name in intake_rules.ESTIMATE_FIELDS:
        estimate = estimates.get(name)
        if estimate is None:
            continue
        label = intake_rules.FIELD_LABELS[name]
        display = intake_rules.display_value(name, estimate.value)
        if estimate.status == intake_rules.STATUS_ANSWERED:
            if estimate.source.endswith("dont_know_promoted_recommendation"):
                lines.append(f"{label}: 사용자가 '모름'을 선택해 추천값 '{display}'으로 확정했다.")
            else:
                lines.append(f"{label}: 사용자가 '{display}'으로 확정했다.")
        elif estimate.status == intake_rules.STATUS_DEFERRED:
            lines.append(f"{label}: '나중에 결정'으로 미뤘고 현재 값은 '{display}'이다.")
        else:
            lines.append(f"{label}: '{display}'로 추정했다 (신뢰도 {estimate.confidence}).")
    return lines


def _project_name(explicit: str | None, item: str, project_type: str) -> str:
    if explicit:
        return explicit
    if project_type == "dashboard":
        return f"{item} 대시보드"
    if project_type == "ai_demo":
        return f"{item} AI 도우미"
    if project_type == "portfolio":
        return f"{item} 포트폴리오"
    if project_type == "landing_demo":
        return f"{item} 소개 페이지"
    return f"{item} 관리 앱"


def _one_line_definition(idea: str, item: str) -> str:
    """``oneLineDefinition`` has ``minLength: 10``; a very short idea gets padded
    with the inferred subject rather than being rejected."""
    text = intake_rules.normalize_idea(idea)
    if len(text) >= 10:
        return text
    return f"{text} - {item}을 기록하고 현재 상태를 바로 확인하는 MVP".strip()


def _technical_direction(estimates: dict[str, intake_rules.Estimate]) -> dict[str, Any]:
    persistence = estimates[intake_rules.FIELD_DATA_PERSISTENCE].value
    return {
        "prototypeStrategy": "화면 시안을 먼저 만들고 데이터는 mock 어댑터로 연결한 뒤 실제 저장소로 교체한다",
        "frontend": "React + Vite",
        "backend": "FastAPI" if persistence == "database" else None,
        "database": "SQLite" if persistence == "database" else None,
        "auth": estimates[intake_rules.FIELD_AUTH].value,
        "dataPersistence": persistence if persistence is not None else "unknown",
        "aiIntegration": estimates[intake_rules.FIELD_AI_INTEGRATION].value,
    }


def build_blueprint_content(
    idea: str,
    estimates: dict[str, intake_rules.Estimate],
    *,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Assemble a schema-valid blueprint body from the estimates.

    Pure function: no DB, no filesystem, no model call. Raises
    ``ScopeGateError``/``BlueprintSchemaError`` when the result would be invalid.
    """
    item = intake_rules.item_noun(idea)
    project_type = estimates[intake_rules.FIELD_PROJECT_TYPE].value
    must_drafts = _must_drafts(item, estimates)
    overflow = must_drafts[MUST_MAX:]
    must_drafts = must_drafts[:MUST_MAX]
    should_drafts = list(overflow) + [
        _FeatureDraft(
            f"{item} CSV 내보내기",
            "기록을 엑셀로 옮겨 따로 정리한다",
            "핵심 흐름은 아니지만 초기 사용자의 이탈을 막는다",
            "low",
        )
    ]

    must, counter = _numbered(must_drafts, 1)
    should, counter = _numbered(should_drafts, counter)
    later, counter = _numbered(list(_LATER_FEATURES), counter)
    out, _ = _numbered(list(_OUT_FEATURES), counter)

    persona = estimates[intake_rules.FIELD_TARGET_USERS].value
    target_users = list(persona) if isinstance(persona, list) else [str(persona)]

    blueprint = Blueprint(
        projectName=_project_name(project_name, item, project_type),
        oneLineDefinition=_one_line_definition(idea, item),
        projectType=project_type,
        targetUsers=target_users,
        coreProblem=estimates[intake_rules.FIELD_CORE_PROBLEM].value,
        successMoment=estimates[intake_rules.FIELD_SUCCESS_MOMENT].value,
        valueProposition=f"{target_users[0]}가 {item} 관리를 한 화면에서 끝내도록 돕는다",
        scope={"must": must, "should": should, "later": later, "out": out},
        constraints={
            "teamSize": estimates[intake_rules.FIELD_TEAM_SIZE].value,
            "deadline": estimates[intake_rules.FIELD_DEADLINE].value,
            "skillLevel": estimates[intake_rules.FIELD_SKILL_LEVEL].value,
            "requiredStack": [],
            "budgetNote": None,
        },
        technicalDirection=_technical_direction(estimates),
        risks=_risks(estimates, len(must)),
        openQuestions=_open_questions(estimates),
        confidence={name: estimates[name].confidence for name in intake_rules.ESTIMATE_FIELDS if name in estimates},
        assumptions=_assumptions(estimates),
    )
    content = blueprint.to_content()
    assert_scope_gate(content)
    validate_blueprint(content)
    return content


def assert_scope_gate(content: dict[str, Any]) -> None:
    """Gate B: Must 3~5, Later and Out non-empty. Raises ``ScopeGateError``."""
    scope = content.get("scope") or {}
    must = scope.get("must") or []
    if not MUST_MIN <= len(must) <= MUST_MAX:
        raise ScopeGateError(f"Must 기능은 {MUST_MIN}~{MUST_MAX}개여야 합니다 (현재 {len(must)}개).")
    if not scope.get("later"):
        raise ScopeGateError("Later 기능이 비어 있습니다. 미루는 기능을 최소 1개 남겨야 합니다.")
    if not scope.get("out"):
        raise ScopeGateError("Out 기능이 비어 있습니다. 이번 범위에서 제외할 기능을 명시해야 합니다.")


# --------------------------------------------------------------------------- #
# Persistence helpers
# --------------------------------------------------------------------------- #


def _merge_inference(previous: dict[str, Any], result: intake_rules.IntakeResult) -> dict[str, Any]:
    """Keep the user-supplied project name across intake recomputations.

    ``vo_projects.name`` is a display column that ``generate`` overwrites with the
    blueprint's ``projectName``, so the *user's* explicit name has to survive
    somewhere that intake does not clobber. inference_json is that place.
    """
    payload = result.to_inference()
    if previous.get("projectName"):
        payload["projectName"] = previous["projectName"]
    return payload


def _blueprint_row(db: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM vo_blueprints WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def _require_blueprint_row(db: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = _blueprint_row(db, project_id)
    if row is None:
        raise BlueprintNotFound(f"Blueprint draft not found for project {project_id}")
    return row


def _write_blueprint_file(workspace: Path, content: dict[str, Any]) -> tuple[str, str]:
    """Write ``.vibeoffice/project-blueprint.json`` and return (relative path, sha256)."""
    root = workspace.resolve()
    directory = (root / BLUEPRINT_DIRNAME).resolve()
    if not directory.is_relative_to(root):
        raise ScopeGateError("Blueprint 경로가 워크스페이스를 벗어납니다.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / BLUEPRINT_FILENAME
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Hash the bytes on disk, not the in-memory string: the file is the artifact.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.relative_to(root).as_posix(), digest


def _project_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "name": row["name"],
        "mode": row["mode"],
        "skill_level": row["skill_level"],
        "team_size": row["team_size"],
        "deadline": row["deadline"],
        "state": row["state"],
        "workspace_path": row["workspace_path"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_project(
    *,
    idea: str,
    start_card_id: str | None = None,
    name: str | None = None,
    mode: str | None = None,
    task_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Create a DRAFT project and stash the raw idea for the intake step."""
    normalized_idea = intake_rules.normalize_idea(idea)
    if len(normalized_idea) < 5:
        raise ValueError("아이디어를 한 문장 이상 적어 주세요. 예: 동네 카페 재고를 매일 기록하고 부족하면 알려주는 앱")
    if start_card_id and start_card_id not in intake_rules.START_CARDS_BY_ID:
        raise ValueError(f"알 수 없는 시작 카드입니다: {start_card_id}")
    card = intake_rules.START_CARDS_BY_ID.get(start_card_id or "")
    resolved_mode = mode or (card.mode if card else "standard")
    if resolved_mode not in MODES:
        raise ValueError(f"알 수 없는 진행 모드입니다: {resolved_mode}")

    now = utc_now()
    with vibeoffice_database() as db:
        project_id = next_project_id(db)
        workspace = Path(workspace_path).resolve() if workspace_path else (default_workspace_root() / project_id)
        workspace.mkdir(parents=True, exist_ok=True)
        db.execute(
            "INSERT INTO vo_projects (id, task_id, name, mode, skill_level, team_size, deadline, state, "
            "workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                task_id,
                name or normalized_idea[:40],
                resolved_mode,
                "beginner",
                None,
                None,
                ProjectState.DRAFT.value,
                str(workspace),
                now,
                now,
            ),
        )
        db.execute(
            "INSERT INTO vo_blueprints (id, project_id, version, content_json, inference_json, questions_json, "
            "answers_json, path, sha256, approved_at, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?)",
            (
                f"{project_id}-BP{WORKING_VERSION}",
                project_id,
                WORKING_VERSION,
                json.dumps(
                    {
                        "idea": normalized_idea,
                        "startCard": start_card_id,
                        "projectName": name,
                        "values": {},
                    },
                    ensure_ascii=False,
                ),
                json.dumps([], ensure_ascii=False),
                json.dumps({}, ensure_ascii=False),
                now,
            ),
        )
        return _project_payload(load_project(db, project_id))


def run_intake(project_id: str, *, idea: str | None = None, start_card_id: str | None = None) -> dict[str, Any]:
    """Normalize the idea, produce estimates, surface at most three questions.

    Idempotent: re-running recomputes from the stored idea, so a client may call
    it again after editing the idea without creating a second project.
    """
    with vibeoffice_database() as db:
        project = load_project(db, project_id)
        row = _require_blueprint_row(db, project_id)
        stored = json.loads(row["inference_json"] or "{}")
        resolved_idea = intake_rules.normalize_idea(idea or stored.get("idea") or "")
        resolved_card = start_card_id or stored.get("startCard")
        result = intake_rules.plan_intake(resolved_idea, resolved_card)
        target = ProjectState.NEEDS_USER_DECISION if result.questions else ProjectState.PLANNING
        state = set_project_state(db, project_id, target)
        estimates = result.estimates
        db.execute(
            "UPDATE vo_blueprints SET inference_json = ?, questions_json = ?, answers_json = ? WHERE id = ?",
            (
                json.dumps(_merge_inference(stored, result), ensure_ascii=False),
                json.dumps(result.to_questions(), ensure_ascii=False),
                json.dumps({}, ensure_ascii=False),
                row["id"],
            ),
        )
        db.execute(
            "UPDATE vo_projects SET skill_level = ?, team_size = ?, deadline = ?, updated_at = ? WHERE id = ?",
            (
                estimates[intake_rules.FIELD_SKILL_LEVEL].value,
                estimates[intake_rules.FIELD_TEAM_SIZE].value,
                estimates[intake_rules.FIELD_DEADLINE].value,
                utc_now(),
                project_id,
            ),
        )
        return {
            "project_id": project_id,
            "state": state.value,
            "idea": result.idea,
            "start_card": resolved_card,
            "estimates": {name: estimate.to_dict() for name, estimate in estimates.items()},
            "questions": result.to_questions(),
            "question_count": len(result.questions),
            "workspace_path": project["workspace_path"],
        }


def open_questions(project_id: str) -> dict[str, Any]:
    """Questions still awaiting an answer (never more than ``MAX_QUESTIONS``)."""
    with vibeoffice_database() as db:
        load_project(db, project_id)
        row = _require_blueprint_row(db, project_id)
        questions = json.loads(row["questions_json"] or "[]")
        return {
            "project_id": project_id,
            "max_questions": intake_rules.MAX_QUESTIONS,
            "questions": questions,
            "question_count": len(questions),
        }


def submit_answers(project_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold answers into the estimates and clear the answered questions."""
    with vibeoffice_database() as db:
        load_project(db, project_id)
        row = _require_blueprint_row(db, project_id)
        stored = json.loads(row["inference_json"] or "{}")
        result = intake_rules.load_intake(stored, json.loads(row["questions_json"] or "[]"))
        if not result.estimates:
            raise StateTransitionError("먼저 intake를 실행해 추정값을 만들어야 답변을 반영할 수 있습니다.")
        previous_log = json.loads(row["answers_json"] or "{}")
        log = intake_rules.apply_answers(result, answers)
        previous_log.update(log)
        target = ProjectState.NEEDS_USER_DECISION if result.questions else ProjectState.PLANNING
        state = set_project_state(db, project_id, target)
        db.execute(
            "UPDATE vo_blueprints SET inference_json = ?, questions_json = ?, answers_json = ? WHERE id = ?",
            (
                json.dumps(_merge_inference(stored, result), ensure_ascii=False),
                json.dumps(result.to_questions(), ensure_ascii=False),
                json.dumps(previous_log, ensure_ascii=False),
                row["id"],
            ),
        )
        db.execute(
            "UPDATE vo_projects SET skill_level = ?, team_size = ?, deadline = ?, updated_at = ? WHERE id = ?",
            (
                result.estimates[intake_rules.FIELD_SKILL_LEVEL].value,
                result.estimates[intake_rules.FIELD_TEAM_SIZE].value,
                result.estimates[intake_rules.FIELD_DEADLINE].value,
                utc_now(),
                project_id,
            ),
        )
        return {
            "project_id": project_id,
            "state": state.value,
            "answers": previous_log,
            "estimates": {name: estimate.to_dict() for name, estimate in result.estimates.items()},
            "questions": result.to_questions(),
            "question_count": len(result.questions),
        }


def generate_blueprint(project_id: str) -> dict[str, Any]:
    """Build, validate, persist (DB + file) and move the project to review."""
    with vibeoffice_database() as db:
        project = load_project(db, project_id)
        row = _require_blueprint_row(db, project_id)
        inference = json.loads(row["inference_json"] or "{}")
        result = intake_rules.load_intake(inference, json.loads(row["questions_json"] or "[]"))
        if not result.estimates:
            raise StateTransitionError("추정값이 없습니다. 먼저 intake를 실행하세요.")
        if row["approved_at"]:
            # An approved artifact is frozen (S1 principle; 05A section 1 "승인된
            # 버전만 사용").  Regenerating in place would rewrite the body of an
            # already-approved version *under its own version number*, so every
            # downstream artifact whose ``source_blueprint_version`` points at it
            # would silently start referring to different content.  This is
            # reachable: HANDOFF_REJECTED -> PLANNING_REVIEW is a legal transition
            # and it leaves the latest blueprint row approved.  A revision has to
            # go through ``artifacts.revise_blueprint``, which appends a version.
            raise StateTransitionError(
                f"승인된 blueprint v{row['version']}는 덮어쓸 수 없습니다. "
                "내용을 바꾸려면 새 버전으로 개정해야 합니다."
            )
        content = build_blueprint_content(
            result.idea, result.estimates, project_name=inference.get("projectName")
        )
        relative_path, digest = _write_blueprint_file(Path(project["workspace_path"]), content)
        state = set_project_state(db, project_id, ProjectState.PLANNING_REVIEW)
        db.execute(
            "UPDATE vo_blueprints SET content_json = ?, path = ?, sha256 = ? WHERE id = ?",
            (json.dumps(content, ensure_ascii=False), relative_path, digest, row["id"]),
        )
        db.execute(
            "UPDATE vo_projects SET name = ?, updated_at = ? WHERE id = ?",
            (content["projectName"], utc_now(), project_id),
        )
        return {
            "project_id": project_id,
            "state": state.value,
            "version": row["version"],
            "path": relative_path,
            "sha256": digest,
            "blueprint": content,
            "approved_at": None,
        }


def get_blueprint(project_id: str) -> dict[str, Any]:
    """Read the stored blueprint plus its inference metadata."""
    with vibeoffice_database() as db:
        project = load_project(db, project_id)
        row = _require_blueprint_row(db, project_id)
        if not row["content_json"]:
            raise BlueprintNotFound(f"Blueprint has not been generated for project {project_id}")
        return {
            "project_id": project_id,
            "state": project["state"],
            "version": row["version"],
            "path": row["path"],
            "sha256": row["sha256"],
            "approved_at": row["approved_at"],
            "blueprint": json.loads(row["content_json"]),
            "inference": json.loads(row["inference_json"] or "{}"),
            "answers": json.loads(row["answers_json"] or "{}"),
        }


def approve_blueprint(project_id: str) -> dict[str, Any]:
    """User approval #1 (planning). Only legal from ``PLANNING_REVIEW``."""
    with vibeoffice_database() as db:
        load_project(db, project_id)
        row = _require_blueprint_row(db, project_id)
        if not row["content_json"]:
            raise BlueprintNotFound(f"Blueprint has not been generated for project {project_id}")
        content = json.loads(row["content_json"])
        # Re-validate at the approval boundary: the row could have been edited
        # between generate and approve, and an approved blueprint is what the
        # next department trusts.
        assert_scope_gate(content)
        validate_blueprint(content)
        state = set_project_state(db, project_id, ProjectState.PLANNING_APPROVED)
        approved_at = utc_now()
        db.execute("UPDATE vo_blueprints SET approved_at = ? WHERE id = ?", (approved_at, row["id"]))
        return {
            "project_id": project_id,
            "state": state.value,
            "version": row["version"],
            "approved_at": approved_at,
            "path": row["path"],
            "sha256": row["sha256"],
            "blueprint": content,
        }


def approved_blueprint_for_handoff(project_id: str) -> dict[str, Any]:
    """The only sanctioned reader for the next department.

    Rejects with a Korean reason unless the project is ``PLANNING_APPROVED``, the
    approval timestamp exists, the body still passes schema + scope gate, and the
    workspace file matches the recorded sha256.
    """
    with vibeoffice_database() as db:
        project = load_project(db, project_id)
        row = _blueprint_row(db, project_id)
        if row is None or not row["content_json"]:
            raise HandoffRejected("Blueprint이 아직 생성되지 않아 다음 부서로 넘길 수 없습니다.")
        state = project["state"]
        if state != ProjectState.PLANNING_APPROVED.value:
            raise HandoffRejected(
                f"기획 승인 전에는 다음 부서로 넘길 수 없습니다. 현재 상태: {state} "
                f"(필요 상태: {ProjectState.PLANNING_APPROVED.value})"
            )
        if not row["approved_at"]:
            raise HandoffRejected("승인 시각이 기록되지 않은 Blueprint입니다. 기획 승인을 다시 진행하세요.")
        content = json.loads(row["content_json"])
        try:
            assert_scope_gate(content)
            validate_blueprint(content)
        except (ScopeGateError, BlueprintSchemaError) as error:
            raise HandoffRejected(f"승인된 Blueprint가 검증을 통과하지 못했습니다: {error}") from error
        path = Path(project["workspace_path"]) / (row["path"] or f"{BLUEPRINT_DIRNAME}/{BLUEPRINT_FILENAME}")
        if not path.is_file():
            raise HandoffRejected(f"워크스페이스에 blueprint 파일이 없습니다: {row['path']}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            raise HandoffRejected("Blueprint 파일이 승인 이후 변경되었습니다. 다시 생성하고 승인해야 합니다.")
        return {
            "project_id": project_id,
            "version": row["version"],
            "approved_at": row["approved_at"],
            "path": row["path"],
            "sha256": digest,
            "blueprint": content,
        }


__all__ = [
    "MUST_MAX",
    "MUST_MIN",
    "BlueprintNotFound",
    "HandoffRejected",
    "ScopeGateError",
    "approve_blueprint",
    "approved_blueprint_for_handoff",
    "assert_scope_gate",
    "build_blueprint_content",
    "create_project",
    "generate_blueprint",
    "get_blueprint",
    "open_questions",
    "run_intake",
    "submit_answers",
    "ProjectNotFound",
]
