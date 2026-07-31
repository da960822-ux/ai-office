"""Planning -> Design handoff envelope (slice S2).

Invariants this module owns:

* **Only an approved blueprint may be handed over.**  The single reader is
  ``blueprint.approved_blueprint_for_handoff``, which re-checks project state,
  approval timestamp, schema, scope gate and file hash.  There is no code path
  here that reads ``vo_blueprints.content_json`` for a draft.
* **The envelope is derived, never hard-coded.**  ``constraints``,
  ``acceptanceCriteria`` and ``openDecisions`` are computed from the approved
  blueprint (Out features, skill level, deadline, Must list, open questions) plus
  the Gate C bounds.  A frozen constant array would produce an envelope that
  looks right and says nothing about *this* project - and it would keep saying it
  after the blueprint changed.
* **Rejection conditions are executed, not documented.**  All five conditions in
  05A section 3 are checked in ``evaluate_rejection_reasons``; a violation makes
  the handoff ``rejected`` with Korean reasons and moves the project to
  ``HANDOFF_REJECTED``.  Rejected and superseded are terminal statuses: a bounce
  produces a *new* envelope, it does not edit the refused one.
* **Superseded is driven by input versions (05A section 10).**  Every live
  handoff records the blueprint version it was built from; when a newer version
  appears, that handoff is superseded and the successor's ``supersedes`` points
  back at it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from apps.api.vibeoffice import artifacts as artifact_store
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import intake as intake_rules
from apps.api.vibeoffice.models import HandoffEnvelope, HandoffSchemaError, validate_handoff
from apps.api.vibeoffice.schema import (
    BLUEPRINT_DIRNAME,
    DEPARTMENT_DESIGN,
    DEPARTMENT_PLANNING,
    GATE_C_MAX_SCREENS,
    HANDOFF_DIRNAME,
    LIVE_HANDOFF_STATUSES,
    PLANNING_TO_DESIGN_FILENAME,
    HandoffStatus,
    ProjectNotFound,
    ProjectState,
    StateTransitionError,
    coerce_handoff_status,
    load_project,
    require_handoff_transition,
    s2_database,
    set_project_state,
    utc_now,
)

#: ``inputVersions`` key for the approved blueprint. Kept as a constant because
#: both the envelope writer and the supersede check read it.
INPUT_PROJECT_BLUEPRINT = "projectBlueprint"

#: Design Package deliverables (06_OUTPUT_STANDARD). Derived from the artifact
#: catalogue so a new design document automatically becomes a required output.
#:
#: KNOWN GAP (deferred past S2, deliberately not fixed here): ``prototype`` is
#: promised by the envelope but S2 does not produce it, and ``design.run_design``
#: does not assert that every ``requiredOutputs`` entry exists.  A clickable
#: prototype needs a frontend surface that no slice has built yet, so removing
#: the promise would make the envelope disagree with 06_OUTPUT_STANDARD while
#: faking it would put an empty file in the Design Package.  The completeness
#: check belongs with the slice that can actually satisfy it.
REQUIRED_OUTPUTS: tuple[str, ...] = tuple(
    artifact_store.ARTIFACT_FILENAMES[artifact_type]
    for artifact_type in artifact_store.DESIGN_PACKAGE_TYPES
) + ("prototype",)

#: 05A section 3 필수 입력. S1 only produces ``project-blueprint.json``; the four
#: markdown planning documents arrive in a later slice, so they are listed here as
#: the documented contract and reported as missing rather than faked with a
#: version number that does not exist.
PLANNING_REQUIRED_INPUTS = (
    "project-blueprint.json",
    "PRODUCT_BRIEF.md",
    "MVP_SCOPE.md",
    "REQUIREMENTS.md",
    "DECISIONS.md",
)


class HandoffNotFound(LookupError):
    """No such handoff. Routes map this to 404."""


class HandoffRejectedError(RuntimeError):
    """The handoff exists but is refused/superseded. Routes map this to 409."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------- #
# Rejection conditions (05A section 3)
# --------------------------------------------------------------------------- #

