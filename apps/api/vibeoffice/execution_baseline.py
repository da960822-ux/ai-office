"""Product Execution Baseline generation and Gate PE enforcement (slice S3.5).

Invariants this module owns:

* **No model call, and no new Planning artifact.** Guide section 7 (S3.5): "기존
  Planning 산출물을 대체하지 않는다." PRD.md/decision-register.json/
  risk-register.json/traceability-map.json are pure functions of the already-
  approved blueprint plus the S2 design package and S3 architecture package -
  never a rewrite of ``project-blueprint.json`` itself.
* **No new project state.** The guide's canonical state list (section 5) has no
  dedicated S3.5 state: this slice fixes derivative artifacts on top of an
  already-completed architecture stage, it does not advance the pipeline. The
  project stays on ``ARCHITECTURE_REVIEW`` on success and only leaves it for a
  Gate PE bounce to ``REWORK_REQUIRED`` (see ``schema.S35_TRANSITIONS``).
* **Generator and checker are independent**, same shape as Gate D in
  ``architecture.py``: ``assert_gate_pe`` re-reads whatever an
  ``ExecutionBaseline`` actually holds, so a hand-built one with a broken link
  is caught the same way a corrupted generated one would be.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from apps.api.vibeoffice import architecture as architecture_service
from apps.api.vibeoffice import artifacts as artifact_store
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import design as design_service
from apps.api.vibeoffice import handoff as handoff_service
from apps.api.vibeoffice.schema import (
    ProjectNotFound,
    ProjectState,
    StateTransitionError,
    load_project,
    s2_database,
    set_project_state,
)

#: Guide section 5's own marker for a deferred answer (reused from ``handoff.py``
#: so the two modules cannot drift on what "deferred" looks like in free text).
_DEFERRED_MARKER = handoff_service.DEFERRED_MARKER
#: ``blueprint._open_questions`` marks an unanswered-but-defaulted field with
#: this word (see that function's STATUS_ASKED branch).
_ASSUMPTION_MARKER = "추천값"

#: Risk-title keyword -> owning department (guide section 4 role table). Falls
#: back to Architecture (``BUILD``) for anything technical/unclassified, since
#: every risk ``blueprint._risks`` currently drafts is either scope (Planning) or
#: technical (Architecture) in nature.
_RISK_OWNER_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("범위", "기간"), "FRAME"),
)
_RISK_OWNER_FALLBACK = "BUILD"

#: Severity tier Gate PE actually enforces ownership on. ``Risk.severity`` is
#: only low/medium/high (no "critical" value exists in the model), so "high" is
#: the whole qualifying set today; guide text says "High/Critical" because the
#: spec anticipates a future severity value this codebase does not have yet.
_OWNER_REQUIRED_SEVERITIES = frozenset({"high"})


class GatePEError(ValueError):
    """Gate PE (Product Execution baseline) violation. Routes map this to 422."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Gate PE(Execution Baseline) 통과 실패: " + " / ".join(reasons))


@dataclass(frozen=True)
class Requirement:
    id: str
    feature_id: str
    title: str
    acceptance_criteria: tuple[str, ...]
    task_id: str | None
    test_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "featureId": self.feature_id,
            "title": self.title,
            "acceptanceCriteria": list(self.acceptance_criteria),
            "taskId": self.task_id,
            "testId": self.test_id,
        }


@dataclass(frozen=True)
class KeyResult:
    id: str
    metric: str
    baseline: str
    target: str
    measurement_source: str
    judged_at: str
    requirement_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "metric": self.metric,
            "baseline": self.baseline,
            "target": self.target,
            "measurementSource": self.measurement_source,
            "judgedAt": self.judged_at,
            "requirementId": self.requirement_id,
        }


@dataclass(frozen=True)
class Decision:
    id: str
    text: str
    status: str  # confirmed | assumption | deferred
    affected_artifacts: tuple[str, ...]
    revisit_condition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "affectedArtifacts": list(self.affected_artifacts),
            "revisitCondition": self.revisit_condition,
        }


