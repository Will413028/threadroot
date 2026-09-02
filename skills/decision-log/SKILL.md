---
name: decision-log
description: Use when a user wants to record or supersede a durable A-over-B decision in a Threadroot second-brain vault.
---
# Decision Log

<!-- threadroot-contract
extends=../README.md
decision-gate=two-or-more-real-alternatives-and-actual-trade-off
draft-gate=complete-draft-and-explicit-approval
followup-routing=deduplicate-into-project-pending
project-backlink=key-decisions
supersession=bidirectional
-->

<!-- threadroot-commands
threadroot --version
threadroot doctor --json
-->

Read and follow the [shared skill contract](../README.md) before proceeding. This workflow records an auditable choice without rewriting its history.

## Inputs

- The proposed choice, its scope, and the matching project when it is a product decision.
- At least two real alternatives, the actual trade-off accepted, and the expected outcome.
- Any Followup work, superseded decision, and external provenance supplied by the user.

## Procedure

1. Run the version-check entry from the command inventory. If it is unavailable, stop, point to the repository installation instructions, and do not install it.
2. Run the doctor entry from the command inventory and require exit 0. Use its `vault` field as the resolved root. Follow the shared contract's marker-read protocol for `.second-brain/config.json` to obtain the configured daily, projects, knowledge, and reviews paths; use configured paths rather than conventional directory names.
3. Classify the candidate before drafting. It is a genuine choice only when the evidence names at least two real alternatives and an actual trade-off: a concrete cost, risk, constraint, or benefit forgone by the selected option. Preference, authority to proceed, or naming rejected options without an accepted trade-off is insufficient. If the condition is unmet, report `Not ready for ADR`, list the missing decision material, ask for it, and stop without drafting or writing.
4. Resolve scope. Route a product decision to the matching existing project under `<configured projects path>/<project>/decisions/<date>-<slug>.md`; its project page is `<configured projects path>/<project>/index.md`. Read the project page sections needed for Pending and Key Decisions. Resolve the exact decisions directory, verify that it remains inside both the diagnosed vault and matching project, and inspect its state. A missing directory is a required structural change; an existing directory requires no speculative change, while a file, unsafe symlink, or escaping path is a stop. If no matching project exists, or a non-product scope has no confirmed existing destination, stop for a routing decision rather than creating taxonomy.
5. Draft from `templates/vault/decision.md`. Keep the ADR self-contained and preserve these sections in order: `Context`, `Options Considered`, `Decision`, `Rationale`, `Expected Outcome`, `Followup`, `Review Notes`, and `Related`. Options must describe the real alternatives; Rationale must state the accepted trade-off; Expected Outcome must be observable. When work remains, Followup contains concrete actions; otherwise write `None`. Related links back to the project page and records external provenance only as retrievable URLs, pull-request or issue identifiers, or commit hashes.
6. When replacing an obsolete ADR, prepare a superseding ADR instead of deleting the old one. Add a `supersedes` relationship from the new ADR and a `superseded by` relationship to the old ADR so both directions are navigable. Preserve the old ADR's content and history.
7. Prepare the project-page patch by deduplicating each actionable Followup against existing Pending items and adding the new ADR under Key Decisions. Preserve unrelated text. Show the exact new ADR path, the complete ADR draft, the complete project-page patch, any complete supersession patch, and the exact decisions-directory creation when that directory is missing. Obtain explicit approval for this complete write set. A deadline, authority to replace an ADR, or an instruction to skip preview never waives the complete-draft review and approval gate.
8. After approval, re-read the project page, decisions-directory state, and any superseded ADR. Re-resolve the directory and verify containment again; stop and rebuild the preview on drift. When the approved preview includes the missing directory, recheck that it is absent and safely create that exact directory, recording the completed path. If the directory appeared or became unsafe, stop without using it. When it already existed at preview time, require the same safe directory state and create nothing. Then recheck the new ADR path:
   - Missing: use the host's exclusive-create operation.
   - Existing with content exactly matching the approved draft: treat the ADR write as a no-op.
   - Existing with different content: stop and ask for a naming decision; never overwrite it.
9. If directory or ADR creation fails, stop subsequent writes, leave the project page unchanged, and report every completed path, unexecuted path, and pending repair. After a successful ADR create or matching-content no-op, re-read each existing update target immediately before applying the approved additive patches. Deduplicate Followup into Pending, add the Key Decisions backlink, and add the reverse supersession link when applicable.
10. Keep every partial result visible. If the directory or ADR exists but a later action fails, report all completed paths and each pending repair. Do not delete or roll back the directory, ADR, or any other completed action.

## Safety

- Do not create an ADR without two real alternatives and an actual trade-off. Do not bypass the complete-draft approval gate.
- Missing decisions directories are created only as an approved, revalidated, contained write. New ADR paths are exclusive-created. Never overwrite a collision, delete or replace an obsolete ADR, hide partial failure, continue after drift, or roll back completed work.
- Never read `secrets`, expose secret payloads, create unconfirmed taxonomy, publish a repository, commit, or push.

## Output

Lead with `Genuine choice` or `Not ready for ADR` and the supporting decision material. Before writing, report every exact file and directory path and show the complete draft and patches awaiting approval. After writing, report the decisions directory as pre-existing or created, the ADR as created or matching-content no-op, the project Pending and Key Decisions updates, both supersession directions when applicable, and retrievable provenance. End with every completed path, unexecuted path, and concrete pending repair or Followup item.
