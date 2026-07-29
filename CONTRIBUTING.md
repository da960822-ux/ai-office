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

## 필수 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s apps\api -p "test_*.py" -v
cd apps\web
npm.cmd test -- --run
npm.cmd run build
```

PR에는 변경 이유, 사용자 영향, 재현 원인, 검증 결과를 적습니다.