@dataclass(frozen=True)
class RiskEntry:
    id: str
    title: str
    severity: str
    mitigation: str
    owner: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "mitigation": self.mitigation,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class TraceabilityRow:
    requirement_id: str
    feature_id: str
    flow_id: str | None
    screen_id: str | None
    task_id: str | None
    test_id: str | None
    kr_id: str | None
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirementId": self.requirement_id,
            "featureId": self.feature_id,
            "flowId": self.flow_id,
            "screenId": self.screen_id,
            "taskId": self.task_id,
            "testId": self.test_id,
            "krId": self.kr_id,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ExecutionBaseline:
    objective: str
    problem: str
    scope_summary: dict[str, Any]
    nfrs: tuple[str, ...]
    requirements: tuple[Requirement, ...]
    key_results: tuple[KeyResult, ...]
    decisions: tuple[Decision, ...]
    risks: tuple[RiskEntry, ...]
    traceability: tuple[TraceabilityRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "problem": self.problem,
            "nfrs": list(self.nfrs),
            "requirements": [item.to_dict() for item in self.requirements],
            "keyResults": [item.to_dict() for item in self.key_results],
            "decisions": [item.to_dict() for item in self.decisions],
            "risks": [item.to_dict() for item in self.risks],
            "traceability": [item.to_dict() for item in self.traceability],
        }


# --------------------------------------------------------------------------- #
# Deterministic derivation (guide S3.5: Blueprint+Scope+Requirements+Decisions
# and S3 기술설계 -> PRD/registers, no reinterpretation)
# --------------------------------------------------------------------------- #


def _risk_owner(title: str) -> str:
    for markers, owner in _RISK_OWNER_RULES:
        if any(marker in title for marker in markers):
            return owner
    return _RISK_OWNER_FALLBACK


def _decision_status(question: str) -> str:
    if _DEFERRED_MARKER in question:
        return "deferred"
    if _ASSUMPTION_MARKER in question:
        return "assumption"
    return "assumption"


def build_execution_baseline(
    design_package: design_service.DesignPackage,
    architecture_package: architecture_service.ArchitecturePackage,
    blueprint_content: dict[str, Any],
) -> ExecutionBaseline:
    """One Requirement + one KR + one traceability row per Must feature.

    Screen/flow/task lookups mirror ``design.build_flows``'s own
    ``by_feature`` map (duplicated, not imported: it is a three-line dict
    comprehension over data this module already has, not worth a shared helper
    for one caller).
    """
    scope = blueprint_content.get("scope") or {}
    must = list(scope.get("must") or [])
    constraints = blueprint_content.get("constraints") or {}
    technical = blueprint_content.get("technicalDirection") or {}

    screen_by_feature: dict[str, design_service.Screen] = {}
    for screen in design_package.screens[1:]:
        for feature_id in screen.features:
            screen_by_feature.setdefault(feature_id, screen)
    flow_by_feature = {flow.feature_id: flow for flow in design_package.flows}
    task_by_screen = {task.screen_id: task for task in architecture_package.tasks if task.screen_id}

    requirements: list[Requirement] = []
    key_results: list[KeyResult] = []
    traceability: list[TraceabilityRow] = []
    deadline = constraints.get("deadline") or "출시 후 2주"

    for index, feature in enumerate(must, start=1):
        feature_id = str(feature.get("id"))
        name = str(feature.get("name") or feature_id)
        req_id = f"REQ-{index:03d}"
        kr_id = f"KR-{index:03d}"
        test_id = f"TEST-{index:03d}"
        screen = screen_by_feature.get(feature_id)
        flow = flow_by_feature.get(feature_id)
        task = task_by_screen.get(screen.id) if screen else None

        requirements.append(
            Requirement(
                id=req_id,
                feature_id=feature_id,
                title=name,
                acceptance_criteria=(
                    f"{name} 기능이 승인 기준을 충족한다: {feature.get('userValue') or name}",
                ),
                task_id=task.id if task else None,
                test_id=test_id,
            )
        )
        key_results.append(
            KeyResult(
                id=kr_id,
                metric=f"{name} 사용",
                baseline="0",
                target="출시 후 핵심 사용자가 1회 이상 사용",
                measurement_source="이벤트 로그 (mock 어댑터 단계는 수기 확인)",
                judged_at=str(deadline),
                requirement_id=req_id,
            )
        )
        traceability.append(
            TraceabilityRow(
                requirement_id=req_id,
                feature_id=feature_id,
                flow_id=flow.id if flow else None,
                screen_id=screen.id if screen else None,
                task_id=task.id if task else None,
                test_id=test_id,
                kr_id=kr_id,
                evidence="대기 (Build/QA 단계에서 채움)",
            )
        )

    decisions = tuple(
        Decision(
            id=f"DEC-{index:03d}",
            text=question,
            status=_decision_status(question),
            affected_artifacts=("PRD.md",),
            revisit_condition="사용자가 값을 확정하면 재검토",
        )
        for index, question in enumerate(blueprint_content.get("openQuestions") or [], start=1)
    )
    risks = tuple(
        RiskEntry(
            id=f"RISK-{index:03d}",
            title=str(risk.get("title")),
            severity=str(risk.get("severity")),
            mitigation=str(risk.get("mitigation") or ""),
            owner=_risk_owner(str(risk.get("title") or "")),
        )
        for index, risk in enumerate(blueprint_content.get("risks") or [], start=1)
    )
    nfrs = (
        f"인증: {technical.get('auth', 'unknown')}",
        f"데이터 저장: {technical.get('dataPersistence', 'unknown')}",
        f"AI 연동: {technical.get('aiIntegration', 'unknown')}",
        f"팀 규모: {constraints.get('teamSize') or '미정'}",
        f"기간: {constraints.get('deadline') or '미정'}",
    )

    return ExecutionBaseline(
        objective=str(blueprint_content.get("successMoment") or ""),
        problem=str(blueprint_content.get("coreProblem") or ""),
        scope_summary={
            "must": [f["name"] for f in must],
            "later": [f["name"] for f in scope.get("later") or []],
            "out": [f["name"] for f in scope.get("out") or []],
        },
        nfrs=nfrs,
        requirements=tuple(requirements),
        key_results=tuple(key_results),
        decisions=decisions,
        risks=risks,
        traceability=tuple(traceability),
    )


