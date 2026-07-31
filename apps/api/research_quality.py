"""Score research provenance quality for a task's claims and sources.

Four independent metrics, each a pure function over plain dicts:

1. ``claim_source_coverage`` -- fraction of claims whose ``source_url`` is
   backed by a ``research_sources`` row with ``query == 'verified-original'``.
   (At write time ``record_research_claim`` in main.py already rejects claims
   without such a row, but rows can go stale after the fact -- e.g. the
   source row is deleted/edited later -- so this is re-checked here.)
2. ``primary_source_ratio`` -- of all distinct source URLs recorded for the
   task, the fraction that came from a verified-original row rather than a
   plain ``web_search`` snippet.
3. ``contradiction_resolution`` -- of the claims that recorded a non-empty
   ``contradictions`` list, the fraction "addressed" by the final artifact.
   ADDRESSED RULE (the one concrete rule, chosen because no resolution
   column exists anywhere in the schema): a claim's contradiction is
   considered addressed if the final artifact text contains, after
   normalization, either (a) the claim's exact ``source_url``, or (b) a
   normalized substring match of any one of its contradiction strings using
   the same bounded-prefix rule described below. Requiring the source URL is
   a reasonable proxy: an artifact that cites the very source the
   contradiction stems from has at least surfaced it for the reader, even
   if the artifact does not restate the contradiction verbatim.
4. ``recommendation_linkage`` -- fraction of claims the final artifact
   actually draws on, measured as the artifact text containing the claim's
   ``source_url`` or a normalized bounded-prefix substring of the claim
   text.

Text matching: normalization is casefold + collapse-all-whitespace-to-one-
space (``_normalize``). Claim/contradiction text is never required to match
verbatim -- a full sentence essentially never survives into a rewritten
artifact -- so matching uses a bounded leading portion of the normalized
string. The bound is ``NEEDLE_PREFIX_CHARS = 40``: long enough that a
40-character prefix is specific to one claim (collisions between unrelated
claims sharing the same first 40 characters are unlikely in practice), short
enough to survive light paraphrasing/reordering after the prefix. Needles
shorter than ``MIN_NEEDLE_CHARS`` (8) are never treated as a match target --
without this floor, an empty or near-empty ``source_url``/claim would match
any non-empty artifact text and silently push every metric to 1.0.

Zero-denominator behavior (documented per metric, and enforced by tests):
zero claims/sources must never present as a passing 1.0 score -- that is
exactly the loophole this module exists to close. Each metric returns
score ``0.0`` with a single explanatory offender when its denominator is
zero, so the aggregate gate below fails the task rather than waving it
through.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

NEEDLE_PREFIX_CHARS = 40
MIN_NEEDLE_CHARS = 8

# Default release-gate thresholds. Override per-call via the `thresholds`
# argument to `evaluate_research_quality`.
DEFAULT_THRESHOLDS: dict[str, float] = {
    # Matches the documented release gate in docs/RUNTIME_ROADMAP.md:
    # "at least 90% of material research claims linked to verified
    # original sources".
    "claim_source_coverage": 0.9,
    # Slightly looser than claim coverage: a handful of exploratory
    # web_search lookups alongside verified sources is normal research
    # hygiene, not a quality failure, so allow more slack than the claims
    # gate while still requiring primary sources to dominate.
    "primary_source_ratio": 0.7,
    # Contradiction resolution depends on a proxy rule (source-url or
    # substring presence) rather than a real resolution field, so it is
    # set below the claim-linkage bar to avoid over-penalizing on a fuzzy
    # signal while still catching claims that flagged a contradiction and
    # were never revisited at all.
    "contradiction_resolution": 0.6,
    # Recommendation linkage is the loosest bar: an artifact reasonably
    # synthesizes/aggregates claims rather than name-checking every one,
    # so only require a majority to show up in the final text.
    "recommendation_linkage": 0.5,
}


def _normalize(text: str) -> str:
    """Casefold and collapse all whitespace runs to a single space."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def _needle(text: str) -> str:
    """Bounded, normalized prefix used for substring matching."""
    return _normalize(text)[:NEEDLE_PREFIX_CHARS]


def _contains(haystack_normalized: str, needle: str) -> bool:
    """True if `needle` is a real (non-trivial) substring of the haystack."""
    if len(needle) < MIN_NEEDLE_CHARS:
        return False
    return needle in haystack_normalized


