# AI 자동화 오피스 V1 구현 계획 (폐기 · 2026-07-30 보관)

> **폐기 사유**: 이 문서가 제시한 `packages/contracts`, `policy-engine`, `orchestrator`, `harness`, `evidence`, `office-projection` 패키지 구조는 구현되지 않았다. 실제 구현은 `apps/api/main.py` + `apps/api/worker.py` 단일 모듈이다. 현재 런타임 사실은 `docs/RUNTIME_HARDENING.md`, 로드맵은 `docs/RUNTIME_ROADMAP.md`, 제품 방향은 `docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md`를 본다. 이 문서는 V1 설계 의도와 미구현 범위(BYO 스킬 inbox, 예산 상한 등) 참조용으로만 남긴다.

## 1. 제품 목표

AI 자동화 오피스는 단일 사용자가 로컬 프로젝트 하나를 선택해, 조직처럼 협업하는 24명 AI 직원에게 기획·조사·설계·코드·문서·검증 업무를 맡기는 로컬 운영 시스템이다.

기본 흐름은 다음과 같다.

```text
사용자 요청 → NAVI 접수·계약 → 관련 팀장 회의 → FRAME 업무 분해
→ 팀 배정·실행 → 팀/교차 검토 → BUILD·GUARD·TRACE·EVAL 검증
→ 실패 진단·제한 재작업 → NAVI 최종 승인 → 근거·교훈 저장
```

이 시스템은 코드 실행기나 역할극 채팅이 아니다. 회의 결정, 배정, 실행, 검토, 검증, 재작업, 승인, 시각적 오피스 상태는 같은 `Task`, `Event`, `Run` 데이터에서 파생된다.

## 2. V1 범위와 비범위

### V1 범위

- localhost 단일 사용자, 선택 가능한 로컬 프로젝트 1개.
- 기존 24명 직원 레지스트리, 역할, 권한, 스킬 binding/lock 조회와 검증.
- `TaskContract`, 부서 선택, 최소 팀장 회의, FRAME 업무 분해, 배정, 코드·문서 작업.
- Git worktree 또는 복사본 격리, 허용된 로컬 명령 실행, diff·로그·Evidence Ledger.
- 실패 분류, 계약별 재시도 한도 안의 재작업, escalation, 최종 승인.
- SQLite 이력 복구, 모델·token·비용·오류 기록, 완료 후 교훈 저장.
- React 기반 2D 오피스 맵. 직원 위치·애니메이션은 실행 이벤트에서만 갱신.

### 비범위

- 다중 사용자, SaaS, 결제, Git push, 자동 배포, 실제 광고/게시, 외부 전송, 운영 DB migration.
- 외부 스킬 자동 다운로드, 자동 권한 상승, 정책·권한·스킬의 자동 변경, 무제한 자기개선.
- 전 직원 강제 참여, 3D 메타버스, 전체 SLO/온콜/SEV 운영 체계, 스킬·템플릿 마켓.

외부 행동은 산출물 초안과 검토까지만 허용한다. 실행은 차단 사유와 가능한 안전 대안을 남긴다.

## 3. 현재 패키지와 migration

현재 원천은 `registry/employees.json`의 24명, `employee-skill-bindings.json`, `skill-definitions.json`, `skills.lock.json`, 직원별 `PERMISSIONS.yaml`, `EMPLOYEE.md`, `ROLE.md`, `SOP.md`, `EVALUATION.md`다. `skills.lock.json`의 `installed`는 현재 비어 있으므로, 필수 스킬이 필요한 직원은 검증 전 실행할 수 없다.

기존 `scripts/audit_package.py`, `install_skills.py`, `verify_skills.py`, `render_skill_indexes.py`는 유지한다. 단, V1 실행기는 설치 스크립트를 자동 호출하지 않는다. UI는 설치 상태를 조회하고, 사용자가 로컬에서 설치 또는 inbox 등록 후 다시 검증하게 한다.

현재 정적 오피스 프로토타입은 시각 동작 검증용이다. V1에서 `apps/web` React + Vite + TypeScript로 교체하고, 프로토타입의 직원 ID·팀 배치·상태 이동 개념만 이전한다. FaceFit은 React/Vite/TypeScript 기준, build/lint/test 명령, 3개 benchmark task를 가진 예시 프로젝트 프로필로 유지하며 오피스 제품 자체에 결합하지 않는다.

## 4. 전체 아키텍처와 디렉터리

