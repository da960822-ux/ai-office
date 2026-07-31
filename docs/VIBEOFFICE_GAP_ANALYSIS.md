# VibeOffice 갭 분석 — 현재 구현 vs 목표 명세

- 작성일: 2026-07-30 (갱신: 2026-07-31, S1~S4 구현 반영 / GenTeam 대비 갭 5~6절 추가)
- 목표 명세: `reference/product-context/` (vibe_coding_office_context_pack_v3)
- 현재 코드: AI Office / Corporate OS v6.2 (`apps/api`, `apps/web`, `registry`)
- 검증 기준일 테스트: API 161개 중 158 pass, 3 error (원인: 로컬에 `ripgrep` 미설치)

## 0. 결론 요약

현재 저장소는 **범용 AI 회사 실행 런타임** 위에 **제품 파이프라인 계층(VibeOffice)**을 슬라이스 단위로 쌓는 중이다.

- 실행 계층(Job, 격리, 도구, 증거, 리뷰, 복구)은 명세 요구 수준을 이미 넘는다.
- 제품 계층은 [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md) 7절의 수직 슬라이스 S1~S4(Intake→Blueprint, 디자인 패키지+handoff, 기술설계 계약, Product Execution Baseline, 내부 MVP 빌드)가 구현·검증 완료됐다. 남은 것은 S5(QA 반송 루프 → H4 Export)와 S6(대화형 지시 계층·오피스 UI)다.
- 재작성이 아니라 **기존 실행 런타임 위에 제품 파이프라인 계층을 추가**하는 방향은 그대로 유효하다. `apps/api/vibeoffice/*` 전 모듈이 `main.tasks`/`TaskContract`/Job 큐를 건드리지 않고 `vo_*` 테이블 + 워크스페이스 파일만으로 자기완결적으로 동작한다 - S4(내부 빌드)조차 명령 실행은 `apps/api/policy.py`의 `validate_command`만 재사용하고 Job 시스템에는 올라타지 않았다. 2절 다이어그램이 그리는 "제품 계층 → 실행 계층" 연결은 아직 미착수 목표로 남아 있다.

## 1. 두 제품 모델 차이

| 축 | 현재 구현 | 목표 명세 |
|---|---|---|
| 단위 | `Task` (요청 1건) | `Project` (제품 1개) + phase 진행 |
| 부서 | 8개 회사 부서 (`registry/department-boundaries.json`) | 6개 제품 부서 Planning·Design·Architecture·Build·QA·Shipping |
| 라우팅 | GLM이 매 요청마다 동적 결정 (`apps/api/main.py:1052`) | 고정 파이프라인 + 승인 게이트 3개 |
| 산출물 | `FINAL.md` 1개 + 부서 초안 (`AI_OFFICE_OUTPUTS/<TASK-ID>/`) | 타입별 산출물 세트 + 버전 + 의존성 + stale |
| 인계 | 문자열 `handoff_to` 필드 (`apps/api/main.py:795`) | `handoff.json` 계약 (inputVersions·requiredOutputs·acceptanceCriteria·status) |
| 사용자 | 요청을 서술할 수 있는 운영자 | 프롬프트를 못 쓰는 초보자 (질문 최대 3개) |
| 종료 조건 | 리뷰 통과 + 증거 | H4 Agent-ready 폴더 + 준비도 점수 |

## 2. 이미 구현됨 (재사용 대상)

