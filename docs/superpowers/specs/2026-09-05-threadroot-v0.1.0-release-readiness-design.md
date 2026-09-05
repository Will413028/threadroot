# Threadroot v0.1.0 Release Readiness Design

**Date:** 2026-09-05

**Status:** Approved

**Release:** `v0.1.0`
**Repository:** `https://github.com/Will413028/threadroot`

## Goal

Publish the first GitHub Release of Threadroot from a reviewed commit on
`main`, with accurate repository installation instructions, complete package
metadata, four reproducible install artifacts, and evidence that those exact
artifacts pass the existing safety and clean-install gates.

The release is the start of external validation. It is not evidence of product
adoption, marketplace availability, or API stability.

## Scope

Release readiness changes only:

- Replace the generic repository-owner token in public install commands with
  the live `Will413028/threadroot` repository.
- Add canonical homepage, repository, and issue-tracker URLs to Python package
  metadata.
- Add focused regression checks for the executable repository-install commands
  and package URLs.
- Rebuild and verify the existing wheel, source distribution, Claude Code ZIP,
  and Codex ZIP from the final release commit.
- Publish one immutable `v0.1.0` tag and one GitHub Release containing exactly
  those four artifacts after every pre-publication gate passes.
- Run an immediate post-publication download and clean-install smoke test using
  the uploaded assets.
- Define the evidence required before expanding distribution beyond GitHub and
  repository-based installation.

## Non-goals

This release does not add or change:

- Runtime CLI behavior, the vault schema, or any Agent Skill workflow.
- `migrate`, transaction journals, rollback hashes, MCP, RAG, GUI, telemetry,
  background synchronization, or Windows support.
- PyPI publication, a release automation workflow, artifact signing, or a
  package-manager formula.
- OpenAI universal Plugins Directory submission or any Claude marketplace
  submission.
- A logo, standalone product website, privacy-policy site, terms site, support
  portal, governance model, CLA, DCO, or Code of Conduct.
- Private-vault content, private fixtures, host credentials, or model-generated
  evidence in the public repository or release assets.

## Source and branch model

All work occurs in an isolated worktree on
`release/v0.1.0-readiness`, forked from the merged remote `main` commit. The
maintainer's other checkout and local `main` are not checked out, reset, pulled,
or rewritten by this work.

The readiness changes land through a pull request. After that pull request is
merged and its `main` CI succeeds, the resulting remote `main` commit becomes
the only permitted release target. Artifact builds, the tag, and the GitHub
Release must all name that exact commit.

If remote `main` moves after artifact verification and before publication, stop
and repeat verification against the new commit. Never tag an earlier tree while
describing it as the current release.

## Public metadata changes

### Repository installation

The README repository-install block uses these live values:

```text
https://github.com/Will413028/threadroot.git
Will413028/threadroot
```

The checkout, Claude Code marketplace, and Codex marketplace examples must all
refer to that same repository. The prose must no longer claim that the remote is
absent or that the repository owner must be substituted later.

### Python package URLs

`pyproject.toml` gains this exact `[project.urls]` mapping:

```toml
Homepage = "https://github.com/Will413028/threadroot"
Repository = "https://github.com/Will413028/threadroot"
Issues = "https://github.com/Will413028/threadroot/issues"
```

The package name and version remain `threadroot` and `0.1.0`. Runtime
dependencies remain empty.

### Attribution

Before publication, inspect tracked dependencies, bundled assets, copied
examples, and generated artifacts for third-party material. Create `NOTICE` or
another attribution file only when an actual bundled notice requires it. Do not
add an empty or speculative notice file.

## Release artifacts

The release contains exactly these install assets:

1. `threadroot-0.1.0-py3-none-any.whl`
2. `threadroot-0.1.0.tar.gz`
3. `threadroot-claude-0.1.0.zip`
4. `threadroot-codex-0.1.0.zip`

Use the existing Python build backend and `scripts/build_release.py`; do not
hand-edit archives. Delete or replace only generated files inside the ignored
release output directory before the final build. Never derive a release asset
from a different commit or from the earlier feature worktree.

The release notes must state:

- This is the first public Threadroot release.
- The wheel installs the deterministic CLI and the host ZIP installs the nine
  Agent Skills; a complete installation needs both layers.
- Supported environments are Python 3.11 through 3.14 on macOS and Linux.
- Threadroot is local-first, has no telemetry, and leaves the user-owned
  Markdown and Git vault intact on uninstall.
- The public interfaces are pre-1.0 and can evolve through reviewed releases.
- PyPI and universal plugin-directory installation are not available in this
  release.

## Pre-publication verification

Every gate runs against the exact release commit and stops publication on a
nonzero exit or mismatch:

1. Confirm a clean tracked worktree and index, the expected branch, the exact
   remote `main` ancestry, and matching version `0.1.0` in Python and both host
   manifests.