```text
apps/
  web/                    React + Vite + TypeScript UI
  api/                    FastAPI, orchestration, SQLite API
packages/
  contracts/              Pydantic/TypeScript 공유 schema·상태 enum
  registry-adapter/       기존 registry·직원 파일 읽기/검증
  policy-engine/          경로·명령·권한·network 정책
  orchestrator/           회의·DAG·배정·retry·escalation
  harness/                act/observe/verify/diagnose/repair 루프
  evidence/               artifact hash·test result·stale 처리
  office-projection/      이벤트→2D 오피스 위치/애니메이션 projection
data/
  ai-office.sqlite3       런타임 DB, Git ignore
  artifacts/              실행 artifact, Git ignore
  workspaces/             worktree/복사 격리본, Git ignore
.ai-office/
  user-skills/inbox/      사용자 직접 추가 스킬 대기 영역
  settings.json           로컬 모델/예산 설정, 비밀값 제외
```

`apps/api`만 파일·명령·모델 호출 권한을 가진다. `apps/web`은 API 이벤트를 구독해 화면을 갱신하며 OS·프로젝트 파일에 직접 접근하지 않는다.

## 5. 조직과 직원 모델

직원 이름은 변경하지 않는다. CEO/ORBIT와 PM/QA는 새 직원 ID가 아니라 시스템 역할 projection이다.

- Executive: NAVI가 CEO 대리·최종 오케스트레이터다. 목표 해석, 위험 escalation, 최종 승인/재작업 지시를 맡는다.
- Coordination: NAVI, ROUTE, CLOCK. 계약·DAG·의존성·예산·실행 관제.
- Product: FRAME이 PM/제품 책임자. FLOW UX·서비스, MOSS UI·콘텐츠 설계.
- Team leads: BUILD(application), LINK(ai-data), SHIP(platform-reliability), GUARD(quality-security), GROW(growth-marketing), LENS(service-knowledge), FRAME(product-experience).
- Workers: FRONT, BACK, SIGNAL, SRE, COST, SHIELD, TRACE, EVAL, VOICE, PULSE, JOURNEY, DOCS와 각 팀의 위 역할 직원.
- Assurance: BUILD는 build/test·통합 검토, GUARD는 보안·권한, TRACE는 테스트·추적, EVAL은 결과 품질·AI 평가. 별도 `QA` 직원은 만들지 않으며 QA acceptance 검증은 TRACE를 책임자로 하고 관련 BUILD/GUARD/EVAL을 선택한다.

라우터는 업무 유형, 파일 영역, 위험도, 레지스트리 역할, 설치된 필수 스킬, 계약 예산을 사용해 최소 인원만 고른다. 단순 문서 수정은 `NAVI → DOCS → EVAL`, 복합 기능은 `NAVI → FRAME → BUILD/LINK 팀장 회의 → FRONT/BACK/SIGNAL → BUILD/TRACE/GUARD/EVAL`처럼 확장한다.

## 6. 권한과 스킬 시스템

직원 실행 전 다음을 모두 검사한다.

1. `employee-skill-bindings.json`의 required skill 경로에 `SKILL.md` 존재.
2. `skills.lock.json` 항목 존재와 tree SHA-256 일치.
3. 직원 runtime/역할과 선택한 skill의 호환성.
4. `PERMISSIONS.yaml`의 권한이 계약 행동과 일치.
5. skill 내부 지침이 정책상 금지 도구·network·경로를 요구하지 않음.

실패하면 실행하지 않고 `blocked` 이벤트와 누락 skill/lock/권한 정보를 남긴다. `instruction_only`, `network: deny_by_default`, `scripts: deny_until_task_approved`, `write_scope: task_contract_only`를 기본으로 강제한다.

기존 글로벌 `registry/skills.lock.json`을 권위 원천으로 유지한다. UI inbox 등록은 `.ai-office/user-skills/inbox/<skill-id>/`에 사용자가 넣은 스킬을 manifest 검사·hash 계산·shadow task 3회로 검증한 뒤 별도 `skill_registry`와 `skill_verifications`에 기록한다. 기존 레지스트리나 직원 폴더는 자동 수정하지 않는다. 활성화는 사용자 승인 후에만 binding 변경 제안으로 생성한다.

## 7. TaskContract

