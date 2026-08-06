"""Regression tests for worker.py hardening: parse-failure visibility and bounded lock retries."""

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.api import main, worker


class RecordParseFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = main.DB_PATH
        main.DB_PATH = Path(self.temp.name) / "hardening.sqlite3"
        main.init_db()

    def tearDown(self):
        main.DB_PATH = self.previous_db
        self.temp.cleanup()

    def test_parse_failure_is_recorded_as_job_event(self):
        raw = "not-json garbage from the model"
        with main.database() as db:
            worker.record_parse_failure(db, "TASK-1", "lead_review_verdict", raw, job_id="JOB-1")
        with main.database() as db:
            row = db.execute(
                "SELECT task_id, job_id, type, summary, payload FROM job_events WHERE type = 'parse.failure'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["task_id"], "TASK-1")
        self.assertEqual(row["job_id"], "JOB-1")
        self.assertIn("lead_review_verdict", row["payload"])
        self.assertIn(raw, row["payload"])


class _FakeStop:
    """Stands in for threading.Event: never signals, and never actually sleeps."""

    def wait(self, timeout):
        return False


class MaintainJobLeaseRetryCapTests(unittest.TestCase):
    def test_lock_retry_loop_gives_up_after_cap_instead_of_looping_forever(self):
        @contextlib.contextmanager
        def _always_locked():
            raise sqlite3.OperationalError("database is locked")
            yield  # pragma: no cover - unreachable, keeps this a generator

        job = {"id": "JOB-1", "task_id": "TASK-1"}
        with patch.object(worker.main, "database", _always_locked):
            with self.assertRaises(sqlite3.OperationalError):
                worker.maintain_job_lease(job, _FakeStop())


if __name__ == "__main__":
    unittest.main()
