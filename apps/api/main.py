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
from html import unescape
from xml.etree import ElementTree
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import keyring
import httpx
from openai import OpenAI
from apps.api.policy import validate_path, validate_command

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "ai-office.sqlite3"
REGISTRY_PATH = ROOT / "registry" / "employees.json"
SKILL_BINDINGS_PATH = ROOT / "registry" / "employee-skill-bindings.json"
SKILLS_LOCK_PATH = ROOT / "registry" / "skills.lock.json"
SETTINGS_PATH = ROOT / ".ai-office" / "settings.json"
KEYRING_SERVICE = "AI-Automation-Office"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"
NAVI_MODEL = "z-ai/glm-5.2"
MODELS_CACHE_PATH = ROOT / "data" / "openrouter-models.json"
BUILD_ID = "ai-office-jobs-v3"
SCHEMA_VERSION = 2
JOB_STATES = {"queued", "running", "pause_requested", "paused", "cancel_requested", "cancelled", "succeeded", "failed", "interrupted"}
TASK_STATES = {
    "draft", "contracting", "planning", "meeting", "assigned", "running",
    "team_review", "cross_review", "verifying", "reflecting", "awaiting_approval",
    "completed", "blocked", "failed", "cancelled", "paused", "budget_exceeded", "escalated",
    "awaiting_lead_selection", "meeting_ready", "meeting_running", "awaiting_worker_selection", "executing", "lead_review_running",
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
    "executing": "실행 중", "lead_review_running": "팀장 리뷰",
}
STATUS_TO_ZONE = {
    "draft": "desk", "contracting": "meeting", "planning": "meeting", "meeting": "meeting",
    "assigned": "desk", "running": "desk", "team_review": "review", "cross_review": "review",
    "verifying": "qa", "reflecting": "review", "awaiting_approval": "ceo", "completed": "desk",
    "blocked": "ceo", "failed": "qa", "cancelled": "desk", "paused": "ceo", "budget_exceeded": "ceo", "escalated": "ceo",
    "awaiting_lead_selection": "ceo", "meeting_ready": "ceo", "meeting_running": "meeting", "awaiting_worker_selection": "ceo", "executing": "desk", "lead_review_running": "qa",
}


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


class ContractInput(BaseModel):
    allowed_paths: list[str] = ["."]
    allowed_commands: list[str] = []
    acceptance_criteria: list[str] = []
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
    strategy: Literal["worktree", "copy"] = "copy"


class RunInput(BaseModel):
    workspace_id: str
    command: str = Field(min_length=1, max_length=400)


class AgentRunInput(BaseModel):
    workspace_id: str
    employee_id: str = Field(min_length=1, max_length=40)
    instruction: str = Field(default="", max_length=4000)
    managed_by_job: bool = False
    job_id: str | None = Field(default=None, max_length=80)


class RetryInput(BaseModel):
    failure_class: Literal["contract_interpretation", "permission", "skill", "file_conflict", "build", "test", "runtime", "external_dependency", "quality", "budget", "model_response"]
    strategy: str = Field(min_length=1, max_length=500)


class ModelSettingsInput(BaseModel):
    provider: Literal["openrouter"] = "openrouter"
    lead_model: str = Field(default="gpt-5", min_length=1, max_length=100)
    worker_model: str = Field(default="gpt-5-mini", min_length=1, max_length=100)
    api_key: str | None = Field(default=None, min_length=20)


class McpConnectionInput(BaseModel):
    provider: Literal["github", "google-drive", "notion", "custom"]
    name: str = Field(min_length=1, max_length=80)
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    server_url: str = Field(min_length=8, max_length=1000)
    auth_token: str | None = Field(default=None, max_length=4000)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checkpoint(db: sqlite3.Connection, task_id: str, label: str) -> None:
    task = db.execute("SELECT id, state, updated_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task:
        db.execute("INSERT INTO task_checkpoints (task_id, label, snapshot, created_at) VALUES (?, ?, ?, ?)", (task_id, label, json.dumps(dict(task)), utc_now()))


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


def model_settings() -> dict:
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        legacy = settings.get("model", "gpt-5")
        return {"provider": settings.get("provider", "openrouter"), "lead_model": settings.get("lead_model", legacy), "worker_model": settings.get("worker_model", "openai/gpt-5-mini")}
    return {"provider": "openrouter", "lead_model": "openai/gpt-5", "worker_model": "openai/gpt-5-mini"}


def model_key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY") or keyring.get_password(KEYRING_SERVICE, "openrouter_api_key") or os.getenv("OPENAI_API_KEY")


def model_client() -> OpenAI:
    # Model generation can legitimately take several minutes. Limit only the
    # connection phase; the worker lease heartbeat proves the Job is still alive.
    return OpenAI(api_key=model_key(), base_url=OPENROUTER_BASE_URL, timeout=httpx.Timeout(None, connect=15.0), max_retries=0, default_headers={"HTTP-Referer": "http://localhost:5175", "X-Title": "AI Automation Office"})


def public_model_settings() -> dict:
    settings = model_settings()
    return {"provider": settings["provider"], "lead_model": settings["lead_model"], "worker_model": settings["worker_model"], "configured": bool(model_key())}


def openrouter_models() -> list[dict]:
    try:
        request = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))["data"]
        models = [{"id": item["id"], "name": item.get("name", item["id"]), "context_length": item.get("context_length", 0)} for item in data if item.get("id")]
        MODELS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE_PATH.write_text(json.dumps(models, ensure_ascii=False), encoding="utf-8")
        return models
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        if MODELS_CACHE_PATH.exists():
            return json.loads(MODELS_CACHE_PATH.read_text(encoding="utf-8"))
        return [{"id": "openai/gpt-5", "name": "GPT-5", "context_length": 0}, {"id": "openai/gpt-5-mini", "name": "GPT-5 mini", "context_length": 0}]


def employee_security(employee_id: str) -> dict:
    employee = registry()[employee_id]
    base = ROOT / Path(employee["profile_path"]).parent
    permissions = __import__("yaml").safe_load((base / "PERMISSIONS.yaml").read_text(encoding="utf-8"))
    bindings = json.loads(SKILL_BINDINGS_PATH.read_text(encoding="utf-8"))[employee_id]
    lock = json.loads(SKILLS_LOCK_PATH.read_text(encoding="utf-8"))["installed"]
    required = bindings["required"]
    checks = []
    for skill_id in required:
        path = base / "skills" / skill_id / "SKILL.md"
        locked = f"{employee_id}:{skill_id}" in lock
        checks.append({"skill_id": skill_id, "path": str(path.relative_to(ROOT)), "exists": path.exists(), "locked": locked, "valid": path.exists() and locked})
    return {"employee_id": employee_id, "permissions": permissions, "skills": checks, "ready": all(check["valid"] for check in checks)}


def require_skill_ready(employee_ids: list[str]) -> None:
    unavailable = [employee_id for employee_id in employee_ids if not employee_security(employee_id)["ready"]]
    if unavailable:
        raise HTTPException(409, f"Required skills are not ready for: {', '.join(unavailable)}")


def employee_skill_context(employee_id: str, per_skill_limit: int = 3000) -> dict:
    security = employee_security(employee_id)
    if not security["ready"]:
        raise HTTPException(409, f"Required skills are not ready for {employee_id}")
    content: list[dict] = []
    for skill in security["skills"]:
        path = ROOT / skill["path"]
        text = path.read_text(encoding="utf-8", errors="replace")[:per_skill_limit]
        content.append({"id": skill["skill_id"], "path": skill["path"], "instructions": text})
    return {"permissions": security["permissions"], "required_skills": content}


