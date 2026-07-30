# AI Vibe Coding Office — Codex Context Pack

작성일: 2026-07-30  
작업명: **VibeOffice(가칭)**

이 패키지는 비전공 부트캠프 참여자가 복잡한 프롬프트를 작성하지 않아도 아이디어를 정리하고, 기본 시안·요구사항·작업 목록을 만든 뒤 Codex 또는 Claude Code로 이어서 개발하기 위한 제품 컨텍스트다.

## 사용법

1. 이 폴더의 내용을 현재 저장소 루트에 복사한다.
2. Codex는 루트의 `AGENTS.md`부터 읽게 한다.
3. 아래 프롬프트로 시작한다.

```text
AGENTS.md와 product-context/README_FOR_CODEX.md부터 읽어라.
현재 코드베이스와 명세를 비교해 GAP_ANALYSIS.md를 작성하고,
P0 Golden Path의 가장 작은 수직 슬라이스를 구현·테스트하라.
```

## 문서 순서

1. `product-context/README_FOR_CODEX.md`
2. `01_PRODUCT_VISION.md`
3. `02_USERS_AND_JTBD.md`
4. `03_BENCHMARK.md`
5. `04_CORE_FLOW_AND_FEATURES.md`
6. `05_AGENT_ORCHESTRATION.md`
7. `06_OUTPUT_STANDARD.md`
8. `07_UX_RULES.md`
9. `08_MVP_ROADMAP.md`
10. `09_ACCEPTANCE_CRITERIA.md`
11. `10_DATA_MODEL_API.md`
12. `11_CODEX_IMPLEMENTATION_BRIEF.md`
13. `SOURCES.md`

## 핵심 원칙

- 사용자는 프롬프트를 잘 쓰지 못해도 된다.
- 필수 질문은 최소화하고 추천 기본값을 제공한다.
- 문서만 생성하지 말고 눈에 보이는 기본 시안을 제공한다.
- 에이전트는 내부 구현 방식이지 사용자가 직접 운영해야 하는 조직이 아니다.
- 결과는 Codex·Claude Code·Cursor에 넘길 수 있는 도구 중립적 파일이어야 한다.
- 범위 통제, 검증, 체크포인트, 복구를 화려한 자율 실행보다 우선한다.


## v2 추가 내용

- `03A_MANIFEST_DEEP_ANALYSIS.md`: Manifest 공개 기능 전수 분석, 동등성 기준, 8개 우위
- `06A_HANDOFF_READINESS_STANDARD.md`: Codex·Claude Code H0~H5 인계 품질
- `09A_ARTIFACT_QUALITY_GATES.md`: 산출물 추적성과 품질 게이트
- `reference-output/`: 실제 H4 내보내기 정답 예시

v2의 목표는 긴 실행 프롬프트가 아니라 **코딩 에이전트가 폴더를 읽고 바로 작업할 수 있는 Agent-ready Project Folder**다.

## v3 — 부서형 MVP 제작 흐름

v3는 다음 핵심 구조를 패키지 전체에 반영한다.

```text
기획부
→ 디자인부
→ 기술설계부
→ 개발부
→ QA·검수부
→ 출고부
→ Codex·Claude Code
```

신규 핵심 문서:

- `04A_DEPARTMENT_WORKFLOW.md`
- `05A_DEPARTMENT_HANDOFF_CONTRACTS.md`
- `05B_REVIEW_AND_REWORK_LOOP.md`
- `06B_INTERNAL_MVP_BUILD_STANDARD.md`
- `06C_CODEX_CLAUDE_REFINEMENT_WORKFLOW.md`

핵심 변화:

- 부서마다 소유 산출물과 Gate 정의
- 승인된 버전 기반 handoff
- QA 문제가 소유 부서로 부분 반송
- 내부 개발부의 70점대 buildable MVP 기준
- Standard H4, Quality H5 출고
- Codex·Claude가 전체 재설계가 아니라 세부 완성에 집중
