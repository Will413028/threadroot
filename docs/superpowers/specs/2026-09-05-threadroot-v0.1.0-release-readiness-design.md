# Threadroot v0.1.0 Release Readiness Design

**Date:** 2026-09-05

**Status:** Approved

**Artifact-identity amendment:** Approved 2026-09-06

**Release:** `v0.1.0`
**Repository:** `https://github.com/Will413028/threadroot`

## Goal

Publish the first GitHub Release of Threadroot from a reviewed commit on
`main`, with accurate repository installation instructions, complete package
metadata, four reproducible install artifacts produced by a backend-native
deterministic build, and evidence that those exact artifacts pass the existing
safety and clean-install gates.

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
- Replace the Setuptools build backend with Hatchling so source distributions
  and wheels are reproducible at the PEP 517 backend boundary.
- Replace `MANIFEST.in` and Setuptools-specific file discovery with one explicit
  Hatchling package and source-distribution selection in `pyproject.toml`.
- Define one auditable canonical release environment, distinct from the
  supported-platform compatibility matrix, and lock every effective build-tool
  dependency used by that environment.
- Add a dedicated reproducibility gate that builds all four artifacts from two
  independent exports of the same commit and compares them byte for byte.
- Bind release inputs and both candidate sets once, carry immutable artifact
  snapshots through every verification phase, and promote only from those
  approved snapshots.
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
- PyPI publication, a release automation workflow, artifact signing or
  provenance attestation, and a package-manager formula.
- A custom source-distribution canonicalizer, a custom Setuptools `sdist`
  command, wall-clock interception, or post-build mutation of Python package
  archives.
- A promise that arbitrary Python, zlib, operating-system, locale, or build-tool
  versions produce identical bytes. Reproducibility is scoped to the recorded
  canonical release environment.
- Resistance to a malicious Docker daemon, host root, or concurrent same-UID
  process that can rewrite the dedicated build output while the release gate is
  running. Those actors are inside the trusted local build boundary; stronger
  isolation would require a dedicated build host or filesystem snapshot and is
  deferred until the threat model requires it.
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

Hold a short release freeze on `main` from the moment the green merge commit is
bound through publication; feature-branch work may continue, but no unrelated
merge or direct push may advance `main`. If `main` moves before the annotated
tag is created, stop and repeat verification against the new commit. If it
nevertheless moves after the immutable tag exists, never retarget or delete the
tag: publication remains blocked until an explicit release-version/design
decision resolves the mismatch.

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

## Reproducible build decision

The release preflight exposed a backend defect rather than a Threadroot payload
defect. With the pinned Setuptools toolchain, repeated sdists contained the same
ordered member names and file bytes but different gzip timestamps and tar/PAX
`mtime` metadata. The Setuptools sdist path did not consume
`SOURCE_DATE_EPOCH`; normalizing source-file timestamps could not make generated
metadata, directories, and the gzip header deterministic.

Threadroot will correct this at the component that owns the Python archive:
the PEP 517 build backend. Hatchling is selected because Threadroot is a
pure-Python `src/`-layout project with static project metadata, no extension
modules, and no backend hooks, while Hatchling supports reproducible sdist and
wheel targets and applies `SOURCE_DATE_EPOCH` to build timestamps.

The rejected alternatives are:

- A post-build canonicalizer would make only one release path deterministic,
  leave ordinary `python -m build` sdists nondeterministic, duplicate tar, PAX,
  gzip, ownership, mode, and link policy in Threadroot code, and require ongoing
  compatibility tests for archive edge cases.
- A custom Setuptools command would make Threadroot depend on backend command
  APIs and bootstrap behavior that are unrelated to the product.
- Weakening the byte-identity gate would conceal nondeterminism rather than
  resolve it.

`scripts/build_release.py` remains the owner of Claude Code and Codex ZIP
construction. Those archives are Threadroot product formats without a Python
packaging backend; their existing explicit path, ordering, timestamp, mode, and
symlink policy is domain logic rather than a workaround for another tool.

## Packaging source of truth

`pyproject.toml` is the only Python packaging configuration source:

- `[build-system]` selects `hatchling.build` and declares a compatible,
  reviewed Hatchling version range. The canonical release environment selects
  one exact version from that range.
- The wheel target explicitly selects `src/threadroot` as the sole import
  package. Runtime dependencies remain empty and the `threadroot` entry point
  remains `threadroot.cli:main`.