2. Run the full `unittest` suite and `compileall` on every locally installed
   supported Python minor version. Hosted CI remains the complete macOS/Linux
   by Python 3.11-3.14 matrix.
3. Build a fresh wheel and source distribution without silently installing new
   build dependencies from the network.
4. Build both host ZIPs and verify deterministic member names, safe archive
   paths, no symlinks, and byte parity with the release source tree.
5. Run `scripts/check_public.py` against the checkout and the complete release
   output. Use the maintainer's untracked denylist when available without
   printing or committing its contents.
6. Install the wheel in a fresh virtual environment with `--no-index --no-deps`
   and verify `threadroot --version`, `init`, `doctor`, and `claim` using a
   synthetic vault.
7. Validate the Claude Code and Codex packages using disposable host config
   roots. Native manifest, local marketplace add/install/list/remove, and vault
   no-write checks must not touch normal host state.
8. Verify the proposed release notes and exact four-asset set before creating or
   publishing the release.

Fresh model runs and another private-vault dogfood cycle are not implicit in
these automated gates. They require separate explicit authorization and must be
reported as unexecuted when not authorized. Earlier model runs do not prove a
new release artifact.

## Publication sequence

1. Open and merge the release-readiness pull request after its checks pass.
2. Resolve the exact merge commit from remote `main` and verify it has not moved.
3. Build and verify all four assets from a clean worktree at that commit.
4. Create a draft GitHub Release for `v0.1.0` targeting that exact commit and
   upload only the verified assets.
5. Re-read the draft metadata and uploaded asset names and sizes. Leave the
   release as a draft if any field or upload is incomplete.
6. Publish the draft without moving the tag or rebuilding assets.
7. Download all four public assets into a new temporary directory and rerun the
   archive, privacy, wheel-install, and host-package smoke checks.

Do not delete, retarget, or silently replace a published tag. If the
post-publication check finds a product or artifact defect, document it and ship
the smallest corrected patch release rather than rewriting `v0.1.0`.

## Failure handling

- Dirty state, unexpected commits, version disagreement, missing build tooling,
  failed tests, privacy findings, archive mismatch, or host-state drift blocks
  publication.
- A failed draft creation or asset upload remains unpublished. Inspect and
  repair the draft; do not publish a partial asset set.
- An already-existing `v0.1.0` tag is a hard stop unless it points to the exact
  verified commit. An already-existing release is a hard stop unless it targets
  that tag and contains the exact verified assets. Never force a tag update.
- Authentication or permission failures stop at the external boundary. Do not
  copy credentials, bypass review, or change account ownership to proceed.
- Partial synthetic vault state remains visible for inspection under the
  existing Threadroot failure contract; release tooling does not add rollback
  machinery.

## Post-release validation

GitHub Release `v0.1.0` starts a manual, telemetry-free adoption experiment.
Before expanding distribution, seek evidence from three to five external
developers who are not relying on the maintainer's private setup.

The minimum expansion gate is:

- At least three external developers install both required layers from the
  public repository or release assets.
- Each completes setup or adoption, `doctor`, and at least one real workflow on
  a vault they control.
- At least two voluntarily report a second successful use at least fourteen
  days after their first use.
- No unresolved data-overwrite, unsafe-path, privacy, uninstall, or host-state
  isolation incident exists.

Collect this evidence through opt-in conversations or public issues. Do not add
telemetry or infer retention from downloads, stars, clones, or raw install
counts.

## Marketplace decision boundary

Threadroot remains a GitHub- and repository-distributed tool through this
release. The OpenAI skills-only upload path can convert a valid
`.claude-plugin/plugin.json` into generated Codex metadata, but that conversion
does not make a local-filesystem product submission-ready.

After the adoption gate, separately evaluate universal submission. The current
official process requires publisher verification, listing and policy URLs,
production brand assets, starter prompts, five positive cases, three negative
cases, and review. Because Threadroot's core value depends on local execution,
arbitrary user-approved local file access, and offline operation, contact an
OpenAI partner before submitting. Marketplace preparation must not introduce an
MCP server merely to satisfy a channel when the product has no demonstrated
server requirement.

References:

- https://developers.openai.com/plugins/guides/submit-claude-plugin
- https://developers.openai.com/plugins/deploy/submission

## Acceptance criteria

Release readiness is complete only when:

- The readiness pull request is merged and remote `main` CI is green.
- README repository commands and Python project URLs name the live public repo.
- The attribution audit finds no unresolved obligation.
- The tag and release target the exact verified `main` commit.
- The GitHub Release is public with exactly four verified assets.
- The immediate public-download smoke test passes for all four assets.
- The release notes accurately state support, ownership, privacy, install-layer,
  and pre-1.0 boundaries.
- No PyPI publication or plugin-directory submission occurred.
- Unexecuted model or private-dogfood gates are disclosed rather than inferred.

The external adoption gate is intentionally post-release. It determines whether
Threadroot should expand distribution; it does not retroactively block the
first GitHub Release.
