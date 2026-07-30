# VibeOffice 구현 지침 (기준 문서)

- 작성일: 2026-07-30
- 이 문서 위치: 앞으로 모든 VibeOffice 관련 작업의 **1순위 참조 문서**
- 읽는 순서: 이 문서 → [VIBEOFFICE_GAP_ANALYSIS.md](VIBEOFFICE_GAP_ANALYSIS.md) → 해당 부서의 `reference/product-context/*` 명세

## 1. 목표 한 문장

비전공 사용자의 짧은 아이디어를 **기획 → 디자인 → 기술설계 → 개발 → QA → 출고** 순서로 처리해, Codex·Claude Code가 재해석 없이 이어받을 수 있는 **H4 등급 프로젝트 폴더**를 만든다.

## 2. 불변 원칙

### 제품

1. 사용자는 프롬프트를 못 써도 된다. 필수 질문은 최대 3개, 모든 질문에 `추천값으로 진행`·`모름`·`나중에 결정`을 준다.
2. 문서만 만들지 않는다. 눈에 보이는 시안 또는 실행 가능한 골격을 함께 준다.
3. 사용자 승인은 기본 3회다. 기획 승인, 시안 승인, 출고 승인. 나머지는 안전 자동화한다.
4. 부서는 내부 구현이다. 사용자에게는 단계·산출물·차단 이유를 보이고, 내부 사고 과정과 회의 연출은 보이지 않는다.
5. 아바타 애니메이션·오피스 연출은 항상 마지막 우선순위다.

### 코드 (constitution/KARPATHY.md와 동일 기조)

1. 전면 재작성 금지. 기존 실행 런타임(Job·격리·증거·리뷰·복구)을 재사용한다.
2. 채팅 기록을 상태의 원천으로 쓰지 않는다. 상태 원천은 DB + 워크스페이스 파일이다.
3. 모델 응답은 스키마 검증 후 저장한다. 검증 실패는 실패로 처리한다.
4. `implemented`와 `verified`를 분리한다. 증거 없는 완료는 없다.
5. 신규 코드는 `apps/api/main.py`에 넣지 않는다. 별도 모듈로 분리한다.

## 3. 계층 분리

```text
[제품 계층 = 신규]  vibeoffice: project · blueprint · artifact(version) · handoff · finding · readiness · export
        │ 부서 phase를 실행 요청으로 변환
[실행 계층 = 기존]  task_phases · jobs · agent_runs · tools · evidence · reviews · checkpoints
        │
[격리 계층 = 기존]  workspace copy / git worktree · permission_rules
```

권장 신규 파일:

```text
apps/api/vibeoffice/__init__.py
apps/api/vibeoffice/schema.py      # 테이블 생성·마이그레이션
apps/api/vibeoffice/models.py      # Pydantic 스키마 (blueprint, handoff, finding, readiness)
apps/api/vibeoffice/pipeline.py    # 부서 순서·게이트·상태 전이
apps/api/vibeoffice/artifacts.py   # 버전·의존성·stale 전파·파일 미러
apps/api/vibeoffice/readiness.py   # H0~H5 점수·export lint
apps/api/vibeoffice/export.py      # AGENTS/CLAUDE/NEXT_ACTION 생성·ZIP
apps/api/vibeoffice/routes.py      # /api/vibe/* 라우터 (main.py에 include만 추가)
apps/api/test_vibeoffice_*.py      # 슬라이스별 테스트
```

## 4. 제품 부서 → 기존 직원 매핑

동적 라우팅(GLM)을 이 흐름에서는 쓰지 않는다. 아래 고정 프로필을 사용한다.

| 제품 부서 | 책임 직원 | 소유 산출물 | 게이트 |
|---|---|---|---|
| Planning | FRAME (lead), FLOW | PRODUCT_BRIEF, MVP_SCOPE, REQUIREMENTS, ROADMAP, DECISIONS, project-blueprint.json | Gate A·B |
| Design | MOSS (lead), FLOW | IA, USER_FLOWS, SCREEN_SPEC, DESIGN_SYSTEM, COMPONENT_INVENTORY, prototype | Gate C |
| Architecture | BUILD (lead), BACK, LINK(AI 필요 시) | ARCHITECTURE, API_CONTRACT.yaml, DATA_MODEL, ERD, ENVIRONMENT, SECURITY_BASELINE, TECHNICAL_TASKS | Gate D·E |
| Build | FRONT, BACK (lead BUILD) | source, PROJECT_STATUS, BUILD_REPORT, current-state.json | Gate F |
| QA | GUARD (lead), TRACE, SHIELD | REVIEW_FINDINGS, ACCEPTANCE_REPORT, BUILD_EVIDENCE, review-findings.json, handoff-readiness.json | Gate F·G |
| Shipping | DOCS (lead LENS) | AGENTS.md, CLAUDE.md, NEXT_ACTION.md, README, export-manifest.json | Gate G |

