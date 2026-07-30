"""Durable per-agent sessions and bounded context compaction."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

MAX_SESSION_SUMMARY = 12_000
MAX_RECENT_TURNS = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_id(task_id: str, employee_id: str) -> str:
    return f"SESSION-{task_id}-{employee_id}"


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            state TEXT NOT NULL, summary TEXT NOT NULL, turn_count INTEGER NOT NULL,
            last_response_id TEXT, context_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(task_id, employee_id)
        );
        CREATE TABLE IF NOT EXISTS agent_session_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            input_summary TEXT NOT NULL, output_summary TEXT NOT NULL,
            tool_history TEXT NOT NULL, response_id TEXT, created_at TEXT NOT NULL
        );
        """
    )


def load_session_context(db: sqlite3.Connection, task_id: str, employee_id: str) -> dict[str, Any]:
    ensure_schema(db)
    sid = session_id(task_id, employee_id)
    row = db.execute("SELECT * FROM agent_sessions WHERE id = ?", (sid,)).fetchone()
    turns = [
        dict(item)
        for item in db.execute(
            "SELECT input_summary, output_summary, tool_history, response_id, created_at "
            "FROM agent_session_turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (sid, MAX_RECENT_TURNS),
        )
    ]
    turns.reverse()
    for turn in turns:
        turn["tool_history"] = json.loads(turn["tool_history"])
    return {
        "session_id": sid,
        "state": row["state"] if row else "new",
        "summary": row["summary"] if row else "",
        "turn_count": row["turn_count"] if row else 0,
        "last_response_id": row["last_response_id"] if row else None,
        "recent_turns": turns,
    }


def record_session_turn(
    db: sqlite3.Connection,
    task_id: str,
    employee_id: str,
    *,
    input_summary: str,
    output_summary: str,
    tool_history: list[dict[str, Any]],
    response_id: str | None,
    state: str = "active",
) -> dict[str, Any]:
    ensure_schema(db)
    sid = session_id(task_id, employee_id)
    now = _now()
    compact_tools = [
        {
            "tool": item.get("tool"),
            "arguments": item.get("arguments"),
            "result": item.get("result"),
        }
        for item in tool_history[-8:]
    ]
    db.execute(
        "INSERT INTO agent_session_turns "
        "(session_id, input_summary, output_summary, tool_history, response_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            sid,
            input_summary[:4_000],
            output_summary[:8_000],
            json.dumps(compact_tools, ensure_ascii=False)[:20_000],
            response_id,
            now,
        ),
    )
    previous = db.execute("SELECT summary, turn_count, created_at FROM agent_sessions WHERE id = ?", (sid,)).fetchone()
    facts = [
        previous["summary"] if previous else "",
        f"TURN {(previous['turn_count'] if previous else 0) + 1}",
        f"INPUT: {input_summary[:1500]}",
        f"OUTPUT: {output_summary[:4000]}",
        "TOOLS: " + ", ".join(str(item.get("tool")) for item in compact_tools),
    ]
    summary = "\n".join(item for item in facts if item).strip()
    if len(summary) > MAX_SESSION_SUMMARY:
        summary = summary[-MAX_SESSION_SUMMARY:]
        first_break = summary.find("\n")
        if first_break >= 0:
            summary = summary[first_break + 1 :]
    context_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    db.execute(
        "INSERT INTO agent_sessions "
        "(id, task_id, employee_id, state, summary, turn_count, last_response_id, context_sha256, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET state=excluded.state, summary=excluded.summary, "
        "turn_count=excluded.turn_count, last_response_id=excluded.last_response_id, "
        "context_sha256=excluded.context_sha256, updated_at=excluded.updated_at",
        (
            sid,
            task_id,
            employee_id,
            state,
            summary,
            (previous["turn_count"] if previous else 0) + 1,
            response_id,
            context_hash,
            previous["created_at"] if previous else now,
            now,
        ),
    )
    return {"session_id": sid, "summary": summary, "context_sha256": context_hash}


def set_session_state(db: sqlite3.Connection, task_id: str, employee_id: str, state: str) -> None:
    ensure_schema(db)
    db.execute(
        "UPDATE agent_sessions SET state = ?, updated_at = ? WHERE id = ?",
        (state, _now(), session_id(task_id, employee_id)),
    )
