"""Fixture schema for the P2 acceptance harness (docs/RUNTIME_ROADMAP.md).

A fixture is a JSON file describing one deterministic task run: the plan to
store, the phase-by-phase deliverable each mocked agent produces, the review
that closes it out, and the invariants the harness must observe. Adding a new
fixture is a JSON file under fixtures/cases/ — no new Python required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"

REQUIRED_KEYS = {"id", "category", "task_request", "plan", "phase_outputs", "expected"}


@dataclass
class Fixture:
    id: str
    category: str
    task_request: str
    plan: dict
    phase_outputs: dict
    expected: dict
    prohibited_skills: dict = field(default_factory=dict)
    reviewer_id: str = "GUARD"
    verify_run: dict | None = None

    @property
    def expected_phase_order(self) -> list[str]:
        return self.expected.get("phase_order", [])

    @property
    def expected_completion(self) -> bool:
        return bool(self.expected.get("completion_ok", True))

    @property
    def expected_error_contains(self) -> str | None:
        return self.expected.get("error_contains")

    @property
    def expected_final_owner(self) -> str | None:
        return self.expected.get("final_owner") or self.plan.get("final_owner")

    @property
    def expected_rendered_suffixes(self) -> list[str] | None:
        """Declaring these opts the fixture into the real office-render step."""
        return self.expected.get("rendered_suffixes")


def load_fixture(path: Path) -> Fixture:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"{path.name} missing required keys: {sorted(missing)}")
    return Fixture(
        id=data["id"],
        category=data["category"],
        task_request=data["task_request"],
        plan=data["plan"],
        phase_outputs=data["phase_outputs"],
        expected=data["expected"],
        prohibited_skills=data.get("prohibited_skills", {}),
        reviewer_id=data.get("reviewer_id", "GUARD"),
        verify_run=data.get("verify_run"),
    )


def load_all_fixtures() -> list[Fixture]:
    return [load_fixture(path) for path in sorted(CASES_DIR.glob("*.json"))]
