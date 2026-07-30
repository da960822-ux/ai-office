# 04. Core Flow and Feature Requirements

## 전체 흐름

```text
짧은 아이디어
→ 의도 정규화·최소 질문
→ 기획부: Blueprint·MVP·Roadmap
→ 사용자 기획 승인
→ 디자인부: 흐름·화면·디자인 시스템·시안
→ 사용자 시안 승인
→ 기술설계부: Architecture·API·Data·Tasks
→ 개발부: 빌드 가능한 MVP
→ QA·검수부: 기획·UX·기술·실행 검수
→ 문제 소유 부서로 부분 반송
→ 출고부: H4/H5 프로젝트 폴더
→ Codex·Claude Code: 세부 완성
```

상세 부서 계약은 `04A_DEPARTMENT_WORKFLOW.md`, `05A_DEPARTMENT_HANDOFF_CONTRACTS.md`를 따른다.

## P0-01. 쉬운 프로젝트 시작

빈 채팅창 대신 시작 카드:

- 아이디어만 있어요
- 팀 프로젝트를 정리하고 싶어요
- 기존 코드를 이어서 만들고 싶어요
- 화면 시안을 먼저 보고 싶어요
- 오류 난 프로젝트를 정리하고 싶어요

입력:

- 한두 문장
- 문서
- 기존 저장소
- 참고 이미지·링크
- 음성은 후순위 가능

수용 기준:

- 30자 안팎의 모호한 입력도 Blueprint 초안으로 변환
- 기술 스택 없이 진행
- 빈 입력에는 실제 예시
- 이미 제공한 팀·기간 재질문 금지

## P0-02. 기획부 패키지

자동 추정:

- projectType
- targetUser
- coreProblem
- successMoment
- deadline
- teamSize
- skillLevel
- data/auth/ai needs

출력:

- PRODUCT_BRIEF
- MVP_SCOPE
- REQUIREMENTS
- ROADMAP
- DECISIONS
- project-blueprint.json

규칙:

- 질문 최대 3개
- Must 3~5개
- Later·Out 필수
- 안정형·차별형 최대 2개
- 모든 추천에 이유와 변경 가능 여부

## P0-03. 디자인부 패키지

출력:

- IA
- User Flows
- Screen Spec
- Design System
- Component Inventory
- 실행 시안 또는 구조화 prototype

수용:

- 화면 3~7개
- 모든 Must 연결
- CTA 동작
- loading·empty·error
- dead-end 없음
- 기본 모바일·접근성

## P0-04. 기술설계부 패키지

출력:

- Architecture
- Tech Stack
- API Contract
- Data Model
- ERD
- Environment
- Security Baseline
- Technical Tasks

수용:

- 화면별 데이터 source
- API·DB 일치
- 인증·외부 API 실패
- 작업 의존성
- 실행·검증 명령

## P0-05. 내부 MVP 개발

최소:

- 실제 source
- 핵심 route
- mock 또는 실제 데이터 adapter
- 상태 처리
- build
- smoke/E2E
- PROJECT_STATUS
- BUILD_REPORT

목표는 완성형 SaaS가 아니라 Codex가 재설계 없이 개선 가능한 70점대 MVP다.

## P0-06. QA·검수와 반송

검토:

- Scope
- UX
- Requirement consistency
- Technical feasibility
- Build/Test
- Security basics
- Handoff readiness

Blocker는 소유 부서로 부분 반송한다.

- 기획 → 기획부
- 흐름·화면 → 디자인부
- API·DB → 기술설계부
- 코드·빌드 → 개발부

전체 재생성보다 최소 영향 수정이 기본이다.

## P0-07. 출고

필수:

- AGENTS.md
- CLAUDE.md
- NEXT_ACTION.md
- PROJECT_STATUS.md
- docs/
- .vibeoffice/
- 실제 source 또는 prototype

목표:

- Quick H3+
- Standard H4
- Quality H5

## P1-08. 직접 시각 편집

모델 호출 없이:

- 텍스트
- 색상
- 크기
- 간격
- 정렬
- 표시
- 순서

흐름·데이터 변경은 영향 분석과 재승인을 거친다.

## P1-09. 오피스 시각화

- 부서
- 현재 입력
- 작업
- 완료 조건
- 차단
- 인계 상태

오피스 없이도 모든 산출물과 작업에 접근 가능해야 한다.