# --------------------------------------------------------------------------- #
# Gate PE (guide S3.5)
# --------------------------------------------------------------------------- #


def assert_gate_pe(baseline: ExecutionBaseline) -> None:
    """Enforce Gate PE. Raises ``GatePEError``.

    Four independent checks, each mapping to one guide sentence:

    1. every Must Requirement links to a PRD section (trivially true - it is in
       ``baseline.requirements`` by construction), acceptance criteria, a Task
       and a Test - via its traceability row.
    2. every KR links to a Requirement id, or carries its own post-launch
       measurement plan (a non-empty measurement source *and* judged-at date).
    3. no ``deferred`` decision may touch a structural blueprint field (the same
       ``STRUCTURAL_DECISION_LABELS`` S2's handoff rejection condition 5 uses) -
       those need a decision before Build, not after.
    4. every ``high`` severity risk needs both an owner and a mitigation.
    """
    reasons: list[str] = []
    requirement_ids = {requirement.id for requirement in baseline.requirements}
    row_by_requirement = {row.requirement_id: row for row in baseline.traceability}

    for requirement in baseline.requirements:
        if not requirement.acceptance_criteria:
            reasons.append(f"{requirement.id}에 수용 기준이 없습니다.")
        row = row_by_requirement.get(requirement.id)
        if row is None:
            reasons.append(f"{requirement.id}에 연결된 traceability 행이 없습니다.")
            continue
        if not row.task_id:
            reasons.append(f"{requirement.id}이 Task에 연결되지 않았습니다.")
        if not row.test_id:
            reasons.append(f"{requirement.id}이 Test에 연결되지 않았습니다.")

    for key_result in baseline.key_results:
        has_plan = bool(key_result.measurement_source.strip()) and bool(key_result.judged_at.strip())
        if key_result.requirement_id is None:
            if not has_plan:
                reasons.append(f"{key_result.id}이 Requirement에도, 출시 후 측정 계획에도 연결되지 않았습니다.")
        elif key_result.requirement_id not in requirement_ids:
            reasons.append(f"{key_result.id}이 존재하지 않는 Requirement {key_result.requirement_id}에 연결되어 있습니다.")

    for decision in baseline.decisions:
        if decision.status == "deferred" and any(
            label in decision.text for label in handoff_service.STRUCTURAL_DECISION_LABELS
        ):
            reasons.append(f"{decision.id}이 Build 전 결정이 필요한 미결정 사항입니다: {decision.text}")

    for risk in baseline.risks:
        if risk.severity in _OWNER_REQUIRED_SEVERITIES and (not risk.owner.strip() or not risk.mitigation.strip()):
            reasons.append(f"{risk.id}({risk.severity})에 owner 또는 mitigation이 없습니다.")

    if reasons:
        raise GatePEError(reasons)


# --------------------------------------------------------------------------- #
# Markdown/JSON rendering (06_OUTPUT_STANDARD) - filled in below.
# --------------------------------------------------------------------------- #