```yaml
id: TASK-...
project_id: PROJECT-...
request: string
goal: string
scope:
  allowed_paths: [relative path]
  allowed_commands: [exact command or approved template]
  prohibited_actions: [network, git_push, deploy, delete, privilege_escalation, external_transfer]
acceptance_criteria: [string]
task_type: documentation | bug_fix | feature | research | design | analysis | mixed
selected_departments: [team id]
assigned_employees: [employee id]
dependencies: [work item id]
budget:
  token_limit: integer
  cost_limit_usd: decimal
  model_call_limit: integer
  retry_limit: integer
  deadline_or_sequence: string
risk_level: low | medium | high
workspace_strategy: worktree | copy
status: TaskState
approval_policy: auto_within_contract | user_required
```

계약은 NAVI가 생성하고 FRAME이 제품 범위·acceptance를 보강한다. high risk, 프로젝트 밖 접근, 금지 행동 요청, 예산 초과는 NAVI가 자동 승인하지 않고 `awaiting_approval` 또는 `blocked`로 전환한다.

## 8. 회의와 계획 모델

회의는 짧은 구조화된 결정 기록이다. 자유 대화 원문을 다음 단계에 전달하지 않는다.

```yaml
id: MEET-...
task_id: TASK-...
type: intake | team_lead | department | design_review | architecture_review | qa_review | incident_review | final_approval
objective: string
participants: [employee id]
agenda: [string]
context_refs: [artifact/evidence/decision id]
proposals: [{owner, summary, evidence_refs}]
objections: [{owner, issue, severity, resolution}]
decisions: [{decision, owner, rationale, evidence_refs}]
action_items: [{id, owner, description, sequence, acceptance_criteria}]
unresolved_issues: [string]
evidence_refs: [id]
status: planned | active | concluded | blocked
```

NAVI는 Intake Meeting을, FRAME은 업무 분해와 제품 결정 회의를, 팀장은 팀 내부 검토를 생성한다. `action_items`만 후속 work item과 의존성으로 변환된다. 결정 없는 회의는 종료하지 못한다.

## 9. 상태 머신과 오케스트레이션

정상 상태:

```text
draft → contracting → planning → meeting → assigned → running
→ team_review → cross_review → verifying → reflecting
→ awaiting_approval → completed
```

예외 상태: `blocked`, `failed`, `cancelled`, `budget_exceeded`, `escalated`.

유효 전이와 핵심 guard:

- `draft → contracting`: 프로젝트와 요청 존재.
- `contracting → planning`: 정책 검사·budget·허용 경로/명령 확정.
- `planning → meeting|assigned`: 선택 직원의 권한·skill lock 검증 성공.
- `meeting → assigned`: 각 action item에 owner·acceptance·sequence 존재.
- `assigned → running`: 격리 workspace 준비와 명령 allowlist 성공.
- `running → team_review`: worker artifact와 실행 결과 존재.
- `team_review → cross_review|verifying`: 팀장 review 승인 또는 필요한 교차 부서 선택.
- `verifying → reflecting`: required test/evidence 완료.
- `reflecting → awaiting_approval`: retry 필요 없음 또는 retry 한도 소진 후 escalation 결정.
- `awaiting_approval → completed`: NAVI 승인과 fresh evidence coverage 100%.

모든 전이는 append-only `events`에 actor, 전/후 상태, 이유, 연결 artifact/evidence를 기록한다. 오피스 UI는 이 이벤트 스트림만 읽는다: meeting은 회의실, running은 팀 좌석, team/cross review는 review desk, verifying은 QA zone, awaiting_approval은 대표실 앞, blocked는 정책 대기 구역으로 이동시킨다.

## 10. Harness와 재시도

각 work item은 다음 loop를 수행한다.

```text
Plan → Act → Observe → Verify → Diagnose → Repair → Re-verify → Accept/Escalate
```

`Act`는 계약 범위 안의 파일 변경·허용 명령만 실행한다. `Observe`는 exit code, stdout/stderr hash, diff, artifact, 모델 사용량을 저장한다. `Verify`는 계약의 acceptance와 직원 `EVALUATION.md` 필수 evidence를 대조한다.

실패는 `contract_interpretation`, `permission`, `skill`, `file_conflict`, `build`, `test`, `runtime`, `external_dependency`, `quality`, `budget`, `model_response`로 분류한다. 진단은 같은 접근을 반복하지 않으며, `(failure_class, strategy_hash)` 중복 시 새 strategy, 다른 적격 직원, 팀장 review, NAVI escalation 순서로 전환한다. retry는 `TaskContract.budget.retry_limit`을 절대 넘지 않는다.

