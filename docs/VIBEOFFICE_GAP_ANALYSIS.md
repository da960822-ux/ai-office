# VibeOffice 갭 분석 — 현재 구현 vs 목표 명세

- 작성일: 2026-07-30
- 목표 명세: `reference/product-context/` (vibe_coding_office_context_pack_v3)
- 현재 코드: AI Office / Corporate OS v6.2 (`apps/api`, `apps/web`, `registry`)
- 검증 기준일 테스트: API 31개 중 28 pass, 3 error (원인: 로컬에 `ripgrep` 미설치)

## 0. 결론 요약

현재 저장소는 **범용 AI 회사 실행 런타임**이다. 명세가 요구하는 것은 **비전공자용 제품 파이프라인(아이디어 → MVP → 인계 폴더)**이다.

- 실행 계층(Job, 격리, 도구, 증거, 리뷰, 복구)은 명세 요구 수준을 이미 넘는다.
- 제품 계층(Blueprint, 산출물 버전, 부서 handoff 계약, 화면 명세, 준비도 H0~H5, Export)은 **거의 전부 미구현**이다.
- 따라서 재작성이 아니라 **기존 실행 런타임 위에 제품 파이프라인 계층을 추가**하는 것이 옳다. 구현 방법은 [VIBEOFFICE_IMPLEMENTATION_GUIDE.md](VIBEOFFICE_IMPLEMENTATION_GUIDE.md).

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

## 3. 부분 구현 (개념은 있으나 명세 형태가 아님)

| 명세 요구 | 현재 상태 | 남은 일 |
|---|---|---|
| 부서 handoff 계약 | `handoff_to` 문자열, 상위 산출물 본문만 하위 컨텍스트에 주입 | `inputVersions`·`requiredOutputs`·`acceptanceCriteria`·거부 조건·`status` 8단계 |
| stale 전파 | `evidence.stale`만 존재 | 산출물 간 `dependsOn` 기반 stale 전파(09A 4장 규칙) |
| 리뷰 findings | 리뷰 결과가 텍스트 + `changes_requested` | `severity`/`category`/`ownerDepartment`/`autoFixable` 스키마, 소유 부서 반송, 동일 finding 2회 시 중단 |
| 상태 머신 | 실행 상태(`executing`, `lead_review_running` 등) | 제품 상태(`PLANNING_APPROVED`…`EXPORTED`) 분리 |
| 산출물 버전 | 파일 + hash | `Artifact`/`ArtifactVersion`(type·status·currentVersionId·dependsOn) |
| 오피스 UI | 회사 오피스 맵 + 업무 콘솔 | Start·Planning Room·Design Studio·Architecture Lab·Build Floor·Review Room·Shipping Dock 화면 |
| 초보자 오류 표시 | 토스트 경고 | 쉬운 설명 → 영향 → 재시도 → 기술 세부 4단 형식 |

## 4. 미구현 (코드 0)

명세 파일 기준 전부 신규 구현 대상이다. 코드 검색에서 `blueprint`, `readiness`, `traceability`, `screen_spec`, export/ZIP 관련 심볼은 `apps/` 전체에 존재하지 않는다.

1. **Intake / 최소 질문** — 시작 카드 4종 이상, 30자 입력 → Blueprint 초안, 필수 질문 최대 3개, `추천값으로 진행`·`모름`·`나중에 결정` (04_CORE_FLOW P0-01/02, 09_ACCEPTANCE)
2. **project-blueprint.json** — `InferredValue`(value·confidence·status·source), Must 3~5개, Later/Out, 위험 (`reference/product-context/schemas/project-blueprint.schema.json`)
3. **기획부 패키지 생성** — PRODUCT_BRIEF / MVP_SCOPE / REQUIREMENTS / ROADMAP / DECISIONS
4. **디자인부 패키지 생성** — IA / USER_FLOWS / SCREEN_SPEC / DESIGN_SYSTEM / COMPONENT_INVENTORY / prototype, 화면 3~7개, loading·empty·error
5. **기술설계부 패키지 생성** — ARCHITECTURE / API_CONTRACT.yaml / DATA_MODEL / ERD / ENVIRONMENT / SECURITY_BASELINE / TECHNICAL_TASKS
6. **내부 MVP 빌드 표준** — 70점대 buildable MVP, mock 경계, PROJECT_STATUS / BUILD_REPORT / current-state.json
7. **QA 반송 루프** — review-findings.json, 소유 부서 라우팅, 최소 수정, Gate 재검사, 반복 제한
8. **추적성** — GOAL→FEATURE→REQUIREMENT→FLOW→SCREEN→API→TASK→TEST→EVIDENCE, `traceability-map.json`, `artifact-index.json`, drift 계산
9. **준비도 H0~H5** — 7조건 점수화, `handoff-readiness.json`, 내보내기 lint(필수 파일·빈 섹션·secret·절대경로·깨진 import)
10. **Export 패키징** — AGENTS.md / CLAUDE.md / NEXT_ACTION.md / PROJECT_STATUS.md 생성 + ZIP·Git 패키지 + `export-manifest.json`
11. **직접 시각 편집(P1)** — 모델 호출 없는 텍스트·색·간격·순서 편집
12. **Golden Path E2E** — 명세 08장 예시 입력 1건이 H4 폴더까지 자동 통과

## 5. 현재 리스크

- **문서-코드 불일치**: `AI_AUTOMATION_OFFICE_V1_PLAN.md`가 제시한 `packages/contracts`, `policy-engine`, `orchestrator` 등 패키지 구조는 존재하지 않는다. 실제 구현은 `apps/api/main.py`(171KB) + `worker.py`(66KB) 단일 모듈이다. → `reference/legacy/`로 이동, 신규 작업은 이 갭 문서를 기준으로 한다.
- **거대 모듈**: 제품 계층을 `main.py`에 추가하면 유지 불가. 신규 코드는 별도 모듈로 분리해야 한다.
- **환경 의존성 미문서화**: `ripgrep` 미설치 시 `search_files`/`find_symbols` 계열 테스트 3건이 실패한다. README 요구사항에 없다.
- **동적 라우팅과 고정 파이프라인 충돌**: 제품 파이프라인은 부서 순서가 고정이므로 GLM 동적 라우팅을 그대로 쓰면 게이트가 무의미해진다. 이 흐름 전용 고정 프로필이 필요하다.
