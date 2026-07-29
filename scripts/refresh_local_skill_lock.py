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
        for employee, groups in bindings.items()
        for skill in [*groups["required"], *groups["optional"]]
    }
    lock["installed"] = {
        key: value for key, value in lock["installed"].items() if key in bound
    }
    for employee, groups in bindings.items():
        base = ROOT / employees[employee]["profile_path"].rsplit("/", 1)[0] / "skills"
        for optional, skill_ids in ((False, groups["required"]), (True, groups["optional"])):
            for skill_id in skill_ids:
                definition = definitions[skill_id]
                if definition["source"] != "local":
                    continue
                path = base / skill_id
                if not (path / definition.get("entry", "SKILL.md")).exists():
                    raise SystemExit(f"Missing local skill: {employee}:{skill_id}")
                lock["installed"][f"{employee}:{skill_id}"] = {
                    "employee": employee,
                    "skill_id": skill_id,
                    "source_id": "local",
                    "repo": "workspace",
                    "commit_sha": "local",
                    "license": definition["license"],
                    "source_path": definition["source_path"],
                    "install_path": str(path.relative_to(ROOT)),
                    "tree_sha256": tree_hash(path),
                    "optional": optional,
                }
    (REGISTRY / "skills.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (REGISTRY / "skills.lock.yaml").write_text(
        yaml.safe_dump(lock, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"Refreshed {len(lock['installed'])} bound skill locks")


if __name__ == "__main__":
    main()
