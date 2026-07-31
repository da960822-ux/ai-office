"""Additive SQLite tables and the project state machine for VibeOffice S1.

Design decisions worth keeping:

* We reuse the existing ``data/ai-office.sqlite3`` database and only add
  tables.  No separate database, no migration framework.  ``CREATE TABLE IF
  NOT EXISTS`` keeps ``init_vibeoffice_schema`` idempotent, so it is safe to
  call on every request.
* ``apps.api.main`` is imported **inside function bodies only**.  Importing it
  at module scope would create a cycle once ``main`` includes the router, and
  it would freeze ``DB_PATH`` at import time.  Existing tests swap
  ``main.DB_PATH`` for a temp file and call ``main.init_db()``
  (see ``apps/api/test_workflow_acceptance.py``); the lazy import makes those
  tests work here for free.
* State values are validated in Python (``coerce_state``), not with a SQL
  CHECK constraint.  A CHECK generated from the enum would be baked into the
  table at first creation and silently drift from the enum once later slices
  add states - a migration trap for a guarantee we can enforce in one place.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator


class ProjectState(str, Enum):
    """Project states from VIBEOFFICE_IMPLEMENTATION_GUIDE.md section 5.

    The full machine is declared here even though S1 only drives the planning
    prefix, so later slices extend transitions instead of redefining values.
    """

    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    PLANNING_REVIEW = "PLANNING_REVIEW"
    PLANNING_APPROVED = "PLANNING_APPROVED"
    DESIGN = "DESIGN"
    DESIGN_REVIEW = "DESIGN_REVIEW"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    ARCHITECTURE = "ARCHITECTURE"
    ARCHITECTURE_REVIEW = "ARCHITECTURE_REVIEW"
    BUILD = "BUILD"
    BUILD_VERIFICATION = "BUILD_VERIFICATION"
    QA = "QA"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    SHIPPING_READY = "SHIPPING_READY"
    SHIPPING = "SHIPPING"
    EXPORTED = "EXPORTED"
    # Exception states
    NEEDS_USER_DECISION = "NEEDS_USER_DECISION"
    HANDOFF_REJECTED = "HANDOFF_REJECTED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    STRUCTURAL_REPLAN = "STRUCTURAL_REPLAN"
    STALE_ARTIFACTS = "STALE_ARTIFACTS"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"


#: States slice S1 is allowed to produce.  Anything else means a later slice
#: leaked into the planning flow.
S1_STATES = frozenset(
    {
        ProjectState.DRAFT,
        ProjectState.PLANNING,
        ProjectState.PLANNING_REVIEW,
        ProjectState.PLANNING_APPROVED,
        ProjectState.NEEDS_USER_DECISION,
    }
)

#: Legal S1 transitions.  Self transitions are allowed where the endpoint is
#: idempotent (re-running intake, regenerating a not-yet-approved blueprint).
#: ``PLANNING_APPROVED`` is terminal in S1: an approved blueprint is frozen and
#: only S2 (versioning + handoff) may move past it.
S1_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    ProjectState.DRAFT: frozenset({ProjectState.PLANNING, ProjectState.NEEDS_USER_DECISION}),
    ProjectState.PLANNING: frozenset(
        {ProjectState.PLANNING, ProjectState.NEEDS_USER_DECISION, ProjectState.PLANNING_REVIEW}
    ),
    ProjectState.NEEDS_USER_DECISION: frozenset(
        {ProjectState.PLANNING, ProjectState.NEEDS_USER_DECISION, ProjectState.PLANNING_REVIEW}
    ),
    ProjectState.PLANNING_REVIEW: frozenset(
        {
            ProjectState.PLANNING,
            ProjectState.NEEDS_USER_DECISION,
            ProjectState.PLANNING_REVIEW,
            ProjectState.PLANNING_APPROVED,
        }
    ),
    ProjectState.PLANNING_APPROVED: frozenset(),
}

#: Delivery modes (guide section "출고": Quick H3+, Standard H4, Quality H5).
MODES = ("quick", "standard", "quality")

#: ``constraints.skillLevel`` enum in project-blueprint.schema.json.
SKILL_LEVELS = ("beginner", "intermediate")

BLUEPRINT_DIRNAME = ".vibeoffice"
BLUEPRINT_FILENAME = "project-blueprint.json"


class ProjectNotFound(LookupError):
    """Raised when a vo_projects row does not exist. Routes map this to 404."""


class StateTransitionError(RuntimeError):
    """Illegal state transition. Routes map this to 409.

    ``reason`` is user-facing Korean text.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def coerce_state(raw: str | ProjectState) -> ProjectState:
    """Convert a stored string into ``ProjectState`` or fail loudly.

    Guards the "no undefined state string in the DB" requirement.
    """
    if isinstance(raw, ProjectState):
        return raw
    try:
        return ProjectState(raw)
    except ValueError as error:
        raise ValueError(f"Unknown VibeOffice project state: {raw!r}") from error


