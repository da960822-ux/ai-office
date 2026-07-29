# Skill Routing Index

라우터는 작업 요약만 읽고, 선택된 작업에 해당하는 SKILL.md만 로드한다.

- `_local-role-core`: LENS Local Role Core — 독립 서비스 리뷰 책임자 / 팀장의 고정 업무 절차를 제공한다. 외부 스킬이 아직 설치되지 않아도 이 절차는 항상 사용한다. - 제품 처음부터 끝까지 가치·일관성·신뢰·운영 가능성 검토 - 직접 구현하지 않고 실행 가능한 티켓 발행 1. 핵심 사용자 여정 직접 실행 2. BLOCKER/HIGH 우선 분류 3. 근거·사용자 영향·수정 기준 작성 4. 수정 후 원래 acceptance로 재검토 - route_or_service -
- `churn-prevention`: Churn Prevention — --- name: churn-prevention description: "When the user wants to reduce churn, build cancellation flows, set up save offers, recover failed payments, or implement retention strategies. Also use when the user mentions 'churn,' 'cancel flow,'
- `code-review-and-quality`: Code Review and Quality — --- name: code-review-and-quality description: Conducts multi-axis code review. Use before merging any change. Use when reviewing code written by yourself, another agent, or a human. Use when you need to assess code quality across multiple
- `legal-contract-review`: /review-contract -- Contract Review Against Playbook — --- name: review-contract description: Review a contract against your organization's negotiation playbook — flag deviations, generate redlines, provide business impact analysis. Use when reviewing vendor or customer agreements, when you nee
- `pm-critic`: PM Critic (Dispatch Skill) — --- name: utility-pm-critic description: Run adversarial review on a PM artifact via the pm-critic sub-agent. Returns findings graded P0/P1/P2/P3 with a concrete fix suggestion per finding and a machine-readable status block. Use after prod
- `pm-deliver-acceptance-criteria`: Acceptance Criteria — --- name: deliver-acceptance-criteria description: Generates structured Given/When/Then acceptance criteria for a user story or feature slice, covering the happy path, key failure scenarios, and non-functional expectations in testable form.
- `verification-before-completion`: Verification Before Completion — --- name: verification-before-completion description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success cl