_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    artifact_store.ARTIFACT_PRD: (
        artifact_store.ARTIFACT_SCREEN_SPEC,
        artifact_store.ARTIFACT_API_CONTRACT,
        artifact_store.ARTIFACT_TECHNICAL_TASKS,
    ),
    artifact_store.ARTIFACT_DECISION_REGISTER: (artifact_store.ARTIFACT_PRD,),
    artifact_store.ARTIFACT_RISK_REGISTER: (artifact_store.ARTIFACT_PRD,),
    artifact_store.ARTIFACT_TRACEABILITY: (artifact_store.ARTIFACT_PRD,),
    artifact_store.ARTIFACT_TRACEABILITY_MAP: (artifact_store.ARTIFACT_TRACEABILITY,),
}


def depends_on(artifact_type: str, blueprint_version: int, versions: dict[str, int]) -> list[str]:
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
    lines = [
        "---",
        f"artifact_id: {artifact_store.ARTIFACT_IDS[artifact_type]}",
        f"version: {version}",
        f"status: {status}",
        f"source_blueprint_version: {blueprint_version}",
        f"owner: {artifact_store.EXECUTION_BASELINE_OWNER}",
        "depends_on:",
    ]
    for entry in depends_on(artifact_type, blueprint_version, versions):
        lines.append(f"  - {entry}")
    lines.append("---")
    return "\n".join(lines)


def render_prd(baseline: ExecutionBaseline) -> str:
    lines = [
        "# PRD",
        "",
        "## Problem",
        "",
        baseline.problem,
        "",
        "## OKR",
        "",
        f"Objective: {baseline.objective}",
        "",
        "| id | metric | baseline | target | measurementSource | judgedAt |",
        "|---|---|---|---|---|---|",
    ]
    for kr in baseline.key_results:
        lines.append(
            f"| {kr.id} | {kr.metric} | {kr.baseline} | {kr.target} | {kr.measurement_source} | {kr.judged_at} |"
        )
    lines += [
        "",
        "## Scope",
        "",
        "### Must",
        "",
    ]
    lines += [f"- {item}" for item in baseline.scope_summary.get("must", [])]
    lines += [
        "",
        "### Later",
        "",
    ]
    lines += [f"- {item}" for item in baseline.scope_summary.get("later", [])]
    lines += [
        "",
        "### Out",
        "",
    ]
    lines += [f"- {item}" for item in baseline.scope_summary.get("out", [])]
    lines += [
        "",
        "## Requirements",
        "",
    ]
    for requirement in baseline.requirements:
        lines += [
            f"### {requirement.id} {requirement.title}",
            "",
        ]
        for criterion in requirement.acceptance_criteria:
            lines.append(f"- {criterion}")
        lines += [
            f"- taskId: {requirement.task_id or '-'}",
            f"- testId: {requirement.test_id or '-'}",
            "",
        ]
    lines += [
        "## 비기능 요구사항",
        "",
    ]
    lines += [f"- {nfr}" for nfr in baseline.nfrs]
    lines += [
        "",
        "## Decision",
        "",
    ]
    for decision in baseline.decisions:
        lines.append(f"- {decision.id}: {decision.text} (status: {decision.status}, revisit: {decision.revisit_condition})")
    lines += [
        "",
        "## Risk",
        "",
        "| id | title | severity | mitigation | owner |",
        "|---|---|---|---|---|",
    ]
    for risk in baseline.risks:
        lines.append(f"| {risk.id} | {risk.title} | {risk.severity} | {risk.mitigation} | {risk.owner} |")
    return "\n".join(lines)


def render_decision_register(baseline: ExecutionBaseline) -> str:
    return json.dumps(
        {"decisions": [d.to_dict() for d in baseline.decisions]},
        ensure_ascii=False,
        indent=2,
    )


def render_risk_register(baseline: ExecutionBaseline) -> str:
    return json.dumps(
        {"risks": [r.to_dict() for r in baseline.risks]},
        ensure_ascii=False,
        indent=2,
    )


