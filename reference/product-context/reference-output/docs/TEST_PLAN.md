# TEST PLAN

## TEST-E2E-001

Input:

```text
취업 준비생이 모의면접하고 답변을 분석받는 서비스를 만들고 싶어.
4명이 3주 동안 만들 거야.
```

Expected:

- 취업 준비생 대상 추정
- 4명·3주 보존
- Must 3~5개
- Later와 위험
- Blueprint 승인

Also test:

- schema validation
- duplicate question prevention
- malformed response fallback
- empty/loading/error
- keyboard
- official build
