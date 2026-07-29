#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"


def load(name: str) -> dict:
    return json.loads((REGISTRY / name).read_text(encoding="utf-8"))


def main() -> None:
    employees = load("employees.json")
    bindings = load("employee-skill-bindings.json")
    boundaries = load("department-boundaries.json")
    profiles = load("task-profiles.json")
    standards = load("deliverable-standards.json")
    errors: list[str] = []

    memberships: dict[str, str] = {}
    for department, policy in boundaries.items():
        members = [policy["lead"], *policy["workers"]]
        if len(members) != len(set(members)):
            errors.append(f"{department}: duplicate employee")
        for employee in members:
            if employee not in employees:
                errors.append(f"{department}: unknown employee {employee}")
                continue
            if employee in memberships:
                errors.append(f"{employee}: appears in {memberships[employee]} and {department}")
            memberships[employee] = department
            if employees[employee]["team"] != department:
                errors.append(f"{employee}: team differs from boundary {department}")
        if not policy.get("owns"):
            errors.append(f"{department}: owns is empty")
        if not policy.get("must_handoff"):
            errors.append(f"{department}: must_handoff is empty")

    missing = sorted(set(employees) - set(memberships))
    if missing:
        errors.append(f"employees without a department boundary: {missing}")

    for employee, groups in bindings.items():
        combined = [*groups["required"], *groups["optional"]]
        if len(combined) != len(set(combined)):
            errors.append(f"{employee}: duplicate skill binding")
        if employees[employee]["required_skills"] != groups["required"]:
            errors.append(f"{employee}: required skills differ between registries")
        if employees[employee]["optional_skills"] != groups["optional"]:
            errors.append(f"{employee}: optional skills differ between registries")

    if profiles:
        errors.append("task-profiles.json must remain empty; GLM designs workflows dynamically")
    if "document-artifact-production" not in bindings["DOCS"]["required"]:
        errors.append("DOCS is missing document-artifact-production")

    if errors:
        print("\n".join(f"[ERROR] {error}" for error in errors))
        raise SystemExit(1)
    print(
        f"[OK] {len(employees)} employees, {len(boundaries)} departments, "
        f"dynamic routing with {len(profiles)} hardcoded task profiles, {len(standards)} deliverable standards"
    )


if __name__ == "__main__":
    main()
