# 05A. Department Handoff Contracts

> **상태**: 이 문서는 목표 스펙이다. 원래 구현체(`vibeoffice/`)는 삭제됐고, `apps/api`가 다른 메커니즘으로 점진적으로 재구현 중이다(예: 부서 stage 게이트, 2026-08-06). 이 문서의 규칙이 전부 현재 코드에 집행되는 건 아니다 — 특히 이 파일이 서술하는 Gate/handoff 세부 로직은 아직 미구현이다.

## 1. 원칙

부서 인계는 채팅 요약이 아니라 **버전이 고정된 입력·출력 계약**이다.

다음 부서는 승인된 버전만 사용한다. 초안 파일을 임의로 참고해 핵심 범위를 바꾸지 않는다.

## 2. 공통 Handoff Envelope

```json
{
  "handoffId": "HO-PLN-DES-001",
  "projectId": "project_123",
  "fromDepartment": "planning",
  "toDepartment": "design",
  "status": "ready",
  "inputVersions": {
    "projectBlueprint": 4,
    "mvpScope": 3,
    "requirements": 2
  },
  "requiredOutputs": [
    "USER_FLOWS.md",
    "SCREEN_SPEC.md",
    "DESIGN_SYSTEM.md"
  ],
  "constraints": [
    "핵심 화면 최대 7개",
    "결제 제외",
    "모바일 핵심 흐름 지원"
  ],
  "acceptanceCriteria": [
    "모든 Must 기능이 화면과 연결",
    "loading/empty/error 포함"
  ],
  "openDecisions": [],
  "approvedBy": "user",
  "createdAt": "ISO-8601"
}
```

## 3. 기획부 → 디자인부

### 필수 입력

- project-blueprint.json
- PRD.md
- project-blueprint.json
- decision-register.json
- risk-register.json

### 인계 요약

- 가장 중요한 사용자
- 핵심 성공 장면
- Must 기능
- Explicitly Out
- 기간·팀·숙련도
- 디자인 제약
- 미결정 사항

### 거부 조건

- Must가 5개 초과하며 근거 없음
- 대상 사용자가 충돌
- 성공 장면이 화면 행동으로 바뀔 수 없음
- Out 기능이 Requirements에 포함
- 미결정 사항이 핵심 화면 구조를 바꿈

## 4. 디자인부 → 기술설계부

### 필수 입력

- USER_FLOWS.md
- SCREEN_SPEC.md
- DESIGN_SYSTEM.md
- COMPONENT_INVENTORY.md
- prototype 또는 preview
- 승인된 기획 산출물

### 인계 요약

- 화면과 route
- 화면별 데이터
- 입력과 이벤트
- 상태와 오류
- 외부 기능 필요 여부
- 모바일·접근성 기준

### 거부 조건

- 데이터가 필요한 화면인데 source가 없음
- 무동작 CTA
- 핵심 흐름 dead-end
- Must 기능에 대응하는 화면 없음
- 상태 정의 누락

## 5. 기술설계부 → 개발부

### 필수 입력

- ARCHITECTURE.md
- API_CONTRACT.yaml
- DATA_MODEL.md
- ENVIRONMENT.md
- TECHNICAL_TASKS.md
- TEST_PLAN.md
- PRD.md
- decision-register.json
- risk-register.json
- 승인된 prototype

### 인계 요약

- 저장소 구조
- 구현할 첫 수직 슬라이스
- API와 mock 경계
- 환경 변수
- 작업 의존성
- 공식 검증 명령
- 보안 금지 사항
- Build 전 해결해야 하는 deferred decision
- High/Critical 위험의 owner·mitigation·trigger

### 거부 조건

- API와 Data Model 불일치
- 화면 데이터 계약 누락
- 공식 build/test 명령 미정
- 실제 스택과 문서 충돌
- 한 작업이 전체 앱 재작성 수준
- secret 처리 규칙 없음
- 측정 불가 KR 또는 Requirement·출시 측정 계획에 연결되지 않은 KR
- owner 또는 mitigation 없는 High/Critical 위험
- Build 전에 결정해야 하는 deferred decision

## 6. 개발부 → QA

### 필수 입력

- 실제 코드
- PROJECT_STATUS.md
- BUILD_REPORT.md
- 변경 파일 목록
- test 결과
- preview·스크린샷
- current-state.json

### 인계 요약

- 구현 완료
- 부분 구현
- mock
- 미구현
- 알려진 제한
- build·test 결과
- 검증하지 못한 항목

### 거부 조건

- 공식 build 실패
- 핵심 route 접근 불가
- 문서에 없는 기능 추가
- 완료 표시했지만 evidence 없음
- secret 포함
- 사용자 변경을 덮어씀

## 7. QA → 출고부

### 필수 입력

- ACCEPTANCE_REPORT.md
- REVIEW_FINDINGS.md
- BUILD_EVIDENCE.md
- handoff-readiness.json
- 전체 최신 산출물과 코드

### 통과 조건

- Blocker 0
- High 이슈는 수정 또는 명시 승인
- H3 이상
- secret scan 통과
- 필수 파일 최신
- NEXT_ACTION 후보 존재

## 8. 출고부 → Codex·Claude

### Codex

- AGENTS.md
- NEXT_ACTION.md
- PROJECT_STATUS.md
- traceability
- 실제 source

### Claude Code

- CLAUDE.md import
- NEXT_ACTION.md
- PROJECT_STATUS.md
- 핵심 docs
- 실제 source

### 첫 작업 원칙

- 새로운 전체 기획을 만들지 않는다.
- 기존 MVP를 보존한다.
- 한 개 수직 슬라이스를 개선한다.
- 검증 후 상태와 문서를 갱신한다.

## 9. 인계 상태

```text
draft
ready_for_review
changes_requested
approved
in_progress
completed
rejected
superseded
```

## 10. 인계 버전 규칙

- 승인 후 입력 산출물이 바뀌면 기존 handoff는 superseded
- 다음 부서 작업 중 상위 범위 변경 시 작업 일시 중단
- 시각 텍스트 변경처럼 영향이 작은 수정은 필요한 산출물만 stale
- 모든 재인계는 변경 diff와 이유를 포함
