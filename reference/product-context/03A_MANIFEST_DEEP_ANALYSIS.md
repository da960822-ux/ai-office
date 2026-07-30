# 03A. Manifest 심층 분석과 우위 설계

> 기준일: 2026-07-30  
> 범위: trymanifest.dev가 공개한 제품 설명과 가격 페이지. 비공개 코호트 내부 기능은 확인된 사실처럼 단정하지 않는다.

## 1. Manifest의 핵심 포지션

Manifest는 Lovable, Claude Code, Cursor, Bolt, Replit, GitHub Codespaces 같은 AI 빌더 앞단의 **전략·연속성 레이어**를 지향한다.

해결하려는 문제:

- 세션이 바뀌면 초기 목적과 결정이 사라짐
- 합의하지 않은 기능을 AI가 추가함
- 무엇이 완료·고장·의존 상태인지 불명확함
- 같은 프로젝트 맥락을 빌더마다 다시 설명함
- 모호한 상태에서 생성해 크레딧과 시간을 낭비함

공개된 기본 흐름:

```text
아이디어·브리프·문서 입력
→ 제품 설명·비전·UX·아키텍처 구조화
→ 단계·기능·실행 프롬프트가 포함된 live roadmap
→ 선택한 AI 빌더에서 구현
→ 빌드 상태 추적
→ 다음 작업과 제품 개선 추천
```

## 2. 공개 확인 기능 전수 목록

### M-01. Vague Idea Intake

- 한 문장 아이디어
- 기존 브리프 붙여넣기
- 문서 첨부
- 모호한 입력에서 시작

### M-02. Structured Product Brief

공개 설명상 다음을 구조화한다.

- Product description
- Vision
- UX
- Architecture

### M-03. Phase-aware Roadmap

기능마다 다음을 정리한다.

- Phase
- Scope
- Complexity
- Dependencies

### M-04. Execution-ready Builder Prompts

공개 지원 대상으로 언급된 빌더:

- Lovable
- Claude Code
- Cursor
- Bolt
- Replit
- GitHub Codespaces

### M-05. Strategic PM Chat

- 아이디어 논의
- 기능 승격
- 불필요한 방향 제거
- phase 재생성
- roadmap 수정

### M-06. Build Status Tracking

계획만이 아니라 실제 빌드 상태를 추적한다고 설명한다.

### M-07. AI Recommendations

현재 roadmap을 바탕으로 다음 작업과 제품 확장 아이디어를 추천한다.

### M-08. Document Grounding

공개 요금제 기준:

- Pro: roadmap당 최대 3개 문서
- Max: roadmap당 문서 grounding 무제한

### M-09. Version History

모든 roadmap의 버전 기록.

### M-10. Export

- PDF
- Word
- Google Drive

### M-11. Project Management

- Pro: 활성 프로젝트 최대 5개
- Max: 활성 프로젝트 무제한

### M-12. Credit-efficient Structuring

코드 생성 전 모호성을 줄여 재생성과 크레딧 낭비를 줄이는 방향.

### M-13. Coming Soon

현재 제공 기능으로 간주하지 않는다.

- Portfolio intelligence
- Persistent memory
- Shareable client links

## 3. 공개 자료만으로 확인할 수 없는 항목

- 빌드 상태 자동 동기화 방식
- GitHub 커밋·PR 연동 깊이
- 실행 프롬프트의 실제 품질과 구조
- 요구사항·화면·API·테스트 간 추적성
- 실행 가능한 프로토타입 생성
- 자동 빌드·테스트 검증
- 코드 체크포인트·롤백
- 보안 검토와 권한
- API·DB 명세 깊이
- Codex·Claude용 실제 프로젝트 폴더 생성

경쟁 비교 화면에서는 반드시 `확인`, `미확인`, `향후 공개`를 구분한다.

## 4. Manifest의 강점

