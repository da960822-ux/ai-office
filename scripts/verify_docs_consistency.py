#!/usr/bin/env python3
"""Catch documentation that has drifted out of sync with the runtime it describes.

Three checks, each grouped in the report and each citing file:line for every
finding (never just a count):

1. File/path references — markdown links and inline-code paths in docs/*.md
   that look like repo paths must resolve to a real file or directory.
2. Code symbol references — backticked Python-identifier-shaped tokens must
   exist somewhere under apps/, and `file.py:123` references must point at a
   real file with at least that many lines.
3. UI vs API task/job states — state string literals hardcoded in
   apps/web/src must be a subset of the states apps/api/main.py can produce
   (JOB_STATES | TASK_STATES).

Design choices that keep this from crying wolf (see docs comments below for
why): only prose text is scanned, not fenced code blocks, because every
observed "planned but unbuilt" path/tree/schema in these docs lives inside a
```text/```sql/```http fence, while real references to existing code are
inline backticks in sentences. File-existence findings (checks 1 and 2's
file.py:123 half) are ERROR because they are binary and deterministic.
Symbol-resolution findings (check 2's identifier half) are WARNING because
extraction is a heuristic and cannot prove absence. Check 3 findings are
ERROR because both sides are extracted from an authoritative source
(apps/api/main.py's JOB_STATES/TASK_STATES literals), not a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
APPS = ROOT / "apps"

# ---------------------------------------------------------------------------
# Allowlist — known-intentional exceptions. Add an entry here only when the
# reference is genuinely correct but this checker's heuristics can't tell.
# Do NOT add an entry to silence a real drift finding.
# ---------------------------------------------------------------------------

# Backticked paths that intentionally describe locations outside this repo
# (e.g. inside a *target* project workspace this runtime writes into), not a
# path in this repository.
ALLOWLISTED_PATHS: dict[str, str] = {
    ".vibeoffice/": "runtime target-project workspace directory (created inside a user's project), not a path in this repo",
}

# Backticked tokens that are Python-identifier-shaped but are informal/
# conceptual names used consistently across the docs and code comments
# rather than an actual `def`/`class`/module-constant symbol.
ALLOWLISTED_SYMBOLS: dict[str, str] = {
    "TaskContract": "informal name for the task_contracts table/concept; no literal `class TaskContract` exists",
    "InferredValue": "documented-as-intentionally-absent concept (see apps/api/vibeoffice/models.py module docstring); not a literal symbol by design",
}


@dataclass
class Finding:
    level: str  # "ERROR" or "WARNING"
    file: str
    line: int
    message: str
    category: str  # "check1", "check2", or "check3" — which of the 3 checks raised this


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def error(self, category: str, file: str, line: int, message: str) -> None:
        self.findings.append(Finding("ERROR", file, line, message, category))

    def warning(self, category: str, file: str, line: int, message: str) -> None:
        self.findings.append(Finding("WARNING", file, line, message, category))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def strip_fenced_code(text: str) -> str:
    """Blank out fenced code blocks, preserving line numbers/newlines.

    Planned-but-unbuilt file trees, SQL schemas, and HTTP endpoint lists in
    these docs are consistently presented inside fenced code blocks, while
    real references to existing code/paths are inline backticks in prose.
    Scanning only prose is the main false-positive mitigation for checks 1
    and 2.
    """

    def blank(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    return FENCE_RE.sub(blank, text)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


PLACEHOLDER_MARKERS = ("<", ">", "*", "?", "%")


def looks_like_placeholder(candidate: str) -> bool:
    return any(marker in candidate for marker in PLACEHOLDER_MARKERS)


def repo_top_dirs() -> set[str]:
    """Top-level directory names of ROOT, recomputed each call (not cached at
    import time) so tests can point ROOT at a synthetic tree and see it
    reflected immediately."""
    return {p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")}


def is_backtick_path_candidate(candidate: str) -> bool:
    """Conservative filter for bare backticked paths (not markdown links).

    Requires a slash (excludes control-flow tokens like `try/finally`),
    excludes anything shaped like an HTTP route (leading `/`, e.g.
    `/api/tasks/{id}`), and requires a recognized repo top-level directory as
    the first path segment. That last rule is deliberate: docs sometimes use
    an abbreviated cross-reference within a paragraph that already named the
    full path once (e.g. `schemas/department-handoff.schema.json` shorthand
    for `reference/product-context/schemas/department-handoff.schema.json`)
    — those aren't real repo-root-relative paths, so requiring a known top
    directory keeps them from being misreported as broken.
    """
    if not candidate or " " in candidate or looks_like_placeholder(candidate):
        return False
    if candidate.startswith(("http://", "https://", "mailto:", "/")):
        return False
    if "/" not in candidate:
        return False
    first_segment = candidate.split("/", 1)[0]
    return first_segment in repo_top_dirs()


def resolve_repo_path(candidate: str, doc_dir: Path) -> Path:
    """Resolve a path reference the way these docs actually use them.

    Markdown links to other docs are relative to the linking file's own
    directory (e.g. a link in docs/README.md to `ARCHITECTURE.md` means
    docs/ARCHITECTURE.md). Backticked bare paths like `apps/api/main.py` are
    written consistently relative to the repo root throughout docs/.
    """
    cleaned = candidate.split("#", 1)[0]
    path = Path(cleaned)
    if not path.is_absolute() and not cleaned.startswith(("apps/", "apps\\")) and (doc_dir / path).exists():
        return (doc_dir / path).resolve()
    return (ROOT / path).resolve()


# ---------------------------------------------------------------------------
# Check 1: file/path references
# ---------------------------------------------------------------------------

MARKDOWN_LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
LINE_SUFFIX_RE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)$")


def is_link_candidate(candidate: str) -> bool:
    if not candidate:
        return False
    if candidate.startswith(("http://", "https://", "mailto:", "#")):
        return False
    if looks_like_placeholder(candidate):
        return False
    return True


def check_file_references(report: Report) -> None:
    for doc in sorted(DOCS.glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        prose = strip_fenced_code(text)
        rel_doc = doc.relative_to(ROOT).as_posix()

        candidates: list[tuple[str, int]] = []
        for m in MARKDOWN_LINK_RE.finditer(prose):
            target = m.group(1)
            if is_link_candidate(target):
                candidates.append((target, line_of(prose, m.start(1))))
        for m in BACKTICK_RE.finditer(prose):
            token = m.group(1)
            # file:line refs are handled by check 2; skip them here.
            if LINE_SUFFIX_RE.match(token):
                continue
            if is_backtick_path_candidate(token):
                candidates.append((token, line_of(prose, m.start(1))))

        for raw, lineno in candidates:
            if raw in ALLOWLISTED_PATHS:
                continue
            resolved = resolve_repo_path(raw, doc.parent)
            if resolved.exists():
                continue
            report.error("check1", rel_doc, lineno, f"path reference `{raw}` does not resolve to a file or directory")


# ---------------------------------------------------------------------------
# Check 2: code symbol references (identifiers + file.py:123)
# ---------------------------------------------------------------------------

CONST_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
SNAKE_FUNC_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")

_PY_FILES_CACHE: list[Path] | None = None
_SEARCHABLE_FILES_CACHE: list[Path] | None = None
_FILE_STEMS_CACHE: set[str] | None = None


def python_files() -> list[Path]:
    global _PY_FILES_CACHE
    if _PY_FILES_CACHE is None:
        _PY_FILES_CACHE = [p for p in APPS.rglob("*.py") if "__pycache__" not in p.parts]
    return _PY_FILES_CACHE


def searchable_files() -> list[Path]:
    """Every apps/ file worth full-text-searching for a symbol reference.

    Scoped beyond *.py on purpose: fixture case IDs and category tags (e.g.
    `policy_regression`, `market_research`) live in apps/api/fixtures/cases/*.json,
    and web-side identifiers live in *.ts/*.tsx. All are still "somewhere in
    apps/" per the check's charter.
    """
    global _SEARCHABLE_FILES_CACHE
    if _SEARCHABLE_FILES_CACHE is None:
        exts = ("*.py", "*.json", "*.ts", "*.tsx")
        files: list[Path] = []
        for ext in exts:
            files.extend(p for p in APPS.rglob(ext) if "__pycache__" not in p.parts)
        _SEARCHABLE_FILES_CACHE = files
    return _SEARCHABLE_FILES_CACHE


def file_stems() -> set[str]:
    global _FILE_STEMS_CACHE
    if _FILE_STEMS_CACHE is None:
        _FILE_STEMS_CACHE = {p.stem for p in APPS.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    return _FILE_STEMS_CACHE


_SYMBOL_TEXT_CACHE: dict[Path, str] = {}


def reset_caches() -> None:
    """Clear module-level lazy caches. Tests must call this after pointing
    APPS at a synthetic directory, otherwise stale results from a previous
    APPS value (e.g. the real repo) would leak in."""
    global _PY_FILES_CACHE, _SEARCHABLE_FILES_CACHE, _FILE_STEMS_CACHE
    _PY_FILES_CACHE = None
    _SEARCHABLE_FILES_CACHE = None
    _FILE_STEMS_CACHE = None
    _SYMBOL_TEXT_CACHE.clear()


def _read_cached(path: Path) -> str:
    text = _SYMBOL_TEXT_CACHE.get(path)
    if text is None:
        text = path.read_text(encoding="utf-8", errors="ignore")
        _SYMBOL_TEXT_CACHE[path] = text
    return text


def symbol_exists(name: str) -> bool:
    # 1. A real Python def/class or module-level constant assignment.
    def_pattern = re.compile(rf"^\s*(?:async\s+def|def|class)\s+{re.escape(name)}\b", re.MULTILINE)
    const_pattern = re.compile(rf"^{re.escape(name)}\s*[:=]", re.MULTILINE)
    for path in python_files():
        text = _read_cached(path)
        if def_pattern.search(text) or const_pattern.search(text):
            return True

    # 2. The name matches a file's stem (e.g. docs say `test_agent_tools`
    #    for apps/api/test_agent_tools.py, or a fixture id like
    #    `research_quality_gate_fail_001` naming its own .json file).
    if name in file_stems():
        return True

    # 3. A bare whole-word occurrence anywhere in apps/ text (table names,
    #    dict/JSON keys, fixture category tags, SQL columns — these are real
    #    runtime vocabulary even though they're not formal top-level defs).
    word_pattern = re.compile(rf"\b{re.escape(name)}\b")
    for path in searchable_files():
        if word_pattern.search(_read_cached(path)):
            return True
    return False


def is_symbol_candidate(token: str) -> bool:
    if not (3 <= len(token) <= 60):
        return False
    if CONST_RE.match(token):
        return True
    if SNAKE_FUNC_RE.match(token):
        return True
    if PASCAL_RE.match(token) and token.upper() != token and any(c.islower() for c in token):
        return True
    return False


def check_code_symbols(report: Report) -> None:
    for doc in sorted(DOCS.glob("*.md")):
        text = doc.read_text(encoding="utf-8")
        prose = strip_fenced_code(text)
        rel_doc = doc.relative_to(ROOT).as_posix()

        for m in BACKTICK_RE.finditer(prose):
            token = m.group(1)
            lineno = line_of(prose, m.start(1))

            line_match = LINE_SUFFIX_RE.match(token)
            if line_match:
                file_part = line_match.group("path")
                line_num = int(line_match.group("line"))
                if not is_backtick_path_candidate(file_part):
                    continue
                if file_part in ALLOWLISTED_PATHS:
                    continue
                resolved = resolve_repo_path(file_part, doc.parent)
                if not resolved.exists() or not resolved.is_file():
                    report.error("check2", rel_doc, lineno, f"`{token}` references a file that does not exist ({file_part})")
                    continue
                actual_lines = resolved.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
                if line_num > actual_lines:
                    report.error(
                        "check2", rel_doc, lineno,
                        f"`{token}` references line {line_num} but {file_part} only has {actual_lines} lines",
                    )
                continue

            if "/" in token or "." in token or " " in token:
                continue  # not a bare identifier
            if token in ALLOWLISTED_SYMBOLS:
                continue
            if not is_symbol_candidate(token):
                continue
            if symbol_exists(token):
                continue
            report.warning("check2", rel_doc, lineno, f"symbol `{token}` not found under apps/ (may be a false positive)")


# ---------------------------------------------------------------------------
# Check 3: UI state literals vs API-producible states
# ---------------------------------------------------------------------------

def extract_api_states() -> set[str]:
    main_py = APPS / "api" / "main.py"
    text = main_py.read_text(encoding="utf-8")
    states: set[str] = set()

    job_match = re.search(r"JOB_STATES\s*=\s*\{([^}]*)\}", text)
    if job_match:
        states.update(re.findall(r"[\"']([a-zA-Z_]+)[\"']", job_match.group(1)))

    task_match = re.search(r"TASK_STATES\s*=\s*\{(.*?)\n\}", text, re.DOTALL)
    if task_match:
        states.update(re.findall(r"[\"']([a-zA-Z_]+)[\"']", task_match.group(1)))

    return states


STATE_ARRAY_RE = re.compile(r"\[([^\[\]]*)\]\.includes\(\s*(?:job|task|item)?\??\.?state")
STATE_EQ_RE = re.compile(r"state\s*===\s*'([a-zA-Z_]+)'")
EQ_STATE_RE = re.compile(r"'([a-zA-Z_]+)'\s*===\s*[a-zA-Z_.?]*state\b")


def extract_ui_states() -> dict[str, list[tuple[str, int]]]:
    """Map each UI-referenced state literal to its (file, line) occurrences."""
    occurrences: dict[str, list[tuple[str, int]]] = {}
    web_src = ROOT / "apps" / "web" / "src"
    for path in sorted(list(web_src.glob("*.ts")) + list(web_src.glob("*.tsx"))):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for pattern in (STATE_ARRAY_RE,):
            for m in pattern.finditer(text):
                for lit in re.findall(r"'([a-zA-Z_]+)'", m.group(1)):
                    occurrences.setdefault(lit, []).append((rel, line_of(text, m.start())))
        for pattern in (STATE_EQ_RE, EQ_STATE_RE):
            for m in pattern.finditer(text):
                occurrences.setdefault(m.group(1), []).append((rel, line_of(text, m.start())))
    return occurrences


def check_ui_api_states(report: Report) -> None:
    api_states = extract_api_states()
    if not api_states:
        report.warning("check3", "apps/api/main.py", 1, "could not extract JOB_STATES/TASK_STATES; skipping UI-state subset check")
        return
    ui_states = extract_ui_states()
    for state, occurrences in sorted(ui_states.items()):
        if state in api_states:
            continue
        for rel, lineno in occurrences:
            report.error("check3", rel, lineno, f"UI uses state '{state}' which apps/api/main.py cannot produce (not in JOB_STATES|TASK_STATES)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    report = Report()
    check_file_references(report)
    check_code_symbols(report)
    check_ui_api_states(report)

    groups = [
        ("check1", "Check 1: file/path references"),
        ("check2", "Check 2: code symbol references"),
        ("check3", "Check 3: UI vs API state"),
    ]

    error_count = sum(1 for f in report.findings if f.level == "ERROR")
    warning_count = sum(1 for f in report.findings if f.level == "WARNING")

    for category, title in groups:
        matches = [f for f in report.findings if f.category == category]
        print(f"\n--- {title} ---")
        if not matches:
            print("[OK] no findings")
            continue
        for f in matches:
            print(f"[{f.level}] {f.file}:{f.line} {f.message}")

    print(f"\n{len(report.findings)} findings ({error_count} error, {warning_count} warning)")
    if error_count:
        raise SystemExit(1)
    print("[OK] no ERROR-level documentation drift found")


if __name__ == "__main__":
    main()
