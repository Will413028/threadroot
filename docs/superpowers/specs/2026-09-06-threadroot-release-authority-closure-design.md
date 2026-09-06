# Threadroot Release Authority Closure Design

**Date:** 2026-09-06
**Status:** Implemented and verified; canonical rebuild authorization pending
**Amends:** `2026-09-05-threadroot-v0.1.0-release-readiness-design.md`

## Purpose

Close two release-readiness gaps found by the final whole-branch review:

1. a canonical candidate can drift after its build while the current final
   binding still succeeds; and
2. a ZIP directory member can carry a non-empty payload that the shared
   framing accepts and the public scanner skips.

This amendment does not change Threadroot's runtime CLI, plugin package
contract, artifact formats or selection, supported Python versions,
dependency policy, or user-vault schema. The new release-safety source and
tests necessarily produce new canonical sdist hashes; no artifact is
post-processed or normalized after its build.

## Observed Failure

A read-only review command executed `check_public.py` from a candidate source
tree without `-B` or `PYTHONDONTWRITEBYTECODE=1`. Python imported two sibling
modules and created `scripts/__pycache__/` plus two bytecode files in
`source-a` after the reviewer had compared both source exports. Candidate A,
candidate B, selected artifacts, and their recorded hashes did not change, but
the reviewed candidate no longer contained two exact exports of its commit.

The existing Task 7 binding checked only `build.json.commit` and the selected
files against the co-located `SHA256SUMS`. It did not recheck either source
tree or bind `build.json` and `SHA256SUMS` to an authority outside the mutable
candidate root. Its positive integration fixture contained no source exports
and still passed. Reviewer hygiene would have prevented this instance, but it
cannot enforce the release invariant.

An independent synthetic ZIP probe also produced a directory entry whose
uncompressed size was nonzero. The raw local/central framing, DEFLATE stream,
CRC, and sizes were internally consistent, so shared framing accepted it.
The generic archive loader rejected it, while the public scanner skipped it
at `ZipInfo.is_dir()` and reported no finding. The same archive therefore had
different validity depending on its consumer.

## Options Considered

### A. Reviewer hygiene only

Require `python -B` or `PYTHONDONTWRITEBYTECODE=1` and tell reviewers not to
execute candidate-local code.

This is necessary defense in depth but rejected as the authority mechanism.
A forgotten flag, another tool with write side effects, or drift after review
would still pass the current binding.

### B. Recursively remove write permissions

Make every candidate source and evidence file read-only after the build.

This is rejected as the primary mechanism. Rewriting source modes conflicts
with later archive validation against canonical Git modes, and portable
filesystem immutability is not available across supported hosts. Permissions
also do not establish which bytes were approved.

### C. Content-and-identity manifest with external attempt authority

Record the complete candidate tree immediately after the canonical build,
anchor that manifest in a separate exclusive record, attest the successful
build attempt with a second no-clobber receipt, and require a fresh read-only
verifier at every authority transition.

This is adopted. It detects accidental post-build drift, preserves canonical
source modes, and extends the existing descriptor/snapshot model across
process and shell boundaries without claiming protection from the malicious
host actor excluded by the release threat model.

## Candidate Integrity Manifest

Every successful outer canonical build creates exactly one local evidence
file at:

```text
build/evidence/candidate-integrity.json
```

The file is canonical UTF-8 JSON with one trailing newline, exact schema 1,
mode `0444`, and one regular-file link. It contains:

```json
{
  "commit": "0000000000000000000000000000000000000000",
  "entries": [
    {
      "ctime_ns": 0,
      "device": 0,
      "gid": 0,
      "inode": 0,
      "kind": "file",
      "mode": "0644",
      "mtime_ns": 0,
      "nlink": 1,
      "path": "source-a/README.md",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "size": 0,
      "uid": 0
    }
  ],
  "schema": 1
}
```

The numeric zeros above illustrate types only; the manifest records the live
values. Its exact wire contract is:

| Object | Exact keys and value types |
| --- | --- |
| top level | `schema`: integer exactly `1`; `commit`: lowercase 40-character hexadecimal string; `entries`: array |
| directory entry | `device`, `inode`, `uid`, `gid`: non-negative integers; `kind`: string exactly `directory`; `mode`: four-character octal string; `path`: string |
| regular-file entry | all directory identity keys except with `kind` exactly `file`, plus `nlink`: integer exactly `1`; `size`: non-negative integer; `mtime_ns`, `ctime_ns`: signed integers; `sha256`: lowercase 64-character hexadecimal string |

Entries are ordered by candidate-root-relative POSIX path. Each path is
normalized, relative, non-empty, at most 4096 UTF-8 bytes, free of control
characters and surrogate code points, and unique. Directories omit link
count, size, and timestamps because writing the manifest itself necessarily
changes its parent directory metadata. Regular files include streamed
SHA-256.

The manifest covers every directory and regular file beneath the candidate
root except the manifest file itself. No symlink, hard-linked regular file,
socket, FIFO, device, or other special entry is accepted. The exact top-level
membership remains `source-a/`, `source-b/`, and `build/`. The scanner uses
bounded traversal: at most 4096 entries, at most 64 MiB per regular file, and
at most 512 MiB of regular-file payload in total. The serialized manifest is
limited to 8 MiB. Exceeding a bound fails the candidate rather than truncating
its authority.

All three metadata formats in this design use one canonical serializer:
`json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
separators=(",", ":"))`, UTF-8 encoding, and exactly one trailing LF. Reads
reject a BOM, invalid UTF-8, duplicate or unknown keys, noncanonical bytes,
and a Boolean where an integer is required. Integers use JSON decimal form;
filesystem identity values are limited to `0..2^64-1`, signed timestamps to
`-2^63..2^63-1`, entry sizes to the stated per-file limit, and the manifest
size in the external record to `1..8 MiB`. Modes match `0[0-7]{3}`. These
ranges are checked explicitly rather than inherited from Python's numeric
coercions.

Manifest construction uses held no-follow descriptors and before/after
identity checks. It captures the tree once, writes the manifest exclusively,
captures the covered tree again, and requires both snapshots to match before
creating any external authority record. Before the manifest write, both live
source trees must also match a freshly read, safely parsed `git archive` of
the exact commit, including its sole expected global PAX comment. This makes
the Git object database, rather than a post-Docker source snapshot, the source
content authority.

## External Authority Record

The outer entry point gains a required outer-mode argument:

```text
--authority-record ABSOLUTE_MISSING_PATH
```

Inside mode rejects this argument. The record must be outside both the
repository and candidate root, its real parent must already exist, and the
final path must be missing. An existing file, symlink, control character, or
unsafe parent fails before Docker provisioning begins.

After manifest self-verification, the builder creates a canonical schema-1
JSON record with this exact shape:

```json
{
  "candidate": {
    "device": 0,
    "gid": 0,
    "inode": 0,
    "mode": "0700",
    "uid": 0
  },
  "candidate_root": "/absolute/candidate/path",
  "commit": "0000000000000000000000000000000000000000",
  "manifest": {
    "ctime_ns": 0,
    "device": 0,
    "gid": 0,
    "inode": 0,
    "mode": "0444",
    "mtime_ns": 0,
    "nlink": 1,
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "size": 1,
    "uid": 0
  },
  "schema": 1
}
```

The exact record types are:

| Object | Exact keys and value types |
| --- | --- |
| top level | `schema`: integer exactly `1`; `candidate_root`: normalized absolute string; `commit`: lowercase 40-character hexadecimal string; `candidate`, `manifest`: objects |
| `candidate` | `device`, `inode`, `uid`, `gid`: non-negative integers; `mode`: four-character octal string |
| `manifest` | `device`, `inode`, `uid`, `gid`: non-negative integers; `mode`: four-character octal string exactly `0444`; `nlink`: integer exactly `1`; `size`: non-negative integer; `mtime_ns`, `ctime_ns`: signed integers; `sha256`: lowercase 64-character hexadecimal string |

`candidate_root` is at most 4096 UTF-8 bytes and contains no control or
surrogate code point. The authority record is limited to 16 KiB. The
manifest read is limited to 8 MiB before JSON decoding. Both use the canonical
serializer and strict parser rules above.

