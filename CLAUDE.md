# AI Office — 스킬 구조 가이드

## 정정

`skills/`의 102개는 **이 세션(Claude Code)이 쓰는 스킬이 아님.** 이 프로젝트는 자체 에이전트
런타임을 갖고 있고(`registry/role-core-template.md` 참고), 스킬은 `employees/<team>/<ID>`로
시뮬레이션되는 워커·팀장 에이전트에게 `TaskContract` 통해 배정됨. 그 런타임은 `list_files`,
`search_files`, `replace_exact_text`, `apply_unified_patch`, `run_verification` 같은 자체 툴셋을
쓰고, 내 Bash/Edit/Read와는 별개임. 팀장이 업무마다 부서 스킬 풀에서 3개를 골라 워커에게 준다.

## 조직 구조 (`registry/department-boundaries.json`, `employees.json` 기준)

| 부서 | Stage | Lead | Workers | 책임 범위 | 반드시 넘기는 것 |
|---|---|---|---|---|---|
| operations-planning | 0 | NAVI | ROUTE, CLOCK | 요청 정규화, TaskContract, 라우팅, 인계, 일정·예산 | 제품 결정, 구현, 마케팅 결론, 보안 승인 |
| product-experience | 1 | FRAME | FLOW, MOSS | 문제 정의, PRD, 인수 기준, UX/UI 명세 | 코드 구현, 시장 규모, 배포, 보안 승인 |
| growth-marketing | 1 | GROW | VOICE, PULSE | 시장·고객 리서치, 포지셔닝, 카피, 분석·실험 | 제품 승인, UI 설계, 코드 구현, 릴리즈 |
| application | 2 | BUILD | FRONT, BACK | 기술 설계, 프론트·백엔드 구현, 통합 리뷰 | 제품 범위, 시장 조사, 릴리즈 승인, 독립 QA |
| ai-data | 2 | LINK | SIGNAL, EVAL | AI 아키텍처, 검색·데이터 파이프라인, 모델 평가 | 제품 범위, UI 설계, 배포, 보안 승인 |
| platform-reliability | 3 | SHIP | SRE, COST | 릴리즈, CI/CD, 관측성, 신뢰성·비용 | 기능 요구사항, 구현 소유권, 비즈니스 권고 |
| quality-security | 3 | GUARD | TRACE, SHIELD | 독립 테스트, 보안·프라이버시 리뷰, 증거 게이트 | 기능 구현, 비즈니스 전략, UI 저작 |
| service-knowledge | 3 | LENS | JOURNEY, DOCS | 서비스 여정 리뷰, 문서화, 지식 패키징 | 시장 결정, 코드 구현, 보안 승인, 배포 |

경계는 `must_handoff` 위반 금지 — 남의 부서 일 대신 완료시키는 게 이 시스템에서 가장 비싼 실패
(`role-core-template.md` 섹션2). 완료 인정은 파일+해시+`run_verification` 결과+독립 리뷰어 통과
네 가지 모두 있어야 함(섹션6). `git push`/`deploy`/`sudo`/`rm -rf` 등은 계약과 무관하게 항상 차단.

## 부서별 스킬 바인딩 (`registry/employee-skill-bindings.json`, 그대로 옮김)

**operations-planning**: dispatching-parallel-agents, executing-plans, subagent-driven-development,
systematic-debugging, using-agent-skills, writing-plans

**product-experience**: customer-research, design-first-ui-prompting, humanizer, impeccable,
pm-define-hypothesis, pm-define-jtbd-canvas, pm-define-prioritization-framework,
pm-define-problem-statement, pm-deliver-prd, pm-deliver-user-stories, pm-develop-solution-brief,
pm-discover-competitive-analysis, pm-discover-market-sizing, pm-foundation-lean-canvas, writing-plans

**application**: api-and-interface-design, architecture-patterns, auth-implementation-patterns,
browser-testing-with-devtools, code-review-and-quality, code-simplification,
documentation-and-adrs, error-handling-patterns, executing-plans, frontend-ui-engineering,
git-workflow-and-versioning, gsap-performance, gsap-react, incremental-implementation,
openapi-spec-generation, performance-optimization, receiving-code-review, requesting-code-review,
security-and-hardening, spec-driven-development, sql-optimization-patterns,
subagent-driven-development, systematic-debugging, test-driven-development, using-git-worktrees,
verification-before-completion, writing-plans