#: Minimum length a Must feature's ``reason`` needs before it counts as 근거.
#: The schema only demands ``minLength: 1``, so "-" would satisfy it.
MIN_RATIONALE_CHARS = 8

#: Persona groups that cannot be the *same* primary user.  A conflict exists only
#: when two *different* personas fall into two *different* groups.
#:
#: Declaration order is priority order, and it matters: one persona string may
#: contain keywords from several groups ("1인 카페 사장" hits both 개인 사용자 and
#: 조직 구성원), so ``_persona_group`` picks exactly one group per persona.  The
#: generic 개인 사용자 group is therefore listed **last**: 개인/1인 describe the
#: scale of the operation, while 사장/담당자/직원 name who the person actually is,
#: which is the thing that changes the screen structure.  Scanning every group
#: into one accumulated set - the previous behaviour - rejected "1인 카페 사장" and
#: "개인 병원 담당자", both perfectly ordinary single personas.
PERSONA_CONFLICT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("학생", ("학생", "수업", "학교", "수강")),
    ("외부 고객", ("고객", "방문자", "구매자", "환자")),
    ("조직 구성원", ("팀", "사내", "회사", "직원", "동료", "관리자", "점주", "사장", "담당자")),
    ("개인 사용자", ("혼자", "개인", "1인", "나만")),
)

#: A success moment is translatable into screen behaviour only if it names an
#: observable action. Nouns alone ("좋은 경험") cannot become a CTA.
#:
#: These are *stems*, not whole words: Korean verbs inflect ("받고 / 받아 / 받는 /
#: 받은"), so matching whole conjugated forms rejected ordinary sentences like
#: "알림을 받고 바로 주문한다".  Every entry is the part of the verb or action noun
#: that survives inflection.  Single-syllable stems are only used where they
#: cannot collide with common nouns ("받"); for 보다 the inflected forms are listed
#: explicitly because a bare "보" would match 정보/보관/확보.
OBSERVABLE_ACTION_STEMS = (
    # action nouns (+하다/한다/하고/했다 …)
    "확인",
    "입력",
    "등록",
    "저장",
    "제출",
    "선택",
    "작성",
    "완료",
    "실행",
    "공유",
    "검색",
    "조회",
    "수정",
    "삭제",
    "추가",
    "이동",
    "비교",
    "정리",
    "기록",
    "주문",
    "발주",
    "예약",
    "신청",
    "승인",
    "결제",
    "취소",
    "업로드",
    "다운로드",
    "내보내",
    "클릭",
    "알림",
    "알려",
    # verb stems
    "받",
    "누르",
    "열어",
    "연다",
    "읽",
    "본다",
    "보고",
    "보이",
    "봅니",
    "찾",
)

#: Kept as an alias so any external reader of the old name still resolves.
OBSERVABLE_ACTION_MARKERS = OBSERVABLE_ACTION_STEMS

#: Open questions touching these blueprint decisions change the screen skeleton
#: itself (how many screens, whether there is a login screen, whether a screen
#: reads stored data). Design cannot start while they are undecided.
#:
#: Referenced out of ``intake.FIELD_LABELS`` rather than spelled out: S1's
#: ``blueprint._open_questions`` builds the openQuestion string from exactly that
#: mapping, so hard-coding the five labels here meant one label tweak in intake
#: would silently kill rejection condition 5.
STRUCTURAL_DECISION_FIELDS = (
    intake_rules.FIELD_PROJECT_TYPE,
    intake_rules.FIELD_TARGET_USERS,
    intake_rules.FIELD_AUTH,
    intake_rules.FIELD_DATA_PERSISTENCE,
    intake_rules.FIELD_AI_INTEGRATION,
)
STRUCTURAL_DECISION_LABELS: tuple[str, ...] = tuple(
    intake_rules.FIELD_LABELS[field_name] for field_name in STRUCTURAL_DECISION_FIELDS
)

#: Marker S1 writes into ``openQuestions`` for a "나중에 결정" answer.
DEFERRED_MARKER = "나중에 결정"


