"""Task lifecycle endpoints - the largest slice of the ``/api/*`` surface.

Extracted verbatim from ``apps/api/main.py``: task CRUD, the SSE event stream,
checkpoint restore, contract and permission decisions, planning, pause/steer/
resume/cancel, lead and worker selection, meetings, reviews, approval, reflection,
state commands, verification runs, retry, the office projection and the CEO brief.

``POST /api/tasks/{task_id}/agent/run`` deliberately stays in ``main``: the test
suite intercepts it with ``patch.object(main, "run_agent", ...)``, and a moved
definition would keep importing fine while silently dropping the patch - green
tests calling a real model.

Helpers are reached through ``main.<name>`` for the same reason; see
``admin_routes`` for the full rationale.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from apps.api import main
from apps.api.api_models import (
    ApprovalInput,
    Command,
    ContractInput,
    CreateTask,
    DirectDispatchInput,
    MeetingInput,
    PermissionDecisionInput,
    ReflectionInput,
    RetryInput,
    ReviewInput,
    RunInput,
    SelectionInput,
    SteeringInput,
)

router = APIRouter()


@router.get("/api/tasks/{task_id}/events/stream")
def event_stream(task_id: str, after: int = 0) -> StreamingResponse:
    def stream():
        cursor = after
        while True:
            with main.database() as db:
                rows = [dict(row) for row in db.execute("SELECT * FROM job_events WHERE task_id = ? AND id > ? ORDER BY id", (task_id, cursor))]
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: job\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            yield ": keepalive\n\n"
            time.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/tasks/{task_id}/agent/brief")
def agent_brief(task_id: str) -> dict:
    key = main.model_key()
    if not key:
        raise HTTPException(409, "OpenRouter API key is not configured")
    with main.database() as db:
        task = main.task_payload(db, task_id)
        settings = main.model_settings()
        instructions = "You are NAVI, the chief orchestrator of a local AI automation office. Return a compact Korean execution brief with: task contract risks, departments, next action, verification evidence needed. Do not claim tools were run."
        input_text = json.dumps({"task": task["title"], "request": task["request"], "state": task["state"], "assigned_employees": task["assigned_employees"], "contract": task["contract"]}, ensure_ascii=False)
        try:
            response = main.model_client().responses.create(model=main.model_assignment("NAVI")["model"], instructions=instructions, input=input_text)
        except Exception as error:
            main.record_usage(db, task_id, main.model_assignment("NAVI")["model"], error=str(error))
            raise HTTPException(502, "Model call failed; see local model_usage log") from error
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        text = response.output_text
        now = main.utc_now()
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, "NAVI", "brief", text, now))
        main.record_usage(db, task_id, main.model_assignment("NAVI")["model"], input_tokens, output_tokens)
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "agent_brief", task["state"], task["state"], "NAVI", "CEO briefing generated", json.dumps(["NAVI"]), now))
        return {"employee_id": "NAVI", "content": text, "model": main.model_assignment("NAVI")["model"], "input_tokens": input_tokens, "output_tokens": output_tokens}


@router.get("/api/tasks")
def tasks() -> list[dict]:
    with main.database() as db:
        ids = [r[0] for r in db.execute("SELECT id FROM tasks ORDER BY updated_at DESC")]
        return [main.task_payload(db, task_id) for task_id in ids]


@router.post("/api/tasks", status_code=201)
def create_task(payload: CreateTask) -> dict:
    known = main.registry()
    unknown = sorted(set(payload.selected_employees) - set(known))
    if unknown:
        raise HTTPException(422, f"Unknown employees: {', '.join(unknown)}")
    if payload.route == "direct_lead" and (payload.lead_id not in main.LEAD_IDS or payload.lead_id == "NAVI"):
        raise HTTPException(422, "Direct task requires a department lead")
    with main.database() as db:
        sequence = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] + 1
        task_id = f"TASK-{sequence:03d}"
        now = main.utc_now()
        db.execute("INSERT INTO tasks (id, title, request, state, created_at, updated_at, route, lead_id, parent_task_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_id, payload.title, payload.request, "draft", now, now, payload.route, payload.lead_id, payload.parent_task_id))
        initial = [payload.lead_id] if payload.route == "direct_lead" and payload.lead_id else ["NAVI"]
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee) for employee in initial])
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (task_id, "create", None, "draft", "NAVI", "업무 요청 접수", json.dumps(initial), now))
        main.emit_job_event(db, task_id, "task.created", "업무 요청 접수", agent_id=payload.lead_id or "NAVI")
        return main.task_payload(db, task_id)


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    with main.database() as db:
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/checkpoints/{checkpoint_id}/restore")
def restore_checkpoint(task_id: str, checkpoint_id: int) -> dict:
    with main.database() as db:
        active = db.execute(
            "SELECT id FROM jobs WHERE task_id = ? AND state IN "
            "('queued','running','pause_requested','cancel_requested') LIMIT 1",
            (task_id,),
        ).fetchone()
        if active:
            raise HTTPException(409, f"Stop active Job {active['id']} before checkpoint restore")
        row = db.execute(
            "SELECT * FROM task_checkpoints WHERE id = ? AND task_id = ?",
            (checkpoint_id, task_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Checkpoint not found")
        snapshot = json.loads(row["snapshot"])
        task_snapshot = snapshot["task"]
        db.execute(
            "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
            (task_snapshot["state"], main.utc_now(), task_id),
        )
        for phase in snapshot.get("phases", []):
            db.execute(
                "UPDATE task_phases SET status = ?, artifact_ids = ?, updated_at = ? "
                "WHERE task_id = ? AND phase_id = ?",
                (phase["status"], phase["artifact_ids"], main.utc_now(), task_id, phase["phase_id"]),
            )
        for deliverable in snapshot.get("deliverables", []):
            db.execute(
                "UPDATE deliverables SET status = ?, artifact_sha256 = ?, updated_at = ? "
                "WHERE task_id = ? AND id = ?",
                (
                    deliverable["status"],
                    deliverable["artifact_sha256"],
                    main.utc_now(),
                    task_id,
                    deliverable["id"],
                ),
            )
        evidence_ids = [item["id"] for item in snapshot.get("evidence", [])]
        db.execute("UPDATE evidence SET stale = 1 WHERE task_id = ?", (task_id,))
        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            db.execute(
                f"UPDATE evidence SET stale = 0 WHERE task_id = ? AND id IN ({placeholders})",
                (task_id, *evidence_ids),
            )
        for session in snapshot.get("agent_sessions", []):
            db.execute(
                "UPDATE agent_sessions SET state = ?, summary = ?, turn_count = ?, "
                "last_response_id = ?, context_sha256 = ?, updated_at = ? WHERE id = ?",
                (
                    session["state"], session["summary"], session["turn_count"],
                    session["last_response_id"], session["context_sha256"], main.utc_now(), session["id"],
                ),
            )
        main.emit_job_event(
            db,
            task_id,
            "checkpoint.restored",
            f"Checkpoint {checkpoint_id} restored; later evidence marked stale",
            payload={"checkpoint_id": checkpoint_id},
        )
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/contract")
def create_contract(task_id: str, payload: ContractInput) -> dict:
    with main.database() as db:
        main.task_payload(db, task_id)
        now = main.utc_now()
        mandatory = [
            "요청을 직접 충족한다",
            "선택한 프로젝트 안에 실제 산출물 파일이 존재한다",
            "부서별 결과가 하나의 최종안으로 통합된다",
            "검증 근거와 최종 검수 결과가 기록된다",
        ]
        acceptance_criteria = list(dict.fromkeys([*payload.acceptance_criteria, *mandatory]))
        db.execute("INSERT INTO task_contracts VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET allowed_paths=excluded.allowed_paths, allowed_commands=excluded.allowed_commands, acceptance_criteria=excluded.acceptance_criteria, retry_limit=excluded.retry_limit, token_limit=excluded.token_limit, updated_at=excluded.updated_at", (task_id, json.dumps(payload.allowed_paths), json.dumps(payload.allowed_commands), json.dumps(acceptance_criteria, ensure_ascii=False), payload.retry_limit, payload.token_limit, now, now))
        db.execute("DELETE FROM task_permission_rules WHERE task_id = ?", (task_id,))
        db.executemany(
            "INSERT INTO task_permission_rules (task_id, action, effect, pattern, created_at) VALUES (?, ?, ?, ?, ?)",
            [(task_id, rule.action, rule.effect, rule.pattern, now) for rule in payload.permission_rules],
        )
        db.execute("UPDATE tasks SET state = 'contracting', updated_at = ? WHERE id = ?", (now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "contract", None, "contracting", "NAVI", "TaskContract 생성", json.dumps(["NAVI"]), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/permissions/{request_id}")
def decide_permission(task_id: str, request_id: str, payload: PermissionDecisionInput) -> dict:
    with main.database() as db:
        request = db.execute(
            "SELECT * FROM permission_requests WHERE id = ? AND task_id = ?",
            (request_id, task_id),
        ).fetchone()
        if not request:
            raise HTTPException(404, "Permission request not found")
        state = "approved" if payload.decision == "approve" else "denied"
        db.execute(
            "UPDATE permission_requests SET state = ?, reason = ?, decided_at = ? WHERE id = ?",
            (state, payload.reason or payload.decision, main.utc_now(), request_id),
        )
        db.execute(
            "INSERT INTO permission_checks (task_id, employee_id, action, allowed, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, request["employee_id"], f"{request['action']}:{request['target']}", int(state == "approved"), payload.reason or state, main.utc_now()),
        )
        return dict(db.execute("SELECT * FROM permission_requests WHERE id = ?", (request_id,)).fetchone())


@router.post("/api/tasks/{task_id}/plan")
def plan(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "Create TaskContract before planning")
        try:
            roster, items, selection_reason, selection_usage = main.select_roster_with_model(task["request"])
        except Exception as error:
            fallback_roster, _ = main.planned_roster(task["request"])
            roster = [employee_id for employee_id in fallback_roster if employee_id in main.LEAD_IDS and employee_id != "NAVI"][:3] or ["FRAME"]
            items = [(leader, f"{leader} team scope, delegation, and acceptance plan") for leader in roster]
            selection_reason, selection_usage = f"Model selection failed; used deterministic fallback: {error}", None
            if main.model_key():
                main.record_usage(db, task_id, main.model_assignment("NAVI")["model"], error=str(error))
        main.require_skill_ready(roster, task["request"])
        now = main.utc_now()
        execution_plan = selection_usage.get("plan") if selection_usage and selection_usage.get("plan") else main.fallback_execution_plan(roster, items)
        main.store_execution_plan(db, task_id, execution_plan)
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
            main.record_usage(db, task_id, selection_usage["model"], selection_usage["input_tokens"], selection_usage["output_tokens"])
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "plan", task["state"], "planning", "NAVI", selection_reason, json.dumps(roster), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if task["state"] in {"completed", "cancelled"}:
            raise HTTPException(409, "Completed or cancelled task cannot be paused")
        now = main.utc_now()
        db.execute("INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) VALUES (?, ?, 1, 0, ?) ON CONFLICT(task_id) DO UPDATE SET state_before_pause=excluded.state_before_pause, pause_requested=1, updated_at=excluded.updated_at", (task_id, task["state"], now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("paused", now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "pause", task["state"], "paused", "CEO", "Pause requested. Current model call may finish; next tool or agent call stops.", "[]", now))
        main.checkpoint(db, task_id, "paused")
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/steer", status_code=202)
def steer_task(task_id: str, payload: SteeringInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if task["state"] in {"completed", "cancelled"}:
            raise HTTPException(409, "Completed or cancelled task cannot receive new instructions")
        now = main.utc_now()
        cursor = db.execute(
            "INSERT INTO steering_messages (task_id, content, status, created_at, applied_at) "
            "VALUES (?, ?, 'queued', ?, NULL)",
            (task_id, payload.content.strip(), now),
        )
        main.emit_job_event(
            db, task_id, "steering.queued", "사용자 추가 지시가 활성 작업에 등록되었습니다.",
            payload={"steering_id": cursor.lastrowid},
        )
        return {"id": cursor.lastrowid, "task_id": task_id, "status": "queued", "created_at": now}


@router.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if task["state"] != "paused":
            raise HTTPException(409, "Only a paused task can resume")
        control = db.execute("SELECT state_before_pause FROM task_controls WHERE task_id = ?", (task_id,)).fetchone()
        resume_state = control["state_before_pause"] if control and control["state_before_pause"] in main.TASK_STATES else "assigned"
        now = main.utc_now()
        db.execute("UPDATE task_controls SET pause_requested = 0, updated_at = ? WHERE task_id = ?", (now, task_id))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (resume_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "resume", "paused", resume_state, "CEO", "Resume requested", "[]", now))
        main.checkpoint(db, task_id, "resumed")
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if task["state"] in {"completed", "cancelled"}:
            raise HTTPException(409, "Completed or cancelled task cannot be cancelled")
        now = main.utc_now()
        db.execute("INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) VALUES (?, ?, 0, 1, ?) ON CONFLICT(task_id) DO UPDATE SET pause_requested=0, cancel_requested=1, updated_at=excluded.updated_at", (task_id, task["state"], now))
        db.execute("UPDATE jobs SET state = CASE WHEN state = 'queued' THEN 'cancelled' ELSE 'cancel_requested' END, updated_at = ? WHERE task_id = ? AND state IN ('queued','running','pause_requested')", (now, task_id))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("cancelled", now, task_id))
        db.execute("UPDATE meetings SET status = 'cancelled' WHERE task_id = ? AND status = 'active'", (task_id,))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "cancel", task["state"], "cancelled", "CEO", "Cancel requested. Future agent calls blocked; completed evidence retained.", "[]", now))
        main.checkpoint(db, task_id, "cancelled")
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/direct-dispatch")
def direct_dispatch(task_id: str, payload: DirectDispatchInput) -> dict:
    """CEO direct order: one selected lead, no NAVI planning or lead meeting."""
    if payload.lead_id not in main.LEAD_IDS or payload.lead_id == "NAVI":
        raise HTTPException(422, "Direct dispatch target must be a department lead")
    with main.database() as db:
        main.require_runnable(db, task_id)
        task = main.task_payload(db, task_id)
        main.require_skill_ready([payload.lead_id], task["request"])
        now = main.utc_now()
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.execute("INSERT INTO task_assignments VALUES (?, ?)", (task_id, payload.lead_id))
        db.execute("DELETE FROM action_items WHERE task_id = ?", (task_id,))
        db.execute("INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"ACT-{task_id.split('-')[-1]}-01", task_id, None, payload.lead_id, "Direct CEO order: complete small scoped task without a lead meeting", 1, json.dumps(task["contract"]["acceptance_criteria"]), "assigned"))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("assigned", now, task_id))
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, payload.lead_id, "direct_order", task["request"], now))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "direct_dispatch", task["state"], "assigned", "CEO", "Direct order; NAVI planning and lead meeting skipped", json.dumps([payload.lead_id]), now))
        main.checkpoint(db, task_id, f"direct:{payload.lead_id}")
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/select-leads")
def select_leads(task_id: str, payload: SelectionInput) -> dict:
    with main.database() as db:
        main.require_runnable(db, task_id)
        task = main.task_payload(db, task_id)
        if task["state"] != "awaiting_lead_selection":
            raise HTTPException(409, "Task is not awaiting lead selection")
        candidates = set(task["assigned_employees"])
        selected = list(dict.fromkeys(payload.employee_ids))
        if not set(selected).issubset(candidates) or any(employee_id not in main.LEAD_IDS or employee_id == "NAVI" for employee_id in selected):
            raise HTTPException(422, "Select only NAVI-proposed department leads")
        now = main.utc_now(); meeting_id = f"MEET-{task_id.split('-')[-1]}-LEADS"; participants = ["NAVI", *selected]
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee_id) for employee_id in selected])
        db.execute("INSERT OR REPLACE INTO meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (meeting_id, task_id, "lead_dispatch", "NAVI-led: selected department leads decide scope, risks, worker delegation", json.dumps(participants), json.dumps(["scope", "risk", "worker roles", "acceptance"]), json.dumps([]), "active", now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("meeting_running", now, task_id))
        meeting_job = main.enqueue_job(db, task_id, "meeting", {"meeting_id": meeting_id, "participants": participants})
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "lead_selection", task["state"], "meeting_running", "USER", "Selected leads approved; autonomous meeting started", json.dumps(participants), now))
        main.emit_job_event(db, task_id, "meeting.queued", "대표가 팀장을 선택해 회의 Job을 자동 시작했습니다.", job_id=meeting_job["id"], agent_id="NAVI", payload={"participants": participants})
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/select-workers")
def select_workers(task_id: str, payload: SelectionInput) -> dict:
    with main.database() as db:
        main.require_runnable(db, task_id)
        task = main.task_payload(db, task_id)
        selected = list(dict.fromkeys(payload.employee_ids))
        direct_lead_id = task.get("lead_id") if task.get("route") == "direct_lead" else None
        proposed = {item["owner"] for item in task["action_items"]}
        # Compatibility for pre-worker proposals that still named a lead instead of its team members.
        proposed_leads = proposed & main.LEAD_IDS
        if proposed_leads:
            lead_teams = {main.registry()[lead]["team"] for lead in proposed_leads}
            proposed |= {employee_id for employee_id, employee in main.registry().items() if employee["team"] in lead_teams and employee_id not in main.LEAD_IDS}
            if direct_lead_id in proposed_leads:
                proposed.add(direct_lead_id)
        if not proposed:
            raise HTTPException(409, "Wait for the responsible lead's worker proposal")
        if not set(selected).issubset(proposed):
            raise HTTPException(422, "Select only workers proposed by the responsible team lead")
        if any(employee_id not in main.registry() or (employee_id in main.LEAD_IDS and employee_id != direct_lead_id) for employee_id in selected):
            raise HTTPException(422, "Select worker agents only")
        lead_ids = [direct_lead_id] if direct_lead_id else [employee_id for meeting in task["meetings"] if meeting["type"] == "lead_dispatch" for employee_id in meeting["participants"] if employee_id != "NAVI"]
        if not lead_ids:
            raise HTTPException(409, "Select department leads first")
        now = main.utc_now(); assignments = list(dict.fromkeys(lead_ids + selected))
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee_id) for employee_id in assignments])
        placeholders = ",".join("?" for _ in assignments)
        db.execute(
            f"UPDATE task_phases SET status = CASE "
            f"WHEN owner_id IN ({placeholders}) THEN 'assigned' WHEN source = 'meeting' THEN 'skipped' ELSE status END, "
            "updated_at = ? WHERE task_id = ?",
            (*assignments, now, task_id),
        )
        skipped = {
            row["phase_id"]
            for row in db.execute(
                "SELECT phase_id FROM task_phases WHERE task_id = ? AND status = 'skipped'",
                (task_id,),
            )
        }
        if skipped:
            rows = list(db.execute("SELECT phase_id, dependencies FROM task_phases WHERE task_id = ?", (task_id,)))
            for row in rows:
                dependencies = [item for item in json.loads(row["dependencies"]) if item not in skipped]
                db.execute(
                    "UPDATE task_phases SET dependencies = ?, updated_at = ? WHERE task_id = ? AND phase_id = ?",
                    (json.dumps(dependencies, ensure_ascii=False), now, task_id, row["phase_id"]),
                )
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("assigned", now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "worker_selection", task["state"], "assigned", "USER", "User selected worker agents", json.dumps(selected), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/meetings")
def create_meeting(task_id: str, payload: MeetingInput) -> dict:
    raise HTTPException(410, "Manual meeting creation is disabled; select leads and let the worker start the meeting Job")
    unknown = sorted(set(payload.participant_ids) - set(main.registry()))
    if unknown:
        raise HTTPException(422, f"Unknown employees: {', '.join(unknown)}")
    with main.database() as db:
        task = main.task_payload(db, task_id); now = main.utc_now()
        count = db.execute("SELECT COUNT(*) FROM meetings WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        meeting_id = f"MEET-{task_id.split('-')[-1]}-{count:02d}"
        db.execute("INSERT INTO meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (meeting_id, task_id, "department", payload.objective, json.dumps(payload.participant_ids), json.dumps(payload.agenda), json.dumps([]), "active", now))
        db.execute("UPDATE tasks SET state = 'meeting', updated_at = ? WHERE id = ?", (now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "meeting", task["state"], "meeting", "NAVI", payload.objective, json.dumps(payload.participant_ids), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/meetings/{meeting_id}/run")
def run_meeting(task_id: str, meeting_id: str) -> dict:
    """Record one real model response per attendee, then conclude the meeting."""
    raise HTTPException(410, "Browser meeting execution is disabled; the local worker owns meeting Jobs")
    if not main.model_key():
        raise HTTPException(409, "OpenRouter API key is not configured")
    with main.database() as db:
        main.require_runnable(db, task_id)
        task = main.task_payload(db, task_id)
        meeting = db.execute("SELECT * FROM meetings WHERE id = ? AND task_id = ?", (meeting_id, task_id)).fetchone()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        if meeting["status"] != "active":
            raise HTTPException(409, "Meeting is not active")
        participants = json.loads(meeting["participants"])
        agenda = json.loads(meeting["agenda"])
        transcript: list[str] = []
        try:
            for employee_id in participants:
                main.require_runnable(db, task_id)
                role = main.agent_role(employee_id)
                meeting_model = main.task_model_assignment(db, task_id, employee_id)["model"]
                response = main.model_client().responses.create(
                    model=meeting_model,
                    instructions=(
                        f"You are {employee_id}, {role['title']}. Participate in a work meeting. "
                        "Give one concise, evidence-focused Korean contribution. Do not claim unverified research."
                    ),
                    input=json.dumps({"task": task["request"], "objective": meeting["objective"], "agenda": agenda, "prior_contributions": transcript}, ensure_ascii=False),
                )
                content = response.output_text.strip()
                usage = getattr(response, "usage", None)
                db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (task_id, employee_id, "meeting", content, main.utc_now()))
                main.record_usage(db, task_id, meeting_model, getattr(usage, "input_tokens", 0) if usage else 0, getattr(usage, "output_tokens", 0) if usage else 0)
                transcript.append(f"{employee_id}: {content}")
        except HTTPException:
            raise
        except Exception as error:
            main.record_usage(db, task_id, settings["lead_model"], error=str(error))
            raise HTTPException(502, "Meeting model run failed; see local model_usage log") from error
        now = main.utc_now()
        db.execute("UPDATE meetings SET status = ?, decisions = ? WHERE id = ?", ("concluded", json.dumps(["Transcript recorded. Review evidence before execution."], ensure_ascii=False), meeting_id))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("planning", now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "meeting_run", task["state"], "planning", "NAVI", "Meeting transcript recorded", json.dumps(participants), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/reviews")
def create_review(task_id: str, payload: ReviewInput) -> dict:
    raise HTTPException(409, "Manual reviews are disabled; queue a lead review Job after Evidence")
    if payload.reviewer_id not in main.registry():
        raise HTTPException(404, "Reviewer not found")
    with main.database() as db:
        main.require_runnable(db, task_id)
        task = main.task_payload(db, task_id)
        if payload.reviewer_id not in task["assigned_employees"]:
            raise HTTPException(403, "Reviewer is not assigned to this task")
        if payload.reviewer_id not in main.LEAD_IDS and main.registry()[payload.reviewer_id]["runtime"] != "REVIEWER":
            raise HTTPException(403, "Reviewer must be a team lead or reviewer agent")
        direct_order = next((event for event in task["events"] if event["action"] == "direct_dispatch"), None)
        if direct_order:
            required_lead = direct_order["employee_ids"][0]
            if payload.reviewer_id != required_lead:
                raise HTTPException(403, f"Direct task requires review by assigned lead: {required_lead}")
        count = db.execute("SELECT COUNT(*) FROM reviews WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        review_id = f"REV-{task_id.split('-')[-1]}-{count:02d}"
        now = main.utc_now()
        next_state = "awaiting_approval" if payload.verdict == "pass" else ("blocked" if payload.verdict == "blocked" else "planning")
        db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)", (review_id, task_id, payload.reviewer_id, payload.verdict, payload.findings, now))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "review", task["state"], next_state, payload.reviewer_id, payload.findings or payload.verdict, json.dumps([payload.reviewer_id]), now))
        main.checkpoint(db, task_id, f"review:{payload.reviewer_id}")
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/approval")
def decide_approval(task_id: str, payload: ApprovalInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if task["state"] != "awaiting_approval":
            raise HTTPException(409, "Task is not awaiting approval")
        if not any(item["type"] == "lead_review" and item["status"] == "pass" for item in task["evidence"]):
            raise HTTPException(409, "Approval requires a passing lead review Job")
        if payload.decision == "approve":
            workspace_row = db.execute(
                "SELECT * FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if not workspace_row:
                raise HTTPException(409, "Approval requires a workspace containing the final deliverable")
            workspace, allowed, reason = main.validate_task_workspace(workspace_row)
            if not allowed:
                raise HTTPException(409, reason)
        count = db.execute("SELECT COUNT(*) FROM approvals WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        approval_id = f"APR-{task_id.split('-')[-1]}-{count:02d}"
        now = main.utc_now()
        next_state = {"approve": "completed", "rework": "planning", "reject": "cancelled"}[payload.decision]
        db.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?)", (approval_id, task_id, payload.decision, payload.reason, "USER", now))
        if payload.decision == "approve":
            try:
                main.assert_completion_invariants(db, task_id, workspace)
            except RuntimeError as error:
                raise HTTPException(409, str(error)) from error
            db.execute(
                "UPDATE deliverables SET status = CASE "
                "WHEN status = 'final_candidate' THEN 'approved' ELSE 'rendered_approved' END, updated_at = ? "
                "WHERE task_id = ? AND status IN ('final_candidate', 'rendered_candidate')",
                (now, task_id),
            )
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "approval_decision", task["state"], next_state, "USER", payload.reason or payload.decision, json.dumps([]), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/reflection")
def create_reflection(task_id: str, payload: ReflectionInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        count = db.execute("SELECT COUNT(*) FROM reflections WHERE task_id = ?", (task_id,)).fetchone()[0] + 1
        reflection_id = f"RFL-{task_id.split('-')[-1]}-{count:02d}"
        now = main.utc_now()
        db.execute("INSERT INTO reflections VALUES (?, ?, ?, ?, ?, ?)", (reflection_id, task_id, payload.summary, json.dumps(payload.root_causes), json.dumps(payload.improvements), now))
        lesson_id = None
        if payload.lesson.strip():
            lesson_id = f"LES-{task_id.split('-')[-1]}-{count:02d}"
            db.execute("INSERT INTO lessons VALUES (?, ?, ?, ?, ?)", (lesson_id, task_id, payload.lesson.strip(), reflection_id, now))
        next_state = task["state"] if task["state"] in {"completed", "cancelled"} else "reflecting"
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "reflection", task["state"], next_state, "NAVI", payload.summary, json.dumps(["NAVI"]), now))
        result = main.task_payload(db, task_id)
        return result | {"reflection_id": reflection_id, "lesson_id": lesson_id}


@router.post("/api/tasks/{task_id}/command")
def command(task_id: str, payload: Command) -> dict:
    known = main.registry()
    unknown = sorted(set(payload.employee_ids) - set(known))
    if unknown:
        raise HTTPException(422, f"Unknown employees: {', '.join(unknown)}")
    with main.database() as db:
        task = main.task_payload(db, task_id)
        previous = task["state"]
        state = main.ACTION_TO_STATE[payload.action]
        selected = payload.employee_ids or task["assigned_employees"]
        if payload.action in {"meeting", "assign", "run", "team_review", "cross_review", "verify", "approval"} and not selected:
            raise HTTPException(409, "Select at least one employee before this command")
        if payload.action == "complete":
            workspace_row = db.execute(
                "SELECT * FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if not workspace_row:
                raise HTTPException(409, "Completion requires a workspace containing the final deliverable")
            workspace, allowed, reason = main.validate_task_workspace(workspace_row)
            if not allowed:
                raise HTTPException(409, reason)
            try:
                main.assert_completion_invariants(db, task_id, workspace)
            except RuntimeError as error:
                raise HTTPException(409, str(error)) from error
        if payload.employee_ids:
            db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task_id,))
            db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task_id, employee) for employee in selected])
        now = main.utc_now()
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (task_id, payload.action, previous, state, "NAVI", payload.note or main.STATE_LABELS[state], json.dumps(selected), now))
        return main.task_payload(db, task_id)


@router.post("/api/tasks/{task_id}/runs")
def run_command(task_id: str, payload: RunInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "TaskContract required before command execution")
        workspace = db.execute("SELECT * FROM workspaces WHERE id = ? AND task_id = ?", (payload.workspace_id, task_id)).fetchone()
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        workspace_path, safe_path, path_reason = main.validate_task_workspace(workspace)
        safe_command, command_reason = main.validate_command(payload.command, task["contract"]["allowed_commands"])
        now = main.utc_now()
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


@router.post("/api/tasks/{task_id}/retry")
def retry(task_id: str, payload: RetryInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "TaskContract required before retry")
        attempts = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE task_id = ?", (task_id,)).fetchone()[0]
        prior_hashes = {
            row[0] for row in db.execute(
                "SELECT strategy_sha256 FROM retry_attempts WHERE task_id = ? AND failure_class = ?",
                (task_id, payload.failure_class),
            )
        }
        strategy = payload.strategy
        if strategy is None:
            strategy = next(
                (
                    candidate for candidate in main.RETRY_PLAYBOOK[payload.failure_class]
                    if hashlib.sha256(candidate.encode()).hexdigest() not in prior_hashes
                ),
                None,
            )
            if strategy is None:
                strategy = "retry-playbook-exhausted"
        strategy_hash = hashlib.sha256(strategy.encode()).hexdigest()
        repeated = db.execute("SELECT COUNT(*) FROM retry_attempts WHERE task_id = ? AND failure_class = ? AND strategy_sha256 = ?", (task_id, payload.failure_class, strategy_hash)).fetchone()[0]
        state = "escalated" if attempts >= task["contract"]["retry_limit"] or repeated or strategy == "retry-playbook-exhausted" else "planning"
        now = main.utc_now(); status = "escalated" if state == "escalated" else "retrying"
        db.execute(
            "INSERT INTO retry_attempts (task_id, failure_class, strategy_sha256, status, created_at, strategy) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, payload.failure_class, strategy_hash, status, now, strategy),
        )
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task_id))
        db.execute("INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, "escalate" if state == "escalated" else "retry", task["state"], state, "NAVI", f"{payload.failure_class}:{strategy}", json.dumps(task["assigned_employees"]), now))
        return main.task_payload(db, task_id)


@router.get("/api/tasks/{task_id}/office")
def office(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        return {"task": task, "employees": main.office_projection(task)}