## 11. SQLite 스키마

기존 실행 이력 계열: `projects`, `tasks`, `task_contracts`, `work_items`, `runs`, `agent_assignments`, `events`, `artifacts`, `evidence`, `model_usage`, `settings`.

조직 계열: `departments`, `meetings`, `meeting_participants`, `decisions`, `action_items`, `reviews`, `approval_requests`, `reflections`, `lessons`.

통제 계열: `skill_registry`, `skill_verifications`, `permission_checks`, `retry_attempts`, `incidents`, `context_snapshots`.

핵심 관계:

- `tasks` 1:1 `task_contracts`, 1:N `work_items`, `meetings`, `events`, `evidence`, `model_usage`, `reflections`.
- `work_items` N:1 `tasks`, N:1 owner employee, N:N dependency work item, 1:N `runs`, `reviews`, `retry_attempts`.
- `meetings` 1:N participants/decisions/action_items; action item은 선택적으로 work item에 연결.
- `evidence`는 run/artifact/test command/diff hash를 참조한다. 변경 후 연결된 evidence는 `stale_at`을 기록해 완료 근거에서 제외한다.
- `lessons`는 task type, roster, strategy, failure class, effective test, cost, reuse hint만 저장하며 권한·정책·skill source를 변경하지 않는다.

## 12. FastAPI 명세

### 프로젝트·레지스트리

- `POST /projects` — root path 등록, root 정책 검사, Git 여부 확인.
- `GET /projects`, `GET /projects/{id}` — 프로젝트와 현재 task 요약.
- `GET /registry/employees`, `GET /registry/employees/{id}` — 기존 역할/권한/skill 상태.
- `POST /skills/verify` — 기존 lock 및 user inbox 검증 결과만 생성.

### 업무·회의·실행

- `POST /tasks` — 요청으로 draft 생성.
- `POST /tasks/{id}/contract` — NAVI 계약 생성/갱신.
- `POST /tasks/{id}/plan` — 부서 선택, FRAME 분해, work item DAG 생성.
- `POST /tasks/{id}/meetings` — 구조화 회의 생성/종료.
- `POST /tasks/{id}/assignments` — 승인된 action item 배정.
- `POST /tasks/{id}/run` — harness 시작. Server-Sent Events로 progress 전송.
- `POST /tasks/{id}/retry`, `POST /tasks/{id}/approve`, `POST /tasks/{id}/cancel`.
- `GET /tasks/{id}`, `GET /tasks/{id}/events`, `GET /tasks/{id}/evidence`, `GET /tasks/{id}/office-projection`.

### 관측·학습

- `GET /runs/{id}`, `GET /tasks/{id}/usage`, `GET /tasks/{id}/lessons`.
- `POST /settings/model-routing` — 모델 alias·예산 정책 저장. API key는 OS 환경변수만 사용하며 DB에 저장하지 않는다.

모든 write API는 예상 상태와 idempotency key를 받아 중복 실행을 막는다. API는 localhost bind만 허용한다.

## 13. UI 화면

- 업무 화면: 프로젝트 선택, 요청, TaskContract, 부서/직원 선택 근거, DAG, diff, 테스트, Evidence Ledger, token/비용, 차단·승인·재개·취소.
- 조직 화면: 8개 팀, 24명, 역할, runtime, 권한, skill lock 상태, 최근 task, 현재 work item.
- 회의 화면: 회의 유형, 참석자, 안건, 제안, 이견, 결정, action item, unresolved issue, evidence.
- 실행 상세: run 단계, 로그, retry 진단, strategy 변경, approval request.
- 오피스 화면: 2D floor map, 팀 좌석, 회의실, review/QA zone, 대표실, 이벤트 기반 avatar 이동, 현재 task overlay. UI에서 위치를 직접 상태로 변경할 수 없다.
- 이력 화면: 완료/실패/차단 task, 비용, evidence, reflection, lessons 검색.

## 14. 보안과 실행 정책

