# 04A. Department Workflow — 기획에서 MVP, Codex 완성까지

## 1. 최종 서비스 흐름

```text
사용자 아이디어
→ 기획부
→ 디자인부
→ 기술설계부
→ 개발부
→ QA·검수부
→ 출고부
→ Codex·Claude Code
```

이 흐름의 목적은 에이전트가 회사처럼 보이게 하는 것이 아니다.

> 각 부서가 명확한 산출물을 만들고, 다음 부서가 그것을 입력 계약으로 받아, 검증 가능한 MVP와 개발 인계 폴더를 완성하는 것.

## 2. 부서별 책임

### 2.1 기획부 — Product Planning

#### 입력

- 사용자의 짧은 아이디어
- 팀 규모·기간·숙련도
- 참고 문서·이미지·링크
- 기존 프로젝트 자료
- 이전 결정과 제약

#### 수행

- 의도 정규화
- 필요한 질문 최대 3개
- 대상 사용자·문제·성공 장면 정의
- MVP 범위 3~5개 제한
- 안정형·차별형 방향 비교
- 단계형 roadmap
- 명시적 제외 범위
- 위험과 미결정 사항

#### 출력

```text
PRD.md
project-blueprint.json
decision-register.json
risk-register.json
traceability-map.json
roadmap.json
```

#### 출구 조건

- 대상 사용자와 성공 장면 명확
- Must 3~5개
- Later와 Out 존재
- 각 Must가 사용자 가치와 연결
- 팀·기간 대비 과도한 기능 없음
- 모든 핵심 결정에 이유 존재

#### 다음 부서

디자인부

---

### 2.2 디자인부 — UX and Product Design

#### 입력

- 승인된 Blueprint
- MVP Scope
- Requirements
- 사용자·제품 제약
- 브랜드 또는 디자인 참고자료

#### 수행

- 정보 구조
- 핵심 사용자 흐름
- 화면 3~7개 정의
- 주요 CTA와 상태
- loading·empty·error
- 디자인 시스템
- 컴포넌트 목록
- 모바일·접근성 기본
- 실행 가능한 시안 또는 구조화 프로토타입

#### 출력

```text
INFORMATION_ARCHITECTURE.md
USER_FLOWS.md
SCREEN_SPEC.md
DESIGN_SYSTEM.md
COMPONENT_INVENTORY.md
prototype/
design-tokens.json
```

#### 출구 조건

- 모든 Must 기능이 흐름과 화면에 연결
- dead-end 없음
- 모든 주요 CTA 동작 정의
- 데이터가 필요한 화면 표시
- loading·empty·error 존재
- 실행 시안이면 공식 build 성공
- 장식용 버튼 없음

#### 다음 부서

기술설계부

---

### 2.3 기술설계부 — Architecture and Contracts

#### 입력

- 승인된 Blueprint·Scope
- 화면·흐름·컴포넌트
- 현재 저장소 또는 선택된 기술 템플릿
- 외부 API·비용·배포 제약

#### 수행

- 시스템 경계
- 프론트·백엔드 책임
- 화면별 데이터 요구
- API 계약
- 데이터 모델
- 인증·권한
- 외부 AI/API 실패 처리
- 환경 변수
- 테스트 전략
- 구현 순서와 의존성

#### 출력

```text
ARCHITECTURE.md
TECH_STACK.md
API_CONTRACT.yaml
DATA_MODEL.md
ERD.md
SECURITY_BASELINE.md
ENVIRONMENT.md
TECHNICAL_TASKS.md
```

#### 출구 조건

- 데이터 화면마다 source 존재
- API·Data Model 필드 일치
- 인증 필요성 일치
- 외부 서비스 실패 경로 존재
- 비밀값 처리 규칙 존재
- 현재 기간·숙련도 안에서 구현 가능
- 개발 작업이 수직 슬라이스로 나뉨

#### 다음 부서

개발부

---

### 2.4 개발부 — MVP Build

#### 입력

- 승인된 기획·디자인·기술 산출물
- prototype 또는 starter template
- 작업 목록
- 테스트 계획
- 현재 저장소

#### 수행

- 프로젝트 골격 또는 기존 코드 개선
- 핵심 화면·라우트
- 핵심 사용자 흐름
- mock 또는 기본 데이터 연결
- API adapter
- 상태 처리
- 기본 테스트
- build 검증
- 현재 상태 문서화

#### 출력

