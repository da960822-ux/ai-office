# 06A. Codex·Claude Code 인계 준비도 표준

## 1. 목표

프로젝트 폴더를 코딩 에이전트에 넣었을 때 다음 질문을 다시 받지 않게 한다.

- 무엇을 만드는가?
- 누가 쓰는가?
- MVP가 무엇인가?
- 현재 무엇이 작동하는가?
- 무엇부터 구현하는가?
- 어느 파일과 영역을 수정하는가?
- 어떤 명령으로 검증하는가?
- 무엇을 하지 말아야 하는가?

## 2. Handoff Ready 7조건

1. **Goal Ready** — 사용자 가치와 성공 장면
2. **Scope Ready** — Must·Later·Out
3. **Design Ready** — 흐름·화면·상태
4. **Technical Ready** — 스택·경계·데이터 계약
5. **Task Ready** — 첫 수직 슬라이스·의존성
6. **Verification Ready** — 실행·빌드·테스트·완료 기준
7. **Context Ready** — AGENTS/CLAUDE/결정 기록 최신

## 3. 루트 필수 파일

### AGENTS.md

- 제품 목적
- 현재 phase
- 우선순위
- 저장소 구조
- 코드 규칙
- 실행·테스트 명령
- 위험 명령 승인
- 금지 범위
- 완료 보고 형식

### CLAUDE.md

권장 import:

```md
@AGENTS.md
@NEXT_ACTION.md
@PROJECT_STATUS.md
@docs/PRODUCT_BRIEF.md
@docs/MVP_SCOPE.md
@docs/REQUIREMENTS.md
@docs/TASKS.md
@docs/TEST_PLAN.md
@docs/DECISIONS.md
```

### NEXT_ACTION.md

한 번에 수행할 첫 수직 슬라이스.

- 사용자 가치
- 현재 상태
- 구현 범위
- 제외 범위
- 예상 변경 영역
- 완료 기준
- 검증 명령
- rollback 기준
- 작업 후 갱신 문서

### PROJECT_STATUS.md

계획이 아니라 현재 사실.

- Working
- Partial
- Not implemented
- Known issues
- Last verification
- Last successful commit
- Blockers

## 4. docs 필수 파일

```text
PRODUCT_BRIEF.md
MVP_SCOPE.md
REQUIREMENTS.md
USER_FLOWS.md
SCREEN_SPEC.md
DESIGN_SYSTEM.md
ARCHITECTURE.md
API_CONTRACT.yaml
DATA_MODEL.md
TASKS.md
TEST_PLAN.md
DECISIONS.md
TRACEABILITY.md
```

## 5. 기계 판독 파일

```text
.vibeoffice/
├── project-blueprint.json
├── roadmap.json
├── artifact-index.json
├── traceability-map.json
├── current-state.json
├── review-findings.json
├── export-manifest.json
└── handoff-readiness.json
```

## 6. 첫 실행 프로토콜

```text
1. AGENTS.md 또는 CLAUDE.md 읽기
2. PROJECT_STATUS.md 확인
3. 저장소 구조·실행 명령을 실제로 검증
4. 문서와 코드의 차이를 기록
5. NEXT_ACTION의 성공 조건 확인
6. 체크포인트 생성
7. 가장 작은 수직 슬라이스 구현
8. build·test·핵심 흐름 검증
9. PROJECT_STATUS·TRACEABILITY·DECISIONS 갱신
10. 증거와 남은 위험 보고
```

## 7. 내보내기 자동 검사

### File

- 필수 파일
- 빈 섹션
- 깨진 import
- secret
- 로컬 절대경로

### Consistency

- 프로젝트명
- Must 기능
- Out 기능이 Tasks에 없는지
- Requirement→Screen→Task→Test
- API→Data Model
- NEXT_ACTION→현재 phase
- PROJECT_STATUS→최근 검증

### Execution

- install
- dev
- build
- test
- `.env.example`
- 재현 가능한 첫 실행

## 8. 품질 등급

| 등급 | 상태 |
|---|---|
| H0 | 대화·메모만 존재 |
| H1 | Brief·roadmap 존재 |
| H2 | 요구사항·흐름·작업 존재 |
| H3 | AGENTS/CLAUDE/NEXT_ACTION/검증 명령으로 개발 시작 가능 |
| H4 | 실행 시안·mock·traceability·test scaffold 포함 |
| H5 | build 성공·핵심 smoke/E2E·증거·체크포인트 포함 |

기본 내보내기 목표는 **H4**, 고품질 모드는 **H5**다.

## 9. 사용자 화면

```text
Codex 준비도: 92%

완료
✓ 제품 범위
✓ 핵심 화면
✓ 개발 작업
✓ 실행 명령
✓ 테스트 기준
✓ 프로젝트 지침

확인 필요
! 실제 AI API 키 연결 필요
! 로그인은 MVP 이후로 제외

[Codex용 폴더]
[Claude Code용 폴더]
[일반 ZIP]
```
