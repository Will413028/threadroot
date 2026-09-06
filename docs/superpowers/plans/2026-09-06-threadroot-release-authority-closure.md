# Threadroot Release Authority Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind each canonical release candidate to its complete Git-backed
tree, publish no-clobber external authority and successful-attempt records,
require that paired authority at every Tasks 7-12 mutation boundary, and make
all ZIP consumers reject payload-bearing directory entries consistently.

**Architecture:** A new standard-library `scripts.release_candidate` module
owns canonical metadata, descriptor-held tree snapshots, exact Git-archive
comparison, external publication, and read-only verification. The canonical
builder creates and verifies the candidate authority record; only its shell
success arm creates the second receipt. Tasks 7-12 accept the pair—not a path
string—as transferable authority. Existing ZIP framing becomes the semantic
gate shared by scanners, loaders, extractors, and artifact validators.

**Tech Stack:** Python 3.11-3.14 standard library, `dataclasses`, `json`,
`hashlib`, descriptor-relative `os` APIs, `zipfile`, `unittest`, SHA-256,
Linux `renameat2(RENAME_NOREPLACE)`, and Darwin
`renameatx_np(RENAME_EXCL)`.

**Spec:**
`docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md`

## Global constraints

- Keep runtime dependencies empty. Do not change the plugin contract, product
  CLI, version, artifact names, selected artifact count, package metadata, or
  user-vault schema.
- Use only synthetic fixtures. Never put a private path, denylist payload,
  credential, vault content, or host identity in source, tests, logs, evidence,
  or commits.
- Treat the Git object database for the requested 40-character commit as the
  source authority. A post-build source snapshot is evidence, not authority.
- Keep candidate metadata bounded: 4096 entries, 64 MiB per file, 512 MiB
  total file payload, 8 MiB manifest, 16 KiB authority record, 4 KiB receipt,
  and 4096 UTF-8 bytes per recorded path.
- Use the one canonical JSON serializer from the spec and reject BOMs,
  duplicate or unknown keys, invalid UTF-8, noncanonical bytes, booleans in
  integer fields, and out-of-range integers.
- Never follow a symlink while capturing, publishing, or verifying authority.
  Reject hard links and special files; retain descriptors through before/after
  identity checks.
- External metadata paths must be absolute missing leaves below an existing
  real parent, outside both repository and candidate. Publication is
  same-filesystem, no-clobber, durable, and never repairs or deletes evidence.
- A raw authority record is diagnostic only. Every cross-shell release action
  requires its paired successful-attempt receipt and a fresh complete
  `verify-success` call.
- Runbook validation may read a candidate but must never write below its root.
  Task 10 uses one separate bound disposable validation root.
- Preserve old candidates, old path-only `.txt` records, failed-attempt
  records, and pending files as audit evidence. Never add a compatibility
  reader or migration framework.
- No Docker, network, push, PR, merge, tag, draft, upload, publish, or release
  operation is part of implementation. Those remain separately authorized
  operational steps after a clean implementation review.
- Follow strict RED-GREEN-REFACTOR. Run each named RED command before its
  implementation and capture the expected failure in the SDD ledger.
- Before each commit, stage only the listed paths and require repository-local
  Git identity `Will` / `will413028@gmail.com`.

## Current execution state

The branch `release/v0.1.0-readiness` is at approved spec commit `33c324d`.
The approved spec's status line is the only tracked implementation-worktree
change before this plan; this plan itself is the only new file. Existing
canonical candidates predate the authority protocol and remain diagnostic
evidence only. Any implementation commit requires a new explicitly authorized
canonical Docker build and two fresh independent whole-branch reviews.

## File map

| Path | Responsibility |
|---|---|
| `scripts/release_candidate.py` | Canonical schemas, candidate snapshots, Git source authority, external publication, receipt, verifier, and CLI |
| `tests/test_release_candidate.py` | Synthetic candidate, schema, drift, publication, race, receipt, and CLI tests |
| `scripts/build_verified_release.py` | Required outer authority argument, pre-Docker path gate, runner-byte binding, bind/verify calls, and final status |
| `tests/test_verified_release.py` | Outer/inside argument, preflight ordering, runner binding, failure, and builder-success tests |
| `scripts/release_archives.py` | Shared ZIP directory-payload invariant |
| `tests/test_release_archives.py` | Stored/DEFLATE framing and loader controls |
| `scripts/check_public.py` | Public scanner consumption of shared framing |
| `tests/test_public_safety.py` | Scanner API and sanitized CLI regressions |
| `.github/workflows/ci.yml` | Canonical authority + receipt CI invocation |
| `docs/testing.md` | Local canonical authority + receipt invocation |
| `tests/test_documentation.py` | Exact CI/docs commands and Tasks 7-12 shell authority contracts |
| `docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md` | Operational Tasks 7-12 authority flow and state placement |

