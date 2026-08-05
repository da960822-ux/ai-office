"""Single local durable worker for AI Office jobs.

The API only enqueues work. This process leases one SQLite job at a time and
commits observable events between every safe execution step.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import traceback
from datetime import timedelta
from multiprocessing import Process
from threading import Event, Thread

from apps.api import main
from apps.api import agent_worktree
from apps.api.artifact_renderer import formats_for_request

WORKER_ID = f"local-worker-{os.getpid()}"
WORKER_CONCURRENCY = max(1, min(int(os.getenv("AI_OFFICE_WORKER_CONCURRENCY", "4")), 8))
WORKER_MODE = os.getenv("AI_OFFICE_WORKER_MODE", "process").strip().lower()


def workspace_supports_parallel_worktrees(path: str) -> bool:
    """Only parallelize when every agent can receive an isolated clean worktree."""
    try:
        root = main.Path(path).resolve()
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return dirty.returncode == 0 and not dirty.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False


def review_and_integrate_worktree(job: dict, employee_id: str, agent_workspace: dict, pending: dict) -> dict:
    """Independent reviewer must pass agent commit before base branch changes."""
    if not pending.get("isolated"):
        return {"isolated": False, "integrated": False, "reason": pending.get("reason", "not_git")}
    if not pending.get("changed"):
        return agent_worktree.integrate_reviewed(agent_workspace, pending.get("commit"))
    reviewer = "LENS" if employee_id == "GUARD" else "GUARD"
    role = main.agent_role(reviewer)
    with main.database() as db:
        model = main.task_model_assignment(db, job["task_id"], reviewer)["model"]
    response = main.cancellable_model_response(
        main.model_client(),
        job["task_id"],
        job["id"],
        model=model,
        instructions=(
            "Review this isolated agent Git diff. You are independent reviewer, not author. "
            "Pass only if change is scoped, safe, and has no obvious correctness/security regression. "
            "Return strict JSON only: {\"verdict\":\"pass|changes_requested|blocked\",\"findings\":\"Korean actionable review\"}."
        ),
        input=json.dumps({"employee_id": employee_id, "commit": pending["commit"], "diff": pending.get("diff", "")}, ensure_ascii=False),
    )
    raw = response.output_text.strip()
    try:
        decision = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        verdict = decision.get("verdict", "changes_requested")
        findings = str(decision.get("findings", raw))
    except Exception:
        verdict, findings = "changes_requested", raw
    if verdict not in {"pass", "changes_requested", "blocked"}:
        verdict = "changes_requested"
    with main.database() as db:
        number = db.execute("SELECT COUNT(*) FROM integration_reviews WHERE task_id = ?", (job["task_id"],)).fetchone()[0] + 1
        review_id = f"IREV-{job['task_id'].split('-')[-1]}-{number:03d}"
        db.execute(
            "INSERT INTO integration_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, job["task_id"], employee_id, reviewer, pending["commit"], verdict, findings[:4000], main.utc_now()),
        )
        review_hash = main.hashlib.sha256((pending["commit"] + findings).encode()).hexdigest()
        db.execute(
            "INSERT OR REPLACE INTO evidence VALUES (?, ?, NULL, 'integration_review', ?, ?, 0, ?)",
            (f"EVD-{job['task_id'].split('-')[-1]}-IREV-{review_hash[:12]}", job["task_id"], "pass" if verdict == "pass" else "fail", review_hash, main.utc_now()),
        )
        main.emit_job_event(
            db, job["task_id"], "integration.review_completed", findings[:800],
            job_id=job["id"], agent_id=reviewer,
            payload={"employee_id": employee_id, "commit": pending["commit"], "verdict": verdict},
        )
    if verdict != "pass":
        raise RuntimeError(f"Independent worktree review {verdict}: {findings[:1000]}")
    return agent_worktree.integrate_reviewed(agent_workspace, pending["commit"])


def queue_ready_agent_jobs(db: sqlite3.Connection, task: dict) -> list[dict]:
    """Queue one independent Job per ready owner; dependencies form waves."""
    active_owners: set[str] = set()
    for row in db.execute(
        "SELECT payload FROM jobs WHERE task_id = ? AND kind = 'execute' "
        "AND state IN ('queued','running','pause_requested','cancel_requested')",
        (task["id"],),
    ):
        active_owners.update(json.loads(row["payload"]).get("employee_ids", []))
    completed = {
        phase["phase_id"]
        for phase in task["phases"]
        if phase["status"] in {"completed", "skipped"}
        and (phase["artifact_ids"] or phase["status"] == "skipped")
    }
    pending = [
        phase for phase in task["phases"]
        if phase["status"] in {"planned", "proposed"}
    ]
    delegated_parents = {phase["parent_phase_id"] for phase in pending if phase["parent_phase_id"]}
    pending_by_owner: dict[str, list[dict]] = {}
    for phase in pending:
        if phase["phase_id"] not in delegated_parents:
            pending_by_owner.setdefault(phase["owner_id"], []).append(phase)
    workspace = db.execute(
        "SELECT id, path FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    if not workspace:
        return []
    parallel_safe = workspace_supports_parallel_worktrees(workspace["path"])
    if not parallel_safe and active_owners:
        return []
    job_limit = len(pending_by_owner) if parallel_safe else 1
    jobs = []
    for owner, phases in pending_by_owner.items():
        dependencies = {item for phase in phases for item in phase["dependencies"]}
        if owner in active_owners or not dependencies.issubset(completed):
            continue
        jobs.append(
            main.enqueue_job(
                db,
                task["id"],
                "execute",
                {
                    "workspace_id": workspace["id"],
                    "employee_ids": [owner],
                    "instruction": task["request"],
                    "parallel_wave": True,
                },
            )
        )
        if len(jobs) >= job_limit:
            break
    if jobs:
        db.execute("UPDATE tasks SET state = 'executing', updated_at = ? WHERE id = ?", (main.utc_now(), task["id"]))
        main.emit_job_event(
            db,
            task["id"],
            "delegation.parallel_wave",
            f"{len(jobs)} independent agent Jobs queued",
            payload={"job_ids": [job["id"] for job in jobs]},
        )
    return jobs

def team_worker_candidates(lead_ids: list[str], include_lead: bool = False) -> list[tuple[str, str]]:
    people = main.registry()
    teams = {people[lead]["team"] for lead in lead_ids if lead in people}
    candidates = [(employee_id, f"{people[employee_id]['title']} · 팀장 제안 실행자") for employee_id in people if people[employee_id]["team"] in teams and employee_id not in main.LEAD_IDS]
    if include_lead:
        candidates = [(lead, "팀장 직접 실행 · 별도 팀장 리뷰 필수") for lead in lead_ids] + candidates
    return candidates


def worker_candidates_for_lead(lead_id: str, request: str = "") -> list[tuple[str, str]]:
    people = main.registry()
    if lead_id not in people:
        return []
    team = people[lead_id]["team"]
    candidates = [(employee_id, people[employee_id]["title"]) for employee_id in people if people[employee_id]["team"] == team and employee_id not in main.LEAD_IDS]
    return candidates


def heartbeat() -> None:
    with main.database() as db:
        db.execute("INSERT OR REPLACE INTO worker_heartbeats (worker_id, build_id, heartbeat_at) VALUES (?, ?, ?)", (WORKER_ID, main.BUILD_ID, main.utc_now()))


def maintain_job_lease(job: dict, stop: Event) -> None:
    """Keep a long model/tool call observable without imposing a generation deadline."""
    last_event = 0.0
    while not stop.wait(2):
        try:
            with main.database() as db:
                row = db.execute("SELECT state, step FROM jobs WHERE id = ?", (job["id"],)).fetchone()
                if not row or row["state"] not in {"running", "pause_requested", "cancel_requested"}:
                    return
                now = main.utc_now()
                lease_until = (main.datetime.now(main.timezone.utc) + timedelta(seconds=45)).isoformat()
                db.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (now, job["id"]))
                db.execute("INSERT OR REPLACE INTO job_leases (job_id, worker_id, heartbeat_at, lease_until) VALUES (?, ?, ?, ?)", (job["id"], WORKER_ID, now, lease_until))
                db.execute("INSERT OR REPLACE INTO worker_heartbeats (worker_id, build_id, heartbeat_at) VALUES (?, ?, ?)", (WORKER_ID, main.BUILD_ID, now))
                if time.monotonic() - last_event >= 15:
                    main.emit_job_event(db, job["task_id"], "job.heartbeat", "현재 모델·도구 호출이 응답 중입니다.", job_id=job["id"], payload={"step": row["step"], "state": row["state"]})
                    last_event = time.monotonic()
        except sqlite3.OperationalError:
            # A short SQLite writer overlap is not a dead worker. Retry next tick.
            continue


def recover_orphaned_jobs() -> None:
    """Never leave a job visually running after its owning worker was restarted."""
    with main.database() as db:
        rows = db.execute(
            "SELECT id, task_id FROM jobs WHERE state IN ('running', 'pause_requested', 'cancel_requested') "
            "AND lease_owner IS NOT NULL AND lease_owner != ?",
            (WORKER_ID,),
        ).fetchall()
        for row in rows:
            db.execute("UPDATE jobs SET state = 'interrupted', error = ?, updated_at = ? WHERE id = ?", ("Worker restarted during model call; retry required", main.utc_now(), row["id"]))
            db.execute("DELETE FROM job_leases WHERE job_id = ?", (row["id"],))
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state NOT IN ('cancelled', 'completed')", ("blocked", main.utc_now(), row["task_id"]))
            db.execute(
                "UPDATE agent_runs SET state = 'interrupted', finished_at = ? "
                "WHERE job_id = ? AND state = 'running'",
                (main.utc_now(), row["id"]),
            )
            db.execute(
                "UPDATE agent_sessions SET state = 'interrupted', updated_at = ? "
                "WHERE task_id = ? AND employee_id IN "
                "(SELECT employee_id FROM agent_runs WHERE job_id = ?)",
                (main.utc_now(), row["task_id"], row["id"]),
            )
            main.emit_job_event(db, row["task_id"], "job.interrupted", "worker 재시작으로 현재 모델 호출을 중단했습니다. 재시도해야 합니다.", job_id=row["id"])

def schedule_lead_selection() -> None:
    """Auto-approve NAVI's proposed leads so awaiting_lead_selection doesn't need a human click.
    Mirrors task_routes.select_leads, minus the CEO's ability to drop a proposed lead."""
    with main.database() as db:
        rows = db.execute("SELECT id FROM tasks WHERE state = 'awaiting_lead_selection'").fetchall()
        for row in rows:
            task = main.task_payload(db, row["id"])
            if any(job["state"] in {"queued", "running", "pause_requested"} for job in task["jobs"]):
                continue
            selected = [employee for employee in task["assigned_employees"] if employee in main.LEAD_IDS and employee != "NAVI"]
            if not selected:
                db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), task["id"]))
                main.emit_job_event(db, task["id"], "delegation.blocked", "제안된 팀장 후보가 없습니다.")
                continue
            now = main.utc_now()
            meeting_id = f"MEET-{task['id'].split('-')[-1]}-LEADS"
            participants = ["NAVI", *selected]
            db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task["id"],))
            db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task["id"], employee) for employee in selected])
            db.execute(
                "INSERT OR REPLACE INTO meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (meeting_id, task["id"], "lead_dispatch", "NAVI-led: selected department leads decide scope, risks, worker delegation", json.dumps(participants), json.dumps(["scope", "risk", "worker roles", "acceptance"]), json.dumps([]), "active", now),
            )
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("meeting_running", now, task["id"]))
            meeting_job = main.enqueue_job(db, task["id"], "meeting", {"meeting_id": meeting_id, "participants": participants})
            db.execute(
                "INSERT INTO events (task_id, action, from_state, to_state, actor, note, employee_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task["id"], "lead_selection", task["state"], "meeting_running", "NAVI", "제안된 팀장 후보 전원 자동 승인; 자율 회의 시작", json.dumps(participants), now),
            )
            main.emit_job_event(db, task["id"], "meeting.queued", "팀장 후보를 자동 승인해 회의 Job을 시작했습니다.", job_id=meeting_job["id"], agent_id="NAVI", payload={"participants": participants})