def _feature_names(features: list[dict[str, Any]]) -> list[str]:
    return [str(feature.get("name", "")).strip() for feature in features or []]


def persona_group(persona: str) -> str | None:
    """The single group one persona belongs to, by ``PERSONA_CONFLICT_GROUPS`` priority.

    Returns ``None`` when no group keyword matches; an unclassified persona cannot
    conflict with anything, which is the conservative answer for free text we do
    not recognise.
    """
    text = str(persona)
    for label, keywords in PERSONA_CONFLICT_GROUPS:
        if any(keyword in text for keyword in keywords):
            return label
    return None


def _persona_groups(target_users: list[str]) -> set[str]:
    """Groups represented by the persona list - one group per persona at most."""
    groups: set[str] = set()
    for persona in target_users or []:
        group = persona_group(persona)
        if group is not None:
            groups.add(group)
    return groups


def names_observable_action(text: str) -> bool:
    """True when the sentence contains an action stem design can turn into a CTA."""
    return any(stem in str(text or "") for stem in OBSERVABLE_ACTION_STEMS)


def evaluate_rejection_reasons(content: dict[str, Any]) -> list[str]:
    """The five 05A section 3 rejection conditions, in document order.

    Pure function over an approved blueprint body. Returns Korean reasons; an
    empty list means the handoff may be created.
    """
    reasons: list[str] = []
    scope = content.get("scope") or {}
    must = scope.get("must") or []
    should = scope.get("should") or []
    out = scope.get("out") or []

    # 1. Must가 5개 초과하며 근거 없음
    #
    # KNOWN GAP (deferred past S2, deliberately not fixed here): this branch is
    # unreachable through the API.  ``create_handoff`` reads the blueprint through
    # ``approved_blueprint_for_handoff``, which re-runs Gate B, and Gate B caps
    # Must at ``MUST_MAX``; a 6-Must blueprint therefore dies as a 409
    # ``ScopeGateError`` long before it reaches this function.  The condition is
    # covered by a *pure function* test only, and is kept because 05A section 3
    # lists it and because a later slice that relaxes Gate B (or accepts a
    # hand-written blueprint) would need it live.  Redefining it to not overlap
    # Gate B is a spec change, not a bug fix.
    if len(must) > blueprint_service.MUST_MAX:
        unjustified = [
            str(feature.get("id") or feature.get("name"))
            for feature in must
            if len(str(feature.get("reason") or "").strip()) < MIN_RATIONALE_CHARS
        ]
        if unjustified:
            reasons.append(
                f"Must 기능이 {len(must)}개로 {blueprint_service.MUST_MAX}개를 넘는데 근거가 없는 항목이 있습니다: "
                f"{', '.join(unjustified)}. 범위를 줄이거나 각 기능의 근거를 채워 주세요."
            )

    # 2. 대상 사용자가 충돌
    target_users = content.get("targetUsers") or []
    if not [str(user).strip() for user in target_users if str(user).strip()]:
        reasons.append("대상 사용자가 비어 있습니다. 가장 중요한 사용자 1명을 정해 주세요.")
    else:
        # A conflict needs two *different* personas landing in two *different*
        # groups, so a single persona string can never trigger it.
        groups = _persona_groups(list(target_users))
        if len(groups) > 1:
            reasons.append(
                f"대상 사용자가 서로 충돌합니다: {', '.join(sorted(groups))}. "
                "화면 구조가 달라지므로 주 사용자를 한 부류로 정해 주세요."
            )

    # 3. 성공 장면이 화면 행동으로 바뀔 수 없음
    success_moment = str(content.get("successMoment") or "")
    if not names_observable_action(success_moment):
        reasons.append(
            "성공 장면을 화면 행동으로 바꿀 수 없습니다. "
            "사용자가 무엇을 눌러 무엇을 보게 되는지 관찰 가능한 행동으로 적어 주세요."
        )

    # 4. Out 기능이 Must/Should에 포함
    #
    # SUBSTITUTION (deliberate, not a bug): 05A section 3 words this condition as
    # "Out 기능이 Requirements에 포함".  There is no REQUIREMENTS.md yet - no slice
    # produces one - so the closest artifact that actually exists is the approved
    # blueprint's Must/Should buckets, which is what REQUIREMENTS.md will be
    # generated from.  When that document lands, this check should move to it.
    # Comparison is by *name*, not id, on purpose: S1's generator can put the same
    # feature name in Out and Must under different ids.
    out_names = {name for name in _feature_names(out) if name}
    included = sorted(out_names & set(_feature_names(must) + _feature_names(should)))
    if included:
        reasons.append(
            f"이번 범위에서 제외(Out)한 기능이 Must/Should에 다시 들어 있습니다: {', '.join(included)}."
        )

    # 5. 미결정 사항이 핵심 화면 구조를 바꿈
    structural = [
        question
        for question in content.get("openQuestions") or []
        if DEFERRED_MARKER in str(question)
        and any(label in str(question) for label in STRUCTURAL_DECISION_LABELS)
    ]
    if structural:
        reasons.append(
            "미결정 사항이 핵심 화면 구조를 바꿉니다: "
            + "; ".join(str(question) for question in structural)
            + ". 디자인 시작 전에 결정이 필요합니다."
        )
    return reasons


