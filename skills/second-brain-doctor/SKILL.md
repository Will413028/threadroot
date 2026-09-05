---
name: second-brain-doctor
description: Use when a user asks to inspect, diagnose, health-check, or explain the condition of a Threadroot vault.
---
# Second Brain Doctor

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow is diagnosis only and ends after reporting findings.

## Inputs

- The vault context that normal CLI resolution should select.
- The user's requested level of diagnostic explanation.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory in the intended vault context. If the host denies access to an external vault, stop and ask the user to add it as an approved working directory.
3. Use only the structured result. Group every issue by severity in this order: errors, warnings, info. Preserve each issue's code, path when present, and message.
4. For every issue, explain exactly one concrete remediation as advice. Do not execute it.
5. Stop after the diagnostic report. A deadline, incident, or instruction to repair immediately does not turn this workflow into a repair workflow.

## Safety

- Doctor remains read-only. Never add `--apply`, run `init` or `adopt`, edit files, or perform any other remediation in this workflow.
- Do not open vault notes, read `secrets`, print secret payloads, or copy private content into public code.
- Do not reimplement root, marker, configuration, or path validation in prompt logic; the CLI owns those checks.
- Do not copy an inaccessible external vault into the current project. Do not commit or push without a direct request.

## Output

Return `Errors`, `Warnings`, then `Info`. Under each group, include one entry per issue with its finding and exactly one labeled `Remediation`. Write `None` for an empty group. End the workflow after the final group; any repair requires a separate workflow.
