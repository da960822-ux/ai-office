#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import yaml

from skill_pool import POOL_PATH as POOL, tree_hash

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"


def load(name: str) -> dict:
    return json.loads((REGISTRY / name).read_text(encoding="utf-8"))


def main() -> None:
    employees = load("employees.json")
    bindings = load("employee-skill-bindings.json")
    definitions = load("skill-definitions.json")
    lock = load("skills.lock.json")
    # The pool is shared, so the lock is keyed by skill id -- one entry per skill instead
    # of one per (employee, skill) pair that repeated the same hash three or four times.
    bound = {skill for info in employees.values() for skill in bindings[info["team"]]["skills"]}
    lock["installed"] = {
        key: value for key, value in lock["installed"].items() if key in bound
    }
    for skill_id in sorted(bound):
        definition = definitions[skill_id]
        path = POOL / skill_id
        if not (path / definition.get("entry", "SKILL.md")).exists():
            raise SystemExit(f"Missing bound skill: {skill_id}")
        if definition["source"] == "local":
            lock["installed"][skill_id] = {
                "skill_id": skill_id,
                "source_id": "local",
                "repo": "workspace",
                "commit_sha": "local",
                "license": definition["license"],
                "source_path": definition["source_path"],
                "install_path": path.relative_to(ROOT).as_posix(),
                "tree_sha256": tree_hash(path),
                "optional": False,
            }
        else:
            if skill_id not in lock["installed"]:
                raise SystemExit(f"Missing external skill lock: {skill_id}")
            lock["installed"][skill_id]["tree_sha256"] = tree_hash(path)
    (REGISTRY / "skills.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (REGISTRY / "skills.lock.yaml").write_text(
        yaml.safe_dump(lock, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"Refreshed {len(lock['installed'])} bound skill locks")


if __name__ == "__main__":
    main()