def require_s1_transition(current: str | ProjectState, target: str | ProjectState) -> ProjectState:
    """Validate an S1 transition and return the target state.

    Raises ``StateTransitionError`` with a Korean reason the API can surface.
    """
    current_state = coerce_state(current)
    target_state = coerce_state(target)
    if current_state not in S1_STATES:
        raise StateTransitionError(
            f"이 프로젝트는 기획 단계를 벗어난 상태({current_state.value})라 기획 작업을 진행할 수 없습니다."
        )
    if target_state not in S1_STATES:
        raise StateTransitionError(f"기획 슬라이스에서 사용할 수 없는 상태입니다: {target_state.value}")
    if target_state not in S1_TRANSITIONS[current_state]:
        raise StateTransitionError(
            f"현재 상태 {current_state.value}에서 {target_state.value}(으)로 넘어갈 수 없습니다."
        )
    return target_state


def utc_now() -> str:
    """Reuse main's timestamp format so both layers sort identically."""
    from apps.api.main import utc_now as main_utc_now  # lazy: see module docstring

    return main_utc_now()


# --------------------------------------------------------------------------- #
# Slice S2: design states, handoff status machine, handoff/design file layout
# --------------------------------------------------------------------------- #

#: States slice S2 adds on top of ``S1_STATES``.  ``S1_STATES``/``S1_TRANSITIONS``
#: are left untouched on purpose: ``require_s1_transition`` is the contract the
#: S1 test suite pins down ("planning may not jump into DESIGN"), so S2 *extends*
#: the machine with a second table instead of rewriting the first one.
S2_STATES = frozenset(
    {
        ProjectState.PLANNING_APPROVED,
        ProjectState.DESIGN,
        ProjectState.DESIGN_REVIEW,
        ProjectState.DESIGN_APPROVED,
        ProjectState.HANDOFF_REJECTED,
        ProjectState.REWORK_REQUIRED,
        ProjectState.STALE_ARTIFACTS,
    }
)

