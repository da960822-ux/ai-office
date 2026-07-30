# Durable Agent Runtime v9

## Execution model

- Each employee owns one durable `agent_sessions` record per task.
- Recent six turns remain verbatim and older context compacts into a bounded rolling summary.
- Task checkpoints contain task state, phases, artifacts, evidence, and agent sessions.
- Checkpoints can be restored only while no Job is active; later evidence becomes stale.
- Independent ready phases become separate Jobs. Four OS worker processes run Jobs concurrently by default.
- Phase dependencies create execution waves. Downstream Jobs are not queued until upstream artifacts exist.

## Workspace and Git

- Git projects receive one branch and worktree per parallel employee.
- Agent changes become an explicit commit, then independent `GUARD`/`LENS` diff review.
- Only passing integration review uses serialized `git cherry-pick`.
- Conflicts abort the cherry-pick and block completion; they are never silently overwritten.
- Dirty or non-Git roots fall back to the selected task workspace.

## Tools and permissions

- Discovery: bounded file listing, line-range reads, ripgrep symbol/reference search, Pyright diagnostics, and test discovery.
- Editing: exact replacement, atomic unified patch, create-only file writes.
- Evidence: bounded shell verification, Git status/diff/commit/push, public source fetch, MCP tools.
- `TaskContract.permission_rules` supports `allow`, `ask`, and `deny` by tool and target pattern.
- `ask` creates a durable permission request and stops the active call with HTTP 428.

## Research

- Search providers: Brave API, SearXNG, then Bing RSS fallback; public PDFs extract text directly.
- Dynamic browser rendering is approval-gated and uses local headless Chrome/Edge.
- HTML parsing ignores scripts, styles, templates, SVG, and non-content elements.
- Research completion requires search plus two verified originals from independent domains.
- Browser and external research tools can be added through MCP without changing agent code.

## Deliverables and completion

- Primary artifact remains `FINAL.md`.
- Final synthesis also renders HTML, DOCX, PDF, `ARTIFACTS.json`, XLSX for financial models, and requested PPTX/HWPX.
- Every rendered file receives hash evidence and a registry record.
- Implementation and release tasks require a successful executed verification command.
- Current failing verification evidence blocks completion.
- Independent review, final-file hash, completed dependency phases, and required user approvals remain mandatory.

## Failure controls

- Model calls have a configurable hard deadline through `AI_OFFICE_MODEL_TIMEOUT_SECONDS`.
- Jobs retain leases and heartbeats.
- Restart recovery marks active runs and sessions interrupted.
- Cancel, pause, timeout, Git conflict, permission denial, and verification failure cannot produce completed state.