```text
실제 소스코드
PROJECT_STATUS.md
BUILD_REPORT.md
IMPLEMENTATION_NOTES.md
test-results/
evidence/
current-state.json
```

#### 개발부 목표

완전한 상용 서비스가 아니라 다음 상태의 **구조적으로 올바른 70점대 MVP**다.

- 핵심 사용자 흐름 작동
- build 성공
- mock 또는 실제 데이터 경계 명확
- 주요 상태 존재
- 문서와 코드가 일치
- 남은 구현이 명확
- Codex·Claude가 재설계보다 개선에 집중 가능

#### 개발부가 하지 않는 것

- 모든 성능 최적화
- 완전한 운영 보안 인증
- 모든 예외 처리
- 대규모 리팩터링
- 프로덕션 인프라 자동화
- 세부 애니메이션 완성
- 완벽한 테스트 커버리지

#### 다음 부서

QA·검수부

---

### 2.5 QA·검수부 — Cross-functional Review

#### 입력

- 전체 승인 산출물
- 실제 코드
- build·test 결과
- preview 또는 스크린샷
- current-state

#### 검수 영역

##### 기획

- MVP를 벗어난 기능
- 핵심 사용자 문제 해결 여부
- 성공 장면 구현 여부
- 문서와 실제 기능 일치

##### UX

- dead-end
- 무동작 버튼
- loading·empty·error 누락
- 모바일·키보드 핵심 흐름

##### 기술

- 화면·API·DB 연결
- 인증·권한
- 외부 API 실패
- secret
- 과도한 구조

##### 실행

- install
- dev
- build
- smoke/E2E
- 콘솔 치명 오류
- 재현성

#### 출력

```text
REVIEW_FINDINGS.md
ACCEPTANCE_REPORT.md
BUILD_EVIDENCE.md
review-findings.json
handoff-readiness.json
```

#### 반송 규칙

```text
범위·사용자 가치 문제 → 기획부
흐름·화면·상태 문제 → 디자인부
API·DB·아키텍처 문제 → 기술설계부
코드·테스트·빌드 문제 → 개발부
```

Blocker가 있으면 출고부로 넘기지 않는다.

---

### 2.6 출고부 — Agent Shipping

#### 입력

- 검수를 통과한 산출물
- 실제 코드
- 현재 상태
- 남은 제한
- 다음 작업 후보

#### 수행

- Codex용 AGENTS.md 생성
- Claude Code용 CLAUDE.md 생성
- NEXT_ACTION.md 생성
- PROJECT_STATUS 최신화
- 문서·코드 추적성 검사
- secret·절대경로 검사
- Handoff readiness 계산
- ZIP 또는 저장소 패키지 생성

#### 출력

```text
AGENTS.md
CLAUDE.md
NEXT_ACTION.md
PROJECT_STATUS.md
README.md
docs/
.vibeoffice/
prototype 또는 실제 source
```

#### 기본 출고 목표

- 빠른 모드: H3 이상
- 기본 모드: H4
- 고품질 모드: H5

#### 다음 단계

Codex 또는 Claude Code가 세부 기능, 리팩터링, 테스트 확대, 실제 API 연결, 배포를 수행한다.

## 3. 사용자 승인 지점

기본 자율성에서는 세 번만 승인받는다.

1. **기획 승인** — 제품 방향과 MVP
2. **시안 승인** — 화면과 사용자 흐름
3. **출고 승인** — 남은 제한과 인계 대상

그 외 문서 정렬·스키마 수정·검토 재실행은 안전 자동화한다.

## 4. 오피스 UI에서 보이는 것

### 메인 화면

항상 산출물과 현재 단계가 중심이다.

```text
현재 부서: 기술설계부
입력: 승인된 화면 5개
작업: 화면별 데이터 계약 작성
완료 조건: API와 Data Model 일치
차단: 로그인 범위 사용자 결정 필요
```

### 오피스 공간

- Planning Room
- Design Studio
- Architecture Lab
- Build Floor
- Review Room
- Shipping Dock

아바타의 이동은 실제 handoff와 상태를 반영해야 한다. 의미 없는 회의 연출은 넣지 않는다.

## 5. 전체 성공 기준

다음 문장이 성립해야 한다.

> 사용자는 아이디어만 설명했고, 오피스 내부에서 부서들이 승인된 산출물을 넘겨받아 빌드 가능한 MVP를 만들었으며, Codex·Claude Code는 제품을 다시 해석하지 않고 세부 완성도를 높이기 시작했다.
