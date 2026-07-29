import tempfile
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
                (f"WS-{task['id'].split('-')[-1]}", task["id"], str(self.workspace), str(self.workspace), "copy", "ready", main.utc_now()),
            )
        return task

    def claim_and_process(self):
        job = worker.claim_job()
        self.assertIsNotNone(job)
        worker.process(job)
        return job

    def test_navi_to_review_completes_with_one_user_choice(self):
        task = self.create_task()
        queued = self.client.post(f"/api/tasks/{task['id']}/jobs/plan", json={})
        self.assertEqual(queued.status_code, 202, queued.text)

        fake_client = FakeModelClient([
            "실제 요청 기준으로 회의를 시작합니다.",
            '{"message":"성장 관점 조사를 PULSE에게 맡깁니다.","assignments":[{"worker_id":"PULSE","description":"시장 규모와 경쟁 근거를 웹 검색해 보고서 작성"}]}',
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
            return {
                "employee_id": payload.employee_id,
                "tier": "worker",
                "model": "mock",
                "summary": "시장 조사 결과와 출처 URL",
                "changed_files": [],
                "commands": [],
                "evidence_id": f"EVD-{task_id}-WEB",
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
            self.assertEqual(reviewing["state"], "lead_review_running")

            self.claim_and_process()

        completed = self.client.get(f"/api/tasks/{task['id']}").json()
        self.assertEqual(completed["state"], "completed")
        self.assertEqual([job["kind"] for job in completed["jobs"]].count("meeting"), 1)
        self.assertTrue(any(message["kind"] == "meeting" for message in completed["agent_messages"]))
        self.assertTrue(any(item["type"] == "lead_review" and item["status"] == "pass" for item in completed["evidence"]))
        self.assertTrue(any(item["status"] == "completed" for item in completed["action_items"]))

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


if __name__ == "__main__":
    unittest.main()