#: Legal S2 transitions.  ``PLANNING_APPROVED`` is terminal in S1; S2 is the
#: slice that is allowed to move past it, and only through a handoff.
#: ``HANDOFF_REJECTED`` routes back to planning (guide section 9: 사용자·문제·범위
#: problems are owned by Planning), never forward into design.
#:
#: ``REWORK_REQUIRED`` is the Gate C 반송 state (09A Gate C / guide section 8: a
#: Gate C violation sends the design work back).  It is reachable from
#: ``PLANNING_APPROVED`` because ``design.run_design`` runs Gate C on the
#: in-memory package *before* it moves the project into ``DESIGN``, so a bounce
#: happens while the project is still sitting on the planning approval.  No new
#: state was invented for this: ``REWORK_REQUIRED`` already means "the department
#: that produced this has to fix it", which is exactly a Gate C failure, whereas
#: ``HANDOFF_REJECTED`` means the *input* from the previous department is wrong.
S2_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    ProjectState.PLANNING_APPROVED: frozenset(
        {
            ProjectState.DESIGN,
            ProjectState.HANDOFF_REJECTED,
            ProjectState.REWORK_REQUIRED,
            ProjectState.STALE_ARTIFACTS,
        }
    ),
    ProjectState.DESIGN: frozenset(
        {
            ProjectState.DESIGN,
            ProjectState.DESIGN_REVIEW,
            ProjectState.HANDOFF_REJECTED,
            ProjectState.REWORK_REQUIRED,
            ProjectState.STALE_ARTIFACTS,
        }
    ),
    ProjectState.DESIGN_REVIEW: frozenset(
        {
            ProjectState.DESIGN,
            ProjectState.DESIGN_REVIEW,
            ProjectState.DESIGN_APPROVED,
            ProjectState.HANDOFF_REJECTED,
            ProjectState.STALE_ARTIFACTS,
        }
    ),
    ProjectState.DESIGN_APPROVED: frozenset({ProjectState.STALE_ARTIFACTS}),
    #: ``STALE_ARTIFACTS`` is reachable from ``HANDOFF_REJECTED`` because the
    #: natural repair for a refused handoff is to revise the blueprint, and
    #: ``artifacts.revise_blueprint`` walks STALE_ARTIFACTS -> PLANNING_REVIEW.
    #: Without this edge that repair path dead-ends.
    ProjectState.HANDOFF_REJECTED: frozenset(
        {ProjectState.PLANNING, ProjectState.PLANNING_REVIEW, ProjectState.STALE_ARTIFACTS}
    ),
    #: Gate C 반송 exits: revise the blueprint (STALE_ARTIFACTS -> PLANNING_REVIEW),
    #: re-plan, or re-run design once the generator is fixed.
    ProjectState.REWORK_REQUIRED: frozenset(
        {
            # Self-loop: re-running design while the generator is still broken
            # bounces again instead of raising "illegal transition" on top of the
            # real Gate C failure. Every other retryable state above (DESIGN,
            # DESIGN_REVIEW) already allows this; REWORK_REQUIRED was missed.
            ProjectState.REWORK_REQUIRED,
            ProjectState.DESIGN,
            ProjectState.PLANNING,
            ProjectState.PLANNING_REVIEW,
            ProjectState.STALE_ARTIFACTS,
        }
    ),
    ProjectState.STALE_ARTIFACTS: frozenset(
        {ProjectState.DESIGN, ProjectState.PLANNING_REVIEW, ProjectState.STALE_ARTIFACTS}
    ),
}


#: Slice S3: design approval -> architecture contract (auto, no user approval -
#: guide section 10 lists exactly 3 user approvals: planning, design, shipping).
#: ``ARCHITECTURE_REVIEW`` is terminal until S4 (BUILD) adds the next edge, the
#: same way ``DESIGN_APPROVED`` was terminal (bar stale) before this slice.
S3_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    #: ``REWORK_REQUIRED`` here is the Gate D/E bounce - it fires *before* the
    #: project ever enters ``ARCHITECTURE`` (same shape as design.py's Gate C
    #: bounce firing while still on ``PLANNING_APPROVED``).
    ProjectState.DESIGN_APPROVED: frozenset(
        {ProjectState.ARCHITECTURE, ProjectState.REWORK_REQUIRED, ProjectState.STALE_ARTIFACTS}
    ),
    ProjectState.ARCHITECTURE: frozenset(
        {ProjectState.ARCHITECTURE, ProjectState.ARCHITECTURE_REVIEW, ProjectState.REWORK_REQUIRED}
    ),
    #: Gate D/E 반송 exit (guide section 9: API·DB·인증·아키텍처 문제 -> Architecture).
    #: Re-running architecture is the repair path; REWORK_REQUIRED already routes to
    #: DESIGN too (Gate C bounce), so an architecture bounce that turns out to be a
    #: design problem still has a way back.
    ProjectState.REWORK_REQUIRED: frozenset({ProjectState.ARCHITECTURE, ProjectState.ARCHITECTURE_REVIEW}),
}