- The sdist target uses a root-anchored allowlist for the Python source,
  `skills/`, `templates/`, both native plugin metadata directories, `scripts/`,
  `tests/`, `docs/`, the tracked canonical environment definition under
  `requirements/` and `tools/release/`, `.dockerignore`, and exactly
  `AGENTS.md`, `CONTRIBUTING.md`, `LICENSE`, `README.md`, and `SECURITY.md` at
  the project root.
- Backend-required files such as `pyproject.toml`, the declared README and
  license, and generated `PKG-INFO` remain present. Project metadata explicitly
  declares `LICENSE` through `license-files`. Setuptools-generated `*.egg-info`
  and `setup.cfg` files are not part of the new contract.
- `MANIFEST.in` and all `[tool.setuptools]` configuration are deleted in the
  same change. No dormant second packaging manifest remains.

Tests assert observable wheel and sdist membership, metadata, entry points, and
install behavior. They do not infer correctness merely by parsing the build
configuration. Any intentional membership change requires an explicit test and
review update.

## Canonical release environment

Compatibility testing and release-byte production have different purposes and
must not share an ambiguous environment contract.

The compatibility matrix continues to exercise Python 3.11 through 3.14 on
macOS and Linux. It answers whether supported users can build, install, and run
Threadroot; its outputs are not release assets and need not be byte-identical
across matrix cells.

One canonical `linux/amd64` builder produces release bytes. Its tracked
definition contains:

- an OCI base image referenced by immutable digest;
- one exact Python patch version;
- a hash-locked list of every installed release-build package, including the
  frontend, backend, and transitive dependencies;
- full-commit-SHA pins for CI actions that invoke the builder;
- `SOURCE_DATE_EPOCH` set to the exact release commit's committer timestamp,
  `TZ=UTC`, `LC_ALL=C.UTF-8`, `LANG=C.UTF-8`, `PYTHONHASHSEED=0`, and umask
  `022`; and
- one checked-in entry point used identically by local maintainers and CI.

The builder and Hatchling are maintainer-side build dependencies only. They do
not become Threadroot runtime dependencies, and users installing the wheel or
host ZIPs do not need an OCI runtime.

Environment provisioning may fetch only the digest-pinned image and artifacts
named by the hash lock. The artifact-build phase itself runs without network,
uses the already-provisioned environment, and disables PEP 517 build isolation
so the lock cannot be bypassed by a new resolver result. The entry point verifies
the actual Python and package versions before reading release inputs.

This environment definition, the exact source commit, and the build
instructions form Threadroot's reproducibility perimeter. A backend or
toolchain upgrade is made only through a reviewed pull request that updates the
lock and image reference as needed and passes the complete reproducibility and
install gates. A floating dependency or image tag can exercise compatibility
CI but can never produce release assets.

## Artifact reproducibility contract

For a candidate or final release, create two independent source trees from
`git archive` of the same exact commit. Extract them beneath distinct paths in
the canonical builder and build each without reusing build directories,
caches, generated metadata, or output directories.

Each source tree independently produces exactly:

1. `threadroot-0.1.0-py3-none-any.whl`
2. `threadroot-0.1.0.tar.gz`
3. `threadroot-claude-0.1.0.zip`
4. `threadroot-codex-0.1.0.zip`

The gate requires byte-for-byte equality for each corresponding pair. It then:

- verifies the exact four-file output membership and records SHA-256 values;
- validates wheel metadata, entry point, package membership, archive paths, and
  install behavior;
- validates the sdist top-level directory, explicit source membership, member
  types, safe relative paths, modes, metadata, and absence of unintended or
  generated Setuptools files;
- extracts the selected sdist, rebuilds its wheel offline with the same locked
  environment, and requires byte identity with the selected wheel;
- verifies both host ZIPs against their exact input allowlists and existing
  archive-safety contract; and
- runs the public scanner against the source export and every unpacked and
  packed artifact, including the maintainer's local denylist when available.

Candidate set A becomes the selected release set only after A and B pass every
gate. Publication promotes those exact bytes; it never invokes another build,
normalizes an archive, or replaces a selected artifact. Candidate set B and the
recorded hashes remain verification evidence but are not published.

A dedicated CI job runs the same checked-in build and verification entry point
for relevant pull requests and `main`. It is separate from the supported-system
test matrix, produces no GitHub Release, and fails on any byte, membership,
metadata, privacy, or source-to-wheel mismatch.

## Artifact identity and build trust amendment

The release gate uses one ownership model from input binding through atomic
promotion. Repeating pathname checks at individual phases is not sufficient:
it can validate one inode, consume another, and lose the identity of candidate
B after the byte comparison. The implementation therefore binds filesystem
objects once and carries their identities and bytes forward instead of taking
new path-based snapshots as each phase begins.

