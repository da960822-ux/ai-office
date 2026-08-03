#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"


def load(name: str) -> dict:
    return json.loads((REGISTRY / name).read_text(encoding="utf-8"))


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(file.relative_to(path)).encode())
        digest.update(b"\0")
        digest.update(file.read_bytes())
    return digest.hexdigest()


def main() -> None:
    employees = load("employees.json")
    bindings = load("employee-skill-bindings.json")
    definitions = load("skill-definitions.json")
    lock = load("skills.lock.json")
    bound = {
        f"{employee}:{skill}"
        for employee, info in employees.items()
        for skill in bindings[info["team"]]["skills"]
    }
    lock["installed"] = {
        key: value for key, value in lock["installed"].items() if key in bound
    }
    for employee, info in employees.items():
        base = ROOT / info["profile_path"].rsplit("/", 1)[0] / "skills"
        for skill_id in bindings[info["team"]]["skills"]:
            definition = definitions[skill_id]
            path = base / skill_id
            if not (path / definition.get("entry", "SKILL.md")).exists():
                raise SystemExit(f"Missing bound skill: {employee}:{skill_id}")
            key = f"{employee}:{skill_id}"
            if definition["source"] == "local":
                lock["installed"][key] = {
                    "employee": employee,
                    "skill_id": skill_id,
                    "source_id": "local",
                    "repo": "workspace",
                    "commit_sha": "local",
                    "license": definition["license"],
                    "source_path": definition["source_path"],
                    "install_path": str(path.relative_to(ROOT)),
                    "tree_sha256": tree_hash(path),
                    "optional": False,
                }
            else:
                if key not in lock["installed"]:
                    raise SystemExit(f"Missing external skill lock: {key}")
                lock["installed"][key]["tree_sha256"] = tree_hash(path)
    (REGISTRY / "skills.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (REGISTRY / "skills.lock.yaml").write_text(
        yaml.safe_dump(lock, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"Refreshed {len(lock['installed'])} bound skill locks")


if __name__ == "__main__":
    main()
