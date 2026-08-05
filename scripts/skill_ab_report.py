#!/usr/bin/env python3
"""Answer "did selecting skill X actually improve outcomes?" from run history.

Groups task_phases by task_kind, and within a task_kind compares phases that
used a given skill (treatment) against phases in the same task_kind that did
not (control). Used to gate promotion of a skill out of shadow status: only
promote on measured evidence, and only when both arms have enough samples.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "ai-office.sqlite3"
SKILL_DEFINITIONS = ROOT / "registry" / "skill-definitions.json"

# Terminal-success status strings, resolved from apps/api/main.py (not guessed):
#   - phase success: apps/api/worker.py sets "UPDATE task_phases SET status = 'completed'"
#     on phase completion (lines ~796, ~803); apps/api/main.py:1258 treats
#     status NOT IN ('completed', 'skipped') as "incomplete", i.e. 'completed' is the
#     only terminal-success phase status ('skipped' is terminal but not a success).
#   - review pass: apps/api/main.py:1271 and apps/api/task_routes.py:513 use
#     verdict == 'pass' as the passing review verdict.
PHASE_SUCCESS_STATUS = "completed"
REVIEW_PASS_VERDICT = "pass"


def load_phases(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(db.execute("SELECT task_id, phase_id, task_kind, status, skill_ids FROM task_phases"))


def load_reviews_by_task(db: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in db.execute("SELECT task_id, verdict FROM reviews"):
        out.setdefault(row["task_id"], []).append(row["verdict"])
    return out


def load_retries_by_task(db: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in db.execute("SELECT task_id, COUNT(*) AS n FROM retry_attempts GROUP BY task_id"):
        out[row["task_id"]] = row["n"]
    return out


def load_cost_by_task(db: sqlite3.Connection) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in db.execute("SELECT task_id, SUM(cost_usd) AS c FROM model_usage GROUP BY task_id"):
        out[row["task_id"]] = row["c"] or 0.0
    return out


def skill_ids_of(phase: sqlite3.Row) -> list[str]:
    try:
        parsed = json.loads(phase["skill_ids"])
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def summarize_arm(task_ids: set[str], phases: list[sqlite3.Row], reviews: dict[str, list[str]],
                   retries: dict[str, int], costs: dict[str, float]) -> dict:
    # Retries, reviews and cost are recorded per task, but one task holds phases from both
    # arms. Attributing a shared task to both sides would let the other arm's failures leak
    # in, so task-level metrics are computed only over tasks exclusive to this arm.
    n = len(phases)
    successes = sum(1 for p in phases if p["status"] == PHASE_SUCCESS_STATUS)
    verdicts = [v for tid in task_ids for v in reviews.get(tid, [])]
    review_pass_rate = (sum(1 for v in verdicts if v == REVIEW_PASS_VERDICT) / len(verdicts)) if verdicts else None
    return {
        "n_phases": n,
        "n_tasks": len(task_ids),
        "success_rate": successes / n if n else None,
        "mean_retries_per_task": statistics.fmean(retries.get(tid, 0) for tid in task_ids) if task_ids else None,
        "review_pass_rate": review_pass_rate,
        "mean_cost_usd_per_task": statistics.fmean(costs.get(tid, 0.0) for tid in task_ids) if task_ids else None,
    }


def build_comparisons(db: sqlite3.Connection, skill_filter: str | None, min_n: int) -> list[dict]:
    phases = load_phases(db)
    reviews = load_reviews_by_task(db)
    retries = load_retries_by_task(db)
    costs = load_cost_by_task(db)

    by_kind: dict[str, list[sqlite3.Row]] = {}
    for p in phases:
        # task_kind was added by a later migration, so old rows can carry NULL
        by_kind.setdefault(p["task_kind"] or "unknown", []).append(p)

    comparisons = []
    for task_kind, kind_phases in by_kind.items():
        phase_skill_sets = [(p, set(skill_ids_of(p))) for p in kind_phases]
        skills_in_kind: set[str] = set()
        for _, skills in phase_skill_sets:
            skills_in_kind.update(skills)
        for skill_id in sorted(skills_in_kind):
            if skill_filter and skill_id != skill_filter:
                continue
            treatment_phases = [p for p, skills in phase_skill_sets if skill_id in skills]
            control_phases = [p for p, skills in phase_skill_sets if skill_id not in skills]
            treatment_all = {p["task_id"] for p in treatment_phases}
            control_all = {p["task_id"] for p in control_phases}
            shared = treatment_all & control_all
            treatment_tasks = treatment_all - shared
            control_tasks = control_all - shared
            treatment = summarize_arm(treatment_tasks, treatment_phases, reviews, retries, costs)
            control = summarize_arm(control_tasks, control_phases, reviews, retries, costs)
            sufficient = treatment["n_phases"] >= min_n and control["n_phases"] >= min_n
            recommendation = None
            if sufficient and treatment["success_rate"] is not None and control["success_rate"] is not None:
                recommendation = "PROMOTE" if treatment["success_rate"] > control["success_rate"] else "KEEP-SHADOW"
            comparisons.append({
                "task_kind": task_kind,
                "skill_id": skill_id,
                "treatment": treatment,
                "control": control,
                "sufficient": sufficient,
                "shared_tasks_excluded": len(shared),
                "recommendation": recommendation if sufficient else "INSUFFICIENT",
            })
    return comparisons


def load_shadow_skills() -> list[str]:
    if not SKILL_DEFINITIONS.exists():
        return []
    definitions = json.loads(SKILL_DEFINITIONS.read_text(encoding="utf-8"))
    return sorted(sid for sid, meta in definitions.items() if meta.get("status") == "shadow")


def shadow_verdicts(comparisons: list[dict]) -> dict[str, str]:
    """Best verdict seen for each shadow skill across all its task_kind comparisons.
    PROMOTE beats KEEP-SHADOW beats INSUFFICIENT so one supporting comparison is enough
    to flag promotion for a human to look at; skills with no comparisons at all are
    INSUFFICIENT DATA."""
    rank = {"PROMOTE": 2, "KEEP-SHADOW": 1, "INSUFFICIENT": 0}
    best: dict[str, str] = {}
    for c in comparisons:
        sid = c["skill_id"]
        if sid not in best or rank[c["recommendation"]] > rank[best[sid]]:
            best[sid] = c["recommendation"]
    return {
        sid: "INSUFFICIENT DATA" if best.get(sid, "INSUFFICIENT") == "INSUFFICIENT" else best[sid]
        for sid in load_shadow_skills()
    }


def fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def fmt_num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def print_text(comparisons: list[dict], min_n: int) -> None:
    if not comparisons:
        print("No comparisons available (no phases with skill_ids found).")
    for c in comparisons:
        t, ctl = c["treatment"], c["control"]
        print(f"[{c['task_kind']}] skill={c['skill_id']}  (n={t['n_phases']} vs n={ctl['n_phases']}, min_n={min_n})")
        print(f"  treatment: success={fmt_pct(t['success_rate'])} retries/task={fmt_num(t['mean_retries_per_task'])} "
              f"review_pass={fmt_pct(t['review_pass_rate'])} cost/task=${fmt_num(t['mean_cost_usd_per_task'])}")
        print(f"  control  : success={fmt_pct(ctl['success_rate'])} retries/task={fmt_num(ctl['mean_retries_per_task'])} "
              f"review_pass={fmt_pct(ctl['review_pass_rate'])} cost/task=${fmt_num(ctl['mean_cost_usd_per_task'])}")
        if c["sufficient"] and t["success_rate"] is not None and ctl["success_rate"] is not None:
            delta = (t["success_rate"] - ctl["success_rate"]) * 100
            print(f"  delta success: {delta:+.0f}pp (n={t['n_phases']} vs n={ctl['n_phases']})  -> {c['recommendation']}")
        else:
            print(f"  -> INSUFFICIENT (need >= {min_n} phases in both arms)")
        print()

    shadow = shadow_verdicts(comparisons)
    if shadow:
        print("Shadow skills:")
        for sid, verdict in shadow.items():
            print(f"  {sid}: {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--skill", default=None, help="filter to one skill id")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--min-n", type=int, default=5)
    args = parser.parse_args()

    if not args.db.exists():
        print("No run history yet (database does not exist).")
        raise SystemExit(0)

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        total_phases = connection.execute("SELECT COUNT(*) FROM task_phases").fetchone()[0]
        if total_phases == 0:
            print("No run history yet (task_phases is empty).")
            raise SystemExit(0)
        comparisons = build_comparisons(connection, args.skill, args.min_n)
    finally:
        connection.close()

    if args.as_json:
        print(json.dumps({
            "comparisons": comparisons,
            "shadow_skills": shadow_verdicts(comparisons),
        }, indent=2))
    else:
        print_text(comparisons, args.min_n)


if __name__ == "__main__":
    main()