### Canonical trust perimeter

The outer release entry point is the isolation boundary. It must create both
source exports itself and run the inner orchestrator with all of these
properties at once:

- `/source-a` and `/source-b` are distinct read-only bind mounts containing
  safely extracted `git archive` trees of the same exact commit;
- the container root filesystem is read-only, the artifact phase has no
  network, all capabilities are dropped, `no-new-privileges` is set, and the
  process runs as the invoking non-root UID/GID;
- `/release-output` is the only writable bind mount and is dedicated to this
  invocation; and
- an optional denylist is a read-only regular-file mount at exactly
  `/run/threadroot/denylist`.

The maintainer account, host kernel, Docker daemon, dedicated output root, and
reviewed build tools are trusted not to mutate these mounts concurrently or
leave hostile background writers. A detected accidental drift still fails the
run and must never produce `selected/`, but candidate and evidence directories
may remain for diagnosis. The gate does not claim to defeat a malicious host
actor able to write between the last filesystem check and a kernel rename.

### Bound inputs and source snapshots

The inner orchestrator owns a single run-scoped binding object managed by one
`ExitStack`. It opens and retains descriptors for both source roots and the
output root. Every root is opened with directory and no-follow semantics and
its pathname entry is matched to the held descriptor. A missing output leaf is
created only beneath a held real parent with exclusive `mkdirat` semantics; an
existing empty output is opened and checked through its held descriptor. The
orchestrator never adopts an entry that appears during creation and never uses
`mkdir(..., exist_ok=True)` to cross this boundary.

Release-relevant source files are read component by component relative to the
held source descriptors. Each directory component and regular-file leaf is
opened without following links and is checked before and after the read. The
result is an immutable release-source snapshot containing only the files
required by the wheel, sdist, host ZIP, scanner, Dockerfile, and release lock
contracts. Both exports must produce identical builder-definition bytes and
the lock must contain exactly the approved option and complete package map.

Task 3 gains narrow snapshot-oriented entry points that share the existing
validation and extraction cores. The existing Path APIs remain available for
post-download and standalone validation, while the inner orchestrator passes
captured archive bytes and the immutable release-source snapshot. There is one
metadata, membership, path-safety, and extraction implementation—not a second
validator and not an archive canonicalizer.

### Candidate snapshots and verification flow

After each independent build, the orchestrator opens the candidate directory
and exactly four regular, single-link artifact members relative to that held
directory. For every member it records the original device, inode, file type,
permission mode, link count, size, mtime, ctime, streamed SHA-256, and immutable
payload bytes. Candidate A and B become a verified pair only when corresponding
payload bytes match exactly; `filecmp.cmp(..., shallow=False)` remains an
additional required comparison, not the identity authority.

All subsequent archive validation and extraction consumes the captured source
and artifact snapshots. Sdist replay captures its sole regular wheel and
compares it with candidate A's approved wheel payload. The public scanner still
receives the two canonical read-only source mount paths, four packed paths, and
four unpacked roots because it is a separate path-based process; bindings and
all eight candidate snapshots are revalidated immediately before and after
that subprocess.

Before evidence or promotion, candidate A and B must both retain exact
membership, pathname-to-descriptor identity, full recorded metadata, and
approved hashes. Any byte, inode, mode, link, timestamp, or membership drift
fails without `selected/`. Evidence is serialized only from the already-bound
Dockerfile, lock, source, and artifact snapshots; it never reopens a pathname
to establish a new authority.

### Promotion and failure semantics

Promotion copies candidate A's immutable approved payloads into an owned
`selected.pending/`; it does not reopen candidate A to choose publication
bytes. Short writes are handled explicitly. Immediately before publication,
the exclusive primitive verifies through held descriptors that pending has
exactly four regular, single-link `0644` files, that each directory entry still
names the opened inode, and that every size and hash equals the approved A
snapshot. It then uses Linux `renameat2(RENAME_NOREPLACE)` or Darwin
`renameatx_np(RENAME_EXCL)`. An existing, broken-link, or raced `selected/` is
never replaced.

All acquired descriptors are registered with the run's `ExitStack` as soon as
they are opened and close on every success and failure path. Scanner or
validation failure creates neither promotion directory. A copy or pending
write failure leaves the owned `selected.pending/` visible for diagnosis, as
required by the existing failure policy. An identity mismatch never deletes a
replacement object whose ownership cannot be proven.

This amendment expands the implementation scope narrowly to
`scripts/release_archives.py`, `tests/test_release_archives.py`,
`scripts/release_artifacts.py`, and `tests/test_release_artifacts.py`, plus the
binding spec and implementation plan. It does not change runtime CLI behavior,
artifact formats, product manifests, dependency policy, or release bytes.

