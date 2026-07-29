import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api import main, worker


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def create(self, **_kwargs):
        return SimpleNamespace(
            output_text=next(self.outputs),
            usage=SimpleNamespace(input_tokens=10, output_tokens=10),
        )


class FakeModelClient:
    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)


class DurableJobWorkflowE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = main.DB_PATH
        main.DB_PATH = Path(self.temp.name) / "workflow.sqlite3"
        main.init_db()
        self.client = TestClient(main.app)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        main.DB_PATH = self.previous_db
        self.temp.cleanup()

    def create_task(self, title="시장 조사", request="신규 사업 아이템 시장 조사"):
        response = self.client.post("/api/tasks", json={"title": title, "request": request, "selected_employees": [], "route": "navi"})
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        contract = self.client.post(
            f"/api/tasks/{task['id']}/contract",
            json={"allowed_paths": ["."], "allowed_commands": [], "acceptance_criteria": ["근거 있는 결과"]},
        )
        self.assertEqual(contract.status_code, 200, contract.text)
        with main.database() as db:
            db.execute(
                "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"WS-{task['id'].split('-')[-1]}", task["id"], str(self.workspace), str(self.workspace), "in_place", "ready", main.utc_now()),
            )
        return task

    def claim_and_process(self):
        job = worker.claim_job()
        self.assertIsNotNone(job)
        worker.process(job)
        return job

    def test_glm_builds_dynamic_cross_department_plan(self):
        output = """{
          "summary":"공식·산업·고객 근거를 교차 검증해 하나의 사업안을 결정한다.",
          "artifact_kind":"market_decision_report",
          "final_owner":"FRAME",
          "workspace_context":"none",
          "requires_web_research":true,
          "evidence_strategy":"최신 공식 통계, 산업 자료, 고객 문제 근거를 독립 출처로 교차 검증한다.",
          "phases":[
            {"id":"research","department":"growth-marketing","lead_id":"GROW","objective":"시장·고객·경쟁 대안을 조사한다.","output":"출처가 연결된 대안 비교표","handoff_to":"FRAME","depends_on":[]},
            {"id":"decision","department":"product-experience","lead_id":"FRAME","objective":"근거를 평가해 단일 추천안을 결정한다.","output":"최종 의사결정 보고서","handoff_to":null,"depends_on":["research"]}
          ],
          "reason":"조사와 제품 의사결정을 분리하고 명시적으로 인계한다."
        }"""
        with patch.object(main, "model_key", return_value="configured"), patch.object(main, "model_client", return_value=FakeModelClient([output])):
            roster, items, reason, usage = main.select_roster_with_model("새로운 기회를 조사하고 실행 가능한 사업안을 제안해줘")
        self.assertEqual(roster, ["GROW", "FRAME"])
        self.assertEqual([owner for owner, _ in items], ["GROW", "FRAME"])
        self.assertEqual(reason, "공식·산업·고객 근거를 교차 검증해 하나의 사업안을 결정한다.")
        self.assertTrue(usage["plan"]["requires_web_research"])
        self.assertEqual(usage["plan"]["workspace_context"], "none")
        self.assertEqual(usage["plan"]["phases"][1]["depends_on"], ["research"])

    def test_scheduler_never_expands_to_unproposed_workers(self):
        task = self.create_task("팀장 직접 실행", "조사 결과를 통합해 결정")
        with main.database() as db:
            db.execute("INSERT INTO task_assignments VALUES (?, ?)", (task["id"], "FRAME"))
            db.execute(
                "INSERT INTO action_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("ACT-001-01", task["id"], None, "FRAME", "FRAME 팀장 직접 통합", 1, "[]", "proposed"),
            )
            db.execute("UPDATE tasks SET state = 'awaiting_worker_selection' WHERE id = ?", (task["id"],))
        worker.schedule_autonomous_tasks()
        scheduled = self.client.get(f"/api/tasks/{task['id']}").json()
        execute = next(job for job in scheduled["jobs"] if job["kind"] == "execute")
        self.assertEqual(execute["payload"]["employee_ids"], ["FRAME"])
        self.assertNotIn("MOSS", execute["payload"]["employee_ids"])

    def test_navi_to_review_completes_with_one_user_choice(self):
        task = self.create_task()
        queued = self.client.post(f"/api/tasks/{task['id']}/jobs/plan", json={})
        self.assertEqual(queued.status_code, 202, queued.text)

        fake_client = FakeModelClient([
            "실제 요청 기준으로 회의를 시작합니다.",
            '{"message":"성장 관점 조사를 PULSE에게 맡깁니다.","assignments":[{"worker_id":"PULSE","description":"시장 규모와 경쟁 근거를 웹 검색해 보고서 작성"}]}',
            "# 최종 추천안\n\n## 추천\n소상공인 AI 비서를 단일 추천안으로 선택한다.\n\n## 대안\n자격증 플랫폼은 고객 획득비용 불확실성 때문에 제외한다.\n\n## 출처\nhttps://example.com/source\n",
            '{"verdict":"changes_requested","findings":"90일 검증 계획과 KPI를 보강하세요."}',
            "# 최종 추천안\n\n## 추천\n소상공인 AI 비서를 단일 추천안으로 선택한다.\n\n## 대안\n자격증 플랫폼은 고객 획득비용 불확실성 때문에 제외한다.\n\n## 90일 검증 계획\n30일 고객 인터뷰, 60일 MVP, 90일 유료 전환 검증.\n\n## KPI\n유료 전환율과 고객 획득비용을 측정한다.\n\n## 출처\nhttps://example.com/source\n",
            '{"verdict":"pass","findings":"웹 출처와 실행 결과 확인 완료"}',
        ])

        def fake_agent_run(task_id, payload):
            with main.database() as db:
                db.execute(
                    "INSERT OR REPLACE INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"EVD-{task_id}-WEB", task_id, None, "web_source", "pass", "hash", 0, main.utc_now()),
                )
                db.execute(
                    "INSERT INTO agent_messages (task_id, employee_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, payload.employee_id, "run", "시장 조사 결과와 출처 URL", main.utc_now()),
                )
                deliverable = main.persist_deliverable(
                    db,
                    self.workspace,
                    task_id,
                    payload.employee_id,
                    "department_draft",
                    "# 부서 조사\n\n근거 기반 시장 조사 결과\n",
                    filename=f"departments/{payload.employee_id}.md",
                    status="department_draft",
                )
            return {
                "employee_id": payload.employee_id,
                "tier": "worker",
                "model": "mock",
                "summary": "시장 조사 결과와 출처 URL",
                "changed_files": [deliverable["path"]],
                "commands": [],
                "evidence_id": f"EVD-{task_id}-WEB",
                "deliverable": deliverable,
                "state": "executing",
            }

        with patch.object(main, "select_roster_with_model", return_value=(["GROW"], [("GROW", "시장 조사 범위")], "GROW만 필요", None)), \
             patch.object(main, "model_client", return_value=fake_client), \
             patch.object(main, "run_agent", side_effect=fake_agent_run), \
             patch.object(main, "require_skill_ready", return_value=None):
            self.claim_and_process()
            planned = self.client.get(f"/api/tasks/{task['id']}").json()
            self.assertEqual(planned["state"], "awaiting_lead_selection")

            selected = self.client.post(f"/api/tasks/{task['id']}/select-leads", json={"employee_ids": ["GROW"]})
            self.assertEqual(selected.status_code, 200, selected.text)
            duplicate = self.client.post(f"/api/tasks/{task['id']}/select-leads", json={"employee_ids": ["GROW"]})
            self.assertEqual(duplicate.status_code, 409)

            self.claim_and_process()
            after_meeting = self.client.get(f"/api/tasks/{task['id']}").json()
            chronological = list(reversed(after_meeting["job_events"]))
            first_model = next(index for index, event in enumerate(chronological) if event["type"] == "model.started" and event["job_id"].endswith("-002"))
            seated = {event["agent_id"] for event in chronological[:first_model] if event["type"] == "agent.at_location"}
            self.assertEqual(seated, {"NAVI", "GROW"})
            worker.schedule_autonomous_tasks()
            delegated = self.client.get(f"/api/tasks/{task['id']}").json()
            self.assertEqual(delegated["state"], "executing")
            self.assertEqual([item["owner"] for item in delegated["action_items"]], ["PULSE"])

            self.claim_and_process()
            reviewing = self.client.get(f"/api/tasks/{task['id']}").json()
            self.assertEqual(reviewing["state"], "synthesizing")

            self.claim_and_process()
            reviewing = self.client.get(f"/api/tasks/{task['id']}").json()
            self.assertEqual(reviewing["state"], "lead_review_running", reviewing["jobs"])

            self.claim_and_process()
            reworking = self.client.get(f"/api/tasks/{task['id']}").json()
            self.assertEqual(reworking["state"], "synthesizing")

            self.claim_and_process()
            rereviewing = self.client.get(f"/api/tasks/{task['id']}").json()
            self.assertEqual(rereviewing["state"], "lead_review_running")

            self.claim_and_process()

        completed = self.client.get(f"/api/tasks/{task['id']}").json()
        self.assertEqual(completed["state"], "completed")
        self.assertEqual([job["kind"] for job in completed["jobs"]].count("meeting"), 1)
        self.assertTrue(any(message["kind"] == "meeting" for message in completed["agent_messages"]))
        self.assertTrue(any(item["type"] == "lead_review" and item["status"] == "pass" for item in completed["evidence"]))
        self.assertTrue(any(item["status"] == "completed" for item in completed["action_items"]))
        self.assertEqual([review["verdict"] for review in reversed(completed["reviews"])], ["changes_requested", "pass"])
        self.assertEqual({review["reviewer_id"] for review in completed["reviews"]}, {"GUARD"})
        self.assertTrue(all(phase["status"] == "completed" and phase["artifact_ids"] for phase in completed["phases"]))
        final = next(item for item in completed["deliverables"] if item["status"] == "approved")
        self.assertEqual(final["path"], f"AI_OFFICE_OUTPUTS/{task['id']}/FINAL.md")
        self.assertTrue((self.workspace / final["path"]).is_file())

    def test_pause_resume_cancel_and_orphan_recovery(self):
        task = self.create_task("제어 테스트", "파일 검토")
        with main.database() as db:
            job = main.enqueue_job(db, task["id"], "execute", {"workspace_id": "WS-001", "employee_ids": ["PULSE"], "instruction": "검토"})
            db.execute("UPDATE jobs SET state='running', lease_owner=?, heartbeat_at=? WHERE id=?", (worker.WORKER_ID, main.utc_now(), job["id"]))
            db.execute("UPDATE tasks SET state='executing' WHERE id=?", (task["id"],))

        paused_request = self.client.post(f"/api/jobs/{job['id']}/control", json={"action": "pause"})
        self.assertEqual(paused_request.status_code, 200, paused_request.text)
        self.assertFalse(worker.safe_point(job))
        paused = self.client.get(f"/api/tasks/{task['id']}").json()
        self.assertEqual(paused["state"], "paused")

        resumed = self.client.post(f"/api/jobs/{job['id']}/control", json={"action": "resume"})
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}").json()["state"], "executing")

        cancelled = self.client.post(f"/api/tasks/{task['id']}/cancel", json={})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["state"], "cancelled")

        orphan = self.create_task("복구 테스트", "중단 복구")
        with main.database() as db:
            old = main.enqueue_job(db, orphan["id"], "plan", {})
            db.execute("UPDATE jobs SET state='running', lease_owner='old-worker' WHERE id=?", (old["id"],))
            db.execute("UPDATE tasks SET state='planning' WHERE id=?", (orphan["id"],))
        worker.recover_orphaned_jobs()
        recovered = self.client.get(f"/api/tasks/{orphan['id']}").json()
        self.assertEqual(recovered["state"], "blocked")
        self.assertEqual(recovered["jobs"][0]["state"], "interrupted")

    def test_token_limit_warns_without_stopping_and_failed_job_retries(self):
        task = self.create_task("긴 실행", "완료될 때까지 파일을 점검")
        with main.database() as db:
            db.execute("UPDATE task_contracts SET token_limit = 1000 WHERE task_id = ?", (task["id"],))
            db.execute(
                "INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, error, created_at) "
                "VALUES (?, 'mock', 1200, 50, 0, NULL, ?)",
                (task["id"], main.utc_now()),
            )
            main.require_runnable(db, task["id"])
            main.require_runnable(db, task["id"])
            warning_count = db.execute(
                "SELECT COUNT(*) FROM job_events WHERE task_id = ? AND type = 'budget.warning'",
                (task["id"],),
            ).fetchone()[0]
            self.assertEqual(warning_count, 1)
            job = main.enqueue_job(
                db,
                task["id"],
                "execute",
                {"workspace_id": f"WS-{task['id'].split('-')[-1]}", "employee_ids": ["PULSE"], "instruction": task["request"]},
            )
            db.execute("UPDATE jobs SET state = 'failed', error = 'provider error' WHERE id = ?", (job["id"],))
            db.execute("UPDATE tasks SET state = 'blocked' WHERE id = ?", (task["id"],))

        retried = self.client.post(f"/api/jobs/{job['id']}/retry", json={})
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["state"], "queued")
        refreshed = self.client.get(f"/api/tasks/{task['id']}").json()
        self.assertEqual(refreshed["state"], "executing")

    def test_pending_model_call_obeys_cancel_without_deadline(self):
        task = self.create_task("취소 가능한 호출", "긴 모델 호출")
        with main.database() as db:
            job = main.enqueue_job(db, task["id"], "lead_review", {"lead_id": "BUILD"})
            db.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (job["id"],))

        started = threading.Event()
        release = threading.Event()

        class BlockingResponses:
            def create(self, **_kwargs):
                started.set()
                release.wait(5)
                return SimpleNamespace(output_text="late")

        def request_cancel():
            started.wait(2)
            with main.database() as db:
                db.execute("UPDATE jobs SET state = 'cancel_requested' WHERE id = ?", (job["id"],))

        controller = threading.Thread(target=request_cancel)
        controller.start()
        began = time.monotonic()
        with self.assertRaises(main.JobControlSignal):
            main.cancellable_model_response(SimpleNamespace(responses=BlockingResponses()), task["id"], job["id"], model="mock", input="test")
        self.assertLess(time.monotonic() - began, 2)
        release.set()
        controller.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
