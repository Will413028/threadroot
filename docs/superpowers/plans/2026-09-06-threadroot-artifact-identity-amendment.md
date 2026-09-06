# Threadroot Artifact Identity Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve one immutable identity and byte authority for both release
artifact sets from initial comparison through validation, evidence, and
no-clobber promotion.

**Architecture:** Task 3 exposes snapshot-oriented archive APIs backed by its
existing parsing and safe-extraction cores. Task 4 owns run-scoped source,
output, candidate, and artifact bindings with `ExitStack`; validators consume
captured bytes, both candidate sets are revalidated after all path-based work,
and promotion copies only the approved candidate-A payload snapshots.

**Tech Stack:** Python 3.11-3.14 standard library, `dataclasses`, descriptor-
relative `os` APIs, `contextlib.ExitStack`, `unittest`, SHA-256, Linux
`renameat2(RENAME_NOREPLACE)`, and Darwin `renameatx_np(RENAME_EXCL)`.

**Spec:**
`docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md`
— section “Artifact identity and build trust amendment”.

## Global constraints

- Keep runtime dependencies empty and do not change release artifact bytes,
  package metadata, product manifests, skills, CLI behavior, or version.
- Preserve the existing Path-based Task 3 APIs for standalone and
  post-download validation. Snapshot APIs must delegate to the same parser,
  metadata, membership, and extraction cores; do not duplicate validators.
- Use only synthetic fixtures. Never put a private path, denylist payload,
  credential, or vault content in tests, logs, evidence, or commits.
- The canonical security perimeter remains Task 5's read-only source mounts,
  read-only container root, offline network, dropped capabilities,
  `no-new-privileges`, non-root UID/GID, and dedicated output bind mount.
- The trusted host account and Docker daemon do not mutate source or output
  concurrently. Detected drift must prevent evidence success and `selected/`,
  but candidates may remain for diagnosis.
- Do not promise protection against a malicious same-UID host writer. Do bind
  every object Task 4 owns, reject deterministic pathname/identity drift, and
  use an atomic no-replace publication primitive.
- `build_and_verify(...)`, `ArtifactSet.load(...)`,
  `compare_artifact_sets(...)`, and all existing Task 3 public functions retain
  their current external signatures.
- No Docker, network, push, PR, merge, tag, or release operation is part of
  this amendment. The original release plan's authorization gates remain in
  force.
- Before each commit, stage exact paths only and require repository-local Git
  identity `Will` / `will413028@gmail.com`.

## Current execution state

The release branch already contains the reviewed preliminary Task 4 commits
through `2ab10bea2a40683e286bb59552d800f38bd467ce` and the approved design commit
`5960b28`. Two Task 4 files contain an uncommitted, passing partial fix created
before the architecture amendment:

- `scripts/release_artifacts.py`
- `tests/test_release_artifacts.py`

Those changes add exact lock-option validation, canonical installed-package
duplicate rejection, early missing-denylist rejection, replay-wheel symlink
rejection, and pending mode enforcement. Their original RED evidence is in the
main SDD ledger and Task 4 report. Task 1 below stabilizes and commits only this
known diff so later tasks start clean.

## File map

| Path | Responsibility in this amendment |
|---|---|
| `scripts/release_archives.py` | Immutable release-source capture plus payload-based archive validation and extraction adapters over the existing cores |
| `tests/test_release_archives.py` | Path/payload API parity, descriptor ownership, intermediate-symlink, and extraction regression tests |
| `scripts/release_artifacts.py` | Run bindings, A/B artifact snapshots, phase continuity, evidence generation, and snapshot-only promotion |
| `tests/test_release_artifacts.py` | Static gates, subprocess boundary, lifecycle drift, evidence, promotion-race, and fd-lifecycle tests |

---

### Task 1: Stabilize the already-proven input and pending gates

**Files:**

- Modify: `scripts/release_artifacts.py`
- Modify: `tests/test_release_artifacts.py`

