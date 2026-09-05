# Shared Skill Contract

<!-- threadroot-contract
drift=stop
secrets=never-read
new-file=claim-verify-native-edit
claim-failure=stop
claim-verification=same-identity-empty-regular
partial-state=preserve-and-report
outside-vault-create=independent-native-exclusive-or-omit
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

## New-file claim protocol

For an authorized missing vault file, finish the semantic draft in the host first. Require an existing safe parent; if it is missing, report the unmet precondition and stop this file workflow. Invoke the claim-preview inventory entry with the diagnosed vault and the exact vault-relative target. Require exit 0, one JSON object with the existing result shape, `ok=true`, `command=claim`, `applied=false`, the diagnosed `vault`, exactly one `create_file` change for that target with `status=planned`, and no issues. Missing executable, unsupported command, malformed or mismatched output, unsafe path, or conflict means stop without any native create or edit. Do not install or substitute another write mechanism.

With the workflow's explicit apply intent, invoke the claim-apply inventory entry. Require the same checks with `applied=true` and `status=completed`. A successful apply reserves one zero-byte file; it has not written the draft. Immediately observe the target with the host's native metadata capability without following a link, record its file identity (`device` and `inode` on supported systems), and require a regular file of size zero. Immediately before the native edit, repeat that observation and require the identical identity, regular type and zero size. If the host cannot establish this evidence, stop. Under the cooperative-session threat model the successful exclusive claim and these observations bind the reservation; they do not protect against malicious replacement between the CLI and first observation.

Only then fill the reserved file with the host's native edit mechanism. A generic native Write or an absence check is not exclusive-create proof. Another session's existing empty file is a collision, never a reservation to reuse. If apply succeeded but verification or native editing fails, report the visible empty reservation or partial edit and every unexecuted action. Do not delete, roll back, retry as an existing-file edit, or report that nothing was created. A failed or malformed apply result with possible completed actions must also be reported as uncertain partial state, not proof of zero writes. Existing files continue to use read/draft/re-read/drift-stop/native-edit.

A proposed local adapter outside the diagnosed vault is omitted unless its parent already exists, the host independently guarantees exclusive native creation, the exact adapter path is already ignored by Git, and the adapter is a native auto-loaded convention. The vault claim command never authorizes that outside path.

## Safety

- The agent never reads `secrets`, prints secret payloads, or copies private content into public code.
- The agent does not commit or push without a direct request.
- The agent previews structural moves, bulk rewrites, taxonomy changes, and deletion, then waits for explicit confirmation.