1. **문제 정의가 명확하다.** 코드 생성보다 연속성·범위·다음 행동을 판다.
2. **기획과 실행을 연결한다.** 정적 문서가 아니라 빌더별 프롬프트까지 제공한다.
3. **단계별 범위를 통제한다.** phase·complexity·dependency가 초보자의 과도한 MVP를 막는다.
4. **빌더 중립적이다.** 특정 코딩 도구 하나에 종속되지 않는다.
5. **roadmap을 살아 있는 상태로 다룬다.** 기능 추가·제거·승격·재단계화가 가능하다.

## 5. 최소 동등성 기준

| 영역 | VibeOffice가 반드시 가져야 할 기능 |
|---|---|
| Intake | 문장·브리프·문서·기존 자료 입력 |
| Brief | 제품·비전·UX·기술 구조화 |
| Roadmap | phase·scope·complexity·dependency |
| Builder support | Codex·Claude·Cursor 계열 인계 |
| PM interaction | 기능 추가·제거·승격·재단계화 |
| Tracking | 계획과 실제 구현 상태 비교 |
| Memory | 결정·범위·버전 유지 |
| Recommendation | 현재 단계 기반 다음 행동 |
| Export | 사람이 읽는 문서와 에이전트용 파일 |
| Cost UX | 생성 범위·난이도·재작업 방지 |

## 6. Manifest보다 앞서기 위한 우위

### W-01. Prompt가 아니라 Project Folder

Manifest식 실행 프롬프트를 넘어 실제 폴더를 만든다.

```text
AGENTS.md
CLAUDE.md
NEXT_ACTION.md
PROJECT_STATUS.md
README.md
docs/
.vibeoffice/
prototype/
```

### W-02. 산출물 추적 그래프

```text
Goal
→ Feature
→ Requirement
→ User Flow
→ Screen
→ API/Data
→ Task
→ Test
→ Evidence
```

한 결정이 바뀌면 영향을 받는 파일만 stale 처리한다.

### W-03. 실행 가능한 첫 시안

- 핵심 화면
- 클릭 흐름
- mock data
- loading·empty·error
- 기본 반응형
- 공식 build 성공
- 미구현 기능 명시

### W-04. 증거 기반 완료

완료 상태에 다음 증거를 연결한다.

- build/test 결과
- 스크린샷 또는 preview
- 변경 파일
- git commit
- 관련 요구사항
- 남은 제한

### W-05. 비전공자 번역 계층

```text
기본 화면: “새로 들어와도 기록을 남겨야 하나요?”
전문 산출물: persistence requirement + data model + API contract
```

### W-06. 기존 코드 조정

프로젝트 폴더를 넣으면 다음을 먼저 만든다.

- 현재 구조 지도
- 실행 방법
- 구현된 기능
- 문서와 코드의 차이
- 유지·수정·추가·삭제
- 가장 작은 다음 패치

### W-07. 품질 게이트

- Intent Gate
- Scope Gate
- UX Gate
- Technical Gate
- Build Gate
- Handoff Gate

### W-08. 복구 가능한 자율성

- 체크포인트
- 산출물 버전
- Git diff
- 부분 재시도
- 위험 작업 승인
- 전체 중단
- 승인 상태 복구

## 7. 사용성 우위 화면

1. **Idea Inbox** — 문장·음성·문서·저장소
2. **Recommended Blueprint** — 핵심 사용자·문제·성공 장면·MVP·위험
3. **Roadmap Canvas** — phase 목표와 exit criteria
4. **Artifact Studio** — 기획·화면·API·DB·작업·테스트
5. **Prototype** — 실제 시안
6. **Build Sync** — 계획과 코드의 차이
7. **Ship to Agent** — Codex·Claude·Generic Folder

## 8. 최종 제품 정의

> Manifest의 전략·연속성 기능에 실행 가능한 시안, 산출물 추적, 검증 증거, 기존 코드 분석, 코딩 에이전트용 프로젝트 폴더를 추가한 초보자용 Product-to-Code Workspace.

외부 문구:

> **아이디어를 계획으로 끝내지 않습니다. 바로 개발할 수 있는 프로젝트로 정리합니다.**
