# P1 Completion and Harness Plan

## Implemented P1 controls

- Independent ready phases run in separate OS worker processes by default. Set `AI_OFFICE_WORKER_MODE=thread` only for local debugging.
- Parallel Git phases use one branch/worktree per employee. Agent commit is immutable pending review; `GUARD` reviews it (`LENS` reviews `GUARD`) before serialized cherry-pick. A failed review or conflict blocks the task.
- Code navigation includes symbol search, reference search, Pyright diagnostics when installed, syntax fallback, and local test discovery. Project test execution remains TaskContract-gated.
- Research supports safe HTML extraction, public PDF text extraction, and approved headless-browser rendering for JavaScript pages. Browser rendering defaults to `ask` permission.
- Material research claims persist claim text, verified source URL, publisher, date, retrieved source span, confidence, and contradictions. Research cannot finish without claim-to-source evidence.
- Rendered deliverables are reopened and validated: DOCX, PDF, XLSX, PPTX, and HWPX. HWPX uses local pinned `kordoc`; output is parsed after generation.
- Retry API selects an unused failure-class playbook strategy when caller does not provide one. Repeated/exhausted strategies escalate rather than replaying identical prompts.

## Remaining platform boundary

- Binary `.hwp` authoring is not safe to emulate. System creates and validates standards-based `.hwpx`; direct `.hwp` creation needs a separately installed Hancom-compatible binary editing engine. A request for `.hwp` must therefore be converted to HWPX or blocked with this reason, never fulfilled by renaming another file.
- Full language-server protocol support varies by language server availability. Pyright runs as installed semantic diagnostics for Python. Other language ecosystems use bounded syntax/test discovery until their specific LSP server is installed and registered.

## P2 fixed acceptance harness

Create deterministic fixtures under `apps/api/fixtures/` and execute them in CI. Each fixture records expected artifact paths, evidence, phase order, prohibited skills, and verification commands.

1. Research-to-PRD: verify two independent originals, claim provenance, one recommendation, PRD handoff.
2. PRD-to-code: verify worktree review before merge, relevant diff, test evidence, independent final review.
3. Document: verify DOCX/PDF/PPTX/HWPX/XLSX requested formats reopen successfully.
4. Failure matrix: permission ask/deny, Git conflict, model timeout, failed verification, repeated retry strategy, worker restart.
5. Policy regression: no UI skill loaded for market research; no department executes another department's owned phase.

Release gate: all fixtures pass; no task reaches `completed` without current approved artifact, independent review, fresh evidence, and required user approval.
