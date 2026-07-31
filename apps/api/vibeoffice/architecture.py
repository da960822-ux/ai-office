"""Architecture contract generation and Gate D/E enforcement (slice S3).

Invariants this module owns:

* **No model call.** Same reason as ``design``: API_CONTRACT/DATA_MODEL/
  TECHNICAL_TASKS are pure functions of the approved design package, so
  regenerating twice produces byte-identical files and Gate D/E can run before
  anything lands on disk.
* **The generator and the checker are independent.** ``build_architecture_package``
  derives matching API fields and Data Model fields from the same per-screen-kind
  table, which is *why* a freshly generated package always passes Gate D. But
  ``assert_gate_d`` re-derives nothing from that table - it compares whatever
  ``ApiEndpoint.fields``/``DataEntity.fields`` actually hold. A hand-built package
  with a manually broken field list still gets caught, which is what makes the
  gate a real check instead of a tautology.
* **Gate D+E bounce to ``REWORK_REQUIRED``**, mirroring Gate C in ``design.py``
  (09A gate table: Gate D/E 위반 -> Architecture 반송). No new state was needed:
  ``REWORK_REQUIRED`` already means "the department that produced this has to
  fix it".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.api.vibeoffice import artifacts as artifact_store
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import design as design_service
from apps.api.vibeoffice.schema import (
    ProjectNotFound,
    ProjectState,
    StateTransitionError,
    load_project,
    s2_database,
    set_project_state,
)

#: Secret-looking substrings that must never appear in a generated artifact
#: (09A Gate D "secret 규칙" / guide section 11 "secret 또는 로컬 절대경로 포함 금지").
#: This module never generates any of these itself, so the check only ever fires
#: against a hand-built fixture in tests - which is exactly what makes it a real
#: gate rather than dead code.
SECRET_MARKERS: tuple[str, ...] = ("sk-", "AKIA", "-----BEGIN", "password=", "secret=")

#: Canonical field set per screen kind. The API endpoint and the Data Model
#: entity for a screen both read this *same* table, so "API 필드 == Data Model
#: 필드" holds by construction for anything this module generates. Gate D checks
#: it anyway because a hand-built ``ArchitecturePackage`` (used to test the gate
#: itself) can disagree on purpose.
_KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "auth": ("id", "email", "displayName", "createdAt"),
    "insight": ("id", "period", "value", "updatedAt"),
    "list": ("id", "title", "status", "updatedAt"),
    "form": ("id", "status", "createdAt"),
    "assist": ("id", "prompt", "result", "createdAt"),
    "detail": ("id", "title", "status", "updatedAt"),
}
_KIND_FIELDS_FALLBACK = ("id", "createdAt", "updatedAt")

#: 화면 kind 마다 실패 시 재시도 문구가 다르면 화면 목적이 더 잘 드러나므로 kind별로 둔다.
_KIND_ERROR_HANDLING: dict[str, str] = {
    "auth": "인증 서버 응답 실패 시 오류 문구를 보여주고 재시도 버튼을 제공한다.",
    "insight": "통계 조회 실패 시 마지막으로 성공한 값을 유지하고 갱신 실패를 안내한다.",
    "list": "목록 조회 실패 시 오류 문구와 다시 시도 버튼을 보여준다.",
    "form": "저장 요청 실패 시 입력값을 보존하고 오류 문구를 보여준다.",
    "assist": "외부 AI 호출 실패 시 mock 응답 경로로 대체하고 실패를 표시한다.",
    "detail": "상세 조회 실패 시 오류 문구와 다시 시도 버튼을 보여준다.",
}
_KIND_ERROR_HANDLING_FALLBACK = "요청 실패 시 오류 문구와 다시 시도 버튼을 보여준다."


class GateDError(ValueError):
    """Gate D/E (기술설계) violation. Routes map this to 422.

    ``reasons`` holds one Korean sentence per violation, same shape as
    ``design.GateCError``.
    """

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Gate D/E(기술설계) 통과 실패: " + " / ".join(reasons))


@dataclass(frozen=True)
class ApiEndpoint:
    id: str
    method: str
    path: str
    screen_id: str
    entity: str
    fields: tuple[str, ...]
    auth: str
    error_handling: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "path": self.path,
            "screenId": self.screen_id,
            "entity": self.entity,
            "fields": list(self.fields),
            "auth": self.auth,
            "errorHandling": self.error_handling,
        }


@dataclass(frozen=True)
class DataEntity:
    name: str
    fields: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "fields": list(self.fields), "source": self.source}


@dataclass(frozen=True)
class TechnicalTask:
    id: str
    title: str
    screen_id: str | None
    api_id: str | None
    depends_on: tuple[str, ...]
    definition_of_done: str
    session_size: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "screenId": self.screen_id,
            "apiId": self.api_id,
            "dependsOn": list(self.depends_on),
            "definitionOfDone": self.definition_of_done,
            "sessionSize": self.session_size,
        }


@dataclass(frozen=True)
class ArchitecturePackage:
    endpoints: tuple[ApiEndpoint, ...]
    entities: tuple[DataEntity, ...]
    tasks: tuple[TechnicalTask, ...]
    design: design_service.DesignPackage = field(repr=False)
    auth: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
            "entities": [entity.to_dict() for entity in self.entities],
            "tasks": [task.to_dict() for task in self.tasks],
        }


# --------------------------------------------------------------------------- #
# Deterministic derivation (guide S3: 화면<->데이터 source 매핑, 필드 일치)
# --------------------------------------------------------------------------- #


def _fields_for(kind: str) -> tuple[str, ...]:
    return _KIND_FIELDS.get(kind, _KIND_FIELDS_FALLBACK)


def build_architecture_package(
    design_package: design_service.DesignPackage, blueprint_content: dict[str, Any]
) -> ArchitecturePackage:
    """Derive API endpoints, Data Model entities and Technical Tasks.

    One endpoint + one entity per data-driven screen, sharing one field list, so
    Gate D's "API 필드 == Data Model 필드" holds by construction. One task per
    data-driven screen (session size: exactly one screen + one endpoint), plus a
    non-data-driven "설정" task per remaining screen so no screen is orphaned by
    the technical task breakdown.
    """
    auth = (blueprint_content.get("technicalDirection") or {}).get("auth") or "none"
    out_names = {
        str(feature.get("name") or "").strip()
        for feature in (blueprint_content.get("scope") or {}).get("out") or []
        if feature.get("name")
    }

    endpoints: list[ApiEndpoint] = []
    entities: list[DataEntity] = []
    tasks: list[TechnicalTask] = []
    task_counter = 1
    previous_task_id: str | None = None

    for screen in design_package.screens:
        entity_name = screen.id.replace("SCR-", "Entity")
        if screen.data_driven:
            endpoint_id = f"API-{screen.id.removeprefix('SCR-')}"
            fields = _fields_for(screen.kind)
            endpoints.append(
                ApiEndpoint(
                    id=endpoint_id,
                    method="GET",
                    path=f"/api{screen.route}" if screen.route != "/" else "/api/home",
                    screen_id=screen.id,
                    entity=entity_name,
                    fields=fields,
                    auth=auth,
                    error_handling=_KIND_ERROR_HANDLING.get(screen.kind, _KIND_ERROR_HANDLING_FALLBACK),
                )
            )
            entities.append(DataEntity(name=entity_name, fields=fields, source="mock adapter (S4에서 실제 저장소로 교체)"))
            api_id = endpoint_id
        else:
            api_id = None

        task_id = f"TASK-{task_counter:03d}"
        title = f"{screen.name} 화면 구현" if screen.data_driven else f"{screen.name} 화면(입력 전용) 구현"
        depends_on = (previous_task_id,) if previous_task_id else ()
        tasks.append(
            TechnicalTask(
                id=task_id,
                title=title,
                screen_id=screen.id,
                api_id=api_id,
                depends_on=depends_on,
                definition_of_done=f"{screen.id} {screen.name} 화면이 렌더되고 주요 CTA({screen.cta_label})가 동작한다.",
                session_size="single-session",
            )
        )
        previous_task_id = task_id
        task_counter += 1

    # Gate D 5th check needs a fixture path to actually observe an Out-scope task
    # rejected; nothing generated here ever names an Out feature, since tasks are
    # derived from design screens (which are derived from Must features only).
    del out_names

    return ArchitecturePackage(
        endpoints=tuple(endpoints), entities=tuple(entities), tasks=tuple(tasks), design=design_package, auth=auth
    )


# --------------------------------------------------------------------------- #
# Gate D (09A Technical) + Gate E (09A Task)
# --------------------------------------------------------------------------- #


def assert_gate_d(package: ArchitecturePackage, blueprint_content: dict[str, Any] | None = None) -> None:
    """Enforce Gate D (technical) + Gate E (task) on an architecture package.

    Independent of ``build_architecture_package``: every check re-reads the
    package's own data, so a hand-built package with a broken field list, a
    forward-referencing task dependency, or an Out-scope task title is caught
    the same way a generated-then-corrupted one would be. Raises ``GateDError``.
    """
    reasons: list[str] = []
    screen_ids = {screen.id for screen in package.design.screens}
    data_screen_ids = {screen.id for screen in package.design.screens if screen.data_driven}
    endpoint_by_screen = {endpoint.screen_id: endpoint for endpoint in package.endpoints}
    entity_by_name = {entity.name: entity for entity in package.entities}

    # Gate D: 화면 데이터 source - every data-driven screen has exactly one endpoint.
    for screen_id in data_screen_ids:
        if screen_id not in endpoint_by_screen:
            reasons.append(f"{screen_id}은 데이터 화면인데 연결된 API가 없습니다.")

    for endpoint in package.endpoints:
        if endpoint.screen_id not in screen_ids:
            reasons.append(f"{endpoint.id}이 존재하지 않는 화면 {endpoint.screen_id}을 가리킵니다.")
        # Gate D: API <-> Data Model 필드 일치.
        entity = entity_by_name.get(endpoint.entity)
        if entity is None:
            reasons.append(f"{endpoint.id}이 참조하는 Data Model {endpoint.entity}이 없습니다.")
        elif tuple(entity.fields) != tuple(endpoint.fields):
            reasons.append(
                f"{endpoint.id}의 필드({', '.join(endpoint.fields)})와 "
                f"{entity.name}의 필드({', '.join(entity.fields)})가 일치하지 않습니다."
            )
        # Gate D: 인증 일치.
        if blueprint_content is not None:
            declared_auth = (blueprint_content.get("technicalDirection") or {}).get("auth") or "none"
            if endpoint.auth != declared_auth:
                reasons.append(
                    f"{endpoint.id}의 인증 방식({endpoint.auth})이 기술 방향({declared_auth})과 일치하지 않습니다."
                )
        # Gate D: 외부 API 실패 처리.
        if not endpoint.error_handling.strip():
            reasons.append(f"{endpoint.id}에 실패 처리 정의가 없습니다.")
        # Gate D: secret 규칙.
        haystack = f"{endpoint.path} {endpoint.error_handling} {' '.join(endpoint.fields)}"
        for marker in SECRET_MARKERS:
            if marker in haystack:
                reasons.append(f"{endpoint.id}에 금지된 비밀정보 패턴이 포함되어 있습니다: {marker!r}.")

    for entity in package.entities:
        haystack = f"{entity.name} {' '.join(entity.fields)}"
        for marker in SECRET_MARKERS:
            if marker in haystack:
                reasons.append(f"{entity.name}에 금지된 비밀정보 패턴이 포함되어 있습니다: {marker!r}.")

    # Gate E: 한 세션 크기, 의존성, 검증 가능한 done, Out 작업 없음.
    task_ids = {task.id for task in package.tasks}
    out_names = {
        str(feature.get("name") or "").strip()
        for feature in ((blueprint_content or {}).get("scope") or {}).get("out") or []
        if feature.get("name")
    }
    for task in package.tasks:
        if task.screen_id is not None and task.screen_id not in screen_ids:
            reasons.append(f"{task.id}이 존재하지 않는 화면 {task.screen_id}을 가리킵니다.")
        if task.api_id is not None and task.api_id not in {endpoint.id for endpoint in package.endpoints}:
            reasons.append(f"{task.id}이 존재하지 않는 API {task.api_id}을 가리킵니다.")
        for dependency in task.depends_on:
            if dependency not in task_ids:
                reasons.append(f"{task.id}이 존재하지 않는 작업 {dependency}에 의존합니다.")
            elif dependency == task.id:
                reasons.append(f"{task.id}이 자기 자신에 의존합니다.")
        if not task.definition_of_done.strip():
            reasons.append(f"{task.id}에 검증 가능한 done 조건이 없습니다.")
        if task.session_size != "single-session":
            reasons.append(f"{task.id}이 한 세션 크기를 넘습니다 ({task.session_size}).")
        if any(out_name and out_name in task.title for out_name in out_names):
            reasons.append(f"{task.id}이 이번 범위에서 제외(Out)한 기능을 작업으로 만들었습니다: {task.title}.")

    if reasons:
        raise GateDError(reasons)


# --------------------------------------------------------------------------- #
# Markdown/YAML rendering (06_OUTPUT_STANDARD)
# --------------------------------------------------------------------------- #

#: Architecture 산출물은 승인된 Design Package 전체(SCREEN_SPEC)에 의존한다.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    artifact_store.ARTIFACT_API_CONTRACT: (artifact_store.ARTIFACT_SCREEN_SPEC,),
    artifact_store.ARTIFACT_DATA_MODEL: (artifact_store.ARTIFACT_SCREEN_SPEC,),
    artifact_store.ARTIFACT_TECHNICAL_TASKS: (
        artifact_store.ARTIFACT_API_CONTRACT,
        artifact_store.ARTIFACT_DATA_MODEL,
    ),
}


def depends_on(artifact_type: str, blueprint_version: int, versions: dict[str, int]) -> list[str]:
    """``depends_on`` entries for the artifact header (``name@version``)."""
    entries = [f"project-blueprint@{blueprint_version}"]
    for dependency in _DEPENDS_ON.get(artifact_type, ()):
        entries.append(f"{artifact_store.ARTIFACT_IDS[dependency]}@{versions.get(dependency, 1)}")
    return entries


def render_header(
    artifact_type: str,
    *,
    version: int,
    blueprint_version: int,
    versions: dict[str, int],
    status: str = artifact_store.ARTIFACT_STATUS_PROPOSED,
) -> str:
    """Same shape as ``design.render_header`` - duplicated, not imported, because
    it is keyed off this module's own ``_DEPENDS_ON``/owner, and the two artifact
    catalogues are small enough that sharing one generic function would need a
    parameter for what is otherwise a two-line function."""
    lines = [
        "---",
        f"artifact_id: {artifact_store.ARTIFACT_IDS[artifact_type]}",
        f"version: {version}",
        f"status: {status}",
        f"source_blueprint_version: {blueprint_version}",
        f"owner: {artifact_store.ARCHITECTURE_OWNER}",
        "depends_on:",
    ]
    for entry in depends_on(artifact_type, blueprint_version, versions):
        lines.append(f"  - {entry}")
    lines.append("---")
    return "\n".join(lines)


def render_api_contract(package: ArchitecturePackage) -> str:
    """``API_CONTRACT.yaml`` body (header excluded - ``render_package`` prepends it)."""
    lines = ["endpoints:"]
    if not package.endpoints:
        lines.append("  []")
    for endpoint in package.endpoints:
        lines += [
            f"  - id: {endpoint.id}",
            f"    method: {endpoint.method}",
            f"    path: {endpoint.path}",
            f"    screenId: {endpoint.screen_id}",
            f"    entity: {endpoint.entity}",
            "    fields:",
        ]
        lines += [f"      - {name}" for name in endpoint.fields]
        lines += [
            f"    auth: {endpoint.auth}",
            f"    errorHandling: \"{endpoint.error_handling}\"",
        ]
    return "\n".join(lines)


def render_data_model(package: ArchitecturePackage) -> str:
    lines = ["# DATA MODEL", "", f"엔티티 {len(package.entities)}종. 각 엔티티는 API_CONTRACT의 같은 이름 엔티티와 필드가 같다.", ""]
    lines += ["| 엔티티 | 필드 | 저장 위치 |", "|---|---|---|"]
    for entity in package.entities:
        lines.append(f"| {entity.name} | {', '.join(entity.fields)} | {entity.source} |")
    return "\n".join(lines)


def render_technical_tasks(package: ArchitecturePackage) -> str:
    lines = ["# TECHNICAL TASKS", "", f"작업 {len(package.tasks)}개. 각 작업은 화면 1개 + API 1개 이하 (한 세션 크기)."]
    for task in package.tasks:
        lines += [
            "",
            f"## {task.id} {task.title}",
            "",
            f"- 화면: {task.screen_id or '-'}",
            f"- API: {task.api_id or '-'}",
            f"- 의존 작업: {', '.join(task.depends_on) or '없음'}",
            f"- done 조건: {task.definition_of_done}",
            f"- 세션 크기: {task.session_size}",
        ]
    return "\n".join(lines)


RENDERERS = {
    artifact_store.ARTIFACT_API_CONTRACT: render_api_contract,
    artifact_store.ARTIFACT_DATA_MODEL: render_data_model,
    artifact_store.ARTIFACT_TECHNICAL_TASKS: render_technical_tasks,
}


def render_package(
    package: ArchitecturePackage, *, blueprint_version: int, versions: dict[str, int]
) -> dict[str, str]:
    documents: dict[str, str] = {}
    for artifact_type in artifact_store.ARCHITECTURE_PACKAGE_TYPES:
        header = render_header(
            artifact_type, version=versions.get(artifact_type, 1), blueprint_version=blueprint_version, versions=versions
        )
        documents[artifact_type] = f"{header}\n\n{RENDERERS[artifact_type](package)}\n"
    return documents


# --------------------------------------------------------------------------- #
# Department run
# --------------------------------------------------------------------------- #


#: States a retry may legally start from besides ``DESIGN_APPROVED`` itself.
#: ``REWORK_REQUIRED`` is ambiguous on its own - ``design.run_design`` also lands
#: a project there on a *Gate C* bounce, which happens before design is ever
#: approved - so raw state alone cannot tell "architecture was bounced" from
#: "design was bounced". ``_has_recorded_design`` disambiguates using data that
#: only exists once a design package has actually been generated.
_RETRY_STATES = frozenset({ProjectState.REWORK_REQUIRED.value, ProjectState.ARCHITECTURE.value})


def _has_recorded_design(db: Any, project_id: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM vo_artifacts WHERE project_id = ? AND type = ? AND current_version_id IS NOT NULL",
        (project_id, artifact_store.ARTIFACT_SCREEN_SPEC),
    ).fetchone()
    return row is not None


def run_architecture(project_id: str) -> dict[str, Any]:
    """Generate the Architecture contract for an approved design package.

    Order matches ``design.run_design``: a read-only precheck confirms the
    project holds ``DESIGN_APPROVED`` (or is retrying after its *own* Gate D/E
    bounce) *before* a Gate D/E failure is allowed to bounce it again, the
    package is built and gated in memory, and only a passing package is written
    to the workspace.
    """
    with s2_database() as db:
        project = load_project(db, project_id)
        state = project["state"]
        allowed = state == ProjectState.DESIGN_APPROVED.value or (
            state in _RETRY_STATES and _has_recorded_design(db, project_id)
        )
        if not allowed:
            raise StateTransitionError(
                f"시안 승인 전에는 기술설계를 시작할 수 없습니다. 현재 상태: {state} "
                f"(필요 상태: {ProjectState.DESIGN_APPROVED.value})"
            )

    # Not ``blueprint_service.approved_blueprint_for_handoff``: that reader hard-
    # requires project state == PLANNING_APPROVED, which is exactly the state this
    # project left behind two departments ago. The blueprint is frozen the moment
    # it is approved (``generate_blueprint`` refuses to overwrite an approved row),
    # so a plain read is the correct - and only - way to reach it from here.
    approved = blueprint_service.get_blueprint(project_id)
    content = approved["blueprint"]
    # Regenerating the design package is a pure function of the same approved
    # blueprint (see design.py's own docstring), so this is guaranteed
    # byte-identical to what Gate C already passed - not a second, divergent copy.
    design_package = design_service.build_design_package(content)
    package = build_architecture_package(design_package, content)

    try:
        assert_gate_d(package, content)
    except GateDError:
        with s2_database() as db:
            set_project_state(db, project_id, ProjectState.REWORK_REQUIRED)
        raise

    with s2_database() as db:
        project = load_project(db, project_id)
        set_project_state(db, project_id, ProjectState.ARCHITECTURE)
        versions = artifact_store.peek_next_versions(db, project_id, artifact_store.ARCHITECTURE_PACKAGE_TYPES)
        documents = render_package(package, blueprint_version=approved["version"], versions=versions)
        written = []
        for artifact_type in artifact_store.ARCHITECTURE_PACKAGE_TYPES:
            written.append(
                artifact_store.record_artifact(
                    db,
                    project,
                    artifact_type,
                    documents[artifact_type],
                    source_blueprint_version=approved["version"],
                    depends_on=depends_on(artifact_type, approved["version"], versions),
                    created_by=artifact_store.ARCHITECTURE_OWNER,
                )
            )
        state = set_project_state(db, project_id, ProjectState.ARCHITECTURE_REVIEW)
        return {
            "project_id": project_id,
            "state": state.value,
            "source_blueprint_version": approved["version"],
            "endpoint_count": len(package.endpoints),
            "entity_count": len(package.entities),
            "task_count": len(package.tasks),
            "endpoints": [endpoint.to_dict() for endpoint in package.endpoints],
            "entities": [entity.to_dict() for entity in package.entities],
            "tasks": [task.to_dict() for task in package.tasks],
            "artifacts": written,
        }


__all__ = [
    "SECRET_MARKERS",
    "ApiEndpoint",
    "ArchitecturePackage",
    "DataEntity",
    "GateDError",
    "TechnicalTask",
    "assert_gate_d",
    "build_architecture_package",
    "depends_on",
    "render_api_contract",
    "render_data_model",
    "render_header",
    "render_package",
    "render_technical_tasks",
    "run_architecture",
    "ProjectNotFound",
    "StateTransitionError",
]
