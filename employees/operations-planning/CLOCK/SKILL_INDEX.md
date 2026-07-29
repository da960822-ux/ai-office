# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: CLOCK Local Role Core — 실행 관제 / 비용·시간 관리자의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 호출 수·토큰·시간·재시도·heartbeat 추적 - 반복 실패·예산 초과 차단 1. 실행 예산 등록 2. 단계별 사용량 기록 3. 동일 원인 재시도 차단 4. BUDGET_BLOCKED 또는 RECOVERY 제안 - call_count - elapsed_time - retry_reason - 하드 예
- `code-simplification`: Code Simplification — --- name: code-simplification description: Simplifies code for clarity. Use when refactoring code for clarity without changing behavior. Use when code works but is harder to read, maintain, or extend than it should be. Use when reviewing co
- `debugging-and-error-recovery`: Debugging and Error Recovery — --- name: debugging-and-error-recovery description: Guides systematic root-cause debugging. Use when tests fail, builds break, behavior doesn't match expectations, or you encounter any unexpected error. Use when you need a systematic approa
- `observability-and-instrumentation`: Observability and Instrumentation — --- name: observability-and-instrumentation description: Instruments code so production behavior is visible and diagnosable. Use when adding logging, metrics, tracing, or alerting. Use when shipping any feature that runs in production and y
