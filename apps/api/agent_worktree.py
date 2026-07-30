"""Per-agent Git worktrees with explicit commit and integration evidence."""
from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from threading import Lock

INTEGRATION_LOCK = Lock()


def _git(workspace: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
        check=check,
    )


def prepare(
    db: sqlite3.Connection,
    *,
    root: Path,
    task_id: str,
    base_workspace_id: str,
    employee_id: str,
    now: str,
) -> dict:
    base = db.execute("SELECT * FROM workspaces WHERE id = ?", (base_workspace_id,)).fetchone()
    if not base:
        raise RuntimeError("Base workspace not found")
    base_path = Path(base["path"]).resolve()
    if _git(base_path, "rev-parse", "--is-inside-work-tree", check=False).returncode:
        return {"workspace_id": base_workspace_id, "path": base_path, "isolated": False}
    if _git(base_path, "status", "--porcelain").stdout.strip():
        return {"workspace_id": base_workspace_id, "path": base_path, "isolated": False, "reason": "base_worktree_dirty"}
    safe_employee = re.sub(r"[^A-Za-z0-9_-]", "-", employee_id)
    destination = (root / "data" / "workspaces" / task_id / "agents" / safe_employee).resolve()
    branch = f"ai-office/{task_id.lower()}/{safe_employee.lower()}"
    workspace_id = f"{base_workspace_id}-{safe_employee}"
    existing = db.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    if existing and Path(existing["path"]).is_dir():
        return {
            "workspace_id": workspace_id,
            "path": Path(existing["path"]),
            "isolated": True,
            "branch": branch,
            "base_path": base_path,
            "worktree_root": destination.parent,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    _git(base_path, "branch", "-D", branch, check=False)
    _git(base_path, "worktree", "add", "-b", branch, str(destination), "HEAD")
    db.execute(
        "INSERT OR REPLACE INTO workspaces VALUES (?, ?, ?, ?, 'worktree', 'ready', ?)",
        (workspace_id, task_id, base["source_root"], str(destination), now),
    )
    return {
        "workspace_id": workspace_id,
        "path": destination,
        "isolated": True,
        "branch": branch,
        "base_path": base_path,
        "worktree_root": destination.parent,
    }


def commit_and_integrate(agent_workspace: dict, *, task_id: str, employee_id: str) -> dict:
    if not agent_workspace.get("isolated"):
        return {"isolated": False, "integrated": False, "reason": agent_workspace.get("reason", "not_git")}
    path = Path(agent_workspace["path"])
    _git(path, "add", "-A")
    if _git(path, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return {"isolated": True, "integrated": True, "commit": None, "changed": False}
    _git(
        path,
        "-c",
        "user.name=AI Office",
        "-c",
        "user.email=ai-office@local",
        "commit",
        "-m",
        f"agent({employee_id}): {task_id} contribution",
    )
    commit = _git(path, "rev-parse", "HEAD").stdout.strip()
    base_path = Path(agent_workspace["base_path"])
    with INTEGRATION_LOCK:
        cherry_pick = _git(base_path, "cherry-pick", commit, check=False)
        if cherry_pick.returncode:
            _git(base_path, "cherry-pick", "--abort", check=False)
            raise RuntimeError(f"Agent worktree integration conflict: {(cherry_pick.stderr or cherry_pick.stdout)[:1000]}")
    return {"isolated": True, "integrated": True, "commit": commit, "changed": True}


def cleanup(base_path: Path, agent_workspace: dict) -> None:
    if not agent_workspace.get("isolated"):
        return
    path = Path(agent_workspace["path"]).resolve()
    worktree_root = Path(agent_workspace["worktree_root"]).resolve()
    if path == worktree_root or not path.is_relative_to(worktree_root):
        raise RuntimeError("Refusing to clean an agent worktree outside its verified root")
    _git(base_path, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path)
