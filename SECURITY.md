# Security

## Threat model

Threadroot treats the vault as user-owned, potentially sensitive data and its configuration as untrusted input. v0 aims to prevent accidental vault-content overwrite, path escape, unintended publication, and ordinary concurrent drift during deterministic CLI operations.

Threadroot does not defend against a malicious or privileged local process that can replace filesystem entries between validation and use. Operating-system access controls and host isolation remain part of the user's security boundary.

## Trust boundaries

The CLI, installed host package, host application, and external vault are separate components. Threadroot validates only its own deterministic operations. The user controls which vault a command targets and which files a host may access.

Host workspace approval, such as `--add-dir`, grants the host—not Threadroot—filesystem capability. Scope that approval to the vault only; do not disable a sandbox or expose unrelated directories.

## Path containment

Configuration paths must be relative and must remain within the resolved vault after normalization and symlink resolution. Absolute paths, parent traversal, unsupported schema versions, and escaping configured paths fail closed. Commands do not discover through unrelated directories or directories named `secrets`.

Exact `secrets` components are rejected in lexical and resolved paths before marker/content access; the `.second-brain` marker namespace cannot be a content root or claim target. Invalid literals, including NUL and symlink loops, return unsafe-path exit `4` without raw exception diagnostics. Ordinary filesystem errors return `6`; unsupported schema/config errors remain `3`. Init does not flatten unsafe marker/config errors into a generic nonempty-target conflict.

## Non-overwriting writes

`init` and `adopt` preview changes by default and write vault data only with explicit `--apply` intent. Planned vault files use exclusive creation and are rechecked immediately before use. Existing vault content is never overwritten, and `doctor` is always read-only.

`claim` previews by default and accepts only a path, never note bytes. With explicit `--apply`, it uses OS-exclusive creation to reserve one zero-byte regular file strictly inside exactly one configured content root. It creates no parents. Existing targets are planning conflicts (`5`); exclusive-open collisions after planning are drift (`6`). Skills require successful exact claim results, then two native no-follow metadata observations of the same empty regular file identity before a host-native semantic edit. A generic Write is not proof of exclusive creation. This cooperative-session protocol does not defend against malicious replacement between the CLI and first metadata observation or between validation and use.

With `--apply --set-default`, `init` and `adopt` atomically replace the machine-local default-vault pointer only after the vault operation succeeds. That pointer stores the selected vault location; replacing it does not modify vault content.

The resolved pointer destination must be outside the selected vault. Direct overlap or overlap through a parent symlink is rejected with `4` before any setup/pointer write; apply and the pointer writer revalidate before mutations. Later failures retain the old pointer and expose any completed vault actions.

## Partial failures

If a later operation fails after earlier writes succeeded, Threadroot stops and reports completed and pending work. It does not hide the visible state with automatic cleanup or rollback; inspect the filesystem and Git diff before retrying.

The only narrow cleanup is removal of the pointer writer's own uncommitted temporary file; it never removes a reservation, note, or completed vault action. Failed reservation verification or native editing leaves an empty reservation or partial edit to report, not a claim of zero writes. Never retry a competing file as an existing-file edit. An outside-vault local adapter is omitted unless its parent exists and independent native exclusive creation, Git ignore status, and native auto-loading are all established.

## Secrets

Do not put credentials, private note excerpts, personal paths, or real identities in issues, fixtures, examples, logs, or release artifacts. Use synthetic reproductions. Threadroot errors report validation context without intentionally echoing note contents or secret values.

## Host data policy

The Threadroot runtime performs no telemetry, background networking, uploads, or model calls. A host model or service may still process files the user authorizes. That access follows the host's data-handling and retention policy, which Threadroot cannot override.

## Dependency policy

The Python runtime is standard-library-only. Build tooling and host applications are separate dependencies and should be obtained from their official distribution channels. New runtime dependencies require an explicit security and maintenance justification.

## Reporting

After a public remote enables GitHub private vulnerability reporting, use that private feature for security reports. Until then, do not include secrets, private vault samples, sensitive paths, or exploit payloads in a public issue; contact the maintainer through an established private channel or provide only a synthetic description.
