# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: EVAL Local Role Core — AI 평가·안전 엔지니어의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - golden set·회귀·환각·안전·편향·지연·비용 평가 - 프롬프트 변경 전후 동일 데이터 비교 1. 실패 유형과 평가셋 정의 2. 기준 버전 측정 3. 후보 버전 동일 조건 실행 4. 허용 범위·실패군·회귀 보고 - dataset_version - prompt_version - model_version -
- `doubt-driven-development`: Doubt-Driven Development — --- name: doubt-driven-development description: Subjects every non-trivial decision to a fresh-context adversarial review before it stands. Use when correctness matters more than speed, when working in unfamiliar code, when stakes are high
- `llm-evaluation`: LLM Evaluation — --- name: llm-evaluation description: Implement comprehensive evaluation strategies for LLM applications using automated metrics, human feedback, and benchmarking. Use when testing LLM performance, measuring AI application quality, or estab
- `security-and-hardening`: Security and Hardening — --- name: security-and-hardening description: Hardens code against vulnerabilities. Use when handling user input, authentication, data storage, or external integrations. Use when building any feature that accepts untrusted data, manages use
- `verification-before-completion`: Verification Before Completion — --- name: verification-before-completion description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success cl