| 명세 요구 | 현재 구현 | 근거 |
|---|---|---|
| 승인 경계 / 파괴적 작업 차단 | TaskContract `allowed_paths`·`allowed_commands`, `permission_rules` ask→HTTP 428 | `apps/api/main.py:133`, `apps/api/main.py:296` |
| 안전 자동화 vs 사용자 승인 분리 | `/api/tasks/{id}/approval`, permission 결정 API | `apps/api/main.py:2123`, `apps/api/main.py:1814` |
| 부서 경계와 반송 원칙 | 8부서 `owns`/`must_handoff`를 실행·회의 프롬프트에 주입 | `registry/department-boundaries.json`, `apps/api/worker.py:435` |
| 단계 의존성 게이트 | `task_phases` + `depends_on`, 상위 산출물 없으면 하위 Job 미큐 | `apps/api/main.py:795`, `apps/api/main.py:1170` |
| 산출물 파일 강제(채팅 답변 불인정) | 부서 초안 파일 + `FINAL.md` + hash, 필수 섹션 규격 16종 | `apps/api/main.py:642`, `registry/deliverable-standards.json` |
| 독립 리뷰 후 재작업 | GUARD/LENS 독립 리뷰, `changes_requested` → 자동 재통합 | `apps/api/main.py:2095`, `docs/RUNTIME_HARDENING.md` |
| 체크포인트·롤백 | `checkpoint()`, `/checkpoints/{id}/restore`, 이후 evidence stale | `apps/api/main.py:242`, `apps/api/main.py:1594` |
| 증거 기반 완료 | `evidence` 테이블(`artifact_sha256`, `stale`), 완료 불변식 | `apps/api/main.py:854`, `apps/api/main.py:1212` |
| 실패 정상화·부분 재시도 | Job lease·heartbeat·pause·resume·retry playbook | `apps/api/main.py:1728`, `apps/api/main.py:1750` |
| 병렬 실행과 코드 격리 | 직원별 branch/worktree, 리뷰 통과 후 직렬 cherry-pick | `apps/api/agent_worktree.py`, `docs/RUNTIME_HARDENING.md` |
| 조사 근거 품질 | 검색 스니펫 비증거, 원문 2건 교차검증 | `apps/api/research.py`, `docs/RUNTIME_HARDENING.md` |
| 오피스 시각화(실이벤트 기반) | zone/아바타 + SSE `job_events` | `apps/web/src/App.tsx:158`, `apps/api/main.py:1379` |
| 문서 렌더 QA | DOCX/PDF/XLSX/PPTX/HWPX 생성 후 재파싱 | `apps/api/artifact_renderer.py` |
| **Intake / 최소 질문 (S1)** | 시작 카드, 30자 입력→Blueprint, 질문 ≤3, `추천값`·`모름`·`나중에 결정` | `apps/api/vibeoffice/intake.py`, `blueprint.py`, `test_vibeoffice_intake.py` |
| **project-blueprint.json (S1)** | Must 3~5·Later/Out·위험, Gate B, 스키마 검증 | `apps/api/vibeoffice/blueprint.py` (`assert_scope_gate`), `models.py` |
| **부서 handoff 계약 (S2)** | `inputVersions`·`requiredOutputs`·`acceptanceCriteria`·`openDecisions`·8단계 `status`, 05A 3장 거부 조건 5종 전부, 10장 supersede | `apps/api/vibeoffice/handoff.py` |
| **디자인부 패키지 생성 (S2)** | IA/USER_FLOWS/SCREEN_SPEC/DESIGN_SYSTEM/COMPONENT_INVENTORY, 화면 3~7개, Gate C(loading/empty/error·dead-end·CTA) | `apps/api/vibeoffice/design.py` |
| **stale 전파 (S2)** | 변경 종류(대상 사용자/Must/시각/기술스택/경험)별로 다른 영향 산출물 집합, `dependsOn`·`stale_reason` 기록 | `apps/api/vibeoffice/artifacts.py` (`classify_blueprint_change`, `STALE_IMPACT`) |
| **산출물 버전 (S2)** | `vo_artifacts`/`vo_artifact_versions`(type·status·currentVersionId·dependsOn·sha256) | `apps/api/vibeoffice/artifacts.py` |
| **제품 상태 머신 (S1~S4)** | `DRAFT`…`BUILD_VERIFICATION` + 예외 상태, 슬라이스별 전이 테이블을 병합 | `apps/api/vibeoffice/schema.py` (`ProjectState`, `S1~S4_TRANSITIONS`) |
| **기술설계부 패키지 생성 (S3)** | API_CONTRACT.yaml/DATA_MODEL/TECHNICAL_TASKS, 화면↔데이터 source 매핑, Gate D(필드 일치·인증 일치·실패 처리·secret)+Gate E(세션 크기·의존성·Out 금지) | `apps/api/vibeoffice/architecture.py` |
| **Product Execution Baseline (S3.5)** | PRD.md(Problem/OKR/Scope/Requirements/NFR/Decision/Risk 통합), decision-register/risk-register/traceability-map.json, Gate PE | `apps/api/vibeoffice/execution_baseline.py` |
| **내부 MVP 빌드 (S4)** | 정적 스캐폴드 + 실제 `node` build/test 명령 실행, PROJECT_STATUS/BUILD_REPORT/current-state.json, Gate F | `apps/api/vibeoffice/build.py` |