**Interfaces:**

- Consumes: the exact two-file uncommitted partial fix described above.
- Produces: a clean committed baseline that rejects incomplete release-lock
  options, duplicate normalized installed distributions, missing explicit
  denylist mounts, replay-wheel symlinks, and non-`0644` pending members.

- [ ] **Step 1: Confirm the inherited diff is exact and contains all five regression tests**

Run:

```bash
git diff --name-only
rg -n "def test_(lock_requires_exactly_one_approved_option|installed_package_canonical_duplicate_is_rejected|missing_fixed_denylist_is_rejected_before_output|replay_symlink_wheel_is_rejected|pending_mode_mutation_is_rejected)" \
  tests/test_release_artifacts.py
```

Expected: exactly the two Task 4 paths are dirty and all five named tests are
present. Do not add another behavior to this recovery commit.

- [ ] **Step 2: Re-run the focused regressions and complete suite**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_artifacts.BuildAndVerifyTests.test_lock_requires_exactly_one_approved_option \
  tests.test_release_artifacts.BuildAndVerifyTests.test_installed_package_canonical_duplicate_is_rejected \
  tests.test_release_artifacts.BuildAndVerifyTests.test_missing_fixed_denylist_is_rejected_before_output \
  tests.test_release_artifacts.BuildAndVerifyTests.test_replay_symlink_wheel_is_rejected \
  tests.test_release_artifacts.BuildAndVerifyTests.test_pending_mode_mutation_is_rejected \
  -v
PYTHONPATH=src:. python3 -m unittest discover -s tests -q
python3 -m compileall -q scripts/release_artifacts.py tests/test_release_artifacts.py
python3 scripts/check_public.py scripts/release_artifacts.py tests/test_release_artifacts.py
git diff --check
```

Expected: the five regressions and the full suite pass; compile, public scan,
and diff checks exit zero.

- [ ] **Step 3: Commit only the recovered baseline**

Run:

```bash
test "$(git config --local user.name)" = "Will"
test "$(git config --local user.email)" = "will413028@gmail.com"
git add scripts/release_artifacts.py tests/test_release_artifacts.py
git diff --cached --check
git commit -m "fix: close artifact input validation gaps"
```

Expected: exactly the two named paths are committed and the tracked worktree
and index are clean.

---

### Task 2: Expose immutable archive and source-snapshot APIs

**Files:**

- Modify: `scripts/release_archives.py`
- Modify: `tests/test_release_archives.py`

**Interfaces:**

- Consumes: a caller-owned, open source-root directory descriptor and archive
  payload bytes captured by Task 4.
- Produces these new public types and callable signatures while preserving
  every existing Path API:

```python
@dataclass(frozen=True)
class ReleaseSourceEntry:
    path: str
    payload: bytes
    mode: int


@dataclass(frozen=True)
class ReleaseSourceSnapshot:
    entries: tuple[ReleaseSourceEntry, ...]
```

```text
capture_release_source(source_fd: int) -> ReleaseSourceSnapshot
validate_wheel_payload(artifact: bytes, source: ReleaseSourceSnapshot, version: str, epoch: int) -> None
validate_sdist_payload(artifact: bytes, source: ReleaseSourceSnapshot, version: str, epoch: int) -> None
validate_host_zip_payload(artifact: bytes, source: ReleaseSourceSnapshot, host: str) -> None
extract_regular_tar_payload(artifact: bytes, destination: Path, expected_global_comment: str | None = None) -> None
extract_regular_zip_payload(artifact: bytes, destination: Path) -> None
```

`ReleaseSourceSnapshot.entries` is sorted by `path`, contains no duplicate,
and uses only immutable tuples and bytes. The public
`capture_release_source` root set is exactly the union of `SDIST_ROOTS`,
`.gitignore`, and `pyproject.toml`; that union already contains every wheel,
host ZIP, Dockerfile, release-lock, builder, and scanner input. It duplicates
or descends from the supplied root fd but never closes the caller's descriptor.
An internal `_capture_source_roots(source_fd, roots)` supplies the smaller
wheel and host selections used by existing Path wrappers, so their current
minimal synthetic source contract does not expand.

- [ ] **Step 1: Add RED tests for descriptor-relative source capture**

Add tests equivalent to:

```python
def test_capture_release_source_rejects_intermediate_symlink_and_keeps_root_fd_open(self) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = _make_sdist_source(root)
        outside = root / "outside"
        outside.mkdir()
        (outside / "release.txt").write_text("outside", encoding="utf-8")
        (source / "requirements").rename(source / "requirements.real")
        (source / "requirements").symlink_to(outside, target_is_directory=True)
        descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with self.assertRaisesRegex(ReleaseArchiveError, "source tree"):
                capture_release_source(descriptor)
            os.fstat(descriptor)
        finally:
            os.close(descriptor)
