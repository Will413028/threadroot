# Shared Skill Contract

<!-- threadroot-contract
drift=stop
secrets=never-read
-->

These public skills are provider-neutral and use `the agent`, `the model`, and `the host` for shared roles.

## Skill format

- Frontmatter contains only `name` and a trigger-focused `description`.
- Each skill contains `Inputs`, `Procedure`, `Safety`, and `Output` sections.
- The agent reads only files needed for the active workflow.

## CLI and vault boundary

1. Before any CLI-dependent workflow, the agent runs `threadroot --version`. If the executable is unavailable, the agent stops and points to the repository installation instructions. The agent does not install software automatically.
2. Before semantic work, the agent runs `threadroot doctor --json` and requires an exit-0 result. The agent uses the result's `vault` field as the resolved vault root; prompt logic must not duplicate or weaken CLI validation.
3. The agent records the metadata of that root's `.second-brain/config.json`, reads that exact marker once to obtain the four configured path strings, and immediately checks its metadata again. If the metadata changed during the read or the document no longer has the diagnosed shape, the agent stops and reruns diagnosis.
4. If the host denies access to an external vault, the agent stops and asks for that vault to be added as an approved working directory. The agent never copies the vault into the current project as a workaround.
5. Before editing, the agent re-reads the target and stops if it drifted. Markdown semantic edits use the host's native read and edit tools, not the CLI.

## Safety

- The agent never reads `secrets`, prints secret payloads, or copies private content into public code.
- The agent does not commit or push without a direct request.
- The agent previews structural moves, bulk rewrites, taxonomy changes, and deletion, then waits for explicit confirmation.
