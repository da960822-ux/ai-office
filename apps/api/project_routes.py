"""Project registration and task workspace endpoints.

Extracted verbatim from ``apps/api/main.py``. Covers the project list/create pair,
the native folder picker and the per-task workspace read/create pair.

Helpers are reached through ``main.<name>`` so ``patch.object(main, ...)`` in the
test suite still applies - see ``admin_routes`` for the full rationale.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from fastapi import APIRouter, HTTPException

from apps.api import main
from apps.api.api_models import (
    ProjectInput,
    WorkspaceInput,
)

router = APIRouter()


@router.get("/api/projects")
def projects() -> list[dict]:
    with main.database() as db:
        return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at DESC")]


@router.post("/api/projects/pick")
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
    return {"path": str(main.safe_project_root(selected))}


@router.post("/api/projects", status_code=201)
def create_project(payload: ProjectInput) -> dict:
    root = main.safe_project_root(payload.root_path); now = main.utc_now()
    with main.database() as db:
        sequence = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] + 1
        project = {"id": f"PROJECT-{sequence:03d}", "name": payload.name or root.name, "root_path": str(root), "git_available": int((root / ".git").exists()), "created_at": now}
        db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?)", tuple(project.values()))
        return project


@router.get("/api/tasks/{task_id}/workspace")
def get_workspace(task_id: str) -> dict:
    with main.database() as db:
        main.task_payload(db, task_id)
        workspace = db.execute("SELECT * FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        return dict(workspace)


@router.post("/api/tasks/{task_id}/workspace")
def create_workspace(task_id: str, payload: WorkspaceInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        project = db.execute("SELECT * FROM projects WHERE id = ?", (payload.project_id,)).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        source = main.safe_project_root(project["root_path"])
        workspace_id = f"WS-{task_id.split('-')[-1]}"
        destination = source if payload.strategy == "in_place" else (main.ROOT / "data" / "workspaces" / workspace_id).resolve()
        if payload.strategy != "in_place":
            allowed, reason = main.validate_path((main.ROOT / "data" / "workspaces").resolve(), destination)
            if not allowed:
                raise HTTPException(403, reason)
        existing = db.execute("SELECT * FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if existing:
            return dict(existing)
        if payload.strategy != "in_place" and destination.exists():
            raise HTTPException(409, "Workspace path exists without a matching database record")
        strategy = payload.strategy
        try:
            if strategy == "in_place":
                pass
            elif strategy == "worktree" and (source / ".git").exists():
                subprocess.run(["git", "worktree", "add", "--detach", str(destination)], cwd=source, check=True, capture_output=True, text=True)
            else:
                strategy = "copy"
                shutil.copytree(source, destination, ignore=main.workspace_copy_ignore)
        except (OSError, subprocess.CalledProcessError) as error:
            raise HTTPException(500, f"Workspace creation failed: {error}") from error
        now = main.utc_now()
        db.execute("INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?)", (workspace_id, task_id, str(source), str(destination), strategy, "ready", now))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "workspace", task["state"], task["state"], "ROUTE", f"작업 프로젝트 준비: {strategy}", json.dumps(task["assigned_employees"]), now))
        return {"id": workspace_id, "task_id": task_id, "path": str(destination), "strategy": strategy, "status": "ready"}
