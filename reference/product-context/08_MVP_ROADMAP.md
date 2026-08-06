# 08. MVP Scope and Roadmap

## MVP가 증명할 것

> 비전공 사용자가 짧은 아이디어를 입력하면, 오피스의 부서들이 승인된 산출물을 인계해 빌드 가능한 MVP를 만들고, Codex·Claude가 바로 세부 완성을 시작할 수 있다.

## Phase 0 — Current State

- 저장소 구조
- 실행·빌드·테스트
- 기존 기능
- 현재 오피스 UI
- 재사용·보류·제거
- GAP_ANALYSIS

## Phase 1 — Planning Department

```text
Idea
→ Normalize
→ Questions
→ Blueprint
→ Scope
→ Roadmap
→ Planning Approval
```

필수:

- PRD.md의 필수 섹션(06_OUTPUT_STANDARD.md 참고, 별도 문서로 중복 생성 금지): Product Brief, MVP Scope, Requirements, Decisions
- Roadmap (본 문서의 Phase 구성)
- Blueprint JSON (`project-blueprint.json`, 06_OUTPUT_STANDARD.md Planning Package 참고)

완료:

- Must 3~5개
- Later·Out
- 성공 장면
- 기획 Gate 통과

## Phase 2 — Design Department

```text
Approved Planning
→ User Flow
→ Screen Spec
→ Design System
→ Prototype
→ Design Approval
```

완료:

- 화면 3~7개
- 모든 Must 연결
- 상태
- dead-end 없음
- 실행 시안 가능 시 build

## Phase 3 — Architecture Department

```text
Approved Design
→ Architecture
→ API/Data
→ Environment
→ Technical Tasks
→ Technical Gate
```

완료:

- 화면 데이터 계약
- API·DB 정렬
- 실패 처리
- 공식 명령
- 개발 수직 슬라이스

## Phase 4 — Internal MVP Build

```text
Approved Contracts
→ Source
→ Core Flow
→ Mock/Integration
→ Build
→ Smoke
→ Build Report
```

완료:

- 핵심 가치 작동
- build 성공
- mock 경계
- 상태
- PROJECT_STATUS
- evidence

## Phase 5 — QA and Rework

- Scope review
- UX review
- Technical review
- Build/test review
- Security basics
- 반송과 최소 수정
- Handoff readiness

완료:

- Blocker 0
- High 수정 또는 승인
- H4 목표

## Phase 6 — Shipping

- AGENTS
- CLAUDE
- NEXT_ACTION
- PROJECT_STATUS
- traceability
- secret scan
- ZIP/Git package

## Phase 7 — Codex·Claude Refinement

- 실제 API
- 세부 기능
- 리팩터링
- 테스트 확대
- 접근성·성능
- 디자인 polish
- 배포

## 초기 구현 순서

실제 제품 P0는 모든 부서에 별도 고성능 에이전트를 먼저 두지 않는다.

1. 공통 canonical state
2. Planning pipeline
3. Design template pipeline
4. Architecture contract generator
5. Build template runner
6. QA rules
7. Handoff packager
8. Office visualization
9. 역할별 독립 에이전트와 병렬화

## P0 대표 Golden Path

입력:

```text
취업 준비생이 면접 연습하고 답변 분석을 받는 서비스를 만들고 싶어.
4명이 3주 동안 만들 거야.
```

출력:

- 기획부 패키지
- 핵심 화면 4개 React 시안
- API·Data Model 초안
- build 가능한 mock MVP
- QA 보고서
- H4 Codex·Claude 폴더

