# Contributing

## 개발 환경

README의 설치 절차로 Python과 Web 의존성을 설치합니다. 런타임 DB, 로그, API key, task workspace는 커밋하지 않습니다.

## 변경 원칙

- task 상태와 Job 상태를 혼합하지 않습니다.
- UI 상태는 추측하지 않고 API의 task·Job·event를 사용합니다.
- 모델 실행을 완료로 처리하려면 Evidence와 별도 팀장 리뷰가 필요합니다.
- 파일·명령·MCP 쓰기 권한은 TaskContract를 우회하지 않습니다.
- 말풍선과 tool summary에 prompt 원문, 파일 본문, 인증 값을 넣지 않습니다.
- Windows launcher 변경 시 부모 reloader와 listener 자식 종료를 함께 검증합니다.
- 코드 변경 없는 신규 계획/제안 문서(docs/*)는 추가하지 않습니다. 계획은 이슈나 PR 설명에 적고, 실행된 것만 `docs/WORK_LOG.md`에 남깁니다.

## 필수 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py" -v
cd apps\web
npm.cmd test -- --run
npm.cmd run build
```

**이 스위트는 배관(plumbing) 회귀 테스트입니다.** `main.run_agent`/모델 응답을 mock하므로 코드 경로가 안 깨졌다는 것만 보장하고, 산출물이 실제로 쓸만한지는 보증하지 않습니다. "테스트 통과"를 완료·릴리스 판정의 근거로 쓰지 마세요. 산출물 품질 판정은 실 API로 도는 별도 eval(사람 또는 다른 모델이 채점)로 합니다.

PR에는 변경 이유, 사용자 영향, 재현 원인, 검증 결과를 적습니다.