The final record is a regular, single-link `0400` file. Creation is
no-clobber and atomic at the canonical pathname: write and `fsync` an owned
adjacent pending file, publish it with an exclusive same-filesystem primitive,
then `fsync` the parent. Successful exclusive publication is the commit point.
A failure before it can leave only an owned pending file. A parent-directory
`fsync` failure or final verification failure after it can leave the canonical
record visible, but the builder returns failure, emits no success message,
stops the workflow, and preserves the record and candidate as diagnostic-only
evidence. A failed invocation's record is never adopted as workflow authority,
even if a later standalone verification succeeds. Existing, competitor,
pending, and published paths are never removed, repaired, or replaced; a new
attempt uses a fresh missing record path and a fresh candidate.

The builder prints `verified release build completed` only after the record
and candidate have passed the same low-level verifier that later stages call.
This fixed output is process-local status, not transferable release authority.
The record contains no denylist bytes, subprocess environment, repository
path, or candidate file contents. Failures emit one fixed public error and
never echo an untrusted path or record payload.

Old path-only `.txt` candidate records remain untouched as audit evidence and
are never accepted by the new verifier. Threadroot has no released consumer of
this local protocol, so there is no adapter, compatibility reader, or
migration path.

## Successful Attempt Receipt

A valid raw authority record proves candidate integrity but cannot prove that
the builder returned zero: publication can succeed before a later parent
`fsync` or final verification fails. Every canonical invocation therefore has
a second HEAD-and-attempt-qualified missing path for a success receipt outside
the repository and candidate. It has the same absolute-path, existing-real-
parent, missing-leaf, no-symlink, and no-control-character preconditions as
the authority record.

Only the success arm of the outer runbook may create the receipt. It invokes
`record_successful_attempt` after the `build_verified_release` process has
exited zero; the failure arm stops without invoking it. Before writing, the
receipt command freshly verifies the candidate and reads the authority record
through a held no-follow descriptor with before/after identity checks. The
receipt is canonical schema-1 JSON with this exact shape:

```json
{
  "authority_record_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "authority_record_size": 1,
  "commit": "0000000000000000000000000000000000000000",
  "schema": 1
}
```

The top-level keys are exact. `schema` is integer exactly `1`; `commit` is a
lowercase 40-character hexadecimal string;
`authority_record_sha256` is a lowercase 64-character hexadecimal string; and
`authority_record_size` is an integer in `1..16 KiB`. The receipt uses the
shared canonical serializer, is limited to 4 KiB, and is a regular,
single-link `0400` file.

Receipt creation uses the same pending-file, exclusive-publication, and
parent-`fsync` primitive as the authority record. Receipt publication is its
commit point. If a later receipt `fsync` or verification step fails, the
current workflow still stops and preserves all evidence; a later explicit
resume may use the published receipt only after full successful-attempt
verification. This is safe because receipt creation is reachable only after
the build process returned zero.

Across a shell boundary, downstream code accepts only a success receipt paired
with authority-record bytes of the recorded size and SHA-256, then performs
the complete candidate verification. Held no-follow descriptors and
before/after identity checks cover both metadata files throughout that
operation; the verifier does not hash one record open and silently trust a
later reopen. A raw authority record is never enough. Consequently, a failed
build that leaves a valid published record but no receipt cannot be reviewed,
bound into release state, merged, installed, uploaded, tagged, drafted, or
published. This is a narrow release-attempt receipt, not a general transaction
or migration framework.

## Read-only Candidate Verifier

A focused standard-library module, `scripts/release_candidate.py`, owns the
manifest and authority-record formats. Its programmatic interface is:

```python
bind_candidate(
    candidate_root: Path,
    commit: str,
    authority_record: Path,
) -> None

verify_candidate(
    authority_record: Path,
    expected_commit: str,
) -> Path

record_successful_attempt(
    authority_record: Path,
    expected_commit: str,
    success_receipt: Path,
) -> None

verify_successful_attempt(
    success_receipt: Path,
    authority_record: Path,
    expected_commit: str,
) -> Path
```

Its CLI verification form is:

```text
python3 -B -m scripts.release_candidate verify \
  --authority-record ABSOLUTE_RECORD \
  --expected-commit COMMIT
```