def safe_project_root(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(422, "Project root must be an existing directory")
    return candidate


LEAD_IDS = {"NAVI", "FRAME", "BUILD", "LINK", "SHIP", "GUARD", "GROW", "LENS"}


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


def safe_workspace_file(workspace: Path, relative_path: str, allowed_paths: list[str]) -> Path:
    candidate = (workspace / relative_path).resolve()
    if not candidate.is_relative_to(workspace):
        raise HTTPException(403, "Agent file path escapes workspace")
    normalized = str(candidate.relative_to(workspace)).replace("\\", "/")
    permitted = any(item == "." or normalized == item.strip("/") or normalized.startswith(item.strip("/") + "/") for item in allowed_paths)
    if not permitted:
        raise HTTPException(403, "Agent file path is outside TaskContract allowed_paths")
    return candidate


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


def mcp_headers(connection: sqlite3.Row | dict, session_id: str | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    credential_key = connection["credential_key"]
    token = keyring.get_password(KEYRING_SERVICE, credential_key) if credential_key else None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def mcp_http_call(connection: sqlite3.Row | dict, method: str, params: dict, session_id: str | None = None) -> tuple[dict, str | None]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    request = urllib.request.Request(connection["server_url"], data=body, headers=mcp_headers(connection, session_id), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            if raw.startswith("data:"):
                raw = raw.split("data:", 1)[1].strip()
            data = json.loads(raw)
            if "error" in data:
                raise HTTPException(502, f"MCP {method} failed: {data['error']}")
            return data.get("result", {}), response.headers.get("Mcp-Session-Id") or session_id
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise HTTPException(502, f"MCP {method} connection failed: {error}") from error


def mcp_initialize(connection: sqlite3.Row | dict) -> tuple[list[dict], str | None]:
    result, session_id = mcp_http_call(connection, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "AI Automation Office", "version": "1.0"}})
    tools_result, session_id = mcp_http_call(connection, "tools/list", {}, session_id)
    return tools_result.get("tools", []), session_id


def web_search(query: str, limit: int = 5) -> list[dict]:
    """Public web search fallback. Results are evidence, never ground truth."""
    normalized = " ".join(query.split())[:300]
    if not normalized:
        raise HTTPException(422, "Web search query is required")
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(normalized)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AI-Automation-Office/1.0", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as error:
        raise HTTPException(502, f"Web search failed: {error}") from error
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise HTTPException(502, f"Web search returned invalid RSS: {error}") from error
    results = []
    for item in root.findall("./channel/item")[:limit]:
        title = (item.findtext("title") or "").strip()
        source_url = (item.findtext("link") or "").strip()
        snippet = (item.findtext("description") or "").strip()
        if source_url.startswith(("http://", "https://")) and title:
            results.append({"title": title[:300], "url": source_url[:2000], "snippet": snippet[:1000]})
    if not results:
        raise HTTPException(502, "Web search returned no usable sources")
    return results


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
        CREATE TABLE IF NOT EXISTS task_controls (
            task_id TEXT PRIMARY KEY, state_before_pause TEXT, pause_requested INTEGER NOT NULL DEFAULT 0,
            cancel_requested INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, label TEXT NOT NULL,
            snapshot TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, reviewer_id TEXT NOT NULL, verdict TEXT NOT NULL,
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
        ensure_column(db, "tasks", "route", "TEXT NOT NULL DEFAULT 'navi'")
        ensure_column(db, "tasks", "lead_id", "TEXT")
        ensure_column(db, "tasks", "parent_task_id", "TEXT")
        # Old plan rows were placeholders, not real meetings. Preserve audit, hide from runtime.
        db.execute("UPDATE meetings SET status = 'superseded' WHERE status = 'concluded' AND type = 'team_lead' AND id NOT IN (SELECT DISTINCT m.id FROM meetings m JOIN agent_messages a ON a.task_id = m.task_id WHERE a.kind = 'meeting')")


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
    meetings = [dict(row) | {key: json.loads(row[key]) for key in ("participants", "agenda", "decisions")} for row in db.execute("SELECT * FROM meetings WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    items = [dict(row) | {"acceptance_criteria": json.loads(row["acceptance_criteria"])} for row in db.execute("SELECT * FROM action_items WHERE task_id = ? ORDER BY sequence", (task_id,))]
    reviews = [dict(row) for row in db.execute("SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    approvals = [dict(row) for row in db.execute("SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    reflections = [dict(row) | {key: json.loads(row[key]) for key in ("root_causes", "improvements")} for row in db.execute("SELECT * FROM reflections WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    lessons = [dict(row) for row in db.execute("SELECT * FROM lessons WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    agent_messages = [dict(row) for row in db.execute("SELECT * FROM agent_messages WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    model_usage = [dict(row) for row in db.execute("SELECT * FROM model_usage WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    research_sources = [dict(row) for row in db.execute("SELECT * FROM research_sources WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    checkpoints = [dict(row) | {"snapshot": json.loads(row["snapshot"])} for row in db.execute("SELECT * FROM task_checkpoints WHERE task_id = ? ORDER BY id DESC", (task_id,))]
    jobs = [dict(row) | {"payload": json.loads(row["payload"])} for row in db.execute("SELECT * FROM jobs WHERE task_id = ? ORDER BY created_at DESC", (task_id,))]
    job_events = [dict(row) | {"payload": json.loads(row["payload"])} for row in db.execute("SELECT * FROM job_events WHERE task_id = ? ORDER BY id DESC LIMIT 120", (task_id,))]
    budget_spent = sum(item["input_tokens"] + item["output_tokens"] for item in model_usage)
    return dict(task) | {"assigned_employees": assigned, "events": events, "evidence": evidence, "state_label": STATE_LABELS[task["state"]], "contract": (dict(contract) | {key: json.loads(contract[key]) for key in ("allowed_paths", "allowed_commands", "acceptance_criteria")}) if contract else None, "meetings": meetings, "action_items": items, "reviews": reviews, "approvals": approvals, "reflections": reflections, "lessons": lessons, "agent_messages": agent_messages, "model_usage": model_usage, "research_sources": research_sources, "checkpoints": checkpoints, "jobs": jobs, "job_events": job_events, "budget_spent": budget_spent}


def emit_job_event(db: sqlite3.Connection, task_id: str, event_type: str, summary: str, *, job_id: str | None = None, agent_id: str | None = None, payload: dict | None = None) -> None:
    db.execute("INSERT INTO job_events (task_id, job_id, agent_id, type, summary, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, job_id, agent_id, event_type, summary[:500], json.dumps(payload or {}, ensure_ascii=False), utc_now()))


def enqueue_job(db: sqlite3.Connection, task_id: str, kind: str, payload: dict) -> dict:
    count = db.execute("SELECT COUNT(*) FROM jobs WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
    now = utc_now(); job_id = f"JOB-{task_id.split('-')[-1]}-{count:03d}"
    job = {"id": job_id, "task_id": task_id, "kind": kind, "payload": payload, "state": "queued", "step": 0, "created_at": now, "updated_at": now}
    db.execute("INSERT INTO jobs (id, task_id, kind, payload, state, step, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (job_id, task_id, kind, json.dumps(payload, ensure_ascii=False), "queued", 0, now, now))
    emit_job_event(db, task_id, "job.queued", f"{kind} 작업 대기", job_id=job_id, payload={"kind": kind})
    return job


def planned_roster(request: str) -> tuple[list[str], list[tuple[str, str]]]:
    text = request.lower()
    research_terms = ("\uc2dc\uc7a5\uc870\uc0ac", "\uc2dc\uc7a5 \uc870\uc0ac", "\uc2dc\uc7a5\ubd84\uc11d", "\uc2dc\uc7a5 \ubd84\uc11d", "\ub9ac\uc11c\uce58", "\uc870\uc0ac", "\ubd84\uc11d", "\uc0ac\uc5c5\uc544\uc774\ud15c", "\uc0ac\uc5c5 \uc544\uc774\ud15c", "market research", "market analysis", "research")
    if any(word in text for word in research_terms):
        return ["NAVI", "FRAME", "JOURNEY", "PULSE", "GROW", "VOICE"], [
            ("JOURNEY", "Research market, customers, competitors; cite sources"),
            ("PULSE", "Analyze research data and summarize insights"),
            ("GROW", "Identify channels, opportunities, and testable hypotheses"),
            ("VOICE", "Draft target positioning and message"),
            ("FRAME", "Synthesize findings and prioritize next actions"),
        ]
    if any(word in text for word in ("시장조사", "시장 조사", "시장분석", "시장 분석", "리서치", "조사해", "조사해줘", "market research", "market analysis", "research")):
        return ["NAVI", "FRAME", "JOURNEY", "PULSE", "GROW", "VOICE"], [
            ("JOURNEY", "시장·고객·경쟁사 조사 범위와 근거 수집"),
            ("PULSE", "조사 자료 정량 분석과 핵심 인사이트 정리"),
            ("GROW", "채널·성장 기회와 실행 가설 도출"),
            ("VOICE", "타깃 메시지와 포지셔닝 초안 작성"),
            ("FRAME", "조사 결과 통합, 우선순위와 다음 action 확정"),
        ]
    if any(word in text for word in ("문서", "documentation", "readme")):
        return ["NAVI", "DOCS", "EVAL"], [("DOCS", "문서 산출물 작성"), ("EVAL", "acceptance 기준 검토")]
    if any(word in text for word in ("api", "backend", "백엔드", "database", "서버")):
        return ["NAVI", "FRAME", "BUILD", "BACK", "TRACE", "GUARD"], [("FRAME", "요구사항과 acceptance 확정"), ("BACK", "백엔드 변경 구현"), ("BUILD", "통합 검토"), ("TRACE", "테스트 실행"), ("GUARD", "권한·보안 검토")]
    if any(word in text for word in ("ui", "ux", "frontend", "프론트", "화면")):
        return ["NAVI", "FRAME", "BUILD", "FRONT", "TRACE"], [("FRAME", "제품 범위와 acceptance 확정"), ("FRONT", "UI 구현"), ("BUILD", "통합 검토"), ("TRACE", "테스트 실행")]
    return ["NAVI", "FRAME", "BUILD", "FRONT", "BACK", "TRACE", "GUARD"], [("FRAME", "업무 분해와 acceptance 확정"), ("FRONT", "프런트엔드 작업"), ("BACK", "백엔드 작업"), ("BUILD", "통합 검토"), ("TRACE", "QA 검증"), ("GUARD", "보안·권한 검토")]


def select_roster_with_model(request: str) -> tuple[list[str], list[tuple[str, str]], str, dict | None]:
    fallback_roster, fallback_items = planned_roster(request)
    fallback_leads = [employee_id for employee_id in fallback_roster if employee_id in LEAD_IDS and employee_id != "NAVI"][:3] or ["FRAME"]
    fallback_items = [(leader, f"{leader} team scope, delegation, and acceptance plan") for leader in fallback_leads]
    if not model_key():
        return fallback_leads, fallback_items, "Model unavailable; used deterministic fallback.", None
    available = [{"id": employee_id, "title": employee["title"], "team": employee["team"], "responsibility": agent_role(employee_id)["responsibility"]} for employee_id, employee in registry().items() if employee_id in LEAD_IDS and employee_id != "NAVI"]
    instructions = (
        "Select the minimum capable agent set for this task. Do not select security, QA, or engineering roles unless task scope requires them. "
        "Return JSON only: {\"agents\":[\"ID\"],\"action_items\":[{\"owner\":\"ID\",\"description\":\"...\"}],\"reason\":\"...\"}. "
        "Choose 1 to 3 department leads. Each action owner must be selected."
    )
    response = model_client().responses.create(model=NAVI_MODEL, instructions=instructions, input=json.dumps({"request": request, "available_department_leads": available}, ensure_ascii=False))
    match = re.search(r"\{.*\}", response.output_text, re.S)
    if not match:
        raise ValueError("Planner returned no JSON object")
    payload = json.loads(match.group())
    agents = list(dict.fromkeys(agent for agent in payload.get("agents", []) if agent in LEAD_IDS and agent != "NAVI"))[:3]
    raw_items = payload.get("action_items", [])
    items = [(item["owner"], item["description"].strip()[:500]) for item in raw_items if isinstance(item, dict) and item.get("owner") in agents and isinstance(item.get("description"), str) and item["description"].strip()]
    if not agents or not items:
        raise ValueError("Planner returned no valid assignments")
    usage = getattr(response, "usage", None)
    return agents, items, str(payload.get("reason", "Model selected minimum capable team."))[:800], {"model": NAVI_MODEL, "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0, "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0}


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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "build_id": BUILD_ID, "schema_version": SCHEMA_VERSION, "registry_employees": len(registry()), "model": public_model_settings()}


@app.get("/api/runtime/version")
def runtime_version() -> dict:
    with database() as db:
        running = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','pause_requested','cancel_requested')").fetchone()[0]
        worker = db.execute("SELECT build_id, heartbeat_at FROM worker_heartbeats ORDER BY heartbeat_at DESC LIMIT 1").fetchone()
    fresh = worker and (datetime.now(timezone.utc) - datetime.fromisoformat(worker["heartbeat_at"])).total_seconds() < 8
    return {"api_build_id": BUILD_ID, "worker_build_id": worker["build_id"] if fresh else None, "schema_version": SCHEMA_VERSION, "running_jobs": running}


@app.get("/api/tasks/{task_id}/events/stream")
def event_stream(task_id: str, after: int = 0) -> StreamingResponse:
    def stream():
        cursor = after
        while True:
            with database() as db:
                rows = [dict(row) for row in db.execute("SELECT * FROM job_events WHERE task_id = ? AND id > ? ORDER BY id", (task_id, cursor))]
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: job\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            yield ": keepalive\n\n"
            time.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/usage/summary")
def usage_summary() -> dict:
    with database() as db:
        row = db.execute("SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), COALESCE(SUM(cost_usd), 0) FROM model_usage").fetchone()
        return {"input_tokens": row[0], "output_tokens": row[1], "cost_usd": row[2]}


@app.get("/api/settings/model")
def get_model_settings() -> dict:
    return public_model_settings()


@app.get("/api/settings/models")
def get_openrouter_models() -> list[dict]:
    return openrouter_models()


@app.post("/api/settings/model")
def save_model_settings(payload: ModelSettingsInput) -> dict:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps({"provider": payload.provider, "lead_model": payload.lead_model, "worker_model": payload.worker_model}, indent=2), encoding="utf-8")
    if payload.api_key:
        try:
            keyring.set_password(KEYRING_SERVICE, "openrouter_api_key", payload.api_key)
        except keyring.errors.KeyringError as error:
            raise HTTPException(500, f"Could not save API key in Windows Credential Manager: {error}") from error
    return public_model_settings()


@app.get("/api/settings/mcp")
def get_mcp_connections() -> list[dict]:
    with database() as db:
        return [dict(row) | {"configured": bool(row["credential_key"])} for row in db.execute("SELECT * FROM mcp_connections ORDER BY created_at DESC")]


@app.post("/api/settings/mcp", status_code=201)
def save_mcp_connection(payload: McpConnectionInput) -> dict:
    if not payload.server_url.startswith("https://") and not payload.server_url.startswith("http://localhost") and not payload.server_url.startswith("http://127.0.0.1"):
        raise HTTPException(422, "MCP server URL must use HTTPS or local HTTP")
    with database() as db:
        count = db.execute("SELECT COUNT(*) FROM mcp_connections").fetchone()[0] + 1
        connection_id = f"MCP-{count:03d}"
        credential_key = f"mcp:{connection_id}"
        if payload.auth_token:
            try:
                keyring.set_password(KEYRING_SERVICE, credential_key, payload.auth_token)
            except keyring.errors.KeyringError as error:
                raise HTTPException(500, f"Could not save MCP credential in Windows Credential Manager: {error}") from error
        now = utc_now()
        db.execute("INSERT INTO mcp_connections VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (connection_id, payload.provider, payload.name, payload.transport, payload.server_url, credential_key if payload.auth_token else None, "configured", now))
        return {"id": connection_id, "provider": payload.provider, "name": payload.name, "transport": payload.transport, "server_url": payload.server_url, "configured": bool(payload.auth_token), "status": "configured", "created_at": now}


@app.post("/api/settings/mcp/{connection_id}/test")
def test_mcp_connection(connection_id: str) -> dict:
    with database() as db:
        connection = db.execute("SELECT * FROM mcp_connections WHERE id = ?", (connection_id,)).fetchone()
        if not connection:
            raise HTTPException(404, "MCP connection not found")
        tools, _ = mcp_initialize(connection)
        db.execute("UPDATE mcp_connections SET status = 'connected' WHERE id = ?", (connection_id,))
        return {"id": connection_id, "status": "connected", "tool_count": len(tools), "tools": [tool.get("name") for tool in tools]}


@app.post("/api/tasks/{task_id}/agent/brief")
def agent_brief(task_id: str) -> dict:
    key = model_key()
    if not key:
        raise HTTPException(409, "OpenRouter API key is not configured")
    with database() as db:
        task = task_payload(db, task_id)
        settings = model_settings()
        instructions = "You are NAVI, the chief orchestrator of a local AI automation office. Return a compact Korean execution brief with: task contract risks, departments, next action, verification evidence needed. Do not claim tools were run."
        input_text = json.dumps({"task": task["title"], "request": task["request"], "state": task["state"], "assigned_employees": task["assigned_employees"], "contract": task["contract"]}, ensure_ascii=False)
        try:
            response = model_client().responses.create(model=settings["lead_model"], instructions=instructions, input=input_text)
        except Exception as error:
            now = utc_now()
            db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, settings["lead_model"], 0, 0, 0, str(error), now))
            raise HTTPException(502, "Model call failed; see local model_usage log") from error
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        text = response.output_text
        now = utc_now()
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, "NAVI", "brief", text, now))
        db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, settings["lead_model"], input_tokens, output_tokens, 0, None, now))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "agent_brief", task["state"], task["state"], "NAVI", "CEO briefing generated", json.dumps(["NAVI"]), now))
        return {"employee_id": "NAVI", "content": text, "model": settings["lead_model"], "input_tokens": input_tokens, "output_tokens": output_tokens}


@app.get("/api/registry/employees")
def employees() -> list[dict]:
    return [{"id": key} | value | {"skill_ready": employee_security(key)["ready"], "agent_role": agent_role(key)} for key, value in registry().items()]


@app.get("/api/registry/employees/{employee_id}/security")
def employee_permissions(employee_id: str) -> dict:
    if employee_id not in registry():
        raise HTTPException(404, "Employee not found")
    result = employee_security(employee_id)
    with database() as db:
        db.execute("INSERT INTO skill_verifications (employee_id, ready, result, created_at) VALUES (?, ?, ?, ?)", (employee_id, result["ready"], json.dumps(result), utc_now()))
        return result


@app.get("/api/agents/{employee_id}/capabilities")
def agent_capabilities(employee_id: str) -> dict:
    if employee_id not in registry():
        raise HTTPException(404, "Employee not found")
    employee = registry()[employee_id]
    security = employee_security(employee_id)
    return {"employee": {"id": employee_id} | employee | {"agent_role": agent_role(employee_id)}, "permissions": security["permissions"], "skills": security["skills"], "optional_skills": json.loads(SKILL_BINDINGS_PATH.read_text(encoding="utf-8"))[employee_id]["optional"]}


@app.get("/api/teams/{team_id}/capabilities")
def team_capabilities(team_id: str) -> dict:
    members = [{"id": key} | value | {"agent_role": agent_role(key), "security": employee_security(key)} for key, value in registry().items() if value["team"] == team_id]
    if not members:
        raise HTTPException(404, "Team not found")
    return {"team_id": team_id, "members": members}


@app.post("/api/skills/verify")
def verify_skills() -> list[dict]:
    results = [employee_security(employee_id) for employee_id in registry()]
    with database() as db:
        now = utc_now()
        db.executemany("INSERT INTO skill_verifications (employee_id, ready, result, created_at) VALUES (?, ?, ?, ?)", [(result["employee_id"], result["ready"], json.dumps(result), now) for result in results])
    return results


@app.get("/api/projects")
def projects() -> list[dict]:
    with database() as db:
        return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at DESC")]


@app.post("/api/projects/pick")
def pick_project_folder() -> dict:
    """Open native Windows folder picker; browser never receives unrestricted filesystem access."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="AI Office 프로젝트 폴더 선택")
        root.destroy()
    except Exception as error:
        raise HTTPException(500, f"Native folder picker failed: {error}") from error
    if not selected:
        return {"path": ""}
    return {"path": str(safe_project_root(selected))}


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectInput) -> dict:
    root = safe_project_root(payload.root_path); now = utc_now()
    with database() as db:
        sequence = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] + 1
        project = {"id": f"PROJECT-{sequence:03d}", "name": payload.name or root.name, "root_path": str(root), "git_available": int((root / ".git").exists()), "created_at": now}
        db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?)", tuple(project.values()))
        return project


@app.get("/api/tasks")
def tasks() -> list[dict]:
    with database() as db:
        ids = [r[0] for r in db.execute("SELECT id FROM tasks ORDER BY updated_at DESC")]
        return [task_payload(db, task_id) for task_id in ids]


@app.post("/api/tasks", status_code=201)
def create_task(payload: CreateTask) -> dict:
    known = registry()
    unknown = sorted(set(payload.selected_employees) - set(known))
    if unknown:
        raise HTTPException(422, f"Unknown employees: {', '.join(unknown)}")
    if payload.route == "direct_lead" and (payload.lead_id not in LEAD_IDS or payload.lead_id == "NAVI"):
        raise HTTPException(422, "Direct task requires a department lead")
    with database() as db:
        sequence = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] + 1
        task_id = f"TASK-{sequence:03d}"
        now = utc_now()
        db.execute("INSERT INTO tasks (id, title, request, state, created_at, updated_at, route, lead_id, parent_task_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_id, payload.title, payload.request, "draft", now, now, payload.route, payload.lead_id, payload.parent_task_id))
        initial = [payload.lead_id] if payload.route == "direct_lead" and payload.lead_id else ["NAVI"]
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee) for employee in initial])
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (task_id, "create", None, "draft", "NAVI", "업무 요청 접수", json.dumps(initial), now))
        emit_job_event(db, task_id, "task.created", "업무 요청 접수", agent_id=payload.lead_id or "NAVI")
        return task_payload(db, task_id)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    with database() as db:
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/jobs/plan", status_code=202)
def queue_plan(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "Create TaskContract before planning")
        if any(job["state"] in {"queued", "running", "pause_requested"} and job["kind"] == "plan" for job in task["jobs"]):
            raise HTTPException(409, "Planning job is already active")
        job = enqueue_job(db, task_id, "direct_plan" if task.get("route") == "direct_lead" else "plan", {"lead_id": task.get("lead_id")})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("planning", utc_now(), task_id))
        return job | {"task": task_payload(db, task_id)}


@app.post("/api/tasks/{task_id}/jobs/meeting", status_code=202)
def queue_meeting(task_id: str, payload: JobInput) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if any(job["kind"] == "meeting" and job["state"] in {"queued", "running", "pause_requested", "cancel_requested"} for job in task["jobs"]):
            raise HTTPException(409, "A meeting Job is already active")
        meeting = next((item for item in task["meetings"] if item["id"] == payload.meeting_id and item["status"] == "active"), None)
        if not meeting:
            raise HTTPException(409, "Select leads and create an active meeting first")
        job = enqueue_job(db, task_id, "meeting", {"meeting_id": meeting["id"], "participants": meeting["participants"]})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("meeting_running", utc_now(), task_id))
        return job | {"task": task_payload(db, task_id)}


@app.post("/api/tasks/{task_id}/jobs/execute", status_code=202)
def queue_execution(task_id: str, payload: JobInput) -> dict:
    if not payload.workspace_id or not payload.employee_ids:
        raise HTTPException(422, "workspace_id and employee_ids are required")
    with database() as db:
        task = task_payload(db, task_id)
        if any(job["kind"] == "execute" and job["state"] in {"queued", "running", "pause_requested", "cancel_requested"} for job in task["jobs"]):
            raise HTTPException(409, "An execution Job is already active")
        if task["state"] not in {"awaiting_worker_selection", "assigned", "executing"}:
            raise HTTPException(409, "Task is not ready for worker execution")
        unknown = set(payload.employee_ids) - set(task["assigned_employees"])
        if unknown:
            raise HTTPException(403, f"Workers are not assigned: {', '.join(sorted(unknown))}")
        job = enqueue_job(db, task_id, "execute", {"workspace_id": payload.workspace_id, "employee_ids": payload.employee_ids, "instruction": payload.instruction})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("executing", utc_now(), task_id))
        return job | {"task": task_payload(db, task_id)}


@app.post("/api/tasks/{task_id}/jobs/review", status_code=202)
def queue_lead_review(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if any(job["kind"] == "lead_review" and job["state"] in {"queued", "running", "pause_requested", "cancel_requested"} for job in task["jobs"]):
            raise HTTPException(409, "A lead review Job is already active")
        if not any(item["status"] == "pass" for item in task["evidence"]):
            raise HTTPException(409, "Lead review requires passing Evidence")
        lead = task.get("lead_id") or next((employee for employee in task["assigned_employees"] if employee in LEAD_IDS and employee != "NAVI"), None)
        if not lead:
            raise HTTPException(409, "No responsible team lead")
        job = enqueue_job(db, task_id, "lead_review", {"lead_id": lead})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("lead_review_running", utc_now(), task_id))
        return job | {"task": task_payload(db, task_id)}


@app.post("/api/jobs/{job_id}/control")
def control_job(job_id: str, payload: JobControlInput) -> dict:
    with database() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        target = {"pause": "pause_requested", "cancel": "cancel_requested", "resume": "queued"}[payload.action]
        if payload.action == "resume" and job["state"] not in {"paused", "interrupted"}:
            raise HTTPException(409, "Only paused or interrupted jobs can resume")
        db.execute("UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?", (target, utc_now(), job_id))
        if payload.action == "pause":
            task = db.execute("SELECT state FROM tasks WHERE id = ?", (job["task_id"],)).fetchone()
            if task:
                db.execute("INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) VALUES (?, ?, 1, 0, ?) ON CONFLICT(task_id) DO UPDATE SET state_before_pause=excluded.state_before_pause, pause_requested=1, cancel_requested=0, updated_at=excluded.updated_at", (job["task_id"], task["state"], utc_now()))
        elif payload.action == "resume":
            resume_state = {"plan": "planning", "direct_plan": "planning", "meeting": "meeting_running", "execute": "executing", "lead_review": "lead_review_running"}.get(job["kind"], "planning")
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (resume_state, utc_now(), job["task_id"]))
            db.execute("UPDATE task_controls SET pause_requested = 0, updated_at = ? WHERE task_id = ?", (utc_now(), job["task_id"]))
        emit_job_event(db, job["task_id"], f"job.{payload.action}_requested", f"{payload.action} 요청", job_id=job_id)
        return dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str) -> dict:
    with database() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        if job["state"] not in {"failed", "interrupted"}:
            raise HTTPException(409, "Only failed or interrupted jobs can retry")
        active = db.execute(
            "SELECT 1 FROM jobs WHERE task_id = ? AND kind = ? AND id != ? "
            "AND state IN ('queued','running','pause_requested','cancel_requested') LIMIT 1",
            (job["task_id"], job["kind"], job_id),
        ).fetchone()
        if active:
            raise HTTPException(409, "Another Job of this kind is already active")
        resume_state = {
            "plan": "planning",
            "direct_plan": "planning",
            "meeting": "meeting_running",
            "execute": "executing",
            "lead_review": "lead_review_running",
        }.get(job["kind"], "planning")
        now = utc_now()
        db.execute(
            "UPDATE jobs SET state = 'queued', lease_owner = NULL, lease_until = NULL, "
            "heartbeat_at = NULL, error = NULL, updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        db.execute("DELETE FROM job_leases WHERE job_id = ?", (job_id,))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (resume_state, now, job["task_id"]))
        db.execute(
            "INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) "
            "VALUES (?, ?, 0, 0, ?) ON CONFLICT(task_id) DO UPDATE SET "
            "pause_requested=0, cancel_requested=0, updated_at=excluded.updated_at",
            (job["task_id"], resume_state, now),
        )
        emit_job_event(db, job["task_id"], "job.retry_queued", "실패한 단계부터 Job을 다시 시작합니다.", job_id=job_id)
        return dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


@app.post("/api/tasks/{task_id}/contract")
def create_contract(task_id: str, payload: ContractInput) -> dict:
    with database() as db:
        task_payload(db, task_id)
        now = utc_now()
        db.execute("INSERT INTO task_contracts VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET allowed_paths=excluded.allowed_paths, allowed_commands=excluded.allowed_commands, acceptance_criteria=excluded.acceptance_criteria, retry_limit=excluded.retry_limit, token_limit=excluded.token_limit, updated_at=excluded.updated_at", (task_id, json.dumps(payload.allowed_paths), json.dumps(payload.allowed_commands), json.dumps(payload.acceptance_criteria), payload.retry_limit, payload.token_limit, now, now))
        db.execute("UPDATE tasks SET state = 'contracting', updated_at = ? WHERE id = ?", (now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "contract", None, "contracting", "NAVI", "TaskContract 생성", json.dumps(["NAVI"]), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/plan")
def plan(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "Create TaskContract before planning")
        try:
            roster, items, selection_reason, selection_usage = select_roster_with_model(task["request"])
        except Exception as error:
            fallback_roster, _ = planned_roster(task["request"])
            roster = [employee_id for employee_id in fallback_roster if employee_id in LEAD_IDS and employee_id != "NAVI"][:3] or ["FRAME"]
            items = [(leader, f"{leader} team scope, delegation, and acceptance plan") for leader in roster]
            selection_reason, selection_usage = f"Model selection failed; used deterministic fallback: {error}", None
            if model_key():
                db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, model_settings()["lead_model"], 0, 0, 0, str(error), utc_now()))
        require_skill_ready(roster)
        now = utc_now()
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee) for employee in roster])
        # Planning is not a meeting. Remove legacy placeholder rows that falsely showed "meeting complete".
        db.execute("DELETE FROM meetings WHERE task_id = ? AND type = 'team_lead'", (task_id,))
        db.execute("DELETE FROM action_items WHERE task_id = ?", (task_id,))
        for index, (owner, description) in enumerate(items, 1):
            db.execute("INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"ACT-{task_id.split('-')[-1]}-{index:02d}", task_id, None, owner, description, index, json.dumps(task["contract"]["acceptance_criteria"]), "planned"))
        db.execute("UPDATE tasks SET state = 'planning', updated_at = ? WHERE id = ?", (now, task_id))
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, "NAVI", "dispatch", selection_reason, now))
        if selection_usage:
            db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, selection_usage["model"], selection_usage["input_tokens"], selection_usage["output_tokens"], 0, None, now))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "plan", task["state"], "planning", "NAVI", selection_reason, json.dumps(roster), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if task["state"] in {"completed", "cancelled"}:
            raise HTTPException(409, "Completed or cancelled task cannot be paused")
        now = utc_now()
        db.execute("INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) VALUES (?, ?, 1, 0, ?) ON CONFLICT(task_id) DO UPDATE SET state_before_pause=excluded.state_before_pause, pause_requested=1, updated_at=excluded.updated_at", (task_id, task["state"], now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("paused", now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "pause", task["state"], "paused", "CEO", "Pause requested. Current model call may finish; next tool or agent call stops.", "[]", now))
        checkpoint(db, task_id, "paused")
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if task["state"] != "paused":
            raise HTTPException(409, "Only a paused task can resume")
        control = db.execute("SELECT state_before_pause FROM task_controls WHERE task_id = ?", (task_id,)).fetchone()
        resume_state = control["state_before_pause"] if control and control["state_before_pause"] in TASK_STATES else "assigned"
        now = utc_now()
        db.execute("UPDATE task_controls SET pause_requested = 0, updated_at = ? WHERE task_id = ?", (now, task_id))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (resume_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "resume", "paused", resume_state, "CEO", "Resume requested", "[]", now))
        checkpoint(db, task_id, "resumed")
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if task["state"] in {"completed", "cancelled"}:
            raise HTTPException(409, "Completed or cancelled task cannot be cancelled")
        now = utc_now()
        db.execute("INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) VALUES (?, ?, 0, 1, ?) ON CONFLICT(task_id) DO UPDATE SET pause_requested=0, cancel_requested=1, updated_at=excluded.updated_at", (task_id, task["state"], now))
        db.execute("UPDATE jobs SET state = CASE WHEN state = 'queued' THEN 'cancelled' ELSE 'cancel_requested' END, updated_at = ? WHERE task_id = ? AND state IN ('queued','running','pause_requested')", (now, task_id))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("cancelled", now, task_id))
        db.execute("UPDATE meetings SET status = 'cancelled' WHERE task_id = ? AND status = 'active'", (task_id,))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "cancel", task["state"], "cancelled", "CEO", "Cancel requested. Future agent calls blocked; completed evidence retained.", "[]", now))
        checkpoint(db, task_id, "cancelled")
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/direct-dispatch")
def direct_dispatch(task_id: str, payload: DirectDispatchInput) -> dict:
    """CEO direct order: one selected lead, no NAVI planning or lead meeting."""
    if payload.lead_id not in LEAD_IDS or payload.lead_id == "NAVI":
        raise HTTPException(422, "Direct dispatch target must be a department lead")
    with database() as db:
        require_runnable(db, task_id)
        task = task_payload(db, task_id)
        require_skill_ready([payload.lead_id])
        now = utc_now()
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.execute("INSERT INTO task_assignments VALUES (?, ?)", (task_id, payload.lead_id))
        db.execute("DELETE FROM action_items WHERE task_id = ?", (task_id,))
        db.execute("INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"ACT-{task_id.split('-')[-1]}-01", task_id, None, payload.lead_id, "Direct CEO order: complete small scoped task without a lead meeting", 1, json.dumps(task["contract"]["acceptance_criteria"]), "assigned"))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("assigned", now, task_id))
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, payload.lead_id, "direct_order", task["request"], now))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "direct_dispatch", task["state"], "assigned", "CEO", "Direct order; NAVI planning and lead meeting skipped", json.dumps([payload.lead_id]), now))
        checkpoint(db, task_id, f"direct:{payload.lead_id}")
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/select-leads")
def select_leads(task_id: str, payload: SelectionInput) -> dict:
    with database() as db:
        require_runnable(db, task_id)
        task = task_payload(db, task_id)
        if task["state"] != "awaiting_lead_selection":
            raise HTTPException(409, "Task is not awaiting lead selection")
        candidates = set(task["assigned_employees"])
        selected = list(dict.fromkeys(payload.employee_ids))
        if not set(selected).issubset(candidates) or any(employee_id not in LEAD_IDS or employee_id == "NAVI" for employee_id in selected):
            raise HTTPException(422, "Select only NAVI-proposed department leads")
        now = utc_now(); meeting_id = f"MEET-{task_id.split('-')[-1]}-LEADS"; participants = ["NAVI", *selected]
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee_id) for employee_id in selected])
        db.execute("INSERT OR REPLACE INTO meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (meeting_id, task_id, "lead_dispatch", "NAVI-led: selected department leads decide scope, risks, worker delegation", json.dumps(participants), json.dumps(["scope", "risk", "worker roles", "acceptance"]), json.dumps([]), "active", now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("meeting_running", now, task_id))
        meeting_job = enqueue_job(db, task_id, "meeting", {"meeting_id": meeting_id, "participants": participants})
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "lead_selection", task["state"], "meeting_running", "USER", "Selected leads approved; autonomous meeting started", json.dumps(participants), now))
        emit_job_event(db, task_id, "meeting.queued", "대표가 팀장을 선택해 회의 Job을 자동 시작했습니다.", job_id=meeting_job["id"], agent_id="NAVI", payload={"participants": participants})
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/select-workers")
def select_workers(task_id: str, payload: SelectionInput) -> dict:
    with database() as db:
        require_runnable(db, task_id)
        task = task_payload(db, task_id)
        selected = list(dict.fromkeys(payload.employee_ids))
        direct_lead_id = task.get("lead_id") if task.get("route") == "direct_lead" else None
        proposed = {item["owner"] for item in task["action_items"]}
        # Compatibility for pre-worker proposals that still named a lead instead of its team members.
        proposed_leads = proposed & LEAD_IDS
        if proposed_leads:
            lead_teams = {registry()[lead]["team"] for lead in proposed_leads}
            proposed |= {employee_id for employee_id, employee in registry().items() if employee["team"] in lead_teams and employee_id not in LEAD_IDS}
            if direct_lead_id in proposed_leads:
                proposed.add(direct_lead_id)
        if not proposed:
            raise HTTPException(409, "Wait for the responsible lead's worker proposal")
        if not set(selected).issubset(proposed):
            raise HTTPException(422, "Select only workers proposed by the responsible team lead")
        if any(employee_id not in registry() or (employee_id in LEAD_IDS and employee_id != direct_lead_id) for employee_id in selected):
            raise HTTPException(422, "Select worker agents only")
        lead_ids = [direct_lead_id] if direct_lead_id else [employee_id for meeting in task["meetings"] if meeting["type"] == "lead_dispatch" for employee_id in meeting["participants"] if employee_id != "NAVI"]
        if not lead_ids:
            raise HTTPException(409, "Select department leads first")
        now = utc_now(); assignments = list(dict.fromkeys(lead_ids + selected))
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee_id) for employee_id in assignments])
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("assigned", now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "worker_selection", task["state"], "assigned", "USER", "User selected worker agents", json.dumps(selected), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/meetings")
def create_meeting(task_id: str, payload: MeetingInput) -> dict:
    raise HTTPException(410, "Manual meeting creation is disabled; select leads and let the worker start the meeting Job")
    unknown = sorted(set(payload.participant_ids) - set(registry()))
    if unknown:
        raise HTTPException(422, f"Unknown employees: {', '.join(unknown)}")
    with database() as db:
        task = task_payload(db, task_id); now = utc_now()
        count = db.execute("SELECT COUNT(*) FROM meetings WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        meeting_id = f"MEET-{task_id.split('-')[-1]}-{count:02d}"
        db.execute("INSERT INTO meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (meeting_id, task_id, "department", payload.objective, json.dumps(payload.participant_ids), json.dumps(payload.agenda), json.dumps([]), "active", now))
        db.execute("UPDATE tasks SET state = 'meeting', updated_at = ? WHERE id = ?", (now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "meeting", task["state"], "meeting", "NAVI", payload.objective, json.dumps(payload.participant_ids), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/meetings/{meeting_id}/run")
def run_meeting(task_id: str, meeting_id: str) -> dict:
    """Record one real model response per attendee, then conclude the meeting."""
    raise HTTPException(410, "Browser meeting execution is disabled; the local worker owns meeting Jobs")
    if not model_key():
        raise HTTPException(409, "OpenRouter API key is not configured")
    with database() as db:
        require_runnable(db, task_id)
        task = task_payload(db, task_id)
        meeting = db.execute("SELECT * FROM meetings WHERE id = ? AND task_id = ?", (meeting_id, task_id)).fetchone()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        if meeting["status"] != "active":
            raise HTTPException(409, "Meeting is not active")
        participants = json.loads(meeting["participants"])
        agenda = json.loads(meeting["agenda"])
        settings = model_settings()
        transcript: list[str] = []
        try:
            for employee_id in participants:
                require_runnable(db, task_id)
                role = agent_role(employee_id)
                meeting_model = NAVI_MODEL if employee_id == "NAVI" else settings[role["model_role"]]
                response = model_client().responses.create(
                    model=meeting_model,
                    instructions=(
                        f"You are {employee_id}, {role['title']}. Participate in a work meeting. "
                        "Give one concise, evidence-focused Korean contribution. Do not claim unverified research."
                    ),
                    input=json.dumps({"task": task["request"], "objective": meeting["objective"], "agenda": agenda, "prior_contributions": transcript}, ensure_ascii=False),
                )
                content = response.output_text.strip()
                usage = getattr(response, "usage", None)
                db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, employee_id, "meeting", content, utc_now()))
                db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, meeting_model, getattr(usage, "input_tokens", 0) if usage else 0, getattr(usage, "output_tokens", 0) if usage else 0, 0, None, utc_now()))
                transcript.append(f"{employee_id}: {content}")
        except HTTPException:
            raise
        except Exception as error:
            db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, settings["lead_model"], 0, 0, 0, str(error), utc_now()))
            raise HTTPException(502, "Meeting model run failed; see local model_usage log") from error
        now = utc_now()
        db.execute("UPDATE meetings SET status = ?, decisions = ? WHERE id = ?", ("concluded", json.dumps(["Transcript recorded. Review evidence before execution."], ensure_ascii=False), meeting_id))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("planning", now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "meeting_run", task["state"], "planning", "NAVI", "Meeting transcript recorded", json.dumps(participants), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/reviews")
def create_review(task_id: str, payload: ReviewInput) -> dict:
    raise HTTPException(409, "Manual reviews are disabled; queue a lead review Job after Evidence")
    if payload.reviewer_id not in registry():
        raise HTTPException(404, "Reviewer not found")
    with database() as db:
        require_runnable(db, task_id)
        task = task_payload(db, task_id)
        if payload.reviewer_id not in task["assigned_employees"]:
            raise HTTPException(403, "Reviewer is not assigned to this task")
        if payload.reviewer_id not in LEAD_IDS and registry()[payload.reviewer_id]["runtime"] != "REVIEWER":
            raise HTTPException(403, "Reviewer must be a team lead or reviewer agent")
        direct_order = next((event for event in task["events"] if event["action"] == "direct_dispatch"), None)
        if direct_order:
            required_lead = direct_order["employee_ids"][0]
            if payload.reviewer_id != required_lead:
                raise HTTPException(403, f"Direct task requires review by assigned lead: {required_lead}")
        count = db.execute("SELECT COUNT(*) FROM reviews WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        review_id = f"REV-{task_id.split('-')[-1]}-{count:02d}"
        now = utc_now()
        next_state = "awaiting_approval" if payload.verdict == "pass" else ("blocked" if payload.verdict == "blocked" else "planning")
        db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)", (review_id, task_id, payload.reviewer_id, payload.verdict, payload.findings, now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "review", task["state"], next_state, payload.reviewer_id, payload.findings or payload.verdict, json.dumps([payload.reviewer_id]), now))
        checkpoint(db, task_id, f"review:{payload.reviewer_id}")
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/approval")
def decide_approval(task_id: str, payload: ApprovalInput) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if task["state"] != "awaiting_approval":
            raise HTTPException(409, "Task is not awaiting approval")
        if not any(item["type"] == "lead_review" and item["status"] == "pass" for item in task["evidence"]):
            raise HTTPException(409, "Approval requires a passing lead review Job")
        count = db.execute("SELECT COUNT(*) FROM approvals WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        approval_id = f"APR-{task_id.split('-')[-1]}-{count:02d}"
        now = utc_now()
        next_state = {"approve": "completed", "rework": "planning", "reject": "cancelled"}[payload.decision]
        db.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?)", (approval_id, task_id, payload.decision, payload.reason, "USER", now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "approval_decision", task["state"], next_state, "USER", payload.reason or payload.decision, json.dumps([]), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/reflection")
def create_reflection(task_id: str, payload: ReflectionInput) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        count = db.execute("SELECT COUNT(*) FROM reflections WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        reflection_id = f"RFL-{task_id.split('-')[-1]}-{count:02d}"
        now = utc_now()
        db.execute("INSERT INTO reflections VALUES (?, ?, ?, ?, ?, ?)", (reflection_id, task_id, payload.summary, json.dumps(payload.root_causes), json.dumps(payload.improvements), now))
        lesson_id = None
        if payload.lesson.strip():
            lesson_id = f"LES-{task_id.split('-')[-1]}-{count:02d}"
            db.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?)", (lesson_id, task_id, payload.lesson.strip(), reflection_id, now))
        next_state = task["state"] if task["state"] in {"completed", "cancelled"} else "reflecting"
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "reflection", task["state"], next_state, "NAVI", payload.summary, json.dumps(["NAVI"]), now))
        result = task_payload(db, task_id)
        return result | {"reflection_id": reflection_id, "lesson_id": lesson_id}


@app.get("/api/lessons")
def list_lessons() -> list[dict]:
    with database() as db:
        return [dict(row) for row in db.execute("SELECT * FROM lessons ORDER BY created_at DESC LIMIT 100")]


@app.get("/api/tasks/{task_id}/workspace")
def get_workspace(task_id: str) -> dict:
    with database() as db:
        task_payload(db, task_id)
        workspace = db.execute("SELECT * FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        return dict(workspace)


@app.post("/api/tasks/{task_id}/workspace")
def create_workspace(task_id: str, payload: WorkspaceInput) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        project = db.execute("SELECT * FROM projects WHERE id = ?", (payload.project_id,)).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        source = safe_project_root(project["root_path"])
        workspace_id = f"WS-{task_id.split('-')[-1]}"
        destination = (ROOT / "data" / "workspaces" / workspace_id).resolve()
        allowed, reason = validate_path((ROOT / "data" / "workspaces").resolve(), destination)
        if not allowed:
            raise HTTPException(403, reason)
        existing = db.execute("SELECT * FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if existing:
            return dict(existing)
        if destination.exists():
            raise HTTPException(409, "Workspace path exists without a matching database record")
        strategy = payload.strategy
        try:
            if strategy == "worktree" and (source / ".git").exists():
                subprocess.run(["git", "worktree", "add", "--detach", str(destination)], cwd=source, check=True, capture_output=True, text=True)
            else:
                strategy = "copy"
                shutil.copytree(source, destination, ignore=workspace_copy_ignore)
        except (OSError, subprocess.CalledProcessError) as error:
            raise HTTPException(500, f"Workspace creation failed: {error}") from error
        now = utc_now()
        db.execute("INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?)", (workspace_id, task_id, str(source), str(destination), strategy, "ready", now))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "workspace", task["state"], task["state"], "ROUTE", f"격리 workspace 준비: {strategy}", json.dumps(task["assigned_employees"]), now))
        return {"id": workspace_id, "task_id": task_id, "path": str(destination), "strategy": strategy, "status": "ready"}


@app.post("/api/tasks/{task_id}/command")
def command(task_id: str, payload: Command) -> dict:
    known = registry()
    unknown = sorted(set(payload.employee_ids) - set(known))
    if unknown:
        raise HTTPException(422, f"Unknown employees: {', '.join(unknown)}")
    with database() as db:
        task = task_payload(db, task_id)
        previous = task["state"]
        state = ACTION_TO_STATE[payload.action]
        selected = payload.employee_ids or task["assigned_employees"]
        if payload.action in {"meeting", "assign", "run", "team_review", "cross_review", "verify", "approval"} and not selected:
            raise HTTPException(409, "Select at least one employee before this command")
        if payload.action == "complete":
            passed = db.execute("SELECT COUNT(*) FROM evidence WHERE task_id = ? AND status = 'pass' AND stale = 0", (task_id,)).fetchone()[0]
            if passed == 0:
                raise HTTPException(409, "Completion requires fresh passing Evidence Ledger entries")
        if payload.employee_ids:
            db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
            db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee) for employee in selected])
        now = utc_now()
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (task_id, payload.action, previous, state, "NAVI", payload.note or STATE_LABELS[state], json.dumps(selected), now))
        return task_payload(db, task_id)


@app.post("/api/tasks/{task_id}/runs")
def run_command(task_id: str, payload: RunInput) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "TaskContract required before command execution")
        workspace = db.execute("SELECT * FROM workspaces WHERE id = ? AND task_id = ?", (payload.workspace_id, task_id)).fetchone()
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        workspace_path = Path(workspace["path"]).resolve()
        safe_path, path_reason = validate_path((ROOT / "data" / "workspaces").resolve(), workspace_path)
        safe_command, command_reason = validate_command(payload.command, task["contract"]["allowed_commands"])
        now = utc_now()
        if not safe_path or not safe_command:
            reason = path_reason if not safe_path else command_reason
            db.execute("INSERT INTO permission_checks (task_id, employee_id, action, allowed, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)", (task_id, "GUARD", payload.command, False, reason, now))
            db.execute("UPDATE tasks SET state = 'blocked', updated_at = ? WHERE id = ?", (now, task_id))
            db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "block", task["state"], "blocked", "GUARD", reason, json.dumps(task["assigned_employees"]), now))
            raise HTTPException(403, reason)
        result = subprocess.run(shlex.split(payload.command, posix=False), cwd=workspace_path, capture_output=True, text=True, timeout=300, shell=False)
        stdout = result.stdout.encode("utf-8", errors="replace"); stderr = result.stderr.encode("utf-8", errors="replace")
        count = db.execute("SELECT COUNT(*) FROM runs WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        run_id = f"RUN-{task_id.split('-')[-1]}-{count:02d}"; status = "pass" if result.returncode == 0 else "fail"
        db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, task_id, payload.workspace_id, payload.command, result.returncode, hashlib.sha256(stdout).hexdigest(), hashlib.sha256(stderr).hexdigest(), status, now))
        evidence_id = f"EVD-{task_id.split('-')[-1]}-{count:02d}"
        db.execute("INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (evidence_id, task_id, run_id, "command", status, hashlib.sha256(stdout + stderr).hexdigest(), 0, now))
        state = "verifying" if status == "pass" else "failed"
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "verify" if status == "pass" else "fail", task["state"], state, "BUILD", f"{payload.command}: exit {result.returncode}", json.dumps(task["assigned_employees"]), now))
        return {"run_id": run_id, "evidence_id": evidence_id, "status": status, "exit_code": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}


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
        workspace = Path(workspace_row["path"]).resolve()
        safe, reason = validate_path((ROOT / "data" / "workspaces").resolve(), workspace)
        if not safe:
            raise HTTPException(403, reason)

        role = agent_role(payload.employee_id)
        request_text = (payload.instruction or task["request"]).lower()
        research_task = any(term in request_text for term in ("market research", "market analysis", "research", "\uc2dc\uc7a5\uc870\uc0ac", "\uc2dc\uc7a5 \uc870\uc0ac", "\uc2dc\uc7a5\ubd84\uc11d", "\ub9ac\uc11c\uce58", "\uc870\uc0ac", "\ubd84\uc11d", "\uc0ac\uc5c5\uc544\uc774\ud15c", "\uc0ac\uc5c5 \uc544\uc774\ud15c"))
        skill_context = employee_skill_context(payload.employee_id)
        settings = model_settings()
        model = settings[role["model_role"]]
        changed_files: list[str] = []
        command_results: list[dict] = []
        web_search_used = False
        required_skill_ids = {skill["id"] for skill in skill_context["required_skills"]}
        applied_skill_ids: set[str] = set()
        skill_paths = {skill["id"]: ROOT / skill["path"] for skill in skill_context["required_skills"]}
        tools = [
            {"type": "function", "name": "read_required_skill", "description": "Read full instruction text for one required skill. You must read every required skill before changing files, running verification, or using MCP.", "parameters": {"type": "object", "properties": {"skill_id": {"type": "string", "enum": sorted(required_skill_ids)}}, "required": ["skill_id"], "additionalProperties": False}},
            {"type": "function", "name": "list_files", "description": "List project files in isolated workspace.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
            {"type": "function", "name": "read_file", "description": "Read UTF-8 text file from isolated workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
            {"type": "function", "name": "write_file", "description": "Create or replace UTF-8 text file in isolated workspace. Use only for requested work.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
            {"type": "function", "name": "run_verification", "description": "Run an allowed TaskContract verification command in isolated workspace.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}},
            {"type": "function", "name": "web_search", "description": "Search public web for current, citable sources. Results are leads; report title and URL for each factual claim.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 300}}, "required": ["query"], "additionalProperties": False}},
        ]
        mcp_tool_map: dict[str, tuple[sqlite3.Row, str, str | None]] = {}
        for connection in db.execute("SELECT * FROM mcp_connections WHERE status IN ('configured', 'connected')"):
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
            + ("This is a research task: call web_search before writing your conclusion, then cite source URLs in Korean. " if research_task else "")
            + "Required skill instructions and permissions are included in your context. You must call read_required_skill for every listed required skill before changing files, running verification, or using MCP. Follow them; do not replace them with generic behavior. "
            "Use tools before claiming a change. Never access credentials, parent folders, or delete unrelated files. Use web_search for external research; cite returned URLs and never invent sources. Network access beyond web_search is allowed only through configured MCP tools. "
            "For leads: inspect work, give precise review or debugging changes. For workers: implement smallest safe change. "
            "Finish with Korean summary: changed files, verification run, remaining risk."
        )
        skill_manifest = {
            "permissions": skill_context["permissions"],
            "required_skills": [{"id": skill["id"], "path": skill["path"]} for skill in skill_context["required_skills"]],
        }
        context = json.dumps({"task": task["title"], "request": payload.instruction or task["request"], "contract": task["contract"], "files": workspace_files(workspace), "role": role, "skill_context": skill_manifest}, ensure_ascii=False)
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
            response = client.responses.create(model=model, instructions=instructions, input=context, tools=tools)
            add_usage(response)
            tool_history: list[dict] = []
            for _ in range(12):
                calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
                if not calls:
                    break
                outputs = []
                for call in calls:
                    require_runnable(db, task_id)
                    args = json.loads(call.arguments)
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
                        elif call.name == "list_files":
                            result: object = workspace_files(workspace)
                        elif call.name == "read_file":
                            path = safe_workspace_file(workspace, args["path"], task["contract"]["allowed_paths"])
                            result = path.read_text(encoding="utf-8", errors="replace")[:50000] if path.exists() else {"missing": True}
                        elif call.name == "write_file":
                            missing_skills = sorted(required_skill_ids - applied_skill_ids)
                            if missing_skills:
                                raise HTTPException(409, f"Read all required skills before writing files: {', '.join(missing_skills)}")
                            path = safe_workspace_file(workspace, args["path"], task["contract"]["allowed_paths"])
                            content = args["content"]
                            if len(content.encode("utf-8")) > 100000:
                                raise HTTPException(422, "Agent write exceeds 100 KB limit")
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(content, encoding="utf-8")
                            relative = str(path.relative_to(workspace)).replace("\\", "/")
                            if relative not in changed_files:
                                changed_files.append(relative)
                            result = {"written": relative, "bytes": len(content.encode("utf-8"))}
                        elif call.name == "run_verification":
                            missing_skills = sorted(required_skill_ids - applied_skill_ids)
                            if missing_skills:
                                raise HTTPException(409, f"Read all required skills before verification: {', '.join(missing_skills)}")
                            command = args["command"]
                            allowed, command_reason = validate_command(command, task["contract"]["allowed_commands"])
                            if not allowed:
                                raise HTTPException(403, command_reason)
                            run = subprocess.run(shlex.split(command, posix=False), cwd=workspace, capture_output=True, text=True, timeout=300, shell=False)
                            result = {"exit_code": run.returncode, "stdout": run.stdout[-4000:], "stderr": run.stderr[-4000:]}
                            command_results.append({"command": command, "exit_code": run.returncode})
                        elif call.name == "web_search":
                            results = web_search(args["query"])
                            web_search_used = True
                            now = utc_now()
                            for source in results:
                                db.execute("INSERT INTO research_sources (task_id, employee_id, query, title, url, snippet, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, payload.employee_id, args["query"], source["title"], source["url"], source["snippet"], now))
                                source_hash = hashlib.sha256(source["url"].encode("utf-8")).hexdigest()
                                db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"EVD-{task_id.split('-')[-1]}-WEB-{source_hash[:12]}", task_id, None, "web_source", "pass", source_hash, 0, now))
                            result = {"query": args["query"], "sources": results}
                        elif call.name in mcp_tool_map:
                            missing_skills = sorted(required_skill_ids - applied_skill_ids)
                            if missing_skills:
                                raise HTTPException(409, f"Read all required skills before MCP use: {', '.join(missing_skills)}")
                            connection, remote_name, session_id = mcp_tool_map[call.name]
                            result, next_session = mcp_http_call(connection, "tools/call", {"name": remote_name, "arguments": args}, session_id)
                            mcp_tool_map[call.name] = (connection, remote_name, next_session)
                        else:
                            result = {"error": "Unknown tool"}
                    except HTTPException as error:
                        if error.status_code in {409, 410}:
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
                        output_summary = f"{len(result) if isinstance(result, list) else 0}개 파일 확인"
                    elif call.name == "read_file":
                        output_summary = f"{args.get('path', '')} · {len(result) if isinstance(result, str) else 0:,}자 읽음"
                    elif call.name == "write_file" and isinstance(result, dict) and result.get("written"):
                        output_summary = f"{result['written']} · {result.get('bytes', 0)} bytes"
                    elif call.name == "run_verification" and isinstance(result, dict):
                        output_summary = f"{args.get('command', '')} · exit {result.get('exit_code', 'unknown')}"
                    elif call.name == "web_search" and isinstance(result, dict):
                        output_summary = f"{args.get('query', '')} · {len(result.get('sources', []))}개 출처"
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
                response = client.responses.create(model=model, input=json.dumps({"original_context": json.loads(context), "tool_history": tool_history}, ensure_ascii=False), tools=tools, instructions=instructions)
                add_usage(response)
            else:
                # Stop an endless tool-call loop without treating partial work as
                # completion. Ask for one final evidence-grounded result, no tools.
                response = client.responses.create(
                    model=model,
                    input=json.dumps({"original_context": json.loads(context), "tool_history": tool_history}, ensure_ascii=False),
                    instructions=instructions + " Tool phase is closed. Return the final Korean result using only recorded tool results.",
                )
                add_usage(response)
            if research_task and not web_search_used:
                raise HTTPException(422, "Research agent must call web_search before returning a conclusion")
            summary = response.output_text
        except HTTPException:
            raise
        except Exception as error:
            now = utc_now()
            error_text = str(error)[:4000]
            db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, model, 0, 0, 0, error_text, now))
            db.commit()  # Preserve provider failure even though this request raises and outer context rolls back.
            raise HTTPException(502, "Model agent run failed; see local model_usage log") from error

        input_tokens = total_input_tokens
        output_tokens = total_output_tokens
        now = utc_now()
        if not summary.strip():
            raise HTTPException(502, "Model returned no final output")
        state = "team_review" if role["tier"] == "lead" else "verifying"
        artifact = hashlib.sha256(json.dumps({"files": changed_files, "commands": command_results, "summary": summary}, ensure_ascii=False).encode()).hexdigest()
        evidence_id = f"EVD-{task_id.split('-')[-1]}-AGENT-{payload.employee_id}"
        db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (evidence_id, task_id, None, "agent_run", "pass" if changed_files or command_results else "info", artifact, 0, now))
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, payload.employee_id, "run", summary, now))
        db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, model, input_tokens, output_tokens, 0, None, now))
        # Job worker owns task state. A worker result must not turn an active
        # multi-worker execution into "verifying" before all workers/review finish.
        if not payload.managed_by_job:
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
            db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "agent_run", task["state"], state, payload.employee_id, summary[:800], json.dumps([payload.employee_id]), now))
        checkpoint(db, task_id, f"agent:{payload.employee_id}")
        return {"employee_id": payload.employee_id, "tier": role["tier"], "model": model, "summary": summary, "changed_files": changed_files, "commands": command_results, "evidence_id": evidence_id, "state": task["state"] if payload.managed_by_job else state}


@app.post("/api/tasks/{task_id}/retry")
def retry(task_id: str, payload: RetryInput) -> dict:
    strategy_hash = hashlib.sha256(payload.strategy.encode()).hexdigest()
    with database() as db:
        task = task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "TaskContract required before retry")
        attempts = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE task_id = ?", (task_id,)).fetchone()[0]
        repeated = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE task_id = ? AND failure_class = ? AND strategy_sha256 = ?", (task_id, payload.failure_class, strategy_hash)).fetchone()[0]
        state = "escalated" if attempts >= task["contract"]["retry_limit"] or repeated else "planning"
        now = utc_now(); status = "escalated" if state == "escalated" else "retrying"
        db.execute("INSERT INTO retry_attempts (task_id, failure_class, strategy_sha256, status, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, payload.failure_class, strategy_hash, status, now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "escalate" if state == "escalated" else "retry", task["state"], state, "NAVI", payload.failure_class, json.dumps(task["assigned_employees"]), now))
        return task_payload(db, task_id)


@app.get("/api/tasks/{task_id}/office")
def office(task_id: str) -> dict:
    with database() as db:
        task = task_payload(db, task_id)
        return {"task": task, "employees": office_projection(task)}