def schedule_autonomous_tasks() -> None:
    """After user approves lead candidates, remaining delegation/execution is autonomous."""
    with main.database() as db:
        rows = db.execute("SELECT id FROM tasks WHERE state = 'awaiting_worker_selection'").fetchall()
        for row in rows:
            task = main.task_payload(db, row["id"])
            if any(job["state"] in {"queued", "running", "pause_requested"} for job in task["jobs"]):
                continue
            workspace = db.execute("SELECT id FROM workspaces WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task["id"],)).fetchone()
            if not workspace:
                continue
            leads = [employee for employee in task["assigned_employees"] if employee in main.LEAD_IDS and employee != "NAVI"]
            proposed = [item["owner"] for item in task["action_items"]]
            execution_ids = list(dict.fromkeys(proposed or leads))
            if not execution_ids:
                db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), task["id"]))
                main.emit_job_event(db, task["id"], "delegation.blocked", "팀장 제안 실행자가 없습니다.")
                continue
            assignments = list(dict.fromkeys(leads + execution_ids))
            db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task["id"],))
            db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task["id"], employee) for employee in assignments])
            jobs = queue_ready_agent_jobs(db, main.task_payload(db, task["id"]))
            if not jobs and not task["phases"]:
                jobs = [
                    main.enqueue_job(
                        db,
                        task["id"],
                        "execute",
                        {
                            "workspace_id": workspace["id"],
                            "employee_ids": execution_ids,
                            "instruction": task["request"],
                        },
                    )
                ]
                db.execute("UPDATE tasks SET state = 'executing', updated_at = ? WHERE id = ?", (main.utc_now(), task["id"]))
            main.emit_job_event(db, task["id"], "delegation.auto_assigned", "팀장 분배안을 승인해 실행 Job을 자동 시작합니다.", job_id=jobs[0]["id"] if jobs else None, payload={"workers": execution_ids, "jobs": [item["id"] for item in jobs]})

def schedule_ready_phase_jobs() -> None:
    with main.database() as db:
        rows = db.execute("SELECT id FROM tasks WHERE state = 'executing'").fetchall()
        for row in rows:
            queue_ready_agent_jobs(db, main.task_payload(db, row["id"]))


def reconcile_failed_jobs() -> None:
    with main.database() as db:
        db.execute("UPDATE jobs SET state = 'cancelled', updated_at = ? WHERE state = 'cancel_requested' AND task_id IN (SELECT id FROM tasks WHERE state IN ('cancelled','blocked'))", (main.utc_now(),))
        duplicate_meetings = db.execute("SELECT task_id, id FROM jobs WHERE kind = 'meeting' AND state = 'failed' AND error = 'Active meeting not found'").fetchall()
        for duplicate in duplicate_meetings:
            completed = db.execute("SELECT 1 FROM jobs WHERE task_id = ? AND kind = 'meeting' AND state = 'succeeded'", (duplicate["task_id"],)).fetchone()
            executed = db.execute("SELECT 1 FROM jobs WHERE task_id = ? AND kind = 'execute'", (duplicate["task_id"],)).fetchone()
            if completed and not executed:
                db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state = 'blocked'", ("awaiting_worker_selection", main.utc_now(), duplicate["task_id"]))
                main.emit_job_event(db, duplicate["task_id"], "meeting.recovered", "중복 회의 Job 실패를 무시하고, 완료된 회의의 팀장 분배안으로 자동 실행을 재개합니다.", job_id=duplicate["id"])
        rows = db.execute("SELECT id, task_id, error FROM jobs WHERE state = 'failed'").fetchall()
        for row in rows:
            task = db.execute("SELECT state FROM tasks WHERE id = ?", (row["task_id"],)).fetchone()
            if task and task["state"] in {"executing", "meeting_running", "synthesizing", "lead_review_running"}:
                db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), row["task_id"]))
                main.emit_job_event(db, row["task_id"], "task.blocked", f"실행 Job 실패: {row['error'] or '원인 미상'}. 재시도 또는 모델 설정을 확인하세요.", job_id=row["id"])


