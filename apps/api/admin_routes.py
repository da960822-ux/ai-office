"""Read-only status and settings endpoints for the ``/api/*`` surface.

Extracted verbatim from ``apps/api/main.py``: health, runtime version, usage
rollup, model/MCP settings, registry and capability reads, skill verification and
the lesson log.

Every helper is reached through ``main.<name>`` rather than imported by name. The
test suite patches ``main.model_client``, ``main.model_key`` and friends by module
attribute; a direct ``from apps.api.main import model_key`` would bind the original
function here and silently defeat those patches while still importing cleanly.

``main`` imports this module at the very bottom of the file, so by the time the
module-scope ``from apps.api import main`` below runs, every helper these handlers
call is already defined on the partially initialised module object.
"""

from __future__ import annotations

import json

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from apps.api import main
from apps.api.api_models import (
    McpConnectionInput,
    ModelSettingsInput,
)

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    return {"ok": True, "build_id": main.BUILD_ID, "schema_version": main.SCHEMA_VERSION, "registry_employees": len(main.registry()), "model": main.public_model_settings()}


@router.get("/api/runtime/version")
def runtime_version() -> dict:
    with main.database() as db:
        running = db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','pause_requested','cancel_requested')").fetchone()[0]
        worker = db.execute("SELECT build_id, heartbeat_at FROM worker_heartbeats ORDER BY heartbeat_at DESC LIMIT 1").fetchone()
    fresh = worker and (datetime.now(timezone.utc) - datetime.fromisoformat(worker["heartbeat_at"])).total_seconds() < 8
    return {"api_build_id": main.BUILD_ID, "worker_build_id": worker["build_id"] if fresh else None, "schema_version": main.SCHEMA_VERSION, "running_jobs": running}


@router.get("/api/usage/summary")
def usage_summary() -> dict:
    with main.database() as db:
        row = db.execute("SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), COALESCE(SUM(cost_usd), 0), COUNT(*) FROM model_usage").fetchone()
        return {"input_tokens": row[0], "output_tokens": row[1], "cost_usd": row[2], "cost_known": bool(row[3] and row[2] > 0)}


@router.get("/api/settings/model")
def get_model_settings() -> dict:
    return main.public_model_settings()


@router.get("/api/settings/models")
def get_openrouter_models() -> list[dict]:
    return main.openrouter_models()


@router.post("/api/settings/model")
def save_model_settings(payload: ModelSettingsInput) -> dict:
    routing = main.model_routing()
    known_teams = {employee["team"] for employee in main.registry().values()}
    known_employees = set(main.registry())
    unknown_roles = set(payload.role_models) - set(routing["role_models"])
    unknown_teams = set(payload.team_overrides) - known_teams
    unknown_employees = set(payload.employee_overrides) - known_employees
    if unknown_roles or unknown_teams or unknown_employees:
        raise HTTPException(422, "Unknown model routing target")
    main.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    role_models = {key: value.strip() for key, value in payload.role_models.items() if value.strip()}
    if payload.lead_model:
        role_models["complex_design_integration"] = payload.lead_model
    if payload.worker_model:
        role_models["development_basic"] = payload.worker_model
    main.SETTINGS_PATH.write_text(json.dumps({"provider": payload.provider, "role_models": role_models, "team_overrides": payload.team_overrides, "employee_overrides": payload.employee_overrides}, indent=2, ensure_ascii=False), encoding="utf-8")
    if payload.api_key:
        try:
            main.keyring.set_password(main.KEYRING_SERVICE, "openrouter_api_key", payload.api_key)
        except main.keyring.errors.KeyringError as error:
            raise HTTPException(500, f"Could not save API key in Windows Credential Manager: {error}") from error
    return main.public_model_settings()


@router.get("/api/settings/mcp")
def get_mcp_connections() -> list[dict]:
    with main.database() as db:
        return [dict(row) | {"configured": bool(row["credential_key"])} for row in db.execute("SELECT * FROM mcp_connections ORDER BY created_at DESC")]


