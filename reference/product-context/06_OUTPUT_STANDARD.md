# 06. Output Artifact Standard

## 원칙

산출물은 보고서가 아니라 다음 코딩 에이전트가 실행할 계약이다. 각 산출물은 버전, 상태, 소유 역할, 입력 버전, 의존 산출물을 가진다.

```yaml
artifact_id: requirements
version: 3
status: approved
source_blueprint_version: 5
owner: product_guide
depends_on:
  - product-brief@3
  - scope@4
```

## 필수 파일

### PRD.md

- 기본 모드의 유일한 사람용 기획서. `PRODUCT_BRIEF`, `MVP_SCOPE`, `REQUIREMENTS`, `DECISIONS`, OKR, 위험 목록을 별도 문서로 중복 생성하지 않는다.
- 문제·대상 사용자·가치 제안·성공 장면
- Objective와 KR별 baseline·목표값·측정 source·판정 시점
- Must/Should/Later/Explicitly Out과 판단 근거
- Requirement ID별 사용자 가치·동작·전제 조건·수용 기준·예외·우선순위
- 주요 사용자 흐름 링크, 비기능 요구사항, 결정·가정·보류, 위험·완화책
- 개발 AI가 참조하는 단일 진입 문서다. 기계 검증용 원본은 `project-blueprint.json`과 register JSON이며, PRD의 ID·값과 불일치하면 오류다.

### 선택 파생 문서

- 외부 고객, 대형 팀, 규제/감사 요구가 있을 때만 PRD에서 `PRODUCT_BRIEF.md`, `MVP_SCOPE.md`, `REQUIREMENTS.md`, `DECISIONS.md`, `OKR.md`, `RISK_REGISTER.md`를 생성한다.
- 파생 문서는 편집 원본이 아니다. 수정은 PRD 또는 구조화 JSON에서만 하고 재생성한다.

### USER_FLOWS.md

- 주요 진입점
- Happy Path
- 대체 흐름
- 오류 흐름
- 종료 상태

### SCREEN_SPEC.md

화면별 목적, 행동, 컴포넌트, 데이터, 이벤트, loading/empty/error, 반응형, 접근성.

### 파생 REQUIREMENTS.md

요구사항별 ID, 사용자 가치, 동작, 전제조건, 수용 기준, 관련 화면, 우선순위, 제외 조건.

### DESIGN.md

정보 구조, 디자인 원칙, 토큰, 컴포넌트, 상태 패턴, 반응형 기준.

### ARCHITECTURE.md

현재 스택, 구조, 경계, 데이터 흐름, 외부 서비스, 실패 처리, 보안 기본, 비기능 요구.

### API_CONTRACT.md

method/path, 목적, 인증, request, response, error, 화면 사용처.

### DATA_MODEL.md

entity, field, 관계, 필수 여부, 샘플 데이터.

### TASKS.md

ID, 사용자 가치, owner, dependencies, files/modules, done criteria, verification, rollback.

### TEST_PLAN.md

핵심 E2E, 단위·통합, 상태 테스트, 수동 확인, 시연 체크리스트.

### 파생 DECISIONS.md

결정, 이유, 대안, 영향, 되돌릴 조건.

### AGENTS.md

목적, 우선순위, 코딩 원칙, 실행 명령, 검증, 금지, 보고 형식.

## 실행 가능한 프로토타입 기준

- 설치·실행 방법 존재
- 핵심 라우트 열림
- 주요 흐름 클릭 가능
- 명시적 mock 또는 데이터 구조
- CTA가 동작하거나 disabled 이유
- loading/empty/error 예시
- 콘솔 치명 오류 없음
- 기본 반응형
- 공식 빌드 성공

금지:

- 모든 버튼을 alert로 연결
- 아무 동작 없는 CTA
- 한 파일에 전체 앱
- 비밀키 포함
- 존재하지 않는 API 임의 가정
- 문서와 다른 기능 추가
- 빌드 없이 완성 표시

## 내보내기 구조

```text
project/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── NEXT_ACTION.md
├── docs/
│   ├── PRD.md
│   ├── USER_FLOWS.md
│   ├── SCREEN_SPEC.md
│   ├── DESIGN.md
│   ├── ARCHITECTURE.md
│   ├── API_CONTRACT.md
│   ├── DATA_MODEL.md
│   ├── TASKS.md
│   ├── TEST_PLAN.md
│   └── TRACEABILITY.md
└── .vibeoffice/
    ├── project-blueprint.json
    ├── decision-register.json
    ├── risk-register.json
    ├── artifact-index.json
    ├── review-findings.json
    └── export-manifest.json
```

## NEXT_ACTION.md 필수

```md
# 다음 작업

## 목표
로그인 없이 핵심 데모 흐름을 실행할 첫 수직 슬라이스를 완성한다.

## 구현
- 홈에서 데모 시작
- 입력 폼
- 더미 결과
- 결과 화면

## 제외
- 실제 AI API
- 사용자 계정
- DB 저장

## 완료
- 공식 build 통과
- 핵심 흐름 검증
- 로딩·오류 상태 확인
```

초보 사용자는 내보낸 뒤 다시 무엇을 말해야 할지 고민하면 안 된다.

## 일관성 규칙

- Must 기능은 요구사항·화면·작업에 연결된다.
- Out 기능은 작업 목록에 없다.
- API 필드와 데이터 모델이 일치한다.
- 화면 데이터는 API 또는 mock source가 있다.
- 작업 완료 기준은 테스트와 연결된다.
- 결정 변경 시 관련 산출물을 stale 처리한다.

## 부서별 산출물 패키지

### Planning Package

```text
planning/
├── PRD.md
├── project-blueprint.json
├── decision-register.json
├── risk-register.json
├── traceability-map.json
└── planning-handoff.json
```

### Design Package

```text
design/
├── INFORMATION_ARCHITECTURE.md
├── USER_FLOWS.md
├── SCREEN_SPEC.md
├── DESIGN_SYSTEM.md
├── COMPONENT_INVENTORY.md
├── design-tokens.json
├── prototype/
└── design-handoff.json
```

### Architecture Package

```text
architecture/
├── ARCHITECTURE.md
├── TECH_STACK.md
├── API_CONTRACT.yaml
├── DATA_MODEL.md
├── ERD.md
├── SECURITY_BASELINE.md
├── ENVIRONMENT.md
├── TECHNICAL_TASKS.md
└── architecture-handoff.json
```

### Build Package

```text
build/
├── source/
├── PROJECT_STATUS.md
├── BUILD_REPORT.md
├── IMPLEMENTATION_NOTES.md
├── test-results/
├── evidence/
├── current-state.json
└── build-handoff.json
```

### QA Package

```text
qa/
├── REVIEW_FINDINGS.md
├── ACCEPTANCE_REPORT.md
├── BUILD_EVIDENCE.md
├── review-findings.json
└── handoff-readiness.json
```

## 최종 Agent-ready 폴더

```text
project/
├── AGENTS.md
├── CLAUDE.md
├── NEXT_ACTION.md
├── PROJECT_STATUS.md
├── README.md
├── .env.example
├── docs/
├── .vibeoffice/
├── prototype/ 또는 실제 source/
└── evidence/
```

내부 부서 파일은 필요에 따라 `docs/internal/` 또는 `.vibeoffice/handoffs/`에 보존한다.

## 출고 품질 기준

- H3: 바로 개발 시작 가능
- H4: 실행 시안·mock·traceability·test scaffold
- H5: build·smoke/E2E·evidence·checkpoint

Standard 모드는 H4를 목표로 한다.