QA 부서는 생성 부서와 절대 겹치지 않는다. Build를 BUILD 팀이 소유하면 리뷰는 GUARD, GUARD가 소유하면 LENS가 리뷰한다(기존 규칙 유지).

## 5. 데이터 모델 추가안

DB는 기존 `data/ai-office.sqlite3`를 쓰고 테이블만 추가한다. 모든 산출물은 **DB 레코드 + 워크스페이스 파일**을 동시에 유지하고, 파일이 진실이면 hash로 검증한다.

```sql
vo_projects(id, task_id, name, mode, skill_level, team_size, deadline, state, created_at, updated_at)
vo_blueprints(id, project_id, version, content_json, approved_at)      -- InferredValue 포함
vo_artifacts(id, project_id, type, status, current_version_id, depends_on_json, updated_at)
vo_artifact_versions(id, artifact_id, version, path, sha256, source_blueprint_version, created_by, created_at)
vo_handoffs(id, project_id, from_dept, to_dept, status, input_versions_json,
            required_outputs_json, constraints_json, acceptance_json, open_decisions_json, approved_by, created_at)
vo_findings(id, project_id, severity, category, owner_dept, title, evidence_json,
            impact, requested_change, affected_artifacts_json, auto_fixable, status, repeat_count)
vo_readiness(id, project_id, grade, score, conditions_json, lint_json, created_at)
vo_exports(id, project_id, target, path, manifest_json, status, created_at)
```

`state` 값 (05_AGENT_ORCHESTRATION 상태 머신 그대로):

```text
DRAFT → PLANNING → PLANNING_REVIEW → PLANNING_APPROVED
→ DESIGN → DESIGN_REVIEW → DESIGN_APPROVED
→ ARCHITECTURE → ARCHITECTURE_REVIEW → BUILD → BUILD_VERIFICATION
→ QA → (REWORK_REQUIRED | SHIPPING_READY) → SHIPPING → EXPORTED
예외: NEEDS_USER_DECISION, HANDOFF_REJECTED, RETRYABLE_FAILURE, STRUCTURAL_REPLAN, STALE_ARTIFACTS, ROLLBACK_REQUIRED
```

워크스페이스 파일 배치(= 그대로 내보내는 폴더):

```text
<workspace>/
├── AGENTS.md  CLAUDE.md  NEXT_ACTION.md  PROJECT_STATUS.md  README.md
├── docs/       PRODUCT_BRIEF.md … TRACEABILITY.md
├── prototype/ 또는 실제 source
└── .vibeoffice/ project-blueprint.json roadmap.json artifact-index.json
                traceability-map.json current-state.json review-findings.json
                handoffs/*.json export-manifest.json handoff-readiness.json
```

정답 예시는 `reference/product-context/reference-output/`를 그대로 목표로 삼는다. 스키마는 `reference/product-context/schemas/*.json`으로 검증한다.

## 6. API 추가안

기존 `/api/tasks/*`는 건드리지 않고 `/api/vibe/*`를 추가한다.

```http
POST  /api/vibe/projects                                  # 시작 카드 선택 + 자유 입력
POST  /api/vibe/projects/{id}/intake                      # 의도 정규화, 추정값 생성
GET   /api/vibe/projects/{id}/intake/questions            # 최대 3개
POST  /api/vibe/projects/{id}/intake/answers
POST  /api/vibe/projects/{id}/blueprint/generate
GET   /api/vibe/projects/{id}/blueprint
POST  /api/vibe/projects/{id}/blueprint/approve           # 승인 1
POST  /api/vibe/projects/{id}/departments/{dept}/run      # 실행 계층 Job 큐잉
GET   /api/vibe/projects/{id}/artifacts[/{type}]
POST  /api/vibe/projects/{id}/artifacts/{type}/approve    # 승인 2 (design)
GET   /api/vibe/projects/{id}/handoffs
POST  /api/vibe/projects/{id}/qa/run
POST  /api/vibe/projects/{id}/findings/{fid}/fix
GET   /api/vibe/projects/{id}/readiness
POST  /api/vibe/projects/{id}/exports                     # 승인 3 (shipping)
GET   /api/vibe/projects/{id}/exports/{exportId}
```

