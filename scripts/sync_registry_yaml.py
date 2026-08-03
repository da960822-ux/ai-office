#!/usr/bin/env python3
"""Mechanically mirror JSON registries as YAML without an external dependency."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"
NAMES = ("employee-skill-bindings", "employees", "skill-definitions", "skill-sources")


def scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(value: object, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, child in value.items():
            if child in ({}, []):
                lines.append(f"{prefix}{scalar(str(key))}: {scalar(child)}")
            else:
                lines.append(f"{prefix}{scalar(str(key))}:")
                lines.extend(render(child, indent + 2))
        return lines or [f"{prefix}{{}}"]
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = []
        for child in value:
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(render(child, indent + 2))
            else:
                lines.append(f"{prefix}- {scalar(child)}")
        return lines
    return [f"{prefix}{scalar(value)}"]


# Skills live in employee-skill-bindings.json keyed by department; employees.json
# stays free of them. Callers read the pool through main.employee_skill_pool()
# instead of a copy that goes stale the moment a binding changes.
employees_path = REGISTRY / "employees.json"
employees = json.loads(employees_path.read_text(encoding="utf-8"))
if any(key in info for info in employees.values() for key in ("required_skills", "optional_skills", "team_skills")):
    for info in employees.values():
        for key in ("required_skills", "optional_skills", "team_skills"):
            info.pop(key, None)
    employees_path.write_text(json.dumps(employees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

for name in NAMES:
    data = json.loads((REGISTRY / f"{name}.json").read_text(encoding="utf-8"))
    (REGISTRY / f"{name}.yaml").write_text("\n".join(render(data)) + "\n", encoding="utf-8")