@router.post("/api/settings/mcp", status_code=201)
def save_mcp_connection(payload: McpConnectionInput) -> dict:
    if not payload.server_url.startswith("https://") and not payload.server_url.startswith("http://localhost") and not payload.server_url.startswith("http://127.0.0.1"):
        raise HTTPException(422, "MCP server URL must use HTTPS or local HTTP")
    with main.database() as db:
        count = db.execute("SELECT COUNT(*) FROM mcp_connections").fetchone()[0] + 1
        connection_id = f"MCP-{count:03d}"
        credential_key = f"mcp:{connection_id}"
        if payload.auth_token:
            try:
                main.keyring.set_password(main.KEYRING_SERVICE, credential_key, payload.auth_token)
            except main.keyring.errors.KeyringError as error:
                raise HTTPException(500, f"Could not save MCP credential in Windows Credential Manager: {error}") from error
        now = main.utc_now()
        db.execute("INSERT INTO mcp_connections VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (connection_id, payload.provider, payload.name, payload.transport, payload.server_url, credential_key if payload.auth_token else None, "configured", now))
        return {"id": connection_id, "provider": payload.provider, "name": payload.name, "transport": payload.transport, "server_url": payload.server_url, "configured": bool(payload.auth_token), "status": "configured", "created_at": now}


@router.post("/api/settings/mcp/{connection_id}/test")
def test_mcp_connection(connection_id: str) -> dict:
    with main.database() as db:
        connection = db.execute("SELECT * FROM mcp_connections WHERE id = ?", (connection_id,)).fetchone()
        if not connection:
            raise HTTPException(404, "MCP connection not found")
        tools, _ = main.mcp_initialize(connection)
        db.execute("UPDATE mcp_connections SET status = 'connected' WHERE id = ?", (connection_id,))
        return {"id": connection_id, "status": "connected", "tool_count": len(tools), "tools": [tool.get("name") for tool in tools]}


@router.get("/api/registry/employees")
def employees() -> list[dict]:
    return [{"id": key} | value | {"skill_ready": main.employee_security(key)["ready"], "agent_role": main.agent_role(key), "model_assignment": main.model_assignment(key)} for key, value in main.registry().items()]


@router.get("/api/registry/employees/{employee_id}/security")
def employee_permissions(employee_id: str) -> dict:
    if employee_id not in main.registry():
        raise HTTPException(404, "Employee not found")
    result = main.employee_security(employee_id)
    with main.database() as db:
        db.execute("INSERT INTO skill_verifications (employee_id, ready, result, created_at) VALUES (?, ?, ?, ?)", (employee_id, result["ready"], json.dumps(result), main.utc_now()))
        return result


@router.get("/api/agents/{employee_id}/capabilities")
def agent_capabilities(employee_id: str) -> dict:
    if employee_id not in main.registry():
        raise HTTPException(404, "Employee not found")
    employee = main.registry()[employee_id]
    security = main.employee_security(employee_id)
    return {"employee": {"id": employee_id} | employee | {"agent_role": main.agent_role(employee_id), "model_assignment": main.model_assignment(employee_id)}, "permissions": security["permissions"], "skills": security["skills"], "team_skills": main.employee_skill_pool(employee_id)}


@router.get("/api/teams/{team_id}/capabilities")
def team_capabilities(team_id: str) -> dict:
    members = [{"id": key} | value | {"agent_role": main.agent_role(key), "model_assignment": main.model_assignment(key), "security": main.employee_security(key)} for key, value in main.registry().items() if value["team"] == team_id]
    if not members:
        raise HTTPException(404, "Team not found")
    return {"team_id": team_id, "members": members}


@router.post("/api/skills/verify")
def verify_skills() -> list[dict]:
    results = [main.employee_security(employee_id) for employee_id in main.registry()]
    with main.database() as db:
        now = main.utc_now()
        db.executemany("INSERT INTO skill_verifications (employee_id, ready, result, created_at) VALUES (?, ?, ?, ?)", [(result["employee_id"], result["ready"], json.dumps(result), now) for result in results])
    return results


@router.get("/api/lessons")
def list_lessons() -> list[dict]:
    with main.database() as db:
        return [dict(row) for row in db.execute("SELECT * FROM lessons ORDER BY created_at DESC LIMIT 100")]
