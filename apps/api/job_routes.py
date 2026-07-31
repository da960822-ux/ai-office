"""Durable Job queueing and control endpoints.

Extracted verbatim from ``apps/api/main.py``. Queues the plan / meeting / execute
/ lead-review Jobs and handles pause, cancel, resume and retry.

Helpers are reached through ``main.<name>`` so ``patch.object(main, ...)`` in the
test suite still applies - see ``admin_routes`` for the full rationale.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import main
from apps.api.api_models import (
    JobControlInput,
    JobInput,
)

router = APIRouter()


@router.post("/api/tasks/{task_id}/jobs/plan", status_code=202)
def queue_plan(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if not task["contract"]:
            raise HTTPException(409, "Create TaskContract before planning")
        if any(job["state"] in {"queued", "running", "pause_requested"} and job["kind"] == "plan" for job in task["jobs"]):
            raise HTTPException(409, "Planning job is already active")
        job = main.enqueue_job(db, task_id, "direct_plan" if task.get("route") == "direct_lead" else "plan", {"lead_id": task.get("lead_id")})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("planning", main.utc_now(), task_id))
        return job | {"task": main.task_payload(db, task_id)}


@router.post("/api/tasks/{task_id}/jobs/meeting", status_code=202)
def queue_meeting(task_id: str, payload: JobInput) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if any(job["kind"] == "meeting" and job["state"] in {"queued", "running", "pause_requested", "cancel_requested"} for job in task["jobs"]):
            raise HTTPException(409, "A meeting Job is already active")
        meeting = next((item for item in task["meetings"] if item["id"] == payload.meeting_id and item["status"] == "active"), None)
        if not meeting:
            raise HTTPException(409, "Select leads and create an active meeting first")
        job = main.enqueue_job(db, task_id, "meeting", {"meeting_id": meeting["id"], "participants": meeting["participants"]})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("meeting_running", main.utc_now(), task_id))
        return job | {"task": main.task_payload(db, task_id)}


@router.post("/api/tasks/{task_id}/jobs/execute", status_code=202)
def queue_execution(task_id: str, payload: JobInput) -> dict:
    if not payload.workspace_id or not payload.employee_ids:
        raise HTTPException(422, "workspace_id and employee_ids are required")
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if any(job["kind"] == "execute" and job["state"] in {"queued", "running", "pause_requested", "cancel_requested"} for job in task["jobs"]):
            raise HTTPException(409, "An execution Job is already active")
        if task["state"] not in {"awaiting_worker_selection", "assigned", "executing"}:
            raise HTTPException(409, "Task is not ready for worker execution")
        unknown = set(payload.employee_ids) - set(task["assigned_employees"])
        if unknown:
            raise HTTPException(403, f"Workers are not assigned: {', '.join(sorted(unknown))}")
        job = main.enqueue_job(db, task_id, "execute", {"workspace_id": payload.workspace_id, "employee_ids": payload.employee_ids, "instruction": payload.instruction})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("executing", main.utc_now(), task_id))
        return job | {"task": main.task_payload(db, task_id)}


@router.post("/api/tasks/{task_id}/jobs/review", status_code=202)
def queue_lead_review(task_id: str) -> dict:
    with main.database() as db:
        task = main.task_payload(db, task_id)
        if any(job["kind"] == "lead_review" and job["state"] in {"queued", "running", "pause_requested", "cancel_requested"} for job in task["jobs"]):
            raise HTTPException(409, "A lead review Job is already active")
        if not any(item["status"] == "pass" for item in task["evidence"]):
            raise HTTPException(409, "Lead review requires passing Evidence")
        if not any(item["status"] == "final_candidate" for item in task["deliverables"]):
            raise HTTPException(409, "Lead review requires an actual final_candidate file")
        lead = task.get("lead_id") or next((employee for employee in task["assigned_employees"] if employee in main.LEAD_IDS and employee != "NAVI"), None)
        if not lead:
            raise HTTPException(409, "No responsible team lead")
        workspace = db.execute("SELECT id FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if not workspace:
            raise HTTPException(409, "Lead review requires a workspace")
        reviewer = "NAVI"
        job = main.enqueue_job(db, task_id, "lead_review", {"lead_id": lead, "reviewer_id": reviewer, "workspace_id": workspace["id"]})
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("lead_review_running", main.utc_now(), task_id))
        return job | {"task": main.task_payload(db, task_id)}


@router.post("/api/jobs/{job_id}/control")
def control_job(job_id: str, payload: JobControlInput) -> dict:
    with main.database() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        target = {"pause": "pause_requested", "cancel": "cancel_requested", "resume": "queued"}[payload.action]
        if payload.action == "resume" and job["state"] not in {"paused", "interrupted"}:
            raise HTTPException(409, "Only paused or interrupted jobs can resume")
        db.execute("UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?", (target, main.utc_now(), job_id))
        if payload.action == "pause":
            task = db.execute("SELECT state FROM tasks WHERE id = ?", (job["task_id"],)).fetchone()
            if task:
                db.execute("INSERT INTO task_controls (task_id, state_before_pause, pause_requested, cancel_requested, updated_at) VALUES (?, ?, 1, 0, ?) ON CONFLICT(task_id) DO UPDATE SET state_before_pause=excluded.state_before_pause, pause_requested=1, cancel_requested=0, updated_at=excluded.updated_at", (job["task_id"], task["state"], main.utc_now()))
        elif payload.action == "resume":
            resume_state = {"plan": "planning", "direct_plan": "planning", "meeting": "meeting_running", "execute": "executing", "synthesize": "synthesizing", "lead_review": "lead_review_running"}.get(job["kind"], "planning")
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (resume_state, main.utc_now(), job["task_id"]))
            db.execute("UPDATE task_controls SET pause_requested = 0, updated_at = ? WHERE task_id = ?", (main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], f"job.{payload.action}_requested", f"{payload.action} 요청", job_id=job_id)
        return dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


@router.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str) -> dict:
    with main.database() as db:
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
            "synthesize": "synthesizing",
            "lead_review": "lead_review_running",
        }.get(job["kind"], "planning")
        now = main.utc_now()
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
        main.emit_job_event(db, job["task_id"], "job.retry_queued", "실패한 단계부터 Job을 다시 시작합니다.", job_id=job_id)
        return dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
