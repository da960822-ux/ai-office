---
name: sales-operations
description: Design evidence-backed sales pipelines, qualification rules, CRM fields, handoffs, forecasts, and approval-gated outreach. Use for sales process design, CRM planning, lead qualification, pipeline reviews, sales-to-product feedback, or preparing controlled outbound work. Never send messages or mutate a CRM without an approved connector and explicit authorization.
---

# Sales Operations

## Workflow

1. Confirm offer, ICP, territory, channel, owner, target period, and success metric.
2. Consume approved product, positioning, pricing, and market evidence. Do not redefine them.
3. Define lifecycle stages with entry, exit, owner, required evidence, and stale-opportunity rules.
4. Define qualification criteria and disqualification reasons. Separate observed facts from seller judgment.
5. Define minimum CRM schema: account, contact, consent/source, opportunity, stage, value, probability, next action, owner, timestamps, loss reason.
6. Produce pipeline math with explicit assumptions. Never fabricate contacts, activity, conversion, or revenue.
7. Define product, marketing, support, and finance handoffs.
8. Return a file-ready operating plan plus unresolved permissions and risks.

## External action gate

- Drafting sequences, fields, reports, and enablement material is allowed.
- Reading or writing CRM data requires a configured scoped connector.
- Sending email, changing opportunity stage, creating contacts, or exporting PII requires explicit approval.
- Respect opt-out, consent, retention, regional privacy, and platform rules.
- When source records are unavailable, label output `DESIGN ONLY`; do not claim execution.

## Completion evidence

Require pipeline definitions, owner map, field dictionary, metric formulas, approval points, and exact artifact path. For executed work also require connector receipts or immutable action IDs.
