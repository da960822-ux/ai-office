# 기여 가이드

## 개발 환경

- Python 3.11 이상
- Node.js 20 이상
- 루트 `requirements.txt` 의 의존성

## 변경 절차

1. 작업 목적이 드러나는 브랜치를 만듭니다. 예: `feat/task-dashboard`, `fix/job-retry`.
2. 작은 단위로 변경하고, 관련 테스트를 함께 추가합니다.
3. 아래 검증 명령을 실행합니다.
4. 커밋 메시지는 `feat:`, `fix:`, `docs:`, `test:`, `chore:` 형식을 사용합니다.
5. Pull Request에 변경 내용, 검증 결과, 남은 위험을 기록합니다.

## 검증 명령

```bash
npm test
python -m pytest apps/api
```

웹 앱을 변경했다면 다음도 실행합니다.

```bash
cd apps/web
npm ci
npm run build
```

## 보안

API 키와 MCP 인증 토큰은 커밋하지 않습니다. 로컬 설정은 `.ai-office/settings.json` 또는 OS keyring을 사용하고, 공개 저장소에 올릴 파일에는 비밀값을 포함하지 않습니다.
