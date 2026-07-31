"""Unit tests for apps.api.research_quality."""
from __future__ import annotations

import json
import sqlite3
import unittest

from apps.api.research_quality import (
    DEFAULT_THRESHOLDS,
    claim_source_coverage,
    contradiction_resolution,
    evaluate_research_quality,
    load_task_research,
    primary_source_ratio,
    recommendation_linkage,
)


def _source(url: str, query: str = "verified-original") -> dict:
    return {
        "id": 1,
        "task_id": "T1",
        "employee_id": "E1",
        "query": query,
        "title": "title",
        "url": url,
        "snippet": "snippet",
        "created_at": "2026-01-01T00:00:00Z",
    }


def _claim(
    source_url: str,
    claim: str = "The market grew by twelve percent year over year according to the report",
    contradictions: list | None = None,
) -> dict:
    return {
        "id": 1,
        "task_id": "T1",
        "employee_id": "E1",
        "claim": claim,
        "source_url": source_url,
        "publisher": "Pub",
        "published_at": "2026-01-01",
        "retrieved_span": "2026-01-01",
        "confidence": 0.9,
        "contradictions": contradictions or [],
        "created_at": "2026-01-01T00:00:00Z",
    }


class HappyPathTests(unittest.TestCase):
    def test_all_metrics_pass_and_aggregate_passes(self):
        sources = [_source("https://a.example/1"), _source("https://b.example/2")]
        artifact = (
            "The market grew by twelve percent year over year according to the report. "
            "Sources: https://a.example/1 https://b.example/2"
        )
        claims = [
            _claim("https://a.example/1"),
            _claim(
                "https://b.example/2",
                claim="Revenue declined sharply due to seasonal factors last quarter overall",
                contradictions=["Some analysts dispute the seasonal decline explanation entirely here"],
            ),
        ]

        coverage = claim_source_coverage(claims, sources)
        ratio = primary_source_ratio(sources)
        resolution = contradiction_resolution(claims, artifact)
        linkage = recommendation_linkage(claims, artifact)

        self.assertEqual(coverage["score"], 1.0)
        self.assertEqual(ratio["score"], 1.0)
        self.assertEqual(resolution["score"], 1.0)
        self.assertEqual(linkage["score"], 1.0)

        gate = evaluate_research_quality(coverage, ratio, resolution, linkage)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["failures"], [])


class EachMetricFailsIndependentlyTests(unittest.TestCase):
    def setUp(self):
        self.sources = [_source("https://a.example/1"), _source("https://b.example/2")]
        self.artifact = (
            "The market grew by twelve percent year over year according to the report. "
            "Sources: https://a.example/1 https://b.example/2"
        )
        self.claims = [
            _claim("https://a.example/1"),
            _claim(
                "https://b.example/2",
                claim="Revenue declined sharply due to seasonal factors last quarter overall",
                contradictions=["Some analysts dispute the seasonal decline explanation entirely here"],
            ),
        ]

    def test_claim_source_coverage_fails_on_unverified_source(self):
        claims = self.claims + [_claim("https://unverified.example/x", claim="An unrelated unverified claim")]
        coverage = claim_source_coverage(claims, self.sources)
        self.assertLess(coverage["score"], 1.0)
        self.assertEqual(len(coverage["offenders"]), 1)
        self.assertEqual(coverage["offenders"][0]["source_url"], "https://unverified.example/x")

        ratio = primary_source_ratio(self.sources)
        resolution = contradiction_resolution(self.claims, self.artifact)
        linkage = recommendation_linkage(self.claims, self.artifact)
        gate = evaluate_research_quality(coverage, ratio, resolution, linkage)
        self.assertFalse(gate["passed"])
        names = {f["metric"] for f in gate["failures"]}
        self.assertIn("claim_source_coverage", names)

    def test_primary_source_ratio_fails_with_many_web_search_sources(self):
        sources = self.sources + [
            _source("https://search1.example", query="web_search"),
            _source("https://search2.example", query="web_search"),
            _source("https://search3.example", query="web_search"),
        ]
        ratio = primary_source_ratio(sources)
        self.assertLess(ratio["score"], DEFAULT_THRESHOLDS["primary_source_ratio"])
        self.assertEqual(
            set(ratio["offenders"]),
            {"https://search1.example", "https://search2.example", "https://search3.example"},
        )

        coverage = claim_source_coverage(self.claims, sources)
        resolution = contradiction_resolution(self.claims, self.artifact)
        linkage = recommendation_linkage(self.claims, self.artifact)
        gate = evaluate_research_quality(coverage, ratio, resolution, linkage)
        self.assertFalse(gate["passed"])
        names = {f["metric"] for f in gate["failures"]}
        self.assertIn("primary_source_ratio", names)

    def test_contradiction_resolution_fails_when_unaddressed(self):
        claims = self.claims + [
            _claim(
                "https://c.example/3",
                claim="A completely different unrelated claim about pricing trends",
                contradictions=["Nobody in the artifact ever mentions this particular dispute at all"],
            )
        ]
        sources = self.sources + [_source("https://c.example/3")]
        resolution = contradiction_resolution(claims, self.artifact)
        self.assertLess(resolution["score"], 1.0)
        self.assertEqual(len(resolution["offenders"]), 1)
        self.assertEqual(resolution["offenders"][0]["source_url"], "https://c.example/3")

        coverage = claim_source_coverage(claims, sources)
        ratio = primary_source_ratio(sources)
        linkage = recommendation_linkage(claims, self.artifact)
        gate = evaluate_research_quality(coverage, ratio, resolution, linkage)
        self.assertFalse(gate["passed"])
        names = {f["metric"] for f in gate["failures"]}
        self.assertIn("contradiction_resolution", names)

    def test_recommendation_linkage_fails_on_orphaned_claim(self):
        orphans = [
            _claim(
                f"https://orphan.example/{i}",
                claim=f"This orphaned claim number {i} never shows up in the final artifact text",
            )
            for i in range(3)
        ]
        claims = self.claims + orphans
        sources = self.sources + [_source(o["source_url"]) for o in orphans]
        linkage = recommendation_linkage(claims, self.artifact)
        self.assertLess(linkage["score"], DEFAULT_THRESHOLDS["recommendation_linkage"])
        self.assertEqual(len(linkage["offenders"]), 3)

        coverage = claim_source_coverage(claims, sources)
        ratio = primary_source_ratio(sources)
        resolution = contradiction_resolution(claims, self.artifact)
        gate = evaluate_research_quality(coverage, ratio, resolution, linkage)
        self.assertFalse(gate["passed"])
        names = {f["metric"] for f in gate["failures"]}
        self.assertIn("recommendation_linkage", names)