## Release artifacts

The release contains exactly these install assets:

1. `threadroot-0.1.0-py3-none-any.whl`
2. `threadroot-0.1.0.tar.gz`
3. `threadroot-claude-0.1.0.zip`
4. `threadroot-codex-0.1.0.zip`

Use Hatchling for the Python distributions and `scripts/build_release.py` for
the two host ZIPs. Do not hand-edit or post-process archives. Delete or replace
only generated files inside the ignored release output directory before the
final build. Never derive a release asset from a different commit, an untracked
working-tree file, or the earlier feature worktree.

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
3. Resolve and verify the immutable canonical-builder image, Python version,
   complete hash-locked toolchain, fixed environment, and no-network build
   boundary.
4. Export the exact commit twice with `git archive`, build all four artifacts
   independently, require exact output membership, and compare every pair byte
   for byte.
5. Inspect Python and host archive members, paths, types, modes, metadata, and
   source parity. Extract the selected sdist, rebuild its wheel offline, and
   require byte identity with the selected wheel.
6. Run `scripts/check_public.py` against both source exports and every packed and
   unpacked artifact. Use the maintainer's untracked denylist when available
   without printing or committing its contents.
7. Install the wheel in a fresh virtual environment with `--no-index --no-deps`
   and verify `threadroot --version`, `init`, `doctor`, and `claim` using a
   synthetic vault.
8. Validate the Claude Code and Codex packages using disposable host config
   roots. Native manifest, local marketplace add/install/list/remove, and vault
   no-write checks must not touch normal host state.
9. Verify the proposed release notes and exact four-asset set before creating or
   publishing the release.

Fresh model runs and another private-vault dogfood cycle are not implicit in
these automated gates. They require separate explicit authorization and must be
reported as unexecuted when not authorized. Earlier model runs do not prove a
new release artifact.

## Publication sequence

1. Open and merge the release-readiness pull request after its checks pass.
2. Resolve the exact merge commit from remote `main` and verify it has not moved.
3. Use the canonical builder to create candidate sets A and B from two clean
   exports of that commit, complete all gates, and select set A without changing
   it.
4. Create a draft GitHub Release for `v0.1.0` targeting that exact commit and
   upload only the four selected assets.
5. Re-read the draft metadata and downloaded asset names, sizes, and SHA-256
   values. Leave the release as a draft if any field, byte, or upload is
   incomplete.
6. Publish the draft without moving the tag or rebuilding assets.
7. Download all four public assets into a new temporary directory and rerun the
   archive, privacy, wheel-install, and host-package smoke checks.

Do not delete, retarget, or silently replace a published tag. If the
post-publication check finds a product or artifact defect, document it and ship
the smallest corrected patch release rather than rewriting `v0.1.0`.

## Failure handling

- Dirty state, unexpected commits, version disagreement, missing build tooling,
  canonical-image or lock disagreement, network access during the build phase,
  failed tests, privacy findings, archive mismatch, or host-state drift blocks
  publication.
- Any difference between candidate sets A and B is a release failure. Do not
  canonicalize, replace, or selectively copy members to make the comparison
  pass; fix the responsible backend, configuration, input, or environment and
  restart with two new candidate roots.
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

## Build architecture references

- https://packaging.python.org/en/latest/tutorials/packaging-projects/
- https://packaging.python.org/en/latest/specifications/source-distribution-format/
- https://peps.python.org/pep-0517/
- https://hatch.pypa.io/dev/config/build/#reproducible-builds
- https://hatch.pypa.io/dev/plugins/builder/sdist/
- https://reproducible-builds.org/docs/definition/
- https://reproducible-builds.org/docs/perimeter/
- https://reproducible-builds.org/docs/timestamps/
- https://github.com/pypa/setuptools/issues/2133

## Acceptance criteria

Release readiness is complete only when:

- The readiness pull request is merged and remote `main` CI is green.
- README repository commands and Python project URLs name the live public repo.
- The attribution audit finds no unresolved obligation.
- Hatchling is the only Python build backend, `pyproject.toml` is the only
  packaging file-selection authority, and no sdist canonicalizer or dormant
  Setuptools configuration remains.
- The canonical builder is immutable and auditable, every effective release
  build dependency is hash-locked, and the build phase performs no network
  access.
- Two independent exports of the exact release commit produce byte-identical
  wheel, sdist, Claude ZIP, and Codex ZIP artifacts; the selected sdist also
  reproduces the selected wheel offline.
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
