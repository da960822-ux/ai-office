"""Artifact versioning, workspace mirroring and stale propagation (slice S2).

Invariants this module owns:

* **One ``vo_artifacts`` row per artifact, N ``vo_artifact_versions`` rows.**
  ``current_version_id`` points at the newest version; history is never
  rewritten.  Regenerating an artifact appends a version, it does not edit one.
* **File and DB are written together, and the hash comes from disk.**  Same rule
  as ``blueprint._write_blueprint_file``: the file is the artifact, the sha256 is
  the proof, and the stored path is *relative* so exported artifacts never leak a
  local absolute path (guide section 11).
* **Stale is a targeted signal, not a rebuild trigger.**  Guide section 9 says
  최소 영향 수정 is the default: a blueprint revision marks only the artifacts the
  change can actually invalidate, and it records *why* in ``stale_reason`` so the
  owning department can repair instead of regenerate.  ``STALE_IMPACT`` is
  therefore keyed by *kind of change*, not by "everything downstream".  Widening
  those sets to "all artifacts" would technically be safe and would destroy the
  whole point of the rule.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from apps.api.vibeoffice.schema import (
    BLUEPRINT_DIRNAME,
    DOCS_DIRNAME,
    ProjectNotFound,
    ProjectState,
    load_project,
    require_transition,
    s2_database,
    set_project_state,
    utc_now,
)

# --------------------------------------------------------------------------- #
# Artifact catalogue (06_OUTPUT_STANDARD Design Package)
# --------------------------------------------------------------------------- #

ARTIFACT_INFORMATION_ARCHITECTURE = "information_architecture"
ARTIFACT_USER_FLOWS = "user_flows"
ARTIFACT_SCREEN_SPEC = "screen_spec"
ARTIFACT_DESIGN_SYSTEM = "design_system"
ARTIFACT_COMPONENT_INVENTORY = "component_inventory"

#: Generation order matters: later documents reference the screen ids the
#: SCREEN_SPEC assigns, so the order is also the reading order for a human.
DESIGN_PACKAGE_TYPES: tuple[str, ...] = (
    ARTIFACT_INFORMATION_ARCHITECTURE,
    ARTIFACT_USER_FLOWS,
    ARTIFACT_SCREEN_SPEC,
    ARTIFACT_DESIGN_SYSTEM,
    ARTIFACT_COMPONENT_INVENTORY,
)

ARTIFACT_FILENAMES: dict[str, str] = {
    ARTIFACT_INFORMATION_ARCHITECTURE: "INFORMATION_ARCHITECTURE.md",
    ARTIFACT_USER_FLOWS: "USER_FLOWS.md",
    ARTIFACT_SCREEN_SPEC: "SCREEN_SPEC.md",
    ARTIFACT_DESIGN_SYSTEM: "DESIGN_SYSTEM.md",
    ARTIFACT_COMPONENT_INVENTORY: "COMPONENT_INVENTORY.md",
}

#: ``artifact_id`` value used in the artifact header (06_OUTPUT_STANDARD).
ARTIFACT_IDS: dict[str, str] = {
    ARTIFACT_INFORMATION_ARCHITECTURE: "information-architecture",
    ARTIFACT_USER_FLOWS: "user-flows",
    ARTIFACT_SCREEN_SPEC: "screen-spec",
    ARTIFACT_DESIGN_SYSTEM: "design-system",
    ARTIFACT_COMPONENT_INVENTORY: "component-inventory",
}

#: Artifact lifecycle labels from 09A section 6. S2 only produces ``proposed``;
#: promotion to implemented/verified needs evidence, which arrives in S4/S5.
ARTIFACT_STATUS_PROPOSED = "proposed"

#: The design department that owns these documents (guide section 4).
DESIGN_OWNER = "MOSS"

# --------------------------------------------------------------------------- #
# Slice S3: Architecture contract (API_CONTRACT / DATA_MODEL / TECHNICAL_TASKS)
# --------------------------------------------------------------------------- #

ARTIFACT_API_CONTRACT = "api_contract"
ARTIFACT_DATA_MODEL = "data_model"
ARTIFACT_TECHNICAL_TASKS = "technical_tasks"

#: Generation order: tasks reference endpoints and entities, so it reads last.
ARCHITECTURE_PACKAGE_TYPES: tuple[str, ...] = (
    ARTIFACT_API_CONTRACT,
    ARTIFACT_DATA_MODEL,
    ARTIFACT_TECHNICAL_TASKS,
)

#: ``record_artifact``/``list_artifacts``/``get_artifact`` are generic over
#: ``ARTIFACT_FILENAMES`` already, so appending these three entries is the whole
#: integration - no other function in this module changes for slice S3.
ARTIFACT_FILENAMES[ARTIFACT_API_CONTRACT] = "API_CONTRACT.yaml"
ARTIFACT_FILENAMES[ARTIFACT_DATA_MODEL] = "DATA_MODEL.md"
ARTIFACT_FILENAMES[ARTIFACT_TECHNICAL_TASKS] = "TECHNICAL_TASKS.md"

ARTIFACT_IDS[ARTIFACT_API_CONTRACT] = "api-contract"
ARTIFACT_IDS[ARTIFACT_DATA_MODEL] = "data-model"
ARTIFACT_IDS[ARTIFACT_TECHNICAL_TASKS] = "technical-tasks"

#: The architecture department that owns these documents (guide section 4).
ARCHITECTURE_OWNER = "BUILD"

# --------------------------------------------------------------------------- #
# Slice S3.5: Product Execution Baseline (PRD / decision-register /
# risk-register / traceability-map). All four are written through the same
# ``_write_doc`` -> ``docs/`` path as every other artifact in this module - the
# guide's file tree sketch (section 5) does not actually pin these three JSON
# registers to ``.vibeoffice/``, and splitting the writer for three artifacts
# would be a second file-location system for no behavioural gain (nothing else
# reads these paths by convention; they come from the DB row either way).
# --------------------------------------------------------------------------- #

ARTIFACT_PRD = "prd"
ARTIFACT_DECISION_REGISTER = "decision_register"
ARTIFACT_RISK_REGISTER = "risk_register"
ARTIFACT_TRACEABILITY = "traceability"
ARTIFACT_TRACEABILITY_MAP = "traceability_map"

EXECUTION_BASELINE_TYPES: tuple[str, ...] = (
    ARTIFACT_PRD,
    ARTIFACT_DECISION_REGISTER,
    ARTIFACT_RISK_REGISTER,
    ARTIFACT_TRACEABILITY,
    ARTIFACT_TRACEABILITY_MAP,
)

ARTIFACT_FILENAMES[ARTIFACT_PRD] = "PRD.md"
ARTIFACT_FILENAMES[ARTIFACT_DECISION_REGISTER] = "decision-register.json"
ARTIFACT_FILENAMES[ARTIFACT_RISK_REGISTER] = "risk-register.json"
ARTIFACT_FILENAMES[ARTIFACT_TRACEABILITY] = "TRACEABILITY.md"
ARTIFACT_FILENAMES[ARTIFACT_TRACEABILITY_MAP] = "traceability-map.json"

ARTIFACT_IDS[ARTIFACT_PRD] = "prd"
ARTIFACT_IDS[ARTIFACT_DECISION_REGISTER] = "decision-register"
ARTIFACT_IDS[ARTIFACT_RISK_REGISTER] = "risk-register"
ARTIFACT_IDS[ARTIFACT_TRACEABILITY] = "traceability"
ARTIFACT_IDS[ARTIFACT_TRACEABILITY_MAP] = "traceability-map"

#: PRD/registers are Planning-owned per guide section 4 (PRODUCT_BRIEF, MVP_SCOPE,
#: REQUIREMENTS, DECISIONS, project-blueprint.json all belong to Planning; PRD.md
#: consolidates exactly those, so it inherits the same owner).
EXECUTION_BASELINE_OWNER = "FRAME"

# --------------------------------------------------------------------------- #
# Slice S4: internal MVP build evidence (PROJECT_STATUS.md at workspace root,
# BUILD_REPORT.md under docs/, current-state.json under .vibeoffice/).
# --------------------------------------------------------------------------- #

ARTIFACT_PROJECT_STATUS = "project_status"
ARTIFACT_BUILD_REPORT = "build_report"
ARTIFACT_CURRENT_STATE = "current_state"

#: Directory each S4 artifact writes to - the one place the three-directory
#: split (root/docs/.vibeoffice) is decided, so ``build.py`` never hardcodes a
#: path itself.
BUILD_EVIDENCE_DIRECTORY: dict[str, str] = {
    ARTIFACT_PROJECT_STATUS: "",
    ARTIFACT_BUILD_REPORT: DOCS_DIRNAME,
    ARTIFACT_CURRENT_STATE: BLUEPRINT_DIRNAME,
}

BUILD_EVIDENCE_TYPES: tuple[str, ...] = (ARTIFACT_PROJECT_STATUS, ARTIFACT_BUILD_REPORT, ARTIFACT_CURRENT_STATE)

ARTIFACT_FILENAMES[ARTIFACT_PROJECT_STATUS] = "PROJECT_STATUS.md"
ARTIFACT_FILENAMES[ARTIFACT_BUILD_REPORT] = "BUILD_REPORT.md"
ARTIFACT_FILENAMES[ARTIFACT_CURRENT_STATE] = "current-state.json"

ARTIFACT_IDS[ARTIFACT_PROJECT_STATUS] = "project-status"
ARTIFACT_IDS[ARTIFACT_BUILD_REPORT] = "build-report"
ARTIFACT_IDS[ARTIFACT_CURRENT_STATE] = "current-state"

#: Build department owner (guide section 4: Build is FRONT/BACK, lead BUILD).
BUILD_OWNER = "BUILD"

class ArtifactNotFound(LookupError):
    """No such artifact for this project. Routes map this to 404."""


class UnknownArtifactType(LookupError):
    """Artifact type outside the catalogue. Routes map this to 404."""


# --------------------------------------------------------------------------- #
# Stale propagation (guide section 9 / 09A section 4)
# --------------------------------------------------------------------------- #

CHANGE_TARGET_USERS = "target_users"
CHANGE_MUST = "must"
CHANGE_VISUAL = "visual"
CHANGE_TECH_STACK = "tech_stack"
#: ``should``/``later``/``out`` moved. No design document renders those buckets,
#: but the handoff envelope's ``constraints`` are derived from ``out`` and
#: rejection condition 4 reads Out against Must/Should, so the change has to be
#: *recorded* even though it marks no artifact stale.
CHANGE_SCOPE_SECONDARY = "scope_secondary"
#: ``successMoment`` / ``skillLevel``. These are exactly what
#: ``design.render_design_system`` reads, and they were previously invisible to
#: the classifier, so DESIGN_SYSTEM went stale in silence.
CHANGE_EXPERIENCE = "experience"
#: Catch-all for any remaining difference between two blueprint bodies. Its impact
#: set is the whole design package on purpose: an unclassified change is a change
#: we cannot reason about, and "mark too much" is the safe direction. Its real job
#: is to make "the bodies differ but change_kinds is empty" impossible.
CHANGE_OTHER = "other"

CHANGE_LABELS = {
    CHANGE_TARGET_USERS: "대상 사용자 변경",
    CHANGE_MUST: "Must 기능 변경",
    CHANGE_VISUAL: "색상·문구 변경",
    CHANGE_TECH_STACK: "기술 스택 변경",
    CHANGE_SCOPE_SECONDARY: "Should·Later·Out 범위 변경",
    CHANGE_EXPERIENCE: "성공 장면·숙련도 변경",
    CHANGE_OTHER: "기타 기획 내용 변경",
}

#: Which artifacts a given kind of blueprint change can invalidate.  Only design
#: package artifacts appear here because those are the only ones S2 produces;
#: entries for artifacts that do not exist yet are simply skipped when marking.
#: The three sets are intentionally *different* - that difference is the "최소
#: 영향 수정" rule expressed as data.
#: Each entry is justified by what the renderer in ``design.py`` actually reads:
#:
#:   render_information_architecture ← targetUsers, oneLineDefinition,
#:                                     screen.features (Must ids), screen.route
#:   render_user_flows               ← screens, flows
#:   render_screen_spec              ← every screen field incl. data source
#:   render_design_system            ← targetUsers, successMoment, skillLevel
#:   render_component_inventory      ← screen.components (derived from kind)
STALE_IMPACT: dict[str, frozenset[str]] = {
    # 대상 사용자 변경 → Brief·UX·Screen·Requirements·테스트 페르소나
    CHANGE_TARGET_USERS: frozenset(
        {ARTIFACT_INFORMATION_ARCHITECTURE, ARTIFACT_USER_FLOWS, ARTIFACT_SCREEN_SPEC}
    ),
    # Must 변경 → Scope·Flow·Screen·API/Data·Tasks. IA is included because its
    # "화면과 Must 기능 연결" table lists Must ids and its screen tree is numbered
    # from the Must order.
    CHANGE_MUST: frozenset(
        {
            ARTIFACT_INFORMATION_ARCHITECTURE,
            ARTIFACT_USER_FLOWS,
            ARTIFACT_SCREEN_SPEC,
            ARTIFACT_COMPONENT_INVENTORY,
        }
    ),
    # 색상·문구 변경 → Design·Screen Spec·시각 테스트만. IA is included because
    # ``oneLineDefinition`` is one of ``_VISUAL_FIELDS`` and it is printed in the
    # IA body.
    CHANGE_VISUAL: frozenset(
        {ARTIFACT_DESIGN_SYSTEM, ARTIFACT_SCREEN_SPEC, ARTIFACT_INFORMATION_ARCHITECTURE}
    ),
    # 기술 스택 변경 → Architecture·API·Data Model·Tasks. SCREEN_SPEC is included
    # because ``dataPersistence`` decides the entry screen's kind and every data
    # source sentence on every screen. API_CONTRACT/DATA_MODEL/TECHNICAL_TASKS are
    # the S3 architecture package guide section 9 names explicitly for this kind
    # of change - a tech-stack revision (frontend/backend/database/dataPersistence/
    # auth/aiIntegration) changes the endpoints, entities and tasks those three
    # documents describe, so they must go stale alongside the design artifacts.
    CHANGE_TECH_STACK: frozenset(
        {
            ARTIFACT_COMPONENT_INVENTORY,
            ARTIFACT_SCREEN_SPEC,
            ARTIFACT_API_CONTRACT,
            ARTIFACT_DATA_MODEL,
            ARTIFACT_TECHNICAL_TASKS,
        }
    ),
    # No design document renders should/later/out - the impact is on the handoff
    # envelope, which is rebuilt from the approved blueprint anyway.
    CHANGE_SCOPE_SECONDARY: frozenset(),
    # successMoment/skillLevel are read only by DESIGN_SYSTEM.
    CHANGE_EXPERIENCE: frozenset({ARTIFACT_DESIGN_SYSTEM}),
    # Unclassified difference: be conservative, mark the whole package.
    CHANGE_OTHER: frozenset(DESIGN_PACKAGE_TYPES),
}

#: Blueprint fields whose text is "visual copy" rather than structure. Changing
#: only these must not invalidate the flows.
_VISUAL_FIELDS = ("projectName", "oneLineDefinition", "valueProposition")

_TECH_FIELDS = ("frontend", "backend", "database", "dataPersistence", "auth", "aiIntegration")

#: Secondary scope buckets: everything in ``scope`` that is not ``must``.
_SECONDARY_SCOPE_BUCKETS = ("should", "later", "out")

#: ``constraints`` keys classified by a specific change kind.
_CLASSIFIED_CONSTRAINT_FIELDS = ("skillLevel",)

#: Top-level blueprint keys that a specific change kind already covers. Anything
#: outside this list (coreProblem, projectType, risks, openQuestions, assumptions,
#: confidence, constraints.deadline, technicalDirection.prototypeStrategy, ...)
#: falls through to ``CHANGE_OTHER``.
_CLASSIFIED_TOP_FIELDS = (
    "targetUsers",
    "successMoment",
    "scope",
    "technicalDirection",
    "constraints",
    *_VISUAL_FIELDS,
)


def _feature_signature(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Full comparable form of a feature list.

    Compares the *whole* feature body, not just ``(id, name)``: ``userValue``
    becomes the screen ``purpose`` and ``reason`` feeds rejection condition 1, so
    editing either one really does invalidate SCREEN_SPEC - and used to do it
    without any change kind being raised at all.
    """
    return [
        {key: feature.get(key) for key in sorted(feature.keys())} for feature in features or []
    ]