def claim_job() -> dict | None:
    with main.database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM jobs WHERE state = 'queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        now = main.utc_now()
        db.execute("UPDATE jobs SET state = 'running', lease_owner = ?, heartbeat_at = ?, updated_at = ? WHERE id = ? AND state = 'queued'", (WORKER_ID, now, now, row["id"]))
        db.execute("INSERT OR REPLACE INTO job_leases (job_id, worker_id, heartbeat_at, lease_until) VALUES (?, ?, ?, ?)", (row["id"], WORKER_ID, now, (main.datetime.now(main.timezone.utc) + timedelta(seconds=45)).isoformat()))
        job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())
        job["payload"] = json.loads(job["payload"])
        main.emit_job_event(db, job["task_id"], "job.started", f"{job['kind']} 작업 시작", job_id=job["id"], payload={"kind": job["kind"]})
        return job


def set_job(job: dict, state: str, summary: str, error: str | None = None) -> None:
    with main.database() as db:
        now = main.utc_now()
        error_class = main.classify_error(error) if state == "failed" else None
        db.execute("UPDATE jobs SET state = ?, error = ?, error_class = ?, heartbeat_at = ?, updated_at = ? WHERE id = ?", (state, error, error_class, now, now, job["id"]))
        db.execute("DELETE FROM job_leases WHERE job_id = ?", (job["id"],))
        main.emit_job_event(db, job["task_id"], f"job.{state}", summary, job_id=job["id"])


def safe_point(job: dict) -> bool:
    with main.database() as db:
        row = db.execute("SELECT state FROM jobs WHERE id = ?", (job["id"],)).fetchone()
        if not row:
            return False
        if row["state"] == "cancel_requested":
            db.execute("UPDATE jobs SET state = 'cancelled', updated_at = ? WHERE id = ?", (main.utc_now(), job["id"]))
            db.execute("UPDATE tasks SET state = 'cancelled', updated_at = ? WHERE id = ?", (main.utc_now(), job["task_id"]))
            main.emit_job_event(db, job["task_id"], "job.cancelled", "현재 안전 지점에서 작업 취소", job_id=job["id"])
            return False
        if row["state"] == "pause_requested":
            db.execute("UPDATE jobs SET state = 'paused', updated_at = ? WHERE id = ?", (main.utc_now(), job["id"]))
            db.execute("UPDATE tasks SET state = 'paused', updated_at = ? WHERE id = ?", (main.utc_now(), job["task_id"]))
            main.emit_job_event(db, job["task_id"], "job.paused", "현재 안전 지점에서 작업 정지", job_id=job["id"])
            return False
        db.execute("UPDATE jobs SET heartbeat_at = ?, updated_at = ? WHERE id = ?", (main.utc_now(), main.utc_now(), job["id"]))
        return True


def record_step(db: sqlite3.Connection, job: dict, step: int, name: str, state: str, detail: str) -> None:
    db.execute("INSERT INTO job_steps (job_id, step, name, state, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)", (job["id"], step, name, state, detail[:1000], main.utc_now()))
    db.execute("UPDATE jobs SET step = ?, updated_at = ? WHERE id = ?", (step, main.utc_now(), job["id"]))


def process_plan(job: dict) -> None:
    with main.database() as db:
        task = main.task_payload(db, job["task_id"])
        record_step(db, job, 1, "route", "running", "NAVI/팀장 범위 판단")
        main.emit_job_event(db, job["task_id"], "model.started", "업무 범위와 필요한 팀을 판단 중", job_id=job["id"], agent_id=task.get("lead_id") or "NAVI")
    if job["kind"] == "direct_plan":
        roster = [job["payload"]["lead_id"]]
        candidates = worker_candidates_for_lead(roster[0], task["request"])
        items = [(candidates[0][0], f"{candidates[0][1]} · 팀장 자동 배정") ] if candidates else [(roster[0], "팀장 직접 실행 · 별도 리뷰 필수")]
        reason = "대표가 선택한 팀장이 소규모 업무를 판단합니다."
        usage = None
    else:
        try:
            roster, items, reason, usage = main.select_roster_with_model(task["request"], job["task_id"], job["id"])
        except Exception as error:
            fallback, _ = main.planned_roster(task["request"])
            roster = [employee for employee in fallback if employee in main.LEAD_IDS and employee != "NAVI"][:3] or ["FRAME"]
            items = [(employee, "팀 범위와 worker 제안") for employee in roster]
            reason, usage = f"모델 판단 실패, 안전한 규칙 기반 후보 사용: {error}", None
    if not safe_point(job):
        return
    with main.database() as db:
        main.require_skill_ready(roster, task["request"])
        execution_plan = usage.get("plan") if usage and usage.get("plan") else main.fallback_execution_plan(roster, items)
        main.store_execution_plan(db, job["task_id"], execution_plan)
        db.execute("DELETE FROM task_assignments WHERE task_id = ?", (job["task_id"],))
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(job["task_id"], employee) for employee in roster])
        db.execute("DELETE FROM action_items WHERE task_id = ?", (job["task_id"],))
        contract = main.task_payload(db, job["task_id"])["contract"]
        for index, (owner, description) in enumerate(items, 1):
            db.execute("INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"ACT-{job['task_id'].split('-')[-1]}-{index:02d}", job["task_id"], None, owner, description, index, json.dumps(contract["acceptance_criteria"]), "planned"))
        next_state = "awaiting_worker_selection" if job["kind"] == "direct_plan" else "awaiting_lead_selection"
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, main.utc_now(), job["task_id"]))
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (job["task_id"], task.get("lead_id") or "NAVI", "dispatch", reason, main.utc_now()))
        if usage:
            main.record_usage(db, job["task_id"], usage["model"], usage["input_tokens"], usage["output_tokens"])
        record_step(db, job, 2, "route", "succeeded", reason)
        main.emit_job_event(db, job["task_id"], "agent.completed", "팀장 후보와 업무 분해 생성", job_id=job["id"], agent_id=task.get("lead_id") or "NAVI", payload={"leads": roster})