#: Slice S3.5: Product Execution Baseline (PRD.md, decision-register.json,
#: risk-register.json, traceability-map.json). The guide's own state list has no
#: dedicated state for this slice - it fixes *derivative* artifacts on top of the
#: already-approved architecture, it does not advance the pipeline (guide section
#: 7 S3.5: "기존 Planning 산출물을 대체하지 않는다"). So this slice stays on
#: ``ARCHITECTURE_REVIEW`` on success and only ever leaves it for a Gate PE bounce.
S35_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    #: ``STALE_ARTIFACTS`` is included because ``CHANGE_TECH_STACK``'s impact set
    #: now reaches the S3 architecture package (API_CONTRACT/DATA_MODEL/
    #: TECHNICAL_TASKS - see ``artifacts.STALE_IMPACT``), so a tech-stack
    #: revision has to be able to fire ``artifacts.revise_blueprint`` while the
    #: project is sitting on ``ARCHITECTURE_REVIEW``, the same way it already
    #: could from ``DESIGN_APPROVED`` in ``S3_TRANSITIONS``. Without this edge a
    #: revision that should only invalidate architecture docs was unreachable
    #: past design approval.
    ProjectState.ARCHITECTURE_REVIEW: frozenset(
        {ProjectState.ARCHITECTURE_REVIEW, ProjectState.REWORK_REQUIRED, ProjectState.STALE_ARTIFACTS}
    ),
    #: Repair path back from a Gate PE bounce, plus a self-loop for a second
    #: failed retry (same shape as ``STALE_ARTIFACTS``'s own self-loop).
    ProjectState.REWORK_REQUIRED: frozenset(
        {ProjectState.ARCHITECTURE_REVIEW, ProjectState.REWORK_REQUIRED}
    ),
}


#: Slice S4: 기술설계 승인 -> 내부 MVP 빌드. Unlike S3.5, this one *does* have
#: dedicated states in the guide's canonical list (section 5): ``BUILD`` while
#: the scaffold/build/test commands run, ``BUILD_VERIFICATION`` once evidence is
#: recorded. Gate F 반송 (guide section 9: 코드·빌드·테스트 문제 -> Build) fires
#: while still on ``ARCHITECTURE_REVIEW`` - S3.5 already legalised that edge.
S4_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    ProjectState.ARCHITECTURE_REVIEW: frozenset({ProjectState.BUILD}),
    ProjectState.BUILD: frozenset({ProjectState.BUILD_VERIFICATION}),
    #: Retry path after a Gate F bounce - mirrors ``REWORK_REQUIRED -> ARCHITECTURE``
    #: in S3_TRANSITIONS.
    ProjectState.REWORK_REQUIRED: frozenset({ProjectState.BUILD}),
}


def _merged_transitions() -> dict[ProjectState, frozenset[ProjectState]]:
    """Union of the S1/S2/S3/S3.5/S4 tables, keyed by every state any one mentions."""
    merged: dict[ProjectState, frozenset[ProjectState]] = {}
    for table in (S1_TRANSITIONS, S2_TRANSITIONS, S3_TRANSITIONS, S35_TRANSITIONS, S4_TRANSITIONS):
        for state, targets in table.items():
            merged[state] = merged.get(state, frozenset()) | targets
    return merged


#: The machine ``set_project_state`` actually enforces.  Built by union so a
#: later slice can never silently loosen an earlier slice's table.
TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = _merged_transitions()


class HandoffStatus(str, Enum):
    """Handoff statuses from 05A_DEPARTMENT_HANDOFF_CONTRACTS.md section 9.

    Exactly these eight strings, spelled the way the ``status`` enum in
    ``department-handoff.schema.json`` spells them.  Nothing else may reach
    ``vo_handoffs.status``.
    """

    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


