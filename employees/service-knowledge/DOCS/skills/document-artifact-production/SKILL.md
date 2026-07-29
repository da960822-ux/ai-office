---
name: document-artifact-production
description: Create and validate real document artifacts for reports, plans, specifications, meeting records, manuals, and office deliverables. Use when work must end with a Markdown, DOCX, PDF, HWP, spreadsheet, or presentation file rather than a chat-only answer.
---

# Document Artifact Production

## Required outcome

Produce a real file inside the assigned workspace. A message, database summary, or code block that merely describes a document is not a deliverable.

## Workflow

1. Read the task contract and `references/deliverable-rules.md`.
2. Select the requested format. When no format is specified, create UTF-8 Markdown.
3. Build the document around the required sections for its artifact kind.
4. Write the file under `AI_OFFICE_OUTPUTS/<TASK-ID>/`.
5. Verify the file exists, opens, and contains substantive content.
6. For DOCX, PDF, spreadsheets, or slides, use the matching artifact skill and perform its render or structural QA.
7. Report the exact relative and absolute output path. Never report completion without the file.

## Integration rule

Department files are drafts. The designated final owner must reconcile contradictions, choose one recommendation when required, and produce one final file. Concatenating drafts is not integration.

## Failure rule

Block completion when the requested file is absent, empty, outside the assigned workspace, missing required sections, or not visually/structurally verified for its format.

## References

- Read `references/deliverable-rules.md` for artifact-specific minimum content and evidence rules.