def process_meeting(job: dict) -> None:
    with main.database() as db:
        meeting = db.execute("SELECT * FROM meetings WHERE id = ?", (job["payload"]["meeting_id"],)).fetchone()
        if not meeting or meeting["status"] != "active":
            raise RuntimeError("Active meeting not found")
        participants = json.loads(meeting["participants"]); agenda = json.loads(meeting["agenda"])
        task = main.task_payload(db, job["task_id"])
        for employee in participants:
            main.emit_job_event(db, job["task_id"], "agent.move", "회의실로 이동", job_id=job["id"], agent_id=employee, payload={"zone": "meeting", "action": "walk"})
    time.sleep(0.4)
    with main.database() as db:
        for employee in participants:
            main.emit_job_event(db, job["task_id"], "agent.at_location", "회의실 착석", job_id=job["id"], agent_id=employee, payload={"zone": "meeting", "action": "meeting"})
    transcript: list[str] = []
    worker_proposals: list[dict] = []
    for index, employee in enumerate(participants, 1):
        if not safe_point(job):
            return
        role = main.agent_role(employee)
        run_id = f"AR-{job['id']}-{index:02d}"
        with main.database() as db:
            model = main.task_model_assignment(db, job["task_id"], employee)["model"]
            existing = db.execute("SELECT state, summary FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if existing and existing["state"] == "succeeded":
                transcript.append(f"{employee}: {existing['summary'] or ''}")
                continue
            record_step(db, job, index, "meeting_speaker", "running", employee)
            main.emit_job_event(db, job["task_id"], "model.started", "회의 발언 준비", job_id=job["id"], agent_id=employee)
            db.execute("INSERT OR REPLACE INTO agent_runs (id, task_id, job_id, employee_id, state, model, started_at, finished_at, summary) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)", (run_id, job["task_id"], job["id"], employee, "running", model, main.utc_now()))
        available = worker_candidates_for_lead(employee, task["request"]) if employee != "NAVI" else []
        scope = next((item for item in task.get("agent_scopes", []) if item["employee_id"] == employee), None)
        selected_skill_ids = scope.get("skill_ids", []) if scope else []
        current_plan = task.get("execution_plan", {}).get("plan") if task.get("execution_plan") else {}
        lead_phase = next((phase for phase in current_plan.get("phases", []) if phase.get("lead_id") == employee), None)
        phase_task_kind = (lead_phase or {}).get("task_kind") or (
            main.default_task_kind(main.registry()[employee]["team"], employee) if employee != "NAVI" else "general"
        )
        skill_context = main.employee_skill_context(
            employee,
            task["request"],
            selected_skill_ids=selected_skill_ids,
            task_kind=phase_task_kind,
        ) if selected_skill_ids else {"required_skills": []}
        if available:
            boundary = main.department_policy(employee)
            instructions = (
                f"You are {employee}, {role['title']}. Discuss the actual task and delegate only necessary workers. "
                f"Your department owns: {boundary.get('owns', [])}. "
                f"Transfer these scopes instead of doing them here: {boundary.get('must_handoff', {})}. "
                "Reason from the execution plan and current evidence. A worker may be unnecessary. "
                "Return strict JSON: {\"message\":\"concise Korean decision\",\"assignments\":[{\"worker_id\":\"ID\",\"description\":\"specific work\",\"skill_ids\":[\"ID\"],\"deliverable\":\"file or evidence\",\"handoff_to\":\"ID\",\"depends_on\":[\"phase-id\"]}]}. "
                "Choose zero to two workers. Select a worker only when that worker's output is necessary for this phase; otherwise keep work with the lead. Use only available_workers. "
                "Choose zero to three skills from that worker's listed skills; choose only skills directly needed for this assignment. "
                "Never assign another department's worker or absorb another department's responsibility. Use only the supplied selected skill instructions when they are present."
            )
        else:
            instructions = f"You are {employee}, {role['title']}. Open this meeting with one concise Korean statement grounded in the actual request."
        client = main.model_client()
        response = main.cancellable_model_response(client, job["task_id"], job["id"], model=model, instructions=instructions, input=json.dumps({
            "task_request": task["request"],
            "execution_plan": task.get("execution_plan", {}).get("plan") if task.get("execution_plan") else None,
            "objective": meeting["objective"],
            "agenda": agenda,
            "prior": transcript,
            "selected_skill_instructions": skill_context["required_skills"],
            "available_workers": [
                {"id": worker_id, "title": title, "skills": main.employee_skill_pool(worker_id)}
                for worker_id, title in available
            ] if available else [],
        }, ensure_ascii=False))
        raw = response.output_text.strip(); usage = getattr(response, "usage", None)
        content = raw
        if available:
            try:
                parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
                content = str(parsed.get("message") or "").strip()
                allowed = {worker_id for worker_id, _ in available}
                for assignment in parsed.get("assignments", [])[:2]:
                    worker_id = assignment.get("worker_id")
                    description = str(assignment.get("description") or "").strip()
                    if worker_id in allowed and description:
                        bound = set(main.employee_skill_pool(worker_id))
                        skill_ids = [skill for skill in assignment.get("skill_ids", []) if skill in bound][:3]
                        try:
                            skill_ids = main.validate_selected_skills(
                                worker_id, skill_ids, 3, task_kind=phase_task_kind,
                            )
                        except main.HTTPException:
                            skill_ids = []
                        worker_proposals.append({
                            "worker_id": worker_id,
                            "proposer_id": employee,
                            "task_kind": phase_task_kind,
                            "description": description[:500],
                            "skill_ids": skill_ids,
                            "deliverable": str(assignment.get("deliverable") or "부서 초안")[:500],
                            "handoff_to": str(assignment.get("handoff_to") or employee)[:40],
                            "depends_on": [str(item)[:80] for item in assignment.get("depends_on", []) if isinstance(item, str)][:6],
                        })
            except Exception:
                content = raw
            if not any(item["worker_id"] in {candidate[0] for candidate in available} for item in worker_proposals):
                worker_proposals.append({
                    "worker_id": employee,
                    "proposer_id": employee,
                    "task_kind": phase_task_kind,
                    "description": f"{employee} 팀장 직접 재검토 범위",
                    "skill_ids": [],
                    "deliverable": "검증 가능한 부서 초안",
                    "handoff_to": employee,
                    "depends_on": [],
                })
        if not content:
            raise RuntimeError(f"Meeting model returned no statement: {employee}")
        if not safe_point(job):
            with main.database() as db:
                db.execute("UPDATE agent_runs SET state = 'interrupted', finished_at = ? WHERE id = ?", (main.utc_now(), run_id))
            return
        with main.database() as db:
            db.execute("UPDATE agent_runs SET state = 'succeeded', finished_at = ?, summary = ? WHERE id = ?", (main.utc_now(), content[:2000], run_id))
            db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (job["task_id"], employee, "meeting", content, main.utc_now()))
            main.record_usage(db, job["task_id"], model, getattr(usage, "input_tokens", 0) if usage else 0, getattr(usage, "output_tokens", 0) if usage else 0)
            record_step(db, job, index, "meeting_speaker", "succeeded", content)
            main.emit_job_event(db, job["task_id"], "meeting.message", content, job_id=job["id"], agent_id=employee, payload={"zone": "meeting", "action": "meeting"})
        transcript.append(f"{employee}: {content}")
    with main.database() as db:
        db.execute("UPDATE meetings SET status = ?, decisions = ? WHERE id = ?", ("concluded", json.dumps(["실제 모델 발언 기록 완료"], ensure_ascii=False), job["payload"]["meeting_id"]))
        leads = [employee for employee in participants if employee != "NAVI"]
        proposed_candidates = list({item["worker_id"]: item for item in worker_proposals}.values())
        plan = main.task_payload(db, job["task_id"]).get("execution_plan", {}).get("plan") or {}
        planned_candidates = [
            {
                "phase_id": phase["id"],
                "worker_id": phase["lead_id"], "description": phase["objective"],
                "task_kind": phase.get("task_kind") or main.default_task_kind(phase["department"]),
                "skill_ids": phase.get("skill_ids", []), "deliverable": phase["output"],
                "handoff_to": phase.get("handoff_to") or plan.get("final_owner") or phase["lead_id"],
                "depends_on": phase.get("depends_on", []),
                "source": "plan",
            }
            for phase in plan.get("phases", []) if phase.get("lead_id") in leads
        ]
        delegated_candidates = []
        for proposal_index, proposal in enumerate(proposed_candidates, 1):
            proposer_id = proposal.get("proposer_id") or proposal["handoff_to"]
            parent = next((item for item in planned_candidates if item["worker_id"] == proposer_id), None)
            phase_id = f"{parent['phase_id'] if parent else 'meeting'}-worker-{proposal_index}"[:80]
            proposal = proposal | {
                "phase_id": phase_id,
                "parent_phase_id": parent["phase_id"] if parent else None,
                "source": "meeting",
                "depends_on": list(dict.fromkeys([
                    *(parent["depends_on"] if parent else []),
                    *proposal.get("depends_on", []),
                ])),
                "task_kind": proposal.get("task_kind") or (parent or {}).get("task_kind") or "general",
            }
            delegated_candidates.append(proposal)
        # A valid lead delegation defines the execution roster. Planned lead
        # phases remain accountable integration records, not worker placeholders.
        candidates = delegated_candidates or planned_candidates
        if not candidates:
            candidates = [
                {
                    "phase_id": f"meeting-lead-{index}",
                    "worker_id": lead,
                    "task_kind": main.default_task_kind(main.registry()[lead]["team"], lead),
                    "description": f"{lead} 팀장 직접 재검토 범위",
                    "skill_ids": [],
                    "deliverable": "검증 가능한 부서 초안",
                    "handoff_to": lead,
                    "depends_on": [],
                    "source": "meeting",
                }
                for index, lead in enumerate(leads, 1)
            ]
        db.execute("DELETE FROM action_items WHERE task_id = ?", (job["task_id"],))
        db.execute("DELETE FROM task_agent_scopes WHERE task_id = ?", (job["task_id"],))
        contract = main.task_payload(db, job["task_id"])["contract"]
        for index, scope in enumerate(candidates, 1):
            owner, description = scope["worker_id"], scope["description"]
            if scope.get("source") == "meeting":
                parent_row = db.execute(
                    "SELECT sequence FROM task_phases WHERE task_id = ? AND phase_id = ?",
                    (job["task_id"], scope.get("parent_phase_id")),
                ).fetchone()
                sequence = max(1, (parent_row["sequence"] if parent_row else index * 100) - 10 + index)
                db.execute(
                    "INSERT OR REPLACE INTO task_phases "
                    "(task_id, phase_id, parent_phase_id, department, owner_id, task_kind, objective, expected_output, handoff_to, "
                    "dependencies, skill_ids, status, artifact_ids, source, sequence, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', '[]', 'meeting', ?, ?, ?)",
                    (
                        job["task_id"], scope["phase_id"], scope.get("parent_phase_id"),
                        main.registry()[owner]["team"], owner, scope.get("task_kind") or "general",
                        description, scope["deliverable"],
                        scope["handoff_to"], json.dumps(scope["depends_on"], ensure_ascii=False),
                        json.dumps(scope["skill_ids"], ensure_ascii=False), sequence, main.utc_now(), main.utc_now(),
                    ),
                )
            db.execute("INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"ACT-{job['task_id'].split('-')[-1]}-{index:02d}", job["task_id"], job["payload"]["meeting_id"], owner, description, index, json.dumps(contract["acceptance_criteria"]), "proposed"))
            db.execute(
                "INSERT INTO task_agent_scopes (task_id, employee_id, assignment, skill_ids, deliverable, handoff_to, dependencies, sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id, employee_id) DO UPDATE SET "
                "assignment=excluded.assignment, skill_ids=excluded.skill_ids, deliverable=excluded.deliverable, "
                "handoff_to=excluded.handoff_to, dependencies=excluded.dependencies, sequence=excluded.sequence",
                (
                    job["task_id"], owner, description, json.dumps(scope["skill_ids"], ensure_ascii=False),
                    scope["deliverable"], scope["handoff_to"], json.dumps(scope["depends_on"], ensure_ascii=False), index,
                ),
            )
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("awaiting_worker_selection", main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "meeting.completed", "팀장 회의 발언 기록 완료", job_id=job["id"], agent_id="NAVI")


def process_execute(job: dict) -> None:
    payload = job["payload"]
    with main.database() as db:
        phase_order = {
            row["owner_id"]: row["first_sequence"]
            for row in db.execute(
                "SELECT owner_id, MIN(sequence) AS first_sequence FROM task_phases "
                "WHERE task_id = ? AND status NOT IN ('completed','skipped') GROUP BY owner_id",
                (job["task_id"],),
            )
        }
    employees = sorted(
        dict.fromkeys(payload["employee_ids"]),
        key=lambda employee: (phase_order.get(employee, 1_000_000), payload["employee_ids"].index(employee)),
    )
    for index, employee in enumerate(employees, 1):
        if not safe_point(job):
            return
        with main.database() as db:
            model = main.task_model_assignment(db, job["task_id"], employee)["model"]
            assignment = db.execute("SELECT description FROM action_items WHERE task_id = ? AND owner = ? ORDER BY sequence LIMIT 1", (job["task_id"], employee)).fetchone()
            work_summary = assignment["description"] if assignment else "배정된 업무 수행"
            scope = db.execute("SELECT * FROM task_agent_scopes WHERE task_id = ? AND employee_id = ?", (job["task_id"], employee)).fetchone()
            skill_ids = json.loads(scope["skill_ids"]) if scope else []
            handoff = f"Handoff to {scope['handoff_to']}: {scope['deliverable']}" if scope else "Return a verifiable department contribution."
            employee_phases = list(db.execute(
                "SELECT * FROM task_phases WHERE task_id = ? AND owner_id = ? "
                "AND status NOT IN ('completed','skipped') ORDER BY sequence",
                (job["task_id"], employee),
            ))
            dependencies = list(dict.fromkeys(
                item
                for phase in employee_phases
                for item in json.loads(phase["dependencies"])
            ))
            missing_dependencies = []
            for dependency in dependencies:
                dependency_row = db.execute(
                    "SELECT status, artifact_ids FROM task_phases WHERE task_id = ? AND phase_id = ?",
                    (job["task_id"], dependency),
                ).fetchone()
                if (
                    not dependency_row
                    or dependency_row["status"] != "completed"
                    or not json.loads(dependency_row["artifact_ids"])
                ):
                    missing_dependencies.append(dependency)
            if missing_dependencies:
                detail = f"Missing upstream phase artifacts: {', '.join(missing_dependencies)}"
                db.execute("UPDATE tasks SET state = 'blocked', updated_at = ? WHERE id = ?", (main.utc_now(), job["task_id"]))
                db.execute("UPDATE action_items SET status = 'blocked' WHERE task_id = ? AND owner = ?", (job["task_id"], employee))
                main.emit_job_event(
                    db, job["task_id"], "phase.blocked", detail,
                    job_id=job["id"], agent_id=employee,
                    payload={"missing_dependencies": missing_dependencies},
                )
                return
            db.execute(
                "UPDATE task_phases SET status = 'running', updated_at = ? "
                "WHERE task_id = ? AND owner_id = ? AND status NOT IN ('completed','skipped')",
                (main.utc_now(), job["task_id"], employee),
            )
            plan = main.task_payload(db, job["task_id"]).get("execution_plan", {}).get("plan") or {}
            phase_by_id = {phase["id"]: phase for phase in plan.get("phases", [])}
            dependency_owners = [phase_by_id[item]["lead_id"] for item in (json.loads(scope["dependencies"]) if scope else []) if item in phase_by_id]
            upstream = [item for item in main.task_payload(db, job["task_id"])["deliverables"] if item["owner"] in dependency_owners and item["status"] == "department_draft"]
            workspace_row = db.execute("SELECT path FROM workspaces WHERE id = ?", (payload["workspace_id"],)).fetchone()
            upstream_context = []
            for item in upstream:
                path = main.Path(workspace_row["path"]) / item["path"]
                if path.exists():
                    upstream_context.append({"owner": item["owner"], "path": item["path"], "content": path.read_text(encoding="utf-8", errors="replace")[:12000]})
            run_id = f"AR-{job['id']}-{index:02d}"
            existing = db.execute("SELECT state FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if existing and existing["state"] == "succeeded":
                continue
            db.execute("INSERT OR REPLACE INTO agent_runs (id, task_id, job_id, employee_id, state, model, started_at, finished_at, summary) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)", (run_id, job["task_id"], job["id"], employee, "running", model, main.utc_now()))
            db.execute("UPDATE action_items SET status = 'running' WHERE task_id = ? AND owner = ?", (job["task_id"], employee))
            record_step(db, job, index, "agent_run", "running", employee)
            main.emit_job_event(db, job["task_id"], "agent.move", "작업 위치로 이동", job_id=job["id"], agent_id=employee, payload={"zone": "desk", "action": "walk"})
            main.emit_job_event(db, job["task_id"], "agent.at_location", "작업 좌석 도착", job_id=job["id"], agent_id=employee, payload={"zone": "desk", "action": "work"})
            main.emit_job_event(db, job["task_id"], "model.started", work_summary, job_id=job["id"], agent_id=employee, payload={"zone": "desk", "action": "work"})
            isolated_workspace = agent_worktree.prepare(
                db,
                root=main.ROOT,
                task_id=job["task_id"],
                base_workspace_id=payload["workspace_id"],
                employee_id=employee,
                now=main.utc_now(),
            ) if payload.get("parallel_wave") else {
                "workspace_id": payload["workspace_id"],
                "path": main.Path(workspace_row["path"]),
                "isolated": False,
            }
        try:
            result = main.run_agent(
                job["task_id"],
                main.AgentRunInput(
                    workspace_id=isolated_workspace["workspace_id"],
                    employee_id=employee,
                    instruction=(
                        f"Original task:\n{payload.get('instruction', '')}\n\n"
                        f"Your bounded assignment:\n{work_summary}\n\n"
                        f"{handoff}\n\n"
                        f"Required upstream handoff inputs:\n{json.dumps(upstream_context, ensure_ascii=False)}\n\n"
                        "Use upstream inputs as constraints. Cite unresolved gaps; do not restart prior research or redefine approved upstream decisions.\n\n"
                        "Deliver only this bounded contribution. Do not choose or rewrite the final cross-department recommendation."
                    ),
                    skill_ids=skill_ids,
                    managed_by_job=True,
                    job_id=job["id"],
                ),
            )
            pending_integration = agent_worktree.commit_for_review(
                isolated_workspace,
                task_id=job["task_id"],
                employee_id=employee,
            )
            integration = review_and_integrate_worktree(
                job,
                employee,
                isolated_workspace,
                pending_integration,
            )
            if integration.get("isolated"):
                with main.database() as db:
                    db.execute(
                        "UPDATE workspaces SET status = 'integrated' WHERE id = ?",
                        (isolated_workspace["workspace_id"],),
                    )
                    main.emit_job_event(
                        db,
                        job["task_id"],
                        "agent.worktree_integrated",
                        f"{employee} worktree integrated",
                        job_id=job["id"],
                        agent_id=employee,
                        payload=integration,
                    )
        finally:
            if isolated_workspace.get("isolated"):
                agent_worktree.cleanup(
                    main.Path(isolated_workspace["base_path"]),
                    isolated_workspace,
                )
        if not safe_point(job):
            with main.database() as db:
                db.execute("UPDATE agent_runs SET state = 'interrupted', finished_at = ? WHERE id = ?", (main.utc_now(), run_id))
            return
        with main.database() as db:
            db.execute("UPDATE agent_runs SET state = 'succeeded', finished_at = ?, summary = ? WHERE id = ?", (main.utc_now(), result["summary"][:2000], run_id))
            db.execute("UPDATE action_items SET status = 'completed' WHERE task_id = ? AND owner = ?", (job["task_id"], employee))
            artifact_ids = json.dumps([result["deliverable"]["id"]], ensure_ascii=False)
            completed_phases = list(db.execute(
                "SELECT phase_id, parent_phase_id FROM task_phases WHERE task_id = ? AND owner_id = ? AND status = 'running'",
                (job["task_id"], employee),
            ))
            db.execute(
                "UPDATE task_phases SET status = 'completed', artifact_ids = ?, updated_at = ? "
                "WHERE task_id = ? AND owner_id = ? AND status = 'running'",
                (artifact_ids, main.utc_now(), job["task_id"], employee),
            )
            for phase in completed_phases:
                if phase["parent_phase_id"]:
                    db.execute(
                        "UPDATE task_phases SET status = 'completed', artifact_ids = ?, updated_at = ? "
                        "WHERE task_id = ? AND phase_id = ?",
                        (artifact_ids, main.utc_now(), job["task_id"], phase["parent_phase_id"]),
                    )
            db.execute("INSERT INTO tool_calls (task_id, job_id, agent_id, tool_name, input_summary, output_summary, status, duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (job["task_id"], job["id"], employee, "agent_run", "격리 작업공간에서 에이전트 실행", result["summary"][:500], "pass", None, main.utc_now()))
            record_step(db, job, index, "agent_run", "succeeded", result["summary"])
            main.emit_job_event(db, job["task_id"], "agent.completed", result["summary"], job_id=job["id"], agent_id=employee, payload={"zone": "desk", "action": "work"})
    with main.database() as db:
        task = main.task_payload(db, job["task_id"])
        plan = task.get("execution_plan", {}).get("plan") if task.get("execution_plan") else {}
        lead = plan.get("final_owner") or task.get("lead_id") or next((employee for employee in task["assigned_employees"] if employee in main.LEAD_IDS and employee != "NAVI"), None)
        department_deliverables = [item for item in task["deliverables"] if item["status"] == "department_draft"]
        incomplete_phases = [
            phase for phase in task["phases"]
            if phase["status"] not in {"completed", "skipped"}
        ]
        active_execute = db.execute(
            "SELECT 1 FROM jobs WHERE task_id = ? AND kind = 'execute' AND id != ? "
            "AND state IN ('queued','running','pause_requested','cancel_requested') LIMIT 1",
            (job["task_id"], job["id"]),
        ).fetchone()
        if incomplete_phases or active_execute:
            db.execute("UPDATE tasks SET state = 'executing', updated_at = ? WHERE id = ?", (main.utc_now(), job["task_id"]))
            main.emit_job_event(
                db,
                job["task_id"],
                "execution.wave_completed",
                "Parallel wave completed; waiting for ready downstream phases.",
                job_id=job["id"],
                payload={"remaining_phases": [phase["phase_id"] for phase in incomplete_phases]},
            )
        elif lead and department_deliverables:
            synthesize_job = main.enqueue_job(db, job["task_id"], "synthesize", {
                "lead_id": lead,
                "workspace_id": payload["workspace_id"],
                "revision_findings": "",
            })
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("synthesizing", main.utc_now(), job["task_id"]))
            main.emit_job_event(db, job["task_id"], "synthesis.queued", "팀장 최종 산출물 통합 Job을 시작합니다.", job_id=synthesize_job["id"], agent_id=lead)
        else:
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "execution.completed", "부서별 산출물 저장 완료.", job_id=job["id"])


def process_synthesize(job: dict) -> None:
    lead = job["payload"]["lead_id"]
    workspace_id = job["payload"]["workspace_id"]
    with main.database() as db:
        task = main.task_payload(db, job["task_id"])
        workspace_row = db.execute("SELECT * FROM workspaces WHERE id = ? AND task_id = ?", (workspace_id, job["task_id"])).fetchone()
        if not workspace_row:
            raise RuntimeError("Synthesis workspace not found")
        workspace, allowed, reason = main.validate_task_workspace(workspace_row)
        if not allowed:
            raise RuntimeError(reason)
        drafts = [item for item in task["deliverables"] if item["status"] == "department_draft"]
        if not drafts:
            raise RuntimeError("No department deliverables to synthesize")
        contributions = []
        for item in drafts:
            path = (workspace / item["path"]).resolve()
            if not path.is_relative_to(workspace) or not path.exists():
                raise RuntimeError(f"Department deliverable missing: {item['path']}")
            contributions.append({"owner": item["owner"], "path": item["path"], "content": path.read_text(encoding="utf-8", errors="replace")[:30000]})
        sources = [
            {"title": row["title"], "url": row["url"], "snippet": row["snippet"][:500]}
            for row in db.execute(
                "SELECT title, url, MAX(snippet) AS snippet FROM research_sources "
                "WHERE task_id = ? AND query = 'verified-original' GROUP BY url ORDER BY MIN(created_at) LIMIT 100",
                (job["task_id"],),
            )
        ]
        plan = task.get("execution_plan", {}).get("plan") if task.get("execution_plan") else {}
        artifact_kind = plan.get("artifact_kind")
        standards = json.loads(main.DELIVERABLE_STANDARDS_PATH.read_text(encoding="utf-8"))
        if artifact_kind in standards:
            standard = standards[artifact_kind]
        else:
            artifact_kind, standard = main.deliverable_spec(task["request"])
        revision_findings = job["payload"].get("revision_findings", "")
        main.emit_job_event(db, job["task_id"], "synthesis.started", "팀장이 부서 결과를 단일 최종안으로 통합합니다.", job_id=job["id"], agent_id=lead)
    role = main.agent_role(lead)
    final_scope = next((item for item in task.get("agent_scopes", []) if item["employee_id"] == lead), None)
    final_skill_ids = final_scope.get("skill_ids", []) if final_scope else []
    final_phase = next((phase for phase in task.get("phases", []) if phase["owner_id"] == lead), None)
    final_task_kind = (final_phase or {}).get("task_kind") or main.default_task_kind(main.registry()[lead]["team"], lead)
    final_skill_context = main.employee_skill_context(
        lead,
        task["request"],
        selected_skill_ids=final_skill_ids,
        task_kind=final_task_kind,
    ) if final_skill_ids else {"required_skills": []}
    model = main.technical_integration_model()
    response = main.cancellable_model_response(
        main.model_client(),
        job["task_id"],
        job["id"],
        model=model,
        instructions=(
            f"You are {lead}, technical integration owner. Produce one Korean Markdown deliverable. "
            "Reconcile contradictions instead of concatenating drafts. Follow required sections exactly. "
            "When the standard requires a single recommendation, choose exactly one and explain why alternatives lost. "
            "Use only supplied source URLs for factual citations. Mark unsupported numbers as estimates. "
            "Do not mention internal agents, skills, tool calls, or drafts. Apply supplied selected skill instructions silently. Return final document content only."
        ),
        input=json.dumps({
            "task": task["request"],
            "execution_plan": plan,
            "artifact_kind": artifact_kind,
            "standard": standard,
            "department_contributions": contributions,
            "sources": sources,
            "revision_findings": revision_findings,
            "selected_skill_instructions": final_skill_context["required_skills"],
        }, ensure_ascii=False),
    )
    content = response.output_text.strip()
    if not content:
        raise RuntimeError("Synthesis model returned no final deliverable")
    if not safe_point(job):
        return
    with main.database() as db:
        final = main.persist_deliverable(
            db,
            workspace,
            job["task_id"],
            lead,
            artifact_kind,
            content,
            filename=standard["filename"],
            status="final_candidate",
        )
        formats = formats_for_request(task["request"], artifact_kind)
        rendered = [
            main.register_existing_deliverable(
                db,
                workspace,
                job["task_id"],
                lead,
                f"{artifact_kind}:{path.suffix.lstrip('.') or 'manifest'}",
                path,
                "rendered_candidate",
            )
            for path in main.render_bundle(workspace / final["path"], formats)
        ]
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (job["task_id"], lead, "synthesis", content, main.utc_now()))
        reviewer = "NAVI"
        review_job = main.enqueue_job(
            db,
            job["task_id"],
            "lead_review",
            {"lead_id": lead, "reviewer_id": reviewer, "workspace_id": workspace_id},
        )
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("lead_review_running", main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "synthesis.completed", f"DeepSeek V4 Pro 기술 통합 완료: {final['path']}", job_id=job["id"], agent_id=lead, payload={"deliverable": final, "model": model})
        main.emit_job_event(db, job["task_id"], "review.queued", "NAVI(GLM-5.2) 증거 검토와 완료 판정을 시작합니다.", job_id=review_job["id"], agent_id=reviewer)


