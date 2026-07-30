# AGENTS.md

## Product

비전공 부트캠프 사용자의 짧은 아이디어를 현실적인 MVP와 코딩 에이전트용 프로젝트 폴더로 바꾼다.

## Current Phase

Phase 1 — Idea to Approved Blueprint

## Must

- 짧은 아이디어 입력
- 최소 질문과 추천값
- 프로젝트 블루프린트
- Must·Later 분리
- 승인

## Out

- 실제 다중 에이전트 병렬 실행
- GitHub push
- 결제
- 스킬 마켓
- 3D 오피스

## Rules

1. 현재 저장소와 실행 명령을 먼저 조사한다.
2. 전면 재작성하지 않는다.
3. 한 수직 슬라이스씩 완료한다.
4. 모델 출력은 schema로 검증한다.
5. 채팅을 canonical state로 쓰지 않는다.
6. loading·empty·error를 포함한다.
7. build와 관련 test를 실행한다.
8. 작업 후 PROJECT_STATUS와 TRACEABILITY를 갱신한다.

## Commands

현재 저장소 조사 후 실제 명령으로 교체한다.

```bash
npm install
npm run dev
npm run build
npm test
```

## Department Workflow

Planning artifacts are approved. Design and Architecture are specifications. Build is the next owner.

Do not skip directly to polish. Complete:

```text
Build
→ Build Verification
→ QA
→ H4 Shipping
```

After implementation update:

- PROJECT_STATUS.md
- docs/BUILD_REPORT.md
- docs/ACCEPTANCE_REPORT.md
- .vibeoffice/review-findings.json
- .vibeoffice/handoff-readiness.json