# --------------------------------------------------------------------------- #
# Envelope derivation
# --------------------------------------------------------------------------- #


def derive_constraints(content: dict[str, Any]) -> list[str]:
    """Design constraints derived from the approved blueprint + Gate C."""
    constraints = [f"핵심 화면 최대 {GATE_C_MAX_SCREENS}개"]
    scope = content.get("scope") or {}
    for name in _feature_names(scope.get("out")):
        if name:
            constraints.append(f"{name} 제외")
    if (content.get("constraints") or {}).get("skillLevel") == "beginner":
        constraints.append("초보자 언어")
    constraints.append("loading/empty/error")
    constraints.append("모바일 핵심 흐름 지원")
    deadline = (content.get("constraints") or {}).get("deadline")
    if deadline:
        constraints.append(f"기간 {deadline} 안에 구현 가능한 범위")
    technical = content.get("technicalDirection") or {}
    if technical.get("auth") in ("none", "later"):
        constraints.append("로그인 화면 없이 진행")
    if technical.get("aiIntegration") in ("none", "later"):
        constraints.append("AI 기능 화면 없이 진행")
    return constraints


def derive_acceptance_criteria(content: dict[str, Any]) -> list[str]:
    """Gate C acceptance criteria, one entry per Must plus the shared UX rules."""
    criteria = ["모든 Must 기능이 화면에 연결"]
    scope = content.get("scope") or {}
    for feature in scope.get("must") or []:
        criteria.append(f"{feature.get('id')} {feature.get('name')}이 흐름과 화면에 모두 존재")
    criteria.extend(
        [
            "dead-end 없음",
            "주요 CTA 동작 정의",
            "데이터 화면에 loading/empty/error 정의",
            f"핵심 화면 {GATE_C_MAX_SCREENS}개 이하",
        ]
    )
    return criteria


def derive_open_decisions(content: dict[str, Any]) -> list[str]:
    """Undecided items the design department has to work around.

    Straight from the blueprint's ``openQuestions``: the planning department
    already recorded every deferral and unanswered recommendation there.
    """
    return [str(question) for question in content.get("openQuestions") or []]


def derive_handoff_summary(content: dict[str, Any]) -> dict[str, Any]:
    """05A section 3 인계 요약. Stored alongside the envelope, not inside it
    (``additionalProperties: false``), and returned by the API for the UI."""
    scope = content.get("scope") or {}
    constraints = content.get("constraints") or {}
    return {
        "primaryUser": (content.get("targetUsers") or [None])[0],
        "successMoment": content.get("successMoment"),
        "mustFeatures": [
            {"id": feature.get("id"), "name": feature.get("name")} for feature in scope.get("must") or []
        ],
        "explicitlyOut": _feature_names(scope.get("out")),
        "deadline": constraints.get("deadline"),
        "teamSize": constraints.get("teamSize"),
        "skillLevel": constraints.get("skillLevel"),
        "designConstraints": derive_constraints(content),
        "openDecisions": derive_open_decisions(content),
        "requiredInputs": list(PLANNING_REQUIRED_INPUTS),
    }


