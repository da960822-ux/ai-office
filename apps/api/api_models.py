"""Pydantic request bodies for the ``/api/*`` endpoints.

Extracted from ``apps/api/main.py`` (2,940 lines) to shrink that module without
changing any behaviour.

**Why these and not the rest:** these 21 classes are pure request-shape
declarations - no database, no model client, no imports back into ``main``. They
are the largest self-contained block in ``main.py`` and the only one that can move
with zero risk to the test suite.

**Do not move the model-client / roster / agent-run helpers here.** The test suite
patches ``main.model_client``, ``main.model_key``, ``main.select_roster_with_model``,
``main.run_agent`` and ``main.require_skill_ready`` by module attribute
(``patch.object(main, ...)``). Those patches only take effect while ``main`` both
*owns* the attribute and the caller reaches it through ``main.<name>``; re-exporting
them from another module would keep imports working while silently breaking every
one of those patches, which is worse than leaving them in place.

``main`` re-exports every name defined here (``from apps.api.api_models import *``),
so ``main.CreateTask`` and friends keep resolving for any existing caller.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateTask(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    request: str = Field(min_length=1, max_length=4000)
    selected_employees: list[str] = []
    route: Literal["navi", "direct_lead"] = "navi"
    lead_id: str | None = None
    parent_task_id: str | None = None


class Command(BaseModel):
    action: Literal[
        "contract", "plan", "meeting", "assign", "run", "team_review", "cross_review",
        "verify", "reflect", "approval", "complete", "block", "fail", "cancel", "pause", "escalate"
    ]
    employee_ids: list[str] = []
    note: str = Field(default="", max_length=800)


class PermissionRuleInput(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    effect: Literal["allow", "ask", "deny"]
    pattern: str = Field(default="*", min_length=1, max_length=400)


class ContractInput(BaseModel):
    allowed_paths: list[str] = ["."]
    allowed_commands: list[str] = []
    acceptance_criteria: list[str] = []
    permission_rules: list[PermissionRuleInput] = []
    retry_limit: int = Field(default=2, ge=0, le=5)
    token_limit: int = Field(default=16000, ge=1000, le=100000)


class MeetingInput(BaseModel):
    objective: str = Field(min_length=1, max_length=800)
    participant_ids: list[str] = []
    agenda: list[str] = []


class SelectionInput(BaseModel):
    employee_ids: list[str] = Field(min_length=1, max_length=8)


class DirectDispatchInput(BaseModel):
    lead_id: str = Field(min_length=1, max_length=40)


class JobInput(BaseModel):
    workspace_id: str | None = None
    employee_ids: list[str] = []
    meeting_id: str | None = None
    instruction: str = Field(default="", max_length=4000)


class JobControlInput(BaseModel):
    action: Literal["pause", "resume", "cancel"]


class PermissionDecisionInput(BaseModel):
    decision: Literal["approve", "deny"]
    reason: str = Field(default="", max_length=1000)


class ReviewInput(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=40)
    verdict: Literal["pass", "changes_requested", "blocked"]
    findings: str = Field(default="", max_length=4000)


class ApprovalInput(BaseModel):
    decision: Literal["approve", "rework", "reject"]
    reason: str = Field(default="", max_length=4000)


class ReflectionInput(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    root_causes: list[str] = []
    improvements: list[str] = []
    lesson: str = Field(default="", max_length=4000)


class ProjectInput(BaseModel):
    root_path: str = Field(min_length=1)
    name: str = Field(default="", max_length=120)


class WorkspaceInput(BaseModel):
    project_id: str
    strategy: Literal["worktree", "copy", "in_place"] = "copy"


class RunInput(BaseModel):
    workspace_id: str
    command: str = Field(min_length=1, max_length=400)


class AgentRunInput(BaseModel):
    workspace_id: str
    employee_id: str = Field(min_length=1, max_length=40)
    instruction: str = Field(default="", max_length=4000)
    skill_ids: list[str] = Field(default_factory=list, max_length=3)
    managed_by_job: bool = False
    job_id: str | None = Field(default=None, max_length=80)


class SteeringInput(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    intake_mode: Literal["blank", "has_items"] | None = None


class RetryInput(BaseModel):
    failure_class: Literal["contract_interpretation", "permission", "skill", "file_conflict", "build", "test", "runtime", "external_dependency", "quality", "budget", "model_response"]
    strategy: str | None = Field(default=None, min_length=1, max_length=500)


class ModelSettingsInput(BaseModel):
    provider: Literal["openrouter"] = "openrouter"
    lead_model: str | None = Field(default=None, min_length=1, max_length=100)
    worker_model: str | None = Field(default=None, min_length=1, max_length=100)
    role_models: dict[str, str] = Field(default_factory=dict)
    team_overrides: dict[str, str] = Field(default_factory=dict)
    employee_overrides: dict[str, str] = Field(default_factory=dict)
    api_key: str | None = Field(default=None, min_length=20)


class McpConnectionInput(BaseModel):
    provider: Literal["github", "google-drive", "notion", "custom"]
    name: str = Field(min_length=1, max_length=80)
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    server_url: str = Field(min_length=8, max_length=1000)
    auth_token: str | None = Field(default=None, max_length=4000)


__all__ = [
    "AgentRunInput",
    "ApprovalInput",
    "ChatInput",
    "Command",
    "ContractInput",
    "CreateTask",
    "DirectDispatchInput",
    "JobControlInput",
    "JobInput",
    "McpConnectionInput",
    "MeetingInput",
    "ModelSettingsInput",
    "PermissionDecisionInput",
    "PermissionRuleInput",
    "ProjectInput",
    "ReflectionInput",
    "RetryInput",
    "ReviewInput",
    "RunInput",
    "SelectionInput",
    "SteeringInput",
    "WorkspaceInput",
]
