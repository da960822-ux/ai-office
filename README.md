# AI Office — Corporate OS v6.2

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async%20worker-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-Vite%20%2B%20TS-61DAFB?logo=react&logoColor=black)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![Tests](https://img.shields.io/badge/tests-70%20passing-brightgreen)

전문 스킬을 가진 24명의 AI 직원이 **팀 단위로 실제 로컬 프로젝트를 조사·수정·검증**하는 로컬 실행 시스템입니다. 역할극 채팅이 아니라, 모델 호출·도구 호출·파일 변경·명령 실행·증거 수집이 모두 SQLite에 기록되며, 상태 요약은 UI에 표시됩니다.

- **단일 사용자·로컬 전용**: 브라우저는 모델을 직접 호출하지 않습니다. FastAPI가 Job을 큐에 넣고 별도 worker 프로세스가 실행합니다.
- **증거 없으면 완료 없음**: 실제 파일, hash, 검증 명령 결과, 독립 리뷰 통과가 없으면 작업은 `completed`가 되지 않습니다.
- **권한은 계약으로 제한**: 파일 경로·명령·MCP 도구는 TaskContract의 allow/ask/deny 규칙 안에서만 동작합니다.

이 프로젝트가 **하지 않는 것**: 멀티테넌트 SaaS, 자동 배포, 승인 없는 외부 전송·게시, 스킬 자동 다운로드, 무제한 자율 실행.

## 왜 만들었나 — 풀어야 했던 엔지니어링 문제

LLM 멀티 에이전트 데모 대부분은 "채팅창에 역할극"에서 멈춥니다. 이 프로젝트는 그 다음 단계, 즉 **에이전트가 실제로 파일을 건드리는 순간부터 생기는 문제**를 다룹니다.

| 문제 | 이 저장소의 해법 |
|---|---|
| 에이전트가 "다했다"고 말해도 실제로는 안 됐을 때 | Task는 실제 파일 hash·검증 명령 종료 코드·독립 리뷰 통과 3가지가 모두 있어야 `completed`로 전이 (`apps/api/main.py`) |
| worker 프로세스가 죽으면 Job이 영원히 `running`으로 남는 문제 | SQLite 원자적 lease + heartbeat. lease 만료된 Job은 재시작 시 자동으로 `interrupted`, 재시도는 이미 성공한 `agent_run`을 건너뜀 |
| 에이전트에게 파일 접근·명령 실행 권한을 얼마나 줄지 | TaskContract가 요청 단위로 `allowed_paths`/`allowed_commands`/`permission_rules`를 발급. `ask` 등급은 HTTP 428로 멈추고 사용자 승인을 기다림 |
| 24명·8부서 규모에서 "누가 이 일을 할지" 정적 매핑이 깨지는 문제 | 하드코딩된 라우팅 표 없음. 매 요청마다 모델이 `department-boundaries.json` + 가용 인력·스킬을 함께 보고 동적으로 배정 |
| API와 worker가 다른 버전으로 떠 있을 때 생기는 조용한 실패 | `/api/runtime/version`에서 build id·schema version을 대조해 불일치 시 UI 실행 버튼을 하드 차단 |

규모: FastAPI + worker 약 7.8k LOC(Python), React/Vite/TS UI 약 1.2k LOC, 자동 테스트 70건(`apps/api/test_*.py`) + 정적 정합성 검사 스크립트 3종.

## 스택

**Backend** Python 3.12 · FastAPI · SQLite(WAL) · OpenRouter API · ripgrep(코드 검색) · Pyright(선택)
**Frontend** React · Vite · TypeScript · Server-Sent Events
**인프라** 단일 프로세스가 아닌 다중 worker 프로세스, Git worktree 기반 작업 격리, OS keyring 기반 시크릿 저장

## 목차

- [업무 흐름](#업무-흐름)
- [아키텍처](#아키텍처)
- [요구 사항](#요구-사항)
- [설치](#설치)
- [실행](#실행)
- [설정](#설정)
- [사용 흐름](#사용-흐름)
- [API 요약](#api-요약)
- [데이터와 산출물 위치](#데이터와-산출물-위치)
- [프로젝트 구조](#프로젝트-구조)
- [검증](#검증)
- [문서](#문서)
- [로드맵](#로드맵)
- [트러블슈팅](#트러블슈팅)
- [보안](#보안)
- [라이선스](#라이선스)

## 업무 흐름

```text
대표(사용자) 요청
→ NAVI(z-ai/glm-5.2)가 요청을 정규화하고 필요한 팀장 후보만 제안
→ 사용자가 팀장 선택
→ NAVI + 선택 팀장 실제 회의 (발언 기록 없으면 회의 미완료)
→ 팀장이 자기 부서 실행자만 배정, 업무별 스킬 최대 3개 동적 선택
→ 실행자가 파일·검색·명령·MCP 도구로 작업 (부서별 격리 워크스페이스 또는 Git worktree)
→ 부서 초안을 실제 파일로 저장 → 최종 책임자가 FINAL.md로 통합
→ NAVI(z-ai/glm-5.2)가 증거를 검토해 완료 여부를 판정 (병렬 Git worktree 병합 전 diff 검수는 GUARD, GUARD 소유 시 LENS가 별도로 수행)
→ changes_requested면 지적 사항을 넣어 자동 재통합
→ 실제 파일 + 통과한 리뷰 + 증거가 모두 있을 때만 완료
```

팀장 아바타에 직접 지시한 소규모 업무는 NAVI 판단과 팀장 회의를 생략하지만, 실행 후 해당 팀장의 독립 리뷰는 생략하지 않습니다.

### 조직

8개 부서 × 3명 = 24명. 부서 소유 범위와 필수 인계 범위는 [`registry/department-boundaries.json`](registry/department-boundaries.json)에 정의되어 있으며, 실행·회의 프롬프트에 주입됩니다. 팀장은 다른 부서 업무를 흡수하지 않고 소유 부서로 넘깁니다.

| 부서 | 팀장 | 실행자 | 소유 범위 |
|---|---|---|---|
| operations-planning | NAVI | ROUTE, CLOCK | 요청 정규화, 계약, 라우팅, 일정·예산 |
| product-experience | FRAME | FLOW, MOSS | 문제 정의, PRD, 수용 기준, UX/UI 명세 |
| application | BUILD | FRONT, BACK | 기술 설계, 프런트·백엔드 구현, 통합 검토 |
| ai-data | LINK | SIGNAL, EVAL | AI 구조, 검색·데이터 파이프라인, 모델 평가 |
| platform-reliability | SHIP | SRE, COST | 릴리스, CI/CD, 관측성, 신뢰성·비용 |
| quality-security | GUARD | TRACE, SHIELD | 독립 시험, 보안·개인정보, 증거 게이트 |
| growth-marketing | GROW | VOICE, PULSE | 시장·고객 조사, 포지셔닝, 카피, 실험 |
| service-knowledge | LENS | JOURNEY, DOCS | 여정 검토, 문서화, 지식 패키징 |

업무 종류별 하드코딩된 라우팅 표는 없습니다(`registry/task-profiles.json`은 비어 있음). 매 요청마다 모델이 부서 소유권·가용 직원·스킬·산출물 기준을 함께 보고 동적으로 결정합니다.

## 아키텍처

```text
React + Vite UI (apps/web)
  │ REST + SSE
FastAPI (apps/api/main.py)
  │ Job enqueue / state query
SQLite WAL (data/ai-office.sqlite3)
  │ atomic lease + heartbeat
Worker 프로세스 (apps/api/worker.py, 기본 다중 프로세스)
  ├─ OpenRouter 모델 호출
  ├─ 워크스페이스 파일 도구 (읽기·정밀 치환·패치·생성)
  ├─ 코드 탐색 (ripgrep 심볼·참조 검색, Pyright 진단, 테스트 탐색)
  ├─ 검증 명령 실행 (TaskContract 허용 명령만)
  ├─ 웹 조사 (Brave → SearXNG → Bing RSS, 공개 PDF 추출, 승인형 헤드리스 렌더링)
  ├─ 문서 렌더 (DOCX/PDF/XLSX/PPTX/HWPX 생성 후 재파싱 검증)
  └─ 설정된 MCP 도구
```

- **Task 상태**와 **Job 상태**를 분리합니다. Task는 사용자가 이해할 업무 단계, Job은 실행기 상태입니다.
- worker는 모델·도구 호출 사이의 안전 지점에서 pause/cancel을 처리하고, 응답 대기 중에는 lease와 heartbeat를 갱신합니다.
- worker 재시작 시 다른 lease를 가진 실행 Job은 `interrupted`가 되고, 재시도는 성공한 `agent_run`을 건너뜁니다.
- API build id, worker build id, schema version이 일치하지 않으면 UI의 실행 기능이 차단됩니다.

자세한 내용: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/RUNTIME_HARDENING.md](docs/RUNTIME_HARDENING.md)

## 요구 사항

| 항목 | 버전·비고 |
|---|---|
| OS | Windows 10/11 (런처가 PowerShell 기반) |
| Python | 3.12 이상 |
| Node.js | 20 이상 + npm |
| ripgrep (`rg`) | 필수. 없으면 코드 검색·심볼 도구가 HTTP 503으로 실패 |
| OpenRouter API key | 필수. UI 설정 화면에서 입력해 OS keyring에 저장 |
| Git | 선택. Git 프로젝트면 브랜치·worktree 격리를 사용 |
| Pyright | 선택. 설치 시 Python 의미 진단 사용 (`node_modules`에 pin) |
| 헤드리스 Chrome/Edge | 선택. JavaScript 페이지 조사에만 사용, 기본 `ask` 승인 |

## 설치

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
cd apps\web
npm install
cd ..\..
```

내장 스킬 설치·검증 (설치본은 공용 풀 `skills/`에 1부만 생기고, `--employee`는 어떤 스킬을 받을지만 좁힙니다):

```powershell
.\.venv\Scripts\python.exe scripts\install_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\verify_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\render_skill_indexes.py
```

인터넷이 차단된 환경은 [`manual-drop/README.md`](manual-drop/README.md) 절차를 따릅니다. 필수 스킬의 `SKILL.md`와 lock hash가 없으면 해당 직원은 실행되지 않고 `blocked` 이벤트가 남습니다.

## 실행

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-ai-office.ps1
```

또는 `AI_Office_실행.cmd`를 실행합니다. 런처가 하는 일:

1. 이 저장소 루트에서 시작된 기존 uvicorn·worker·vite 프로세스만 종료
2. 비어 있는 포트 선택 — API `8100~8199`, UI `5175~5199`
3. API, worker, Vite dev server를 같은 build로 시작
4. `/api/runtime/version`에서 API build == worker build 확인
5. 실제 주소를 [`.ai-office/runtime.json`](.ai-office) 에 기록하고 브라우저 열기

포트는 고정이 아닙니다. 실행 중 주소는 `.ai-office/runtime.json`에서 확인하세요.

## 설정

### API key

UI 설정 화면에서 입력하면 OS keyring(`AI-Automation-Office` 서비스)에 저장됩니다. 저장소나 SQLite에 평문으로 남기지 않습니다. CI·헤드리스 환경에서는 환경 변수를 사용합니다.

### 모델

| 용도 | 기본값 | 변경 |
|---|---|---|
| NAVI 라우팅·판단 | `z-ai/glm-5.2` (코드 고정) | `apps/api/main.py:57` |
| 팀장 | `openai/gpt-5` | UI 설정 → `.ai-office/settings.json` |
| 실행자 | `openai/gpt-5-mini` | UI 설정 → `.ai-office/settings.json` |

### 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OPENROUTER_API_KEY` | — | 없으면 keyring, 그다음 `OPENAI_API_KEY`를 사용 |
| `AI_OFFICE_MODEL_TIMEOUT_SECONDS` | `900` | 모델 호출 하드 데드라인 (최소 30) |
| `AI_OFFICE_WORKER_MODE` | `process` | `thread`는 로컬 디버깅 전용 |
| `AI_OFFICE_WORKER_CONCURRENCY` | `4` | 동시 실행 worker 프로세스 수 (1~8로 제한) |
| `AI_OFFICE_SEARCH_ENDPOINT` | — | SearXNG 등 자체 검색 엔드포인트 |
| `BRAVE_SEARCH_API_KEY` | — | Brave Search API 사용 시 |
| `AI_OFFICE_BROWSER_PATH` | 자동 탐색 | 헤드리스 렌더링에 쓸 Chrome/Edge 경로 |

## 사용 흐름

1. **프로젝트 등록** — 로컬 폴더를 선택합니다. Git 저장소면 브랜치·worktree, 아니면 격리 복사본을 사용합니다.
2. **업무 요청** — 자연어로 요청합니다. NAVI가 계약(TaskContract)과 팀장 후보를 제안합니다.
3. **계약 확인** — 허용 경로, 허용 명령, 금지 행동, 수용 기준을 확인합니다. `ask` 권한은 실행 중 승인 요청(HTTP 428)으로 멈춥니다.
4. **실행 관제** — SSE로 회의 발언, 도구 호출 요약, 파일 변경, 검증 결과가 들어옵니다. pause / resume / cancel / 단계 재시도가 가능합니다.
5. **추가 지시** — 실행 중 입력한 지시는 durable steering 큐에 쌓여 다음 모델·도구 경계에서 1회 적용됩니다.
6. **결과 확인** — `FINAL.md`와 부서 초안, 증거, 렌더된 문서를 확인합니다. 리뷰가 반려하면 자동 재통합됩니다.
7. **복구** — 체크포인트를 복원하면 이후 증거는 stale로 표시됩니다. Job 실행 중에는 복원할 수 없습니다.

## API 요약

기본 주소는 `.ai-office/runtime.json`의 `api_url`입니다.

| 그룹 | 엔드포인트 |
|---|---|
| 상태 | `GET /api/health`, `GET /api/runtime/version`, `GET /api/usage/summary` |
| 이벤트 | `GET /api/tasks/{id}/events/stream` (SSE) |
| 레지스트리 | `GET /api/registry/employees`, `GET /api/agents/{id}/capabilities`, `GET /api/teams/{id}/capabilities`, `POST /api/skills/verify` |
| 프로젝트 | `GET /api/projects`, `POST /api/projects`, `POST /api/projects/pick` |
| 작업 | `POST /api/tasks`, `GET /api/tasks/{id}`, `POST /api/tasks/{id}/contract`, `POST /api/tasks/{id}/plan` |
| Job | `POST /api/tasks/{id}/jobs/{plan\|meeting\|execute\|review}`, `POST /api/jobs/{jobId}/control`, `POST /api/jobs/{jobId}/retry` |
| 제어 | `POST /api/tasks/{id}/{pause\|resume\|cancel\|steer\|retry}` |
| 배정 | `POST /api/tasks/{id}/{select-leads\|select-workers\|direct-dispatch}` |
| 검수 | `POST /api/tasks/{id}/reviews`, `POST /api/tasks/{id}/approval`, `POST /api/tasks/{id}/reflection` |
| 권한 | `POST /api/tasks/{id}/permissions/{requestId}` |
| 복구 | `POST /api/tasks/{id}/checkpoints/{checkpointId}/restore` |
| 워크스페이스 | `GET/POST /api/tasks/{id}/workspace`, `POST /api/tasks/{id}/runs`, `POST /api/tasks/{id}/agent/run` |
| 설정 | `GET/POST /api/settings/model`, `GET /api/settings/models`, `GET/POST /api/settings/mcp`, `POST /api/settings/mcp/{id}/test` |
| 오피스 | `GET /api/tasks/{id}/office` |

## 데이터와 산출물 위치

| 경로 | 내용 | Git |
|---|---|---|
| `data/ai-office.sqlite3` | 작업·Job·이벤트·증거·사용량 | 제외 |
| `data/workspaces/WS-*` | 작업별 격리 워크스페이스 | 제외 |
| `<워크스페이스>/AI_OFFICE_OUTPUTS/<TASK-ID>/` | 부서 초안 + `FINAL.md` + 렌더 파일 | 제외 |
| `reference/outputs/<TASK-ID>/` | 보관할 완료 산출물 | 포함 |
| `.ai-office/` | 런타임 주소·모델 설정·사용자 스킬 inbox | 제외 |
| `logs/`, `.cache/` | 로그, 제거된 스킬 백업 | 제외 |

산출물 유형별 파일명·필수 섹션·검수 규칙은 [`registry/deliverable-standards.json`](registry/deliverable-standards.json)에 16종이 등록되어 있습니다. 채팅 답변은 산출물로 인정되지 않습니다.

## 프로젝트 구조

```text
apps/api/            FastAPI, SQLite 스키마, worker, 에이전트 도구, 문서 렌더러, 조사 모듈
apps/web/            React + Vite + TypeScript 오피스 UI
employees/           직원 persona, 권한(PERMISSIONS.yaml), 역할 코어 스킬(_local-role-core)
skills/              부서 공용 스킬 풀 (설치본 1부, 런타임이 직접 참조)
registry/            직원·스킬·모델 binding, lock, 부서 경계, 산출물 기준
runtimes/            공통 runtime 지침 6종 (PLANNER, BUILDER, REVIEWER, VERIFIER, OPERATOR, SPECIALIST)
constitution/        운영 원칙 (CORPORATE, KARPATHY, CAVEMAN, TOKEN_ECONOMY, DIAGNOSIS)
scripts/             런처, 스킬 설치·검증, 라우팅 검사, 패키지 감사, 스킬 A/B 리포트
docs/                살아 있는 개발 문서
reference/           참고 자료 · 명세 원본 · 보관 산출물 · 폐기 문서
third_party/         외부 스킬 라이선스 사본
manual-drop/         오프라인 스킬 수동 반입 절차
```

## 검증

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

검사 내용:

- `apps/api/test_*.py` — Job 워크플로, 수용 기준, E2E, 런타임 내구성, 생애주기 권한, 에이전트 도구 (70개)
- `scripts/verify_routing.py` — 24명·8부서·정적 프로필 0개·산출물 기준 정합성
- `scripts/verify_skills.py` — 필수 스킬 존재와 lock hash 일치
- `scripts/audit_package.py` — 직원 필수 파일, constitution 참조, 스킬 정의·설치·라우팅 인덱스, YAML 파싱, Markdown 코드 펜스, 스크립트 컴파일

**현재 상태(2026-07-30)**: `ripgrep`이 설치된 환경에서 전부 통과합니다. `rg`가 없으면 `apps/api/test_agent_tools.py`의 검색·심볼·진단 테스트 3건이 `AgentToolError(503, "ripgrep (rg) is required for search_files")`로 실패합니다.

## 문서

전체 지도: [docs/README.md](docs/README.md)

| 문서 | 용도 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 실행 구성, task/job 분리, 영속성, 권한 |
| [docs/RUNTIME_HARDENING.md](docs/RUNTIME_HARDENING.md) | 현재 런타임 동작 사실 |
| [docs/RUNTIME_ROADMAP.md](docs/RUNTIME_ROADMAP.md) | P0/P1 완료 항목, P2 수용 harness 계획 |
| [reference/legacy/VIBEOFFICE_IMPLEMENTATION_GUIDE.md](reference/legacy/VIBEOFFICE_IMPLEMENTATION_GUIDE.md) | 제품 파이프라인 구현 지침 (신규 작업 1순위) |
| [reference/legacy/VIBEOFFICE_GAP_ANALYSIS.md](reference/legacy/VIBEOFFICE_GAP_ANALYSIS.md) | 구현됨 / 부분 / 미구현 목록 |
| [reference/legacy/CONVERSATIONAL_AGENT_TARGET.md](reference/legacy/CONVERSATIONAL_AGENT_TARGET.md) | 대화형 지시 + 자율 실행 목표와 설계안 |
| [reference/README.md](reference/README.md) | 참고 자료·보관 산출물 규칙 |
| [reference/corporate-os/](reference/corporate-os/) | Corporate OS v6.2 원본 명세 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 변경 원칙과 필수 검증 |
| [SECURITY.md](SECURITY.md) | 보안 정책 |
| [NOTICE.md](NOTICE.md) | 외부 저작물 고지 |

## 로드맵

다음 목표는 초보 사용자의 아이디어를 **기획 → 디자인 → 기술설계 → 개발 → QA → 출고** 순서로 처리해 Codex·Claude Code가 이어받을 수 있는 H4 등급 프로젝트 폴더를 만드는 제품 파이프라인입니다.

- 목표 명세: [reference/product-context/](reference/product-context/)
- 현재 격차: [reference/legacy/VIBEOFFICE_GAP_ANALYSIS.md](reference/legacy/VIBEOFFICE_GAP_ANALYSIS.md) — 실행 계층은 충족, 제품 계층(Blueprint·산출물 버전·handoff 계약·준비도·Export)은 미구현
- 구현 순서와 게이트: [reference/legacy/VIBEOFFICE_IMPLEMENTATION_GUIDE.md](reference/legacy/VIBEOFFICE_IMPLEMENTATION_GUIDE.md)

또 하나의 목표는 **대화형 지시 + 자율 실행**입니다. 지금은 팀장·실행자를 사용자가 직접 고르고 단계별 버튼으로 진행하지만, 목표는 기존 AI 채팅처럼 한 창에서 말하면 오피스가 접수·계획·실행·검증·보고까지 스스로 진행하고 사람은 대화로만 개입하는 것입니다. 파괴적·외부 전송·비용·배포 행동의 명시 승인은 자율성 레벨과 무관하게 유지합니다. 설계안: [reference/legacy/CONVERSATIONAL_AGENT_TARGET.md](reference/legacy/CONVERSATIONAL_AGENT_TARGET.md)

런타임 쪽 남은 경계: 바이너리 `.hwp` 직접 작성 불가(표준 `.hwpx`로 생성·검증), Python 외 언어의 의미 진단은 해당 LSP 설치 시에만 지원.

## 트러블슈팅

| 증상 | 원인·해결 |
|---|---|
| UI에서 실행 버튼이 비활성 | API build ≠ worker build. 런처를 다시 실행해 두 프로세스를 같은 build로 시작 |
| `ripgrep (rg) is required for search_files` | `rg` 설치 후 재실행 (`winget install BurntSushi.ripgrep.MSVC`) |
| 직원이 `blocked`로 멈춤 | 필수 스킬 `SKILL.md` 누락 또는 lock hash 불일치. `scripts/install_skills.py` → `verify_skills.py` |
| 실행 도중 HTTP 428 | TaskContract `ask` 권한 대기. UI 승인 화면에서 허용/거부 |
| Job이 `interrupted` | worker 재시작으로 lease 상실. 재시도하면 성공한 실행은 건너뛰고 이어서 진행 |
| 포트를 못 찾음 | `8100~8199`, `5175~5199` 전체 점유. 다른 프로세스를 정리 후 재실행 |
| 모델 호출이 오래 걸림 | 하드 데드라인은 `AI_OFFICE_MODEL_TIMEOUT_SECONDS`. 대기 중에도 heartbeat로 Job은 살아 있음 |
| 체크포인트 복원 불가 | 활성 Job이 있으면 복원 차단. pause/cancel 후 재시도 |

## 보안

- API key는 OS keyring에만 저장하고 저장소·DB·내보내기 파일에 남기지 않습니다.
- 파일 쓰기와 명령 실행은 TaskContract의 `allowed_paths`·`allowed_commands`·`permission_rules` 안에서만 허용됩니다.
- `git push`, 배포, 외부 전송, 삭제 등 되돌리기 어려운 행동은 명시 권한 없이 실행되지 않습니다.
- 말풍선과 도구 요약에는 프롬프트 원문, 파일 본문, 인증 값을 표시하지 않습니다.
- 웹 검색 스니펫은 근거로 인정하지 않습니다. 조사 완료에는 독립 도메인 원문 2건 이상이 필요합니다.

상세: [SECURITY.md](SECURITY.md)

## 라이선스

이 저장소 전체에 적용되는 라이선스는 아직 선언되지 않았습니다. 외부 스킬과 자산은 각 원저작자의 라이선스를 따릅니다. 배포·상업 이용 전 [NOTICE.md](NOTICE.md)와 [reference/corporate-os/07-SOURCE_LICENSE_MATRIX_v6.2.md](reference/corporate-os/07-SOURCE_LICENSE_MATRIX_v6.2.md)를 검토하세요.