**ai-data**: context-engineering, doubt-driven-development, embedding-strategies,
hybrid-search-implementation, llm-evaluation, prompt-engineering-patterns, rag-implementation,
security-and-hardening, sql-optimization-patterns, verification-before-completion

**platform-reliability**: ci-cd-and-automation, cost-optimization, deployment-pipeline-design,
distributed-tracing, finance-driver-based-model, finance-unit-economics,
git-workflow-and-versioning, github-actions-templates, gitops-workflow, helm-chart-scaffolding,
incident-runbook-templates, k8s-manifest-generator, multi-cloud-architecture,
observability-and-instrumentation, on-call-handoff-patterns, postmortem-writing,
prometheus-configuration, secrets-management, shipping-and-launch, slo-implementation,
systematic-debugging, terraform-module-library, verification-before-completion

**quality-security**: auth-implementation-patterns, code-review-and-quality, e2e-testing-patterns,
gdpr-data-handling, legal-compliance-check, legal-risk-assessment, receiving-code-review,
requesting-code-review, sast-configuration, screen-reader-testing, secrets-management,
security-and-hardening, security-requirement-extraction, stride-analysis-patterns,
systematic-debugging, test-driven-development, verification-before-completion

**growth-marketing**: ab-testing, analytics, brand-voice-analyzer, churn-prevention, copywriting,
cro, customer-research, humanizer, launch, pm-deliver-launch-checklist, pm-measure-experiment-design,
pm-measure-experiment-results, product-marketing, sales-enablement, sales-operations, seo-audit,
startup-metrics-framework

**service-knowledge**: churn-prevention, customer-research, customer-support-operations,
document-artifact-production, documentation-and-adrs, incident-runbook-templates,
legal-contract-review, onboarding, openapi-spec-generation, pm-critic,
pm-deliver-acceptance-criteria, pm-discover-interview-synthesis, pm-foundation-meeting-synthesize,
postmortem-writing, sales-enablement, verification-before-completion, writing-skills

바인딩 안 된 스킬(`ml-pipeline` 등은 이 목록에 없음 — `skills/`에 있어도 어느 부서에도 배정 안
됐을 수 있음)은 `registry/skill-definitions.json`, `skill-sources.json` 대조해서 확인 필요.
이 문서에 없는 이름을 부서 것으로 단정하지 말 것.

## 내(Claude Code 세션)가 실제 쓰는 것

이 repo에서 내가 직접 작업할 땐 위 registry가 아니라 평소 전역/로컬 스킬(`code-reviewer`,
`systematic-debugging` 등)을 씀. operations-planning 바인딩과 역할이 겹치는 편이지만 내가 그
department를 대신하는 게 아님 — 나는 이 시스템 바깥에서 코드/구성 파일을 고치는 협업자일 뿐.

## TODO — registry에 없는 오케스트레이션 계층 (실제 공백, skill-creator로 제작 검토)

8개 부서 바인딩 어디에도 없는 것들. `operations-planning`이 라우팅/인계는 책임지지만 아래는
안 다룸:

1. `model-routing` — `registry/model-routing.json`이 설정 파일로는 있음, 이걸 다루는 방법론
   스킬은 없음
2. `model-cost-governance`
3. `agent-memory-architecture`
4. `prompt-injection-defense`
5. `tool-permission-governance` — `TaskContract`가 코드로 강제하긴 하지만 설계 방법론 스킬은 없음
6. `sandboxed-execution`
7. `agent-contract-testing` — `TaskContract` 자체를 테스트하는 스킬

### 커스텀 스킬 후보 (실제 배정 전엔 아무 부서 것도 아님 — 어느 department에 바인딩할지부터 정할 것)
- `aioffice-agent-contracts`
- `aioffice-skill-registry`
- `aioffice-budget-controller`
- `aioffice-agent-permission-policy`
- `aioffice-evaluation-suite`

먼저 `registry/skill-definitions.json`, `task-profiles.json` 읽고 기존 규약과 안 겹치는지
확인한 뒤 skill-creator로 착수.
