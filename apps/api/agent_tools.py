"""Bounded local tools for AI Office agents.

This module deliberately has no database or FastAPI dependency.  The API layer
supplies a task workspace and TaskContract allow-list, then translates
``AgentToolError`` into its own transport error/event format.
"""
from __future__ import annotations

import fnmatch
import html
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_TOOL_OUTPUT = 12_000
MAX_FILE_BYTES = 1_000_000
MAX_REPLACEMENT_BYTES = 100_000
IGNORED_PARTS = {".git", "node_modules", ".venv", "dist", "build", "__pycache__"}
ROOT = Path(__file__).resolve().parents[2]


class _ReadableHTML(HTMLParser):
    """Small dependency-free text extractor that ignores non-content elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.title_depth = 0
        self.title: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.ignored_depth += 1
        if tag == "title":
            self.title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"} and self.ignored_depth:
            self.ignored_depth -= 1
        if tag == "title" and self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.text.append(cleaned)
            if self.title_depth:
                self.title.append(cleaned)


class AgentToolError(RuntimeError):
    """A safe, user-visible error from a bounded agent tool."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _short(value: str, limit: int = MAX_TOOL_OUTPUT) -> dict[str, Any]:
    if len(value) <= limit:
        return {"content": value, "truncated": False}
    return {"content": value[:limit], "truncated": True, "original_characters": len(value)}


def _normal_relative(path: str) -> str:
    value = path.replace("\\", "/").strip().strip("/")
    if not value or value == ".":
        return "."
    if value.startswith("../") or "/../" in value or Path(value).is_absolute():
        raise AgentToolError(403, "Agent file path escapes workspace")
    return value


def _is_permitted(relative_path: str, allowed_paths: list[str]) -> bool:
    for allowed in allowed_paths:
        normalized = _normal_relative(str(allowed))
        if normalized == "." or relative_path == normalized or relative_path.startswith(normalized + "/"):
            return True
    return False