# --------------------------------------------------------------------------- #
# Persistence helpers
# --------------------------------------------------------------------------- #


def _write_envelope_file(workspace: Path, content: dict[str, Any]) -> tuple[str, str]:
    """Write ``.vibeoffice/handoffs/planning-to-design.json``; return (relpath, sha256).

    KNOWN GAPS (deferred past S2, deliberately not fixed here):

    * The filename is a constant, so every status change and every successor
      envelope overwrites the same file: the workspace keeps the newest contract
      only, and right after a supersede that newest contract is a ``superseded``
      one.  The guide (section 5) writes ``handoffs/*.json``, i.e. one file per
      handoff id.  Changing the layout means changing what an exported workspace
      looks like and how the next department discovers the live contract, which is
      a call the slice that adds the second handoff (design -> architecture)
      should make once there is more than one envelope kind on disk.
    * ``vo_handoffs`` has no change-diff / re-handoff-reason column, so 05A
      section 10 "모든 리인계는 변경 diff와 이유를 포함" is only half met: the
      successor records ``supersedes`` and the *superseded* row records the
      sentence.  A real diff needs the previous envelope body, which means keeping
      envelope history - the same per-id file question as above.  One change, one
      slice.
    """
    root = workspace.resolve()
    directory = (root / HANDOFF_DIRNAME).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Handoff 경로가 워크스페이스를 벗어납니다.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / PLANNING_TO_DESIGN_FILENAME
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Hash the bytes on disk, not the in-memory string: the file is the artifact.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.relative_to(root).as_posix(), digest


#: Handoff id shape. The project id is part of the id because ``vo_handoffs.id`` is
#: a *global* primary key while the sequence number is per project: without the
#: prefix the second project in the same database collided on
#: ``HO-PLN-DES-001`` and ``POST /handoffs`` died with an IntegrityError (500).
#: There is one production database, so that made handoffs impossible for every
#: project after the first.
HANDOFF_ID_TEMPLATE = "{project_id}-HO-PLN-DES-{sequence:03d}"


def _next_handoff_id(db: sqlite3.Connection, project_id: str) -> str:
    sequence = (
        db.execute("SELECT COUNT(*) FROM vo_handoffs WHERE project_id = ?", (project_id,)).fetchone()[0] + 1
    )
    candidate = HANDOFF_ID_TEMPLATE.format(project_id=project_id, sequence=sequence)
    # The uniqueness probe is global, matching the PK it has to satisfy.
    while db.execute("SELECT 1 FROM vo_handoffs WHERE id = ?", (candidate,)).fetchone():
        sequence += 1
        candidate = HANDOFF_ID_TEMPLATE.format(project_id=project_id, sequence=sequence)
    return candidate


def _handoff_row(db: sqlite3.Connection, project_id: str, handoff_id: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM vo_handoffs WHERE project_id = ? AND id = ?", (project_id, handoff_id)
    ).fetchone()
    if row is None:
        raise HandoffNotFound(f"Handoff not found: {project_id}/{handoff_id}")
    return row


def _envelope_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """Rebuild the schema-shaped envelope from the DB row."""
    return HandoffEnvelope(
        handoffId=row["id"],
        projectId=row["project_id"],
        fromDepartment=row["from_dept"],
        toDepartment=row["to_dept"],
        status=row["status"],
        inputVersions=json.loads(row["input_versions_json"]),
        requiredOutputs=json.loads(row["required_outputs_json"]),
        constraints=json.loads(row["constraints_json"]),
        acceptanceCriteria=json.loads(row["acceptance_json"]),
        openDecisions=json.loads(row["open_decisions_json"]),
        approvedBy=row["approved_by"],
        createdAt=row["created_at"],
        supersedes=row["supersedes"],
    ).to_content()


