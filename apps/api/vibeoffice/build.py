"""Internal MVP build scaffold and Gate F enforcement (slice S4).

Invariants this module owns:

* **Files land before the gate runs, unlike every earlier slice.** S2/S3/S3.5
  gate an in-memory package and only write on success. S4 cannot: Gate F needs
  a *real* build/test command to actually execute against *real* files, so the
  scaffold is written first and the gate judges the command's real exit code -
  there is no in-memory stand-in for "did `node scripts/build.js` succeed".
* **The scaffold is deliberately dependency-free.** No React/Vite install: this
  repo's own toolchain (``apps/web``) needs network + minutes for that, and the
  guide caps S4 at "70점대, 완성형 SaaS를 목표로 하지 않는다". A static
  HTML/vanilla-JS skeleton with two trivial Node scripts (no ``node_modules``)
  gives a *genuine* pass/fail command instead of a slower fake-real one. This is
  the mock boundary, and it is documented in PROJECT_STATUS.md/BUILD_REPORT.md,
  not hidden (guide: "mock 경계가 문서에 명시된다").
* **Command execution reuses ``policy.validate_command``**, the same allowlist+
  blocklist check ``main.run_command`` already uses - not a second command-safety
  implementation. VibeOffice does not otherwise touch ``main.tasks``/
  ``TaskContract``/the job queue (every S1-S3.5 module is self-contained on
  ``vo_*`` tables + workspace files), so S4 keeps that shape rather than wiring
  into the execution layer the guide's section 3 diagram sketches for the whole
  system - reusing the validator, not the task/contract machinery around it.
* **No new project state beyond the guide's own list.** ``BUILD`` while the
  scaffold/commands run, ``BUILD_VERIFICATION`` once evidence is recorded (guide
  section 5's state list already names both). Gate F bounce goes to
  ``REWORK_REQUIRED`` while still on ``ARCHITECTURE_REVIEW`` (guide section 9:
  코드·빌드·테스트 문제 -> Build), mirroring Gate C/D/PE's own bounce shape.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.api.vibeoffice import architecture as architecture_service
from apps.api.vibeoffice import artifacts as artifact_store
from apps.api.vibeoffice import blueprint as blueprint_service
from apps.api.vibeoffice import design as design_service
from apps.api import policy as command_policy
from apps.api.vibeoffice.schema import (
    ProjectNotFound,
    ProjectState,
    StateTransitionError,
    load_project,
    s2_database,
    set_project_state,
)

#: The only two commands Gate F may run. Exact-match against ``policy.
#: validate_command`` (same allowlist shape ``main.run_command`` enforces) -
#: nothing here ever shells out to anything the caller supplied.
BUILD_COMMAND = "node scripts/build.js"
TEST_COMMAND = "node scripts/test.js"
ALLOWED_COMMANDS = (BUILD_COMMAND, TEST_COMMAND)

#: Scaffold app directory, relative to the project workspace.
APP_DIRNAME = "app"

#: Kept short on purpose: the full stdout is hashed for evidence integrity, but
#: BUILD_REPORT.md only needs enough to show a human *why* a command failed.
_LOG_TAIL_CHARS = 2000


class GateFError(ValueError):
    """Gate F (Build) violation. Routes map this to 422."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Gate F(Build) 통과 실패: " + " / ".join(reasons))


@dataclass(frozen=True)
class ScaffoldEntity:
    name: str
    fields: tuple[str, ...]
    sample_rows: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "fields": list(self.fields), "sampleRows": [dict(row) for row in self.sample_rows]}


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_tail: str
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exitCode": self.exit_code,
            "stdoutSha256": self.stdout_sha256,
            "stderrSha256": self.stderr_sha256,
            "stdoutTail": self.stdout_tail,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class BuildEvidence:
    screen_ids: tuple[str, ...]
    entities: tuple[ScaffoldEntity, ...]
    build: CommandResult
    test: CommandResult
    mock_boundaries: tuple[str, ...]
    not_implemented: tuple[str, ...]
    working: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "screenIds": list(self.screen_ids),
            "entities": [entity.to_dict() for entity in self.entities],
            "build": self.build.to_dict(),
            "test": self.test.to_dict(),
            "mockBoundaries": list(self.mock_boundaries),
            "notImplemented": list(self.not_implemented),
            "working": list(self.working),
        }


# --------------------------------------------------------------------------- #
# Scaffold (deterministic, no model call - same discipline as design/architecture)
# --------------------------------------------------------------------------- #


