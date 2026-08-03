---
name: customer-support-operations
description: Triage customer issues, define SLA and escalation paths, draft evidence-grounded replies, maintain support-to-product feedback, and prepare auditable helpdesk workflows. Use for support operations, ticket triage, incident communication, knowledge gaps, churn-risk handoff, or customer-success process design. Never impersonate execution or change accounts, billing, or tickets without an approved connector and authorization.
---

# Customer Support Operations

## Workflow

1. Confirm customer, product, channel, severity, impact, timestamps, entitlement, and requested outcome.
2. Separate verified account facts, customer statements, reproduction evidence, and assumptions.
3. Classify: how-to, defect, outage, access, billing, security/privacy, feature request, or abuse.
4. Assign severity from impact and urgency. Never lower security, privacy, billing, or data-loss risk to meet SLA.
5. Route:
   - defect to BUILD/TRACE;
   - outage to SRE;
   - security/privacy to SHIELD/GUARD;
   - billing/account mutation to authorized human or billing system;
   - product feedback to FRAME;
   - knowledge gap to DOCS.
6. Draft response containing acknowledgment, verified facts, next action, owner, timing, and limitations.
7. Record reusable knowledge only after resolution is verified.

## External action gate

- Drafts, triage tables, macros, runbooks, and KB proposals are allowed.
- Ticket changes, refunds, credits, account access, data deletion, and outbound messages require explicit approval and a scoped connector.
- Minimize PII in prompts and artifacts. Do not expose secrets or unrelated customer records.
- When tools are absent, label output `DRAFT/PLAN`; do not claim ticket updates or customer contact.

## Completion evidence

Require case classification, severity basis, owner, escalation, response draft, next checkpoint, and artifact path. Executed actions require provider receipt or immutable case event ID.
