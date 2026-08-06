# AI Office · Corporate OS v6.2

> **AI가 “완료했습니다”라고 말하는 것과, 실제로 일을 끝내는 것은 다릅니다.**<br />
> AI Office는 24명의 역할 기반 AI 직원이 로컬 프로젝트를 조사·수정·검증하고, 파일 hash·검증 명령·독립 리뷰가 모두 남아야 완료되는 멀티 에이전트 실행 시스템입니다.

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19.2-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-7.0-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/tests-99%20passing-brightgreen)](#검증)
[![License](https://img.shields.io/badge/license-All%20Rights%20Reserved-lightgrey)](LICENSE)

<p align="center">
  <a href="#3분-안에-실행하기"><strong>직접 실행하기</strong></a> ·
  <a href="#어떻게-동작하나"><strong>동작 원리</strong></a> ·
  <a href="#엔지니어링-하이라이트"><strong>기술적 도전</strong></a> ·
  <a href="#프로젝트를-평가하고-있다면"><strong>포트폴리오</strong></a>
</p>

![AI Office 공간 컨셉](apps/web/public/assets/ai-office-zones-v2.png)

## 한눈에 보기

| 구분 | 내용 |
|---|---|
| 핵심 문제 | 모델의 자기 보고를 신뢰하지 않고, 실행 증거로 완료를 판정 |
| 실행 환경 | Windows 10/11, 로컬 단일 사용자 |
| 조직 모델 | 8개 부서, 24명 역할 기반 AI 직원, 동적 라우팅 |
| 실행 엔진 | FastAPI + SQLite WAL + 다중 worker process |
| 관제 UI | React + TypeScript + Vite, REST + SSE 실시간 이벤트 |
| 안전장치 | TaskContract 기반 `allow` / `ask` / `deny`, OS keyring, 격리 workspace |
| 복구 전략 | lease, heartbeat, checkpoint, retry, 성공 단계 재사용 |
| 검증 상태 | Backend 88건 + Frontend 11건 통과, production build 성공 |

역할극 채팅이 아닙니다. AI 직원은 허용된 workspace에서 파일을 읽고 수정하며, 명령을 실행하고, 결과를 검토 가능한 산출물과 Evidence로 남깁니다. UI는 실제 `job_events`를 받아 회의·작업·리뷰 상태를 표시합니다.

## 왜 만들었나

LLM 멀티 에이전트 데모는 대화가 끝나는 순간 그럴듯해 보입니다. 어려운 문제는 에이전트가 실제 프로젝트를 건드리기 시작할 때 생깁니다.

| 현실의 문제 | AI Office의 해법 |
|---|---|
| 모델이 “완료”라고 했지만 파일은 바뀌지 않음 | 실제 산출물 hash, 성공한 검증 명령, 독립 리뷰가 모두 있어야 `completed` 전이 |
| worker가 죽은 뒤 Job이 계속 `running`으로 남음 | SQLite 원자적 lease + heartbeat, 재시작 시 `interrupted` 복구 |
| 에이전트가 어디까지 파일·명령에 접근해도 되는지 불명확 | 요청별 TaskContract가 `allowed_paths`, `allowed_commands`, `permission_rules` 발급 |
| 위험한 작업이 승인 없이 실행됨 | `ask` 권한은 HTTP 428로 실행을 멈추고 사용자 결정 대기 |
| 24명 조직의 담당자 매핑이 정적 표에 갇힘 | 부서 경계·가용 인력·스킬을 기준으로 요청마다 동적 배정 |
| API와 worker 버전이 달라 조용히 실패 | build id와 schema version 불일치 시 UI 실행 차단 |
| 재시도할 때 성공한 작업까지 처음부터 반복 | 성공한 `agent_run`을 재사용하고 실패 단계부터 재개 |

이 저장소가 주장하는 강점은 코드와 테스트로 확인 가능한 동작입니다. MetaGPT·ChatDev·Kiro 등 유사 도구와 실패율·완료율을 정량 비교한 결과는 아직 없으며, 검증하지 않은 우위를 주장하지 않습니다.

## 3분 안에 실행하기

### 1. 준비물

| 항목 | 요구사항 |
|---|---|
| OS | Windows 10/11 |
| Python | 3.12 이상 |
| Node.js | 20.19 이상 또는 22.12 이상 + npm |
| ripgrep | `rg` 명령 사용 가능 상태 |
| 모델 API | OpenRouter API key |
| Git | 선택. Git 프로젝트에서 branch/worktree 격리에 사용 |

### 2. 설치

PowerShell에서 저장소 루트로 이동한 뒤 한 번만 실행합니다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

스크립트는 `.venv` 생성, Python/npm 의존성 설치, 직원별 스킬 설치·검증, 인덱스 생성을 수행합니다.

수동 설치가 필요하면:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
cd apps\web
npm install
cd ..\..

.\.venv\Scripts\python.exe scripts\install_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\verify_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\render_skill_indexes.py
```

인터넷이 차단된 환경은 [수동 스킬 설치 가이드](manual-drop/README.md)를 따릅니다.

### 3. 실행

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-ai-office.ps1
```

또는 `AI_Office_실행.cmd`를 실행합니다.

런처가 다음 작업을 자동 처리합니다.

1. 이 저장소에서 실행한 기존 API·worker·Vite 프로세스 정리
2. 사용 가능한 API/UI 포트 선택
3. FastAPI, worker, Vite 동시 실행
4. API build와 worker build 일치 확인
5. `.ai-office/runtime.json`에 실제 주소 기록
6. 브라우저에서 UI 열기

### 4. 첫 업무 맡기기

1. 설정 화면에서 OpenRouter API key를 저장합니다. key는 저장소나 SQLite가 아닌 OS keyring에 저장됩니다.
2. 작업할 로컬 프로젝트를 등록합니다.
3. 자연어로 업무를 요청합니다. 예: `로그인 실패 원인을 조사하고 회귀 테스트와 함께 수정해줘.`
4. NAVI가 제안한 팀장과 TaskContract 범위를 확인합니다.
5. 회의·실행·리뷰 이벤트와 Evidence를 UI에서 확인합니다.

## 어떻게 동작하나

```text
사용자 요청
  │
  ▼
NAVI · 요청 정규화 / TaskContract / 팀장 후보 제안
  │
  ▼
팀 회의 · 실제 발언과 action item 기록
  │
  ▼
실행 계획 · phase dependency / 직원 배정 / 격리 workspace
  │
  ▼
Worker pool · 모델 호출 / 파일 도구 / 검색 / 검증 명령
  │
  ▼
부서 산출물 · FINAL.md · hash Evidence
  │
  ▼
GUARD / LENS 독립 리뷰
  │
  ├─ changes_requested → 수정·재검증
  └─ pass + Evidence 충족 → completed
```

### 런타임 아키텍처

```text
React + Vite UI (apps/web)
  │ REST + Server-Sent Events
FastAPI (apps/api)
  │ Job enqueue / state query
SQLite WAL (data/ai-office.sqlite3)
  │ atomic lease + heartbeat
Worker processes (apps/api/worker.py)
  ├─ OpenRouter model calls
  ├─ workspace file tools
  ├─ ripgrep / Pyright / test discovery
  ├─ verification commands
  ├─ web research
  ├─ DOCX / PDF / XLSX / PPTX / HWPX rendering
  └─ configured MCP tools
```

Task는 사용자가 이해하는 업무 상태, Job은 실행기의 처리 상태입니다. 둘을 분리해 “업무 재작업”과 “실행 실패 재시도”를 구분합니다. 상세 설계는 [ARCHITECTURE.md](docs/ARCHITECTURE.md), 내구성 규칙은 [RUNTIME_HARDENING.md](docs/RUNTIME_HARDENING.md)에서 확인할 수 있습니다.

## 8개 부서, 24명의 AI 직원

각 직원은 persona, 권한, 필수 스킬, 평가 기준을 가집니다. 24개의 독립 상시 프로세스가 아니라, 요청에 따라 worker가 호출하는 역할 기반 실행자입니다.

| 부서 | 팀장 | 실행자 | 책임 범위 |
|---|---|---|---|
| Operations & Planning | NAVI | ROUTE, CLOCK | 요청 정규화, 계약, 라우팅, 일정·예산 |
| Product Experience | FRAME | FLOW, MOSS | 문제 정의, PRD, 수용 기준, UX/UI |
| Application | BUILD | FRONT, BACK | 기술 설계, 프론트엔드·백엔드, 통합 |
| AI & Data | LINK | SIGNAL, EVAL | AI 구조, 검색·데이터 파이프라인, 평가 |
| Platform & Reliability | SHIP | SRE, COST | 릴리스, CI/CD, 관측성, 비용 |
| Quality & Security | GUARD | TRACE, SHIELD | 독립 시험, 보안·개인정보, Evidence gate |
| Growth & Marketing | GROW | VOICE, PULSE | 시장·고객 조사, 포지셔닝, 카피, 실험 |
| Service & Knowledge | LENS | JOURNEY, DOCS | 사용자 여정, 문서화, 지식 패키지 |

정적 업무 유형표에 사람을 고정하지 않습니다. `registry/department-boundaries.json`의 소유권과 `registry/employees.yaml`의 인력·스킬 정보를 바탕으로 매 요청의 팀을 구성합니다. `registry/task-profiles.json`이 비어 있는 상태도 검증기로 강제합니다.

## 엔지니어링 하이라이트

### 1. Evidence-backed completion

모델의 자연어 응답은 완료 증거가 아닙니다. 구현·릴리스 업무는 다음 조건을 모두 만족해야 합니다.

- 실제 산출물과 SHA-256 hash
- 실행된 검증 명령과 성공 종료 코드
- 현재 실패 Evidence 없음
- GUARD/LENS 독립 리뷰 통과
- 필요한 사용자 승인 완료
- 의존 phase 완료

### 2. Durable worker runtime

- SQLite WAL + busy timeout
- Job lease와 heartbeat
- pause / resume / cancel / retry safe point
- worker 재시작 시 실행 중 Job의 `interrupted` 정규화
- 성공한 단계 재사용
- checkpoint 복원 후 이후 Evidence의 `stale` 처리
- 모델 호출 hard deadline과 최대 tool round

### 3. Capability security

- TaskContract 단위 `allowed_paths` / `allowed_commands`
- 도구·대상 패턴별 `allow` / `ask` / `deny`
- 승인 필요 작업은 HTTP 428로 중단
- API key를 OS keyring에 저장
- `git push`, 배포, 외부 전송, 삭제 등 고위험 행동 제한
- 이벤트 UI에 prompt 원문·파일 본문·인증 값 미노출

### 4. 격리된 협업과 독립 리뷰

Git 프로젝트는 직원별 branch/worktree에서 작업합니다. 변경은 명시적 commit 뒤 GUARD/LENS가 diff를 독립 검토합니다. 통과한 변경만 직렬 `git cherry-pick`하며, 충돌은 자동 덮어쓰기 없이 완료를 차단합니다.

### 5. 조사와 문서도 검증 대상

- 조사 완료에는 서로 다른 domain의 원문 2건 이상 필요
- 검색 snippet은 최종 근거로 인정하지 않음
- DOCX/PDF/XLSX/PPTX/HWPX 생성 후 재파싱
- 렌더 결과 hash와 manifest 기록
- 채팅 답변만으로 산출물 완료 처리하지 않음

## 기술 스택

| Layer | Technology | 선택 이유 |
|---|---|---|
| Frontend | React 19, TypeScript, Vite | 빠른 로컬 개발, typed UI state |
| Realtime | Server-Sent Events | 단방향 실행 이벤트 스트리밍에 맞는 단순한 연결 |
| API | FastAPI, Pydantic | async API와 명시적 request contract |
| Persistence | SQLite WAL | 로컬 단일 사용자 환경에서 transaction·복구·감사 기록 확보 |
| Worker | Python multiprocessing | API와 모델·도구 실행 분리, 기본 동시성 4 |
| Model | OpenRouter via OpenAI SDK | 역할별 모델 라우팅과 교체 가능성 |
| Code tools | ripgrep, Jedi, Pyright | 빠른 탐색, symbol/reference, 선택적 정적 진단 |
| Documents | python-docx, ReportLab, openpyxl, python-pptx, pypdf | 비즈니스 산출물 생성과 재검증 |
| Isolation | Git branch/worktree | 직원별 변경 격리와 review gate |
| Secrets | keyring | key를 저장소·DB와 분리 |

## 프로젝트 구조

```text
apps/api/        FastAPI, SQLite schema, worker, agent tools, renderer
apps/web/        React + Vite + TypeScript 관제 UI
employees/       24명 persona, 권한, 평가 기준, 역할별 스킬
skills/          공용 전문 스킬 pool
registry/        직원·스킬·모델 binding, 부서 경계, 산출물 기준
runtimes/        PLANNER, BUILDER, REVIEWER 등 공통 runtime 지침
constitution/    조직 운영 원칙과 토큰·진단 정책
scripts/         설치, 실행, 검증, 감사, 인덱스 생성
docs/            현재 아키텍처와 개발 문서
reference/       원본 명세, legacy 문서, 보관 산출물
third_party/     외부 자산·스킬 라이선스 고지
```

실행 데이터는 Git에서 제외됩니다.

| 경로 | 내용 |
|---|---|
| `data/ai-office.sqlite3` | Task, Job, event, Evidence, review, usage |
| `data/workspaces/WS-*` | Task별 격리 workspace |
| `<workspace>/AI_OFFICE_OUTPUTS/<TASK-ID>/` | 부서 초안, `FINAL.md`, 렌더 산출물 |
| `.ai-office/` | runtime 주소, 모델 설정, 사용자 inbox |
| `logs/`, `.cache/` | 로그와 임시 데이터 |

## 검증

2026-08-06 저장소 상태에서 직접 실행한 결과입니다.

| 검증 | 결과 |
|---|---|
| Python unittest | **88/88 passed** |
| Vitest | **11/11 passed** |
| TypeScript + Vite production build | **passed** |
| Routing consistency | **24 employees · 8 departments · 0 static profiles · 16 standards** |
| Skill/package audit | **passed** |

```powershell
# Backend
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py"

# Registry, skill, package consistency
.\.venv\Scripts\python.exe scripts\verify_routing.py
.\.venv\Scripts\python.exe scripts\verify_skills.py --employee ALL
.\.venv\Scripts\python.exe scripts\audit_package.py

# Frontend
cd apps\web
npm.cmd test -- --run
npm.cmd run build
```

이 테스트 스위트는 runtime 배관과 회귀를 검증합니다. 모델 응답은 mock하므로 실제 산출물 품질을 보증하지 않습니다. 실제 품질 평가는 실 API 실행과 사람 또는 별도 모델의 eval이 필요합니다.

## 프로젝트를 평가하고 있다면

이 프로젝트는 **1인 개발**로 기획, 제품 범위 설정, 아키텍처, 백엔드, 프론트엔드, 테스트, 운영 문서까지 수행했습니다. 아래 문서는 코드만으로 드러나기 어려운 판단 과정과 문제 해결 역량을 정리합니다.

| 보고 싶은 역량 | 문서 |
|---|---|
| 전체 문제 정의와 시스템 설계 | [프로젝트 스터디](docs/portfolio/01_PROJECT_STUDY.md) |
| 실제 장애의 원인 분석과 재발 방지 | [트러블슈팅 사례](docs/portfolio/02_TROUBLESHOOTING.md) |
| PM 관점의 우선순위·트레이드오프 | [PM 케이스 스터디](docs/portfolio/03_PM_CASE_STUDY.md) |
| 한계 인식과 다음 개선 방향 | [회고](docs/portfolio/04_RETROSPECTIVE.md) |
| 이력서에 바로 쓰는 성과 요약 | [이력서 불릿](docs/portfolio/05_RESUME_BULLETS.md) |
| 지원 동기와 프로젝트 서사 | [자기소개서 내러티브](docs/portfolio/06_COVER_LETTER_NARRATIVE.md) |
| 직무 역량 연결 | [NCS 역량 매핑](docs/portfolio/07_NCS_COMPETENCY_MAP.md) |

### Snapshot

- 개발 기간: 2026-07-29 ~ 2026-08-06
- Git commits: 49
- Python: 41 files, 약 8.6K lines (`apps/api`, `scripts`)
- Frontend: 29 TS/TSX/CSS files, 약 1.8K lines (`apps/web/src`)
- 자동 테스트: 99건
- 조직 정의: 8개 부서, 24명 직원

숫자보다 중요한 결과는 “모델을 얼마나 많이 호출했는가”가 아닙니다. **실패할 수 있는 AI 실행을 어떻게 제한하고, 복구하고, 증명 가능한 상태로 만드는가**를 제품과 코드로 끝까지 밀어붙인 프로젝트입니다.

## API 요약

실제 API 주소는 `.ai-office/runtime.json`의 `api_url`에서 확인합니다.

| 영역 | 대표 endpoint |
|---|---|
| 상태 | `GET /api/health`, `GET /api/runtime/version`, `GET /api/usage/summary` |
| 실시간 이벤트 | `GET /api/tasks/{id}/events/stream` |
| 프로젝트 | `GET/POST /api/projects`, `POST /api/projects/pick` |
| Task | `POST /api/tasks`, `GET /api/tasks/{id}`, `POST /api/tasks/{id}/contract` |
| Job | `POST /api/tasks/{id}/jobs/{plan\|meeting\|execute\|review}` |
| 제어 | `POST /api/tasks/{id}/{pause\|resume\|cancel\|steer\|retry}` |
| 배정 | `POST /api/tasks/{id}/{select-leads\|select-workers\|direct-dispatch}` |
| 리뷰 | `POST /api/tasks/{id}/reviews`, `POST /api/tasks/{id}/approval` |
| 권한 | `POST /api/tasks/{id}/permissions/{requestId}` |
| 복구 | `POST /api/tasks/{id}/checkpoints/{checkpointId}/restore` |
| 설정 | `GET/POST /api/settings/model`, `GET/POST /api/settings/mcp` |

## 범위와 로드맵

현재 목표는 로컬에서 안전하게 실행되는 범용 AI 회사 runtime입니다. 다음 범위는 의도적으로 제외하거나 승인 뒤로 미뤘습니다.

- 멀티테넌트 SaaS
- 운영 환경 자동 배포
- 승인 없는 외부 전송·게시
- 무제한 자율 실행
- 24개의 독립 상시 에이전트 process
- 바이너리 `.hwp` 직접 작성 (`.hwpx` 생성·검증은 지원)

다음 제품 목표는 초보 사용자의 아이디어를 **기획 → 디자인 → 기술 설계 → 개발 → QA → 출고** 순서로 처리해 다른 coding agent가 이어받을 수 있는 프로젝트 폴더를 만드는 것입니다. 이후 한 대화창에서 접수·계획·실행·검증을 지시하는 대화형 계층을 연결합니다. 파괴적 행동, 외부 전송, 비용 발생, 배포는 자율성 수준과 무관하게 명시 승인을 유지합니다.

- [현재 runtime 로드맵](docs/RUNTIME_ROADMAP.md)
- [제품 목표 명세](reference/product-context/)
- [구현 가이드](reference/legacy/VIBEOFFICE_IMPLEMENTATION_GUIDE.md)
- [대화형 지시 목표](reference/legacy/CONVERSATIONAL_AGENT_TARGET.md)

## 문서

- [문서 지도](docs/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Durable Runtime](docs/RUNTIME_HARDENING.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Third-party Notice](NOTICE.md)

## 보안

현재 로컬 단일 사용자 실행을 전제로 합니다. API와 Vite dev server를 외부 네트워크에 공개하는 배포는 지원하지 않습니다. 취약점 제보에 API key, 로컬 경로, 사용자 문서, prompt를 첨부하지 마세요. 자세한 내용은 [SECURITY.md](SECURITY.md)를 확인하세요.

## 라이선스

저장소 원본 코드는 현재 **All Rights Reserved**입니다. 사용·복사·수정·배포 권한이 자동으로 부여되지 않습니다. 외부 스킬과 자산은 각 원저작자의 라이선스를 따릅니다.

- [LICENSE](LICENSE)
- [NOTICE.md](NOTICE.md)
- [Source License Matrix](reference/corporate-os/07-SOURCE_LICENSE_MATRIX_v6.2.md)

---

<p align="center">
  <strong>말이 아닌 실행, 실행만이 아닌 증거.</strong><br />
  AI Office · Corporate OS v6.2
</p>
