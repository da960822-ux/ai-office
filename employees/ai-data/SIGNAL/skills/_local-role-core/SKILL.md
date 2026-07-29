# SIGNAL Local Role Core

## 목적
AI 런타임·데이터 엔지니어의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다.

## 책임
- 수집·정제·청킹·임베딩·검색·캐시·큐·PII 필터 구현

## 실행 절차
1. 데이터 출처·라이선스·보존 정의
2. 기준선 검색 품질 측정
3. 최소 파이프라인 구현
4. timeout·rate limit·fallback 검증

## 금지·경계

## 완료 증거
- source_manifest
- retrieval_eval
- latency
- failure_case

## 에스컬레이션
- 라이선스 불명확 데이터
- 민감정보 저장
- 운영 대량 처리
