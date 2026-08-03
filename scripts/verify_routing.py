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
    definitions = load("skill-definitions.json")
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

    known_teams = {info["team"] for info in employees.values()}
    for team, groups in bindings.items():
        combined = groups["skills"]
        if len(combined) != len(set(combined)):
            errors.append(f"{team}: duplicate skill binding")
        if team not in known_teams:
            errors.append(f"{team}: binding has no department")
        for skill_id in combined:
            if skill_id not in definitions:
                errors.append(f"{team}: undefined skill {skill_id}")
                continue
            if definitions[skill_id].get("install_policy") == "manual_accept_noncommercial":
                errors.append(f"{team}: noncommercial skill {skill_id} is bound")

    ui_skill_ids = {
        "ui-ux-pro-max", "impeccable", "design-first-ui-prompting",
        "gsap-core", "gsap-timeline", "gsap-react", "gsap-performance",
    }
    blocked_ui_kinds = {"market_research", "business_strategy", "document_authoring", "backend_implementation", "quality_review"}
    for skill_id in ui_skill_ids:
        metadata = definitions.get(skill_id, {}).get("activation", {})
        if not metadata:
            errors.append(f"{skill_id}: missing activation metadata")
            continue
        if not blocked_ui_kinds.issubset(set(metadata.get("blocked_task_kinds", []))):
            errors.append(f"{skill_id}: UI activation does not block non-UI work")

    if profiles:
        errors.append("task-profiles.json must remain empty; GLM designs workflows dynamically")
    if "document-artifact-production" not in bindings["service-knowledge"]["skills"]:
        errors.append("service-knowledge is missing document-artifact-production")

    if errors:
        print("\n".join(f"[ERROR] {error}" for error in errors))
        raise SystemExit(1)
    print(
        f"[OK] {len(employees)} employees, {len(boundaries)} departments, "
        f"dynamic routing with {len(profiles)} hardcoded task profiles, {len(standards)} deliverable standards"
    )


if __name__ == "__main__":
    main()
