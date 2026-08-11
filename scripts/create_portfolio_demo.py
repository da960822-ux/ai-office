"""Create an isolated, fictional dataset for README screenshots.

Never points at the normal runtime database. No model call, workspace write, or
user project data is used. Run before starting the API with the same database:

    python scripts/create_portfolio_demo.py
    $env:AI_OFFICE_DB_PATH = "$PWD\\data\\portfolio-demo.sqlite3"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api import main


DATABASE = (ROOT / "data" / "portfolio-demo.sqlite3").resolve()
TASK_ID = "TASK-DEMO-001"
NOW = "2026-08-11T10:00:00+00:00"


def add(db, query: str, values: tuple) -> None:
    db.execute(query, values)


def main_run() -> None:
    if DATABASE.name != "portfolio-demo.sqlite3":
        raise RuntimeError("Refusing to replace a non-demo database")
    if DATABASE.exists():
        DATABASE.unlink()
    main.DB_PATH = DATABASE
    main.init_db()

    plan = {
        "summary": "예약 전환이 막히는 지점을 정리하고, 모바일 예약 흐름을 개선한 뒤 독립 QA로 완료 조건을 확인했습니다.",
        "artifact_kind": "product-improvement",
        "final_owner": "BUILD",
        "workspace_context": "write",
        "requires_web_research": False,
        "evidence_strategy": "산출물 해시, 검증 명령, 독립 리뷰 3가지를 모두 통과해야 완료로 판정합니다.",
        "reason": "기획·디자인·구현·QA가 모두 필요한 소규모 제품 개선 요청입니다.",
        "phases": [
            {"id": "discover", "department": "product-experience", "lead_id": "FRAME", "objective": "예약 이탈 구간과 완료 조건 정의", "output": "개선 범위", "handoff_to": "MOSS", "depends_on": []},
            {"id": "design", "department": "product-experience", "lead_id": "MOSS", "objective": "모바일 예약 화면 구조 설계", "output": "UI 명세", "handoff_to": "FRONT", "depends_on": ["discover"]},
            {"id": "build", "department": "application", "lead_id": "BUILD", "objective": "예약 흐름 구현과 회귀 테스트", "output": "변경 파일", "handoff_to": "GUARD", "depends_on": ["design"]},
            {"id": "verify", "department": "quality-security", "lead_id": "GUARD", "objective": "독립 QA와 완료 판정", "output": "검증 리포트", "handoff_to": None, "depends_on": ["build"]},
        ],
    }
    with main.database() as db:
        add(db, "INSERT INTO projects VALUES (?, ?, ?, ?, ?)", ("PROJECT-DEMO-001", "Demo Cafe Reservation", "C:\\demo\\cafe-reservation", 1, NOW))
        add(db, "INSERT INTO tasks (id, title, request, state, created_at, updated_at, route, lead_id, parent_task_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            TASK_ID, "카페 예약 전환 흐름 개선", "모바일 예약에서 날짜 선택 후 이탈하는 문제를 해결하고, 예약 완료까지의 흐름을 개선한 뒤 회귀 테스트까지 확인해줘.", "completed", NOW, NOW, "navi", "NAVI", None,
        ))
        employees = ("NAVI", "FRAME", "MOSS", "BUILD", "FRONT", "BACK", "GUARD", "TRACE")
        db.executemany("INSERT INTO task_assignments VALUES (?, ?)", [(TASK_ID, employee) for employee in employees])
        add(db, "INSERT INTO task_plans VALUES (?, ?, ?, ?, ?)", (TASK_ID, json.dumps(plan, ensure_ascii=False), plan["summary"], NOW, NOW))
        scopes = [
            ("FRAME", "예약 이탈 원인과 완료 조건 정리", "product-brief", "MOSS", 1),
            ("MOSS", "모바일 예약 화면 구조와 문구 설계", "reservation-flow.md", "FRONT", 2),
            ("FRONT", "예약 단계 UI와 오류 상태 구현", "src/reservation-flow.tsx", "GUARD", 3),
            ("BACK", "예약 요청 검증과 응답 계약 확인", "src/api/reservation.ts", "GUARD", 4),
            ("GUARD", "회귀 테스트와 독립 리뷰", "qa-report.md", None, 5),
        ]
        db.executemany(
            "INSERT INTO task_agent_scopes (task_id, employee_id, assignment, skill_ids, deliverable, handoff_to, dependencies, sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(TASK_ID, employee, assignment, json.dumps([], ensure_ascii=False), deliverable, handoff, json.dumps([], ensure_ascii=False), sequence) for employee, assignment, deliverable, handoff, sequence in scopes],
        )
        db.executemany(
            "INSERT INTO evidence (id, task_id, run_id, type, status, artifact_sha256, stale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("EVD-DEMO-HASH", TASK_ID, "RUN-DEMO-FRONT", "deliverable", "pass", "cafe-flow-a1b2c3d4e5f6", 0, NOW),
                ("EVD-DEMO-TEST", TASK_ID, "RUN-DEMO-QA", "command", "pass", "vitest-pass-9f4b2c", 0, NOW),
                ("EVD-DEMO-REVIEW", TASK_ID, "RUN-DEMO-QA", "lead_review", "pass", "review-7ea1f9", 0, NOW),
            ],
        )
        db.executemany(
            "INSERT INTO deliverables (id, task_id, owner, kind, path, status, artifact_sha256, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("DEL-DEMO-UI", TASK_ID, "FRONT", "source", "src/reservation-flow.tsx", "approved", "cafe-flow-a1b2c3d4e5f6", NOW, NOW),
                ("DEL-DEMO-QA", TASK_ID, "GUARD", "report", "reports/qa-reservation-flow.md", "approved", "review-7ea1f9", NOW, NOW),
            ],
        )
        add(db, "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?)", ("REV-DEMO-001", TASK_ID, "GUARD", "pass", "모바일 예약 단계, 오류 안내, 회귀 테스트 결과를 독립 확인했습니다. 현재 요청 범위에서 차단 이슈는 없습니다.", NOW))
        add(db, "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?)", ("WS-DEMO-001", TASK_ID, "C:\\demo\\cafe-reservation", "C:\\demo\\cafe-reservation", "in_place", "completed", NOW))
        add(db, "INSERT INTO jobs (id, task_id, kind, payload, state, step, lease_owner, lease_until, heartbeat_at, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("JOB-DEMO-001", TASK_ID, "execute", "{}", "succeeded", 4, "portfolio-demo", None, NOW, None, NOW, NOW))
        db.executemany(
            "INSERT INTO agent_runs (id, task_id, job_id, employee_id, state, model, started_at, finished_at, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("RUN-DEMO-FRONT", TASK_ID, "JOB-DEMO-001", "FRONT", "succeeded", "demo-model", NOW, NOW, "예약 UI 구현 완료"),
                ("RUN-DEMO-QA", TASK_ID, "JOB-DEMO-001", "GUARD", "succeeded", "demo-model", NOW, NOW, "독립 QA 완료"),
            ],
        )
        db.executemany(
            "INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
            [
                (TASK_ID, "FRAME", "dispatch", "예약 이탈 구간을 날짜 선택 단계로 좁히고, 모바일 우선 완료 조건을 정의했습니다.", NOW),
                (TASK_ID, "FRONT", "run", "예약 단계 UI와 오류 안내를 구현하고 회귀 테스트를 실행했습니다.", NOW),
                (TASK_ID, "NAVI", "final_report", "데모 시나리오 기준으로 기획, 구현, QA를 완료했습니다. 파일 해시·검증 명령·독립 리뷰를 모두 통과했습니다.", NOW),
            ],
        )
        db.executemany(
            "INSERT INTO job_events (task_id, job_id, agent_id, type, summary, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (TASK_ID, "JOB-DEMO-001", "FRAME", "plan.completed", "예약 이탈 원인과 완료 조건을 정리했습니다.", "{}", NOW),
                (TASK_ID, "JOB-DEMO-001", "FRONT", "agent.run.completed", "모바일 예약 화면과 오류 안내 구현을 마쳤습니다.", "{}", NOW),
                (TASK_ID, "JOB-DEMO-001", "GUARD", "review.completed", "독립 QA와 회귀 테스트를 통과했습니다.", "{}", NOW),
            ],
        )
        add(db, "INSERT INTO worker_heartbeats (worker_id, build_id, heartbeat_at, error_streak, last_error) VALUES (?, ?, ?, ?, ?)", ("portfolio-demo", main.BUILD_ID, main.utc_now(), 0, None))
    print(DATABASE)


if __name__ == "__main__":
    main_run()
