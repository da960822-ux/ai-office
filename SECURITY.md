# Security Policy

## 민감 정보

- OpenRouter API key는 OS keyring에만 저장합니다.
- `.ai-office/`, `data/`, `logs/`, `.env*`, task workspace는 Git에 포함하지 않습니다.
- Job event와 말풍선에 prompt 원문, 파일 본문, tool arguments, 토큰, 인증 값을 기록하지 않습니다.

키나 개인정보가 Git history에 들어갔다면 단순 삭제 커밋만 하지 말고 즉시 키를 폐기·재발급한 뒤 history 정리 여부를 검토하세요.

## 취약점 제보

공개 Issue에 API key, 로컬 경로, 사용자 문서, 모델 prompt를 첨부하지 마세요. 저장소 소유자에게 비공개 채널로 재현 단계와 영향 범위를 전달하세요.

## 지원 범위

현재 단일 사용자 로컬 실행을 전제로 합니다. 외부 네트워크에 API나 Vite dev server를 공개하는 배포는 지원하지 않습니다.
