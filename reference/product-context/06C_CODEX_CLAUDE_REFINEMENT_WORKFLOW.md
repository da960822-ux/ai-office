# 06C. Codex·Claude Code Refinement Workflow

## 1. 역할 분담

### VibeOffice 내부 개발부

- 제품을 다시 해석하지 않게 준비
- 핵심 MVP 구현
- 구조·문서·검증 기준
- H4/H5 출고

### Codex·Claude Code

- 실제 API 연결
- 세부 기능
- 리팩터링
- 테스트 확대
- 성능·접근성
- 디자인 디테일
- 배포·운영 준비

## 2. 첫 작업

코딩 에이전트는 전체 재설계가 아니라 `NEXT_ACTION.md`의 한 수직 슬라이스를 시작한다.

```text
AGENTS.md/CLAUDE.md와 PROJECT_STATUS.md를 읽는다.
현재 코드와 문서의 차이를 확인한다.
NEXT_ACTION의 범위를 보존한다.
구현·검증·문서 갱신까지 수행한다.
```

## 3. 좋은 NEXT_ACTION 예

```md
# NEXT ACTION

## 사용자 가치
사용자가 생성된 기획 패키지를 ZIP으로 내려받는다.

## 현재 상태
화면과 산출물은 생성되지만 파일 패키징은 미구현.

## 구현
- export manifest
- Markdown 파일 생성
- project-blueprint.json 포함
- ZIP 다운로드
- secret·절대경로 검사

## 제외
- GitHub push
- 클라우드 저장
- 배포

## 완료
- 필수 파일 100%
- ZIP 재압축 후 읽기 성공
- snapshot test
- E2E 다운로드
```

## 4. 세부 완성도 작업 유형

### 기능

- 실제 백엔드·DB
- 인증
- 외부 AI API
- 파일 업로드
- 팀 협업

### 품질

- 타입·에러 처리
- 테스트
- 접근성
- 성능
- 보안
- 로깅

### 디자인

- spacing
- typography
- responsive
- motion
- visual polish

### 운영

- CI
- 환경 설정
- 배포
- 모니터링
- runbook

## 5. Drift 방지

Codex·Claude 작업 후 반드시 갱신:

- PROJECT_STATUS.md
- current-state.json
- TRACEABILITY.md
- DECISIONS.md
- TEST_PLAN.md 또는 evidence

코드만 바뀌고 기획 패키지가 오래된 상태로 남지 않게 한다.

## 6. 완료 보고

```text
사용자 가치
변경 파일
검증 결과
새로운 결정
남은 제한
다음 수직 슬라이스
```