## Authority and state map

| Phase | Required pair | Candidate-root writes allowed | State outputs |
|---|---|---:|---|
| Task 7 build/review | external HEAD+attempt `.authority.json` + `.success.json` | builder creates manifest only; reviewers none | no state before final verification |
| Task 7 binding | same external pair, then byte-identical state copies | no | `candidate-authority.json`, `candidate-success.json`, `candidate-root.txt`, `reviewed-head.txt` |
| Task 8 PR | state candidate pair | no | `pr-checks.json`, `pr.diff` under state root |
| Task 9 merge/final build | candidate pair before merge; state `final-authority.json` + `final-success.json` after build | final builder creates manifest only | final pair and `final-root.txt` |
| Tasks 10-12 | state final pair before every mutator | no | `validation-root.txt` plus existing state evidence |

---

### Task 0: Commit the approved design and executable plan baseline

**Files:**

- Modify: `docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md`
- Create: `docs/superpowers/plans/2026-09-06-threadroot-release-authority-closure.md`

**Interfaces:** None. This task records the already-approved design boundary
before production code changes.

- [ ] **Step 1: Confirm the baseline contains only the approved status and this plan**

Run:

```bash
git status --short
git diff -- docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md
```

Expected: one modified approved spec and one untracked plan. The spec diff is
only `Draft pending written-spec approval` to
`Approved by Will on 2026-09-06; implementation plan drafted`.

- [ ] **Step 2: Verify both public documents**

Run:

```bash
python3 scripts/check_public.py \
  docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md \
  docs/superpowers/plans/2026-09-06-threadroot-release-authority-closure.md
if rg -n '[[:blank:]]+$' \
  docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md \
  docs/superpowers/plans/2026-09-06-threadroot-release-authority-closure.md; then
  exit 1
fi
git diff --check
```

Expected: public scan, whitespace scan, and diff check all exit zero.

- [ ] **Step 3: Commit only the approved planning baseline**

Run:

```bash
test "$(git config --local user.name)" = "Will"
test "$(git config --local user.email)" = "will413028@gmail.com"
git add \
  docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md \
  docs/superpowers/plans/2026-09-06-threadroot-release-authority-closure.md
git diff --cached --check
git commit -m "docs: plan release authority closure"
```

Expected: exactly the two named documents are committed and the worktree is
clean.

---

### Task 1: Build a bounded canonical manifest from a Git-backed candidate

**Files:**

- Create: `scripts/release_candidate.py`
- Create: `tests/test_release_candidate.py`

**Interfaces introduced in this task:**

```text
CandidateIntegrityError(RuntimeError)
_canonical_json(value: object) -> bytes
_capture_candidate(candidate_root: Path) -> CandidateSnapshot
_write_candidate_manifest(candidate_root: Path, commit: str) -> None
_verify_candidate_manifest(candidate_root: Path, commit: str) -> None
```

`_capture_candidate` excludes only
`build/evidence/candidate-integrity.json`. It returns entries ordered by
root-relative POSIX path and enforces exact top-level membership
`source-a/`, `source-b/`, and `build/`.

- [ ] **Step 1: Add real temporary Git/candidate fixtures and failing manifest tests**

Build a fixture with a temporary Git repository, configure a synthetic Git
identity, commit a small package tree, obtain its exact commit, export that
commit twice through `git archive`, and create these exact candidate members:

```text
source-a/<tracked Git tree>
source-b/<tracked Git tree>
build/candidate-a/threadroot-0.1.0-py3-none-any.whl
build/candidate-a/threadroot-0.1.0.tar.gz
build/candidate-a/threadroot-claude-plugin-0.1.0.zip
build/candidate-a/threadroot-codex-plugin-0.1.0.zip
build/candidate-b/<same four names and bytes>
build/evidence/build.json
build/evidence/SHA256SUMS
build/selected/<same four names and bytes>
```

Add these tests first:

Test names:

