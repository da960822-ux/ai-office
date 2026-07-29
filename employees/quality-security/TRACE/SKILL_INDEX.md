# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: TRACE Local Role Core — 테스트·디버깅 엔지니어의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 재현·원인 특정·회귀 테스트·실제 명령 실행 1. 변경 전 실패 재현 2. 최소 사례와 근본 원인 확인 3. 변경 후 동일 검증 실행 4. 전체 관련 suite와 flaky 여부 확인 - command - exit_code - stdout_hash - artifact - commit_sha - 재현 불가 - 환
- `e2e-testing-patterns`: E2E Testing Patterns — --- name: e2e-testing-patterns description: Master end-to-end testing with Playwright and Cypress to build reliable test suites that catch bugs, improve confidence, and enable fast deployment. Use when implementing E2E tests, debugging flak
- `screen-reader-testing`: Screen Reader Testing — --- name: screen-reader-testing description: Test web applications with screen readers including VoiceOver, NVDA, and JAWS. Use when validating screen reader compatibility, debugging accessibility issues, or ensuring assistive technology su
- `systematic-debugging`: Systematic Debugging — --- name: systematic-debugging description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes --- **Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure. **Vio
- `test-driven-development`: Test-Driven Development — --- name: test-driven-development description: Drives development with tests. Use when implementing any logic, fixing any bug, or changing any behavior. Use when you need to prove that code works, when a bug report arrives, or when you're a
- `verification-before-completion`: Verification Before Completion — --- name: verification-before-completion description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success cl
