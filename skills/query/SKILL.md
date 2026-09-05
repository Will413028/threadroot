---
name: query
description: Use when a user asks a question that should be answered from a Threadroot second-brain vault.
---
# Query

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow is read-only and starts with the smallest relevant configured area.

## Inputs

- The user's question and any stated project, topic, or date scope.
- The vault context that normal CLI resolution should select.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. If the host denies access to an external vault, stop and ask the user to add it as an approved working directory.
3. Record the metadata of that root's `.second-brain/config.json`, read that exact marker once, and immediately record its metadata again. If the metadata changed or the document no longer has the diagnosed shape, stop and rerun doctor before searching. Take the four configured path strings from its `paths` object; do not duplicate schema, root, or path validation in prompt logic.
4. Choose the single configured area most relevant to the question. Search filenames and headings there before reading content.
5. Read only matched sections and their explicit links. Follow a link only when it stays inside the diagnosed vault and outside `secrets`.
6. If that evidence is insufficient, widen to the next most relevant configured area and repeat the same filename-and-heading funnel. Do not default to recursive whole-vault, broad daily-log, or Git-history searches. Use full-vault or history scope only when the question specifically requires it and narrower configured evidence has been exhausted.
7. Answer from the collected evidence. Cite vault-relative source paths and label every inference separately from sourced facts.

## Safety

- Remain read-only: do not create, edit, move, or delete files; do not run setup commands or add `--apply`; do not commit or push.
- Never read `secrets`, expose secret payloads, or copy private content into public code.
- Do not hard-code directory names, bypass doctor, weaken CLI validation, or continue after marker drift.
- Do not copy an inaccessible external vault into the current project.

## Output

Lead with the answer. Separate sourced facts from inference, attach vault-relative paths to sourced claims, and state material evidence gaps or scope limits. Do not expose the resolved absolute root or secret content.
