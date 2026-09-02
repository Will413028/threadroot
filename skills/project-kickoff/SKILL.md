---
name: project-kickoff
description: Use when a user explicitly starts a new software, client, or product project in a Threadroot second-brain vault.
---
# Project Kickoff

<!-- threadroot-contract
extends=../README.md
confirmation-order=identity,purpose,repository-visibility,target-user,public-private-boundary
confirmation-cadence=one-per-turn
local-adapter=host-native-auto-loaded-and-already-git-ignored
write-gate=complete-preview-and-explicit-approval
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow creates a reviewed project page and, only when safe, one host-native local adapter.

## Inputs

- The project identity and intended repository target.
- Its purpose, repository visibility, target user, and public/private boundary.
- The active host and any user-supplied project context.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. Follow the shared contract's marker-read protocol for `.second-brain/config.json` to obtain the configured daily, projects, knowledge, and reviews paths; use the projects path rather than assuming a conventional directory.
3. Confirm these five inputs in order: project identity, purpose, repository visibility, target user, then public/private boundary. Ask exactly one unanswered or unconfirmed question per turn and wait for its answer before asking the next. A deadline, a request to defer or skip questions, future open-source intent, or company-facing context does not answer any of them; do not infer or batch them.
4. Inspect the intended repository target before proposing structure. Record whether it exists, whether it is a Git worktree, its tracked instruction files recognized by the active host, and its existing ignore rules. Read only the instruction and ignore material needed for this kickoff. Do not initialize a repository or alter ignore rules during inspection.
5. Derive the project slug from the confirmed identity and present the exact project-page path as `<resolved configured projects path>/<slug>/index.md`. Stop on a collision; never overwrite an existing project page.
6. Determine local-adapter eligibility from two independent facts:
   - The active host has a native, auto-loaded local-instruction convention with one exact path at this target.
   - That exact proposed path is already ignored by Git under the inspected rules.

   Propose the local adapter only when both facts are verified. Otherwise state `No safe local adapter discovered` and omit it from the write set. Do not invent an inert instruction filename, edit an ignore file, or add a rule to manufacture eligibility.
7. Draft the project page from `templates/vault/project.md`, replacing every placeholder while preserving its section structure. Put concrete next actions under `Pending`. If an adapter is eligible, draft only the private project context needed locally. Apply the confirmed public/private boundary to every draft: private paths, private identities, personal workflows, and company context must not enter tracked public files.
8. Show one complete preview covering every proposed path: each directory to create, each file's exact path, its tracked/public or ignored/private status, and the complete file content. Include no unpreviewed path. Ask for explicit confirmation of that exact write set and wait; urgency or earlier general permission is not confirmation of the preview.
9. Immediately before the first write, re-read the target, tracked instructions, ignore state, and every existing target used for the preview. On drift or a collision, stop before mutation, report that nothing was created, and rebuild the preview. Otherwise recheck every new file's absence and apply the previewed actions one at a time in their displayed order, using exclusive creation for files. Record each created path. If an action fails, stop the remaining actions, preserve every completed action, and report each unexecuted path and pending repair; never roll back a completed action. Create only the project page, the confirmed eligible adapter, and their currently required parent directories.
10. Treat repository initialization, publication, commit, and push as separate actions requiring separate authorization. They are never part of kickoff confirmation.

## Safety

- Never guess, defer as a batch, or silently default the five confirmed inputs.
- Never create files before the complete preview is explicitly confirmed. Never overwrite a collision, continue after drift, hide partial state, or roll back a completed action.
- Never invent a local adapter, change ignore rules to permit one, initialize or publish a repository, read `secrets`, expose secret payloads, or copy private context into tracked public files.
- Do not create speculative directories or files, commit, or push.

## Output

Before confirmation, report the exact project-page path, adapter eligibility with its evidence or `No safe local adapter discovered`, and the complete proposed write set. A pre-write stop reports that nothing was created and gives the next action. Once apply starts, report every completed path, every unexecuted path, and each pending repair, then list concrete `Pending` work; never claim that nothing was created when an earlier action succeeded.
