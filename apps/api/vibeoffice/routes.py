"""``/api/vibe/*`` router for slice S1 (Intake -> Blueprint -> planning approval).

The router is deliberately *not* included into ``apps.api.main`` here: another
session owns that file right now, and the guide forbids putting new code in
``main.py`` anyway.  A human adds the one-line ``app.include_router(...)`` later.
Until then the router is exercised by mounting it on a throwaway ``FastAPI()``
app inside ``apps/api/test_vibeoffice_intake.py``.

Error mapping follows the existing endpoints in ``main.py``:

* unknown project / missing blueprint -> 404
* illegal state transition, unapproved handoff -> 409
* bad input, schema or scope-gate failure -> 422
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import intake as intake_rules
from apps.api.vibeoffice.models import BlueprintSchemaError
from apps.api.vibeoffice.schema import ProjectNotFound, StateTransitionError

router = APIRouter(prefix="/api/vibe", tags=["vibeoffice"])


class ProjectCreateInput(BaseModel):
    idea: str = Field(min_length=1, description="사용자가 쓴 짧은 한 문장")
    start_card_id: str | None = None
    name: str | None = None
    mode: str | None = None
    task_id: str | None = None
    workspace_path: str | None = None


class IntakeInput(BaseModel):
    idea: str | None = None
    start_card_id: str | None = None


class AnswerInput(BaseModel):
    question_id: str | None = None
    field: str | None = None
    action: Literal["accept_recommended", "dont_know", "decide_later"]
    value: Any | None = None


class AnswersInput(BaseModel):
    answers: list[AnswerInput] = Field(default_factory=list)


@router.get("/start-cards")
def get_start_cards() -> dict[str, Any]:
    """Start cards for the first screen (P0-01: never an empty chat box)."""
    return {"cards": intake_rules.start_cards(), "max_questions": intake_rules.MAX_QUESTIONS}


@router.post("/projects", status_code=201)
def post_project(payload: ProjectCreateInput) -> dict[str, Any]:
    try:
        return blueprint_service.create_project(
            idea=payload.idea,
            start_card_id=payload.start_card_id,
            name=payload.name,
            mode=payload.mode,
            task_id=payload.task_id,
            workspace_path=payload.workspace_path,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/projects/{project_id}/intake")
def post_intake(project_id: str, payload: IntakeInput | None = None) -> dict[str, Any]:
    body = payload or IntakeInput()
    try:
        return blueprint_service.run_intake(project_id, idea=body.idea, start_card_id=body.start_card_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.BlueprintNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/projects/{project_id}/intake/questions")
def get_questions(project_id: str) -> dict[str, Any]:
    try:
        return blueprint_service.open_questions(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.BlueprintNotFound as error:
        raise HTTPException(404, str(error)) from error


@router.post("/projects/{project_id}/intake/answers")
def post_answers(project_id: str, payload: AnswersInput) -> dict[str, Any]:
    answers = [answer.model_dump(exclude_none=False) for answer in payload.answers]
    try:
        return blueprint_service.submit_answers(project_id, answers)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.BlueprintNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except (intake_rules.UnknownQuestion, intake_rules.UnknownAnswerAction) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/projects/{project_id}/blueprint/generate")
def post_generate(project_id: str) -> dict[str, Any]:
    try:
        return blueprint_service.generate_blueprint(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.BlueprintNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except (BlueprintSchemaError, blueprint_service.ScopeGateError) as error:
        raise HTTPException(422, str(error)) from error


@router.get("/projects/{project_id}/blueprint")
def get_blueprint(project_id: str) -> dict[str, Any]:
    try:
        return blueprint_service.get_blueprint(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.BlueprintNotFound as error:
        raise HTTPException(404, str(error)) from error


@router.post("/projects/{project_id}/blueprint/approve")
def post_approve(project_id: str) -> dict[str, Any]:
    try:
        return blueprint_service.approve_blueprint(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.BlueprintNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except (BlueprintSchemaError, blueprint_service.ScopeGateError) as error:
        raise HTTPException(422, str(error)) from error


# --------------------------------------------------------------------------- #
# Slice S2: planning -> design handoff, Design Package, artifact versions
# --------------------------------------------------------------------------- #
#
# Same error mapping as S1:
#   * unknown project / handoff / artifact          -> 404
#   * illegal transition, unapproved or refused handoff -> 409
#   * schema failure, Gate C failure                -> 422
#
# No new ``include_router`` line is needed: S1 already mounted this router in
# ``apps.api.main``, so every endpoint below is live as soon as it is declared.

from apps.api.vibeoffice import artifacts as artifact_store  # noqa: E402
from apps.api.vibeoffice import design as design_service  # noqa: E402
from apps.api.vibeoffice import handoff as handoff_service  # noqa: E402
from apps.api.vibeoffice.models import HandoffSchemaError  # noqa: E402


class HandoffApproveInput(BaseModel):
    approved_by: str = "user"


@router.post("/projects/{project_id}/handoffs", status_code=201)
def post_handoff(project_id: str) -> dict[str, Any]:
    """Create the planning -> design envelope from the approved blueprint."""
    try:
        return handoff_service.create_handoff(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.HandoffRejected as error:
        raise HTTPException(409, error.reason) from error
    except handoff_service.HandoffRejectedError as error:
        raise HTTPException(409, error.reason) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except (HandoffSchemaError, BlueprintSchemaError, blueprint_service.ScopeGateError) as error:
        raise HTTPException(422, str(error)) from error


@router.get("/projects/{project_id}/handoffs")
def get_handoffs(project_id: str) -> dict[str, Any]:
    try:
        return handoff_service.list_handoffs(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error


@router.get("/projects/{project_id}/handoffs/{handoff_id}")
def get_handoff(project_id: str, handoff_id: str) -> dict[str, Any]:
    try:
        return handoff_service.get_handoff(project_id, handoff_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except handoff_service.HandoffNotFound as error:
        raise HTTPException(404, str(error)) from error


@router.post("/projects/{project_id}/handoffs/{handoff_id}/approve")
def post_handoff_approve(
    project_id: str, handoff_id: str, payload: HandoffApproveInput | None = None
) -> dict[str, Any]:
    body = payload or HandoffApproveInput()
    try:
        return handoff_service.approve_handoff(project_id, handoff_id, approved_by=body.approved_by)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except handoff_service.HandoffNotFound as error:
        raise HTTPException(404, str(error)) from error
    except handoff_service.HandoffRejectedError as error:
        raise HTTPException(409, error.reason) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except HandoffSchemaError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/projects/{project_id}/departments/design/run")
def post_design_run(project_id: str) -> dict[str, Any]:
    """Generate the Design Package (Gate C enforced before anything is written)."""
    try:
        return design_service.run_design(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except handoff_service.HandoffNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.HandoffRejected as error:
        raise HTTPException(409, error.reason) from error
    except handoff_service.HandoffRejectedError as error:
        raise HTTPException(409, error.reason) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except design_service.GateCError as error:
        raise HTTPException(422, str(error)) from error
    except (HandoffSchemaError, BlueprintSchemaError, blueprint_service.ScopeGateError) as error:
        raise HTTPException(422, str(error)) from error


class DesignApproveInput(BaseModel):
    approved_by: str = "user"


@router.post("/projects/{project_id}/artifacts/design/approve")
def post_design_approve(project_id: str, payload: DesignApproveInput | None = None) -> dict[str, Any]:
    """User approval #2 (시안 승인)."""
    body = payload or DesignApproveInput()
    try:
        return design_service.approve_design(project_id, approved_by=body.approved_by)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error


