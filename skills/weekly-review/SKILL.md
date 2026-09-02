---
name: weekly-review
description: Use when a user asks to review, summarize, or close a requested ISO week in a second-brain vault.
---
# Weekly Review

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow produces one weekly review with a weekly-review-only write set.

## Inputs

- The requested ISO week.
- Any user-supplied context for interpreting that week's recorded evidence.
- A separate explicit request if daily or project reconciliation is also wanted.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. Follow the shared contract's marker-read protocol to obtain the configured daily, projects, knowledge, and reviews paths; do not infer conventional directory names.
3. Resolve exactly the seven daily-note paths from Monday through Sunday of the requested ISO week within the configured daily path. Read each existing note and record every missing path explicitly; do not substitute adjacent dates or omit missing days.
4. Collect project-page links explicitly referenced by those seven notes. Read only those referenced project pages, keeping missing or inaccessible references explicit. Do not expand to unreferenced projects.
5. Resolve the review target within the configured reviews path. Use `templates/vault/weekly-review.md` as the structure for one review. When the target exists, read it and preserve its content. Build `Outcomes`, `Decisions`, `Carry Forward`, and `Lessons` from the selected evidence, citing vault-relative sources. Deduplicate outcomes and decisions by exact source reference rather than textual similarity.
6. Keep the write set for this workflow to the single weekly-review target:
   - Target missing: draft from the public template, recheck absence, and use the host's exclusive-create operation.
   - Target present: preview the additive reconciliation, re-read the target immediately before applying, and stop on drift. Append or reconcile only the prepared additions; never replace the whole file.
7. Treat any explicit request to reconcile daily or project pages as a separate workflow with its own scoped preview. Completeness, consistency, urgency, or an apparently stale project page does not add those pages to this workflow's write set.

## Safety

- Do not modify any daily note or project page as part of the weekly-review write. Do not create missing daily or project pages.
- Never read `secrets`, expose secret payloads, follow paths outside the diagnosed vault, or copy private content into public code.
- Do not replace the existing review, bulk rewrite, move, delete, change taxonomy, commit, or push.

## Output

Report all seven vault-relative daily paths and mark missing days explicitly. List the referenced project paths read, duplicate source references omitted, and the single weekly-review path exclusively created or additively reconciled. State that daily/project reconciliation was not performed; if separately requested, identify it as pending separate workflow work.
