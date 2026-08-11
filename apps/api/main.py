from __future__ import annotations

import json
import sqlite3
import shutil
import subprocess
import hashlib
import shlex
import os
import urllib.request
import urllib.error
import urllib.parse
import re
import time
import random
import ipaddress
import socket
import fnmatch
from queue import Queue
from threading import Thread
from html import unescape
from xml.etree import ElementTree
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import keyring
import httpx

from apps.api import pricing
from openai import OpenAI, APIConnectionError
from apps.api.agent_tools import AgentToolError, WorkspaceAgentTools, fetch_public_source, tool_definitions
from apps.api.policy import validate_path, validate_command
from apps.api.runtime_context import (
    ensure_schema as ensure_session_schema,
    load_session_context,
    record_session_turn,
    set_session_state,
)
from apps.api.artifact_renderer import render_bundle
from apps.api.research import SearchError, search_public_web
from apps.api.research_quality import (
    claim_source_coverage,
    contradiction_resolution,
    evaluate_research_quality,
    load_task_research,
    primary_source_ratio,
    recommendation_linkage,
)

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("AI_OFFICE_DB_PATH", str(ROOT / "data" / "ai-office.sqlite3"))).resolve()
REGISTRY_PATH = ROOT / "registry" / "employees.json"
SKILL_BINDINGS_PATH = ROOT / "registry" / "employee-skill-bindings.json"
SKILL_DEFINITIONS_PATH = ROOT / "registry" / "skill-definitions.json"
DEPARTMENT_BOUNDARIES_PATH = ROOT / "registry" / "department-boundaries.json"
DELIVERABLE_STANDARDS_PATH = ROOT / "registry" / "deliverable-standards.json"
SKILLS_LOCK_PATH = ROOT / "registry" / "skills.lock.json"
SKILL_POOL_PATH = ROOT / "skills"
SETTINGS_PATH = ROOT / ".ai-office" / "settings.json"
MODEL_ROUTING_PATH = ROOT / "registry" / "model-routing.json"
KEYRING_SERVICE = "AI-Automation-Office"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
MODELS_CACHE_PATH = ROOT / "data" / "openrouter-models.json"
BUILD_ID = "ai-office-jobs-v10-p1-harness"
SCHEMA_VERSION = 5
MODEL_CALL_TIMEOUT_SECONDS = max(30, int(os.getenv("AI_OFFICE_MODEL_TIMEOUT_SECONDS", "900")))
RETRY_PLAYBOOK = {
    "contract_interpretation": ["re-read-contract-and-acceptance", "independent-scope-review"],
    "permission": ["request-required-permission", "narrow-to-approved-action"],
    "skill": ["refresh-task-kind-skill-selection", "handoff-to-owning-department"],
    "file_conflict": ["isolate-worktree-and-rebase", "handoff-conflict-to-owner"],
    "build": ["trace-build-log-with-advanced-model", "minimal-repro-and-owner-handoff"],
    "test": ["discover-tests-and-diagnose", "independent-qa-reproduction"],
    "runtime": ["collect-runtime-evidence-and-retry", "escalate-to-reliability-owner"],
    "external_dependency": ["retry-with-fallback-provider", "pause-for-external-dependency"],
    "quality": ["independent-review-rework", "change-final-owner"],
    "budget": ["compress-context-and-reduce-scope", "human-budget-decision"],
    "model_response": ["switch-model-tier-and-preserve-evidence", "narrow-prompt-and-retry"],
}
JOB_STATES = {"queued", "running", "pause_requested", "paused", "cancel_requested", "cancelled", "succeeded", "failed", "interrupted"}
TASK_STATES = {
    "draft", "contracting", "planning", "meeting", "assigned", "running",
    "team_review", "cross_review", "verifying", "reflecting", "awaiting_approval",
    "completed", "blocked", "failed", "cancelled", "paused", "budget_exceeded", "escalated",
    "awaiting_lead_selection", "meeting_ready", "meeting_running", "awaiting_worker_selection", "executing", "lead_review_running",
    "synthesizing",
}
ACTION_TO_STATE = {
    "contract": "contracting", "plan": "planning", "meeting": "meeting",
    "assign": "assigned", "run": "running", "team_review": "team_review",
    "cross_review": "cross_review", "verify": "verifying", "reflect": "reflecting",
    "approval": "awaiting_approval", "complete": "completed", "block": "blocked",
    "fail": "failed", "cancel": "cancelled", "pause": "paused", "escalate": "escalated",
}
STATE_LABELS = {
    "draft": "초안", "contracting": "계약", "planning": "계획", "meeting": "회의",
    "assigned": "배정", "running": "작업", "team_review": "팀 검토", "cross_review": "교차 검토",
    "verifying": "QA 검증", "reflecting": "회고", "awaiting_approval": "승인 대기",
    "completed": "완료", "blocked": "차단", "failed": "실패", "cancelled": "취소", "paused": "일시 정지",
    "budget_exceeded": "예산 초과", "escalated": "에스컬레이션",
    "awaiting_lead_selection": "팀장 선택 대기", "meeting_ready": "회의 시작 대기", "meeting_running": "팀장 회의", "awaiting_worker_selection": "실행자 선택 대기",
    "executing": "실행 중", "synthesizing": "최종 산출물 통합", "lead_review_running": "팀장 리뷰",
}
STATUS_TO_ZONE = {
    "draft": "desk", "contracting": "meeting", "planning": "meeting", "meeting": "meeting",
    "assigned": "desk", "running": "desk", "team_review": "review", "cross_review": "review",
    "verifying": "qa", "reflecting": "review", "awaiting_approval": "ceo", "completed": "desk",
    "blocked": "ceo", "failed": "qa", "cancelled": "desk", "paused": "ceo", "budget_exceeded": "ceo", "escalated": "ceo",
    "awaiting_lead_selection": "ceo", "meeting_ready": "ceo", "meeting_running": "meeting", "awaiting_worker_selection": "ceo", "executing": "desk", "lead_review_running": "qa",
    "synthesizing": "review",
}


# Request bodies live in apps/api/api_models.py. Imported by name (not a star
# import) so every model this module exposes stays greppable here, and re-exported
# by that import so existing ``main.CreateTask`` callers keep resolving.
from apps.api.api_models import (  # noqa: E402
    AgentRunInput,
    ApprovalInput,
    Command,
    ContractInput,
    CreateTask,
    DirectDispatchInput,
    JobControlInput,
    JobInput,
    McpConnectionInput,
    MeetingInput,
    ModelSettingsInput,
    PermissionDecisionInput,
    PermissionRuleInput,
    ProjectInput,
    ReflectionInput,
    RetryInput,
    ReviewInput,
    RunInput,
    SelectionInput,
    SteeringInput,
    WorkspaceInput,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checkpoint(db: sqlite3.Connection, task_id: str, label: str) -> None:
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task:
        snapshot = {
            "task": dict(task),
            "phases": [dict(row) for row in db.execute("SELECT * FROM task_phases WHERE task_id = ? ORDER BY sequence", (task_id,))],
            "deliverables": [dict(row) for row in db.execute("SELECT * FROM deliverables WHERE task_id = ? ORDER BY updated_at", (task_id,))],
            "evidence": [dict(row) for row in db.execute("SELECT * FROM evidence WHERE task_id = ? AND stale = 0 ORDER BY created_at", (task_id,))],
            "agent_sessions": [dict(row) for row in db.execute("SELECT * FROM agent_sessions WHERE task_id = ? ORDER BY employee_id", (task_id,))],
        }
        db.execute(
            "INSERT INTO task_checkpoints (task_id, label, snapshot, created_at) VALUES (?, ?, ?, ?)",
            (task_id, label, json.dumps(snapshot, ensure_ascii=False), utc_now()),
        )


def require_runnable(db: sqlite3.Connection, task_id: str) -> None:
    task = db.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Task not found")
    if task["state"] == "cancelled":
        raise HTTPException(410, "Task was cancelled; no further agent work is allowed")
    if task["state"] == "paused":
        raise HTTPException(409, "Task is paused; resume it before agent work")
    contract = db.execute("SELECT token_limit FROM task_contracts WHERE task_id = ?", (task_id,)).fetchone()
    if contract:
        spent = db.execute("SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage WHERE task_id = ?", (task_id,)).fetchone()[0]
        if spent >= contract["token_limit"]:
            warned = db.execute("SELECT 1 FROM job_events WHERE task_id = ? AND type = 'budget.warning' LIMIT 1", (task_id,)).fetchone()
            if not warned:
                emit_job_event(
                    db,
                    task_id,
                    "budget.warning",
                    f"초기 토큰 경고 기준 {contract['token_limit']:,}개를 넘었습니다. 고정 중단 대신 Job heartbeat와 단계·도구 호출 한도로 계속 실행합니다.",
                    payload={"token_limit": contract["token_limit"], "spent": spent, "mode": "soft_limit"},
                )


def permission_effect(db: sqlite3.Connection, task_id: str, action: str, target: str) -> str:
    """Resolve most-specific allow/ask/deny rule. Deny wins equal specificity."""
    matches = []
    for row in db.execute(
        "SELECT action, effect, pattern FROM task_permission_rules WHERE task_id = ?",
        (task_id,),
    ):
        if row["action"] in {action, "*"} and fnmatch.fnmatchcase(target, row["pattern"]):
            specificity = (row["action"] != "*", len(row["pattern"]))
            matches.append((specificity, {"allow": 0, "ask": 1, "deny": 2}[row["effect"]], row["effect"]))
    if not matches:
        return "ask" if action == "render_public_page" else "allow"
    return max(matches)[2]


def require_tool_permission(
    db: sqlite3.Connection,
    task_id: str,
    employee_id: str,
    action: str,
    target: str,
) -> None:
    effect = permission_effect(db, task_id, action, target)
    if effect == "allow":
        return
    now = utc_now()
    if effect == "deny":
        db.execute(
            "INSERT INTO permission_checks (task_id, employee_id, action, allowed, reason, created_at) VALUES (?, ?, ?, 0, ?, ?)",
            (task_id, employee_id, f"{action}:{target}", "denied_by_permission_rule", now),
        )
        raise HTTPException(403, f"Permission denied for {action}: {target}")
    approved = db.execute(
        "SELECT 1 FROM permission_requests WHERE task_id = ? AND employee_id = ? "
        "AND action = ? AND target = ? AND state = 'approved' LIMIT 1",
        (task_id, employee_id, action, target),
    ).fetchone()
    if approved:
        return
    request_id = "PERM-" + hashlib.sha256(f"{task_id}:{employee_id}:{action}:{target}".encode()).hexdigest()[:16]
    db.execute(
        "INSERT INTO permission_requests "
        "(id, task_id, employee_id, action, target, state, reason, created_at, decided_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL) "
        "ON CONFLICT(id) DO UPDATE SET state='pending', reason=excluded.reason, decided_at=NULL",
        (request_id, task_id, employee_id, action, target, "TaskContract requires user approval", now),
    )
    db.commit()
    raise HTTPException(428, f"Permission approval required: {request_id}")


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def registry() -> dict[str, dict]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def model_routing() -> dict:
    """Load versioned, repository-managed model defaults."""
    routing = json.loads(MODEL_ROUTING_PATH.read_text(encoding="utf-8"))
    if not routing.get("role_models") or not routing.get("employee_roles"):
        raise RuntimeError("model-routing.json requires role_models and employee_roles")
    return routing


def model_settings() -> dict:
    routing = model_routing()
    stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")) if SETTINGS_PATH.exists() else {}
    role_models = dict(routing["role_models"])
    role_models.update({key: value for key, value in stored.get("role_models", {}).items() if key in role_models and value})
    people = registry()
    team_overrides = {key: value for key, value in stored.get("team_overrides", {}).items() if key in {person["team"] for person in people.values()} and value}
    employee_overrides = {key: value for key, value in stored.get("employee_overrides", {}).items() if key in people and value}
    return {
        "provider": stored.get("provider", "openrouter"),
        "role_models": role_models,
        "team_overrides": team_overrides,
        "employee_overrides": employee_overrides,
        # Compatibility fields for existing clients.
        "lead_model": role_models["complex_design_integration"],
        "worker_model": role_models["development_basic"],
    }


def model_assignment(employee_id: str, *, escalated: bool = False) -> dict:
    settings = model_settings()
    employee = registry()[employee_id]
    role = model_routing()["employee_roles"].get(employee_id, "office_general")
    if escalated:
        return {"role": "debug_escalation", "model": settings["role_models"]["debug_escalation"], "source": "failure_escalation"}
    if employee_id in settings["employee_overrides"]:
        return {"role": role, "model": settings["employee_overrides"][employee_id], "source": "employee"}
    if employee["team"] in settings["team_overrides"]:
        return {"role": role, "model": settings["team_overrides"][employee["team"]], "source": "team"}
    return {"role": role, "model": settings["role_models"][role], "source": "role"}


def task_model_assignment(db: sqlite3.Connection, task_id: str, employee_id: str) -> dict:
    failed_attempts = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE task_id = ?", (task_id,)).fetchone()[0]
    task = db.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return model_assignment(employee_id, escalated=failed_attempts >= 2 or bool(task and task["state"] == "escalated"))


def final_completion_model() -> str:
    return model_settings()["role_models"]["final_completion"]


def technical_integration_model() -> str:
    return model_settings()["role_models"]["complex_design_integration"]


def model_key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY") or keyring.get_password(KEYRING_SERVICE, "openrouter_api_key") or os.getenv("OPENAI_API_KEY")


def model_client() -> OpenAI:
    return OpenAI(
        api_key=model_key(),
        base_url=OPENROUTER_BASE_URL,
        timeout=httpx.Timeout(float(MODEL_CALL_TIMEOUT_SECONDS), connect=15.0),
        max_retries=0,
        default_headers={"HTTP-Referer": "http://localhost:5175", "X-Title": "AI Automation Office"},
    )


class JobControlSignal(RuntimeError):
    """A user paused or cancelled a Job while its provider call was pending."""


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MODEL_CALL_MAX_RETRIES = int(os.getenv("AI_OFFICE_MODEL_CALL_MAX_RETRIES", "3"))


def _is_retryable_model_error(error: BaseException) -> bool:
    """429/5xx and connection drops are transient -- worth a bounded retry. Anything else (bad request, auth) is not."""
    if getattr(error, "status_code", None) in RETRYABLE_STATUS_CODES:
        return True
    return isinstance(error, APIConnectionError)


def _call_model_with_backoff(client: OpenAI, **kwargs):
    attempt = 0
    while True:
        try:
            return client.responses.create(**kwargs)
        except BaseException as error:
            if attempt >= MODEL_CALL_MAX_RETRIES or not _is_retryable_model_error(error):
                raise
            delay = min(2**attempt, 20) + random.uniform(0, 1)
            attempt += 1
            time.sleep(delay)


def cancellable_model_response(client: OpenAI, task_id: str, job_id: str | None, **kwargs):
    """Wait without a generation deadline, but abandon late output on pause/cancel."""
    if not job_id:
        return _call_model_with_backoff(client, **kwargs)
    result: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            result.put((True, _call_model_with_backoff(client, **kwargs)))
        except BaseException as error:
            result.put((False, error))

    call_thread = Thread(target=invoke, daemon=True, name=f"model-{job_id}")
    call_thread.start()
    deadline = time.monotonic() + MODEL_CALL_TIMEOUT_SECONDS
    while call_thread.is_alive():
        call_thread.join(timeout=0.5)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Model call exceeded {MODEL_CALL_TIMEOUT_SECONDS} seconds")
        with database() as db:
            row = db.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row and row["state"] in {"pause_requested", "cancel_requested", "paused", "cancelled"}:
            raise JobControlSignal(f"Job control requested during model call: {row['state']}")
    succeeded, value = result.get()
    if succeeded:
        return value
    raise value


def public_model_settings() -> dict:
    settings = model_settings()
    return settings | {"configured": bool(model_key())}


def openrouter_models() -> list[dict]:
    try:
        request = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))["data"]
        models = [
            {
                "id": item["id"], "name": item.get("name", item["id"]), "context_length": item.get("context_length", 0),
                "pricing": {"prompt": item.get("pricing", {}).get("prompt", "0"), "completion": item.get("pricing", {}).get("completion", "0")},
            }
            for item in data if item.get("id")
        ]
        MODELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE_PATH.write_text(json.dumps(models, ensure_ascii=False), encoding="utf-8")
        return models
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        if MODELS_CACHE_PATH.exists():
            return json.loads(MODELS_CACHE_PATH.read_text(encoding="utf-8"))
        return [{"id": "openai/gpt-5", "name": "GPT-5", "context_length": 0}, {"id": "openai/gpt-5-mini", "name": "GPT-5 mini", "context_length": 0}]