def load_task_research(conn: sqlite3.Connection, task_id: str) -> dict[str, list[dict[str, Any]]]:
    """Load a task's research_sources and research_claims as plain dicts.

    Keeps the scoring functions below DB-free and unit-testable. Parses
    the JSON-encoded `contradictions` column back into a list.
    """
    conn.row_factory = sqlite3.Row
    sources = [
        dict(row)
        for row in conn.execute(
            "SELECT id, task_id, employee_id, query, title, url, snippet, created_at "
            "FROM research_sources WHERE task_id = ?",
            (task_id,),
        ).fetchall()
    ]
    claims = []
    for row in conn.execute(
        "SELECT id, task_id, employee_id, claim, source_url, publisher, published_at, "
        "retrieved_span, confidence, contradictions, created_at "
        "FROM research_claims WHERE task_id = ?",
        (task_id,),
    ).fetchall():
        claim = dict(row)
        try:
            claim["contradictions"] = json.loads(claim["contradictions"]) if claim["contradictions"] else []
        except (TypeError, json.JSONDecodeError):
            claim["contradictions"] = []
        claims.append(claim)
    return {"sources": sources, "claims": claims}


def claim_source_coverage(
    claims: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    """Fraction of claims whose source_url is a verified-original source.

    Returns score 0.0 with a single explanatory offender when there are no
    claims at all -- a task with zero claims must not read as "fully
    covered".
    """
    if not claims:
        return {"score": 0.0, "offenders": ["no research claims recorded"]}
    verified_urls = {s["url"] for s in sources if s.get("query") == "verified-original"}
    offenders = [c for c in claims if c.get("source_url") not in verified_urls]
    score = (len(claims) - len(offenders)) / len(claims)
    return {"score": score, "offenders": offenders}


def primary_source_ratio(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Fraction of distinct recorded source URLs that are verified-original.

    Returns score 0.0 with a single explanatory offender when there are no
    sources at all.
    """
    by_url: dict[str, dict[str, Any]] = {}
    for s in sources:
        by_url.setdefault(s["url"], s)
    if not by_url:
        return {"score": 0.0, "offenders": ["no research sources recorded"]}
    offenders = [s["url"] for s in by_url.values() if s.get("query") != "verified-original"]
    score = (len(by_url) - len(offenders)) / len(by_url)
    return {"score": score, "offenders": offenders}


def contradiction_resolution(
    claims: list[dict[str, Any]], artifact_text: str
) -> dict[str, Any]:
    """Fraction of contradiction-flagged claims addressed in the artifact.

    "Addressed" = the normalized artifact text contains the claim's
    source_url verbatim, or a normalized bounded-prefix substring match of
    any one of its contradiction strings (see module docstring).

    Claims with no contradictions are excluded from the denominator. If no
    claim recorded a contradiction, the metric returns score 0.0 (not 1.0)
    with an explanatory offender: an empty denominator must not present as
    a passing score.
    """
    flagged = [c for c in claims if c.get("contradictions")]
    if not flagged:
        return {"score": 0.0, "offenders": ["no claims recorded any contradictions"]}
    haystack = _normalize(artifact_text)
    offenders = []
    for c in flagged:
        source_hit = bool(c.get("source_url")) and c["source_url"] in artifact_text
        contradiction_hit = any(_contains(haystack, _needle(text)) for text in c["contradictions"])
        if not (source_hit or contradiction_hit):
            offenders.append(c)
    score = (len(flagged) - len(offenders)) / len(flagged)
    return {"score": score, "offenders": offenders}


def recommendation_linkage(
    claims: list[dict[str, Any]], artifact_text: str
) -> dict[str, Any]:
    """Fraction of claims the final artifact actually draws on.

    A claim counts as linked if the artifact text contains its source_url
    verbatim, or a normalized bounded-prefix substring of the claim text.
    Returns score 0.0 with an explanatory offender when there are no claims.
    """
    if not claims:
        return {"score": 0.0, "offenders": ["no research claims recorded"]}
    haystack = _normalize(artifact_text)
    offenders = []
    for c in claims:
        source_hit = bool(c.get("source_url")) and c["source_url"] in artifact_text
        claim_hit = _contains(haystack, _needle(c.get("claim", "")))
        if not (source_hit or claim_hit):
            offenders.append(c)
    score = (len(claims) - len(offenders)) / len(claims)
    return {"score": score, "offenders": offenders}


def evaluate_research_quality(
    coverage: dict[str, Any],
    ratio: dict[str, Any],
    resolution: dict[str, Any],
    linkage: dict[str, Any],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Aggregate gate over the four metric results.

    Takes the pre-computed dict result of each metric function plus a
    thresholds mapping (defaults to DEFAULT_THRESHOLDS, overridable per
    call). Returns whether the task passes and, for every failed metric,
    its score, its threshold, and a few offending items.
    """
    active_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    results = {
        "claim_source_coverage": coverage,
        "primary_source_ratio": ratio,
        "contradiction_resolution": resolution,
        "recommendation_linkage": linkage,
    }

    failures = []
    for name, result in results.items():
        threshold = active_thresholds[name]
        if result["score"] < threshold:
            failures.append(
                {
                    "metric": name,
                    "score": result["score"],
                    "threshold": threshold,
                    "offenders": result["offenders"][:5],
                }
            )

    return {"passed": not failures, "failures": failures}