- `test_clean_manifest_covers_the_complete_tree_and_exact_git_export`
- `test_manifest_is_canonical_bounded_and_mode_0444`
- `test_preexisting_manifest_and_manifest_creation_race_never_overwrite`
- `test_added_modified_replaced_or_mode_changed_member_is_rejected`
- `test_hard_link_symlink_and_special_member_are_rejected`
- `test_source_asymmetry_wrong_commit_and_non_git_source_are_rejected`
- `test_entry_file_total_path_and_manifest_bounds_fail_closed`
- `test_duplicate_unknown_noncanonical_boolean_and_range_values_are_rejected`

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_candidate.CandidateManifestTests -v
```

Expected RED: import failure because `scripts.release_candidate` does not
exist. Keep the fixture fully synthetic and do not mock filesystem identity,
hashing, Git, or archive parsing.

- [ ] **Step 2: Implement canonical JSON and strict field validation**

Use this serializer verbatim:

```python
def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
```

Decode with `utf-8` strict, an `object_pairs_hook` that rejects duplicate
keys, exact key-set validators at every object level, explicit
`type(value) is int` checks, and a byte-for-byte canonical reserialization
check. Define named constants for every limit in the spec; tests patch those
constants downward rather than allocating hundreds of MiB.

- [ ] **Step 3: Implement descriptor-held traversal and manifest publication**

For every directory entry, use parent-relative no-follow opens and `fstat`.
For every file, require regular type, `st_nlink == 1`, capture identity before
and after streaming SHA-256, and reject changes. Accumulate count and payload
bounds before appending an entry. Record directories without link count,
size, or timestamps and files with the exact schema fields from the spec.

Before writing the manifest:

1. capture the complete covered tree;
2. safely parse a fresh `git archive --format=tar <commit>` and require its
   sole global PAX `comment` to equal the requested commit;
3. compare both source trees to that Git membership, kind, canonical mode,
   size, and SHA-256 authority;
4. write the canonical manifest through `O_CREAT|O_EXCL|O_NOFOLLOW`, `fsync`,
   and `fchmod(0444)`; and
5. capture the covered tree again and require equality with the first
   snapshot.

Do not import from either candidate source tree. Reuse the safe tar framing
and mode normalization core from `scripts.release_archives`; do not add a
second permissive tar parser.

- [ ] **Step 4: Reach GREEN and verify the new module**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_candidate.CandidateManifestTests -v
python3 -m compileall -q scripts/release_candidate.py tests/test_release_candidate.py
python3 scripts/check_public.py scripts/release_candidate.py tests/test_release_candidate.py
git diff --check
```

Expected: all manifest tests pass; compile, public scan, and diff checks exit
zero.

- [ ] **Step 5: Commit the manifest core**

Run:

```bash
git add scripts/release_candidate.py tests/test_release_candidate.py
git diff --cached --check
git commit -m "feat: bind complete release candidate trees"
```

Expected: exactly the new module and test file are committed.

---

### Task 2: Publish and verify the external candidate authority record

**Files:**

- Modify: `scripts/release_candidate.py`
- Modify: `tests/test_release_candidate.py`

**Public interfaces completed in this task:**

```text
def bind_candidate(
    candidate_root: Path,
    commit: str,
    authority_record: Path,
) -> None


def verify_candidate(
    authority_record: Path,
    expected_commit: str,
) -> Path
```

- [ ] **Step 1: Add failing record, publication, and complete-verifier tests**

Add these groups before implementation:

Test names:

- `test_clean_candidate_binds_and_verifies_to_its_recorded_root`
- `test_record_is_canonical_single_link_regular_0400_and_bounded`
- `test_record_path_must_be_absolute_missing_external_and_safe`
- `test_existing_symlink_pending_and_competing_paths_are_never_replaced`
- `test_parent_fsync_or_post_publish_verify_failure_never_reports_success`
- `test_published_failure_evidence_is_preserved_and_not_repaired`
- `test_record_schema_bytes_identity_mode_link_and_replacement_races_fail`
- `test_every_candidate_member_and_coedited_artifact_evidence_drift_fails`
- `test_repeated_snapshot_detects_a_concurrent_candidate_change`