def _payload(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "from_dept": row["from_dept"],
        "to_dept": row["to_dept"],
        "status": row["status"],
        "path": row["path"],
        "sha256": row["sha256"],
        "supersedes": row["supersedes"],
        "approved_by": row["approved_by"],
        "rejection_reasons": json.loads(row["rejection_reasons_json"] or "[]"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "envelope": _envelope_from_row(row),
    }


def _persist_envelope(
    db: sqlite3.Connection, project: sqlite3.Row, row: sqlite3.Row
) -> tuple[str, str]:
    """Re-render the envelope file for a row and store the new hash."""
    envelope = _envelope_from_row(row)
    validate_handoff(envelope)
    relative_path, digest = _write_envelope_file(Path(project["workspace_path"]), envelope)
    db.execute(
        "UPDATE vo_handoffs SET path = ?, sha256 = ?, updated_at = ? WHERE id = ? AND project_id = ?",
        (relative_path, digest, utc_now(), row["id"], row["project_id"]),
    )
    return relative_path, digest


def set_handoff_status(
    db: sqlite3.Connection,
    project: sqlite3.Row,
    handoff_id: str,
    target: str | HandoffStatus,
    *,
    approved_by: str | None = None,
    rejection_reasons: list[str] | None = None,
) -> sqlite3.Row:
    """Apply a validated handoff status transition and rewrite the envelope file."""
    row = _handoff_row(db, project["id"], handoff_id)
    status = require_handoff_transition(row["status"], target)
    db.execute(
        "UPDATE vo_handoffs SET status = ?, approved_by = COALESCE(?, approved_by), "
        "rejection_reasons_json = COALESCE(?, rejection_reasons_json), updated_at = ? "
        "WHERE id = ? AND project_id = ?",
        (
            status.value,
            approved_by,
            json.dumps(rejection_reasons, ensure_ascii=False) if rejection_reasons is not None else None,
            utc_now(),
            handoff_id,
            project["id"],
        ),
    )
    updated = _handoff_row(db, project["id"], handoff_id)
    _persist_envelope(db, project, updated)
    return _handoff_row(db, project["id"], handoff_id)


def supersede_live_handoffs(db: sqlite3.Connection, project_id: str, *, reason: str) -> list[str]:
    """Supersede every live handoff whose input blueprint version is stale.

    05A section 10: 승인 후 입력 산출물이 바뀌면 기존 handoff는 superseded. Called by
    ``artifacts.revise_blueprint`` right after a new blueprint version lands.
    """
    current = db.execute(
        "SELECT MAX(version) FROM vo_blueprints WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    if current is None:
        return []
    project = load_project(db, project_id)
    superseded: list[str] = []
    for row in db.execute(
        "SELECT * FROM vo_handoffs WHERE project_id = ? ORDER BY created_at", (project_id,)
    ).fetchall():
        if coerce_handoff_status(row["status"]) not in LIVE_HANDOFF_STATUSES:
            continue
        recorded = json.loads(row["input_versions_json"]).get(INPUT_PROJECT_BLUEPRINT)
        if recorded == current:
            continue
        set_handoff_status(
            db,
            project,
            row["id"],
            HandoffStatus.SUPERSEDED,
            rejection_reasons=[reason],
        )
        superseded.append(row["id"])
    return superseded


def latest_live_handoff(db: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    """Newest handoff that has not been rejected or superseded."""
    for row in db.execute(
        "SELECT * FROM vo_handoffs WHERE project_id = ? ORDER BY created_at DESC, id DESC",
        (project_id,),
    ).fetchall():
        if coerce_handoff_status(row["status"]) in LIVE_HANDOFF_STATUSES:
            return row
    return None


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #


def create_handoff(project_id: str) -> dict[str, Any]:
    """Build the planning -> design envelope from the approved blueprint.

    Raises ``blueprint.HandoffRejected`` when the project has not passed planning
    approval (409).  When the blueprint *is* approved but violates a 05A section 3
    rejection condition, the envelope is still created and persisted - with status
    ``rejected`` and Korean reasons - because the refusal itself is the artifact
    the planning department has to act on.
    """
    # Reads the blueprint through the one sanctioned gate. Never touch
    # vo_blueprints directly here: that is how an unapproved draft leaks.
    approved = blueprint_service.approved_blueprint_for_handoff(project_id)
    content = approved["blueprint"]
    reasons = evaluate_rejection_reasons(content)

    with s2_database() as db:
        project = load_project(db, project_id)

        # 05A section 10 supersedes on *input change*: "승인 후 입력 산출물이 바뀌면".
        # A plain re-POST with an unchanged blueprint version is not that event, so
        # it must not retire a perfectly valid contract.  We return the existing
        # live envelope instead of raising 409: the rest of the S1/S2 surface is
        # idempotent (``intake``, ``blueprint/generate``), a client retrying after a
        # dropped response should not have to distinguish "already created" from
        # "cannot create", and there is nothing for the caller to fix - the answer
        # to "give me the handoff for this approved blueprint" already exists.
        # ``reused`` in the payload tells the caller nothing new was written.
        existing = latest_live_handoff(db, project_id)
        if existing is not None:
            recorded = json.loads(existing["input_versions_json"]).get(INPUT_PROJECT_BLUEPRINT)
            if recorded == approved["version"]:
                payload = _payload(db, existing)
                payload["summary"] = derive_handoff_summary(content)
                payload["project_state"] = project["state"]
                payload["reused"] = True
                return payload

        # ``supersedes`` points at the newest predecessor whatever its status: the
        # successor replaces it either way, and 05A section 10 wants the chain to
        # stay walkable. If the predecessor is still live it is superseded *first*
        # so the shared envelope file ends up holding the new contract.
        previous = db.execute(
            "SELECT * FROM vo_handoffs WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        supersedes = previous["id"] if previous is not None else None
        handoff_id = _next_handoff_id(db, project_id)
        now = utc_now()
        status = HandoffStatus.REJECTED if reasons else HandoffStatus.READY_FOR_REVIEW
        if previous is not None and coerce_handoff_status(previous["status"]) in LIVE_HANDOFF_STATUSES:
            set_handoff_status(
                db,
                project,
                previous["id"],
                HandoffStatus.SUPERSEDED,
                rejection_reasons=[f"{handoff_id}이(가) 이 인계를 대체했습니다."],
            )
        db.execute(
            "INSERT INTO vo_handoffs (id, project_id, from_dept, to_dept, status, input_versions_json, "
            "required_outputs_json, constraints_json, acceptance_json, open_decisions_json, "
            "rejection_reasons_json, approved_by, path, sha256, supersedes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)",
            (
                handoff_id,
                project_id,
                DEPARTMENT_PLANNING,
                DEPARTMENT_DESIGN,
                status.value,
                json.dumps({INPUT_PROJECT_BLUEPRINT: approved["version"]}, ensure_ascii=False),
                json.dumps(list(REQUIRED_OUTPUTS), ensure_ascii=False),
                json.dumps(derive_constraints(content), ensure_ascii=False),
                json.dumps(derive_acceptance_criteria(content), ensure_ascii=False),
                json.dumps(derive_open_decisions(content), ensure_ascii=False),
                json.dumps(reasons, ensure_ascii=False),
                supersedes,
                now,
                now,
            ),
        )
        row = _handoff_row(db, project_id, handoff_id)
        _persist_envelope(db, project, row)
        if reasons:
            set_project_state(db, project_id, ProjectState.HANDOFF_REJECTED)
        row = _handoff_row(db, project_id, handoff_id)
        payload = _payload(db, row)
        payload["summary"] = derive_handoff_summary(content)
        payload["project_state"] = load_project(db, project_id)["state"]
        payload["reused"] = False
        return payload


def list_handoffs(project_id: str) -> dict[str, Any]:
    with s2_database() as db:
        load_project(db, project_id)
        rows = db.execute(
            "SELECT * FROM vo_handoffs WHERE project_id = ? ORDER BY created_at, id", (project_id,)
        ).fetchall()
        return {"project_id": project_id, "handoffs": [_payload(db, row) for row in rows]}


def get_handoff(project_id: str, handoff_id: str) -> dict[str, Any]:
    """One envelope by id. Exposed via ``GET /handoffs/{handoff_id}``."""
    with s2_database() as db:
        load_project(db, project_id)
        return _payload(db, _handoff_row(db, project_id, handoff_id))


def approve_handoff(project_id: str, handoff_id: str, *, approved_by: str = "user") -> dict[str, Any]:
    """Approve the envelope and open the design department.

    Rejected/superseded handoffs cannot be approved - the status machine refuses
    the transition, which the routes map to 409.
    """
    with s2_database() as db:
        project = load_project(db, project_id)
        row = _handoff_row(db, project_id, handoff_id)
        status = coerce_handoff_status(row["status"])
        if status is HandoffStatus.REJECTED:
            raise HandoffRejectedError(
                "거부된 인계는 승인할 수 없습니다. 기획 산출물을 고친 뒤 새 인계를 만들어야 합니다."
            )
        if status is HandoffStatus.SUPERSEDED:
            raise HandoffRejectedError("이 인계는 이미 다른 인계로 대체되었습니다.")
        updated = set_handoff_status(
            db, project, handoff_id, HandoffStatus.APPROVED, approved_by=approved_by
        )
        # The *project* deliberately stays in PLANNING_APPROVED here.  S1's
        # ``approved_blueprint_for_handoff`` gate is state-based, so moving to
        # DESIGN at approval time would lock the design department out of the one
        # sanctioned blueprint reader.  ``design.run_design`` performs
        # PLANNING_APPROVED -> DESIGN -> DESIGN_REVIEW once it has read the input.
        payload = _payload(db, updated)
        payload["project_state"] = load_project(db, project_id)["state"]
        return payload


def require_approved_handoff(db: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    """The approved envelope the design department is allowed to work from."""
    row = latest_live_handoff(db, project_id)
    if row is None:
        raise HandoffRejectedError("승인된 인계 계약이 없어 디자인 작업을 시작할 수 없습니다.")
    status = coerce_handoff_status(row["status"])
    if status not in (HandoffStatus.APPROVED, HandoffStatus.IN_PROGRESS):
        raise HandoffRejectedError(
            f"인계가 아직 승인되지 않았습니다 (현재 상태: {status.value}). 인계 승인 후 다시 실행하세요."
        )
    current = db.execute(
        "SELECT MAX(version) FROM vo_blueprints WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    recorded = json.loads(row["input_versions_json"]).get(INPUT_PROJECT_BLUEPRINT)
    if recorded != current:
        raise HandoffRejectedError(
            f"인계가 참조하는 blueprint v{recorded}가 최신(v{current})이 아닙니다. 새 인계를 만들어야 합니다."
        )
    return row


__all__ = [
    "HANDOFF_ID_TEMPLATE",
    "INPUT_PROJECT_BLUEPRINT",
    "MIN_RATIONALE_CHARS",
    "OBSERVABLE_ACTION_STEMS",
    "PERSONA_CONFLICT_GROUPS",
    "PLANNING_REQUIRED_INPUTS",
    "REQUIRED_OUTPUTS",
    "STRUCTURAL_DECISION_LABELS",
    "names_observable_action",
    "persona_group",
    "HandoffNotFound",
    "HandoffRejectedError",
    "HandoffSchemaError",
    "approve_handoff",
    "create_handoff",
    "derive_acceptance_criteria",
    "derive_constraints",
    "derive_handoff_summary",
    "derive_open_decisions",
    "evaluate_rejection_reasons",
    "get_handoff",
    "latest_live_handoff",
    "list_handoffs",
    "require_approved_handoff",
    "set_handoff_status",
    "supersede_live_handoffs",
    "validate_handoff",
    "BLUEPRINT_DIRNAME",
    "ProjectNotFound",
    "StateTransitionError",
]
