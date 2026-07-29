"""Single local durable worker for AI Office jobs.

The API only enqueues work. This process leases one SQLite job at a time and
commits observable events between every safe execution step.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import timedelta
from threading import Event, Thread

from apps.api import main

WORKER_ID = f"local-worker-{os.getpid()}"

def team_worker_candidates(lead_ids: list[str], include_lead: bool = False) -> list[tuple[str, str]]:
    people = main.registry()
    teams = {people[lead]["team"] for lead in lead_ids if lead in people}
    candidates = [(employee_id, f"{people[employee_id]['title']} · 팀장 제안 실행자") for employee_id in people if people[employee_id]["team"] in teams and employee_id not in main.LEAD_IDS]
    if include_lead:
        candidates = [(lead, "팀장 직접 실행 · 별도 팀장 리뷰 필수") for lead in lead_ids] + candidates
    return candidates


def worker_candidates_for_lead(lead_id: str) -> list[tuple[str, str]]:
    people = main.registry()
    if lead_id not in people:
        return []
    team = people[lead_id]["team"]
    return [(employee_id, people[employee_id]["title"]) for employee_id in people if people[employee_id]["team"] == team and employee_id not in main.LEAD_IDS]


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
            main.emit_job_event(db, row["task_id"], "job.interrupted", "worker 재시작으로 현재 모델 호출을 중단했습니다. 재시도해야 합니다.", job_id=row["id"])

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
            candidates = [employee for employee in proposed if employee not in main.LEAD_IDS]
            if not candidates:
                candidates = [employee for employee, _ in team_worker_candidates(leads)]
            if not candidates:
                db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), task["id"]))
                main.emit_job_event(db, task["id"], "delegation.blocked", "팀장 제안 실행자가 없습니다.")
                continue
            assignments = list(dict.fromkeys(leads + candidates))
            db.execute("DELETE FROM task_assignments WHERE task_id = ?", (task["id"],))
            db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(task["id"], employee) for employee in assignments])
            job = main.enqueue_job(db, task["id"], "execute", {"workspace_id": workspace["id"], "employee_ids": candidates, "instruction": task["request"]})
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("executing", main.utc_now(), task["id"]))
            main.emit_job_event(db, task["id"], "delegation.auto_assigned", "팀장 분배안을 승인해 실행 Job을 자동 시작합니다.", job_id=job["id"], payload={"workers": candidates})

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
            if task and task["state"] in {"executing", "meeting_running", "lead_review_running"}:
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
        db.execute("UPDATE jobs SET state = ?, error = ?, heartbeat_at = ?, updated_at = ? WHERE id = ?", (state, error, now, now, job["id"]))
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
        candidates = worker_candidates_for_lead(roster[0])
        items = [(candidates[0][0], f"{candidates[0][1]} · 팀장 자동 배정") ] if candidates else [(roster[0], "팀장 직접 실행 · 별도 리뷰 필수")]
        reason = "대표가 선택한 팀장이 소규모 업무를 판단합니다."
        usage = None
    else:
        try:
            roster, items, reason, usage = main.select_roster_with_model(task["request"])
        except Exception as error:
            fallback, _ = main.planned_roster(task["request"])
            roster = [employee for employee in fallback if employee in main.LEAD_IDS and employee != "NAVI"][:3] or ["FRAME"]
            items = [(employee, "팀 범위와 worker 제안") for employee in roster]
            reason, usage = f"모델 판단 실패, 안전한 규칙 기반 후보 사용: {error}", None
    if not safe_point(job):
        return
    with main.database() as db:
        main.require_skill_ready(roster)
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
            db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (job["task_id"], usage["model"], usage["input_tokens"], usage["output_tokens"], 0, None, main.utc_now()))
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
    worker_proposals: list[tuple[str, str]] = []
    for index, employee in enumerate(participants, 1):
        if not safe_point(job):
            return
        role = main.agent_role(employee); model = main.NAVI_MODEL if employee == "NAVI" else main.model_settings()[role["model_role"]]
        run_id = f"AR-{job['id']}-{index:02d}"
        with main.database() as db:
            existing = db.execute("SELECT state, summary FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if existing and existing["state"] == "succeeded":
                transcript.append(f"{employee}: {existing['summary'] or ''}")
                continue
            record_step(db, job, index, "meeting_speaker", "running", employee)
            main.emit_job_event(db, job["task_id"], "model.started", "회의 발언 준비", job_id=job["id"], agent_id=employee)
            db.execute("INSERT OR REPLACE INTO agent_runs (id, task_id, job_id, employee_id, state, model, started_at, finished_at, summary) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)", (run_id, job["task_id"], job["id"], employee, "running", model, main.utc_now()))
        available = worker_candidates_for_lead(employee) if employee != "NAVI" else []
        if available:
            instructions = (
                f"You are {employee}, {role['title']}. Discuss the actual task and delegate only necessary workers. "
                "Return strict JSON: {\"message\":\"concise Korean meeting statement\",\"assignments\":[{\"worker_id\":\"ID\",\"description\":\"specific work\"}]}. "
                "Choose one worker by default, at most two. Use only available_workers."
            )
        else:
            instructions = f"You are {employee}, {role['title']}. Open this meeting with one concise Korean statement grounded in the actual request."
        response = main.model_client().responses.create(model=model, instructions=instructions, input=json.dumps({"task_request": task["request"], "objective": meeting["objective"], "agenda": agenda, "prior": transcript, "available_workers": [{"id": worker_id, "title": title} for worker_id, title in available]}, ensure_ascii=False))
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
                        worker_proposals.append((worker_id, description[:500]))
            except Exception:
                content = raw
            if not any(worker_id in {candidate[0] for candidate in available} for worker_id, _ in worker_proposals):
                worker_proposals.append((available[0][0], f"{available[0][1]} · {employee} 팀장 자동 배정"))
        if not content:
            raise RuntimeError(f"Meeting model returned no statement: {employee}")
        if not safe_point(job):
            with main.database() as db:
                db.execute("UPDATE agent_runs SET state = 'interrupted', finished_at = ? WHERE id = ?", (main.utc_now(), run_id))
            return
        with main.database() as db:
            db.execute("UPDATE agent_runs SET state = 'succeeded', finished_at = ?, summary = ? WHERE id = ?", (main.utc_now(), content[:2000], run_id))
            db.execute("INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)", (job["task_id"], employee, "meeting", content, main.utc_now()))
            db.execute("INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (job["task_id"], model, getattr(usage, "input_tokens", 0) if usage else 0, getattr(usage, "output_tokens", 0) if usage else 0, 0, None, main.utc_now()))
            record_step(db, job, index, "meeting_speaker", "succeeded", content)
            main.emit_job_event(db, job["task_id"], "meeting.message", content, job_id=job["id"], agent_id=employee, payload={"zone": "meeting", "action": "meeting"})
        transcript.append(f"{employee}: {content}")
    with main.database() as db:
        db.execute("UPDATE meetings SET status = ?, decisions = ? WHERE id = ?", ("concluded", json.dumps(["실제 모델 발언 기록 완료"], ensure_ascii=False), job["payload"]["meeting_id"]))
        leads = [employee for employee in participants if employee != "NAVI"]
        candidates = list(dict.fromkeys(worker_proposals))
        if not candidates:
            candidates = [candidate for lead in leads for candidate in worker_candidates_for_lead(lead)[:1]]
        db.execute("DELETE FROM action_items WHERE task_id = ?", (job["task_id"],))
        contract = main.task_payload(db, job["task_id"])["contract"]
        for index, (owner, description) in enumerate(candidates, 1):
            db.execute("INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"ACT-{job['task_id'].split('-')[-1]}-{index:02d}", job["task_id"], job["payload"]["meeting_id"], owner, description, index, json.dumps(contract["acceptance_criteria"]), "proposed"))
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("awaiting_worker_selection", main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "meeting.completed", "팀장 회의 발언 기록 완료", job_id=job["id"], agent_id="NAVI")


def process_execute(job: dict) -> None:
    payload = job["payload"]
    for index, employee in enumerate(payload["employee_ids"], 1):
        if not safe_point(job):
            return
        with main.database() as db:
            model = main.model_settings()[main.agent_role(employee)["model_role"]]
            assignment = db.execute("SELECT description FROM action_items WHERE task_id = ? AND owner = ? ORDER BY sequence LIMIT 1", (job["task_id"], employee)).fetchone()
            work_summary = assignment["description"] if assignment else "배정된 업무 수행"
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
        result = main.run_agent(
            job["task_id"],
            main.AgentRunInput(
                workspace_id=payload["workspace_id"],
                employee_id=employee,
                instruction=payload.get("instruction", ""),
                managed_by_job=True,
                job_id=job["id"],
            ),
        )
        if not safe_point(job):
            with main.database() as db:
                db.execute("UPDATE agent_runs SET state = 'interrupted', finished_at = ? WHERE id = ?", (main.utc_now(), run_id))
            return
        with main.database() as db:
            db.execute("UPDATE agent_runs SET state = 'succeeded', finished_at = ?, summary = ? WHERE id = ?", (main.utc_now(), result["summary"][:2000], run_id))
            db.execute("UPDATE action_items SET status = 'completed' WHERE task_id = ? AND owner = ?", (job["task_id"], employee))
            db.execute("INSERT INTO tool_calls (task_id, job_id, agent_id, tool_name, input_summary, output_summary, status, duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (job["task_id"], job["id"], employee, "agent_run", "격리 작업공간에서 에이전트 실행", result["summary"][:500], "pass", None, main.utc_now()))
            record_step(db, job, index, "agent_run", "succeeded", result["summary"])
            main.emit_job_event(db, job["task_id"], "agent.completed", result["summary"], job_id=job["id"], agent_id=employee, payload={"zone": "desk", "action": "work"})
    with main.database() as db:
        task = main.task_payload(db, job["task_id"])
        lead = task.get("lead_id") or next((employee for employee in task["assigned_employees"] if employee in main.LEAD_IDS and employee != "NAVI"), None)
        has_evidence = any(item["status"] == "pass" for item in task["evidence"])
        if lead and has_evidence:
            review_job = main.enqueue_job(db, job["task_id"], "lead_review", {"lead_id": lead})
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("lead_review_running", main.utc_now(), job["task_id"]))
            main.emit_job_event(db, job["task_id"], "review.queued", "팀장 리뷰 Job 자동 대기열 등록", job_id=review_job["id"], agent_id=lead)
        else:
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "execution.completed", "실행 완료. 팀장 리뷰를 시작할 수 있습니다.", job_id=job["id"])


def process_review(job: dict) -> None:
    lead = job["payload"]["lead_id"]; role = main.agent_role(lead); model = main.model_settings()[role["model_role"]]
    with main.database() as db:
        task = main.task_payload(db, job["task_id"])
        main.emit_job_event(db, job["task_id"], "review.started", "팀장 실제 리뷰 시작", job_id=job["id"], agent_id=lead, payload={"zone": "qa", "action": "review"})
        evidence = task["evidence"]; messages = task["agent_messages"][:12]
    response = main.model_client().responses.create(model=model, instructions="You are a team lead. Review actual execution evidence. Return strict JSON only: {\"verdict\":\"pass|changes_requested|blocked\",\"findings\":\"Korean concise review\"}.", input=json.dumps({"task": task["request"], "evidence": evidence, "messages": messages}, ensure_ascii=False))
    raw = response.output_text.strip()
    if not safe_point(job):
        return
    try:
        review = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        verdict = review.get("verdict", "changes_requested")
        findings = review.get("findings", raw)
    except Exception:
        verdict, findings = "changes_requested", raw
    if verdict not in {"pass", "changes_requested", "blocked"}:
        verdict = "changes_requested"
    with main.database() as db:
        count = db.execute("SELECT COUNT(*) FROM reviews WHERE task_id = ?", (job["task_id"],)).fetchone()[0] + 1
        review_id = f"REV-{job['task_id'].split('-')[-1]}-{count:02d}"
        db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)", (review_id, job["task_id"], lead, verdict, findings, main.utc_now()))
        db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"EVD-{job['task_id'].split('-')[-1]}-LEAD-REVIEW", job["task_id"], None, "lead_review", "pass" if verdict == "pass" else "fail", main.hashlib.sha256(findings.encode()).hexdigest(), 0, main.utc_now()))
        next_state = "completed" if verdict == "pass" else ("blocked" if verdict == "blocked" else "planning")
        db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (next_state, main.utc_now(), job["task_id"]))
        main.emit_job_event(db, job["task_id"], "review.completed", findings, job_id=job["id"], agent_id=lead, payload={"verdict": verdict, "zone": "qa", "action": "review"})


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
        elif job["kind"] == "lead_review":
            process_review(job)
        else:
            raise RuntimeError(f"Unknown job kind: {job['kind']}")
        with main.database() as db:
            state = db.execute("SELECT state FROM jobs WHERE id = ?", (job["id"],)).fetchone()[0]
        if state == "running":
            set_job(job, "succeeded", "작업 완료")
    except Exception as error:
        set_job(job, "failed", "작업 실패", str(error))
        with main.database() as db:
            db.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", ("blocked", main.utc_now(), job["task_id"]))
            main.emit_job_event(db, job["task_id"], "job.failed", str(error), job_id=job["id"])
    finally:
        stop.set()
        lease_thread.join(timeout=3)


def main_loop() -> None:
    main.init_db()
    recover_orphaned_jobs()
    while True:
        heartbeat()
        reconcile_failed_jobs()
        schedule_autonomous_tasks()
        job = claim_job()
        if job:
            process(job)
        else:
            time.sleep(0.5)


if __name__ == "__main__":
    main_loop()
