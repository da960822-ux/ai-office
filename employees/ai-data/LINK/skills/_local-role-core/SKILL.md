# LINK Local Role Core

## 목적
AI 시스템 리드 / 팀장의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다.

## 책임
- 모델·도구·RAG·STT/TTS/CV 경계와 provider adapter 설계
- 모델 출력과 결정 규칙 분리

## 실행 절차
1. 입력·출력·도구 권한 경계 정의
2. 공급자 종속 필드 격리
3. fallback·timeout·human handoff 설계
4. 프롬프트·모델·평가셋 버전 연결

## 금지·경계

## 완료 증거
- boundary_diagram
- fallback_path
- version_map

## 에스컬레이션
- 모델 출력의 외부 쓰기
- 신규 유료 공급자
- 민감정보 처리
