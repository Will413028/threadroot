# Security

## Threat model

Threadroot treats the vault as user-owned, potentially sensitive data and its configuration as untrusted input. v0 aims to prevent accidental overwrite, path escape, unintended publication, and ordinary concurrent drift during deterministic CLI operations.

Threadroot does not defend against a malicious or privileged local process that can replace filesystem entries between validation and use. Operating-system access controls and host isolation remain part of the user's security boundary.

## Trust boundaries

The CLI, installed host package, host application, and external vault are separate components. Threadroot validates only its own deterministic operations. The user controls which vault a command targets and which files a host may access.

Host workspace approval, such as `--add-dir`, grants the host—not Threadroot—filesystem capability. Scope that approval to the vault only; do not disable a sandbox or expose unrelated directories.

## Path containment

Configuration paths must be relative and must remain within the resolved vault after normalization and symlink resolution. Absolute paths, parent traversal, unsupported schema versions, and escaping configured paths fail closed. Commands do not discover through unrelated directories or directories named `secrets`.

## Non-overwriting writes

`init` and `adopt` preview changes by default and write only with explicit `--apply` intent. Planned files use exclusive creation and are rechecked immediately before use. Existing content is never overwritten, and `doctor` is always read-only.

## Partial failures

If a later operation fails after earlier writes succeeded, Threadroot stops and reports completed and pending work. It does not hide the visible state with automatic cleanup or rollback; inspect the filesystem and Git diff before retrying.

## Secrets

Do not put credentials, private note excerpts, personal paths, or real identities in issues, fixtures, examples, logs, or release artifacts. Use synthetic reproductions. Threadroot errors report validation context without intentionally echoing note contents or secret values.

## Host data policy

The Threadroot runtime performs no telemetry, background networking, uploads, or model calls. A host model or service may still process files the user authorizes. That access follows the host's data-handling and retention policy, which Threadroot cannot override.

## Dependency policy

The Python runtime is standard-library-only. Build tooling and host applications are separate dependencies and should be obtained from their official distribution channels. New runtime dependencies require an explicit security and maintenance justification.

## Reporting

After a public remote enables GitHub private vulnerability reporting, use that private feature for security reports. Until then, do not include secrets, private vault samples, sensitive paths, or exploit payloads in a public issue; contact the maintainer through an established private channel or provide only a synthetic description.