def render_traceability_md(baseline: ExecutionBaseline) -> str:
    lines = [
        "# TRACEABILITY",
        "",
        "| Requirement | Feature | Flow | Screen | Task | Test | KR | Evidence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in baseline.traceability:
        lines.append(
            f"| {row.requirement_id} | {row.feature_id} | {row.flow_id or '-'} | {row.screen_id or '-'} | {row.task_id or '-'} | {row.test_id or '-'} | {row.kr_id or '-'} | {row.evidence} |"
        )
    return "\n".join(lines)


def render_traceability_map(baseline: ExecutionBaseline) -> str:
    return json.dumps(
        {"rows": [row.to_dict() for row in baseline.traceability]},
        ensure_ascii=False,
        indent=2,
    )


RENDERERS = {
    artifact_store.ARTIFACT_PRD: render_prd,
    artifact_store.ARTIFACT_DECISION_REGISTER: render_decision_register,
    artifact_store.ARTIFACT_RISK_REGISTER: render_risk_register,
    artifact_store.ARTIFACT_TRACEABILITY: render_traceability_md,
    artifact_store.ARTIFACT_TRACEABILITY_MAP: render_traceability_map,
}


def render_package(
    baseline: ExecutionBaseline, *, blueprint_version: int, versions: dict[str, int]
) -> dict[str, str]:
    documents: dict[str, str] = {}
    for artifact_type in artifact_store.EXECUTION_BASELINE_TYPES:
        header = render_header(
            artifact_type,
            version=versions.get(artifact_type, 1),
            blueprint_version=blueprint_version,
            versions=versions,
        )
        documents[artifact_type] = f"{header}\n\n{RENDERERS[artifact_type](baseline)}\n"
    return documents


# --------------------------------------------------------------------------- #
# Department run
# --------------------------------------------------------------------------- #

#: See ``architecture._RETRY_STATES``/``_has_recorded_design`` for the same
#: raw-state-is-ambiguous problem and its fix, one slice up.
_RETRY_STATES = frozenset({ProjectState.REWORK_REQUIRED.value})


def _has_recorded_architecture(db: Any, project_id: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM vo_artifacts WHERE project_id = ? AND type = ? AND current_version_id IS NOT NULL",
        (project_id, artifact_store.ARTIFACT_API_CONTRACT),
    ).fetchone()
    return row is not None


def run_execution_baseline(project_id: str) -> dict[str, Any]:
    """Generate the Product Execution Baseline for a completed architecture stage.

    Regenerates the design and architecture packages the same pure-function way
    ``architecture.run_architecture`` regenerates the design package - never a
    second, divergent read of any upstream artifact file.
    """
    with s2_database() as db:
        project = load_project(db, project_id)
        state = project["state"]
        allowed = state == ProjectState.ARCHITECTURE_REVIEW.value or (
            state in _RETRY_STATES and _has_recorded_architecture(db, project_id)
        )
        if not allowed:
            raise StateTransitionError(
                f"기술설계 완료 전에는 Execution Baseline을 만들 수 없습니다. 현재 상태: {state} "
                f"(필요 상태: {ProjectState.ARCHITECTURE_REVIEW.value})"
            )

    approved = blueprint_service.get_blueprint(project_id)
    content = approved["blueprint"]
    design_package = design_service.build_design_package(content)
    architecture_package = architecture_service.build_architecture_package(design_package, content)
    baseline = build_execution_baseline(design_package, architecture_package, content)

    try:
        assert_gate_pe(baseline)
    except GatePEError:
        with s2_database() as db:
            set_project_state(db, project_id, ProjectState.REWORK_REQUIRED)
        raise

    with s2_database() as db:
        project = load_project(db, project_id)
        if project["state"] != ProjectState.ARCHITECTURE_REVIEW.value:
            set_project_state(db, project_id, ProjectState.ARCHITECTURE_REVIEW)
        versions = artifact_store.peek_next_versions(db, project_id, artifact_store.EXECUTION_BASELINE_TYPES)
        documents = render_package(baseline, blueprint_version=approved["version"], versions=versions)
        written = []
        for artifact_type in artifact_store.EXECUTION_BASELINE_TYPES:
            written.append(
                artifact_store.record_artifact(
                    db,
                    project,
                    artifact_type,
                    documents[artifact_type],
                    source_blueprint_version=approved["version"],
                    depends_on=depends_on(artifact_type, approved["version"], versions),
                    created_by=artifact_store.EXECUTION_BASELINE_OWNER,
                )
            )
        return {
            "project_id": project_id,
            "state": ProjectState.ARCHITECTURE_REVIEW.value,
            "source_blueprint_version": approved["version"],
            "requirement_count": len(baseline.requirements),
            "key_result_count": len(baseline.key_results),
            "decision_count": len(baseline.decisions),
            "risk_count": len(baseline.risks),
            "baseline": baseline.to_dict(),
            "artifacts": written,
        }


__all__ = [
    "Decision",
    "ExecutionBaseline",
    "GatePEError",
    "KeyResult",
    "Requirement",
    "RiskEntry",
    "TraceabilityRow",
    "assert_gate_pe",
    "build_execution_baseline",
    "depends_on",
    "render_header",
    "render_package",
    "run_execution_baseline",
    "ProjectNotFound",
    "StateTransitionError",
]
