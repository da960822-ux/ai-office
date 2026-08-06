# 09A. 산출물 품질 게이트와 추적성

> **상태**: 이 문서는 목표 스펙이다. 원래 구현체(`vibeoffice/`)는 삭제됐고, `apps/api`가 다른 메커니즘으로 점진적으로 재구현 중이다(예: 부서 stage 게이트, 2026-08-06). 이 문서의 규칙이 전부 현재 코드에 집행되는 건 아니다 — 특히 이 파일이 서술하는 Gate/handoff 세부 로직은 아직 미구현이다.

## 1. 기준

산출물 수가 아니라 **서로 맞물려 실제 구현과 검증으로 이어지는지**를 평가한다.

- 계획 기준: `project-blueprint.json`
- 실제 상태 기준: `current-state.json`
- 두 상태의 차이: drift

## 2. Must 기능 추적 체인

```text
GOAL
→ FEATURE
→ REQUIREMENT
→ FLOW
→ SCREEN
→ DATA/API
→ TASK
→ TEST
→ EVIDENCE
```

예:

```text
GOAL-01: 초보자가 복잡한 프롬프트 없이 시작
F-001: 짧은 아이디어 입력
REQ-001: 30자 입력에서도 블루프린트 생성
FLOW-001: Start → Intake → Blueprint
SCR-001: Start
API-001: POST /projects/:id/intake
TASK-001: 입력 UI
TASK-002: 정규화 서비스
TEST-E2E-001: Golden Path
EVIDENCE-001: test log + screenshot
```

## 3. 단계별 Gate

### Gate A — Problem

- 대상 사용자
- 행동·상황으로 표현된 문제
- 관찰 가능한 성공 장면
- 단순 기능 목록이 아님

### Gate B — Scope

- Must 3~5개
- Later와 Out
- 팀·기간·숙련도 반영
- 각 Must가 성공 장면과 연결
- 인증·AI·파일·실시간·결제 동시 포함 경고

### Gate C — UX

- 각 Must가 흐름에 존재
- dead-end 없음
- 주요 CTA 동작
- loading·empty·error
- 모바일 핵심 흐름
- 접근성 기본

### Gate D — Technical

- 화면 데이터 source
- API·Data Model 일치
- 인증 필요성 일치
- 외부 AI/API 실패 처리
- secret 처리
- 지원 스택 내 구현 가능

### Gate E — Task

- 한 에이전트 세션에 적절한 크기
- 의존성
- 검증 가능한 done criteria
- 예상 변경 영역
- Out 작업 없음

### Gate F — Build

- install/dev/build/test
- 공식 build 성공
- 치명 콘솔 오류 없음
- smoke test
- 미구현 명시

### Gate G — Handoff

- AGENTS
- CLAUDE 또는 generic handoff
- NEXT_ACTION
- PROJECT_STATUS
- 최신 산출물
- Blocker 0 또는 명시 승인
- secret scan
- ZIP manifest

## 4. Stale 규칙

### 대상 사용자 변경

Product Brief, UX, Screen, Requirements, Test persona stale.

### Must 기능 변경

Scope, Flow, Screen, API/Data, Tasks, Tests, NEXT_ACTION stale.

### 기술 스택 변경

Architecture, API, Data Model, Tasks, AGENTS, Setup stale.

### 색상·문구 변경

Design·Screen Spec·visual test만 stale.

## 5. 자동 검토

### 규칙 기반

- 누락 파일
- ID 연결
- Out 범위
- 빈 acceptance criteria
- API/Data 불일치
- 명령 존재
- stale 상태

### 독립 LLM Reviewer

- 문제와 기능의 관련성
- 일정 대비 복잡도
- UX dead-end
- 아키텍처 과도함
- 발표 가치
- 초보자 설명 난이도

## 6. 완료 상태

- proposed
- approved
- implemented
- tested
- verified

`implemented`와 `verified`를 분리한다.

Evidence:

- test output
- build hash
- screenshot
- preview
- git commit
- manual checklist
- review finding resolution