## 7. 구현 순서 — 수직 슬라이스

각 슬라이스는 **구현 전에 성공 조건을 적고**, 완료 시 테스트와 문서를 함께 갱신한다. 슬라이스를 건너뛰지 않는다.

### S1. Intake → Blueprint → 기획 승인

- 구현: 시작 카드, 자유 입력 정규화, 추정값 8종(projectType·targetUser·coreProblem·successMoment·deadline·teamSize·skillLevel·data/auth/ai), 질문 ≤3, Blueprint 생성·승인
- 성공 조건: 30자 입력 1건이 스키마 검증을 통과하는 `project-blueprint.json`을 만든다. Must 3~5개, Later·Out 존재. 재질문 없음.
- 검증: `test_vibeoffice_intake.py` — 짧은 입력 fixture 3건, 질문 개수 상한, 스키마 검증

### S2. 기획 승인 → 디자인 패키지 + handoff 계약

- 구현: `vo_handoffs` 봉투(inputVersions·requiredOutputs·acceptanceCriteria), USER_FLOWS·SCREEN_SPEC 생성, 산출물 버전·stale 표시, 거부 조건 검사
- 성공 조건: 승인된 Blueprint 버전만 입력으로 쓴다. 화면 3~7개, 모든 Must가 화면에 연결, 각 데이터 화면에 loading·empty·error. 거부 조건 위반 시 handoff가 `rejected`가 된다.
- 검증: `test_vibeoffice_handoff.py` — 승인 안 된 draft 인계 차단, Must 미연결 시 거부

### S3. 디자인 승인 → 기술설계 계약

- 구현: API_CONTRACT.yaml, DATA_MODEL, TECHNICAL_TASKS 생성, 화면↔데이터 source 매핑, 필드 일치 검사
- 성공 조건: API와 Data Model 필드가 일치한다. 데이터 화면마다 source가 있다. 작업이 한 세션 크기로 쪼개지고 의존성이 있다.
- 검증: `test_vibeoffice_contracts.py` — 필드 불일치 fixture가 Gate D에서 차단

### S4. 기술설계 승인 → 내부 MVP 빌드

- 구현: starter/template 기반 골격, 핵심 route, mock adapter, 상태 처리, build·smoke 실행, PROJECT_STATUS·BUILD_REPORT·current-state.json
- 성공 조건: 공식 build 성공 evidence가 있다. mock 경계가 문서에 명시된다. 미구현 항목이 명시된다. 완성형 SaaS를 목표로 하지 않는다(70점대).
- 검증: 기존 evidence 게이트 재사용 + `test_vibeoffice_build.py`

### S5. QA 반송 루프 → H4 Export

- 구현: `review-findings.json`, 소유 부서 라우팅, stale 전파, 최소 수정, Gate 재검사, 준비도 H0~H5, export lint, AGENTS/CLAUDE/NEXT_ACTION 생성, ZIP
- 성공 조건: Blocker 0 이전에는 출고 불가. secret·절대경로 검출 시 실패. 동일 finding 2회 반복 시 자동 루프 중단. 산출물이 `reference-output/`과 동일 구조.
- 검증: `test_vibeoffice_export.py` + Golden Path E2E 1건

### S6. (그 다음) 대화형 지시 계층, 오피스 UI 7화면, 직접 시각 편집

앞의 5개 슬라이스가 끝나기 전에 착수하지 않는다. 대화형 지시와 자율 실행은 별도 목표 문서를 따른다: [CONVERSATIONAL_AGENT_TARGET.md](CONVERSATIONAL_AGENT_TARGET.md). 두 목표는 충돌하지 않는다 — 제품 파이프라인은 부서 순서와 게이트를 정하고, 대화 계층은 그 파이프라인을 **버튼 대신 말로** 굴리는 표면이다. 승인 지점 3개(기획·시안·출고)는 대화에서도 유지한다.

## 8. 게이트 체크리스트 (09A 요약)

