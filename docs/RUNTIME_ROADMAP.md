# Agent Runtime Roadmap

`AGENT_RUNTIME_IMPROVEMENT_PLAN.md`와 `P1_HARNESS_PLAN.md`를 통합한 문서다. 현재 런타임의 동작 사실은 [RUNTIME_HARDENING.md](RUNTIME_HARDENING.md), 제품 파이프라인 계획은 [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](../reference/legacy/VIBEOFFICE_IMPLEMENTATION_GUIDE.md)를 본다.

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

## P3 — GenTeam-inspired runtime UX (제안, 미구현)

사용자가 GenTeam(범용 협업 공간)에서 가치가 크다고 지목한 기능 중, 실행 계층에 이미 있는 데이터를 노출하거나 소규모 필드를 추가하면 되는 항목만 담는다. 이미 충족된 항목(직원 역할/스킬/모델 라우팅/독립 리뷰/실패 승격)은 [VIBEOFFICE_GAP_ANALYSIS.md 5절](../reference/legacy/VIBEOFFICE_GAP_ANALYSIS.md)을 본다. 각 슬라이스는 기존 테이블·엔드포인트를 확장하고, 신규 모듈이 필요하면 `main.py`에 넣지 않는다.

| 슬라이스 | 내용 | 근거 데이터(이미 존재) | 신규 작업 | 우선순위 |
|---|---|---|---|---|
| R1. 직원 프로필 카드 | 역할·기본 모델·보유 스킬·실행 권한을 한 카드에 표시 | `registry/employees.json`, `registry/model-routing.json`, `employees/*/PERMISSIONS.yaml` | 세 파일을 조인하는 `GET /api/registry/employees/{id}/profile` 1개 + UI 카드 컴포넌트 | 높음 (표시만, 로직 변경 없음) |
| R2. 작업판 4단계 보드 | `TASK_STATES`를 할 일·진행 중·검토 중·완료·반송 4버킷으로 그루핑해 칸반으로 표시 | `apps/api/main.py` `TASK_STATES`/`STATE_LABELS` | 상태→버킷 매핑 테이블 1개(코드) + UI 보드 뷰. 상태 머신 자체는 변경 없음 | 높음 |
| R3. 기본 담당자 단일 필드 | 작업 1건에 기본 담당자 1명, 검토자는 필요할 때만 별도 지정 | `leads`(1~4명), `final_owner`(통합 책임) | `tasks.assignee_id` 필드 추가(nullable, 기본값 = `final_owner` 또는 단일 lead일 때 자동 채움). 기존 다중 리드 배정과 병행 — 대체하지 않음 | 중간 (스키마 마이그레이션 필요) |
| R4. 승인 경계 카탈로그 | 파일 삭제·외부 발송·배포·API 키/권한 변경·운영 데이터 수정 5개 범주를 사용자에게 고정 목록으로 보여줌 | `apps/api/policy.py` `BLOCKED_TOKENS`, `permission_rules` | 신규 파일 *registry/approval-boundaries.json*(범주→기본 `deny`/`ask` 패턴 매핑) + 설정 화면에 읽기 전용 카탈로그 표시. 실제 차단 로직은 기존 `permission_effect`/`BLOCKED_TOKENS` 재사용, 범주는 표시·문서화 목적 | 중간 |
| R5. 예상 비용 | 모델 호출 전 입력 토큰 추정치 × 모델 단가로 예상 비용 표시 | `model_routing()`(모델 이름) | 신규 파일 *registry/model-pricing.json*(모델별 $/1M input·output) + 호출 전 추정 함수. OpenRouter 단가는 주기적으로 수동 갱신 필요(자동 동기화는 범위 밖) | 낮음 (단가 유지보수 비용 있음) |
| R6. 실제 비용 | `model_usage.cost_usd`가 항상 0인 것을 실제 토큰×단가로 채움 | `model_usage(input_tokens, output_tokens)` | R5의 단가 테이블을 재사용해 `worker.py`의 두 `INSERT INTO model_usage` 지점에서 `cost_usd` 계산. 스키마 변경 없음, 계산 로직만 추가 | 낮음 (R5에 의존) |
| R7. 로컬 vs API 실행 표시 | 각 모델 호출이 로컬 실행인지 API 실행인지 구분 | 없음. 현재 100% OpenRouter API | `model_usage.execution_location` 컬럼 추가, 지금은 전부 `"api"`로 채움. 로컬 실행 자체는 R8에 의존 | 낮음 (지금은 표시만, 값은 항상 api) |
| R8. 로컬 Claude Code·Codex 연결 | 직원 실행기를 OpenRouter API 대신 로컬 CLI로 전환 | `employees/*/skills/doubt-driven-development/SKILL.md`(사람이 수동 실행하는 2차 검토 CLI 호출만 존재) | `registry/model-routing.json`에 `provider`(`openrouter`/`local_cli`) 필드 추가, `apps/api/worker.py` 모델 호출 지점에 provider 분기, 로컬 CLI 프로세스 실행·타임아웃·에러 처리 신설. 인증·샌드박스·비동기 실행 문제로 별도 설계 문서가 필요한 규모 | 낮음 (설계 선행 필요, 후순위) |
| R9. 호출형 에이전트(대화에 항상 끼어들지 않음) | NAVI/담당자가 부를 때만 실행 | Job 큐 자체가 이미 요청 기반(끼어들지 않음)이지만 대화 계층이 없어 "호출"이라는 사용자 경험이 없음 | [CONVERSATIONAL_AGENT_TARGET.md](../reference/legacy/CONVERSATIONAL_AGENT_TARGET.md) C1~C5 슬라이스에 종속. 별도 신규 작업 없음 | C1~C5 완료 후 |

권장 순서: R1·R2(표시 전용, 로직 변경 없음) → R4(문서화 성격) → R3(스키마 변경 1개) → R5·R6(단가 테이블) → R7 → R9(대화 계층 선행) → R8(설계 문서 먼저).

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py" -v
.\.venv\Scripts\python.exe scripts\verify_routing.py
.\.venv\Scripts\python.exe scripts\verify_skills.py --include-optional
.\.venv\Scripts\python.exe scripts\audit_package.py
cd apps\web; npm.cmd test -- --run; npm.cmd run build
```