def process_review(job: dict) -> None:
    lead = job["payload"]["lead_id"]
    reviewer = "NAVI"
    with main.database() as db:
        task = main.task_payload(db, job["task_id"])
        model = main.final_completion_model()
        main.emit_job_event(db, job["task_id"], "review.started", "NAVI(GLM-5.2) 증거 검토와 완료 판정 시작", job_id=job["id"], agent_id=reviewer, payload={"zone": "qa", "action": "review"})
        final = next((item for item in task["deliverables"] if item["status"] == "final_candidate"), None)
        if not final:
            raise RuntimeError("Lead review requires a final_candidate deliverable")
        workspace_row = db.execute("SELECT * FROM workspaces WHERE id = ? AND task_id = ?", (job["payload"].get("workspace_id"), job["task_id"])).fetchone()
        if not workspace_row:
            raise RuntimeError("Lead review workspace not found")
        workspace, allowed, reason = main.validate_task_workspace(workspace_row)
        if not allowed:
            raise RuntimeError(reason)
        final_path = (workspace / final["path"]).resolve()
        if not final_path.is_relative_to(workspace) or not final_path.exists():
            raise RuntimeError("Final deliverable file is missing")
        final_content = final_path.read_text(encoding="utf-8", errors="replace")
        plan = task.get("execution_plan", {}).get("plan") if task.get("execution_plan") else {}
        artifact_kind = plan.get("artifact_kind")
        standards = json.loads(main.DELIVERABLE_STANDARDS_PATH.read_text(encoding="utf-8"))
        if artifact_kind in standards:
            standard = standards[artifact_kind]
        else:
            artifact_kind, standard = main.deliverable_spec(task["request"])
        evidence = task["evidence"]
    client = main.model_client()
    response = main.cancellable_model_response(
        client,
        job["task_id"],
        job["id"],
        model=model,
        instructions=(
            "Review the actual final file against every required section and rule. "
            "Pass only when the file is coherent, complete, evidence-grounded, and directly answers the task. "
            "Return strict JSON only: {\"verdict\":\"pass|changes_requested|blocked\",\"findings\":\"Korean actionable review\",\"final_report\":\"Korean executive completion report\"}."
        ),
        input=json.dumps({"task": task["request"], "execution_plan": plan, "artifact_kind": artifact_kind, "standard": standard, "final_file": final_content, "evidence": evidence}, ensure_ascii=False),
    )
    raw = response.output_text.strip()
    if not safe_point(job):
        return
    try:
        review = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        verdict = review.get("verdict", "changes_requested")
        findings = review.get("findings", raw)
        final_report = review.get("final_report", findings)
    except Exception:
        verdict, findings, final_report = "changes_requested", raw, raw
    if verdict not in {"pass", "changes_requested", "blocked"}:
        verdict = "changes_requested"
    final_report = str(final_report).strip() or str(findings)
    with main.database() as db:
        final_status = {"pass": "COMPLETE", "changes_requested": "RETURNED", "blocked": "BLOCKED"}[verdict]
        run_results = list(db.execute("SELECT command, status, exit_code FROM runs WHERE task_id = ? ORDER BY created_at", (job["task_id"],)))
        changed_files = [item["path"] for item in task["deliverables"] if item["status"] != "completion_report"]
        report = "\n".join([
            "# NAVI Final Report",
            "## 요청 목표", task["request"],
            "## 구현 범위", str(plan.get("summary") or task["title"]),
            "## 변경된 주요 파일", "\n".join(f"- {path}" for path in changed_files) or "- 변경 파일 없음",
            "## 실행한 검증 명령", "\n".join(f"- {row['command']}" for row in run_results) or "- 실행된 검증 명령 없음",
            "## 테스트 결과", "\n".join(f"- {row['status']} (exit {row['exit_code']})" for row in run_results) or "- 검증 결과 없음",
            "## 완료 조건별 판정", final_report,
            "## 미해결 사항 및 위험", str(findings) or "- 없음",
            f"## 최종 상태: {final_status}",
        ])
        count = db.execute("SELECT COUNT(*) FROM reviews WHERE task_id = ?", (job["task_id"],)).fetchone()[0] + 1
        review_id = f"REV-{job['task_id'].split('-')[-1]}-{count:02d}"
        db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)", (review_id, job["task_id"], reviewer, verdict, findings, main.utc_now()))
        db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"EVD-{job['task_id'].split('-')[-1]}-LEAD-REVIEW", job["task_id"], None, "lead_review", "pass" if verdict == "pass" else "fail", main.hashlib.sha256(findings.encode()).hexdigest(), 0, main.utc_now()))
        main.persist_deliverable(db, workspace, job["task_id"], "NAVI", "completion_report", report, filename="reports/NAVI_FINAL_REPORT.md", status="completion_report")
        db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (job["task_id"], "NAVI", "final_report", report, main.utc_now()))
        if verdict == "pass":
            if main.task_requires_user_approval(db, job["task_id"]):
                next_state = "awaiting_approval"
                main.emit_job_event(
                    db, job["task_id"], "approval.required",
                    "민감 업무 결과는 사용자 승인이 있어야 완료됩니다.",
                    job_id=job["id"], agent_id=reviewer,
                )
            else:
                main.assert_completion_invariants(
                    db,
                    job["task_id"],
                    workspace,
                    current_job_id=job["id"],
                )
                db.execute(
                    "UPDATE deliverables SET status = CASE "
                    "WHEN status = 'final_candidate' THEN 'approved' ELSE 'rendered_approved' END, updated_at = ? "
                    "WHERE task_id = ? AND status IN ('final_candidate', 'rendered_candidate')",
                    (main.utc_now(), job["task_id"]),
                )
                next_state = "completed"
        elif verdict == "blocked":
            next_state = "blocked"
        else:
            change_count = db.execute("SELECT COUNT(*) FROM reviews WHERE task_id = ? AND verdict = 'changes_requested'", (job["task_id"],)).fetchone()[0]
            retry_limit = task["contract"]["retry_limit"]
            if change_count <= retry_limit:
                rework_job = main.enqueue_job(db, job["task_id"], "synthesize", {
                    "lead_id": lead,
                    "workspace_id": job["payload"]["workspace_id"],
                    "revision_findings": findings,
                })
                next_state = "synthesizing"
                main.emit_job_event(db, job["task_id"], "synthesis.rework_queued", "리뷰 지적사항으로 최종 산출물을 재통합합니다.", job_id=rework_job["id"], agent_id=lead)
            else:
                next_state = "blocked"
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "review.completed", findings, job_id=job["id"], agent_id=reviewer, payload={"verdict": verdict, "zone": "qa", "action": "review"})