Mutation cases must include added `__pycache__`, changed source byte,
same-byte inode replacement, source mode change, hard link, extra member,
changed evidence, changed selected artifact, and a selected artifact plus
`SHA256SUMS` co-edit.

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_candidate.CandidateAuthorityTests -v
```

Expected RED: the public functions are absent or do not publish/verify the
required record.

- [ ] **Step 2: Implement no-clobber durable publication once**

Add one private primitive shared later by record and receipt:

```python
def _publish_exclusive(
    destination: Path,
    payload: bytes,
    *,
    final_mode: int,
    maximum_size: int,
) -> None
```

Resolve and validate the real parent without following a final symlink. Open
an adjacent process-owned unpredictable pending leaf with
`O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` and mode `0600`; write all bytes, apply
the final mode, `fsync` the file, then publish through a dedicated
`_rename_exclusive` helper that ports the already-tested
`renameat2(RENAME_NOREPLACE)` / `renameatx_np(RENAME_EXCL)` syscall pattern
from `release_artifacts` without importing its private build state. `fsync`
the held parent descriptor after publication. Never use a check-then-rename
fallback.
After the publication commit point, re-open and verify the canonical file.
Never unlink a pending, competing, or published path on error.

- [ ] **Step 3: Implement binding and the full read-only verification boundary**

`bind_candidate` must require a normalized absolute candidate root that is a
real `0700` directory, write and self-verify the manifest, derive the exact
candidate and manifest identity objects, exclusively publish the record, then
call the same `verify_candidate` used downstream. `verify_candidate` must:

1. hold and strictly parse the record;
2. validate commit and candidate-root identity;
3. hold and validate manifest identity and hash;
4. compare one complete live tree snapshot to all manifest entries;
5. compare both sources to a fresh exact-commit Git archive;
6. check exact four-file, regular/single-link/`0644`, equal A/B/selected
   artifact sets;
7. strictly verify `build.json` and `SHA256SUMS` against commit and all three
   artifact sets; and
8. repeat tree, root, manifest, record, and held-descriptor identity checks
   before returning the normalized candidate path.

Map every internal failure to `CandidateIntegrityError`; messages are never
rendered by the public CLI.

- [ ] **Step 4: Reach GREEN and run manifest regressions**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_candidate.CandidateManifestTests \
  tests.test_release_candidate.CandidateAuthorityTests -v
python3 -m compileall -q scripts/release_candidate.py tests/test_release_candidate.py
python3 scripts/check_public.py scripts/release_candidate.py tests/test_release_candidate.py
git diff --check
```

Expected: both groups pass and no validator or safety regression appears.

- [ ] **Step 5: Commit the external authority boundary**

Run:

```bash
git add scripts/release_candidate.py tests/test_release_candidate.py
git diff --cached --check
git commit -m "feat: publish candidate authority records"
```

---

### Task 3: Add successful-attempt receipts and the sanitized CLI

**Files:**

- Modify: `scripts/release_candidate.py`
- Modify: `tests/test_release_candidate.py`

**Public interfaces completed in this task:**

```text
def record_successful_attempt(
    authority_record: Path,
    expected_commit: str,
    success_receipt: Path,
) -> None


def verify_successful_attempt(
    success_receipt: Path,
    authority_record: Path,
    expected_commit: str,
) -> Path
```

CLI subcommands are `verify`, `record-success`, and `verify-success`, with the
exact arguments and silent-success behavior in the spec.

- [ ] **Step 1: Add failing receipt and CLI tests**

Test names:

- `test_receipt_binds_exact_record_bytes_size_and_commit`
- `test_raw_record_alone_is_not_successful_attempt_authority`
- `test_receipt_is_canonical_single_link_regular_0400_and_bounded`
- `test_missing_malformed_noncanonical_changed_or_replaced_receipt_fails`
- `test_preexisting_receipt_and_publication_race_never_overwrite`
- `test_byte_identical_safe_record_and_receipt_copies_remain_valid`
- `test_record_and_receipt_descriptors_are_held_through_complete_verification`
- `test_all_three_subcommands_are_silent_on_success`
- `test_all_failures_emit_only_the_fixed_error_and_exit_nonzero`

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_candidate.SuccessfulAttemptTests \
  tests.test_release_candidate.ReleaseCandidateCliTests -v
