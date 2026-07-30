# 06B. Internal MVP Build Standard

## 1. 목표

내부 개발부는 완성형 SaaS가 아니라 **Codex·Claude가 세부 완성도를 높이기 좋은 구조적으로 올바른 MVP**를 만든다.

목표 수준:

- 시각적 첫인상: 기본 이상
- 핵심 흐름: 작동
- 구조: 확장 가능
- 문서: 코드와 일치
- 검증: build + smoke
- 남은 작업: 명확

## 2. MVP Definition of Done

### Product

- 핵심 성공 장면을 실제로 경험
- Must 기능만 구현
- Out 기능 미구현
- mock과 실제 기능 명확히 구분

### UX

- 핵심 화면 3~7개
- 주요 CTA 동작
- dead-end 없음
- loading·empty·error
- 모바일 핵심 흐름
- 기본 접근성

### Code

- 공식 install/dev/build 명령
- 명확한 모듈 경계
- 거대한 단일 파일 금지
- 재사용 컴포넌트
- typed contract
- 환경 변수 분리
- 치명 콘솔 오류 없음

### Data

- 화면마다 데이터 source
- mock은 명시적 adapter
- API·Data Model 일치
- 샘플 데이터

### Test

- 핵심 smoke 또는 E2E
- 중요 규칙 unit test
- 오류·fallback 최소 1개
- 빌드 성공

### Handoff

- PROJECT_STATUS
- NEXT_ACTION
- Known Limitations
- Traceability
- Build Evidence

## 3. 70점 MVP와 나쁜 MVP의 차이

### 70점 MVP

- 핵심 사용자 가치가 작동
- 구현 범위가 작고 명확
- mock 경계가 분명
- 나중 작업이 이어지기 쉬움
- 문서·코드·테스트가 연결

### 나쁜 MVP

- 화면은 많지만 연결 안 됨
- 모든 버튼이 장식
- 실제 API처럼 보이는 하드코딩
- 문서와 코드가 다름
- build 검증 없음
- Codex가 전체 구조부터 다시 설계해야 함

## 4. Replit보다 우위가 가능한 기준

절대적인 모든 영역 우위를 약속하지 않는다.

우위를 목표로 하는 영역:

- 기획 깊이
- 범위 현실성
- 산출물 연결
- 화면·API·DB 일관성
- 검수와 반송
- 도구 중립적 인계
- 후속 개발 준비도

Replit이 강할 수 있는 영역:

- 첫 생성 속도
- 즉시 실행 환경
- 배포 편의성
- 내장 인프라

제품 메시지:

> 가장 빨리 아무 앱을 만드는 것이 아니라, 처음부터 덜 틀리고 다음 개발이 쉬운 MVP를 만든다.

## 5. 템플릿 전략

초기에는 다음 템플릿에 집중한다.

1. Landing + Core Demo
2. CRUD Web Service
3. Dashboard
4. AI Analysis Service
5. Portfolio/Project Showcase

각 템플릿은 다음을 포함한다.

- route skeleton
- layout
- common states
- mock adapter
- basic test
- design tokens
- export docs

## 6. Build Report

```md
# BUILD REPORT

## Implemented
...

## Mocked
...

## Not Implemented
...

## Commands
- install:
- dev:
- build:
- test:

## Results
...

## Evidence
...

## Known Limitations
...

## Recommended Codex Next Action
...
```
