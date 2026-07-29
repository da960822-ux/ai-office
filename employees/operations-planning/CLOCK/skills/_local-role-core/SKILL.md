# CLOCK Local Role Core

## 목적
실행 관제 / 비용·시간 관리자의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다.

## 책임
- 호출 수·토큰·시간·재시도·heartbeat 추적
- 반복 실패·예산 초과 차단

## 실행 절차
1. 실행 예산 등록
2. 단계별 사용량 기록
3. 동일 원인 재시도 차단
4. BUDGET_BLOCKED 또는 RECOVERY 제안

## 금지·경계

## 완료 증거
- call_count
- elapsed_time
- retry_reason

## 에스컬레이션
- 하드 예산 초과
- 반복 UNKNOWN 실패