```

Expected RED: receipt functions and subcommands do not exist.

- [ ] **Step 2: Implement receipt publication and paired verification**

Before receipt publication, freshly call the complete candidate verifier and
read the authority record through one held no-follow descriptor. Derive the
receipt only from those held canonical bytes:

```python
{
    "authority_record_sha256": hashlib.sha256(record_bytes).hexdigest(),
    "authority_record_size": len(record_bytes),
    "commit": expected_commit,
    "schema": 1,
}
```

Publish with `_publish_exclusive(destination, payload, final_mode=0o400,
maximum_size=4 * 1024)`. `verify_successful_attempt` must hold both metadata
files simultaneously, verify the receipt's size and digest against the held
record bytes, perform complete candidate verification without trusting a
later record reopen, then repeat both metadata identities before returning.

- [ ] **Step 3: Implement the fixed-output CLI**

The module entry point catches all expected validation and OS failures, emits
exactly this one line to stderr, emits nothing to stdout, and exits nonzero:

```text
candidate integrity verification failed
```

On success all subcommands emit nothing. Do not print arguments, paths,
payloads, exception text, or tracebacks.

- [ ] **Step 4: Reach GREEN and run the complete module suite**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_release_candidate -v
python3 -m compileall -q scripts/release_candidate.py tests/test_release_candidate.py
python3 scripts/check_public.py scripts/release_candidate.py tests/test_release_candidate.py
git diff --check
```

Expected: every manifest, authority, receipt, race, and CLI test passes.

- [ ] **Step 5: Commit successful-attempt authority**

Run:

```bash
git add scripts/release_candidate.py tests/test_release_candidate.py
git diff --cached --check
git commit -m "feat: attest successful release attempts"
```

---

### Task 4: Integrate authority into the canonical builder, CI, and testing guide

**Files:**

- Modify: `scripts/build_verified_release.py`
- Modify: `tests/test_verified_release.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/testing.md`
- Modify: `tests/test_documentation.py`

**Builder contract:** Outer mode requires
`--authority-record ABSOLUTE_MISSING_PATH`; inside mode rejects it. The path
gate runs before Docker inspection/build/run. `scripts/release_candidate.py`
is included in `RUNNER_FILES`. Builder success binds and re-verifies the
candidate, but never creates a success receipt.

- [ ] **Step 1: Add failing outer/inside, ordering, runner, and success tests**

Add or update these tests:

Test names:

- `test_outer_mode_requires_an_absolute_missing_external_authority_record`
- `test_authority_preflight_fails_before_any_docker_command`
- `test_inside_mode_rejects_authority_record`
- `test_runner_files_bind_release_candidate_module_bytes`
- `test_builder_binds_then_verifies_before_fixed_success_message`
- `test_builder_failure_never_creates_a_success_receipt`
- `test_ci_canonical_build_records_and_verifies_success`
- `test_testing_guide_canonical_build_records_and_verifies_success`

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_verified_release \
  tests.test_documentation.DocumentationTests.test_ci_workflow_matches_the_locked_contract \
  tests.test_documentation.DocumentationTests.test_testing_guide_uses_the_canonical_release_command -v
```

Expected RED: the parser, runner list, builder calls, and exact documentation
commands lack the new authority flow.

- [ ] **Step 2: Change the builder boundary**

Add `scripts/release_candidate.py` to the exact runner-byte map. Parse the
authority path in outer mode and perform all lexical, absolute, external,
real-parent, and missing-leaf checks before the first Docker subprocess.
Inside mode must reject the argument rather than ignore it.

After Docker returns zero, call:

```python
bind_candidate(output, commit, authority_record)
verified_root = verify_candidate(authority_record, commit)
if verified_root != output.resolve(strict=True):
    raise VerifiedReleaseError("candidate integrity verification failed")
```

Only then print exactly `verified release build completed`. Convert all
candidate-authority failures to one fixed public builder error without an
untrusted path or payload. Do not call `record_successful_attempt` here.

- [ ] **Step 3: Replace the canonical CI/docs command with the success arm**

Both locations must create separate missing candidate, authority, and receipt
paths and execute this order:

```bash
python3 -B scripts/build_verified_release.py \
  --output "$candidate_root" \
  --commit "$release_commit" \
  --epoch "$release_epoch" \
  --denylist "$denylist" \
  --authority-record "$authority_record"
python3 -B -m scripts.release_candidate record-success \
  --authority-record "$authority_record" \
  --expected-commit "$release_commit" \
  --success-receipt "$success_receipt"
python3 -B -m scripts.release_candidate verify-success \
  --authority-record "$authority_record" \
  --expected-commit "$release_commit" \
  --success-receipt "$success_receipt"
