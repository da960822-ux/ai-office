"""Acceptance tests for durable sessions, permissions, artifacts, and worktrees."""
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api import agent_worktree, main
from apps.api.artifact_renderer import formats_for_request, render_bundle
from apps.api.runtime_context import load_session_context, record_session_turn


class RuntimeHardeningTests(unittest.TestCase):
    def test_session_survives_turns_and_keeps_bounded_recent_context(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        for index in range(10):
            record_session_turn(
                db,
                "TASK-1",
                "BUILD",
                input_summary=f"input {index}",
                output_summary=f"output {index}",
                tool_history=[{"tool": "search_files", "arguments": {"query": str(index)}, "result": {"count": 1}}],
                response_id=f"response-{index}",
            )
        context = load_session_context(db, "TASK-1", "BUILD")
        self.assertEqual(context["turn_count"], 10)
        self.assertEqual(len(context["recent_turns"]), 6)
        self.assertLessEqual(len(context["summary"]), 12_000)
        self.assertEqual(context["last_response_id"], "response-9")

    def test_permission_rules_support_allow_ask_and_deny(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = main.DB_PATH
            main.DB_PATH = Path(temp) / "permissions.sqlite3"
            try:
                main.init_db()
                with main.database() as db:
                    now = main.utc_now()
                    db.execute(
                        "INSERT INTO tasks (id,title,request,state,created_at,updated_at) VALUES ('TASK-P','p','p','running',?,?)",
                        (now, now),
                    )
                    db.execute(
                        "INSERT INTO task_permission_rules (task_id,action,effect,pattern,created_at) "
                        "VALUES ('TASK-P','git_push','ask','*',?)",
                        (now,),
                    )
                    db.execute(
                        "INSERT INTO task_permission_rules (task_id,action,effect,pattern,created_at) "
                        "VALUES ('TASK-P','create_file','deny','secrets/*',?)",
                        (now,),
                    )
                    with self.assertRaises(HTTPException) as ask:
                        main.require_tool_permission(db, "TASK-P", "SHIP", "git_push", "release")
                    self.assertEqual(ask.exception.status_code, 428)
                    request = db.execute("SELECT id FROM permission_requests").fetchone()
                    db.execute("UPDATE permission_requests SET state='approved' WHERE id=?", (request["id"],))
                    main.require_tool_permission(db, "TASK-P", "SHIP", "git_push", "release")
                    with self.assertRaises(HTTPException) as deny:
                        main.require_tool_permission(db, "TASK-P", "BUILD", "create_file", "secrets/key.txt")
                    self.assertEqual(deny.exception.status_code, 403)
            finally:
                main.DB_PATH = previous

    def test_checkpoint_restores_state_and_stales_later_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = main.DB_PATH
            main.DB_PATH = Path(temp) / "checkpoint.sqlite3"
            try:
                main.init_db()
                with main.database() as db:
                    now = main.utc_now()
                    db.execute(
                        "INSERT INTO tasks (id,title,request,state,created_at,updated_at) "
                        "VALUES ('TASK-C','c','c','running',?,?)",
                        (now, now),
                    )
                    main.checkpoint(db, "TASK-C", "before-change")
                    checkpoint_id = db.execute("SELECT id FROM task_checkpoints").fetchone()["id"]
                    db.execute("UPDATE tasks SET state='blocked' WHERE id='TASK-C'")
                    db.execute(
                        "INSERT INTO evidence VALUES ('E-LATE','TASK-C',NULL,'verification','fail','hash',0,?)",
                        (main.utc_now(),),
                    )
                restored = main.restore_checkpoint("TASK-C", checkpoint_id)
                self.assertEqual(restored["state"], "running")
                late = next(item for item in restored["evidence"] if item["id"] == "E-LATE")
                self.assertEqual(late["stale"], 1)
            finally:
                main.DB_PATH = previous

    def test_retry_uses_unused_failure_playbook_before_escalating(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = main.DB_PATH
            main.DB_PATH = Path(temp) / "retry.sqlite3"
            try:
                main.init_db()
                client = TestClient(main.app)
                task = client.post("/api/tasks", json={"title": "retry", "request": "fix failing test"}).json()
                client.post(
                    f"/api/tasks/{task['id']}/contract",
                    json={"allowed_paths": ["."], "allowed_commands": [], "acceptance_criteria": ["test passes"], "retry_limit": 2},
                )
                first = client.post(f"/api/tasks/{task['id']}/retry", json={"failure_class": "test"})
                second = client.post(f"/api/tasks/{task['id']}/retry", json={"failure_class": "test"})
                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 200)
                attempts = second.json()["retry_attempts"]
                self.assertEqual(len({item["strategy"] for item in attempts}), 2)
                third = client.post(f"/api/tasks/{task['id']}/retry", json={"failure_class": "test"})
                self.assertEqual(third.json()["state"], "escalated")
            finally:
                main.DB_PATH = previous

    def test_markdown_renders_to_office_formats_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            final = Path(temp) / "FINAL.md"
            final.write_text("# 최종 결정\n\n근거가 연결된 결과입니다.\n", encoding="utf-8")
            rendered = render_bundle(final, ["html", "docx", "pdf", "xlsx", "pptx", "hwpx"])
            self.assertEqual({path.suffix for path in rendered}, {".html", ".docx", ".pdf", ".xlsx", ".pptx", ".hwpx", ".json"})
            self.assertTrue(all(path.stat().st_size > 0 for path in rendered))
        self.assertEqual(
            formats_for_request("발표 슬라이드와 HWPX 한글 문서로 만들어줘", "financial_model_report"),
            ["html", "docx", "pdf", "xlsx", "pptx", "hwpx"],
        )

    def test_agent_worktree_requires_review_gate_before_base_integration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "project"
            base.mkdir()
            subprocess.run(["git", "init"], cwd=base, check=True, capture_output=True)
            (base / "app.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.txt"], cwd=base, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "base"],
                cwd=base,
                check=True,
                capture_output=True,
            )
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            db.execute(
                "CREATE TABLE workspaces (id TEXT PRIMARY KEY, task_id TEXT, source_root TEXT, path TEXT, "
                "strategy TEXT, status TEXT, created_at TEXT)"
            )
            db.execute(
                "INSERT INTO workspaces VALUES ('WS','TASK-W',?,?, 'in_place','ready','now')",
                (str(base), str(base)),
            )
            isolated = agent_worktree.prepare(
                db,
                root=root,
                task_id="TASK-W",
                base_workspace_id="WS",
                employee_id="BUILD",
                now="now",
            )
            (Path(isolated["path"]) / "app.txt").write_text("agent\n", encoding="utf-8")
            pending = agent_worktree.commit_for_review(isolated, task_id="TASK-W", employee_id="BUILD")
            self.assertTrue(pending["changed"])
            self.assertEqual((base / "app.txt").read_text(encoding="utf-8"), "base\n")
            result = agent_worktree.integrate_reviewed(isolated, pending["commit"])
            self.assertTrue(result["integrated"])
            self.assertEqual((base / "app.txt").read_text(encoding="utf-8"), "agent\n")
            agent_worktree.cleanup(base, isolated)


if __name__ == "__main__":
    unittest.main()
