# 11. Implementation Brief for Codex

## 목표

현재 코드베이스에서 다음 부서형 P0 흐름을 구현한다.

```text
Planning Package
→ Design Package
→ Architecture Package
→ MVP Build
→ QA·Rework
→ H4 Agent-ready Export
```

## 시작 절차

1. 현재 저장소의 스택·라우팅·상태·API·DB·테스트·오피스 UI 조사
2. 기존 기능을 부서별 Capability로 분류
3. `CURRENT_STATE.md`와 `GAP_ANALYSIS.md`
4. 전면 재작성 없이 가장 작은 부서 간 수직 슬라이스 선택
5. 구현 전 성공 조건
6. build·test·Golden Path 검증

## 우선 구현할 수직 슬라이스

### 목표

한 문장 아이디어가 기획부 패키지로 바뀌고, 디자인부가 이를 인계받아 핵심 화면 구조를 만드는 흐름.

### 구현

- Start
- Intent normalization
- Blueprint
- Planning approval
- planning-handoff.json
- Design workspace
- User Flow + Screen Spec 생성
- design-handoff 상태 표시
- artifacts version/stale

### 제외

- 실제 멀티에이전트 병렬 실행
- 전체 MVP 코드 생성
- GitHub push
- 배포
- 스킬 마켓
- 3D 오피스

## 두 번째 수직 슬라이스

```text
Approved Design
→ API/Data contracts
→ Technical Tasks
→ architecture-handoff
```

## 세 번째 수직 슬라이스

```text
Approved Architecture
→ starter/template MVP
→ build
→ PROJECT_STATUS
→ BUILD_REPORT
```

## 네 번째 수직 슬라이스

```text
QA rules
→ finding
→ owner department
→ stale
→ rework
→ H4 export
```

## canonical 상태

```text
project
blueprint
roadmap
artifacts
handoffs
departmentRuns
reviewFindings
currentState
checkpoints
export
```

채팅 history는 상태의 원천이 아니다.

## 추천 화면

1. Start
2. Planning Room
3. Design Studio
4. Architecture Lab
5. Build Floor
6. Review Room
7. Shipping Dock

공통 레이아웃:

- 좌측: phase·department·tasks
- 중앙: 현재 산출물 또는 preview
- 우측: 결정·검수·인계
- 상단: 승인·중단·복구

## 추천 서비스 경계

```text
intentService
planningService
designService
architectureService
buildService
reviewService
handoffService
checkpointService
exportService
```

## 필수 스키마

- project-blueprint
- roadmap
- artifact
- handoff
- review-finding
- current-state
- handoff-readiness

## 검증 우선순위

1. handoff input version
2. output required files
3. artifact stale propagation
4. department gate
5. QA owner routing
6. ZIP/H4 lint
7. Golden Path E2E

## 금지

- 아바타 애니메이션부터 구현
- 부서마다 같은 문서를 독립 재생성
- 승인되지 않은 draft 인계
- QA Finding을 전체 재생성으로 해결
- build 증거 없이 MVP 완료
- Codex에 긴 프롬프트만 제공
- 실제 current state와 계획 혼합