```

The shell must stop after any nonzero command; no failure branch may call
`record-success`. Update exact command constants and shell fixtures in
`tests/test_documentation.py` rather than loosening them to substring checks.

- [ ] **Step 4: Reach GREEN and run builder/documentation regressions**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_verified_release \
  tests.test_documentation -v
python3 -m compileall -q \
  scripts/build_verified_release.py \
  tests/test_verified_release.py \
  tests/test_documentation.py
python3 scripts/check_public.py \
  scripts/build_verified_release.py \
  tests/test_verified_release.py \
  .github/workflows/ci.yml \
  docs/testing.md \
  tests/test_documentation.py
git diff --check
```

Expected: all tests pass and no Docker command is reached by an invalid
authority target.

- [ ] **Step 5: Commit canonical builder integration**

Run:

```bash
git add \
  scripts/build_verified_release.py \
  tests/test_verified_release.py \
  .github/workflows/ci.yml \
  docs/testing.md \
  tests/test_documentation.py
git diff --cached --check
git commit -m "build: bind canonical release candidates"
```

---

### Task 5: Make shared ZIP framing reject directory payloads

**Files:**

- Modify: `scripts/release_archives.py`
- Modify: `tests/test_release_archives.py`
- Modify: `scripts/check_public.py`
- Modify: `tests/test_public_safety.py`

**Invariant:** After local/central record agreement and before a validated
member is returned, `ZipInfo.is_dir()` implies `file_size == 0`. Both stored
and DEFLATE empty directories remain valid.

- [ ] **Step 1: Add failing stored and DEFLATE framing/loader tests**

Create synthetic `ZipInfo("safe/")` directory entries with Unix directory
mode and either `ZIP_STORED` or `ZIP_DEFLATED`. Give the negative variants a
nonempty synthetic payload; give controls `b""`.

Add:

Test names:

- `test_zip_framing_rejects_stored_directory_with_payload`
- `test_zip_framing_rejects_deflated_directory_with_payload`
- `test_zip_framing_accepts_empty_stored_and_deflated_directories`
- `test_zip_loader_rejects_directory_payload_before_interpretation`

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_archives.ReleaseArchiveTests.test_zip_framing_rejects_stored_directory_with_payload \
  tests.test_release_archives.ReleaseArchiveTests.test_zip_framing_rejects_deflated_directory_with_payload \
  tests.test_release_archives.ReleaseArchiveTests.test_zip_framing_accepts_empty_stored_and_deflated_directories \
  tests.test_release_archives.ReleaseArchiveTests.test_zip_loader_rejects_directory_payload_before_interpretation -v
```

Expected RED: framing accepts the internally consistent payload-bearing
directory before the generic loader interprets it.

- [ ] **Step 2: Add failing public scanner API and sanitized CLI tests**

Embed a synthetic denied term inside both payload-bearing directory variants.
Assert API callers get a scan error. Assert CLI exit `2`, empty stdout, fixed
sanitized stderr, and no denied term, path, archive member, raw control
character, or internal exception in either stream.

Run the two new scanner tests directly. Expected RED: the scanner skips the
directory after `ZipInfo.is_dir()` and reports the archive clean.

- [ ] **Step 3: Enforce the invariant in shared framing only**

In `_validate_zip_structure`, after local/central size, CRC, method, flags,
and stream agreement but before appending/returning `ValidatedZipMember`, add
the semantic gate:

```python
if info.is_dir() and info.file_size != 0:
    raise _fail("invalid_archive", "ZIP directory payload must be empty")
```

Do not add a scanner-only policy and do not reject nonzero compressed framing
for an empty DEFLATE stream. `check_public` should retain its existing mapping
from framing failure to unreadable unsafe input and fixed CLI error.

- [ ] **Step 4: Reach GREEN across all archive consumers**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_archives \
  tests.test_public_safety -v
python3 -m compileall -q \
  scripts/release_archives.py \
  tests/test_release_archives.py \
  scripts/check_public.py \
  tests/test_public_safety.py
python3 scripts/check_public.py \
  scripts/release_archives.py \
  tests/test_release_archives.py \
  scripts/check_public.py \
  tests/test_public_safety.py
git diff --check
```

Expected: framing, loader, extractor, artifact validation, scanner API, and
CLI agree; both empty-directory controls pass.

- [ ] **Step 5: Commit the shared ZIP invariant**

Run:

```bash
git add \
  scripts/release_archives.py \
  tests/test_release_archives.py \
  scripts/check_public.py \
  tests/test_public_safety.py
git diff --cached --check
git commit -m "fix: reject payload-bearing zip directories"
```

---