## 3. 부분 구현 (개념은 있으나 명세 형태가 아님)

| 명세 요구 | 현재 상태 | 남은 일 |
|---|---|---|
| 리뷰 findings | 리뷰 결과가 텍스트 + `changes_requested` (VibeOffice 쪽엔 아직 findings 스키마 없음) | `severity`/`category`/`ownerDepartment`/`autoFixable` 스키마, 소유 부서 반송, 동일 finding 2회 시 중단 (S5) |
| 기획부 패키지 — 다중 문서 모드 | `PRD.md` 단일 문서(기본 모드, S3.5)만 생성 | `PRODUCT_BRIEF`/`MVP_SCOPE`/`REQUIREMENTS`/`ROADMAP`/`DECISIONS` 별도 문서는 06_OUTPUT_STANDARD.md가 "외부 고객·대형 팀·규제 요구가 있을 때만"이라 명시한 고품질 모드 전용 — 기본 모드가 끝난 지금도 우선순위 낮음 |
| 추적성 | REQ→Task/Test 1:1, `traceability-map.json`(S3.5)까지 있음 | `GOAL`/`FEATURE`/`FLOW`/`SCREEN` 레벨까지 전 구간 연결, `artifact-index.json`, drift 계산은 아직 없음 |
| 오피스 UI | 회사 오피스 맵 + 업무 콘솔 | Start·Planning Room·Design Studio·Architecture Lab·Build Floor·Review Room·Shipping Dock 화면 |
| 초보자 오류 표시 | 토스트 경고 | 쉬운 설명 → 영향 → 재시도 → 기술 세부 4단 형식 |
| 대화형 지시 | 실행 중 steering 큐 + SSE 이벤트만 존재 | 대화 스레드·의도 분류·자율 팀 구성·상태 질의·자연어 승인 → [CONVERSATIONAL_AGENT_TARGET.md](CONVERSATIONAL_AGENT_TARGET.md) |

## 4. 미구현 (코드 0)

S1~S4가 끝나며 아래 목록에서 Intake/Blueprint/디자인부/기술설계부/내부 빌드 항목은 2절 표로 옮겼다(모두 구현 완료). 남은 항목:

1. **QA 반송 루프 (S5)** — review-findings.json, 소유 부서 라우팅, 최소 수정, Gate 재검사, 반복 제한
2. **준비도 H0~H5 (S5)** — 7조건 점수화, `handoff-readiness.json`, 내보내기 lint(필수 파일·빈 섹션·secret·절대경로·깨진 import)
3. **Export 패키징 (S5)** — AGENTS.md / CLAUDE.md / NEXT_ACTION.md 생성 + ZIP·Git 패키지 + `export-manifest.json`
4. **직접 시각 편집 (S6 이후)** — 모델 호출 없는 텍스트·색·간격·순서 편집
5. **Golden Path E2E** — 명세 08장 예시 입력 1건이 S1→S5를 통과해 H4 폴더까지 자동 완주. S4까지는 각 슬라이스가 독립 fixture로 검증됐을 뿐, 전 구간을 잇는 E2E는 아직 없다.