#: Handoff lifecycle.  ``rejected`` is terminal: a 05A section 3 rejection
#: bounces work back to the previous department, which produces a *new* envelope
#: rather than resurrecting the refused one.  ``superseded`` is terminal for the
#: same reason (section 10: a changed input creates a successor envelope).
HANDOFF_TRANSITIONS: dict[HandoffStatus, frozenset[HandoffStatus]] = {
    HandoffStatus.DRAFT: frozenset(
        {HandoffStatus.READY_FOR_REVIEW, HandoffStatus.REJECTED, HandoffStatus.SUPERSEDED}
    ),
    HandoffStatus.READY_FOR_REVIEW: frozenset(
        {
            HandoffStatus.APPROVED,
            HandoffStatus.CHANGES_REQUESTED,
            HandoffStatus.REJECTED,
            HandoffStatus.SUPERSEDED,
        }
    ),
    HandoffStatus.CHANGES_REQUESTED: frozenset(
        {HandoffStatus.READY_FOR_REVIEW, HandoffStatus.REJECTED, HandoffStatus.SUPERSEDED}
    ),
    HandoffStatus.APPROVED: frozenset(
        {HandoffStatus.IN_PROGRESS, HandoffStatus.CHANGES_REQUESTED, HandoffStatus.SUPERSEDED}
    ),
    HandoffStatus.IN_PROGRESS: frozenset(
        {HandoffStatus.COMPLETED, HandoffStatus.CHANGES_REQUESTED, HandoffStatus.SUPERSEDED}
    ),
    HandoffStatus.COMPLETED: frozenset({HandoffStatus.SUPERSEDED}),
    HandoffStatus.REJECTED: frozenset(),
    HandoffStatus.SUPERSEDED: frozenset(),
}

#: Statuses whose recorded inputs are still live, so a blueprint revision has to
#: supersede them (05A section 10).
LIVE_HANDOFF_STATUSES = frozenset(
    {
        HandoffStatus.DRAFT,
        HandoffStatus.READY_FOR_REVIEW,
        HandoffStatus.CHANGES_REQUESTED,
        HandoffStatus.APPROVED,
        HandoffStatus.IN_PROGRESS,
        HandoffStatus.COMPLETED,
    }
)

DEPARTMENT_PLANNING = "planning"
DEPARTMENT_DESIGN = "design"

#: Gate C screen bounds (09A section 3 Gate C, guide section 7 S2: "화면 3~7개").
#: Declared here rather than in ``design`` because the handoff envelope has to
#: state the same number as a constraint, and two copies would drift.
GATE_C_MIN_SCREENS = 3
GATE_C_MAX_SCREENS = 7

HANDOFF_DIRNAME = f"{BLUEPRINT_DIRNAME}/handoffs"
PLANNING_TO_DESIGN_FILENAME = "planning-to-design.json"

#: Design Package documents land in ``<workspace>/docs/`` (guide section 5).
DOCS_DIRNAME = "docs"


def coerce_handoff_status(raw: str | HandoffStatus) -> HandoffStatus:
    """Convert a stored string into ``HandoffStatus`` or fail loudly."""
    if isinstance(raw, HandoffStatus):
        return raw
    try:
        return HandoffStatus(raw)
    except ValueError as error:
        raise ValueError(f"Unknown VibeOffice handoff status: {raw!r}") from error


def require_handoff_transition(current: str | HandoffStatus, target: str | HandoffStatus) -> HandoffStatus:
    """Validate a handoff status transition and return the target status."""
    current_status = coerce_handoff_status(current)
    target_status = coerce_handoff_status(target)
    if target_status not in HANDOFF_TRANSITIONS[current_status]:
        raise StateTransitionError(
            f"인계 상태 {current_status.value}에서 {target_status.value}(으)로 바꿀 수 없습니다."
        )
    return target_status


def require_transition(current: str | ProjectState, target: str | ProjectState) -> ProjectState:
    """Validate a project transition against the merged S1+S2 machine."""
    current_state = coerce_state(current)
    target_state = coerce_state(target)
    if target_state not in TRANSITIONS.get(current_state, frozenset()):
        raise StateTransitionError(
            f"현재 상태 {current_state.value}에서 {target_state.value}(으)로 넘어갈 수 없습니다."
        )
    return target_state


