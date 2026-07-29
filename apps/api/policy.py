from __future__ import annotations

from pathlib import Path

BLOCKED_TOKENS = ("git push", "deploy", "publish", "curl ", "wget ", "http://", "https://", "rm -rf", "remove-item", "del /", "sudo", "runas", "chmod 777")


def validate_path(root: Path, candidate: Path) -> tuple[bool, str]:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True, "inside_project_root"
    except ValueError:
        return False, "path_outside_project_root"


def validate_command(command: str, allowed_commands: list[str]) -> tuple[bool, str]:
    normalized = command.strip().lower()
    if any(token in normalized for token in BLOCKED_TOKENS):
        return False, "blocked_command_policy"
    if command not in allowed_commands:
        return False, "command_not_in_task_contract"
    return True, "allowed_by_task_contract"
