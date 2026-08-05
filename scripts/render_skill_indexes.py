#!/usr/bin/env python3
import json
import re
from pathlib import Path

from skill_pool import POOL_PATH

ROOT = Path(__file__).resolve().parents[1]
employees = json.loads((ROOT / "registry/employees.json").read_text(encoding="utf-8"))
bindings = json.loads((ROOT / "registry/employee-skill-bindings.json").read_text(encoding="utf-8"))

# Skill text lives once in the shared pool at repo root; only _local-role-core stays
# inside the employee folder, and it is deliberately not indexed here. Parse each
# SKILL.md once and reuse the result for every employee instead of re-walking the
# pool per employee.
skill_cache = {}
for path in sorted(POOL_PATH.glob("*/SKILL.md")):
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
    skill_cache[path.parent.name] = (title, summary)

for employee_id, employee in employees.items():
    base = ROOT / employee["profile_path"].rsplit("/", 1)[0]
    # Index only what the lead can actually select. A folder left on disk after its
    # skill was dropped from the department pool is still readable, and advertising it
    # here makes the lead pick a skill that validate_selected_skills then rejects.
    # _local-role-core is excluded on purpose: main.employee_skill_context always
    # delivers it, so listing it here would only invite a pick that 403s.
    selectable = set(bindings[employee["team"]]["skills"])
    rows = []
    for skill_id in sorted(skill_cache):
        if skill_id not in selectable:
            continue
        title, summary = skill_cache[skill_id]
        rows.append(f"- `{skill_id}`: {title} — {summary}")
    (base / "SKILL_INDEX.md").write_text(
        "# Skill Routing Index\n\n"
        "라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.\n\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )

print("Skill indexes rendered.")