```

Also add a valid capture test that asserts entries are sorted, unique, regular,
mode-normalized, and include at least `pyproject.toml`,
`requirements/release.txt`, `tools/release/Dockerfile`,
`scripts/check_public.py`, `README.md`, and `src/threadroot/__init__.py`.

- [ ] **Step 2: Add RED parity tests for payload validators and extractors**

For the existing valid wheel, sdist, Claude ZIP, Codex ZIP, tar, and ZIP
fixtures, call both the Path and payload APIs and require identical success.
For one representative mutation per stable error code, require both forms to
raise the same `ReleaseArchiveError.code`:

```python
with self.assertRaises(ReleaseArchiveError) as path_error:
    validate_wheel(path, source, "0.1.0", WHEEL_EPOCH)
with self.assertRaises(ReleaseArchiveError) as payload_error:
    validate_wheel_payload(path.read_bytes(), snapshot, "0.1.0", WHEEL_EPOCH)
self.assertEqual(payload_error.exception.code, path_error.exception.code)
```

For extraction, feed payload bytes to new missing destinations and reuse the
existing unsafe-name, special-member, nonempty-destination, symlink-parent,
cleanup, and raced-destination fixtures. A payload adapter must not weaken the
existing destination rules.

- [ ] **Step 3: Run the new tests and confirm the APIs are absent**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_archives.ReleaseSourceSnapshotTests \
  tests.test_release_archives.PayloadArchiveApiTests \
  -v
```

Expected: FAIL on imports or missing names before implementation.

- [ ] **Step 4: Split byte parsing from pathname acquisition**

Refactor without changing validation rules:

- `_load_zip_members_payload(raw: bytes)` owns ZIP parsing and raw-boundary
  validation; `_load_zip_members(path)` only calls `_read_artifact(path)` and
  delegates.
- `_load_tar_members_payload(raw: bytes, expected_global_comment)` owns gzip,
  tar-boundary, PAX, member-type, and payload parsing;
  `_load_tar_members(path, ...)` only reads and delegates.
- Each existing validator captures only its current required source roots via
  `_capture_source_roots`, reads the archive path once, and delegates to the
  corresponding payload validator. The Task 4 orchestrator alone uses the
  complete public `capture_release_source` union.
- Each existing extractor reads the path once and delegates to the payload
  extractor.

Do not change accepted metadata, ordering, member types, modes, timestamps,
PAX fields, RECORD rules, or source allowlists.

- [ ] **Step 5: Implement immutable source capture from the caller fd**

Reuse `_open_relative_directory`, `_read_regular_at`, and `_walk_regular`, but
start from `os.dup(source_fd)`. Verify the supplied fd is a directory. Walk the
exact source-root union component by component with `O_NOFOLLOW`, compare each
directory entry with its opened fd, reject links/special files/duplicates, and
normalize regular-file modes to `0644` or `0755`.

Convert the resulting map to sorted `ReleaseSourceEntry` values. Add one
private helper that converts the immutable entries to a fresh mapping for the
existing validation core; never expose or store a mutable authoritative map.

