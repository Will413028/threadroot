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
threadroot claim --path <relative> --vault <vault> --json
threadroot claim --path <relative> --vault <vault> --json --apply
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
4. Resolve scope. Route a product decision to the matching existing project under `<configured projects path>/<project>/decisions/<date>-<slug>.md`; its project page is `<configured projects path>/<project>/index.md`. Read the project page sections needed for Pending and Key Decisions. Resolve the exact decisions directory, verify that it remains inside both the diagnosed vault and matching project, and inspect its state. Require an existing safe directory: a missing parent is an unmet precondition and stops this workflow, as does a file, unsafe symlink, or escaping path. If no matching project exists, or a non-product scope has no confirmed existing destination, stop for a routing decision rather than creating taxonomy. Observe the ADR target now; read it only if it already exists before entering the new-file route.
5. Draft from `templates/vault/decision.md`. Keep the ADR self-contained and preserve these sections in order: `Context`, `Options Considered`, `Decision`, `Rationale`, `Expected Outcome`, `Followup`, `Review Notes`, and `Related`. Options must describe the real alternatives; Rationale must state the accepted trade-off; Expected Outcome must be observable. When work remains, Followup contains concrete actions; otherwise write `None`. Related links back to the project page and records external provenance only as retrievable URLs, pull-request or issue identifiers, or commit hashes.
6. When replacing an obsolete ADR, prepare a superseding ADR instead of deleting the old one. Add a `supersedes` relationship from the new ADR and a `superseded by` relationship to the old ADR so both directions are navigable. Preserve the old ADR's content and history.
7. Prepare the project-page patch by deduplicating each actionable Followup against existing Pending items and adding the ADR under Key Decisions. Preserve unrelated text. Show the exact ADR path, the complete ADR draft, the complete project-page patch, and any complete supersession patch. Require existing parents; no directory creation belongs in this write set. Obtain explicit approval for this complete write set. A deadline, authority to replace an ADR, or an instruction to skip preview never waives the complete-draft review and approval gate.
8. After approval, re-read the project page, decisions-directory state, and any superseded ADR. Re-resolve the directory and verify containment again; stop and rebuild the preview on drift. Require the same existing safe parent. Use the target state observed before the new-file route:
   - Missing at preview: follow the shared new-file claim protocol: claim preview, claim apply, native same-identity/empty/regular verification, then native edit. Any path that appears after the absent preview is always a collision, including an empty or apparently matching file; never read competing bytes to justify continuing.
   - Already observed and read before the new-file route, with content exactly matching the approved draft: re-read, stop on drift, and treat the ADR write as a no-op.
   - Already existing with different content: stop and ask for a naming decision; never overwrite it.
9. If claim, verification, or native editing fails, stop subsequent writes, leave the project page unchanged, and report every visible reservation or partial edit, completed path, unexecuted path, and pending repair. After a successful ADR native edit or pre-observed matching-content no-op, re-read each existing update target immediately before applying the approved additive patches. Deduplicate Followup into Pending, add the Key Decisions backlink, and add the reverse supersession link when applicable.
10. Keep every partial result visible. If the ADR reservation or edit exists but a later action fails, report all completed paths and each pending repair. Do not delete, roll back, or retry the reservation as an existing-file edit.

## Safety

- Do not create an ADR without two real alternatives and an actual trade-off. Do not bypass the complete-draft approval gate.
- Require the pre-existing decisions directory; this workflow creates no parents. New ADR paths use the shared claim protocol. Never overwrite a collision, delete or replace an obsolete ADR, hide partial failure, continue after drift, or roll back completed work.
- Never read `secrets`, expose secret payloads, create unconfirmed taxonomy, publish a repository, commit, or push.

## Output

Lead with `Genuine choice` or `Not ready for ADR` and the supporting decision material. Before writing, report every exact file path, the existing-parent precondition, and the complete draft and patches awaiting approval. After writing, report the ADR as claimed and filled, visibly partial, or pre-observed matching-content no-op; report the project Pending and Key Decisions updates, both supersession directions when applicable, and retrievable provenance. End with every completed path, unexecuted path, and concrete pending repair or Followup item.