### Task 6: Rewrite Tasks 7-12 around paired successful-attempt authority

**Files:**

- Modify: `docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md`
- Modify: `tests/test_documentation.py`

**Runbook contract:** Retain existing authorization gates and Bash-block
counts `{7: 4, 8: 3, 9: 4, 10: 7, 11: 3, 12: 3}`. Replace path-only candidate
trust with explicit paired verification; do not merely append a new check
after a mutator.

- [ ] **Step 1: Add failing Task 7 build/review/binding shell tests**

Extend the fake-command harness so every `release_candidate` subcommand and
every external mutator is logged separately. The positive candidate fixture
must contain both exact source exports plus the complete build tree. Add tests
that prove:

- builder failure never reaches `record-success`;
- a raw record with no receipt cannot begin review or create state;
- each reviewer runs `verify-success` at entry and exit using `python3 -B`;
- post-review candidate drift prevents state-root creation;
- successful binding copies exact record/receipt bytes with mode `0400`, then
  verifies the copied pair before returning; and
- `candidate-root.txt` and `reviewed-head.txt` agree with the trusted record.

Run the new Task 7 tests. Expected RED: the old block writes a path-only
`.txt` record and its incomplete fixture accepts source-tree drift.

- [ ] **Step 2: Rewrite Task 7 without changing its four-block shape**

The build block creates HEAD+attempt-qualified missing paths, passes the
authority record directly to the builder, calls `record-success` only on the
zero-exit arm, then calls `verify-success`. Reviewer blocks verify the pair at
entry and exit and use worktree-owned Python only with `-B`.

The final binding block must execute this order:

1. read unchanged reviewed HEAD and external pair paths;
2. `verify-success` before creating any state path;
3. parse `candidate_root` only from the now-trusted canonical record;
4. create a new state directory;
5. exclusively copy the record and receipt bytes to
   `candidate-authority.json` and `candidate-success.json` with mode `0400`;
6. exclusively write `candidate-root.txt` and `reviewed-head.txt`;
7. `verify-success` against the state copies; and
8. require all four values to agree before emitting completion.

Do not use `cp` with overwrite semantics. The shell's small Python copy
helper must use `open(destination, "xb")`, write held source bytes, `flush`,
`os.fsync`, `os.chmod(0o400)`, and parent `fsync`.

- [ ] **Step 3: Add failing Task 8-12 mutation-boundary tests**

Add discriminating shell tests that introduce authority drift immediately
before one mocked mutation in each task. Assert the mock was never invoked.
Also add positive tests proving:

- Task 8 Step 3 writes `pr-checks.json` and `pr.diff` below state, leaves the
  candidate byte-identical, and re-verifies before push and PR creation;
- Task 9 verifies the candidate pair immediately before merge, then uses new
  missing state-local `final-authority.json` and `final-success.json` paths;
- Task 10 records one external `0700` validation root and places the venv,
  CLI fixture, Claude smoke root, and Codex smoke root below it; and
- Tasks 10-12 verify the final pair immediately before each install, upload,
  tag, draft, and publish command.

Run all new authority-flow tests. Expected RED: old blocks trust path text,
write PR evidence or validation files under candidates, or invoke mutators
without paired verification.

- [ ] **Step 4: Rewrite Task 8 and Task 9 state transitions**

At the beginning and immediately before every external mutation, run:

```bash
python3 -B -m scripts.release_candidate verify-success \
  --authority-record "$state_root/candidate-authority.json" \
  --expected-commit "$reviewed_head" \
  --success-receipt "$state_root/candidate-success.json"
```

Task 8 stores every PR check and diff under `state_root`; update every later
reader to the same path. Task 9 repeats the check immediately before its merge
command. For the merged commit, the final builder writes the new
`state_root/final-authority.json`; only its zero-exit arm creates
`state_root/final-success.json`. Verify that pair before writing
`final-root.txt`.

- [ ] **Step 5: Rewrite Tasks 10-12 final authority and validation roots**

Every shell block that can install, upload, tag, create a draft, or publish
must first read the merged commit and invoke `verify-success` on
`final-authority.json` plus `final-success.json`. Only after success may it
parse the final candidate root from the trusted record.

Task 10 exclusively creates one separate temporary `0700` directory outside
the repository and final candidate, then exclusively records it in
`validation-root.txt`. Put all four validation subtrees below that root. Keep
fresh-download and selected-artifact hash checks; they remain defense in
depth. End every Task 10 block with paired candidate verification so a tool
that wrote into the candidate invalidates the workflow.