def process(job: dict) -> None:
    stop = Event()
    lease_thread = Thread(target=maintain_job_lease, args=(job, stop), daemon=True)
    lease_thread.start()
    try:
        if job["kind"] in {"plan", "direct_plan"}:
            process_plan(job)
        elif job["kind"] == "meeting":
            process_meeting(job)
        elif job["kind"] == "execute":
            process_execute(job)
        elif job["kind"] == "synthesize":
            process_synthesize(job)
        elif job["kind"] == "lead_review":
            process_review(job)
        else:
            raise RuntimeError(f"Unknown job kind: {job['kind']}")
        with main.database() as db:
            state = db.execute("SELECT state FROM jobs WHERE id = ?", (job["id"],)).fetchone()[0]
        if state == "running":
            set_job(job, "succeeded", "작업 완료")
    except main.JobControlSignal:
        safe_point(job)
    except main.HTTPException as error:
        if error.status_code == 428:
            set_job(job, "paused", "권한 승인을 기다립니다.", str(error.detail))
            with main.database() as db:
                for employee in job.get("payload", {}).get("employee_ids", []):
                    main.set_session_state(db, job["task_id"], employee, "paused")
                db.execute(
                    "UPDATE tasks SET state = 'paused', updated_at = ? WHERE id = ?",
                    (main.utc_now(), job["task_id"]),
                )
                main.emit_job_event(
                    db,
                    job["task_id"],
                    "permission.awaiting",
                    str(error.detail),
                    job_id=job["id"],
                )
        else:
            set_job(job, "failed", "작업 실패", str(error.detail))
            with main.database() as db:
                db.execute(
                    "UPDATE tasks SET state = 'blocked', updated_at = ? WHERE id = ?",
                    (main.utc_now(), job["task_id"]),
                )
                main.emit_job_event(
                    db,
                    job["task_id"],
                    "job.failed",
                    str(error.detail),
                    job_id=job["id"],
                )
    except Exception as error:
        set_job(job, "failed", "작업 실패", str(error))
        with main.database() as db:
            for employee in job.get("payload", {}).get("employee_ids", []):
                main.set_session_state(db, job["task_id"], employee, "failed")
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), job["task_id"]))
            main.emit_job_event(db, job["task_id"], "job.failed", str(error), job_id=job["id"])
    finally:
        stop.set()
        lease_thread.join(timeout=3)


