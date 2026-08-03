"""Unit tests for scripts/skill_ab_report.py.

Builds a temporary SQLite DB with synthetic task_phases/reviews/retry_attempts/
model_usage rows and checks the A/B aggregation math, the insufficient-sample
guard, and the empty-DB exit path — never touches the real DB.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import skill_ab_report as report


SCHEMA = """
CREATE TABLE task_phases (
    task_id TEXT NOT NULL, phase_id TEXT NOT NULL, task_kind TEXT NOT NULL,
    skill_ids TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE retry_attempts (
    task_id TEXT NOT NULL, failure_class TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE reviews (
    task_id TEXT NOT NULL, reviewer_id TEXT NOT NULL, verdict TEXT NOT NULL,
    findings TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE model_usage (
    task_id TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL, created_at TEXT NOT NULL
);
"""


def make_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def add_phase(db, task_id, task_kind, skill_ids, status):
    db.execute(
        "INSERT INTO task_phases (task_id, phase_id, task_kind, skill_ids, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, f"{task_id}-P1", task_kind, json.dumps(skill_ids), status, "2026-01-01T00:00:00Z"),
    )


def add_review(db, task_id, verdict):
    db.execute(
        "INSERT INTO reviews (task_id, reviewer_id, verdict, findings, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, "REV", verdict, "[]", "2026-01-01T00:00:00Z"),
    )


def add_cost(db, task_id, cost_usd):
    db.execute(
        "INSERT INTO model_usage (task_id, model, input_tokens, output_tokens, cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, "test-model", 100, 100, cost_usd, "2026-01-01T00:00:00Z"),
    )


class KnownAnswerTestCase(unittest.TestCase):
    """6 treatment phases (5 completed) vs 6 control phases (2 completed):
    a clean known-answer dataset that also clears the default min-n of 5."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.sqlite3"
        db = make_db(self.db_path)
        for i in range(6):
            task_id = f"TREAT-{i}"
            status = report.PHASE_SUCCESS_STATUS if i < 5 else "failed"
            add_phase(db, task_id, "writing", ["skill-x"], status)
            add_review(db, task_id, report.REVIEW_PASS_VERDICT if i < 5 else "fail")
            add_cost(db, task_id, 1.0)
        for i in range(6):
            task_id = f"CTRL-{i}"
            status = report.PHASE_SUCCESS_STATUS if i < 2 else "failed"
            add_phase(db, task_id, "writing", [], status)
            add_review(db, task_id, report.REVIEW_PASS_VERDICT if i < 2 else "fail")
            add_cost(db, task_id, 2.0)
        db.commit()
        db.close()

    def tearDown(self):
        self._tmp.cleanup()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def test_success_rate_and_cost_aggregation(self):
        connection = self.connect()
        try:
            comparisons = report.build_comparisons(connection, None, min_n=5)
        finally:
            connection.close()
        self.assertEqual(len(comparisons), 1)
        c = comparisons[0]
        self.assertEqual(c["skill_id"], "skill-x")
        self.assertEqual(c["treatment"]["n_phases"], 6)
        self.assertEqual(c["control"]["n_phases"], 6)
        self.assertAlmostEqual(c["treatment"]["success_rate"], 5 / 6)
        self.assertAlmostEqual(c["control"]["success_rate"], 2 / 6)
        self.assertAlmostEqual(c["treatment"]["mean_cost_usd_per_task"], 1.0)
        self.assertAlmostEqual(c["control"]["mean_cost_usd_per_task"], 2.0)
        self.assertTrue(c["sufficient"])
        self.assertEqual(c["recommendation"], "PROMOTE")


class InsufficientSampleTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.sqlite3"
        db = make_db(self.db_path)
        # Only 2 treatment phases: below the default min_n of 5.
        for i in range(2):
            task_id = f"TREAT-{i}"
            add_phase(db, task_id, "research", ["skill-y"], report.PHASE_SUCCESS_STATUS)
        for i in range(10):
            task_id = f"CTRL-{i}"
            add_phase(db, task_id, "research", [], report.PHASE_SUCCESS_STATUS)
        db.commit()
        db.close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_undersampled_comparison_is_insufficient_with_no_recommendation(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            comparisons = report.build_comparisons(connection, None, min_n=5)
        finally:
            connection.close()
        self.assertEqual(len(comparisons), 1)
        c = comparisons[0]
        self.assertFalse(c["sufficient"])
        self.assertEqual(c["recommendation"], "INSUFFICIENT")


class SharedTaskTestCase(unittest.TestCase):
    """One task holding phases on both sides must not lend its retries, reviews and
    cost to both arms -- those are recorded per task, so a shared task is dropped
    from the task-level metrics of both arms."""

    def test_shared_task_is_excluded_from_task_level_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared.sqlite3"
            db = make_db(db_path)
            add_phase(db, "MIXED", "writing", ["skill-x"], report.PHASE_SUCCESS_STATUS)
            add_phase(db, "MIXED", "writing", [], report.PHASE_SUCCESS_STATUS)
            add_cost(db, "MIXED", 99.0)
            add_phase(db, "TREAT", "writing", ["skill-x"], report.PHASE_SUCCESS_STATUS)
            add_cost(db, "TREAT", 1.0)
            add_phase(db, "CTRL", "writing", [], report.PHASE_SUCCESS_STATUS)
            add_cost(db, "CTRL", 2.0)
            db.commit()
            db.close()

            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            try:
                comparisons = report.build_comparisons(connection, None, min_n=1)
            finally:
                connection.close()
        c = comparisons[0]
        self.assertEqual(c["shared_tasks_excluded"], 1)
        self.assertEqual(c["treatment"]["n_phases"], 2)
        self.assertEqual(c["treatment"]["n_tasks"], 1)
        self.assertAlmostEqual(c["treatment"]["mean_cost_usd_per_task"], 1.0)
        self.assertAlmostEqual(c["control"]["mean_cost_usd_per_task"], 2.0)


class EmptyDatabaseTestCase(unittest.TestCase):
    def test_empty_db_exits_zero_with_no_history_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.sqlite3"
            db = make_db(db_path)
            db.commit()
            db.close()

            import subprocess
            import sys

            result = subprocess.run(
                [sys.executable, str(report.ROOT / "scripts" / "skill_ab_report.py"), "--db", str(db_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("No run history yet", result.stdout)

    def test_missing_db_file_exits_zero_with_no_history_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "does_not_exist.sqlite3"

            import subprocess
            import sys

            result = subprocess.run(
                [sys.executable, str(report.ROOT / "scripts" / "skill_ab_report.py"), "--db", str(db_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("No run history yet", result.stdout)


if __name__ == "__main__":
    unittest.main()