def _require_public_url(raw_url: str) -> urllib.parse.ParseResult:
    if len(raw_url) > 2_000:
        raise AgentToolError(422, "Source URL exceeds 2000 characters")
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AgentToolError(422, "Only public HTTP(S) source URLs are allowed")
    if parsed.username or parsed.password:
        raise AgentToolError(422, "Source URL credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as error:
        raise AgentToolError(422, "Source URL port is invalid") from error
    if port and port not in {80, 443}:
        raise AgentToolError(422, "Source URL port must be 80 or 443")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as error:
        raise AgentToolError(502, f"Source hostname resolution failed: {error}") from error
    if not addresses:
        raise AgentToolError(502, "Source hostname resolved to no addresses")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise AgentToolError(403, "Private or local source addresses are not allowed")
    return parsed


def fetch_public_source(raw_url: str, *, text_limit: int = 16_000) -> dict[str, Any]:
    """Fetch one public original page with SSRF and response-size controls."""
    parsed = _require_public_url(raw_url)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            raise urllib.error.HTTPError(req.full_url, code, "Source redirects are not followed", headers, fp)

    request = urllib.request.Request(
        raw_url,
        headers={
            "User-Agent": "Mozilla/5.0 AI-Automation-Office/1.0",
            "Accept": "text/html,text/plain,application/json",
        },
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain", "application/json"}:
                raise AgentToolError(422, f"Unsupported source content type: {content_type}")
            raw = response.read(2_000_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            final_url = response.geturl()
    except AgentToolError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
        raise AgentToolError(502, f"Source read failed: {error}") from error

    # Redirects are disabled, yet keep this invariant explicit for future opener changes.
    final = urllib.parse.urlparse(final_url)
    if final.hostname != parsed.hostname or final.scheme != parsed.scheme:
        raise AgentToolError(502, "Source changed host or scheme during fetch")
    title = final.hostname or "source"
    if content_type == "text/html":
        parser = _ReadableHTML()
        parser.feed(raw)
        title = " ".join(parser.title).strip() or title
        text = " ".join(parser.text).strip()
    else:
        text = re.sub(r"\s+", " ", raw).strip()
    if len(text) < 200:
        raise AgentToolError(502, "Source contains too little readable text")
    return {"title": title[:300], "url": final_url[:2000], "content_type": content_type, "text": text[:max(1, min(text_limit, 32_000))]}


def fetch_public_pdf(raw_url: str, *, text_limit: int = 24_000) -> dict[str, Any]:
    """Extract text from one public PDF after the same SSRF checks as HTML research."""
    _require_public_url(raw_url)
    request = urllib.request.Request(raw_url, headers={"User-Agent": "Mozilla/5.0 AI-Automation-Office/1.0", "Accept": "application/pdf"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.headers.get_content_type() != "application/pdf":
                raise AgentToolError(422, "Source is not a PDF")
            raw = response.read(10_000_000)
            final_url = response.geturl()
    except AgentToolError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
        raise AgentToolError(502, f"PDF read failed: {error}") from error
    if urllib.parse.urlparse(final_url).hostname != urllib.parse.urlparse(raw_url).hostname:
        raise AgentToolError(502, "PDF changed host during fetch")
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as error:
        raise AgentToolError(422, f"PDF text extraction failed: {error}") from error
    if len(text) < 80:
        raise AgentToolError(422, "PDF contains too little extractable text; OCR is required")
    return {"title": Path(urllib.parse.urlparse(final_url).path).name or "PDF source", "url": final_url[:2000], "content_type": "application/pdf", "pages": len(reader.pages), "text": text[:max(1, min(text_limit, 32_000))]}


def render_public_page(raw_url: str, *, text_limit: int = 24_000) -> dict[str, Any]:
    """Render JavaScript page with local Chrome; caller must receive explicit approval."""
    parsed = _require_public_url(raw_url)
    browser = next(
        (
            Path(candidate) for candidate in (
                os.getenv("AI_OFFICE_BROWSER_PATH", ""),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ) if candidate and Path(candidate).is_file()
        ),
        None,
    )
    if browser is None:
        raise AgentToolError(503, "No supported local Chrome/Edge executable is available")
    with tempfile.TemporaryDirectory(prefix="ai-office-browser-") as profile:
        try:
            run = subprocess.run(
                [
                    str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
                    "--disable-extensions", "--disable-background-networking",
                    "--virtual-time-budget=10000", f"--user-data-dir={profile}", "--dump-dom", raw_url,
                ],
                capture_output=True,
                text=True,
                timeout=35,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise AgentToolError(504, "Browser render timed out") from error
        except OSError as error:
            raise AgentToolError(503, f"Browser render failed to start: {error}") from error
    if run.returncode:
        raise AgentToolError(502, f"Browser render failed: {(run.stderr or run.stdout)[:800]}")
    parser = _ReadableHTML()
    parser.feed(run.stdout)
    text = " ".join(parser.text).strip()
    if len(text) < 80:
        raise AgentToolError(502, "Rendered page contains too little readable text")
    return {"title": " ".join(parser.title).strip()[:300] or parsed.hostname, "url": raw_url, "rendered": True, "text": text[:max(1, min(text_limit, 32_000))]}


def tool_definitions() -> list[dict[str, Any]]:
    """OpenAI Responses function definitions. Mutation tools remain explicit."""
    return [
        {"type": "function", "name": "list_files", "description": "List TaskContract-allowed workspace files without reading their contents.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "default": "."}, "glob": {"type": "string", "default": "*"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200}}, "additionalProperties": False}},
        {"type": "function", "name": "read_file", "description": "Read one bounded UTF-8 workspace file with line numbers and optional line range.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "start_line": {"type": "integer", "minimum": 1, "default": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"], "additionalProperties": False}},
        {"type": "function", "name": "search_files", "description": "Search UTF-8 workspace files with ripgrep. Results are path, line, and matching text; ignored build/dependency folders are excluded.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300}, "path": {"type": "string", "default": "."}, "glob": {"type": "string", "maxLength": 200}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40}}, "required": ["query"], "additionalProperties": False}},
        {"type": "function", "name": "find_symbols", "description": "Find class, function, type, interface, and variable definitions with ripgrep before reading files.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string", "minLength": 1, "maxLength": 200}, "path": {"type": "string", "default": "."}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40}}, "required": ["symbol"], "additionalProperties": False}},
        {"type": "function", "name": "find_references", "description": "Find bounded whole-word references to a symbol before editing or refactoring.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string", "minLength": 1, "maxLength": 200}, "path": {"type": "string", "default": "."}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 60}}, "required": ["symbol"], "additionalProperties": False}},
        {"type": "function", "name": "language_diagnostics", "description": "Run bounded syntax diagnostics for one allowed Python or JavaScript file. Full project test commands remain TaskContract-gated.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}}, "required": ["path"], "additionalProperties": False}},
        {"type": "function", "name": "discover_tests", "description": "Discover local test files and declared test commands without running them.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "default": "."}, "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 80}}, "additionalProperties": False}},
        {"type": "function", "name": "replace_exact_text", "description": "Safely replace an exact text fragment in one allowed UTF-8 workspace file. Default requires exactly one match; use expected_count only when every replacement is intended.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "old_text": {"type": "string", "minLength": 1, "maxLength": 50000}, "new_text": {"type": "string", "maxLength": 100000}, "expected_count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1}}, "required": ["path", "old_text", "new_text"], "additionalProperties": False}},
        {"type": "function", "name": "apply_unified_patch", "description": "Apply a bounded unified diff atomically after `git apply --check`. Every changed path must be TaskContract-allowed.", "parameters": {"type": "object", "properties": {"patch": {"type": "string", "minLength": 1, "maxLength": 200000}}, "required": ["patch"], "additionalProperties": False}},
        {"type": "function", "name": "create_file", "description": "Create a new UTF-8 file. Refuses to overwrite an existing file.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "content": {"type": "string", "maxLength": 100000}}, "required": ["path", "content"], "additionalProperties": False}},
        {"type": "function", "name": "git_status", "description": "Read concise Git working-tree status for assigned workspace.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"type": "function", "name": "git_diff", "description": "Read bounded Git diff for assigned workspace. Optional path must be inside TaskContract allowed paths.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "maxLength": 500}}, "additionalProperties": False}},
        {"type": "function", "name": "git_commit", "description": "Commit only explicitly listed TaskContract-allowed paths. Available only when the contract grants `git commit *`.", "parameters": {"type": "object", "properties": {"message": {"type": "string", "minLength": 1, "maxLength": 200}, "paths": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 500}, "minItems": 1, "maxItems": 50}}, "required": ["message", "paths"], "additionalProperties": False}},
        {"type": "function", "name": "git_push", "description": "Push HEAD to an explicit remote branch. Available only when the contract grants `git push *`.", "parameters": {"type": "object", "properties": {"remote": {"type": "string", "minLength": 1, "maxLength": 80, "default": "origin"}, "branch": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["branch"], "additionalProperties": False}},
        {"type": "function", "name": "fetch_public_source", "description": "Read one original public HTTP(S) source. Private/local addresses, redirects, non-text content, and oversized responses are rejected.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}}, "required": ["url"], "additionalProperties": False}},
        {"type": "function", "name": "fetch_public_pdf", "description": "Extract bounded readable text from one public PDF. Rejects private hosts, redirects, non-PDF files, oversized files, and scans needing OCR.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}}, "required": ["url"], "additionalProperties": False}},
        {"type": "function", "name": "render_public_page", "description": "Render one JavaScript public page with local headless browser. This tool always requires explicit permission approval.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}}, "required": ["url"], "additionalProperties": False}},
    ]


@dataclass(frozen=True)
class WorkspaceAgentTools:
    workspace: Path
    allowed_paths: list[str]
    output_limit: int = MAX_TOOL_OUTPUT

    def __post_init__(self) -> None:
        root = self.workspace.resolve()
        if not root.is_dir():
            raise AgentToolError(422, "Agent workspace must be an existing directory")
        object.__setattr__(self, "workspace", root)
        # Normalize now, so malformed contract entries cannot become bypasses later.
        object.__setattr__(self, "allowed_paths", [_normal_relative(item) for item in self.allowed_paths])

    def path(self, relative_path: str, *, must_exist: bool = False) -> Path:
        relative = _normal_relative(relative_path)
        candidate = (self.workspace / relative).resolve()
        if not candidate.is_relative_to(self.workspace):
            raise AgentToolError(403, "Agent file path escapes workspace")
        normalized = str(candidate.relative_to(self.workspace)).replace("\\", "/")
        if not _is_permitted(normalized, self.allowed_paths):
            raise AgentToolError(403, "Agent file path is outside TaskContract allowed_paths")
        if any(part in IGNORED_PARTS for part in candidate.relative_to(self.workspace).parts):
            raise AgentToolError(403, "Agent access to ignored workspace directory is not allowed")
        if must_exist and not candidate.is_file():
            raise AgentToolError(404, "Workspace file does not exist")
        return candidate

    def list_files(self, path: str = ".", glob: str = "*", max_results: int = 200) -> dict[str, Any]:
        if not 1 <= max_results <= 500:
            raise AgentToolError(422, "max_results must be between 1 and 500")
        target = self.path(path)
        if not target.exists() or not target.is_dir():
            raise AgentToolError(404, "Workspace directory does not exist")
        results = []
        for item in sorted(target.rglob(glob)):
            if not item.is_file() or any(part in IGNORED_PARTS for part in item.relative_to(self.workspace).parts):
                continue
            relative = item.relative_to(self.workspace).as_posix()
            if _is_permitted(relative, self.allowed_paths):
                results.append(relative)
            if len(results) >= max_results:
                break
        return {"files": results, "truncated": len(results) >= max_results}

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        target = self.path(path, must_exist=True)
        if target.stat().st_size > MAX_FILE_BYTES:
            raise AgentToolError(422, "Workspace file exceeds 1 MB read limit")
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise AgentToolError(422, "read_file supports UTF-8 text files only") from error
        if end_line is None:
            end_line = min(len(lines), start_line + 399)
        if start_line < 1 or end_line < start_line or end_line - start_line > 1000:
            raise AgentToolError(422, "Invalid line range")
        selected = [{"line": index, "text": lines[index - 1]} for index in range(start_line, min(end_line, len(lines)) + 1)]
        return {"path": target.relative_to(self.workspace).as_posix(), "lines": selected, "total_lines": len(lines)}

    def search_files(self, query: str, path: str = ".", glob: str | None = None, max_results: int = 40) -> dict[str, Any]:
        if not query or len(query) > 300:
            raise AgentToolError(422, "Search query must contain 1-300 characters")
        if not 1 <= max_results <= 100:
            raise AgentToolError(422, "max_results must be between 1 and 100")
        # Search may start at workspace root even when the contract grants only
        # selected descendants.  Individual result paths are filtered below.
        relative = _normal_relative(path)
        if relative != "." and not _is_permitted(relative, self.allowed_paths):
            raise AgentToolError(403, "Agent file path is outside TaskContract allowed_paths")
        target = (self.workspace / relative).resolve()
        if not target.is_relative_to(self.workspace):
            raise AgentToolError(403, "Agent file path escapes workspace")
        if any(part in IGNORED_PARTS for part in target.relative_to(self.workspace).parts):
            raise AgentToolError(403, "Agent access to ignored workspace directory is not allowed")
        if not target.exists():
            raise AgentToolError(404, "Search path does not exist")
        if glob and (len(glob) > 200 or Path(glob).is_absolute() or ".." in Path(glob).parts):
            raise AgentToolError(422, "Search glob is invalid")
        command = ["rg", "--json", "--line-number", "--no-heading", "--color", "never", "--max-count", str(max_results)]
        for ignored in IGNORED_PARTS:
            command.extend(["--glob", f"!{ignored}/**"])
        if glob:
            command.extend(["--glob", glob])
        command.extend([query, str(target)])
        try:
            run = subprocess.run(command, cwd=self.workspace, capture_output=True, text=True, timeout=20, shell=False)
        except FileNotFoundError:
            # ripgrep is not on PATH in this environment. Degrade to a pure-Python
            # fallback instead of failing the whole tool (see docs/LAUNCH_HARNESS_PLAN.md B0).
            return self._search_files_fallback(query, target, glob=glob, max_results=max_results)
        except subprocess.TimeoutExpired as error:
            raise AgentToolError(504, "search_files timed out") from error
        if run.returncode not in {0, 1}:
            raise AgentToolError(422, _short(run.stderr, self.output_limit)["content"] or "search_files failed")
        results: list[dict[str, Any]] = []
        for line in run.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") != "match":
                continue
            data = item.get("data", {})
            raw_path = data.get("path", {}).get("text", "")
            try:
                file_path = Path(raw_path).resolve().relative_to(self.workspace).as_posix()
            except (ValueError, OSError):
                continue
            if not _is_permitted(file_path, self.allowed_paths):
                continue
            results.append({"path": file_path, "line": data.get("line_number"), "text": data.get("lines", {}).get("text", "").rstrip()[:1000]})
            if len(results) >= max_results:
                break
        return {"query": query, "results": results, "truncated": len(results) >= max_results, "engine": "ripgrep"}

    def _search_files_fallback(self, query: str, target: Path, *, glob: str | None, max_results: int) -> dict[str, Any]:
        """Pure stdlib line-search used when ripgrep is unavailable on PATH.

        Mirrors ripgrep's default behaviour closely enough for this tool's callers:
        regex line search, ignored-directory exclusion, optional glob filter, and a
        max_results cap. Binary/non-UTF-8 files are skipped rather than erroring out.
        """
        try:
            pattern = re.compile(query)
        except re.error as error:
            raise AgentToolError(422, f"Invalid search pattern: {error}") from error
        if target.is_file():
            candidates = [target]
        else:
            candidates = sorted(target.rglob("*"))
        results: list[dict[str, Any]] = []
        for item in candidates:
            if len(results) >= max_results:
                break
            if not item.is_file():
                continue
            try:
                relative = item.relative_to(self.workspace)
            except ValueError:
                continue
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            file_path = relative.as_posix()
            if not _is_permitted(file_path, self.allowed_paths):
                continue
            if glob and not fnmatch.fnmatch(file_path, glob) and not fnmatch.fnmatch(item.name, glob):
                continue
            try:
                text = item.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    results.append({"path": file_path, "line": line_number, "text": line.rstrip()[:1000]})
                    if len(results) >= max_results:
                        break
        return {"query": query, "results": results, "truncated": len(results) >= max_results, "engine": "python_fallback"}

    def replace_exact_text(self, path: str, old_text: str, new_text: str, expected_count: int = 1) -> dict[str, Any]:
        if not old_text:
            raise AgentToolError(422, "old_text must not be empty")
        if len(old_text.encode("utf-8")) > MAX_REPLACEMENT_BYTES or len(new_text.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
            raise AgentToolError(422, "Replacement text exceeds 100 KB limit")
        if not 1 <= expected_count <= 20:
            raise AgentToolError(422, "expected_count must be between 1 and 20")
        target = self.path(path, must_exist=True)
        if target.stat().st_size > MAX_FILE_BYTES:
            raise AgentToolError(422, "Workspace file exceeds 1 MB edit limit")
        try:
            original = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise AgentToolError(422, "replace_exact_text supports UTF-8 text files only") from error
        count = original.count(old_text)
        if count != expected_count:
            raise AgentToolError(409, f"Exact replacement expected {expected_count} matches, found {count}")
        updated = original.replace(old_text, new_text)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent, prefix=".ai-office-") as temporary:
            temporary.write(updated)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
        return {"path": str(target.relative_to(self.workspace)).replace("\\", "/"), "replacements": count, "bytes": len(updated.encode("utf-8"))}

    def create_file(self, path: str, content: str) -> dict[str, Any]:
        target = self.path(path)
        if target.exists():
            raise AgentToolError(409, "create_file refuses to overwrite an existing file")
        if len(content.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
            raise AgentToolError(422, "New file exceeds 100 KB limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": target.relative_to(self.workspace).as_posix(), "bytes": len(content.encode("utf-8"))}

    def find_symbols(self, symbol: str, path: str = ".", max_results: int = 40) -> dict[str, Any]:
        escaped = re.escape(symbol)
        pattern = rf"^\s*(?:async\s+def|def|class|interface|type|enum|function|const|let|var|export\s+(?:default\s+)?(?:class|function|const|interface|type))\s+{escaped}\b"
        return self.search_files(pattern, path=path, max_results=max_results)

    def find_references(self, symbol: str, path: str = ".", max_results: int = 60) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
            raise AgentToolError(422, "Symbol must be an identifier")
        return self.search_files(rf"\b{re.escape(symbol)}\b", path=path, max_results=max_results)

    def language_diagnostics(self, path: str) -> dict[str, Any]:
        target = self.path(path, must_exist=True)
        suffix = target.suffix.lower()
        if suffix == ".py":
            pyright = ROOT / "node_modules" / ".bin" / "pyright.cmd"
            if pyright.is_file():
                command = [str(pyright), "--outputjson", str(target)]
                provider = "pyright"
            else:
                command = [sys.executable, "-m", "py_compile", str(target)]
                provider = "python.py_compile"
        elif suffix in {".js", ".mjs", ".cjs"}:
            command = ["node", "--check", str(target)]
            provider = "node.syntax_check"
        else:
            raise AgentToolError(422, "Diagnostics support .py, .js, .mjs, and .cjs; use TaskContract verification for project-specific checks")
        try:
            run = subprocess.run(command, cwd=self.workspace, capture_output=True, text=True, timeout=30, shell=False)
        except FileNotFoundError as error:
            raise AgentToolError(503, f"Diagnostics provider unavailable: {provider}") from error
        except subprocess.TimeoutExpired as error:
            raise AgentToolError(504, "language_diagnostics timed out") from error
        diagnostics = (run.stderr or run.stdout).strip()
        if provider == "pyright" and run.stdout.strip():
            try:
                report = json.loads(run.stdout)
                diagnostics = json.dumps(report.get("generalDiagnostics", []), ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        return {"path": target.relative_to(self.workspace).as_posix(), "provider": provider, "ok": run.returncode == 0, "diagnostics": _short(diagnostics, self.output_limit)["content"]}

    def discover_tests(self, path: str = ".", max_results: int = 80) -> dict[str, Any]:
        if not 1 <= max_results <= 200:
            raise AgentToolError(422, "max_results must be between 1 and 200")
        target = self.path(path)
        if not target.is_dir():
            raise AgentToolError(422, "Test discovery path must be a directory")
        patterns = ("test_*.py", "*_test.py", "*.test.js", "*.spec.js", "*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx")
        files: list[str] = []
        for item in sorted(target.rglob("*")):
            if not item.is_file() or any(part in IGNORED_PARTS for part in item.relative_to(self.workspace).parts):
                continue
            relative = item.relative_to(self.workspace).as_posix()
            if _is_permitted(relative, self.allowed_paths) and any(item.match(pattern) for pattern in patterns):
                files.append(relative)
            if len(files) >= max_results:
                break
        commands = []
        package = self.workspace / "package.json"
        if package.is_file() and _is_permitted("package.json", self.allowed_paths):
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
                if "test" in scripts:
                    commands.append({"command": "npm.cmd test", "declared": str(scripts["test"])[:500]})
            except (OSError, json.JSONDecodeError):
                pass
        if any(item.endswith((".py",)) for item in files):
            commands.append({"command": "python -m unittest discover", "declared": "Python unittest discovery"})
        return {"files": files, "commands": commands, "truncated": len(files) >= max_results}

    def apply_unified_patch(self, patch: str) -> dict[str, Any]:
        if len(patch.encode("utf-8")) > 200_000:
            raise AgentToolError(422, "Patch exceeds 200 KB limit")
        changed = set()
        for match in re.finditer(r"^\+\+\+\s+(?:b/)?([^\t\r\n]+)", patch, re.MULTILINE):
            path = match.group(1)
            if path == "/dev/null":
                continue
            self.path(path)
            changed.add(path)
        if not changed:
            raise AgentToolError(422, "Patch contains no valid target paths")
        command = ["git", "apply", "--whitespace=nowarn", "-"]
        check = subprocess.run(
            [*command[:2], "--check", *command[2:]],
            cwd=self.workspace,
            input=patch,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        if check.returncode:
            raise AgentToolError(409, (check.stderr or check.stdout)[:1000] or "Patch check failed")
        applied = subprocess.run(
            command,
            cwd=self.workspace,
            input=patch,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
        if applied.returncode:
            raise AgentToolError(409, (applied.stderr or applied.stdout)[:1000] or "Patch apply failed")
        return {"paths": sorted(changed), "applied": True}

    def _git(self, args: list[str]) -> dict[str, Any]:
        try:
            run = subprocess.run(["git", *args], cwd=self.workspace, capture_output=True, text=True, timeout=20, shell=False)
        except FileNotFoundError as error:
            raise AgentToolError(503, "git is required for this tool") from error
        except subprocess.TimeoutExpired as error:
            raise AgentToolError(504, "git tool timed out") from error
        if run.returncode:
            detail = (run.stderr or run.stdout).strip()
            raise AgentToolError(409, detail[:500] or "Workspace is not a Git repository")
        return _short(run.stdout, self.output_limit)

    def _contract_pathspecs(self) -> list[str]:
        return [] if "." in self.allowed_paths else list(self.allowed_paths)

    def git_status(self) -> dict[str, Any]:
        args = ["status", "--short", "--branch", "--untracked-files=all"]
        pathspecs = self._contract_pathspecs()
        if pathspecs:
            args.extend(["--", *pathspecs])
        return self._git(args)

    def git_diff(self, path: str | None = None) -> dict[str, Any]:
        args = ["diff", "--no-ext-diff"]
        if path:
            target = self.path(path)
            args.extend(["--", str(target.relative_to(self.workspace)).replace("\\", "/")])
        else:
            pathspecs = self._contract_pathspecs()
            if pathspecs:
                args.extend(["--", *pathspecs])
        return self._git(args)

    def git_commit(self, message: str, paths: list[str]) -> dict[str, Any]:
        if not message.strip() or len(message) > 200 or "\n" in message or "\r" in message:
            raise AgentToolError(422, "Commit message must be one line containing 1-200 characters")
        if not 1 <= len(paths) <= 50:
            raise AgentToolError(422, "git_commit requires 1-50 explicit paths")
        pathspecs = []
        for item in dict.fromkeys(paths):
            target = self.path(item)
            pathspecs.append(str(target.relative_to(self.workspace)).replace("\\", "/"))
        self._git(["add", "--", *pathspecs])
        self._git(["commit", "--only", "-m", message.strip(), "--", *pathspecs])
        commit = self._git(["rev-parse", "HEAD"])["content"].strip()
        return {"commit": commit, "paths": pathspecs}

    def git_push(self, branch: str, remote: str = "origin") -> dict[str, Any]:
        safe_ref = re.compile(r"^[A-Za-z0-9._/-]+$")
        if not safe_ref.fullmatch(remote) or remote.startswith("-"):
            raise AgentToolError(422, "Git remote name is invalid")
        if not safe_ref.fullmatch(branch) or branch.startswith(("-", "/")) or ".." in branch:
            raise AgentToolError(422, "Git branch name is invalid")
        result = self._git(["push", remote, f"HEAD:{branch}"])
        return {"remote": remote, "branch": branch, **result}

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "search_files": self.search_files,
            "find_symbols": self.find_symbols,
            "find_references": self.find_references,
            "language_diagnostics": self.language_diagnostics,
            "discover_tests": self.discover_tests,
            "replace_exact_text": self.replace_exact_text,
            "apply_unified_patch": self.apply_unified_patch,
            "create_file": self.create_file,
            "git_status": self.git_status,
            "git_diff": self.git_diff,
            "git_commit": self.git_commit,
            "git_push": self.git_push,
            "fetch_public_source": fetch_public_source,
            "fetch_public_pdf": fetch_public_pdf,
            "render_public_page": render_public_page,
        }
        if name not in handlers:
            raise AgentToolError(404, "Unknown bounded agent tool")
        try:
            return handlers[name](**arguments)
        except TypeError as error:
            raise AgentToolError(422, f"Invalid arguments for {name}: {error}") from error
