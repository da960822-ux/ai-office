# 05. Agent and Department Orchestration

## 원칙

오피스는 아바타 대화 시뮬레이션이 아니라 **부서별 산출물 생산·검토·인계·반송 시스템**이다.

핵심 부서:

1. Planning
2. Design
3. Architecture
4. Build
5. QA
6. Shipping

Orchestrator는 부서 간 상태·버전·승인·비용·복구를 관리한다.

## 부서와 에이전트

### Orchestrator

- workflow state
- 필요한 부서 호출
- 입력 버전 고정
- 승인
- handoff
- stale
- 실패·반송
- 비용·모델 라우팅
- 체크포인트

### Planning Department

내부 역할:

- Product Guide
- Scope Reviewer
- Roadmap Planner

소유:

- Blueprint
- Product Brief
- Scope
- Requirements
- Roadmap
- Decisions

### Design Department

내부 역할:

- UX Designer
- UI System Designer
- Prototype Builder

소유:

- IA
- Flow
- Screen Spec
- Design System
- Component Inventory
- Prototype

### Architecture Department

내부 역할:

- Technical Planner
- API/Data Designer
- Security Reviewer

소유:

- Architecture
- API
- Data Model
- Environment
- Technical Tasks

### Build Department

내부 역할:

- Frontend Builder
- Backend/Integration Builder
- Test Builder

초기에는 실제 별도 에이전트 대신 단일 Build Agent가 순차 수행할 수 있다.

소유:

- source
- Project Status
- Build Report
- implementation evidence

### QA Department

- Product Reviewer
- UX Reviewer
- Technical Reviewer
- Build Verifier

생성 에이전트와 독립된 검토 경로를 사용한다.

### Shipping Department

- AGENTS/CLAUDE 생성
- NEXT_ACTION
- Handoff lint
- secret scan
- ZIP/Git export

## 인계 계약

모든 인계는 다음을 갖는다.

- from/to
- input versions
- required outputs
- constraints
- acceptance criteria
- open decisions
- approval
- status

상세는 `05A_DEPARTMENT_HANDOFF_CONTRACTS.md`.

## 상태 머신

```text
DRAFT
→ PLANNING
→ PLANNING_REVIEW
→ PLANNING_APPROVED
→ DESIGN
→ DESIGN_REVIEW
→ DESIGN_APPROVED
→ ARCHITECTURE
→ ARCHITECTURE_REVIEW
→ BUILD
→ BUILD_VERIFICATION
→ QA
→ REWORK_REQUIRED 또는 SHIPPING_READY
→ SHIPPING
→ EXPORTED
→ CODEX_CLAUDE_REFINEMENT
```

예외:

- NEEDS_USER_DECISION
- HANDOFF_REJECTED
- RETRYABLE_FAILURE
- STRUCTURAL_REPLAN
- STALE_ARTIFACTS
- ROLLBACK_REQUIRED

## 승인 경계

기본 사용자 승인:

1. Planning Approved
2. Design Approved
3. Shipping Approved

안전 자동:

- 형식 정리
- ID 연결
- stale 처리
- 문서 동기화
- 테스트 재시도

승인 필요:

- Must·Out 변경
- 사용자 흐름 변경
- 기술 스택 변경
- 파괴적 작업
- 비용·외부 전송·배포

## 병렬화

가능:

- 기획부 안의 사용자 조사와 경쟁 분석
- 디자인 토큰과 화면 카피
- 독립 화면 명세
- 프론트·백엔드 작업 초안

불가:

- Planning 승인 전 Design 확정
- Screen/Data 요구 전 API 확정
- Architecture Gate 전 Build
- Blocker가 남은 상태의 Shipping

## 반송

QA가 Finding을 만들면:

```text
Finding
→ Owner Department
→ Affected artifacts stale
→ Minimum rework
→ Local Gate
→ Downstream alignment
→ QA rerun
```

같은 Finding이 두 번 반복되면 자동 루프를 중단하고 상위 충돌을 조사한다.

## 오피스 UI

사용자에게 보여줄 것:

- 현재 부서
- 입력 산출물
- 생성 중 산출물
- 완료 조건
- 차단 이유
- 검수 결과
- 다음 인계

보여주지 않을 것:

- 내부 chain of thought
- 의미 없는 장시간 회의
- 에이전트 수를 품질 지표로 표현