def worker_loop() -> None:
    while True:
        heartbeat()
        job = claim_job()
        if job:
            process(job)
        else:
            time.sleep(0.5)


EVENT_CLEANUP_INTERVAL_SECONDS = 6 * 3600


def cleanup_old_job_events() -> None:
    with main.database() as db:
        deleted = main.purge_old_job_events(db)
        if deleted:
            db.commit()  # VACUUM cannot run inside the implicit transaction the DELETE opened
            db.execute("VACUUM")


def main_loop() -> None:
    main.init_db()
    recover_orphaned_jobs()
    worker_factory = Process if WORKER_MODE == "process" else Thread
    workers = [
        worker_factory(target=worker_loop, daemon=True, name=f"ai-office-worker-{index}")
        for index in range(1, WORKER_CONCURRENCY + 1)
    ]
    for thread in workers:
        thread.start()
    last_cleanup = 0.0
    while True:
        try:
            heartbeat()
            reconcile_failed_jobs()
            schedule_lead_selection()
            schedule_autonomous_tasks()
            schedule_ready_phase_jobs()
            if time.monotonic() - last_cleanup >= EVENT_CLEANUP_INTERVAL_SECONDS:
                cleanup_old_job_events()
                last_cleanup = time.monotonic()
        except Exception:
            # ponytail: dispatcher loop must outlive one bad tick (e.g. check_budget
            # raising HTTPException via enqueue_job, or VACUUM hitting a lock).
            # Per-job failures already isolate in process(); this is the same
            # guarantee one level up so the whole worker can't die on a scheduling tick.
            traceback.print_exc()
        time.sleep(0.5)


if __name__ == "__main__":
    main_loop()