## 5. GenTeam 대비 갭 — 직원 프로필 · 작업판 · 승인 경계 · 비용/모델 라우팅

사용자가 GenTeam(범용 협업 공간)에서 가치가 크다고 지목한 기능을 이 저장소(목적형 제품 완성 AI 회사)에 반영할 때의 현황이다. 재작성이 아니라 기존 테이블·엔드포인트 확장으로 처리한다.

| GenTeam 요구 | 현재 구현 | 근거 | 남은 일 |
|---|---|---|---|
| 직원 프로필: 역할 | `registry/employees.yaml`(`title`, `team`, `runtime`) | `registry/employees.yaml` | 없음. 이미 충족 |
| 직원 프로필: 기본 모델 | `registry/model-routing.json`의 `employee_roles`→`role_models` | `registry/model-routing.json` | UI에 직원별 현재 모델을 노출하는 표시만 없음(API `GET /api/settings/models`는 있음) |
| 직원 프로필: 보유 스킬 | `required_skills`/`optional_skills`(`registry/employees.yaml`) + `registry/employee-skill-bindings.json` | `registry/employees.yaml` | 없음. 이미 충족 |
| 직원 프로필: 사용 가능한 도구 | 도구는 역할별이 아니라 전역 `WorkspaceAgentTools`(`apps/api/agent_tools.py`)이고, 실제 허용 여부는 직원이 아니라 TaskContract가 결정 | `apps/api/agent_tools.py` | 직원 카드에 "이 역할이 쓸 수 있는 도구 목록"을 정적으로 보여주는 표시가 없음. 도구 자체를 직원별로 나눌 필요는 없음(TaskContract 경계가 이미 실행 시점 권한을 결정) |
| 직원 프로필: 실행 권한 | `employees/<dept>/<ID>/PERMISSIONS.yaml`(`P0_READ`…`P5_STAGING_WITH_APPROVAL`, `network`, `scripts`, `write_scope`) | `employees/application/BACK/PERMISSIONS.yaml` | 있음. UI 카드에 노출만 없음 |
| 작업 상태: 할 일→진행 중→검토 중→완료·반송 | `TASK_STATES`가 이미 이 흐름을 세분화해서 포함(`planning`/`meeting`→진행 전, `running`/`executing`→진행 중, `team_review`/`cross_review`/`verifying`→검토 중, `completed`/`blocked`→완료·반송) | `apps/api/main.py:82` | 4단계 라벨로 그루핑해 보여주는 UI 보드(칸반)가 없음. `STATE_LABELS`는 있지만 4버킷 매핑이 없음 |
| 한 작업에 기본 담당자 한 명 | 없음. `leads`는 1~4명 배열, `final_owner`는 산출물 통합 책임자 필드로 별개 목적 | `apps/api/main.py:1000` | "기본 담당자(assignee)" 단일 필드가 없음. `final_owner`를 기본 담당자로 재해석하거나 신규 필드 추가 필요 |
| 검토자는 필요한 작업에만 별도 지정 | 이미 이렇게 동작. GUARD/LENS 독립 리뷰는 완료 조건에서만 강제되고, 리뷰가 필요 없는 소규모 직접 지시(`direct-dispatch`)에는 리뷰 단계가 없음 | `apps/api/task_routes.py` (`direct_dispatch`) | 없음. 이미 충족 |
| 호출형 에이전트(항상 대화에 끼어들지 않음) | 대화 계층 자체가 없음. 현재는 Job이 큐에 있을 때만 직원이 실행되므로 "말 걸지 않으면 응답 안 함"과 결과적으로 비슷하지만, 목표인 대화형 지시 계층은 미구현 | `docs/CONVERSATIONAL_AGENT_TARGET.md` | 4절 참고. 대화 저장소·의도 분류가 없으면 "호출 시에만 개입"을 명시적으로 보장할 수 없음 |
| 승인 경계: 파일 삭제·외부 발송·배포·API 키/권한 변경·운영 데이터 수정 | `policy.py`의 `BLOCKED_TOKENS`가 `git push`/`deploy`/`publish`/외부 URL 전송/`rm -rf`/`sudo` 등을 하드 차단, `permission_rules`(allow/ask/deny)가 나머지를 계약 단위로 게이트, API key는 OS keyring에만 저장 | `apps/api/policy.py`, `apps/api/main.py:188` | "API 키·권한 변경"과 "운영 데이터 수정"은 범주명으로 문서화된 승인 경계 목록이 없음(개별 케이스는 `deny`/`ask` 규칙으로만 걸림). 승인 경계를 사용자에게 보여주는 고정 카탈로그가 없음 |
| 비용·모델 라우팅: 예상 비용 | 없음 | — | `model_usage.cost_usd`는 항상 0으로 기록됨(추정 로직 없음). OpenRouter는 모델별 단가를 제공하므로 입력 프롬프트 길이 기반 사전 추정은 추가 가능 |
| 비용·모델 라우팅: 실제 비용 | 토큰 수는 기록되지만 USD 환산이 없음 | `apps/api/worker.py:384`, `apps/api/main.py:1453` | 모델별 단가 테이블 + `cost_usd` 계산 로직 필요 |
| 비용·모델 라우팅: 로컬 실행인지 API 실행인지 | 모든 모델 호출이 OpenRouter API 경유. 로컬 모델 실행 경로 없음 | `apps/api/main.py:317`(`model_client`) | 로컬 Claude Code/Codex CLI 연결은 8절 참고 |
| 비용·모델 라우팅: 실패 시 상위 모델 승격 | 이미 구현. 같은 작업에서 재시도 2회 실패 또는 `escalated` 상태면 `debug_escalation` 모델로 전환 | `apps/api/main.py:303`(`task_model_assignment`) | 없음. 이미 충족. UI에 "왜 모델이 바뀌었는지" 표시만 없음 |

