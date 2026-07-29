#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
employees = json.loads((ROOT / "registry/employees.json").read_text(encoding="utf-8"))

for employee_id, employee in employees.items():
    base = ROOT / employee["profile_path"].rsplit("/", 1)[0]
    rows = []
    for path in sorted((base / "skills").glob("*/SKILL.md")):
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
