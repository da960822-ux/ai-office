# Agent Runtime Improvement Plan

## Objective

Move AI Office from role-labelled prompt orchestration to evidence-backed execution:

1. research discovers and verifies original sources;
2. planning consumes research artifacts and produces an explicit decision/specification;
3. implementation consumes the approved specification and changes the opened project;
4. independent review verifies the final artifact;
5. completion is impossible without real files and recorded evidence.

## P0: enforced in current runtime

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

## P1: implemented

- Independent ready phases run in separate worker processes by default.
- Each implementation phase uses Git branch/worktree; independent review passes before serialized merge.
- Symbol/reference search, Pyright diagnostics, syntax fallback, and test discovery are bounded tools.
- HTML, public-PDF extraction, and approval-gated headless browser rendering cover static, report, and JavaScript sources.
- Claim-to-source evidence stores claim, source URL, publisher, publication date, text span, confidence, and contradictions.
- DOCX/PDF/XLSX/PPTX/HWPX outputs are generated then reopened/parsed; no Markdown relabelling.
- Failure-class retry playbooks choose unused strategy; repeated/exhausted strategy escalates.

Binary `.hwp` authoring remains external-engine-only. Runtime generates standards-based `.hwpx` and blocks false `.hwp` claims.

## P2: product acceptance program

Maintain 30-50 fixed tasks across research, PRD, marketing, coding, QA, documents, and Git delivery.

Required release gates:

- zero completed tasks without an approved existing artifact;
- zero dependent phases executed before upstream artifacts exist;
- every final result reviewed by an agent other than the final owner;
- at least 90% of material research claims linked to verified original sources;
- at least 80% of coding fixtures produce a relevant diff and passing tests;
- zero market-research runs loading UI/design skills;
- no stale running agent/job state after recovery;
- requested document formats open and pass render checks;
- user steering remains durable and is applied once.

## Current verification

Run:

```powershell
.venv\Scripts\python.exe -m unittest apps.api.test_workflow_acceptance apps.api.test_agent_tools apps.api.test_job_workflow apps.api.test_workflow_e2e -v
.venv\Scripts\python.exe scripts/verify_routing.py
.venv\Scripts\python.exe scripts/verify_skills.py --include-optional
npm.cmd test
```