def department_policy(employee_id: str) -> dict:
    employee = registry()[employee_id]
    return json.loads(DEPARTMENT_BOUNDARIES_PATH.read_text(encoding="utf-8"))[employee["team"]]


ARTIFACT_KIND_BY_TASK_KIND = {
    "market_research": "market_decision_report",
    "business_strategy": "market_decision_report",
    "product_planning": "product_design_spec",
    "customer_discovery": "product_design_spec",
    "experiment_design": "experiment_report",
    "experiment_analysis": "experiment_report",
    "architecture_design": "architecture_spec",
    "frontend_implementation": "implementation_report",
    "backend_implementation": "implementation_report",
    "ai_data_implementation": "ai_system_report",
    "test_engineering": "assurance_report",
    "accessibility_review": "assurance_report",
    "quality_review": "assurance_report",
    "security_review": "assurance_report",
    "privacy_review": "compliance_review",
    "legal_compliance": "compliance_review",
    "contract_review_draft": "compliance_review",
    "release_operations": "release_operations_report",
    "ci_cd_design": "release_operations_report",
    "cloud_operations": "release_operations_report",
    "launch_management": "release_operations_report",
    "observability_operations": "observability_runbook",
    "incident_response": "incident_response_report",
    "finops_review": "financial_model_report",
    "financial_planning": "financial_model_report",
    "retention_growth": "go_to_market_plan",
    "content_marketing": "go_to_market_plan",
    "brand_strategy": "go_to_market_plan",
    "sales_operations": "sales_operations_plan",
    "customer_support": "customer_support_runbook",
}


def deliverable_spec(request: str, task_kind: str | None = None) -> tuple[str, dict]:
    standards = json.loads(DELIVERABLE_STANDARDS_PATH.read_text(encoding="utf-8"))
    artifact_kind = ARTIFACT_KIND_BY_TASK_KIND.get(task_kind or "", "business_document")
    return artifact_kind, standards[artifact_kind]


def skill_ids_for_task(employee_id: str, request: str) -> list[str]:
    return []


def team_skill_pool(team: str) -> list[str]:
    """Skills belong to the department, not the individual -- a lead can command any skill its team holds."""
    return json.loads(SKILL_BINDINGS_PATH.read_text(encoding="utf-8"))[team]["skills"]


def employee_skill_pool(employee_id: str) -> list[str]:
    return team_skill_pool(registry()[employee_id]["team"])


def validate_selected_skills(
    employee_id: str,
    skill_ids: list[str],
    limit: int = 3,
    *,
    task_kind: str | None = None,
) -> list[str]:
    if not isinstance(skill_ids, list):
        raise HTTPException(422, "skill_ids must be a list")
    if len(skill_ids) > limit:
        raise HTTPException(422, f"At most {limit} skills may be selected")
    selected = list(dict.fromkeys(skill for skill in skill_ids if isinstance(skill, str)))
    unknown = sorted(set(selected) - set(employee_skill_pool(employee_id)))
    if unknown:
        raise HTTPException(403, f"Skills are not bound to {employee_id}: {', '.join(unknown)}")
    definitions = json.loads(SKILL_DEFINITIONS_PATH.read_text(encoding="utf-8"))
    blocked = []
    for skill_id in selected:
        activation = definitions.get(skill_id, {}).get("activation", {})
        allowed_kinds = set(activation.get("allowed_task_kinds", []))
        blocked_kinds = set(activation.get("blocked_task_kinds", []))
        if task_kind and (task_kind in blocked_kinds or (allowed_kinds and task_kind not in allowed_kinds)):
            blocked.append(skill_id)
    if blocked:
        raise HTTPException(403, f"Skills are blocked for {task_kind}: {', '.join(blocked)}")
    security = employee_security(employee_id, selected)
    missing = [check["skill_id"] for check in security["skills"] if not check["valid"]]
    if missing:
        raise HTTPException(409, f"Selected skills are not ready for {employee_id}: {', '.join(missing)}")
    return selected


def employee_security(employee_id: str, skill_ids: list[str] | None = None) -> dict:
    employee = registry()[employee_id]
    base = ROOT / Path(employee["profile_path"]).parent
    permissions = __import__("yaml").safe_load((base / "PERMISSIONS.yaml").read_text(encoding="utf-8"))
    pool = employee_skill_pool(employee_id)
    lock = json.loads(SKILLS_LOCK_PATH.read_text(encoding="utf-8"))["installed"]
    required = skill_ids if skill_ids is not None else pool
    unknown = sorted(set(required) - set(pool))
    if unknown:
        raise HTTPException(500, f"Task profile has unbound skills for {employee_id}: {', '.join(unknown)}")
    checks = []
    for skill_id in required:
        # One shared pool on disk instead of a copy per employee: the same skill text
        # was installed 3-4 times per department, and every copy had to be hashed and
        # locked separately. Employee folders keep only _local-role-core.
        path = SKILL_POOL_PATH / skill_id / "SKILL.md"
        locked = skill_id in lock
        checks.append({"skill_id": skill_id, "path": str(path.relative_to(ROOT)), "exists": path.exists(), "locked": locked, "valid": path.exists() and locked})
    return {"employee_id": employee_id, "permissions": permissions, "skills": checks, "ready": all(check["valid"] for check in checks)}


def require_skill_ready(employee_ids: list[str], request: str = "") -> None:
    unavailable = [employee_id for employee_id in employee_ids if not employee_security(employee_id, skill_ids_for_task(employee_id, request))["ready"]]
    if unavailable:
        raise HTTPException(409, f"Required skills are not ready for: {', '.join(unavailable)}")


ROLE_CORE_SKILL_ID = "_local-role-core"


def employee_skill_context(
    employee_id: str,
    request: str,
    # Measured: at 3000 only 19/151 bound skills arrived whole; at 16000, 133/151 do (worst case ~3 skills ~12k tokens).
    per_skill_limit: int = 16000,
    selected_skill_ids: list[str] | None = None,
    *,
    task_kind: str | None = None,
) -> dict:
    skill_ids = validate_selected_skills(employee_id, selected_skill_ids, 3, task_kind=task_kind) if selected_skill_ids is not None else skill_ids_for_task(employee_id, request)
    security = employee_security(employee_id, skill_ids)
    if not security["ready"]:
        raise HTTPException(409, f"Required skills are not ready for {employee_id}")
    content: list[dict] = []
    # The role core is this system's own operating manual (tools, contract gate,
    # evidence rules). It is deliberately not in the department pool: it must never
    # compete with the lead's three task skills, and it is always delivered.
    core = ROOT / Path(registry()[employee_id]["profile_path"]).parent / "skills" / ROLE_CORE_SKILL_ID / "SKILL.md"
    if core.exists():
        content.append({
            "id": ROLE_CORE_SKILL_ID,
            "path": str(core.relative_to(ROOT)),
            "instructions": core.read_text(encoding="utf-8", errors="replace")[:per_skill_limit],
        })
    for skill in security["skills"]:
        path = ROOT / skill["path"]
        text = path.read_text(encoding="utf-8", errors="replace")[:per_skill_limit]
        content.append({"id": skill["skill_id"], "path": skill["path"], "instructions": text})
    return {"permissions": security["permissions"], "required_skills": content, "profile_skill_ids": skill_ids}