## 6. 로컬 Claude Code·Codex 연결 — 현황

- 코드 저장소 안에 Claude Code/Codex CLI를 **에이전트 실행기**로 붙이는 경로는 없다. 현재 모든 직원 실행은 OpenRouter API 모델 호출(`apps/api/main.py:317`)로만 이뤄진다.
- `employees/*/skills/doubt-driven-development/SKILL.md`에 Codex/Gemini CLI를 **2차 검토용으로 사람이 수동 실행**하는 절차만 있다(에이전트가 자동으로 호출하지 않음).
- 로컬 CLI를 정식 실행기로 편입하려면 `model_client()`가 반환하는 OpenAI 호환 클라이언트 대신, 직원별로 "OpenRouter API" 또는 "로컬 CLI 프로세스"를 선택하는 어댑터 계층이 필요하다. 이는 `registry/model-routing.json`에 provider 필드를 추가하고, `apps/api/worker.py`의 모델 호출 지점에 분기를 추가하는 규모의 작업이다.

## 7. 현재 리스크

- **문서-코드 불일치**: `AI_AUTOMATION_OFFICE_V1_PLAN.md`가 제시한 `packages/contracts`, `policy-engine`, `orchestrator` 등 패키지 구조는 존재하지 않는다. 실제 구현은 `apps/api/main.py`(171KB) + `worker.py`(66KB) 단일 모듈이다. → `reference/legacy/`로 이동, 신규 작업은 이 갭 문서를 기준으로 한다.
- **거대 모듈**: 제품 계층을 `main.py`에 추가하면 유지 불가. 신규 코드는 별도 모듈로 분리해야 한다.
- **환경 의존성 미문서화**: `ripgrep` 미설치 시 `search_files`/`find_symbols` 계열 테스트 3건이 실패한다. README 요구사항에 없다.
- **동적 라우팅과 고정 파이프라인 충돌**: 제품 파이프라인은 부서 순서가 고정이므로 GLM 동적 라우팅을 그대로 쓰면 게이트가 무의미해진다. 이 흐름 전용 고정 프로필이 필요하다.
