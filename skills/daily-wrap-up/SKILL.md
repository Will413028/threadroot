---
name: daily-wrap-up
description: Use when a user says the workday is over, asks to wrap up today, or requests a daily second-brain closeout.
---
# Daily Wrap-Up

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow closes the day from explicit records and evidence.

## Inputs

- Today's date and any work evidence, status corrections, decisions, or follow-ups supplied by the user.
- Direct creation intent if today's daily note does not exist.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. Follow the shared contract's marker-read protocol to obtain the configured daily, projects, knowledge, and reviews paths; do not infer conventional directory names.
3. Resolve today's note within the configured daily path. If it is absent and the user has not directly authorized creating it, disclose that no day record exists, ask whether to create it from `templates/vault/daily.md`, and stop. A request to wrap up or avoid questions, fatigue, a deadline, or available commits is not creation intent.
4. When today's note exists, read only its `Focus` and `Work Log`. If the user directly authorized creation, use the public daily template as the draft base. From those daily sections and user-supplied work evidence, collect only explicitly referenced project paths; read only the existing project sections relevant to status, pending work, recent activity, decisions, and lessons.
5. Build an evidence ledger from the selected daily sections, the selected project sections, direct user statements, and supplied trustworthy artifacts. Label user-supplied or external evidence. Do not use Git history to invent or reconstruct unrecorded non-code activity.
6. Reconcile every evidenced item as `Completed`, `In Progress`, `Blocked`, `Decision`, or `Follow-up`. Preserve unknowns instead of filling gaps. When completion is ambiguous, show the proposed interpretation and missing evidence, and keep the project's `Pending` item unchanged until the user confirms completion.
7. Draft additive updates to the daily note's existing sections and concise updates to the referenced project pages. Preserve unrelated text and structure. Identify durable decision and lesson candidates, but do not create or modify a separate durable page without a separate routing request.
8. Immediately before applying, re-read each existing target and compare it with the version used for the draft; stop on any drift. For an explicitly authorized missing daily note, recheck absence and use the host's exclusive-create operation. Apply only the prepared additive edits with the host's native edit mechanism.

## Safety

- Never invent work, status, completion, decisions, blockers, or follow-ups. Keep conflicting or incomplete evidence visible.
- Never read `secrets`, expose secret payloads, follow paths outside the diagnosed vault, or copy private content into public code.
- Do not create the daily note without direct creation intent. Do not replace whole files, bulk rewrite, move, delete, change taxonomy, commit, or push.

## Output

Report the vault-relative daily and project paths updated, the reconciliation by status, evidence gaps, and durable decision or lesson candidates. End with `Carry Forward`: each incomplete, blocked, or follow-up item, its next action when known, and its vault-relative source path. If today's daily note is missing without creation intent, report that no day record exists, ask the creation question, and report no write.