On success the CLI is silent and exits zero; its programmatic API returns the
validated path. On failure the CLI emits only
`candidate integrity verification failed` to stderr and exits nonzero.

The module also exposes:

```text
python3 -B -m scripts.release_candidate record-success \
  --authority-record ABSOLUTE_RECORD \
  --expected-commit COMMIT \
  --success-receipt ABSOLUTE_MISSING_RECEIPT

python3 -B -m scripts.release_candidate verify-success \
  --authority-record ABSOLUTE_RECORD \
  --expected-commit COMMIT \
  --success-receipt ABSOLUTE_RECEIPT
```

Release runbooks and CI use `verify-success`; the lower-level `verify` form
exists for builder self-verification and diagnosis only. All three forms are
silent on success and share the fixed sanitized failure contract. Only after
`verify-success` succeeds may a runbook parse the candidate root from the
now-trusted canonical record into a quoted shell variable.

Verification is fail closed and performs all of these checks as one boundary:

1. open and parse the external record with exact schema, canonical bytes,
   regular-file, link-count, mode, and path checks;
2. require its commit to equal the caller's reviewed commit and its candidate
   path to resolve to the recorded root identity;
3. open the manifest without following links and require every recorded
   identity and hash from the external record;
4. capture the complete live candidate tree, excluding only the manifest,
   and require exact equality with every manifest entry;
5. freshly read the expected commit from the current repository and require
   source A and source B to have the exact relative membership, kinds,
   canonical modes, sizes, and payload hashes of its safely parsed Git
   archive;
6. require candidate A, candidate B, and selected to contain exactly the four
   release artifacts as regular, single-link `0644` files with identical
   sizes and hashes;
7. require canonical `build.json` and `SHA256SUMS` bytes, the expected commit,
   and artifact name/size/hash data to agree with the three artifact sets;
8. repeat the live candidate snapshot and root/manifest identity checks before
   returning success.

The verifier executes only tracked worktree code. It never imports or executes
Python from a candidate source tree, never writes within the candidate, and
never uses the network or Docker. The outer runner's existing commit-byte
check expands to include `scripts/release_candidate.py`, so the verifier used
to bind a build is itself part of the selected commit.

## Authority Flow Through Tasks 7-12

Task 7's canonical build supplies a HEAD-and-attempt-qualified missing `.json`
authority-record path directly to `build_verified_release`. Only when that
process returns zero does the same runbook success arm create its separately
qualified success receipt; it emits the final workflow completion status only
after `verify-success` passes. The old shell-side path-only record write is
removed. Both independent reviewers must run `verify-success` on the paired
receipt and record at entry and exit, use worktree-owned scripts, and invoke
Python with `-B` or `PYTHONDONTWRITEBYTECODE=1`. Approval is invalid if either
boundary check fails, even when artifact hashes remain unchanged.

Immediately before final Task 7 binding, a fresh successful-attempt verifier
call must succeed for the unchanged reviewed HEAD. Only then may the runbook
create the state root and exclusively copy the exact authority-record and
receipt bytes into `candidate-authority.json` and `candidate-success.json`,
alongside the derived `candidate-root.txt` and `reviewed-head.txt`. The copied
metadata files are `0400`, byte-identical to their external originals, and
must pass paired `verify-success` before the binding block returns. All four
values must agree. No state path is created when the first verification fails.

Task 8 re-verifies the paired `candidate-success.json` and
`candidate-authority.json` before every external mutation. Its
`pr-checks.json` and `pr.diff` outputs live under the release state root, and
every reader is changed to that location; no PR evidence is written into the
candidate. Immediately before Task 9 invokes the merge mutator, it reads
`reviewed-head.txt` and freshly verifies that same pair against the commit. A
failed check prevents the merge regardless of PR-head status. After the merge,
Task 9 supplies a new state-local, no-clobber `final-authority.json` to the
canonical build for the merged commit; only the successful build arm creates
`final-success.json`. Tasks 10-12 derive the final root only from paired
successful-attempt verification and repeat it before each install, upload,
tag, draft, or publish boundary. Existing fresh-download and selected-artifact
hash checks remain defense in depth; they are not replaced by the manifest.