- [ ] **Step 6: Implement payload validation and extraction adapters**

Move the bodies of `validate_wheel`, `validate_sdist`, and `validate_host_zip`
behind the new payload functions. Their source lookups come only from the
provided `ReleaseSourceSnapshot`. Keep the old functions as thin acquisition
wrappers. Add payload extractors that pass parsed members to the unchanged
`_extract_members` implementation.

- [ ] **Step 7: Verify Path/payload parity and commit Task 2**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_release_archives -v
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_archives tests.test_release_artifacts \
  tests.test_release tests.test_public_safety -q
python3 -m compileall -q scripts/release_archives.py tests/test_release_archives.py
python3 scripts/check_public.py scripts/release_archives.py tests/test_release_archives.py
git diff --check
test "$(git diff --name-only)" = $'scripts/release_archives.py\ntests/test_release_archives.py'
test "$(git config --local user.name)" = "Will"
test "$(git config --local user.email)" = "will413028@gmail.com"
git add scripts/release_archives.py tests/test_release_archives.py
git diff --cached --check
git commit -m "refactor: validate immutable release snapshots"
```

Expected: all tests and checks pass, exactly the two archive paths are
committed, and existing Path API callers remain green.

---

### Task 3: Preserve A/B artifact identity through every release gate

**Files:**

- Modify: `scripts/release_artifacts.py`
- Modify: `tests/test_release_artifacts.py`

**Interfaces:**

- Consumes: Task 2's `ReleaseSourceSnapshot`, payload validators, and payload
  extractors; Task 5's trusted read-only source mounts and dedicated output
  mount.
- Preserves these existing public interfaces exactly:

```text
ArtifactSet
expected_asset_names(version: str) -> tuple[str, str, str, str]
compare_artifact_sets(left: ArtifactSet, right: ArtifactSet) -> dict[str, str]
build_and_verify(source_a: Path, source_b: Path, output: Path, commit: str, epoch: int, denylist: Path | None = None) -> dict[str, str]
```

- Produces internal run-owned types with these responsibilities:

```python
@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    file_type: int
    permissions: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass
class _BoundDirectory:
    path: Path
    fd: int
    device: int
    inode: int
    permissions: int


@dataclass(frozen=True)
class _ArtifactSnapshot:
    name: str
    fd: int
    identity: _FileIdentity
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class _VerifiedPair:
    candidate_a: tuple[_ArtifactSnapshot, ...]
    candidate_b: tuple[_ArtifactSnapshot, ...]
    hashes: tuple[tuple[str, str], ...]