- 선택 프로젝트의 canonical root 밖 읽기/쓰기 금지. 심볼릭 링크 해석 뒤에도 root를 재검사.
- 기본 network deny. 허용이 필요한 외부 의존성은 task contract의 명시된 도메인·이유·사용자 승인이 필요하며 V1 기본 구현은 deny 유지.
- `git push`, deploy, package publish, 외부 HTTP 전송, 결제, 운영 DB migration, 삭제 명령, 권한 상승 차단.
- 명령은 shell 문자열을 직접 실행하지 않고 allowlisted command template + 인자 schema로 실행.
- Git 프로젝트는 branch/worktree, 비-Git은 copy workspace 사용. 원본 프로젝트에는 verifier 승인 전 변경을 반영하지 않는다.
- 모든 모델 입력은 최소 컨텍스트 snapshot만 사용한다. 비밀값·환경변수·프로젝트 밖 파일은 모델 input과 log에서 제외한다.
- Evidence, log, diff, model output은 로컬에만 저장한다. 민감 문자열 redaction 후 hash와 pointer를 기록한다.

## 15. 모델 라우팅·token 정책

모델 provider는 adapter interface로 고정하고, 실제 provider/model alias는 로컬 settings에서 설정한다.

- light: 파일 검색·분류·요약·형식 변환·직원 후보·로그 정리.
- standard: 코드/문서 수정, 일반 기획, 테스트 오류 진단, UI 제안.
- advanced: 부서 충돌, 복합 architecture, 반복 실패 분석, 최종 품질 review, high risk proposal.

`03-FACEFIT_PROFILE_v6.2.yaml`의 `low/standard/complex` profile 예산을 기본값으로 사용한다. 각 task는 active profile 수, model call 수, deep call 수, dynamic context, output, USD 비용 상한을 contract에 snapshot한다. 고정 constitution/runtime/tool schema/approved core hash는 cacheable prefix로 분리한다. 회의는 decision summary, worker는 관련 파일·diff·evidence만 받는다. 규칙/스크립트 검증을 모델 호출보다 먼저 수행한다.

## 16. 테스트와 E2E acceptance

### 자동 테스트

- registry adapter: 24명, profile path, binding, permission parse, empty lock 상태 검출.
- policy engine: root escape, symlink escape, 금지 명령, network, Git push, delete, privilege escalation 차단.
- state machine: 모든 정상/예외 전이 guard, stale evidence, approval gate, idempotency.
- meeting: action item owner/acceptance 누락 시 종료 거부, 결정→work item 변환.
- harness: failure 분류, retry limit, 동일 strategy 반복 차단, escalation.
- evidence: test exit code/diff/artifact hash 연결, 변경 후 stale 처리, fresh coverage 없으면 completed 거부.
- API: SQLite 재시작 복구, SSE event order, API key 비저장.
- UI: event→avatar room/status mapping, UI 단독 상태 변경 불가, 1440/768/390 viewport.

### E2E 시나리오

1. 문서: `NAVI 계약 → DOCS 수정 → EVAL 검토 → diff/evidence → NAVI 완료`. 선택 경로 밖 변경은 없어야 한다.
2. 버그: `NAVI → BUILD 팀장 선택 → FRONT 또는 BACK 수정 → BUILD test 실패 진단 → 제한 재작업 → TRACE/GUARD → 완료`. 재작업 전후 evidence가 구분돼야 한다.
3. 복합 기능: `FRAME 분해 → BUILD/LINK 팀장 회의 → FRONT/BACK/SIGNAL 병렬 → cross review → BUILD/TRACE/GUARD/EVAL → 승인`. 모든 action item owner와 dependency가 있어야 한다.
4. 차단: Git push 또는 root 밖 경로 요청은 실행 전 `blocked`; 사유, 필요한 권한, 안전 대안, 취소/재개 UI를 보여야 한다.
5. 오피스: 각 E2E의 event stream과 avatar status/location이 일치해야 하며, 화면 클릭만으로 task 상태가 바뀌면 실패다.

## 17. 단계별 구현 순서

1. foundation: React/Vite/TypeScript, FastAPI, SQLite migration, registry adapter, localhost config, 기존 audit script 의존성(`PyYAML`) 정리.
2. control plane: TaskContract, 상태 머신, policy engine, workspace isolation, event/evidence/model usage 저장.
3. organization: employee/skill verification, department selection, FRAME work breakdown, structured meeting/action item/DAG.
4. execution: model adapter, command template runner, harness/retry/diagnosis/escalation, review/approval gate.
5. experience: 업무·조직·회의·실행·이력 UI, SSE, 2D office projection.
6. acceptance: 4개 E2E, security negative tests, FaceFit benchmark A/B/C, restart recovery, token/cost regression 비교.

각 단계는 이전 단계의 evidence와 테스트가 통과해야 다음 단계로 진행한다. 완료 선언은 fresh evidence, required assurance review, contract acceptance coverage가 모두 존재할 때만 가능하다.
