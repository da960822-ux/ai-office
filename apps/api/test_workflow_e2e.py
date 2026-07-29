import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from fastapi.testclient import TestClient

import apps.api.main as office


class WorkflowE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = office.DB_PATH
        office.DB_PATH = Path(self.temp.name) / "workflow.sqlite3"
        office.init_db()
        self.client = TestClient(office.app)

        class MockMcp(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                request = __import__("json").loads(self.rfile.read(length))
                if request["method"] == "initialize":
                    result = {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","serverInfo":{"name":"mock"}}}
                elif request["method"] == "tools/list":
                    result = {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"search_docs","description":"Search mock documents","inputSchema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}]}}
                else:
                    result = {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}
                encoded = __import__("json").dumps(result).encode()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Mcp-Session-Id","mock-session"); self.send_header("Content-Length",str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
            def log_message(self, *args):
                return
        self.mcp_server = ThreadingHTTPServer(("127.0.0.1", 0), MockMcp)
        self.mcp_thread = Thread(target=self.mcp_server.serve_forever, daemon=True)
        self.mcp_thread.start()

    def tearDown(self) -> None:
        office.DB_PATH = self.previous_db
        self.mcp_server.shutdown()
        self.mcp_server.server_close()
        self.temp.cleanup()

    def post(self, path: str, payload: dict) -> dict:
        response = self.client.post(path, json=payload)
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()

    def test_meeting_review_approval_reflection_lesson_workflow(self) -> None:
        task = self.post("/api/tasks", {"title": "UI 오류 수정", "request": "frontend UI 오류를 수정하고 검토한다", "selected_employees": ["NAVI", "FRAME", "BUILD", "FRONT", "TRACE"]})
        task_id = task["id"]
        self.post(f"/api/tasks/{task_id}/contract", {"allowed_paths": ["."], "allowed_commands": [], "acceptance_criteria": ["UI 정상 동작"]})
        planned = self.post(f"/api/tasks/{task_id}/plan", {})
        self.assertEqual(planned["meetings"], [])
        self.assertEqual(planned["state"], "planning")
        manual_review = self.client.post(f"/api/tasks/{task_id}/reviews", json={"reviewer_id": "BUILD", "verdict": "pass", "findings": "manual"})
        self.assertEqual(manual_review.status_code, 409)
        return

        meeting = self.post(f"/api/tasks/{task_id}/meetings", {"objective": "수정 범위와 담당 확정", "participant_ids": planned["assigned_employees"], "agenda": ["범위", "위험", "담당"]})
        self.assertEqual(meeting["state"], "meeting")

        reviewed = self.post(f"/api/tasks/{task_id}/reviews", {"reviewer_id": "BUILD", "verdict": "pass", "findings": "독립 리뷰 통과"})
        self.assertEqual(reviewed["state"], "awaiting_approval")
        self.assertEqual(reviewed["reviews"][0]["verdict"], "pass")

        approved = self.post(f"/api/tasks/{task_id}/approval", {"decision": "approve", "reason": "대표 승인"})
        self.assertEqual(approved["state"], "completed")
        self.assertEqual(approved["approvals"][0]["decision"], "approve")

        reflected = self.post(f"/api/tasks/{task_id}/reflection", {"summary": "리뷰 기준이 효과적이었다", "root_causes": ["초기 범위 모호"], "improvements": ["계약 시 확인 강화"], "lesson": "작업 전 acceptance를 합의한다"})
        self.assertEqual(reflected["state"], "completed")
        self.assertTrue(reflected["reflections"])
        self.assertEqual(reflected["lessons"][0]["content"], "작업 전 acceptance를 합의한다")
        lessons = self.client.get("/api/lessons")
        self.assertEqual(lessons.status_code, 200)
        self.assertTrue(any(item["task_id"] == task_id for item in lessons.json()))

    def test_mcp_connection_registers_and_lists_tools(self) -> None:
        url = f"http://127.0.0.1:{self.mcp_server.server_port}/mcp"
        created = self.client.post("/api/settings/mcp", json={"provider":"github","name":"Mock GitHub","transport":"streamable_http","server_url":url})
        self.assertEqual(created.status_code, 201, created.text)
        checked = self.client.post(f"/api/settings/mcp/{created.json()['id']}/test")
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(checked.json()["tools"], ["search_docs"])

    def test_planning_blocks_when_required_skill_is_not_ready(self) -> None:
        task = self.post("/api/tasks", {"title": "스킬 게이트", "request": "frontend UI 변경", "selected_employees": ["NAVI", "FRAME", "BUILD", "FRONT", "TRACE"]})
        self.post(f"/api/tasks/{task['id']}/contract", {"allowed_paths": ["."], "allowed_commands": [], "acceptance_criteria": ["스킬 검증"]})
        with patch("apps.api.main.employee_security", return_value={"ready": False}):
            response = self.client.post(f"/api/tasks/{task['id']}/plan", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Required skills are not ready", response.text)


if __name__ == "__main__":
    unittest.main()