No post-build validation may write beneath a recorded candidate root. Task 10
therefore creates one separate `0700` disposable validation root under the
existing local temporary-root convention, records its absolute path once in
the release state directory, and places the wheel virtual environment, CLI
fixture, and both host smoke roots beneath it. Every later Task 10 shell loads
that bound path instead of reconstructing a path below the final candidate.
The disposable root is not release authority and is never published; it
remains visible with the other local evidence until the release workflow is
finished.

A changed commit, manifest, source member, diagnostic evidence member,
artifact, membership set, co-edited `SHA256SUMS`, or any recorded mode, link
count, inode, owner, or timestamp field therefore fails before the next
authority transition.

## ZIP Directory Payload Invariant

Shared ZIP framing becomes the single semantic authority for directory
payloads. After local/central record agreement and before returning a
validated member, it requires:

```text
ZipInfo.is_dir() implies file_size == 0
```

An empty DEFLATE stream may have nonzero compressed framing bytes; the
uncompressed payload must still be empty. A directory with nonzero
uncompressed size fails as `invalid_archive` before the public scanner,
generic loader, extractor, or artifact validator can interpret it
differently.

The public scanner keeps treating a framing failure as an unreadable unsafe
input: API callers receive a scan error, and the CLI exits `2` with only its
fixed sanitized error. Neither a denied payload nor an unsafe archive name is
rendered.

## Tests

Candidate-integrity tests use real temporary trees and hand-derived expected
records. They must first fail against the old implementation and prove:

- a clean, complete candidate binds and verifies;
- an added `__pycache__`, modified source byte, identical source replacement,
  mode change, hard link, extra member, modified evidence file, modified
  selected artifact, and selected-plus-`SHA256SUMS` co-edit all fail;
- source A/B asymmetry and an incorrect commit fail;
- matching source A/B trees that differ from the expected Git archive fail;
- a missing, malformed, symlinked, noncanonical, non-`0400`, or pre-existing
  authority record fails without Docker or authority creation;
- manifest, record, and receipt writes are exclusive and never emit ambiguous
  success;
- a parent-directory `fsync` failure and a post-publication verifier failure
  leave any published record untouched, return failure, and cannot advance the
  workflow;
- a builder failure never invokes receipt creation, and a separate shell
  cannot bind Task 7 state or begin Task 10 installation from the leftover raw
  record even when low-level verification succeeds;
- a valid receipt binds the exact record size, digest, and commit; malformed,
  noncanonical, pre-existing, content-changed, non-`0400`, or replacement-race
  receipts fail closed, while a byte-identical safe copy remains valid;
- the Task 7 binding fixture contains both exact source exports and rejects
  post-review drift before creating the state root;
- the complete Task 8 Step 3 flow stores PR checks and diff evidence under the
  state root and leaves the candidate valid;
- Task 9 rejects drift introduced after Task 8 before invoking its mocked
  merge mutator;
- Tasks 8 and 10-12 reject authority drift before their mocked mutator;
- Task 10 creates all virtual environments and smoke fixtures outside the
  final candidate and leaves the complete candidate manifest valid; and
- CI and documented canonical commands supply and verify authority records.

ZIP tests construct stored and DEFLATE directory entries with nonzero
uncompressed payload. Shared framing, scanner API, and the CLI must reject
them. The CLI test includes a synthetic denied term and asserts exit `2` with
no occurrence of that term or raw control characters in stdout or stderr. A
normal empty stored directory and an empty DEFLATE directory remain accepted
controls.

The complete Python 3.11-3.14 suite, compileall, repository public scan,
artifact validators, real Git-archive comparison, and runbook shell-contract
tests remain required. Any implementation commit invalidates earlier
canonical candidates and requires a new explicit Docker authorization, new
candidate, and two fresh whole-branch reviews before final binding.

## Non-goals

- No signing service, transparency log, remote attestation, or defense against
  a malicious maintainer, kernel, Docker daemon, or host administrator.
- No general artifact store or migration framework.
- No change to runtime product behavior, artifact selection, or archive
  format; the corrected source is rebuilt rather than patched in place.
- No deletion, repair, reuse, or normalization of contaminated candidates.