def build_scaffold(
    workspace: Path,
    design_package: design_service.DesignPackage,
    architecture_package: architecture_service.ArchitecturePackage,
) -> tuple[tuple[str, ...], tuple[ScaffoldEntity, ...]]:
    """Write the static app/ skeleton and return (screen_ids, entities).

    Writes ``app/index.html``, ``app/mock-data.json``, ``app/package.json``,
    ``app/scripts/build.js``, ``app/scripts/test.js``. Everything is a pure
    function of the design/architecture packages, so regenerating twice
    overwrites with byte-identical content (same invariant every earlier
    slice's renderer holds).
    """
    root = workspace.resolve()
    app_dir = (root / APP_DIRNAME).resolve()
    if not app_dir.is_relative_to(root):
        raise ValueError("스캐폴드 경로가 워크스페이스를 벗어납니다.")
    (app_dir / "scripts").mkdir(parents=True, exist_ok=True)

    screen_ids = tuple(screen.id for screen in design_package.screens)
    entities = tuple(
        ScaffoldEntity(
            name=entity.name,
            fields=entity.fields,
            sample_rows=tuple(
                {field: f"{field}-샘플{row}" for field in entity.fields} for row in (1, 2)
            ),
        )
        for entity in architecture_package.entities
    )

    (app_dir / "index.html").write_text(render_index_html(design_package), encoding="utf-8")
    (app_dir / "mock-data.json").write_text(render_mock_data_json(entities), encoding="utf-8")
    (app_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "vibeoffice-mvp-scaffold",
                "private": True,
                "scripts": {"build": "node scripts/build.js", "test": "node scripts/test.js"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (app_dir / "scripts" / "build.js").write_text(render_build_script_js(), encoding="utf-8")
    (app_dir / "scripts" / "test.js").write_text(render_test_script_js(entities), encoding="utf-8")

    return screen_ids, entities


def run_smoke_commands(workspace: Path) -> tuple[CommandResult, CommandResult]:
    """Run the build then the test command inside ``app/``. Real subprocesses,
    real exit codes - Gate F judges what actually happened, not a stand-in."""
    app_dir = (workspace.resolve() / APP_DIRNAME).resolve()
    return _run(BUILD_COMMAND, app_dir), _run(TEST_COMMAND, app_dir)


def _run(command: str, cwd: Path) -> CommandResult:
    safe, reason = command_policy.validate_command(command, list(ALLOWED_COMMANDS))
    if not safe:
        # Unreachable through this module's own two constants, but the check
        # stays live for the same reason handoff.py keeps its unreachable Gate B
        # branch: it is the executable form of the policy, not decoration.
        return CommandResult(command=command, exit_code=1, stdout_sha256="", stderr_sha256="", stdout_tail=reason, ok=False)
    result = subprocess.run(
        shlex.split(command, posix=False), cwd=cwd, capture_output=True, text=True, timeout=60, shell=False
    )
    stdout_bytes = result.stdout.encode("utf-8", errors="replace")
    stderr_bytes = result.stderr.encode("utf-8", errors="replace")
    tail = (result.stdout + result.stderr)[-_LOG_TAIL_CHARS:]
    return CommandResult(
        command=command,
        exit_code=result.returncode,
        stdout_sha256=hashlib.sha256(stdout_bytes).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr_bytes).hexdigest(),
        stdout_tail=tail,
        ok=result.returncode == 0,
    )


# --------------------------------------------------------------------------- #
# Gate F (09A / guide section 8)
# --------------------------------------------------------------------------- #


def assert_gate_f(evidence: BuildEvidence) -> None:
    """Enforce Gate F. Raises ``GateFError``.

    Independent of ``build_scaffold``/``run_smoke_commands``: every check reads
    the ``BuildEvidence`` it is given, so a hand-built one with a failing command
    or an empty mock-boundary list is caught the same way a real failure would be.
    """
    reasons: list[str] = []
    if not evidence.build.ok:
        reasons.append(f"공식 build 명령이 실패했습니다 (exit {evidence.build.exit_code}).")
    if not evidence.test.ok:
        reasons.append(f"공식 test 명령이 실패했습니다 (exit {evidence.test.exit_code}).")
    if not evidence.screen_ids:
        reasons.append("스캐폴드된 화면이 없습니다.")
    if not evidence.mock_boundaries:
        reasons.append("mock 경계가 문서화되지 않았습니다.")
    if not evidence.not_implemented:
        reasons.append("미구현 항목이 명시되지 않았습니다.")
    if reasons:
        raise GateFError(reasons)


# --------------------------------------------------------------------------- #
# Markdown/HTML/JS/JSON rendering - filled in below.
# --------------------------------------------------------------------------- #

_MOCK_BOUNDARIES = (
    "프레임워크(React/Vite) 설치 없이 정적 HTML + vanilla JS로만 화면을 렌더한다.",
    "모든 데이터는 mock-data.json의 고정 샘플이며 실제 저장소·API 호출이 없다.",
    "인증·네트워크 오류 처리는 화면 문구로만 존재하고 실제 동작은 구현되지 않았다.",
)
_NOT_IMPLEMENTED = (
    "실제 프레임워크(React/Vite) 빌드 파이프라인",
    "실제 데이터 저장소 연동 (mock-data.json 대체)",
    "인증/권한 처리",
    "반응형 레이아웃의 실제 CSS 구현",
)


def render_index_html(design_package: design_service.DesignPackage) -> str:
    """Static HTML page showing all screens from the design package."""
    project_name = design_package.blueprint.get("projectName", "VibeOffice MVP")

    lines = [
        "<!DOCTYPE html>",
        '<html lang="ko">',
        "<head>",
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{project_name}</title>",
        "  <style>",
        '    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto; margin: 20px; line-height: 1.6; }',
        "    section { border: 1px solid #ddd; padding: 16px; margin: 16px 0; border-radius: 4px; }",
        "    h1 { margin-top: 0; }",
        "    h2 { margin-top: 0; font-size: 1.1em; }",
        "    p { margin: 8px 0; }",
        "    ul { margin: 8px 0; padding-left: 20px; }",
        "    footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #eee; font-size: 12px; color: #999; }",
        "  </style>",
        "</head>",
        "<body>",
        f"  <h1>{project_name}</h1>",
    ]

    for screen in design_package.screens:
        lines.append("  <section>")
        lines.append(f"    <h2>{screen.id} {screen.name}</h2>")
        lines.append(f"    <p><strong>목적:</strong> {screen.purpose}</p>")
        if screen.data_driven:
            entity_name = screen.id.replace("SCR-", "Entity")
            lines.append(f'    <ul data-entity="{entity_name}">')
            lines.append(f"      <li>데이터 영역 (mock-data.json에서 로드)</li>")
            lines.append(f"    </ul>")
        lines.append("  </section>")

    lines.append("  <footer>")
    lines.append("    <p>정적 MVP 스캐폴드입니다. 모든 데이터는 mock-data.json의 고정 샘플입니다.</p>")
    lines.append("  </footer>")
    lines.append("</body>")
    lines.append("</html>")

    return "\n".join(lines)


def render_mock_data_json(entities: tuple[ScaffoldEntity, ...]) -> str:
    """JSON representation of mock entities with sample rows."""
    return json.dumps(
        {entity.name: [dict(row) for row in entity.sample_rows] for entity in entities},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def render_build_script_js() -> str:
    """Node.js build script that validates mock-data.json and copies index.html to dist/."""
    lines = [
        'const fs = require("fs");',
        'const path = require("path");',
        "",
        "const appDir = path.dirname(__dirname);",
        "const mockDataPath = path.join(appDir, 'mock-data.json');",
        "const indexPath = path.join(appDir, 'index.html');",
        "const distDir = path.join(appDir, 'dist');",
        "const distIndexPath = path.join(distDir, 'index.html');",
        "",
        "try {",
        "  // Validate mock-data.json exists and is valid JSON",
        "  if (!fs.existsSync(mockDataPath)) {",
        '    console.error("ERROR: mock-data.json not found at " + mockDataPath);',
        "    process.exit(1);",
        "  }",
        "",
        "  const mockContent = fs.readFileSync(mockDataPath, 'utf8');",
        "  const mockData = JSON.parse(mockContent);",
        "",
        "  if (Object.keys(mockData).length === 0) {",
        '    console.error("ERROR: mock-data.json has no keys");',
        "    process.exit(1);",
        "  }",
        "",
        "  // Validate index.html exists",
        "  if (!fs.existsSync(indexPath)) {",
        '    console.error("ERROR: index.html not found at " + indexPath);',
        "    process.exit(1);",
        "  }",
        "",
        "  // Create dist directory and copy index.html",
        "  if (!fs.existsSync(distDir)) {",
        "    fs.mkdirSync(distDir, { recursive: true });",
        "  }",
        "  fs.copyFileSync(indexPath, distIndexPath);",
        "",
        '  console.log("build ok");',
        "  process.exit(0);",
        "} catch (err) {",
        '  console.error("ERROR: " + err.message);',
        "  process.exit(1);",
        "}",
    ]
    return "\n".join(lines) + "\n"


def render_test_script_js(entities: tuple[ScaffoldEntity, ...]) -> str:
    """Node.js test script that validates mock-data.json structure and entity keys."""
    expected_keys = [entity.name for entity in entities]
    expected_keys_str = ", ".join(f'"{key}"' for key in expected_keys)
    expected_count = len(entities)

    lines = [
        'const fs = require("fs");',
        'const path = require("path");',
        'const assert = require("assert");',
        "",
        "const appDir = path.dirname(__dirname);",
        "const mockDataPath = path.join(appDir, 'mock-data.json');",
        "",
        "try {",
        "  // Read and parse mock-data.json",
        "  if (!fs.existsSync(mockDataPath)) {",
        '    console.error("ERROR: mock-data.json not found at " + mockDataPath);',
        "    process.exit(1);",
        "  }",
        "",
        "  const mockContent = fs.readFileSync(mockDataPath, 'utf8');",
        "  const mockData = JSON.parse(mockContent);",
        "",
        f"  // Assert exactly {expected_count} top-level keys",
        f"  const keyCount = Object.keys(mockData).length;",
        f"  assert.strictEqual(keyCount, {expected_count}, `Expected {expected_count} top-level keys, got ${{keyCount}}`);",
        "",
        "  // Assert each expected key exists and has a non-empty array value",
        f"  const expectedKeys = [{expected_keys_str}];",
        "  for (const key of expectedKeys) {",
        f"    assert(key in mockData, `Missing expected key: ${{key}}`);",
        f"    assert(Array.isArray(mockData[key]), `Expected array for key ${{key}}, got ${{typeof mockData[key]}}`);",
        f"    assert(mockData[key].length > 0, `Expected non-empty array for key ${{key}}`);",
        "  }",
        "",
        '  console.log("test ok");',
        "  process.exit(0);",
        "} catch (err) {",
        '  console.error("ERROR: " + err.message);',
        "  process.exit(1);",
        "}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Evidence documents - filled in below.
# --------------------------------------------------------------------------- #

def render_project_status(evidence: BuildEvidence) -> str:
    """Markdown PROJECT_STATUS document from build evidence."""
    build_status = "build ok" if evidence.build.ok else "build failed"

    lines = [
        "# PROJECT STATUS",
        "",
        f"Last verified: {build_status}",
        "",
        "## Working",
        "",
    ]
    lines += [f"- {item}" for item in evidence.working]
    lines += [
        "",
        "## Partial",
        "",
        "- 화면 스캐폴드는 정적 HTML이며 실제 프레임워크 빌드는 아직 없다.",
        "",
        "## Not Implemented",
        "",
    ]
    lines += [f"- {item}" for item in evidence.not_implemented]
    lines += [
        "",
        "## Next",
        "",
        "`NEXT_ACTION.md`",
    ]
    return "\n".join(lines) + "\n"


def render_build_report(evidence: BuildEvidence) -> str:
    """Markdown BUILD_REPORT document from build evidence."""
    build_status = "성공" if evidence.build.ok else "실패"
    test_status = "성공" if evidence.test.ok else "실패"

    lines = [
        "# BUILD REPORT",
        "",
        "## Status",
        "",
        f"build: {build_status} (exit {evidence.build.exit_code}) / test: {test_status} (exit {evidence.test.exit_code})",
        "",
        "## Mock Boundaries",
        "",
    ]
    lines += [f"- {item}" for item in evidence.mock_boundaries]
    lines += [
        "",
        "## Not Implemented",
        "",
    ]
    lines += [f"- {item}" for item in evidence.not_implemented]
    lines += [
        "",
        "## Evidence",
        "",
        "| command | exit code | stdout sha256 | stderr sha256 |",
        "|---|---|---|---|",
    ]
    lines.append(
        f"| {evidence.build.command} | {evidence.build.exit_code} | {evidence.build.stdout_sha256} | {evidence.build.stderr_sha256} |"
    )
    lines.append(
        f"| {evidence.test.command} | {evidence.test.exit_code} | {evidence.test.stdout_sha256} | {evidence.test.stderr_sha256} |"
    )
    lines += [
        "",
        "## Recommended Next",
        "",
        "`NEXT_ACTION.md`",
    ]
    return "\n".join(lines) + "\n"


def render_current_state(evidence: BuildEvidence) -> str:
    """JSON current-state document from build evidence."""
    return json.dumps(evidence.to_dict(), ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# Department run
# --------------------------------------------------------------------------- #

_RETRY_STATES = frozenset({ProjectState.REWORK_REQUIRED.value})


def _has_recorded_baseline(db: Any, project_id: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM vo_artifacts WHERE project_id = ? AND type = ? AND current_version_id IS NOT NULL",
        (project_id, artifact_store.ARTIFACT_PRD),
    ).fetchone()
    return row is not None


def run_build(project_id: str) -> dict[str, Any]:
    """Scaffold the internal MVP, run build+test, gate the result, record evidence."""
    with s2_database() as db:
        project = load_project(db, project_id)
        state = project["state"]
        allowed = state == ProjectState.ARCHITECTURE_REVIEW.value or (
            state in _RETRY_STATES and _has_recorded_baseline(db, project_id)
        )
        if not allowed:
            raise StateTransitionError(
                f"Execution Baseline 완료 전에는 빌드를 시작할 수 없습니다. 현재 상태: {state} "
                f"(필요 상태: {ProjectState.ARCHITECTURE_REVIEW.value})"
            )
        workspace = Path(project["workspace_path"])

    approved = blueprint_service.get_blueprint(project_id)
    content = approved["blueprint"]
    design_package = design_service.build_design_package(content)
    architecture_package = architecture_service.build_architecture_package(design_package, content)

    screen_ids, entities = build_scaffold(workspace, design_package, architecture_package)
    build_result, test_result = run_smoke_commands(workspace)
    evidence = BuildEvidence(
        screen_ids=screen_ids,
        entities=entities,
        build=build_result,
        test=test_result,
        mock_boundaries=_MOCK_BOUNDARIES,
        not_implemented=_NOT_IMPLEMENTED,
        working=tuple(f"{screen_id} 화면 정적 스캐폴드" for screen_id in screen_ids),
    )

    try:
        assert_gate_f(evidence)
    except GateFError:
        with s2_database() as db:
            set_project_state(db, project_id, ProjectState.REWORK_REQUIRED)
        raise

    with s2_database() as db:
        project = load_project(db, project_id)
        set_project_state(db, project_id, ProjectState.BUILD)
        versions = artifact_store.peek_next_versions(db, project_id, artifact_store.BUILD_EVIDENCE_TYPES)
        documents = {
            artifact_store.ARTIFACT_PROJECT_STATUS: render_project_status(evidence),
            artifact_store.ARTIFACT_BUILD_REPORT: render_build_report(evidence),
            artifact_store.ARTIFACT_CURRENT_STATE: render_current_state(evidence),
        }
        written = []
        for artifact_type in artifact_store.BUILD_EVIDENCE_TYPES:
            written.append(
                artifact_store.record_artifact(
                    db,
                    project,
                    artifact_type,
                    documents[artifact_type],
                    source_blueprint_version=approved["version"],
                    depends_on=[f"project-blueprint@{approved['version']}"],
                    created_by=artifact_store.BUILD_OWNER,
                    directory=artifact_store.BUILD_EVIDENCE_DIRECTORY[artifact_type],
                )
            )
        state = set_project_state(db, project_id, ProjectState.BUILD_VERIFICATION)
        return {
            "project_id": project_id,
            "state": state.value,
            "source_blueprint_version": approved["version"],
            "screen_count": len(evidence.screen_ids),
            "entity_count": len(evidence.entities),
            "build_ok": evidence.build.ok,
            "test_ok": evidence.test.ok,
            "evidence": evidence.to_dict(),
            "artifacts": written,
        }


__all__ = [
    "ALLOWED_COMMANDS",
    "BUILD_COMMAND",
    "TEST_COMMAND",
    "BuildEvidence",
    "CommandResult",
    "GateFError",
    "ScaffoldEntity",
    "assert_gate_f",
    "build_scaffold",
    "run_build",
    "run_smoke_commands",
    "ProjectNotFound",
    "StateTransitionError",
]