def init_vibeoffice_schema(conn: sqlite3.Connection) -> None:
    """Create the VibeOffice tables if they are missing. Idempotent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vo_projects (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            name TEXT NOT NULL,
            mode TEXT NOT NULL,
            skill_level TEXT NOT NULL,
            team_size INTEGER,
            deadline TEXT,
            state TEXT NOT NULL,
            workspace_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vo_blueprints (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content_json TEXT,
            inference_json TEXT,
            questions_json TEXT,
            answers_json TEXT,
            path TEXT,
            sha256 TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (project_id, version)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vo_blueprints_project ON vo_blueprints (project_id)")


def init_s2_schema(conn: sqlite3.Connection) -> None:
    """Create the S2 handoff/artifact tables if they are missing. Idempotent.

    Kept as a *separate* entry point rather than appended to
    ``init_vibeoffice_schema`` for one reason: the S1 acceptance suite asserts
    that the planning slice owns exactly ``vo_projects`` and ``vo_blueprints``.
    That assertion is worth keeping - it is what stops a later slice from
    quietly attaching tables to the planning flow - so S2 declares its own
    creator and its own connection helper (``s2_database``).  Both creators are
    ``CREATE TABLE IF NOT EXISTS``, so calling either one on every request is
    free.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vo_handoffs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            from_dept TEXT NOT NULL,
            to_dept TEXT NOT NULL,
            status TEXT NOT NULL,
            input_versions_json TEXT NOT NULL,
            required_outputs_json TEXT NOT NULL,
            constraints_json TEXT NOT NULL,
            acceptance_json TEXT NOT NULL,
            open_decisions_json TEXT NOT NULL,
            rejection_reasons_json TEXT,
            approved_by TEXT,
            path TEXT,
            sha256 TEXT,
            supersedes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vo_handoffs_project ON vo_handoffs (project_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vo_artifacts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL,
            current_version_id TEXT,
            depends_on_json TEXT NOT NULL,
            stale INTEGER NOT NULL DEFAULT 0,
            stale_reason TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (project_id, type)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vo_artifact_versions (
            id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            source_blueprint_version INTEGER NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (artifact_id, version)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vo_artifact_versions_artifact "
        "ON vo_artifact_versions (artifact_id)"
    )


@contextmanager
def vibeoffice_database() -> Iterator[sqlite3.Connection]:
    """Shared AI Office connection with the VibeOffice tables ensured."""
    from apps.api.main import database  # lazy: see module docstring

    with database() as db:
        init_vibeoffice_schema(db)
        yield db


@contextmanager
def s2_database() -> Iterator[sqlite3.Connection]:
    """``vibeoffice_database`` plus the S2 handoff/artifact tables."""
    with vibeoffice_database() as db:
        init_s2_schema(db)
        yield db


def default_workspace_root() -> Path:
    """Where project workspaces live when the caller does not supply a path.

    Derived from ``main.DB_PATH`` on purpose: tests that repoint the database at
    a temp directory get their workspaces in the same temp directory, so no test
    writes into the real repository.
    """
    from apps.api.main import DB_PATH  # lazy: value must be read per call

    return Path(DB_PATH).resolve().parent / "vo-workspaces"


def load_project(db: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM vo_projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFound(f"VibeOffice project not found: {project_id}")
    return row


def next_project_id(db: sqlite3.Connection) -> str:
    """Sequential id in the repo's existing style (``PROJECT-001``/``TASK-001``)."""
    sequence = db.execute("SELECT COUNT(*) FROM vo_projects").fetchone()[0] + 1
    candidate = f"VOP-{sequence:03d}"
    while db.execute("SELECT 1 FROM vo_projects WHERE id = ?", (candidate,)).fetchone():
        sequence += 1
        candidate = f"VOP-{sequence:03d}"
    return candidate


def set_project_state(db: sqlite3.Connection, project_id: str, target: str | ProjectState) -> ProjectState:
    """Apply a validated transition (merged S1+S2 machine) and stamp ``updated_at``."""
    row = load_project(db, project_id)
    state = require_transition(row["state"], target)
    db.execute(
        "UPDATE vo_projects SET state = ?, updated_at = ? WHERE id = ?",
        (state.value, utc_now(), project_id),
    )
    return state