def safe_project_root(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(422, "Project root must be an existing directory")
    return candidate


LEAD_IDS = {"NAVI", "FRAME", "BUILD", "LINK", "SHIP", "GUARD", "GROW", "LENS"}
TASK_KINDS = {
    "market_research", "business_strategy", "product_planning", "ui_design",
    "frontend_implementation", "backend_implementation", "ai_data_implementation",
    "release_operations", "quality_review", "security_review", "document_authoring", "general",
    "customer_discovery", "experiment_design", "experiment_analysis",
    "architecture_design", "test_engineering", "accessibility_review",
    "privacy_review", "legal_compliance", "contract_review_draft",
    "ci_cd_design", "cloud_operations", "observability_operations",
    "finops_review", "incident_response", "financial_planning",
    "launch_management", "sales_operations", "retention_growth",
    "content_marketing", "brand_strategy", "customer_support",
}


EMPLOYEE_TASK_KIND = {
    "BUILD": "architecture_design", "FRONT": "frontend_implementation", "BACK": "backend_implementation",
    "GUARD": "quality_review", "TRACE": "test_engineering", "SHIELD": "security_review",
    "SHIP": "release_operations", "SRE": "observability_operations", "COST": "finops_review",
    "FRAME": "product_planning", "FLOW": "ui_design", "MOSS": "ui_design",
    "LINK": "architecture_design", "SIGNAL": "ai_data_implementation", "EVAL": "test_engineering",
    "GROW": "market_research", "VOICE": "content_marketing", "PULSE": "experiment_analysis",
    "LENS": "customer_support", "JOURNEY": "customer_discovery", "DOCS": "document_authoring",
}


def default_task_kind(department: str, employee_id: str | None = None) -> str:
    if employee_id is not None and employee_id in EMPLOYEE_TASK_KIND:
        return EMPLOYEE_TASK_KIND[employee_id]
    return {
        "product-experience": "product_planning",
        "application": "general",
        "ai-data": "ai_data_implementation",
        "platform-reliability": "release_operations",
        "quality-security": "quality_review",
        "growth-marketing": "market_research",
        "service-knowledge": "document_authoring",
    }.get(department, "general")


def agent_role(employee_id: str) -> dict:
    employee = registry()[employee_id]
    lead = employee_id in LEAD_IDS
    return {
        "tier": "lead" if lead else "worker",
        "model_role": "lead_model" if lead else "worker_model",
        "responsibility": "delegate, review, debug, and report" if lead else "implement, edit files, and run scoped verification",
        "team": employee["team"],
        "title": employee["title"],
    }


def workspace_files(workspace: Path, limit: int = 160) -> list[str]:
    ignored = {".git", "node_modules", ".venv", "dist", "build", "__pycache__"}
    result: list[str] = []
    for path in workspace.rglob("*"):
        if any(part in ignored for part in path.relative_to(workspace).parts):
            continue
        if path.is_file():
            result.append(str(path.relative_to(workspace)).replace("\\", "/"))
            if len(result) >= limit:
                break
    return result


def validate_task_workspace(workspace: sqlite3.Row) -> tuple[Path, bool, str]:
    path = Path(workspace["path"]).resolve()
    root = Path(workspace["source_root"] if workspace["strategy"] == "in_place" else ROOT / "data" / "workspaces").resolve()
    allowed, reason = validate_path(root, path)
    return path, allowed, reason


def persist_deliverable(
    db: sqlite3.Connection,
    workspace: Path,
    task_id: str,
    owner: str,
    kind: str,
    content: str,
    *,
    filename: str,
    status: str,
) -> dict:
    output_root = (workspace / "AI_OFFICE_OUTPUTS" / task_id).resolve()
    if not output_root.is_relative_to(workspace):
        raise HTTPException(403, "Deliverable path escapes workspace")
    path = (output_root / filename).resolve()
    if not path.is_relative_to(output_root):
        raise HTTPException(403, "Invalid deliverable filename")
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.strip() + "\n"
    path.write_text(normalized, encoding="utf-8")
    artifact_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    relative_path = str(path.relative_to(workspace)).replace("\\", "/")
    deliverable_id = f"DEL-{task_id.split('-')[-1]}-{hashlib.sha256(relative_path.encode()).hexdigest()[:12]}"
    now = utc_now()
    db.execute(
        "INSERT INTO deliverables (id, task_id, owner, kind, path, status, artifact_sha256, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id, path) DO UPDATE SET "
        "owner=excluded.owner, kind=excluded.kind, status=excluded.status, "
        "artifact_sha256=excluded.artifact_sha256, updated_at=excluded.updated_at",
        (deliverable_id, task_id, owner, kind, relative_path, status, artifact_sha256, now, now),
    )
    db.execute(
        "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f"EVD-{task_id.split('-')[-1]}-DEL-{artifact_sha256[:12]}", task_id, None, "deliverable", "pass", artifact_sha256, 0, now),
    )
    return {"id": deliverable_id, "path": relative_path, "sha256": artifact_sha256, "status": status}


def register_existing_deliverable(
    db: sqlite3.Connection,
    workspace: Path,
    task_id: str,
    owner: str,
    kind: str,
    path: Path,
    status: str,
) -> dict:
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace.resolve()) or not resolved.is_file():
        raise HTTPException(403, "Rendered deliverable must exist inside workspace")
    artifact_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    relative_path = resolved.relative_to(workspace.resolve()).as_posix()
    deliverable_id = f"DEL-{task_id.split('-')[-1]}-{hashlib.sha256(relative_path.encode()).hexdigest()[:12]}"
    now = utc_now()
    db.execute(
        "INSERT INTO deliverables (id, task_id, owner, kind, path, status, artifact_sha256, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id, path) DO UPDATE SET "
        "owner=excluded.owner, kind=excluded.kind, status=excluded.status, "
        "artifact_sha256=excluded.artifact_sha256, updated_at=excluded.updated_at",
        (deliverable_id, task_id, owner, kind, relative_path, status, artifact_sha256, now, now),
    )
    db.execute(
        "INSERT OR REPLACE INTO evidence VALUES (?, ?, NULL, 'rendered_deliverable', 'pass', ?, 0, ?)",
        (f"EVD-{task_id.split('-')[-1]}-RENDER-{artifact_sha256[:12]}", task_id, artifact_sha256, now),
    )
    return {"id": deliverable_id, "path": relative_path, "sha256": artifact_sha256, "status": status}


def workspace_copy_ignore(source: str, names: list[str]) -> set[str]:
    ignored = {".git", "node_modules", ".venv", "dist", "build", "__pycache__"}
    try:
        current = Path(source).resolve()
        workspace_root = (ROOT / "data" / "workspaces").resolve()
        if workspace_root.is_relative_to(current):
            ignored.add("data")
    except OSError:
        pass
    return {name for name in names if name in ignored}


# MCP JSON-RPC client lives in apps/api/mcp_client.py; re-exported so existing
# ``main.mcp_*`` callers keep resolving. That module reads KEYRING_SERVICE back
# from here so the credential write (save_mcp_connection) and read cannot drift.
from apps.api.mcp_client import mcp_headers, mcp_http_call, mcp_initialize  # noqa: E402


def web_search(query: str, limit: int = 10) -> list[dict]:
    """Use configured Brave/SearXNG providers, then bounded Bing RSS fallback."""
    try:
        return search_public_web(query, limit)
    except SearchError as error:
        raise HTTPException(502, f"Web search failed: {error}") from error


def read_public_web_source(raw_url: str, limit: int = 12000) -> dict:
    try:
        return fetch_public_source(raw_url, text_limit=limit)
    except AgentToolError as error:
        raise HTTPException(error.status_code, str(error)) from error


