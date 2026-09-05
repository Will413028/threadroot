---
name: morning-review
description: Use when a user starts a workday, asks what to do today, or requests a morning review or short daily focus from a second-brain vault.
---
# Morning Review

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow is read-only.

## Inputs

- Today's date and any project, goal, deadline, or capacity constraints supplied by the user.
- The vault context that normal CLI resolution should select.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. Follow the shared contract's marker-read protocol to obtain the configured daily, projects, knowledge, and reviews paths; do not infer conventional directory names.
3. Resolve today's note within the configured daily path. Read it when present. If it is missing, keep the absence explicit as an evidence gap and continue without creating it.
4. Within the configured projects path, identify active project pages and read only their `Current Status` and `Pending` sections. Collect unchecked `Pending` items; do not read unrelated project sections.
5. Read a goal page only when the user supplied its path and it resolves within the diagnosed vault, or a selected daily or project page explicitly links to it. Schema v1 has no implicit goals directory, so an unlinked goals area is outside this review.
6. Sort the collected candidates into `Executable Work`, `Unresolved Choices`, and `Vague Ideas`. Executable work has a concrete next action; unresolved choices need a decision; vague ideas need clarification before scheduling.
7. Select at most three `Focus` items from executable work. Give each an explicit completion condition and cite its vault-relative project or permitted goal source path. Return fewer than three when the evidence does not support three actionable items.

## Safety

- Remain read-only: do not create or edit today's note, project pages, goal pages, or any other vault content.
- Never read `secrets`, expose secret payloads, follow links outside the diagnosed vault, or copy private content into public code.
- Do not hard-code vault directories, weaken CLI validation, install software, commit, or push.

## Output

Lead with up to three numbered `Focus` items, each with its completion condition and vault-relative project or goal source. Then list `Unresolved Choices` and `Vague Ideas` separately. State whether today's daily note was present, identify material evidence gaps, and report the scope reviewed without exposing the absolute vault root.