@router.get("/projects/{project_id}/artifacts")
def get_artifacts(project_id: str) -> dict[str, Any]:
    try:
        return artifact_store.list_artifacts(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error


@router.get("/projects/{project_id}/artifacts/{artifact_type}")
def get_artifact(project_id: str, artifact_type: str) -> dict[str, Any]:
    try:
        return artifact_store.get_artifact(project_id, artifact_type)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except artifact_store.UnknownArtifactType as error:
        raise HTTPException(404, str(error)) from error
    except artifact_store.ArtifactNotFound as error:
        raise HTTPException(404, str(error)) from error


# --------------------------------------------------------------------------- #
# Slice S3: design approval -> Architecture contract (API_CONTRACT/DATA_MODEL/
# TECHNICAL_TASKS). Same error mapping as S2; Gate D/E failure -> 422.
# --------------------------------------------------------------------------- #

from apps.api.vibeoffice import architecture as architecture_service  # noqa: E402


@router.post("/projects/{project_id}/departments/architecture/run")
def post_architecture_run(project_id: str) -> dict[str, Any]:
    """Generate the Architecture contract (Gate D/E enforced before anything is written)."""
    try:
        return architecture_service.run_architecture(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except blueprint_service.HandoffRejected as error:
        raise HTTPException(409, error.reason) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except architecture_service.GateDError as error:
        raise HTTPException(422, str(error)) from error
    except (BlueprintSchemaError, blueprint_service.ScopeGateError, design_service.GateCError) as error:
        raise HTTPException(422, str(error)) from error


# --------------------------------------------------------------------------- #
# Slice S3.5: Product Execution Baseline (PRD/decision-register/risk-register/
# traceability-map). Same error mapping; Gate PE failure -> 422.
# --------------------------------------------------------------------------- #

from apps.api.vibeoffice import execution_baseline as execution_baseline_service  # noqa: E402


@router.post("/projects/{project_id}/departments/execution-baseline/run")
def post_execution_baseline_run(project_id: str) -> dict[str, Any]:
    """Generate the Product Execution Baseline (Gate PE enforced before writing)."""
    try:
        return execution_baseline_service.run_execution_baseline(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except execution_baseline_service.GatePEError as error:
        raise HTTPException(422, str(error)) from error
    except (BlueprintSchemaError, blueprint_service.ScopeGateError, design_service.GateCError, architecture_service.GateDError) as error:
        raise HTTPException(422, str(error)) from error


# --------------------------------------------------------------------------- #
# Slice S4: internal MVP build (scaffold + real build/test commands). Same
# error mapping; Gate F failure -> 422.
# --------------------------------------------------------------------------- #

from apps.api.vibeoffice import build as build_service  # noqa: E402


@router.post("/projects/{project_id}/departments/build/run")
def post_build_run(project_id: str) -> dict[str, Any]:
    """Scaffold the internal MVP and run build+test (Gate F enforced)."""
    try:
        return build_service.run_build(project_id)
    except ProjectNotFound as error:
        raise HTTPException(404, str(error)) from error
    except StateTransitionError as error:
        raise HTTPException(409, error.reason) from error
    except build_service.GateFError as error:
        raise HTTPException(422, str(error)) from error
    except (BlueprintSchemaError, blueprint_service.ScopeGateError, design_service.GateCError, architecture_service.GateDError) as error:
        raise HTTPException(422, str(error)) from error