def init_db() -> None:
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, request TEXT NOT NULL,
            state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_assignments (
            task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            PRIMARY KEY (task_id, employee_id)
        );
        CREATE TABLE IF NOT EXISTS task_plans (
            task_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, summary TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_agent_scopes (
            task_id TEXT NOT NULL, employee_id TEXT NOT NULL, assignment TEXT NOT NULL,
            skill_ids TEXT NOT NULL, deliverable TEXT NOT NULL, handoff_to TEXT,
            dependencies TEXT NOT NULL, sequence INTEGER NOT NULL,
            PRIMARY KEY (task_id, employee_id)
        );
        CREATE TABLE IF NOT EXISTS task_phases (
            task_id TEXT NOT NULL, phase_id TEXT NOT NULL, parent_phase_id TEXT,
            department TEXT NOT NULL, owner_id TEXT NOT NULL, task_kind TEXT NOT NULL,
            objective TEXT NOT NULL,
            expected_output TEXT NOT NULL, handoff_to TEXT, dependencies TEXT NOT NULL,
            skill_ids TEXT NOT NULL, status TEXT NOT NULL, artifact_ids TEXT NOT NULL,
            source TEXT NOT NULL, sequence INTEGER NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (task_id, phase_id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, action TEXT NOT NULL,
            from_state TEXT, to_state TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
            employee_ids TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_contracts (
            task_id TEXT PRIMARY KEY, allowed_paths TEXT NOT NULL, allowed_commands TEXT NOT NULL,
            acceptance_criteria TEXT NOT NULL, retry_limit INTEGER NOT NULL, token_limit INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, type TEXT NOT NULL, objective TEXT NOT NULL,
            participants TEXT NOT NULL, agenda TEXT NOT NULL, decisions TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS action_items (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, meeting_id TEXT, owner TEXT NOT NULL,
            description TEXT NOT NULL, sequence INTEGER NOT NULL, acceptance_criteria TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, root_path TEXT NOT NULL UNIQUE,
            git_available INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skill_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, ready INTEGER NOT NULL,
            result TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permission_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, employee_id TEXT NOT NULL,
            action TEXT NOT NULL, allowed INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_permission_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            action TEXT NOT NULL, effect TEXT NOT NULL, pattern TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permission_requests (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            action TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, source_root TEXT NOT NULL, path TEXT NOT NULL,
            strategy TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, workspace_id TEXT NOT NULL, command TEXT NOT NULL,
            exit_code INTEGER NOT NULL, stdout_sha256 TEXT NOT NULL, stderr_sha256 TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT, type TEXT NOT NULL, status TEXT NOT NULL,
            artifact_sha256 TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deliverables (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, owner TEXT NOT NULL, kind TEXT NOT NULL,
            path TEXT NOT NULL, status TEXT NOT NULL, artifact_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(task_id, path)
        );
        CREATE TABLE IF NOT EXISTS retry_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, failure_class TEXT NOT NULL,
            strategy_sha256 TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL, error TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            query TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, snippet TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            claim TEXT NOT NULL, source_url TEXT NOT NULL, publisher TEXT NOT NULL,
            published_at TEXT, retrieved_span TEXT NOT NULL, confidence REAL NOT NULL,
            contradictions TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_controls (
            task_id TEXT PRIMARY KEY, state_before_pause TEXT, pause_requested INTEGER NOT NULL DEFAULT 0,
            cancel_requested INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS steering_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, applied_at TEXT
        );
        CREATE TABLE IF NOT EXISTS task_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, label TEXT NOT NULL,
            snapshot TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, reviewer_id TEXT NOT NULL, verdict TEXT NOT NULL,
            findings TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS integration_reviews (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            reviewer_id TEXT NOT NULL, commit_sha TEXT NOT NULL, verdict TEXT NOT NULL,
            findings TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
            decided_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reflections (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, summary TEXT NOT NULL, root_causes TEXT NOT NULL,
            improvements TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, content TEXT NOT NULL, source_reflection_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mcp_connections (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, name TEXT NOT NULL, transport TEXT NOT NULL,
            server_url TEXT NOT NULL, credential_key TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL, step INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until TEXT,
            heartbeat_at TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, step INTEGER NOT NULL,
            name TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, job_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            state TEXT NOT NULL, model TEXT, started_at TEXT NOT NULL, finished_at TEXT, summary TEXT
        );
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, job_id TEXT NOT NULL,
            agent_id TEXT NOT NULL, tool_name TEXT NOT NULL, input_summary TEXT NOT NULL,
            output_summary TEXT NOT NULL, status TEXT NOT NULL, duration_ms INTEGER, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, job_id TEXT,
            agent_id TEXT, type TEXT NOT NULL, summary TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_leases (
            job_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, heartbeat_at TEXT NOT NULL, lease_until TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id TEXT PRIMARY KEY, build_id TEXT NOT NULL, heartbeat_at TEXT NOT NULL
        );
        """)
        ensure_session_schema(db)
        ensure_column(db, "worker_heartbeats", "error_streak", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "worker_heartbeats", "last_error", "TEXT")
        ensure_column(db, "jobs", "error_class", "TEXT")
        ensure_column(db, "tasks", "route", "TEXT NOT NULL DEFAULT 'navi'")
        ensure_column(db, "tasks", "lead_id", "TEXT")
        ensure_column(db, "tasks", "parent_task_id", "TEXT")
        ensure_column(db, "task_phases", "task_kind", "TEXT NOT NULL DEFAULT 'general'")
        ensure_column(db, "retry_attempts", "strategy", "TEXT")
        # Old plan rows were placeholders, not real meetings. Preserve audit, hide from runtime.
        db.execute("UPDATE meetings SET status = 'superseded' WHERE status = 'concluded' AND type = 'team_lead' AND id NOT IN (SELECT DISTINCT m.id FROM meetings m JOIN agent_messages a ON a.task_id = m.task_id WHERE a.kind = 'meeting')")
        # Older tool events stored raw file/command output in a UI summary. Keep
        # audit metadata while removing content that must never reach bubbles.
        db.execute("UPDATE job_events SET summary = '파일 읽기 완료 · 기존 상세 내용 제거' WHERE type IN ('tool.completed','tool.failed') AND payload LIKE '%read_file%'")
        db.execute("UPDATE job_events SET summary = '파일 목록 확인 완료 · 기존 상세 내용 제거' WHERE type IN ('tool.completed','tool.failed') AND payload LIKE '%list_files%'")
        db.execute("UPDATE job_events SET summary = '검증 명령 완료 · 기존 상세 출력 제거' WHERE type IN ('tool.completed','tool.failed') AND payload LIKE '%run_verification%'")
        db.execute("UPDATE tool_calls SET output_summary = '파일 읽기 완료 · 기존 상세 내용 제거' WHERE tool_name = 'read_file'")
        db.execute("UPDATE tool_calls SET output_summary = '파일 목록 확인 완료 · 기존 상세 내용 제거' WHERE tool_name = 'list_files'")
        db.execute("UPDATE tool_calls SET output_summary = '검증 명령 완료 · 기존 상세 출력 제거' WHERE tool_name = 'run_verification'")


def task_payload(db: sqlite3.Connection, task_id: str) -> dict:
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Task not found")
    assigned = [r[0] for r in db.execute("SELECT employee_id FROM task_assignments WHERE task_id = ?", (task_id,))]
    events = [dict(r) | {"employee_ids": json.loads(r["employee_ids"])} for r in db.execute(
        "SELECT * FROM events WHERE task_id = ? ORDER BY id DESC", (task_id,)
    )]
    evidence = [dict(row) for row in db.execute("SELECT * FROM evidence WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    contract = db.execute("SELECT * FROM task_contracts WHERE task_id = ?", (task_id,)).fetchone()
    permission_rules = [dict(row) for row in db.execute("SELECT action, effect, pattern FROM task_permission_rules WHERE task_id = ? ORDER BY id", (task_id,))]
    permission_requests = [dict(row) for row in db.execute("SELECT * FROM permission_requests WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    meetings = [dict(row) | {key: json.loads(row[key]) for key in ("participants", "agenda", "decisions")} for row in db.execute("SELECT * FROM meetings WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    items = [dict(row) | {"acceptance_criteria": json.loads(row["acceptance_criteria"])} for row in db.execute("SELECT * FROM action_items WHERE task_id = ? ORDER BY sequence", (task_id,))]
    reviews = [dict(row) for row in db.execute("SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    integration_reviews = [dict(row) for row in db.execute("SELECT * FROM integration_reviews WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    approvals = [dict(row) for row in db.execute("SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    reflections = [dict(row) | {key: json.loads(row[key]) for key in ("root_causes", "improvements")} for row in db.execute("SELECT * FROM reflections WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    lessons = [dict(row) for row in db.execute("SELECT * FROM lessons WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    agent_messages = [dict(row) for row in db.execute("SELECT * FROM agent_messages WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    model_usage = [dict(row) for row in db.execute("SELECT * FROM model_usage WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    research_sources = [dict(row) for row in db.execute("SELECT * FROM research_sources WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    research_claims = [dict(row) | {"contradictions": json.loads(row["contradictions"])} for row in db.execute("SELECT * FROM research_claims WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    retry_attempts = [dict(row) for row in db.execute("SELECT * FROM retry_attempts WHERE task_id = ? ORDER BY id DESC", (task_id,))]
    checkpoints = [dict(row) | {"snapshot": json.loads(row["snapshot"])} for row in db.execute("SELECT * FROM task_checkpoints WHERE task_id = ? ORDER BY id DESC", (task_id,))]
    jobs = [dict(row) | {"payload": json.loads(row["payload"])} for row in db.execute("SELECT * FROM jobs WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    job_events = [dict(row) | {"payload": json.loads(row["payload"])} for row in db.execute("SELECT * FROM job_events WHERE task_id = ? ORDER BY id DESC LIMIT 120", (task_id,))]
    agent_runs = [dict(row) for row in db.execute("SELECT * FROM agent_runs WHERE task_id = ? ORDER BY started_at DESC", (task_id,))]
    agent_sessions = [dict(row) for row in db.execute("SELECT * FROM agent_sessions WHERE task_id = ? ORDER BY employee_id", (task_id,))]
    tool_calls = [dict(row) for row in db.execute("SELECT * FROM tool_calls WHERE task_id = ? ORDER BY id DESC LIMIT 120", (task_id,))]
    steering_messages = [dict(row) for row in db.execute("SELECT * FROM steering_messages WHERE task_id = ? ORDER BY id", (task_id,))]
    deliverables = [dict(row) for row in db.execute("SELECT * FROM deliverables WHERE task_id = ? ORDER BY updated_at DESC", (task_id,))]
    plan_row = db.execute("SELECT * FROM task_plans WHERE task_id = ?", (task_id,)).fetchone()
    execution_plan = (dict(plan_row) | {"plan": json.loads(plan_row["plan_json"])}) if plan_row else None
    agent_scopes = [
        dict(row) | {"skill_ids": json.loads(row["skill_ids"]), "dependencies": json.loads(row["dependencies"])}
        for row in db.execute("SELECT * FROM task_agent_scopes WHERE task_id = ? ORDER BY sequence", (task_id,))
    ]
    phases = [
        dict(row) | {
            "skill_ids": json.loads(row["skill_ids"]),
            "dependencies": json.loads(row["dependencies"]),
            "artifact_ids": json.loads(row["artifact_ids"]),
        }
        for row in db.execute("SELECT * FROM task_phases WHERE task_id = ? ORDER BY sequence, phase_id", (task_id,))
    ]
    budget_spent = sum(item["input_tokens"] + item["output_tokens"] for item in model_usage)
    return dict(task) | {"assigned_employees": assigned, "events": events, "evidence": evidence, "deliverables": deliverables, "execution_plan": execution_plan, "agent_scopes": agent_scopes, "phases": phases, "steering_messages": steering_messages, "state_label": STATE_LABELS[task["state"]], "contract": ((dict(contract) | {key: json.loads(contract[key]) for key in ("allowed_paths", "allowed_commands", "acceptance_criteria")} | {"permission_rules": permission_rules}) if contract else None), "permission_requests": permission_requests, "meetings": meetings, "action_items": items, "reviews": reviews, "integration_reviews": integration_reviews, "approvals": approvals, "reflections": reflections, "lessons": lessons, "agent_messages": agent_messages, "model_usage": model_usage, "research_sources": research_sources, "research_claims": research_claims, "retry_attempts": retry_attempts, "checkpoints": checkpoints, "jobs": jobs, "job_events": job_events, "agent_runs": agent_runs, "agent_sessions": agent_sessions, "tool_calls": tool_calls, "budget_spent": budget_spent}


def consume_steering_messages(db: sqlite3.Connection, task_id: str) -> list[dict]:
    rows = list(db.execute(
        "SELECT id, content, created_at FROM steering_messages "
        "WHERE task_id = ? AND status = 'queued' ORDER BY id",
        (task_id,),
    ))
    if not rows:
        return []
    now = utc_now()
    db.executemany(
        "UPDATE steering_messages SET status = 'applied', applied_at = ? WHERE id = ?",
        [(now, row["id"]) for row in rows],
    )
    return [dict(row) for row in rows]


HEARTBEAT_EVENTS_KEPT_PER_JOB = 5  # ponytail: job.heartbeat fires every 15s for a job's whole runtime and was the actual driver of 4000-event jobs; other event types are step-bounded and don't need trimming.


def emit_job_event(db: sqlite3.Connection, task_id: str, event_type: str, summary: str, *, job_id: str | None = None, agent_id: str | None = None, payload: dict | None = None) -> None:
    db.execute("INSERT INTO job_events (task_id, job_id, agent_id, type, summary, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, job_id, agent_id, event_type, summary[:500], json.dumps(payload or {}, ensure_ascii=False), utc_now()))
    if job_id and event_type == "job.heartbeat":
        db.execute(
            "DELETE FROM job_events WHERE job_id = ? AND type = 'job.heartbeat' AND id NOT IN "
            "(SELECT id FROM job_events WHERE job_id = ? AND type = 'job.heartbeat' ORDER BY id DESC LIMIT ?)",
            (job_id, job_id, HEARTBEAT_EVENTS_KEPT_PER_JOB),
        )


def purge_old_job_events(db: sqlite3.Connection, retain_days: int = 30) -> int:
    """Drop job_events for jobs finished more than retain_days ago. Call this rarely, not per-request."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retain_days)).isoformat()
    deleted = db.execute(
        "DELETE FROM job_events WHERE job_id IN (SELECT id FROM jobs WHERE state IN ('succeeded', 'failed', 'cancelled') AND updated_at < ?)",
        (cutoff,),
    ).rowcount
    return deleted


ERROR_CLASS_RULES = [  # checked in order, first substring match wins
    ("budget_exceeded", "budget"),
    ("invalid_prompt", "invalid_prompt"),
    ("model_key_missing", "API key is not configured"),
    ("contract_required", "TaskContract required"),
    ("not_assigned", "not assigned"),
    ("meeting_not_found", "meeting not found"),
    ("worker_restarted", "Worker restarted"),
    ("model_call_failed", "Model"),
]


def classify_error(error: str | None) -> str | None:
    if not error:
        return None
    for label, needle in ERROR_CLASS_RULES:
        if needle.lower() in error.lower():
            return label
    return "unknown"


def record_usage(db: sqlite3.Connection, task_id: str, model: str, input_tokens: int = 0, output_tokens: int = 0, error: str | None = None) -> float:
    """Single choke point for model_usage rows -- fills in real cost_usd from pricing.py."""
    cost_usd = pricing.usd_cost(model, input_tokens, output_tokens)
    db.execute(
        "INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, model, input_tokens, output_tokens, cost_usd, error, utc_now()),
    )
    return cost_usd


def check_budget(db: sqlite3.Connection, task_id: str) -> None:
    """Reject new jobs once spend hits a configured ceiling. 0/unset = no cap."""
    task_ceiling = float(os.environ.get("AI_OFFICE_TASK_BUDGET_USD", "0"))
    if task_ceiling > 0:
        spent = db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE task_id = ?", (task_id,)).fetchone()[0]
        if spent >= task_ceiling:
            raise HTTPException(402, f"Task budget ${task_ceiling:.2f} reached (spent ${spent:.2f})")
    daily_ceiling = float(os.environ.get("AI_OFFICE_DAILY_BUDGET_USD", "0"))
    if daily_ceiling > 0:
        spent_today = db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ?", (utc_now()[:10],)).fetchone()[0]
        if spent_today >= daily_ceiling:
            raise HTTPException(402, f"Daily budget ${daily_ceiling:.2f} reached (spent ${spent_today:.2f})")


def enqueue_job(db: sqlite3.Connection, task_id: str, kind: str, payload: dict) -> dict:
    check_budget(db, task_id)
    count = db.execute("SELECT COUNT(*) FROM jobs WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
    now = utc_now(); job_id = f"JOB-{task_id.split('-')[-1]}-{count:03d}"
    job = {"id": job_id, "task_id": task_id, "kind": kind, "payload": payload, "state": "queued", "step": 0, "created_at": now, "updated_at": now}
    db.execute("INSERT INTO jobs (id, task_id, kind, payload, state, step, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (job_id, task_id, kind, json.dumps(payload, ensure_ascii=False), "queued", 0, now, now))
    emit_job_event(db, task_id, "job.queued", f"{kind} 작업 대기", job_id=job_id, payload={"kind": kind})
    return job


def planned_roster(request: str) -> tuple[list[str], list[tuple[str, str]]]:
    return ["FRAME"], [("FRAME", "요청을 재검토하고 최소 실행 범위와 인계 지점을 확정")]


PERMISSION_TIER = {
    "P0_READ": "read", "P1_PROPOSE": "read",
    "P2_ANALYTICS_DOC_WRITE": "write_content", "P2_ARCH_WRITE": "write_content",
    "P2_CONTENT_WRITE": "write_content", "P2_DESIGN_SPEC_WRITE": "write_content",
    "P2_DOC_WRITE": "write_content", "P2_MARKETING_DOC_WRITE": "write_content",
    "P2_SPEC_WRITE": "write_content", "P2_STATE_WRITE": "write_content", "P2_WRITE_SCOPED": "write_content",
    "P3_DOC_CHECK": "verify", "P3_TEST_LOCAL": "verify", "P3_SECURITY_SCAN": "verify",
    "P4_EVIDENCE_WRITE": "evidence", "P4_GIT_SAFE": "git_safe", "P5_STAGING_WITH_APPROVAL": "staging",
    # No matching agent tool exists yet for these -- kept in PERMISSIONS.yaml for documentation,
    # deliberately no-op here. See docs/superpowers/specs/2026-08-06-permission-tool-gate-design.md.
    "P3_PROCESS_CONTROL": None, "P4_EVIDENCE_READ": None, "P4_REVIEW": None,
}

TIER_TOOLS = {
    "read": {
        "list_files", "read_file", "search_files", "find_symbols", "find_references",
        "git_status", "git_diff", "discover_tests", "language_diagnostics", "read_required_skill",
    },
    "write_content": {"create_file", "replace_exact_text", "apply_unified_patch"},
    "verify": {"run_verification"},
    "evidence": {"record_research_claim"},
    "git_safe": {"git_commit"},
    "staging": {"git_push"},
}

GATED_TOOL_NAMES = {name for names in TIER_TOOLS.values() for name in names}


def permission_tool_scope(permission_codes: list[str]) -> set[str]:
    """Tool names a PERMISSIONS.yaml permissions list unlocks. Unknown/unmapped codes grant nothing."""
    scope: set[str] = set()
    for code in permission_codes:
        tier = PERMISSION_TIER.get(code)
        if tier:
            scope |= TIER_TOOLS[tier]
    return scope


def apply_stage_ordering(phases: list[dict], boundaries: dict) -> None:
    """Force each phase to depend on every lower-stage phase already in this plan.

    The planner LLM proposes phases and depends_on freely; it isn't reliable about
    respecting department order (plan -> build -> review). Stage is a coarse ordering
    read from department-boundaries.json ("stage" 0-3). Mutates depends_on in place --
    the union with whatever depends_on the LLM already declared is intentional so
    same-stage hints survive. Same-stage phases are left mutually independent so the
    existing worktree-parallel scheduler (queue_ready_agent_jobs) can run them
    concurrently; only cross-stage ordering is enforced here.
    """
    stage_by_department = {department: policy.get("stage", 1) for department, policy in boundaries.items()}
    for phase in phases:
        phase_stage = stage_by_department.get(phase["department"], 1)
        upstream_ids = {
            other["id"] for other in phases
            if other is not phase and stage_by_department.get(other["department"], 1) < phase_stage
        }
        if upstream_ids:
            phase["depends_on"] = sorted(set(phase["depends_on"]) | upstream_ids)


def select_roster_with_model(request: str, task_id: str = "", job_id: str | None = None) -> tuple[list[str], list[tuple[str, str]], str, dict | None]:
    fallback_roster, fallback_items = planned_roster(request)
    if not model_key():
        return fallback_roster, fallback_items, "판단 모델을 사용할 수 없어 FRAME이 요청 재검토를 맡습니다.", None
    people = registry()
    bindings = json.loads(SKILL_BINDINGS_PATH.read_text(encoding="utf-8"))
    boundaries = json.loads(DEPARTMENT_BOUNDARIES_PATH.read_text(encoding="utf-8"))
    standards = json.loads(DELIVERABLE_STANDARDS_PATH.read_text(encoding="utf-8"))
    organization = []
    for department, boundary in boundaries.items():
        members = [boundary["lead"], *boundary["workers"]]
        organization.append({
            "department": department,
            "owns": boundary["owns"],
            "must_handoff": boundary["must_handoff"],
            "lead": boundary["lead"],
            "team_skills": bindings[department]["skills"],  # pooled at department level; a lead may command any of these for any teammate
            "members": [{"id": employee, "title": people[employee]["title"]} for employee in members],
        })
    instructions = (
        "You are the operating chief. Think through the request and design a minimal, adaptive company workflow; do not classify by keywords. "
        "Use department ownership as constraints, not as a canned workflow. Add a department only when its output changes the result. "
        "Build a deliverable chain, not parallel opinions: every later phase that uses earlier work must name that phase in depends_on, state exact input it consumes in objective, and state exact file/evidence it hands off. "
        "Typical example when relevant: verified research -> product decision/PRD -> implementation -> independent quality/security gate -> release or final document. Omit steps that do not change this request. Choose one accountable final owner. "
        "For research, define source quality, recency, triangulation, and decision criteria. For implementation, define verification and independent review proportional to risk. "
        "If any phase is market_research, business_strategy, product_planning, or customer_discovery, requires_web_research must be true and evidence_strategy must require comparing at least two existing competitors or alternatives and naming this product's differentiation. "
        "Choose an artifact kind from the supplied standards. Decide workspace_context as none, read, or write based on whether local project files are relevant. "
        "Return strict JSON only with: summary (<=160 Korean chars), artifact_kind, final_owner, workspace_context, requires_web_research (boolean), evidence_strategy, "
        "phases:[{id,department,lead_id,task_kind,objective,output,handoff_to,depends_on,skill_ids}], reason. "
        f"Each phase task_kind must be one of {sorted(TASK_KINDS)} and describe required capability, not a keyword guess. "
        "For each phase select zero to three skill_ids only from that lead's listed skills. Select only skills that materially help its exact objective/output; do not select UI or design skills for market research, planning, document writing, or review. "
        "Select 1-4 leads. Every lead_id must be the listed lead of its department. final_owner must be selected. No worker assignment yet."
    )
    client = model_client()
    response = cancellable_model_response(
        client, task_id, job_id, model=model_assignment("NAVI")["model"], instructions=instructions,
        input=json.dumps({"request": request, "organization": organization, "artifact_standards": standards}, ensure_ascii=False),
    )
    match = re.search(r"\{.*\}", response.output_text, re.S)
    if not match:
        raise ValueError("Planner returned no JSON object")
    payload = json.loads(match.group())
    valid_leads = {boundary["lead"]: department for department, boundary in boundaries.items() if boundary["lead"] != "NAVI"}
    phases = []
    for index, phase in enumerate(payload.get("phases", [])[:4], 1):
        if not isinstance(phase, dict):
            continue
        lead = phase.get("lead_id")
        if lead not in valid_leads:
            continue
        objective = str(phase.get("objective") or "").strip()
        output = str(phase.get("output") or "").strip()
        if not objective or not output:
            continue
        task_kind = phase.get("task_kind")
        if task_kind not in TASK_KINDS:
            task_kind = default_task_kind(valid_leads[lead], lead)
        selected_skills = validate_selected_skills(lead, phase.get("skill_ids", []), 3, task_kind=task_kind)
        phases.append({
            "id": str(phase.get("id") or f"phase-{index}")[:80],
            "department": valid_leads[lead],
            "lead_id": lead,
            "task_kind": task_kind,
            "objective": objective[:800],
            "output": output[:500],
            "handoff_to": str(phase.get("handoff_to") or "")[:40] or None,
            "depends_on": [str(item)[:80] for item in phase.get("depends_on", []) if isinstance(item, str)][:6],
            "skill_ids": selected_skills,
        })
    seen_phase_ids: set[str] = set()
    for index, phase in enumerate(phases):
        original_id = phase["id"]
        if original_id in seen_phase_ids:
            phase["id"] = f"{original_id}-{index + 1}"
        previous_ids = {item["id"] for item in phases[:index]}
        phase["depends_on"] = [item for item in phase["depends_on"] if item in previous_ids]
        seen_phase_ids.add(phase["id"])
    apply_stage_ordering(phases, boundaries)
    agents = list(dict.fromkeys(phase["lead_id"] for phase in phases))
    final_owner = payload.get("final_owner")
    artifact_kind = payload.get("artifact_kind")
    if not agents:
        raise ValueError(
            f"Planner returned an invalid workflow: leads={agents}, final_owner={final_owner}, "
            f"artifact_kind={artifact_kind}, phase_count={len(payload.get('phases', []))}"
        )
    if final_owner not in agents:
        final_owner = agents[-1]
    if artifact_kind not in standards:
        artifact_kind = "business_document"
    workspace_context = payload.get("workspace_context")
    if workspace_context not in {"none", "read", "write"}:
        workspace_context = "read"
    # Product/strategy phases decide what to build or how to position it; skipping
    # competitive and differentiation research there ships an uninformed decision.
    # The planner model is asked for requires_web_research but not trusted to always
    # set it, so a product-shaped plan forces the flag and appends the requirement
    # instead of hoping the prompt was followed.
    product_shaped = any(phase["task_kind"] in {"market_research", "business_strategy", "product_planning", "customer_discovery"} for phase in phases)
    requires_web_research = bool(payload.get("requires_web_research")) or product_shaped
    evidence_strategy = str(payload.get("evidence_strategy") or "")[:1200]
    if product_shaped and "차별" not in evidence_strategy and "경쟁" not in evidence_strategy:
        evidence_strategy = (evidence_strategy + " 기존 경쟁 서비스·대안을 최소 2건 조사하고 이 제품과의 차별점을 명시한다.").strip()[:1200]
    plan = {
        "summary": str(payload.get("summary") or "동적 실행 계획")[:160],
        "artifact_kind": artifact_kind,
        "final_owner": final_owner,
        "workspace_context": workspace_context,
        "requires_web_research": requires_web_research,
        "evidence_strategy": evidence_strategy,
        "phases": phases,
        "reason": str(payload.get("reason") or "")[:1200],
    }
    items = [(phase["lead_id"], f"{phase['objective']} → {phase['output']}") for phase in phases]
    usage = getattr(response, "usage", None)
    return agents, items, plan["summary"], {
        "model": model_assignment("NAVI")["model"],
        "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
        "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
        "plan": plan,
    }


def store_execution_plan(db: sqlite3.Connection, task_id: str, plan: dict) -> None:
    now = utc_now()
    summary = str(plan.get("summary") or "실행 계획")[:160]
    db.execute(
        "INSERT INTO task_plans (task_id, plan_json, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(task_id) DO UPDATE SET plan_json=excluded.plan_json, summary=excluded.summary, updated_at=excluded.updated_at",
        (task_id, json.dumps(plan, ensure_ascii=False), summary, now, now),
    )
    db.execute("DELETE FROM task_phases WHERE task_id = ?", (task_id,))
    for sequence, phase in enumerate(plan.get("phases", []), 1):
        lead = phase.get("lead_id")
        if lead not in registry():
            continue
        phase_id = str(phase.get("id") or f"phase-{sequence}")[:80]
        dependencies = [str(item)[:80] for item in phase.get("depends_on", []) if isinstance(item, str)]
        skill_ids = validate_selected_skills(lead, phase.get("skill_ids", []), 3)
        db.execute(
            "INSERT INTO task_phases "
            "(task_id, phase_id, parent_phase_id, department, owner_id, task_kind, objective, expected_output, handoff_to, "
            "dependencies, skill_ids, status, artifact_ids, source, sequence, created_at, updated_at) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', '[]', 'plan', ?, ?, ?)",
            (
                task_id, phase_id, registry()[lead]["team"], lead,
                phase.get("task_kind") or default_task_kind(registry()[lead]["team"], lead),
                str(phase.get("objective") or "")[:800], str(phase.get("output") or "")[:500],
                phase.get("handoff_to"), json.dumps(dependencies, ensure_ascii=False),
                json.dumps(skill_ids, ensure_ascii=False), sequence * 100, now, now,
            ),
        )
        db.execute(
            "INSERT INTO task_agent_scopes (task_id, employee_id, assignment, skill_ids, deliverable, handoff_to, dependencies, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id, employee_id) DO UPDATE SET "
            "assignment=excluded.assignment, skill_ids=excluded.skill_ids, deliverable=excluded.deliverable, handoff_to=excluded.handoff_to, "
            "dependencies=excluded.dependencies, sequence=excluded.sequence",
            (
                task_id, lead, str(phase.get("objective") or "")[:800], json.dumps(skill_ids, ensure_ascii=False),
                str(phase.get("output") or "")[:500], phase.get("handoff_to"),
                json.dumps(dependencies, ensure_ascii=False), sequence,
            ),
        )


def assert_completion_invariants(
    db: sqlite3.Connection,
    task_id: str,
    workspace: Path,
    *,
    current_job_id: str | None = None,
) -> dict:
    final = db.execute(
        "SELECT * FROM deliverables WHERE task_id = ? AND status IN ('final_candidate', 'approved') "
        "ORDER BY updated_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if not final:
        raise RuntimeError("Completion requires a final deliverable")
    path = (workspace / final["path"]).resolve()
    if not path.is_relative_to(workspace) or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("Completion requires a non-empty final deliverable file")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != final["artifact_sha256"]:
        raise RuntimeError("Final deliverable hash does not match the recorded artifact")
    incomplete = db.execute(
        "SELECT phase_id, status FROM task_phases WHERE task_id = ? "
        "AND status NOT IN ('completed', 'skipped') ORDER BY sequence LIMIT 1",
        (task_id,),
    ).fetchone()
    if incomplete:
        raise RuntimeError(f"Completion blocked by phase {incomplete['phase_id']} ({incomplete['status']})")
    active = db.execute(
        "SELECT id FROM jobs WHERE task_id = ? AND id != COALESCE(?, '') "
        "AND state IN ('queued','running','pause_requested','cancel_requested') LIMIT 1",
        (task_id, current_job_id),
    ).fetchone()
    if active:
        raise RuntimeError(f"Completion blocked by active job {active['id']}")
    review = db.execute(
        "SELECT reviewer_id FROM reviews WHERE task_id = ? AND verdict = 'pass' ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if not review:
        raise RuntimeError("Completion requires a passing independent review")
    plan_row = db.execute("SELECT plan_json FROM task_plans WHERE task_id = ?", (task_id,)).fetchone()
    plan = json.loads(plan_row["plan_json"]) if plan_row else {}
    final_owner = plan.get("final_owner")
    if final_owner and review["reviewer_id"] == final_owner:
        raise RuntimeError("Final owner cannot approve their own deliverable")
    if plan.get("requires_web_research"):
        research = load_task_research(db, task_id)
        artifact_text = path.read_text(encoding="utf-8", errors="replace")
        coverage = claim_source_coverage(research["claims"], research["sources"])
        ratio = primary_source_ratio(research["sources"])
        resolution = contradiction_resolution(research["claims"], artifact_text)
        linkage = recommendation_linkage(research["claims"], artifact_text)
        quality = evaluate_research_quality(coverage, ratio, resolution, linkage)
        if not quality["passed"]:
            details = "; ".join(
                f"{failure['metric']}={failure['score']:.2f} (threshold {failure['threshold']}, "
                f"offenders: {failure['offenders'][:2]})"
                for failure in quality["failures"]
            )
            raise RuntimeError(f"Research quality gate failed: {details}")
    execution_kinds = {
        "frontend_implementation", "backend_implementation", "ai_data_implementation",
        "test_engineering", "release_operations", "ci_cd_design", "cloud_operations",
        "observability_operations",
    }
    task_kinds = {
        row["task_kind"]
        for row in db.execute("SELECT DISTINCT task_kind FROM task_phases WHERE task_id = ?", (task_id,))
    }
    if task_kinds.intersection(execution_kinds):
        passed_run = db.execute(
            "SELECT 1 FROM runs WHERE task_id = ? AND status = 'pass' LIMIT 1",
            (task_id,),
        ).fetchone()
        if not passed_run:
            raise RuntimeError("Implementation and release completion require a passing executed verification command")
    failed_run = db.execute("SELECT 1 FROM runs WHERE task_id = ? AND status = 'fail' LIMIT 1", (task_id,)).fetchone()
    if failed_run:
        raise RuntimeError("Completion blocked by a failed verification command")
    supporting_evidence = db.execute(
        "SELECT 1 FROM evidence WHERE task_id = ? AND stale = 0 AND status = 'pass' "
        "AND type != 'lead_review' LIMIT 1",
        (task_id,),
    ).fetchone()
    if not supporting_evidence:
        raise RuntimeError("Completion requires passing execution or verification evidence")
    failed_evidence = db.execute(
        "SELECT 1 FROM evidence WHERE task_id = ? AND stale = 0 AND status = 'fail' "
        "AND type IN ('command','verification') LIMIT 1",
        (task_id,),
    ).fetchone()
    if failed_evidence:
        raise RuntimeError("Completion blocked by current failing verification evidence")
    if task_requires_user_approval(db, task_id):
        approval = db.execute(
            "SELECT 1 FROM approvals WHERE task_id = ? AND decision = 'approve' AND decided_by = 'USER' LIMIT 1",
            (task_id,),
        ).fetchone()
        if not approval:
            raise RuntimeError("Completion requires explicit user approval for external, sales, support, privacy, or legal work")
    return dict(final)


def task_requires_user_approval(db: sqlite3.Connection, task_id: str) -> bool:
    sensitive_kinds = {
        "privacy_review",
        "legal_compliance",
        "contract_review_draft",
        "sales_operations",
        "customer_support",
    }
    definitions = json.loads(SKILL_DEFINITIONS_PATH.read_text(encoding="utf-8"))
    for row in db.execute("SELECT task_kind, skill_ids FROM task_phases WHERE task_id = ?", (task_id,)):
        if row["task_kind"] in sensitive_kinds:
            return True
        for skill_id in json.loads(row["skill_ids"]):
            activation = definitions.get(skill_id, {}).get("activation", {})
            if activation.get("requires_human_review") or activation.get("requires_approval"):
                return True
    return False


def fallback_execution_plan(roster: list[str], items: list[tuple[str, str]]) -> dict:
    leads = [employee for employee in roster if employee in LEAD_IDS and employee != "NAVI"] or ["FRAME"]
    phases = [
        {
            "id": f"fallback-{index}",
            "department": registry()[lead]["team"],
            "lead_id": lead,
            "task_kind": default_task_kind(registry()[lead]["team"], lead),
            "objective": next((description for owner, description in items if owner == lead), "요청을 재검토한다."),
            "output": "검증 가능한 부서 산출물",
            "handoff_to": leads[0],
            "depends_on": [],
            "skill_ids": [],
        }
        for index, lead in enumerate(leads, 1)
    ]
    # Deterministic fallback (model call failed) can still span multiple departments --
    # it needs the same stage ordering as the LLM-planned path, or it becomes the one
    # way to bypass the pipeline gate.
    apply_stage_ordering(phases, json.loads(DEPARTMENT_BOUNDARIES_PATH.read_text(encoding="utf-8")))
    return {
        "summary": "판단 모델 실패로 최소 재검토 계획을 사용합니다.",
        "artifact_kind": "business_document",
        "final_owner": leads[0],
        "workspace_context": "read",
        "requires_web_research": False,
        "evidence_strategy": "요청에 필요한 근거를 실행자가 식별하고 출처와 검증 결과를 남긴다.",
        "reason": "모델 응답이 유효하지 않아 확장 작업 전 재검토가 필요하다.",
        "phases": phases,
    }


def office_projection(task: dict | None) -> list[dict]:
    assigned = set(task["assigned_employees"] if task else [])
    state = task["state"] if task else "draft"
    result = []
    for employee_id, employee in registry().items():
        active = employee_id in assigned and state != "draft"
        result.append({
            "id": employee_id, "team": employee["team"], "title": employee["title"],
            "runtime": employee["runtime"], "state": state if active else "draft",
            "label": STATE_LABELS[state] if active else "대기",
            "zone": STATUS_TO_ZONE[state] if active else "desk", "active": active,
        })
    return result


app = FastAPI(title="AI Office API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup() -> None:
    init_db()


@app.post("/api/tasks/{task_id}/agent/run")
def run_agent(task_id: str, payload: AgentRunInput) -> dict:
    """Run one assigned agent with file tools restricted to its task workspace."""
    key = model_key()
    if not key:
        raise HTTPException(409, "OpenRouter API key is not configured")
    if payload.employee_id not in registry():
        raise HTTPException(404, "Employee not found")
    with database() as db:
        task = task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "TaskContract required before agent execution")
        if payload.employee_id not in task["assigned_employees"]:
            raise HTTPException(403, "Agent is not assigned to this task")
        workspace_row = db.execute("SELECT * FROM workspaces WHERE id = ? AND task_id = ?", (payload.workspace_id, task_id)).fetchone()
        if not workspace_row:
            raise HTTPException(404, "Workspace not found")
        workspace, safe, reason = validate_task_workspace(workspace_row)
        if not safe:
            raise HTTPException(403, reason)

        role = agent_role(payload.employee_id)
        effective_request = payload.instruction or task["request"]
        dynamic_plan = task["execution_plan"]["plan"] if task.get("execution_plan") else {}
        evidence_strategy = str(dynamic_plan.get("evidence_strategy") or "")
        research_task = bool(dynamic_plan.get("requires_web_research"))
        workspace_context = dynamic_plan.get("workspace_context", "read")
        allow_workspace_context = workspace_context in {"read", "write"}
        active_phase = next(
            (
                phase for phase in task.get("phases", [])
                if phase["owner_id"] == payload.employee_id and phase["status"] not in {"completed", "skipped"}
            ),
            None,
        )
        task_kind = (active_phase or {}).get("task_kind") or default_task_kind(role["team"], payload.employee_id)
        standards = json.loads(DELIVERABLE_STANDARDS_PATH.read_text(encoding="utf-8"))
        artifact_kind = dynamic_plan.get("artifact_kind")
        if artifact_kind in standards:
            artifact_standard = standards[artifact_kind]
        else:
            artifact_kind, artifact_standard = deliverable_spec(effective_request, task_kind)
        boundary = department_policy(payload.employee_id)
        skill_context = employee_skill_context(
            payload.employee_id,
            effective_request,
            selected_skill_ids=payload.skill_ids or None,
            task_kind=task_kind,
        )
        model = task_model_assignment(db, task_id, payload.employee_id)["model"]
        changed_files: list[str] = []
        command_results: list[dict] = []
        web_search_used = False
        verified_web_sources = 0
        verified_web_domains: set[str] = set()
        required_skill_ids = {skill["id"] for skill in skill_context["required_skills"]}
        applied_skill_ids: set[str] = set()
        skill_paths = {skill["id"]: ROOT / skill["path"] for skill in skill_context["required_skills"]}
        bounded_tools = WorkspaceAgentTools(workspace, task["contract"]["allowed_paths"])
        tools = [
            {"type": "function", "name": "read_required_skill", "description": "Read one task-relevant skill immediately before using it. Do not read unrelated skills.", "parameters": {"type": "object", "properties": {"skill_id": {"type": "string", "enum": sorted(required_skill_ids)}}, "required": ["skill_id"], "additionalProperties": False}},
            {"type": "function", "name": "run_verification", "description": "Run a TaskContract-approved verification command in the assigned project workspace.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}},
            {"type": "function", "name": "web_search", "description": "Discover candidate public sources. Search snippets are not evidence; read selected originals with read_web_source.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 300}}, "required": ["query"], "additionalProperties": False}},
            {"type": "function", "name": "read_web_source", "description": "Read and verify the original public page for a selected source URL.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}}, "required": ["url"], "additionalProperties": False}},
            {"type": "function", "name": "record_research_claim", "description": "Record one material research claim tied to a previously verified original source. Include source text span, confidence 0-1, and contradictions or an empty list.", "parameters": {"type": "object", "properties": {"claim": {"type": "string", "minLength": 10, "maxLength": 1600}, "source_url": {"type": "string", "minLength": 8, "maxLength": 2000}, "publisher": {"type": "string", "minLength": 2, "maxLength": 300}, "published_at": {"type": "string", "maxLength": 40}, "retrieved_span": {"type": "string", "minLength": 20, "maxLength": 4000}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "contradictions": {"type": "array", "items": {"type": "string", "maxLength": 500}, "maxItems": 10}}, "required": ["claim", "source_url", "publisher", "retrieved_span", "confidence", "contradictions"], "additionalProperties": False}},
        ]
        tools.extend(tool_definitions())
        allowed_commands = set(task["contract"]["allowed_commands"])
        enabled_bounded_tools = {
            "list_files", "read_file", "search_files", "find_symbols", "find_references",
            "language_diagnostics", "discover_tests", "replace_exact_text", "apply_unified_patch",
            "create_file", "git_status", "git_diff", "fetch_public_source", "fetch_public_pdf", "render_public_page",
        }
        if "git commit *" in allowed_commands:
            enabled_bounded_tools.add("git_commit")
        if "git push *" in allowed_commands:
            enabled_bounded_tools.add("git_push")
        if payload.employee_id == "NAVI":
            enabled_bounded_tools -= {"replace_exact_text", "apply_unified_patch", "create_file", "git_commit", "git_push"}
        tools = [
            tool for tool in tools
            if tool["name"] in enabled_bounded_tools or tool["name"] not in {"git_commit", "git_push", "replace_exact_text", "apply_unified_patch", "create_file"}
        ]
        if not allow_workspace_context:
            tools = [
                tool for tool in tools
                if tool["name"] not in {
                    "list_files", "read_file", "run_verification", "search_files", "find_symbols", "find_references",
                    "language_diagnostics", "discover_tests",
                    "replace_exact_text", "apply_unified_patch", "create_file",
                    "git_status", "git_diff", "git_commit", "git_push",
                }
            ]
        permission_scope = permission_tool_scope(skill_context["permissions"].get("permissions", []))
        tools = [
            tool for tool in tools
            if tool["name"] not in GATED_TOOL_NAMES or tool["name"] in permission_scope
        ]
        mcp_tool_map: dict[str, tuple[sqlite3.Row, str, str | None]] = {}
        for connection in ([] if payload.employee_id == "NAVI" else db.execute("SELECT * FROM mcp_connections WHERE status IN ('configured', 'connected')")):
            try:
                remote_tools, session_id = mcp_initialize(connection)
                for remote_tool in remote_tools:
                    remote_name = remote_tool.get("name", "")
                    safe_name = "".join(character if character.isalnum() else "_" for character in remote_name)[:48]
                    local_name = f"mcp_{connection['id'].replace('-', '_')}_{safe_name}"
                    if not safe_name:
                        continue
                    tools.append({"type": "function", "name": local_name, "description": f"{connection['name']} MCP: {remote_tool.get('description', remote_name)}", "parameters": remote_tool.get("inputSchema", {"type": "object", "properties": {}})})
                    mcp_tool_map[local_name] = (connection, remote_name, session_id)
            except HTTPException:
                continue
        instructions = (
            f"You are {payload.employee_id}, {role['title']} in an AI automation office. "
            f"Your role: {role['responsibility']}. Work only on task request. "
            f"Department owns: {boundary['owns']}. Must hand off: {boundary['must_handoff']}. "
            "Do not redefine the task, perform another department's work, or make the final cross-department decision. Produce one bounded department contribution. "
            + ("This is a research task: follow the evidence strategy, discover candidates with web_search, read selected original pages with read_web_source or fetch_public_pdf, then record each material conclusion with record_research_claim. Search snippets alone are not evidence. " if research_task else "")
            + ("Workspace files are intentionally unavailable for this task. Do not infer user needs from unrelated local files. " if not allow_workspace_context else "")
            + "Only task-relevant skills are available. Read a skill only when it directly supports the bounded assignment. "
            + ("You may inspect evidence and write reports, but must not modify project code or use external write tools. " if payload.employee_id == "NAVI" else "")
            + "Use find_symbols/find_references and search_files before file reads. Use language_diagnostics and discover_tests to choose a TaskContract-approved verification command. Use replace_exact_text or apply_unified_patch for existing files; create_file only for new files. Inspect git_diff and run verification before claiming implementation success. "
            "Never access credentials, parent folders, or delete unrelated files. Use web_search for discovery and fetch_public_source or read_web_source for original evidence; cite returned URLs and never invent sources. "
            "For leads: inspect work, give precise review or debugging changes. For workers: implement smallest safe change. "
            "Finish with Korean summary: changed files, verification run, remaining risk."
        )
        skill_manifest = {
            "permissions": skill_context["permissions"],
            "required_skills": [{"id": skill["id"], "path": skill["path"]} for skill in skill_context["required_skills"]],
        }
        initial_steering = consume_steering_messages(db, task_id)
        session_context = load_session_context(db, task_id, payload.employee_id)
        context = json.dumps({
            "task": task["title"],
            "request": effective_request,
            "contract": task["contract"],
            "files": workspace_files(workspace) if allow_workspace_context else [],
            "role": role,
            "department_boundary": boundary,
            "execution_plan_summary": dynamic_plan.get("summary"),
            "evidence_strategy": evidence_strategy,
            "active_retry_strategy": task.get("retry_attempts", [{}])[0] if task.get("retry_attempts") else None,
            "deliverable_standard": artifact_standard,
            "skill_context": skill_manifest,
            "user_steering": initial_steering,
            "persistent_session": session_context,
        }, ensure_ascii=False)
        total_input_tokens = 0
        total_output_tokens = 0

        def add_usage(current_response: object) -> None:
            nonlocal total_input_tokens, total_output_tokens
            current_usage = getattr(current_response, "usage", None)
            if current_usage:
                total_input_tokens += int(getattr(current_usage, "input_tokens", 0) or 0)
                total_output_tokens += int(getattr(current_usage, "output_tokens", 0) or 0)

        def compact_tool_result(result: object) -> object:
            serialized = json.dumps(result, ensure_ascii=False)
            if len(serialized) <= 12000:
                return result
            return {"truncated": True, "content": serialized[:12000], "original_characters": len(serialized)}

        try:
            client = model_client()
            response = cancellable_model_response(client, task_id, payload.job_id, model=model, instructions=instructions, input=context, tools=tools)
            add_usage(response)
            tool_history: list[dict] = []
            for _ in range(12):
                calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
                if not calls:
                    steering = consume_steering_messages(db, task_id)
                    if steering:
                        db.commit()
                        response = cancellable_model_response(
                            client,
                            task_id,
                            payload.job_id,
                            model=model,
                            input=json.dumps({
                                "original_context": json.loads(context),
                                "prior_output": response.output_text,
                                "new_user_steering": steering,
                                "tool_history": tool_history,
                            }, ensure_ascii=False),
                            tools=tools,
                            instructions=instructions + " Apply the new user steering without discarding valid completed work.",
                        )
                        add_usage(response)
                        continue
                    break
                outputs = []
                for call in calls:
                    require_runnable(db, task_id)
                    args = json.loads(call.arguments)
                    permission_target = str(
                        args.get("path")
                        or args.get("command")
                        or args.get("url")
                        or args.get("branch")
                        or call.name
                    )[:1000]
                    require_tool_permission(
                        db,
                        task_id,
                        payload.employee_id,
                        call.name,
                        permission_target,
                    )
                    tool_started = time.monotonic()
                    input_summary = str(args.get("path") or args.get("command") or args.get("query") or args.get("skill_id") or call.name)[:500]
                    emit_job_event(db, task_id, "tool.started", f"{call.name}: {input_summary}", job_id=payload.job_id, agent_id=payload.employee_id, payload={"tool": call.name})
                    db.commit()
                    tool_status = "pass"
                    try:
                        if call.name == "read_required_skill":
                            skill_id = args["skill_id"]
                            if skill_id not in skill_paths:
                                raise HTTPException(403, "Skill is not assigned to this employee")
                            applied_skill_ids.add(skill_id)
                            result = {"skill_id": skill_id, "instructions": skill_paths[skill_id].read_text(encoding="utf-8", errors="replace")[:12000]}
                        elif call.name == "run_verification":
                            command = args["command"]
                            allowed, command_reason = validate_command(command, task["contract"]["allowed_commands"])
                            if not allowed:
                                raise HTTPException(403, command_reason)
                            run = subprocess.run(shlex.split(command, posix=False), cwd=workspace, capture_output=True, text=True, timeout=300, shell=False)
                            result = {"exit_code": run.returncode, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}
                            command_results.append({"command": command, "exit_code": run.returncode})
                            run_count = db.execute("SELECT COUNT(*) FROM runs WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
                            run_id = f"RUN-{task_id.split('-')[-1]}-AGENT-{run_count:03d}"
                            run_status = "pass" if run.returncode == 0 else "fail"
                            stdout_bytes = run.stdout.encode("utf-8", errors="replace")
                            stderr_bytes = run.stderr.encode("utf-8", errors="replace")
                            db.execute(
                                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    run_id, task_id, payload.workspace_id, command, run.returncode,
                                    hashlib.sha256(stdout_bytes).hexdigest(),
                                    hashlib.sha256(stderr_bytes).hexdigest(),
                                    run_status, utc_now(),
                                ),
                            )
                            evidence_hash = hashlib.sha256(stdout_bytes + stderr_bytes).hexdigest()
                            if run_status == "pass":
                                db.execute(
                                    "UPDATE evidence SET stale = 1 WHERE task_id = ? AND type = 'command' AND status = 'fail'",
                                    (task_id,),
                                )
                            db.execute(
                                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, 'command', ?, ?, 0, ?)",
                                (f"EVD-{task_id.split('-')[-1]}-RUN-{run_count:03d}", task_id, run_id, run_status, evidence_hash, utc_now()),
                            )
                        elif call.name == "web_search":
                            results = web_search(args["query"])
                            web_search_used = True
                            now = utc_now()
                            for source in results:
                                db.execute("INSERT INTO research_sources (task_id, employee_id, query, title, url, snippet, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, payload.employee_id, args["query"], source["title"], source["url"], source["snippet"], now))
                            result = {"query": args["query"], "sources": results}
                        elif call.name == "read_web_source":
                            source = read_public_web_source(args["url"])
                            verified_web_sources += 1
                            verified_web_domains.add(urllib.parse.urlparse(source["url"]).hostname or "")
                            now = utc_now()
                            db.execute(
                                "INSERT INTO research_sources (task_id, employee_id, query, title, url, snippet, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (task_id, payload.employee_id, "verified-original", source["title"], source["url"], source["text"][:1000], now),
                            )
                            source_hash = hashlib.sha256((source["url"] + source["text"]).encode("utf-8")).hexdigest()
                            db.execute(
                                "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (f"EVD-{task_id.split('-')[-1]}-WEB-{source_hash[:12]}", task_id, None, "verified_web_source", "pass", source_hash, 0, now),
                            )
                            result = source
                        elif call.name == "record_research_claim":
                            source_url = str(args["source_url"])
                            verified = db.execute(
                                "SELECT 1 FROM research_sources WHERE task_id = ? AND url = ? "
                                "AND query = 'verified-original' LIMIT 1",
                                (task_id, source_url),
                            ).fetchone()
                            if not verified:
                                raise HTTPException(409, "Research claim requires a previously verified original source URL")
                            contradictions = args.get("contradictions", [])
                            now = utc_now()
                            db.execute(
                                "INSERT INTO research_claims "
                                "(task_id, employee_id, claim, source_url, publisher, published_at, retrieved_span, confidence, contradictions, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    task_id, payload.employee_id, args["claim"], source_url,
                                    args["publisher"], args.get("published_at") or None,
                                    args["retrieved_span"], float(args["confidence"]),
                                    json.dumps(contradictions, ensure_ascii=False), now,
                                ),
                            )
                            claim_hash = hashlib.sha256(
                                (args["claim"] + source_url + args["retrieved_span"]).encode("utf-8")
                            ).hexdigest()
                            db.execute(
                                "INSERT OR REPLACE INTO evidence VALUES (?, ?, NULL, 'research_claim', 'pass', ?, 0, ?)",
                                (f"EVD-{task_id.split('-')[-1]}-CLAIM-{claim_hash[:12]}", task_id, claim_hash, now),
                            )
                            result = {"recorded": True, "claim_sha256": claim_hash, "source_url": source_url}
                        elif call.name in {
                            "list_files", "read_file", "search_files", "find_symbols", "find_references",
                            "language_diagnostics", "discover_tests",
                            "replace_exact_text", "apply_unified_patch", "create_file",
                            "git_status", "git_diff", "git_commit", "git_push", "fetch_public_source", "fetch_public_pdf", "render_public_page",
                        }:
                            if call.name not in enabled_bounded_tools:
                                raise HTTPException(403, f"{call.name} is not granted by TaskContract")
                            try:
                                result = bounded_tools.dispatch(call.name, args)
                            except AgentToolError as error:
                                raise HTTPException(error.status_code, str(error)) from error
                            if call.name in {"replace_exact_text", "create_file"}:
                                relative = result["path"]
                                if relative not in changed_files:
                                    changed_files.append(relative)
                            elif call.name == "apply_unified_patch":
                                for relative in result["paths"]:
                                    if relative not in changed_files:
                                        changed_files.append(relative)
                            elif call.name == "git_commit":
                                command_results.append({"command": "git commit", "exit_code": 0, "commit": result["commit"]})
                            elif call.name == "git_push":
                                command_results.append({"command": "git push", "exit_code": 0, "branch": result["branch"]})
                            elif call.name in {"fetch_public_source", "fetch_public_pdf", "render_public_page"}:
                                verified_web_sources += 1
                                verified_web_domains.add(urllib.parse.urlparse(result["url"]).hostname or "")
                                now = utc_now()
                                db.execute(
                                    "INSERT INTO research_sources "
                                    "(task_id, employee_id, query, title, url, snippet, created_at) "
                                    "VALUES (?, ?, 'verified-original', ?, ?, ?, ?)",
                                    (task_id, payload.employee_id, result["title"], result["url"], result["text"][:1000], now),
                                )
                                source_hash = hashlib.sha256((result["url"] + result["text"]).encode("utf-8")).hexdigest()
                                db.execute(
                                    "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (f"EVD-{task_id.split('-')[-1]}-WEB-{source_hash[:12]}", task_id, None, "verified_web_source", "pass", source_hash, 0, now),
                                )
                        elif call.name in mcp_tool_map:
                            connection, remote_name, session_id = mcp_tool_map[call.name]
                            result, next_session = mcp_http_call(connection, "tools/call", {"name": remote_name, "arguments": args}, session_id)
                            mcp_tool_map[call.name] = (connection, remote_name, next_session)
                        else:
                            result = {"error": "Unknown tool"}
                    except HTTPException as error:
                        if error.status_code in {409, 410, 428}:
                            raise
                        result = {"error": str(error)}
                        tool_status = "fail"
                    except Exception as error:
                        result = {"error": str(error)}
                        tool_status = "fail"
                    duration_ms = int((time.monotonic() - tool_started) * 1000)
                    output_summary = json.dumps(result, ensure_ascii=False)
                    if call.name == "read_required_skill":
                        output_summary = f"{args.get('skill_id', '')} 스킬 지침 읽음"
                    elif call.name == "list_files":
                        output_summary = f"{len(result.get('files', [])) if isinstance(result, dict) else 0}개 파일 확인"
                    elif call.name == "read_file":
                        output_summary = f"{args.get('path', '')} · {len(result.get('lines', [])) if isinstance(result, dict) else 0}줄 읽음"
                    elif call.name == "run_verification" and isinstance(result, dict):
                        output_summary = f"{args.get('command', '')} · exit {result.get('exit_code', 'unknown')}"
                    elif call.name == "web_search" and isinstance(result, dict):
                        output_summary = f"{args.get('query', '')} · {len(result.get('sources', []))}개 후보"
                    elif call.name == "read_web_source" and isinstance(result, dict):
                        output_summary = f"원문 확인 · {result.get('title', '')} · {result.get('url', '')}"
                    elif call.name == "search_files" and isinstance(result, dict):
                        output_summary = f"{args.get('query', '')} · {len(result.get('results', []))}개 코드 위치"
                    elif call.name == "replace_exact_text" and isinstance(result, dict):
                        output_summary = f"{result.get('path', '')} · {result.get('replacements', 0)}개 정밀 수정"
                    elif call.name == "apply_unified_patch" and isinstance(result, dict):
                        output_summary = f"patch applied · {', '.join(result.get('paths', []))}"
                    elif call.name == "create_file" and isinstance(result, dict):
                        output_summary = f"created {result.get('path', '')} · {result.get('bytes', 0)} bytes"
                    elif call.name == "find_symbols" and isinstance(result, dict):
                        output_summary = f"{args.get('symbol', '')} · {len(result.get('results', []))}개 정의"
                    elif call.name in {"git_status", "git_diff"}:
                        output_summary = f"{call.name} 완료"
                    elif call.name == "git_commit" and isinstance(result, dict):
                        output_summary = f"git commit · {result.get('commit', '')[:12]}"
                    elif call.name == "git_push" and isinstance(result, dict):
                        output_summary = f"git push · {result.get('remote', '')}/{result.get('branch', '')}"
                    elif call.name in {"fetch_public_source", "fetch_public_pdf", "render_public_page"} and isinstance(result, dict):
                        output_summary = f"원문 확인 · {result.get('title', '')} · {result.get('url', '')}"
                    db.execute(
                        "INSERT INTO tool_calls (task_id, job_id, agent_id, tool_name, input_summary, output_summary, status, duration_ms, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (task_id, payload.job_id or f"DIRECT-{task_id}", payload.employee_id, call.name, input_summary, output_summary[:1000], tool_status, duration_ms, utc_now()),
                    )
                    emit_job_event(
                        db,
                        task_id,
                        "tool.completed" if tool_status == "pass" else "tool.failed",
                        f"{call.name}: {output_summary[:500]}",
                        job_id=payload.job_id,
                        agent_id=payload.employee_id,
                        payload={"tool": call.name, "status": tool_status, "duration_ms": duration_ms},
                    )
                    db.commit()
                    outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False)})
                    tool_history.append({"tool": call.name, "arguments": args, "result": compact_tool_result(result)})
                    tool_history = tool_history[-8:]
                # Release any SQLite write lock before the next potentially long
                # provider call so the Job lease thread can keep heartbeating.
                db.commit()
                # OpenRouter Responses API rejects previous_response_id. Continue statelessly
                # with the complete explicit tool transcript instead.
                steering = consume_steering_messages(db, task_id)
                db.commit()
                response = cancellable_model_response(
                    client,
                    task_id,
                    payload.job_id,
                    model=model,
                    input=json.dumps({
                        "original_context": json.loads(context),
                        "tool_history": tool_history,
                        "new_user_steering": steering,
                    }, ensure_ascii=False),
                    tools=tools,
                    instructions=instructions,
                )
                add_usage(response)
            else:
                # Stop an endless tool-call loop without treating partial work as
                # completion. Ask for one final evidence-grounded result, no tools.
                response = cancellable_model_response(
                    client,
                    task_id,
                    payload.job_id,
                    model=model,
                    input=json.dumps({"original_context": json.loads(context), "tool_history": tool_history}, ensure_ascii=False),
                    instructions=instructions + " Tool phase is closed. Return the final Korean result using only recorded tool results.",
                )
                add_usage(response)
            if research_task and (
                not web_search_used
                or verified_web_sources < 2
                or len({domain for domain in verified_web_domains if domain}) < 2
                or not db.execute("SELECT 1 FROM research_claims WHERE task_id = ? LIMIT 1", (task_id,)).fetchone()
            ):
                raise HTTPException(422, "Research completion requires search, two verified originals from independent domains, and claim-to-source evidence")
            summary = response.output_text
        except HTTPException:
            raise
        except Exception as error:
            error_text = str(error)[:4000]
            record_usage(db, task_id, model, error=error_text)
            db.commit()  # Preserve provider failure even though this request raises and outer context rolls back.
            raise HTTPException(502, "Model agent run failed; see local model_usage log") from error

        input_tokens = total_input_tokens
        output_tokens = total_output_tokens
        now = utc_now()
        if not summary.strip():
            raise HTTPException(502, "Model returned no final output")
        department_deliverable = persist_deliverable(
            db,
            workspace,
            task_id,
            payload.employee_id,
            artifact_kind,
            summary,
            filename=f"departments/{payload.employee_id}.md",
            status="department_draft",
        )
        if department_deliverable["path"] not in changed_files:
            changed_files.append(department_deliverable["path"])
        state = "team_review" if role["tier"] == "lead" else "verifying"
        artifact = hashlib.sha256(json.dumps({"files": changed_files, "commands": command_results, "summary": summary}, ensure_ascii=False).encode()).hexdigest()
        evidence_id = f"EVD-{task_id.split('-')[-1]}-AGENT-{payload.employee_id}"
        db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (evidence_id, task_id, None, "agent_run", "pass" if changed_files or command_results else "info", artifact, 0, now))
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, payload.employee_id, "run", summary, now))
        record_usage(db, task_id, model, input_tokens, output_tokens)
        session = record_session_turn(
            db,
            task_id,
            payload.employee_id,
            input_summary=effective_request,
            output_summary=summary,
            tool_history=tool_history,
            response_id=str(getattr(response, "id", "") or "") or None,
            state="active",
        )
        # Job worker owns task state. A worker result must not turn an active
        # multi-worker execution into "verifying" before all workers/review finish.
        if not payload.managed_by_job:
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
            db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "agent_run", task["state"], state, payload.employee_id, summary[:800], json.dumps([payload.employee_id]), now))
        checkpoint(db, task_id, f"agent:{payload.employee_id}")
        return {"employee_id": payload.employee_id, "tier": role["tier"], "model": model, "summary": summary, "changed_files": changed_files, "commands": command_results, "evidence_id": evidence_id, "deliverable": department_deliverable, "session": session, "state": task["state"] if payload.managed_by_job else state}


# Route handlers live in the four apps/api/*_routes.py modules. Imported here, at
# the *bottom* of the file, so every helper above is already defined by the time
# each of those modules runs its own module-scope ``from apps.api import main``.
#
# Each handler is imported by name as well as by router, because before the split
# they were attributes of this module and callers do reach them that way rather
# than over HTTP - ``test_runtime_hardening`` invokes ``main.restore_checkpoint``
# directly. Re-importing the names keeps ``main``'s namespace exactly what it was;
# dropping them would turn those calls into ``AttributeError``.
#
# ``POST /api/tasks/{task_id}/agent/run`` (``run_agent``, above) is deliberately
# *not* in a route module: the test suite replaces it with
# ``patch.object(main, "run_agent", ...)``, and a definition living elsewhere would
# still import cleanly while silently ignoring the patch - green tests spending
# real model calls. ``model_client``, ``model_key``, ``select_roster_with_model``
# and ``require_skill_ready`` stay here for the same reason.
from apps.api.admin_routes import (  # noqa: E402,F401
    router as admin_router,
    agent_capabilities,
    employee_permissions,
    employees,
    get_mcp_connections,
    get_model_settings,
    get_openrouter_models,
    health,
    list_lessons,
    runtime_version,
    save_mcp_connection,
    save_model_settings,
    team_capabilities,
    test_mcp_connection,
    usage_summary,
    verify_skills,
)
from apps.api.project_routes import (  # noqa: E402,F401
    router as project_router,
    create_project,
    create_workspace,
    get_workspace,
    pick_project_folder,
    projects,
)
from apps.api.job_routes import (  # noqa: E402,F401
    router as job_router,
    control_job,
    queue_execution,
    queue_lead_review,
    queue_meeting,
    queue_plan,
    retry_job,
)
from apps.api.task_routes import (  # noqa: E402,F401
    router as task_router,
    agent_brief,
    cancel_task,
    command,
    create_contract,
    create_meeting,
    create_reflection,
    create_review,
    create_task,
    decide_approval,
    decide_permission,
    direct_dispatch,
    event_stream,
    get_task,
    office,
    pause_task,
    plan,
    restore_checkpoint,
    resume_task,
    retry,
    run_command,
    run_meeting,
    select_leads,
    select_workers,
    steer_task,
    tasks,
)

app.include_router(admin_router)
app.include_router(project_router)
app.include_router(job_router)
app.include_router(task_router)
