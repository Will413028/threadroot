---
name: second-brain-setup
description: Use when a user wants to connect Threadroot to a missing, empty, or existing second-brain vault.
---
# Second Brain Setup

<!-- threadroot-contract
extends=../README.md
-->

<!-- threadroot-commands
threadroot --version
threadroot init --vault <target> --json
threadroot adopt --vault <target> --json
threadroot init --vault <target> --json --apply
threadroot adopt --vault <target> --json --apply
threadroot doctor --vault <target> --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding.

## Inputs

- The target vault location.
- Whether the user directly requested applying setup now.
- Whether the target should become the default vault.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Inspect only the target's existence, directory entries, and metadata needed to select a command. If the host denies access to an external target, stop and ask the user to add it as an approved working directory.
3. Select by observed state:
   - For a missing or empty target, including one whose only entry is `.git`, run the init-preview entry from the command inventory.
   - For an existing non-empty target, run the adopt-preview entry from the command inventory and let the CLI validate whether its layout is recognized.
   - If the user requested a default vault, append `--set-default` to both the preview and the matching apply command.
4. Show the complete preview: the resolved vault, every planned change, and every issue. Stop on a failed preview, a conflict, an unsupported layout, or any unexpected destructive change.
5. Obtain explicit apply intent. A direct request to apply or complete setup now qualifies; urgency by itself does not. Without apply intent, wait after the preview.
6. Immediately before applying, re-read the target and marker metadata. If either drifted since the preview, stop and rerun the preview. If marker content is read, compare its metadata immediately before and after that single read; stop and rerun diagnosis if it changed or no longer has the diagnosed shape.
7. Apply the matching preview with exactly the corresponding init-apply or adopt-apply entry from the command inventory, preserving any requested `--set-default` flag. Do not switch commands or add unpreviewed flags.
8. Finish with the doctor entry from the command inventory. Report success only for an exit-0 result.

## Safety

- `init` is only for missing or empty targets. `adopt` is only for existing recognized layouts and may add only `.second-brain/config.json`.
- Neither command moves, renames, or rewrites existing notes. Stop if the preview proposes otherwise.
- Do not install software automatically, read `secrets`, print secret payloads, or copy private vault content into public code.
- Do not reimplement root, marker, configuration, or path validation in prompt logic; use the CLI result.
- Leave partial failures visible. Do not clean up, commit, or push without a direct request.

## Output

Before mutation, present the complete preview and whether explicit apply intent is present. After an apply attempt, report the applied changes and the final doctor result. On any stop condition, report the reason and the single next action needed from the user.