def _unclassified_residual(content: dict[str, Any]) -> dict[str, Any]:
    """The part of a blueprint body no specific change kind looks at."""
    residual = {
        key: value for key, value in (content or {}).items() if key not in _CLASSIFIED_TOP_FIELDS
    }
    residual["constraints"] = {
        key: value
        for key, value in (content.get("constraints") or {}).items()
        if key not in _CLASSIFIED_CONSTRAINT_FIELDS
    }
    residual["technicalDirection"] = {
        key: value
        for key, value in (content.get("technicalDirection") or {}).items()
        if key not in _TECH_FIELDS
    }
    residual["scope"] = {
        key: value
        for key, value in (content.get("scope") or {}).items()
        if key not in ("must", *_SECONDARY_SCOPE_BUCKETS)
    }
    return residual


def classify_blueprint_change(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Which kinds of change happened between two blueprint versions.

    Pure diff, no heuristics: the caller feeds two stored bodies and gets back the
    change kinds that ``STALE_IMPACT`` is keyed by.

    The classification is *total*: if the two bodies differ at all, at least one
    kind comes back.  Anything the specific rules do not recognise raises
    ``CHANGE_OTHER``, whose impact set is the whole design package.  A silent
    difference would leave a stale artifact with no stale badge, which is worse
    than over-marking.
    """
    kinds: list[str] = []
    if previous.get("targetUsers") != current.get("targetUsers"):
        kinds.append(CHANGE_TARGET_USERS)
    previous_scope = previous.get("scope") or {}
    current_scope = current.get("scope") or {}
    if _feature_signature(previous_scope.get("must")) != _feature_signature(current_scope.get("must")):
        kinds.append(CHANGE_MUST)
    if any(previous.get(name) != current.get(name) for name in _VISUAL_FIELDS):
        kinds.append(CHANGE_VISUAL)
    previous_tech = previous.get("technicalDirection") or {}
    current_tech = current.get("technicalDirection") or {}
    if any(previous_tech.get(name) != current_tech.get(name) for name in _TECH_FIELDS):
        kinds.append(CHANGE_TECH_STACK)
    if any(
        _feature_signature(previous_scope.get(bucket)) != _feature_signature(current_scope.get(bucket))
        for bucket in _SECONDARY_SCOPE_BUCKETS
    ):
        kinds.append(CHANGE_SCOPE_SECONDARY)
    previous_constraints = previous.get("constraints") or {}
    current_constraints = current.get("constraints") or {}
    if previous.get("successMoment") != current.get("successMoment") or any(
        previous_constraints.get(name) != current_constraints.get(name)
        for name in _CLASSIFIED_CONSTRAINT_FIELDS
    ):
        kinds.append(CHANGE_EXPERIENCE)
    if _unclassified_residual(previous) != _unclassified_residual(current):
        kinds.append(CHANGE_OTHER)
    return kinds


def stale_targets(kinds: list[str]) -> set[str]:
    """Union of the impact sets for the given change kinds."""
    targets: set[str] = set()
    for kind in kinds:
        targets |= STALE_IMPACT.get(kind, frozenset())
    return targets


def mark_stale(db: sqlite3.Connection, project_id: str, kinds: list[str]) -> list[str]:
    """Flag the artifacts the given change kinds can invalidate.

    Returns the artifact types actually marked (existing rows only). The reason
    string is Korean because it is shown to the user next to the stale badge.
    """
    if not kinds:
        return []
    reason = ", ".join(CHANGE_LABELS.get(kind, kind) for kind in kinds)
    targets = stale_targets(kinds)
    marked: list[str] = []
    now = utc_now()
    for artifact_type in sorted(targets):
        updated = db.execute(
            "UPDATE vo_artifacts SET stale = 1, stale_reason = ?, updated_at = ? "
            "WHERE project_id = ? AND type = ?",
            (f"{reason}으로 영향을 받은 산출물입니다. 전체 재생성 대신 해당 부분만 수정하세요.", now, project_id, artifact_type),
        ).rowcount
        if updated:
            marked.append(artifact_type)
    return marked


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def _write_doc(workspace: Path, filename: str, text: str, *, directory: str = DOCS_DIRNAME) -> tuple[str, str]:
    """Write ``<workspace>/<directory>/<filename>`` and return (relative path, sha256).

    ``directory`` defaults to ``docs/`` (every S1-S3.5 artifact). Slice S4 is the
    first to need the other two spots the guide's own workspace tree (section 5)
    names: ``""`` (workspace root, e.g. ``PROJECT_STATUS.md``) and
    ``BLUEPRINT_DIRNAME`` (``.vibeoffice/``, e.g. ``current-state.json``).
    """
    root = workspace.resolve()
    directory = (root / directory).resolve() if directory else root
    if not directory.is_relative_to(root):
        raise ValueError("산출물 경로가 워크스페이스를 벗어납니다.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    body = text if text.endswith("\n") else text + "\n"
    path.write_text(body, encoding="utf-8")
    # Hash the bytes on disk, not the in-memory string: the file is the artifact.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.relative_to(root).as_posix(), digest


def next_version(db: sqlite3.Connection, artifact_id: str) -> int:
    row = db.execute(
        "SELECT MAX(version) FROM vo_artifact_versions WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    return int(row[0] or 0) + 1


def peek_next_versions(db: sqlite3.Connection, project_id: str, types: tuple[str, ...]) -> dict[str, int]:
    """Version numbers the next write will assign, per artifact type.

    Needed *before* rendering because the artifact header embeds its own version.
    """
    return {
        artifact_type: next_version(db, f"{project_id}-{artifact_type}") for artifact_type in types
    }


def record_artifact(
    db: sqlite3.Connection,
    project: sqlite3.Row,
    artifact_type: str,
    text: str,
    *,
    source_blueprint_version: int,
    depends_on: list[str],
    created_by: str = DESIGN_OWNER,
    directory: str = DOCS_DIRNAME,
) -> dict[str, Any]:
    """Append a version of one artifact: file + version row + current pointer."""
    if artifact_type not in ARTIFACT_FILENAMES:
        raise UnknownArtifactType(f"알 수 없는 산출물 종류입니다: {artifact_type}")
    project_id = project["id"]
    artifact_id = f"{project_id}-{artifact_type}"
    relative_path, digest = _write_doc(
        Path(project["workspace_path"]), ARTIFACT_FILENAMES[artifact_type], text, directory=directory
    )
    version = next_version(db, artifact_id)
    version_id = f"{artifact_id}-v{version}"
    now = utc_now()
    db.execute(
        "INSERT INTO vo_artifact_versions (id, artifact_id, version, path, sha256, "
        "source_blueprint_version, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, artifact_id, version, relative_path, digest, source_blueprint_version, created_by, now),
    )
    db.execute(
        "INSERT INTO vo_artifacts (id, project_id, type, status, current_version_id, depends_on_json, "
        "stale, stale_reason, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?) "
        "ON CONFLICT (project_id, type) DO UPDATE SET current_version_id = excluded.current_version_id, "
        "depends_on_json = excluded.depends_on_json, stale = 0, stale_reason = NULL, "
        "status = excluded.status, updated_at = excluded.updated_at",
        (
            artifact_id,
            project_id,
            artifact_type,
            ARTIFACT_STATUS_PROPOSED,
            version_id,
            json.dumps(depends_on, ensure_ascii=False),
            now,
        ),
    )
    return {
        "id": artifact_id,
        "type": artifact_type,
        "status": ARTIFACT_STATUS_PROPOSED,
        "version": version,
        "version_id": version_id,
        "path": relative_path,
        "sha256": digest,
        "source_blueprint_version": source_blueprint_version,
        "depends_on": depends_on,
        "stale": False,
        "stale_reason": None,
    }


def _artifact_payload(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    version = db.execute(
        "SELECT * FROM vo_artifact_versions WHERE id = ?", (row["current_version_id"],)
    ).fetchone()
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "type": row["type"],
        "status": row["status"],
        "stale": bool(row["stale"]),
        "stale_reason": row["stale_reason"],
        "depends_on": json.loads(row["depends_on_json"] or "[]"),
        "updated_at": row["updated_at"],
        "filename": ARTIFACT_FILENAMES.get(row["type"]),
        "version": version["version"] if version else None,
        "path": version["path"] if version else None,
        "sha256": version["sha256"] if version else None,
        "source_blueprint_version": version["source_blueprint_version"] if version else None,
        "created_by": version["created_by"] if version else None,
    }


def list_artifacts(project_id: str) -> dict[str, Any]:
    with s2_database() as db:
        load_project(db, project_id)
        rows = db.execute(
            "SELECT * FROM vo_artifacts WHERE project_id = ? ORDER BY type", (project_id,)
        ).fetchall()
        artifacts = [_artifact_payload(db, row) for row in rows]
        return {
            "project_id": project_id,
            "artifacts": artifacts,
            "stale_count": sum(1 for artifact in artifacts if artifact["stale"]),
        }


def get_artifact(project_id: str, artifact_type: str) -> dict[str, Any]:
    """One artifact plus its file body and full version history."""
    if artifact_type not in ARTIFACT_FILENAMES:
        raise UnknownArtifactType(f"알 수 없는 산출물 종류입니다: {artifact_type}")
    with s2_database() as db:
        project = load_project(db, project_id)
        row = db.execute(
            "SELECT * FROM vo_artifacts WHERE project_id = ? AND type = ?", (project_id, artifact_type)
        ).fetchone()
        if row is None:
            raise ArtifactNotFound(f"Artifact not generated yet: {project_id}/{artifact_type}")
        payload = _artifact_payload(db, row)
        history = [
            {
                "version": item["version"],
                "path": item["path"],
                "sha256": item["sha256"],
                "source_blueprint_version": item["source_blueprint_version"],
                "created_at": item["created_at"],
            }
            for item in db.execute(
                "SELECT * FROM vo_artifact_versions WHERE artifact_id = ? ORDER BY version",
                (row["id"],),
            ).fetchall()
        ]
        body = None
        if payload["path"]:
            path = Path(project["workspace_path"]) / payload["path"]
            if path.is_file():
                body = path.read_text(encoding="utf-8")
        return {**payload, "history": history, "body": body}


# --------------------------------------------------------------------------- #
# Blueprint revision -> stale + superseded
# --------------------------------------------------------------------------- #


def revise_blueprint(project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Store a new blueprint version and propagate its impact.

    Version bumping lives here rather than in ``blueprint.py`` because a revision
    is only half a scope change: the other half is deciding *which* downstream
    artifacts it invalidates and which handoffs it supersedes, which is this
    module's job.

    ``patch`` is a shallow field patch on the previous body.  The result is
    validated and gated exactly like a freshly generated blueprint, so a revision
    can never smuggle in an invalid scope.

    The new version lands **unapproved** and the project walks
    ``STALE_ARTIFACTS -> PLANNING_REVIEW``.  Guide section 10 lists Must/Later/Out
    and user-flow changes as user-approval items, so a revision has to pass
    approval #1 again before it can be handed to design.  Auto-approving here
    would let a scope change reach the design department without anyone agreeing
    to it.
    """
    # Lazy imports: ``blueprint`` and ``handoff`` both import this module, and the
    # package convention (see __init__) is to break cycles inside function bodies.
    from apps.api.vibeoffice import blueprint as blueprint_service
    from apps.api.vibeoffice import handoff as handoff_service
    from apps.api.vibeoffice.models import validate_blueprint

    with s2_database() as db:
        project = load_project(db, project_id)

        # Validate the *whole* state walk before touching anything.  This used to
        # be checked by the two ``set_project_state`` calls at the end, i.e. after
        # the blueprint file had already been overwritten: the DB rolled back but
        # the file did not, the recorded sha256 no longer matched disk, and the
        # approval gate then answered 409 forever.  ``require_transition`` here is
        # a pure check - it writes nothing - so an illegal state fails with the
        # workspace and the DB both untouched.
        require_transition(project["state"], ProjectState.STALE_ARTIFACTS)
        require_transition(ProjectState.STALE_ARTIFACTS, ProjectState.PLANNING_REVIEW)

        row = db.execute(
            "SELECT * FROM vo_blueprints WHERE project_id = ? ORDER BY version DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if row is None or not row["content_json"]:
            raise blueprint_service.BlueprintNotFound(f"Blueprint not found for project {project_id}")
        previous = json.loads(row["content_json"])
        revised = json.loads(json.dumps(previous))
        revised.update(patch)
        blueprint_service.assert_scope_gate(revised)
        validate_blueprint(revised)

        kinds = classify_blueprint_change(previous, revised)
        version = int(row["version"]) + 1
        # Every validation has passed; only now does anything land on disk.
        relative_path, digest = blueprint_service._write_blueprint_file(
            Path(project["workspace_path"]), revised
        )
        now = utc_now()
        db.execute(
            "INSERT INTO vo_blueprints (id, project_id, version, content_json, inference_json, "
            "questions_json, answers_json, path, sha256, approved_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{project_id}-BP{version}",
                project_id,
                version,
                json.dumps(revised, ensure_ascii=False),
                row["inference_json"],
                row["questions_json"],
                row["answers_json"],
                relative_path,
                digest,
                None,
                now,
            ),
        )
        marked = mark_stale(db, project_id, kinds)
        superseded = handoff_service.supersede_live_handoffs(
            db, project_id, reason=f"입력 blueprint가 v{version}로 갱신되었습니다."
        )
        set_project_state(db, project_id, ProjectState.STALE_ARTIFACTS)
        state = set_project_state(db, project_id, ProjectState.PLANNING_REVIEW)
        return {
            "project_id": project_id,
            "version": version,
            "path": relative_path,
            "sha256": digest,
            "change_kinds": kinds,
            "stale_artifacts": marked,
            "superseded_handoffs": superseded,
            "blueprint": revised,
            "previous_project_state": project["state"],
            "project_state": state.value,
        }


__all__ = [
    "ARTIFACT_COMPONENT_INVENTORY",
    "ARTIFACT_DESIGN_SYSTEM",
    "ARTIFACT_FILENAMES",
    "ARTIFACT_IDS",
    "ARTIFACT_INFORMATION_ARCHITECTURE",
    "ARTIFACT_SCREEN_SPEC",
    "ARTIFACT_STATUS_PROPOSED",
    "ARTIFACT_USER_FLOWS",
    "ArtifactNotFound",
    "CHANGE_EXPERIENCE",
    "CHANGE_LABELS",
    "CHANGE_MUST",
    "CHANGE_OTHER",
    "CHANGE_SCOPE_SECONDARY",
    "CHANGE_TARGET_USERS",
    "CHANGE_TECH_STACK",
    "CHANGE_VISUAL",
    "DESIGN_PACKAGE_TYPES",
    "STALE_IMPACT",
    "UnknownArtifactType",
    "classify_blueprint_change",
    "get_artifact",
    "list_artifacts",
    "mark_stale",
    "peek_next_versions",
    "record_artifact",
    "revise_blueprint",
    "stale_targets",
    "ProjectNotFound",
]