- [ ] **Step 6: Reach GREEN without loosening exact shell contracts**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_documentation -v
python3 -m compileall -q tests/test_documentation.py
python3 scripts/check_public.py \
  docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md \
  tests/test_documentation.py
git diff --check
```

Expected: exact Bash-block counts remain unchanged; positive flows preserve
candidate validity; every injected drift stops before its named mutator.

- [ ] **Step 7: Commit the operational authority flow**

Run:

```bash
git add \
  docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md \
  tests/test_documentation.py
git diff --cached --check
git commit -m "docs: bind release runbooks to successful candidates"
```

---

### Task 7: Prove closure and hand off a new canonical-build boundary

**Files:**

- Verify all files changed by Tasks 0-6
- Modify the approved spec status only if every check below passes

- [ ] **Step 1: Run the focused authority and ZIP suites**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_candidate \
  tests.test_verified_release \
  tests.test_release_archives \
  tests.test_public_safety \
  tests.test_documentation -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete suite on every supported interpreter**

Run:

```bash
for python in python3.11 python3.12 python3.13 python3.14; do
  command -v "$python"
  PYTHONPATH=src:. "$python" -m unittest discover -s tests -q
done
```

Expected: all four interpreters exist and the full suite passes under each.
Do not substitute a narrower matrix.

- [ ] **Step 3: Run static, public-safety, and plan-consistency gates**

Run:

```bash
python3 -m compileall -q src scripts tests
python3 scripts/check_public.py .
git diff --check
if rg -n 'T[B]D|T[O]DO|FIX[M]E|implement[ ]later|same[ ]as[ ]above|similar[ ]to' \
  docs/superpowers/plans/2026-09-06-threadroot-release-authority-closure.md; then
  exit 1
fi
rg -n -- '--authority-record|record-success|verify-success' \
  .github/workflows/ci.yml \
  docs/testing.md \
  docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md
if rg -n 'candidate_root/.+(pr-checks\.json|pr\.diff|\.venv|smoke)' \
  docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md; then
  exit 1
fi
```

Expected: compilation, repository scan, and diff checks pass; no placeholder
or prohibited candidate-local evidence/validation write remains; every
canonical entry point visibly uses the paired authority protocol.

- [ ] **Step 4: Perform two independent read-only reviews**

Reviewer one checks spec compliance across manifest/record/receipt schemas,
bounds, races, builder order, runbook mutation boundaries, and ZIP consumers.
Reviewer two checks code quality, failure sanitization, descriptor lifetime,
test discrimination, and preservation of existing release invariants. These
are source reviews backed by synthetic tests; they do not run Docker or treat
an old candidate as authority. The later operational Task 7 reviewers must
rerun `verify-success` against the future newly authorized candidate.

Expected: no Critical, Important, or material Medium finding remains. Fixes
restart the affected focused suite and invalidate any candidate built before
the fix.

- [ ] **Step 5: Mark the amendment implemented and commit closure evidence**

Only after Steps 1-4 pass, change the design status to:

```text
**Status:** Implemented and verified; canonical rebuild authorization pending
```

Then run:

```bash
python3 scripts/check_public.py \
  docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md
git diff --check
git add docs/superpowers/specs/2026-09-06-threadroot-release-authority-closure-design.md
git diff --cached --check
git commit -m "docs: close release authority implementation"
git status --short
```

Expected: the status-only documentation commit succeeds and the worktree is
clean. Stop here. Report that all older candidates are invalid for release
and request separate authorization for the new canonical Docker build; do not
run Docker or any external release operation.

## Spec coverage audit

| Approved spec requirement | Implemented by |
|---|---|
| Complete bounded manifest, strict canonical JSON, exact Git source authority | Task 1 |
| External record, exclusive publication, full repeated verifier | Task 2 |
| Successful-attempt receipt, raw-record rejection, sanitized CLI | Task 3 |
| Required builder argument, pre-Docker gate, runner-byte binding, CI/docs flow | Task 4 |
| Shared ZIP directory-payload invariant and scanner contract | Task 5 |
| Tasks 7-12 paired authority, state evidence, no candidate writes | Task 6 |
| Python 3.11-3.14, full suite, static/public checks, independent reviews | Task 7 |
| No signing, remote attestation, adapter, migration, or candidate repair | Global constraints and Task 7 stop boundary |
