# 프로젝트 스터디: AI Office (Corporate OS v6.2)

## 한 줄 요약

전문 스킬을 가진 24명의 AI 에이전트가 팀 단위로 실제 로컬 프로젝트를 조사·수정·검증하는 멀티 에이전트 실행 시스템. "채팅으로 역할극"이 아니라, 에이전트가 실제 파일을 건드리고 그 결과를 증거(hash, 검증 명령 종료 코드, 독립 리뷰)로 남겨야만 작업이 완료 처리되도록 설계했다.

## 기본 정보

| 항목 | 내용 |
|---|---|
| 역할 | 1인 개발. 기획, 아키텍처, 백엔드/프론트엔드 구현, 검증, 문서화 전 과정 단독 수행 |
| 기간 | 2026-07-29 ~ 2026-08-06 (약 9일, 커밋 49건) |
| 저장소 규모 | Python(`apps/api`+`scripts`) 약 8,400줄, React/TS(`apps/web`) 약 1,250줄 (직접 `wc -l` 측정) |
| 테스트 | `apps/api/test_*.py` unittest 스위트 + 정적 정합성 검사 스크립트 3종 |

## 왜 만들었나: 풀어야 했던 문제

LLM 멀티 에이전트 데모 대부분은 "채팅창 역할극" 단계에서 멈춘다. 이 프로젝트는 그 다음 단계, 즉 **에이전트가 실제로 파일을 건드리기 시작하는 순간부터 생기는 문제**를 다뤘다.

| 문제 | 해법 |
|---|---|
| 에이전트가 "다 했다"고 말해도 실제로는 안 됐을 때 신뢰 불가 | Task는 실제 파일 hash · 검증 명령 종료 코드 · 독립 리뷰 통과, 3가지가 모두 있어야 `completed`로 전이 |
| worker 프로세스가 죽으면 Job이 영원히 `running`으로 남는 문제 | SQLite 원자적 lease + heartbeat. lease 만료 Job은 재시작 시 자동 `interrupted`, 재시도는 이미 성공한 실행 단계를 건너뜀 |
| 에이전트에게 파일 접근·명령 실행 권한을 어디까지 줄지 | TaskContract가 요청 단위로 `allowed_paths` / `allowed_commands` / `permission_rules` 발급. `ask` 등급은 HTTP 428로 멈추고 사용자 승인 대기 |
| 24명 · 8부서 규모에서 "누가 이 일을 할지" 정적 매핑이 깨지는 문제 | 하드코딩 라우팅 표 없이, 매 요청마다 모델이 부서 경계 정의 + 가용 인력·스킬을 함께 보고 동적 배정 |
| API와 worker가 다른 버전으로 떠 있을 때 생기는 조용한 실패 | `/api/runtime/version`에서 build id·schema version을 대조, 불일치 시 UI 실행 버튼 하드 차단 |

## 아키텍처

```
React + Vite UI (apps/web)
  │ REST + SSE
FastAPI (apps/api/main.py)
  │ Job enqueue / state query
SQLite WAL (data/ai-office.sqlite3)
  │ atomic lease + heartbeat
Worker 프로세스 (apps/api/worker.py, 다중 프로세스 기본값)
  ├─ OpenRouter 모델 호출
  ├─ 워크스페이스 파일 도구 (읽기·정밀 치환·패치·생성)
  ├─ 코드 탐색 (ripgrep, Pyright 진단, 테스트 탐색)
  ├─ 검증 명령 실행 (TaskContract 허용 명령만)
  ├─ 웹 조사 (Brave → SearXNG → Bing RSS)
  ├─ 문서 렌더 (DOCX/PDF/XLSX/PPTX/HWPX)
  └─ 설정된 MCP 도구
```

핵심 설계 원칙 두 가지:

1. **Task 상태와 Job 상태 분리**. Task는 사용자가 이해하는 업무 단계, Job은 실행기 내부 상태. 둘을 섞으면 "재시도"와 "재작업"이 UI에서 구분 안 되는 문제가 생긴다.
2. **증거 기반 완료 판정**. 모델이 자기 작업을 "완료"라고 서술하는 것만으로는 완료 처리하지 않는다. 실제 파일 변경 + 검증 명령 통과 + 독립 리뷰(GUARD/LENS)까지 있어야 한다.

## 업무 흐름 (조직 설계)

8개 부서 × 3명 = 24명 에이전트 조직. 부서 소유 범위는 `registry/department-boundaries.json`에 정의하고 실행·회의 프롬프트에 그대로 주입한다.

| 부서 | 팀장 | 실행자 | 소유 범위 |
|---|---|---|---|
| operations-planning | NAVI | ROUTE, CLOCK | 요청 정규화, 계약, 라우팅, 일정·예산 |
| product-experience | FRAME | FLOW, MOSS | 문제 정의, PRD, 수용 기준, UX/UI 명세 |
| application | BUILD | FRONT, BACK | 기술 설계, 구현, 통합 검토 |
| ai-data | LINK | SIGNAL, EVAL | AI 구조, 검색·데이터 파이프라인, 모델 평가 |
| platform-reliability | SHIP | SRE, COST | 릴리스, CI/CD, 관측성, 비용 |
| quality-security | GUARD | TRACE, SHIELD | 독립 시험, 보안·개인정보, 증거 게이트 |
| growth-marketing | GROW | VOICE, PULSE | 시장 조사, 포지셔닝, 카피, 실험 |
| service-knowledge | LENS | JOURNEY, DOCS | 여정 검토, 문서화 |

요청 → NAVI 정규화 → 사용자 팀장 선택 → 실제 회의(발언 기록 없으면 회의 미완료) → 팀장이 실행자 배정 → 실행 → 부서 초안 저장 → 최종 책임자 FINAL.md 통합 → NAVI가 증거 검토해 완료 판정 → `changes_requested`면 자동 재통합, 이 루프 전체를 구현했다.

## 기술 스택

- **Backend**: Python 3.12, FastAPI, SQLite(WAL), OpenRouter API, ripgrep, Pyright
- **Frontend**: React, Vite, TypeScript, Server-Sent Events
- **인프라**: 다중 worker 프로세스, Git worktree 기반 작업 격리, OS keyring 기반 시크릿 저장

## 이 프로젝트가 의도적으로 안 하는 것

멀티테넌트 SaaS, 자동 배포, 승인 없는 외부 전송·게시, 스킬 자동 다운로드, 무제한 자율 실행. 로컬·단일 사용자 실행 환경으로 범위를 좁혀서, "에이전트가 실제로 안전하게 파일을 건드리게 만드는 문제"에 집중했다.