| Gate | 통과 조건 | 위반 시 |
|---|---|---|
| A Problem | 대상 사용자·행동 기반 문제·관찰 가능한 성공 장면 | Planning 재작업 |
| B Scope | Must 3~5, Later·Out, 기간·팀 대비 타당, 인증+AI+파일+실시간+결제 동시 포함 경고 | Planning 재작업 |
| C UX | 모든 Must가 흐름에 존재, dead-end 없음, CTA 동작, loading·empty·error, 모바일 핵심 흐름 | Design 반송 |
| D Technical | 화면 데이터 source, API↔Data 일치, 인증 일치, 외부 API 실패 처리, secret 규칙 | Architecture 반송 |
| E Task | 한 세션 크기, 의존성, 검증 가능한 done, Out 작업 없음 | Architecture 반송 |
| F Build | install·dev·build·test, 공식 build 성공, 치명 콘솔 오류 없음, smoke, 미구현 명시 | Build 반송 |
| G Handoff | AGENTS·CLAUDE·NEXT_ACTION·PROJECT_STATUS 최신, Blocker 0, secret scan, ZIP manifest | 출고 차단 |

## 9. 반송과 stale 규칙

| 문제 유형 | 소유 부서 |
|---|---|
| 사용자·문제·범위 | Planning |
| 정보 구조·화면·상태 | Design |
| API·DB·인증·아키텍처 | Architecture |
| 코드·빌드·테스트 | Build |
| 파일 누락·인계 형식 | Shipping |

stale 전파:

- 대상 사용자 변경 → Brief·UX·Screen·Requirements·테스트 페르소나
- Must 변경 → Scope·Flow·Screen·API/Data·Tasks·Tests·NEXT_ACTION
- 기술 스택 변경 → Architecture·API·Data Model·Tasks·AGENTS·Setup
- 색상·문구 변경 → Design·Screen Spec·시각 테스트만

전체 재생성보다 **최소 영향 수정**이 기본이다. 같은 finding이 2회 반복되면 자동 수정을 멈추고 상위 산출물 충돌을 조사한다.

## 10. 승인 경계

| 자동 허용 | 사용자 승인 필요 |
|---|---|
| 문서 형식 정리, ID·링크 연결, 기능명 동기화, stale 표시, 테스트 재시도 | Must/Later/Out 변경, 사용자 흐름 변경, 기술 스택 변경, 데이터 삭제, 인증·권한 변경, 비용 발생·외부 전송·배포 |

## 11. 금지

- 아바타 애니메이션·오피스 연출부터 구현
- 승인되지 않은 draft를 다음 부서로 인계
- QA finding을 전체 재생성으로 해결
- build 증거 없이 MVP 완료 처리
- 부서마다 같은 문서를 독립 재생성
- 계획과 실제 상태(current-state)를 한 문서에 섞기
- Codex·Claude에 긴 프롬프트만 넘기고 파일을 안 넘기기
- 산출물·내보내기 파일에 secret 또는 로컬 절대경로 포함

## 12. 검증 명령

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py" -v
.\.venv\Scripts\python.exe scripts\verify_routing.py
.\.venv\Scripts\python.exe scripts\verify_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\audit_package.py
```

```powershell
cd apps\web
npm.cmd test -- --run
npm.cmd run build
```

현재 상태(2026-07-30): API 31개 중 28 pass. `test_agent_tools`의 3건은 로컬 `ripgrep` 미설치로 실패한다. 검색·심볼 도구를 쓰는 작업 전에 `rg`를 설치한다.

## 13. 완료 보고 형식

1. 구현한 사용자 가치
2. 변경 파일
3. 검증 결과 (실행한 명령과 결과)
4. 알려진 제한
5. 다음으로 구현할 가장 작은 수직 슬라이스

## 14. 문서 규칙

- 목표 명세는 `reference/product-context/`만 수정한다. 요약본을 따로 만들지 않는다.
- 현재 구현 사실은 `docs/VIBEOFFICE_GAP_ANALYSIS.md`와 `docs/RUNTIME_HARDENING.md`에 쓴다.
- 로드맵·미구현 계획은 `docs/RUNTIME_ROADMAP.md`에 쓴다.
- 작업 실행 결과물은 `AI_OFFICE_OUTPUTS/<TASK-ID>/`에만 남긴다. 저장소 루트에 보고서를 만들지 않는다.
- 폐기된 계획은 삭제하지 말고 `reference/legacy/`로 옮기고 상단에 폐기 사유를 적는다.
- 보관할 완료 산출물은 `reference/outputs/<TASK-ID>/`로 옮긴다.
- 문서 지도: [docs/README.md](README.md)
