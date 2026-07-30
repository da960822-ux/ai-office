"""Bounded local tools for AI Office agents.

This module deliberately has no database or FastAPI dependency.  The API layer
supplies a task workspace and TaskContract allow-list, then translates
``AgentToolError`` into its own transport error/event format.
"""
from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
import subprocess
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


def tool_definitions() -> list[dict[str, Any]]:
    """OpenAI Responses function definitions. Mutation tools remain explicit."""
    return [
        {"type": "function", "name": "list_files", "description": "List TaskContract-allowed workspace files without reading their contents.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "default": "."}, "glob": {"type": "string", "default": "*"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200}}, "additionalProperties": False}},
        {"type": "function", "name": "read_file", "description": "Read one bounded UTF-8 workspace file with line numbers and optional line range.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "start_line": {"type": "integer", "minimum": 1, "default": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"], "additionalProperties": False}},
        {"type": "function", "name": "search_files", "description": "Search UTF-8 workspace files with ripgrep. Results are path, line, and matching text; ignored build/dependency folders are excluded.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300}, "path": {"type": "string", "default": "."}, "glob": {"type": "string", "maxLength": 200}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40}}, "required": ["query"], "additionalProperties": False}},
        {"type": "function", "name": "find_symbols", "description": "Find class, function, type, interface, and variable definitions with ripgrep before reading files.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string", "minLength": 1, "maxLength": 200}, "path": {"type": "string", "default": "."}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40}}, "required": ["symbol"], "additionalProperties": False}},
        {"type": "function", "name": "replace_exact_text", "description": "Safely replace an exact text fragment in one allowed UTF-8 workspace file. Default requires exactly one match; use expected_count only when every replacement is intended.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "old_text": {"type": "string", "minLength": 1, "maxLength": 50000}, "new_text": {"type": "string", "maxLength": 100000}, "expected_count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1}}, "required": ["path", "old_text", "new_text"], "additionalProperties": False}},
        {"type": "function", "name": "apply_unified_patch", "description": "Apply a bounded unified diff atomically after `git apply --check`. Every changed path must be TaskContract-allowed.", "parameters": {"type": "object", "properties": {"patch": {"type": "string", "minLength": 1, "maxLength": 200000}}, "required": ["patch"], "additionalProperties": False}},
        {"type": "function", "name": "create_file", "description": "Create a new UTF-8 file. Refuses to overwrite an existing file.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "content": {"type": "string", "maxLength": 100000}}, "required": ["path", "content"], "additionalProperties": False}},
        {"type": "function", "name": "git_status", "description": "Read concise Git working-tree status for assigned workspace.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"type": "function", "name": "git_diff", "description": "Read bounded Git diff for assigned workspace. Optional path must be inside TaskContract allowed paths.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "maxLength": 500}}, "additionalProperties": False}},
        {"type": "function", "name": "git_commit", "description": "Commit only explicitly listed TaskContract-allowed paths. Available only when the contract grants `git commit *`.", "parameters": {"type": "object", "properties": {"message": {"type": "string", "minLength": 1, "maxLength": 200}, "paths": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 500}, "minItems": 1, "maxItems": 50}}, "required": ["message", "paths"], "additionalProperties": False}},
        {"type": "function", "name": "git_push", "description": "Push HEAD to an explicit remote branch. Available only when the contract grants `git push *`.", "parameters": {"type": "object", "properties": {"remote": {"type": "string", "minLength": 1, "maxLength": 80, "default": "origin"}, "branch": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["branch"], "additionalProperties": False}},
        {"type": "function", "name": "fetch_public_source", "description": "Read one original public HTTP(S) source. Private/local addresses, redirects, non-text content, and oversized responses are rejected.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "minLength": 8, "maxLength": 2000}}, "required": ["url"], "additionalProperties": False}},
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
        except FileNotFoundError as error:
            raise AgentToolError(503, "ripgrep (rg) is required for search_files") from error
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
        return {"query": query, "results": results, "truncated": len(results) >= max_results}

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
            "replace_exact_text": self.replace_exact_text,
            "apply_unified_patch": self.apply_unified_patch,
            "create_file": self.create_file,
            "git_status": self.git_status,
            "git_diff": self.git_diff,
            "git_commit": self.git_commit,
            "git_push": self.git_push,
            "fetch_public_source": fetch_public_source,
        }
        if name not in handlers:
            raise AgentToolError(404, "Unknown bounded agent tool")
        try:
            return handlers[name](**arguments)
        except TypeError as error:
            raise AgentToolError(422, f"Invalid arguments for {name}: {error}") from error