```

One run-scoped `ExitStack` owns every opened fd immediately after acquisition.
Directory mtime/ctime are not stable because the orchestrator creates children;
directory binding compares device, inode, type, and permissions. Artifact
binding compares the complete `_FileIdentity` and streamed digest.

- [ ] **Step 1: Add RED environment, lock, and static-input gate tables**

Add one table-driven test that independently mutates:

- the canonical flag, platform, architecture, Python patch version, negative
  epoch, mismatched ambient `SOURCE_DATE_EPOCH`, every fixed environment value,
  missing/extra/wrong installed package, and canonical-name duplicates;
- missing/duplicate/wrong lock option, malformed hash, missing/extra/wrong
  package, divergent A/B lock bytes, and intermediate `requirements` or
  `tools/release` symlinks; and
- relative/same/symlink source roots, nonempty/symlink output, arbitrary
  denylist path, and missing/symlink/nonregular fixed denylist.

Every subtest calls `build_and_verify` and asserts `candidate-a`, `candidate-b`,
`evidence`, `selected.pending`, and `selected` are all absent.

- [ ] **Step 2: Add RED binding and candidate-lifecycle tests**

Add deterministic tests named
`test_candidate_b_drift_after_validation_blocks_evidence_and_selection` and
`test_candidate_metadata_or_membership_drift_blocks_selection`. The first
seeds equal A/B sets, lets both validate, then separately replaces B's wheel
with changed bytes and with the same bytes on a new inode. The second separately
changes mode, creates a hardlink, adds a fifth member, and replaces one A or B
member after comparison. Every subtest asserts a stable failure, no successful
evidence file, and no `selected/`.

Also capture every root and artifact fd exposed by test hooks and require
`os.fstat(fd)` to raise `EBADF` after success and after each injected failure.
When source or output drift is detected after a build starts, assert that
`selected/` and successful evidence are absent; candidate directories may
remain as diagnostic state under the approved trust perimeter.

- [ ] **Step 3: Add RED payload-flow, replay, scanner, and evidence tests**

Require both candidate sets to call all four payload validators with their own
captured archive bytes and source snapshot. Require sdist replay to use the
captured A sdist payload and compare its sole regular wheel against the
approved A wheel digest. Retain the real canonical sdist integration fixture.

Assert the scanner receives exactly the candidate-A scanner, two source paths,
four packed paths, four unpacked roots, sanitized environment, and only the
fixed denylist path. Inject A or B drift from the scanner hook and require the
post-scan joint revalidation to fail.

Parse `SHA256SUMS` and `build.json` in the success fixture and compare the
entire structures with expected values derived before the test mutates any
pathname. Replace Dockerfile, lock, or artifact paths after capture and require
evidence either to use the captured bytes or the run to fail—never a new
authority.

- [ ] **Step 4: Add RED promotion ownership and race tests**

Cover all of these deterministic mutations:

- short `os.write` results until the complete snapshot payload is written;
- copy/write failure leaves only owned `selected.pending/` among promotion
  directories;
- extra member, changed payload, `0777` mode, hardlink, or pathname replacement
  immediately before the exclusive syscall;
- pending directory replacement;
- raced empty directory, regular file, valid symlink, and broken symlink at
  `selected`; and
- success and every failure path close parent, pending, candidate, artifact,
  and source descriptors.

For every mutation, assert unapproved bytes never appear under `selected/` and
competitor objects are preserved. The success case asserts exactly four
single-link `0644` files whose names, sizes, and hashes match candidate A's
approved snapshots.

- [ ] **Step 5: Run the new tests and capture genuine RED evidence**

Run the new test classes or exact methods before implementation. Expected
failures must demonstrate at least:

- candidate B replacement after validation is accepted;
- current source/output ownership is not run-scoped;
- at least one phase reopens a pathname rather than using captured bytes; and
- one fd lifecycle or promotion mutation is not yet protected.

Record the exact commands, failing assertions, and mutation flags in the Task
3 implementer report before changing production code.

- [ ] **Step 6: Implement source and output run bindings**

Use one `ExitStack` inside `build_and_verify`. Open source roots with
`O_DIRECTORY | O_NOFOLLOW`, match pathname entries to `fstat`, register closes,
and pass their fds to `capture_release_source`. Read Dockerfile and lock bytes
from those immutable source snapshots; never call `Path.read_text()` or
`Path.read_bytes()` for release authority.

For an existing output, open it without following links and verify emptiness
through the fd. For a missing output leaf, open and bind its real existing
parent, call `os.mkdir(..., dir_fd=parent_fd)` once, and fail on `EEXIST`; then
open and bind the created directory. Do not recursively create parents and do
not adopt an entry that appears after the initial check.

Task 4 continues to pass canonical mount paths to build and scanner
subprocesses. Revalidate held root bindings before and after each path-based
subprocess. Under the approved perimeter, detected drift blocks selection but
is not claimed to prevent every diagnostic candidate write by a hostile host.

- [ ] **Step 7: Capture and compare both candidate sets once**

After each build, open its candidate directory relative to the held output fd,
require the exact four names, then open all four files with `O_NOFOLLOW` and
retain their descriptors in the `ExitStack`. Reject nonregular files,
hardlinks, duplicate inodes, unsupported modes, or metadata drift while
reading. Read each fd to immutable bytes, hash it, restore its offset, and
record the full identity.

Create `_VerifiedPair` only after `filecmp.cmp(..., shallow=False)` and captured
payload equality both pass for all four names. Keep
`compare_artifact_sets(...)` as a compatibility wrapper using the same capture
and comparison helpers within a temporary `ExitStack`.

- [ ] **Step 8: Make validation, replay, scan, and evidence consume the pair**

Call Task 2's payload validators for A and B. Extract captured A payloads with
payload extractors. Capture replay output as one regular, single-link snapshot
and compare its bytes/hash to the approved A wheel.

Bracket the external scanner with root and joint A/B snapshot revalidation.
After scanning, perform one final joint check of exact candidate membership,
directory-entry-to-held-fd identity, complete metadata, and hashes for all
eight files. Serialize `SHA256SUMS` and canonical `build.json` solely from the
captured builder inputs, approved package mapping, and candidate-A snapshots.

- [ ] **Step 9: Promote only immutable A payloads**

Create and bind `selected.pending` relative to the held output fd. Write each
approved A `payload` with an explicit loop that handles short writes. Open and
retain each pending member; immediately before publication, require exact
membership, regular single-link `0644` identities, directory-entry binding,
sizes, and streamed hashes.

Call only the existing Darwin/Linux exclusive no-replace primitive after that
gate. Never reopen candidate A to choose copy bytes. Preserve existing failure
layout semantics and register every descriptor with `ExitStack` before another
fallible operation.

- [ ] **Step 10: Remove superseded pathname authority and run focused checks**

Delete or narrow helpers that establish a second authority, including any
internal use of bare `Path.open`, `Path.read_bytes`, `Path.read_text`, unbound
`stat`, or `_sha256(path)` for release decisions. Path operations used only to
form audited subprocess argv remain allowed.

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_release_artifacts -v
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_artifacts tests.test_release_archives \
  tests.test_release tests.test_public_safety -q
python3 -m compileall -q scripts/release_artifacts.py tests/test_release_artifacts.py
python3 scripts/check_public.py scripts/release_artifacts.py tests/test_release_artifacts.py
rg -n "Path\.(open|read_bytes|read_text)|exist_ok=True|os\.rename\(" \
  scripts/release_artifacts.py
git diff --check
```

