# AI AUTOMATION OFFICE — 24인 Employee Registry v6.2

> 스킬 본문은 공용 풀 `skills/<skill-id>/`에 1부만 두고 부서 바인딩으로 접근을 정한다. 직원 폴더에는 `_local-role-core`만 있다. 세부 역할은 각 직원 폴더의 `EMPLOYEE.md`, `SKILLS.md`에서 관리한다.

## 24인 배치

| 직원 | 팀 | Runtime | 필수 스킬 | 조건부 스킬 | 프로필 |
|---|---|---|---|---|---|
| NAVI | operations-planning | PLANNER | using-agent-skills, planning-and-task-breakdown, executing-plans | agent-orchestration-advisor | `employees/operations-planning/NAVI/EMPLOYEE.md` |
| ROUTE | operations-planning | PLANNER | planning-and-task-breakdown, dispatching-parallel-agents, using-git-worktrees, git-workflow-and-versioning | - | `employees/operations-planning/ROUTE/EMPLOYEE.md` |
| CLOCK | operations-planning | OPERATOR | observability-and-instrumentation, debugging-and-error-recovery, code-simplification | - | `employees/operations-planning/CLOCK/EMPLOYEE.md` |
| FRAME | product-experience | PLANNER | planning-and-task-breakdown, source-driven-development, writing-plans | prd-development, discovery-process, prioritization-advisor, user-story | `employees/product-experience/FRAME/EMPLOYEE.md` |
| FLOW | product-experience | SPECIALIST | ui-ux-pro-max, source-driven-development, customer-research | customer-journey-map, user-story-mapping, discovery-process | `employees/product-experience/FLOW/EMPLOYEE.md` |
| MOSS | product-experience | SPECIALIST | ui-ux-pro-max, impeccable, design-first-ui-prompting, humanizer | gsap-core, gsap-timeline | `employees/product-experience/MOSS/EMPLOYEE.md` |
| BUILD | application | REVIEWER | incremental-implementation, code-simplification, code-review-and-quality, git-workflow-and-versioning | - | `employees/application/BUILD/EMPLOYEE.md` |
| FRONT | application | BUILDER | frontend-ui-engineering, browser-testing-with-devtools, ui-ux-pro-max, gsap-react, gsap-performance | - | `employees/application/FRONT/EMPLOYEE.md` |
| BACK | application | BUILDER | api-and-interface-design, auth-implementation-patterns, sql-optimization-patterns, security-and-hardening | - | `employees/application/BACK/EMPLOYEE.md` |
| LINK | ai-data | REVIEWER | prompt-engineering-patterns, llm-evaluation, rag-implementation | agent-orchestration-advisor | `employees/ai-data/LINK/EMPLOYEE.md` |
| SIGNAL | ai-data | BUILDER | embedding-strategies, hybrid-search-implementation, rag-implementation, sql-optimization-patterns | - | `employees/ai-data/SIGNAL/EMPLOYEE.md` |
| EVAL | ai-data | VERIFIER | llm-evaluation, doubt-driven-development, verification-before-completion, security-and-hardening | - | `employees/ai-data/EVAL/EMPLOYEE.md` |
| SHIP | platform-reliability | OPERATOR | ci-cd-and-automation, shipping-and-launch, git-workflow-and-versioning, verification-before-completion | - | `employees/platform-reliability/SHIP/EMPLOYEE.md` |
| SRE | platform-reliability | OPERATOR | observability-and-instrumentation, debugging-and-error-recovery, systematic-debugging, ci-cd-and-automation | - | `employees/platform-reliability/SRE/EMPLOYEE.md` |
| COST | platform-reliability | OPERATOR | observability-and-instrumentation, code-simplification, source-driven-development | - | `employees/platform-reliability/COST/EMPLOYEE.md` |
| GUARD | quality-security | REVIEWER | code-review-and-quality, verification-before-completion, security-and-hardening, code-review-excellence | - | `employees/quality-security/GUARD/EMPLOYEE.md` |
| TRACE | quality-security | VERIFIER | test-driven-development, systematic-debugging, e2e-testing-patterns, verification-before-completion | - | `employees/quality-security/TRACE/EMPLOYEE.md` |
| SHIELD | quality-security | SPECIALIST | security-and-hardening, auth-implementation-patterns, source-driven-development, doubt-driven-development | - | `employees/quality-security/SHIELD/EMPLOYEE.md` |
| GROW | growth-marketing | SPECIALIST | product-marketing, launch, customer-research | — | `employees/growth-marketing/GROW/EMPLOYEE.md` |
| VOICE | growth-marketing | SPECIALIST | copywriting, humanizer, product-marketing, design-first-ui-prompting | - | `employees/growth-marketing/VOICE/EMPLOYEE.md` |
| PULSE | growth-marketing | SPECIALIST | analytics, ab-testing, cro, seo-audit | - | `employees/growth-marketing/PULSE/EMPLOYEE.md` |
| LENS | service-knowledge | REVIEWER | code-review-and-quality, verification-before-completion, impeccable, ui-ux-pro-max | - | `employees/service-knowledge/LENS/EMPLOYEE.md` |
| JOURNEY | service-knowledge | SPECIALIST | ui-ux-pro-max, cro, customer-research, onboarding | customer-journey-map | `employees/service-knowledge/JOURNEY/EMPLOYEE.md` |
| DOCS | service-knowledge | BUILDER | documentation-and-adrs, writing-skills, source-driven-development, humanizer | - | `employees/service-knowledge/DOCS/EMPLOYEE.md` |

## 공통 규칙

- 직원별 필수 스킬은 설치 후 자기 `skills/<id>/SKILL.md`에 존재해야 한다.
- 실제 모델 호출에는 관련 스킬 1~3개만 로드한다.
- 조건부 스킬은 라이선스·업무 관련성·권한을 통과한 경우에만 설치·로드한다.
- 스킬 자체가 파일·network·shell 권한을 부여하지 않는다.
- lock hash가 일치하지 않으면 실행하지 않는다.