class ZeroDenominatorTests(unittest.TestCase):
    def test_zero_claims_does_not_score_1_and_fails_gate(self):
        sources = [_source("https://a.example/1")]
        coverage = claim_source_coverage([], sources)
        linkage = recommendation_linkage([], "any artifact text here")
        self.assertEqual(coverage["score"], 0.0)
        self.assertEqual(linkage["score"], 0.0)
        self.assertTrue(coverage["offenders"])
        self.assertTrue(linkage["offenders"])

        ratio = primary_source_ratio(sources)
        resolution = contradiction_resolution([], "any artifact text here")
        self.assertEqual(resolution["score"], 0.0)

        gate = evaluate_research_quality(coverage, ratio, resolution, linkage)
        self.assertFalse(gate["passed"])

    def test_zero_sources_scores_zero_not_one(self):
        ratio = primary_source_ratio([])
        self.assertEqual(ratio["score"], 0.0)
        self.assertTrue(ratio["offenders"])

    def test_zero_flagged_contradictions_scores_zero_not_one(self):
        claims = [_claim("https://a.example/1", contradictions=[])]
        resolution = contradiction_resolution(claims, "artifact text")
        self.assertEqual(resolution["score"], 0.0)
        self.assertTrue(resolution["offenders"])


class NeedleEdgeCaseTests(unittest.TestCase):
    def test_empty_claim_text_never_matches(self):
        claims = [_claim("https://no-url-hit.example/1", claim="")]
        # Artifact text is long and unrelated; source_url is deliberately not
        # present in the artifact so only the claim-text needle path is exercised.
        artifact = "This artifact discusses entirely different topics and sources."
        linkage = recommendation_linkage(claims, artifact)
        self.assertEqual(linkage["score"], 0.0)
        self.assertEqual(len(linkage["offenders"]), 1)

    def test_short_needle_below_floor_never_matches(self):
        # "Hi" (2 chars) is far below MIN_NEEDLE_CHARS; artifact contains "Hi"
        # incidentally inside another word, which must NOT count as a match.
        claims = [_claim("https://no-url-hit.example/2", claim="Hi")]
        artifact = "This artifact discusses Higher education trends broadly."
        linkage = recommendation_linkage(claims, artifact)
        self.assertEqual(linkage["score"], 0.0)
        self.assertEqual(len(linkage["offenders"]), 1)

    def test_needle_at_or_above_floor_matches(self):
        claims = [
            _claim(
                "https://no-url-hit.example/3",
                claim="Solar panel adoption accelerated across residential markets in 2025",
            )
        ]
        artifact = "Per the report, solar panel adoption accelerated across residential markets significantly."
        linkage = recommendation_linkage(claims, artifact)
        self.assertEqual(linkage["score"], 1.0)
        self.assertEqual(linkage["offenders"], [])


class LoadTaskResearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE research_sources (id INTEGER PRIMARY KEY, task_id TEXT, employee_id TEXT, "
            "query TEXT, title TEXT, url TEXT, snippet TEXT, created_at TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE research_claims (id INTEGER PRIMARY KEY, task_id TEXT, employee_id TEXT, "
            "claim TEXT, source_url TEXT, publisher TEXT, published_at TEXT, retrieved_span TEXT, "
            "confidence REAL, contradictions TEXT, created_at TEXT)"
        )
        self.conn.execute(
            "INSERT INTO research_sources VALUES (1, 'T1', 'E1', 'verified-original', 't', 'https://a.example', 's', 'now')"
        )
        self.conn.execute(
            "INSERT INTO research_claims VALUES (1, 'T1', 'E1', 'claim text', 'https://a.example', 'pub', "
            "'2026-01-01', '2026-01-01', 0.8, ?, 'now')",
            (json.dumps(["dispute one", "dispute two"]),),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_loads_and_parses_contradictions_json(self):
        data = load_task_research(self.conn, "T1")
        self.assertEqual(len(data["sources"]), 1)
        self.assertEqual(len(data["claims"]), 1)
        self.assertEqual(data["claims"][0]["contradictions"], ["dispute one", "dispute two"])
        self.assertEqual(data["sources"][0]["query"], "verified-original")

    def test_missing_task_returns_empty(self):
        data = load_task_research(self.conn, "NONEXISTENT")
        self.assertEqual(data["sources"], [])
        self.assertEqual(data["claims"], [])


if __name__ == "__main__":
    unittest.main()