Expected: all tests and safety checks pass. Search hits are absent or each is
documented as non-authoritative test/argv handling; no bare overwrite rename
exists.

- [ ] **Step 11: Run the complete suite and commit Task 3**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts src tests
python3 scripts/check_public.py \
  scripts/release_archives.py tests/test_release_archives.py \
  scripts/release_artifacts.py tests/test_release_artifacts.py
git diff --check
test "$(git diff --name-only)" = $'scripts/release_artifacts.py\ntests/test_release_artifacts.py'
test "$(git config --local user.name)" = "Will"
test "$(git config --local user.email)" = "will413028@gmail.com"
git add scripts/release_artifacts.py tests/test_release_artifacts.py
git diff --cached --check
git commit -m "fix: preserve artifact identity through release gates"
```

Expected: the full suite, compile, public scan, diff, scope, and identity gates
pass; exactly the two Task 4 files are committed; no network or Docker command
ran.

---

## Amendment completion gate

After Tasks 1-3 receive clean independent task reviews, the controller must:

1. Generate one immutable review package from the amendment starting commit
   through Task 3 HEAD and request a whole-amendment review.
2. Re-run the full suite, focused archive/artifact suites, compileall, public
   scan, exact changed-path scope, commit identity, and clean status/index
   checks at one HEAD.
3. Record the explicit trust-boundary ruling: no hostile host/same-UID writer;
   Task 5 must prove the exact Docker mount and process-isolation argv.
4. Mark the original release plan's Task 4 complete and resume Task 5 without
   changing any external authorization gate.
