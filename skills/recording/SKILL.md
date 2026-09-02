---
name: recording
description: Use when a user asks to record completed or in-progress work, backfill a workday, or capture project activity in a second-brain vault.
---
# Recording

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow records verified activity through additive Markdown edits.

## Inputs

- The work to record, its date (today unless the user requests a backfill), and the matching project identity when one exists.
- Available evidence such as a commit hash, issue or pull-request reference, test result, work artifact, or direct user confirmation.
- Any lesson the user wants retained and the concrete project cases supporting broader reuse.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. Follow the shared contract's marker-read protocol to obtain the configured daily, projects, knowledge, and reviews paths; do not infer conventional directory names.
3. Resolve today's daily path, or the requested date for an explicit backfill, and the matching project page within the configured projects path. Read the daily note when present. When a matching project page exists, read only its `Current Status`, `Pending`, `Recent Activity`, and `Lessons Learned` sections.
4. Select the write route from observed target state:
   - Daily present: prepare an additive daily entry. Daily missing: draft the note from `templates/vault/daily.md` for later exclusive creation.
   - Project present: prepare a concise project update. Project missing: keep the write set daily-only and report that project routing was skipped. A repository identity, urgency, or otherwise complete evidence does not authorize creating a project page.
5. Deduplicate the activity across the selected targets. Treat a matching commit hash or issue/pull-request reference as the same event. When neither exists, use an exact event fingerprint composed of the work date, project identity, source reference, and outcome; do not merge merely similar activity.
6. Draft an additive narrative under the daily note's `Work Log` and a concise project update in the matching existing sections. Preserve unrelated content and the existing structure. Update `Pending` completion only when the evidence proves completion or the user directly confirms it; otherwise keep the item pending and record the known status.
7. Classify lessons by evidence:
   - Fewer than two concrete, named cases from different projects: keep the lesson under the existing project's `Lessons Learned`. If the project page is missing, retain the observation in the daily entry and report that project and durable-knowledge routing were skipped.
   - At least two concrete, named cases from different projects: the lesson is eligible for the configured knowledge area. Add it to a relevant existing knowledge page after reading that target. Eligibility does not authorize creating a new knowledge page or taxonomy; preview that structural choice and wait for explicit confirmation under the shared contract.
8. Immediately before applying, re-read every existing target and compare it with the version used for the draft. Stop on any drift. For a missing daily note, recheck that it is still absent and use the host's exclusive-create operation; if exclusive creation is unavailable or the path appeared, stop instead of overwriting or merging by guesswork. Then apply only the prepared additive edits with the host's native edit mechanism.

## Safety

- Read and write only the diagnosed vault and the targets selected by this workflow. Never read `secrets` or expose secret payloads.
- Do not create a missing project page implicitly. Do not generalize one project case into durable knowledge.
- Do not infer completion from optimistic wording, elapsed time, or an activity entry; require evidence or direct user confirmation.
- Do not replace whole files, bulk rewrite, move, delete, change taxonomy, commit, or push.

## Output

Report the vault-relative daily path and whether it was additively updated or exclusively created. Report the matching project path as updated or explicitly skipped, list any duplicates omitted, identify every `Pending` item left unchanged for lack of evidence, and state where each lesson remained or was routed. On drift or another stop condition, report no success and give the single next action needed from the user.
