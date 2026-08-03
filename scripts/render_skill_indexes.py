#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
employees = json.loads((ROOT / "registry/employees.json").read_text(encoding="utf-8"))
bindings = json.loads((ROOT / "registry/employee-skill-bindings.json").read_text(encoding="utf-8"))

for employee_id, employee in employees.items():
    base = ROOT / employee["profile_path"].rsplit("/", 1)[0]
    # Index only what the lead can actually select. A folder left on disk after its
    # skill was dropped from the department pool is still readable, and advertising it
    # here makes the lead pick a skill that validate_selected_skills then rejects.
    # _local-role-core is excluded on purpose: main.employee_skill_context always
    # delivers it, so listing it here would only invite a pick that 403s.
    selectable = set(bindings[employee["team"]]["skills"])
    rows = []
    for path in sorted((base / "skills").glob("*/SKILL.md")):
        if path.parent.name not in selectable:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        title = next(
            (re.sub(r"^#\s*", "", line).strip() for line in text.splitlines() if line.startswith("#")),
            path.parent.name,
        )
        summary = " ".join(
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        )[:240].rstrip()
        rows.append(f"- `{path.parent.name}`: {title} — {summary}")
    (base / "SKILL_INDEX.md").write_text(
        "# Skill Routing Index\n\n"
        "라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.\n\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )

print("Skill indexes rendered.")
