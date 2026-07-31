#!/usr/bin/env python3
"""Local environment preflight check (docs/LAUNCH_HARNESS_PLAN.md B0).

Reports which optional local tools (rg, node, git, .venv) are available.
Missing tools are reported as [WARN] and degrade functionality (e.g.
search_files falls back to pure Python) rather than failing the suite.
This script always exits 0 -- warnings are informational, not failures.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    warned = False

    if shutil.which("rg"):
        print("[OK] rg (ripgrep) found on PATH")
    else:
        warned = True
        print("[WARN] rg (ripgrep) not found on PATH; search_files/find_symbols/find_references will use the pure-Python fallback")

    if shutil.which("node"):
        print("[OK] node found on PATH")
    else:
        warned = True
        print("[WARN] node not found on PATH; language_diagnostics for .js/.mjs/.cjs will be unavailable")

    venv_dir = ROOT / ".venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    if not venv_python.is_file():
        venv_python = venv_dir / "bin" / "python"
    if venv_dir.is_dir() and venv_python.exists():
        print(f"[OK] .venv found at {venv_dir} with interpreter {venv_python}")
    elif venv_dir.is_dir():
        warned = True
        print(f"[WARN] .venv directory exists at {venv_dir} but interpreter was not found")
    else:
        warned = True
        print(f"[WARN] .venv not found at {venv_dir}")

    if shutil.which("git"):
        print("[OK] git found on PATH")
    else:
        warned = True
        print("[WARN] git not found on PATH; git_status/git_diff/git_commit/git_push tools will be unavailable")

    if warned:
        print("[WARN] one or more optional tools are missing; continuing in degraded mode")
    else:
        print("[OK] all optional local tools are available")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - preflight must never crash the caller
        print(f"[WARN] preflight check encountered an unexpected error: {error}")
        sys.exit(0)
