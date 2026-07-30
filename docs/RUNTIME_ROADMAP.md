# Agent Runtime Roadmap

`AGENT_RUNTIME_IMPROVEMENT_PLAN.md`와 `P1_HARNESS_PLAN.md`를 통합한 문서다. 현재 런타임의 동작 사실은 [RUNTIME_HARDENING.md](RUNTIME_HARDENING.md), 제품 파이프라인 계획은 [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md)를 본다.

## Objective

Move AI Office from role-labelled prompt orchestration to evidence-backed execution:

1. research discovers and verifies original sources;
2. planning consumes research artifacts and produces an explicit decision/specification;
3. implementation consumes the approved specification and changes the opened project;
4. independent review verifies the final artifact;
5. completion is impossible without real files and recorded evidence.

## P0 — enforced in current runtime

- Store every planned/delegated phase as a first-class `task_phases` row.
- Keep meeting worker delegation; never replace a valid worker proposal with a lead placeholder.
- Gate dependent phases on completed upstream phases with artifact IDs.
- Preserve upstream deliverable content in downstream agent context.
- Generate department drafts, one integrated final artifact, and an artifact hash.
- Require a non-empty final file, matching hash, completed phases, no other active job, and independent passing review before `completed`.
- Use `GUARD` as independent reviewer; use `LENS` when `GUARD` owns the final artifact.
- Accept additional user instructions through a durable steering queue and inject them at the next model/tool boundary.
- Give implementation agents bounded `search_files`, `replace_exact_text`, `git_status`, and `git_diff` tools.
- Expose path-scoped `git_commit` and explicit-branch `git_push` only when TaskContract grants `git commit *` or `git push *`.
- Give research agents bounded original-source fetching; search snippets remain non-evidence.
- Limit skills to three selected skills and enforce task-kind activation rules. UI/design skills are blocked for market research, business strategy, document authoring, backend implementation, and quality review.

## P1 — implemented

- Independent ready phases run in separate OS worker processes by default. Set `AI_OFFICE_WORKER_MODE=thread` only for local debugging.
- Parallel Git phases use one branch/worktree per employee. Agent commit is immutable pending review; `GUARD` reviews it (`LENS` reviews `GUARD`) before serialized cherry-pick. A failed review or conflict blocks the task.
- Code navigation includes symbol search, reference search, Pyright diagnostics when installed, syntax fallback, and local test discovery. Project test execution remains TaskContract-gated.
- Research supports safe HTML extraction, public PDF text extraction, and approval-gated headless-browser rendering for JavaScript pages (default `ask`).
- Material research claims persist claim text, verified source URL, publisher, date, retrieved source span, confidence, and contradictions. Research cannot finish without claim-to-source evidence.
- Rendered deliverables are reopened and validated: DOCX, PDF, XLSX, PPTX, HWPX. HWPX uses local pinned `kordoc`; output is parsed after generation.
- Retry API selects an unused failure-class playbook strategy when the caller does not provide one. Repeated/exhausted strategies escalate rather than replaying identical prompts.

## Remaining platform boundaries

- Binary `.hwp` authoring is not safe to emulate. The runtime creates and validates standards-based `.hwpx`; direct `.hwp` creation needs a separately installed Hancom-compatible engine. A `.hwp` request is converted to HWPX or blocked with this reason — never fulfilled by renaming another file.
- Full LSP support varies by language server availability. Pyright runs as installed semantic diagnostics for Python; other ecosystems use bounded syntax/test discovery until their LSP server is installed and registered.
- `ripgrep` (`rg`) must be installed locally. Without it `search_files`/`find_symbols` fail with HTTP 503 and 3 tests in `apps/api/test_agent_tools.py` error.

## P2 — fixed acceptance harness (미구현)

Create deterministic fixtures under `apps/api/fixtures/` and execute them in CI. Each fixture records expected artifact paths, evidence, phase order, prohibited skills, and verification commands.

1. Research-to-PRD: two independent originals, claim provenance, one recommendation, PRD handoff.
2. PRD-to-code: worktree review before merge, relevant diff, test evidence, independent final review.
3. Document: DOCX/PDF/PPTX/HWPX/XLSX requested formats reopen successfully.
4. Failure matrix: permission ask/deny, Git conflict, model timeout, failed verification, repeated retry strategy, worker restart.
5. Policy regression: no UI skill loaded for market research; no department executes another department's owned phase.

Maintain 30-50 fixed tasks across research, PRD, marketing, coding, QA, documents, and Git delivery.

Release gates:

- zero completed tasks without an approved existing artifact;
- zero dependent phases executed before upstream artifacts exist;
- every final result reviewed by an agent other than the final owner;
- at least 90% of material research claims linked to verified original sources;
- at least 80% of coding fixtures produce a relevant diff and passing tests;
- zero market-research runs loading UI/design skills;
- no stale running agent/job state after recovery;
- requested document formats open and pass render checks;
- user steering remains durable and is applied once.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py" -v
.\.venv\Scripts\python.exe scripts\verify_routing.py
.\.venv\Scripts\python.exe scripts\verify_skills.py --include-optional
.\.venv\Scripts\python.exe scripts\audit_package.py
cd apps\web; npm.cmd test -- --run; npm.cmd run build
```
