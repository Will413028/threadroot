# Threadroot v0 Design

**Status:** Review requested  
**Date:** 2026-09-02  
**Product:** Threadroot  
**Tagline:** Root your work across sessions.

## Summary

Threadroot is an installable, local-first developer tool for people who work with coding agents across sessions and hosts. It combines portable Agent Skills with a small deterministic Python CLI. The user's Markdown vault and Git history remain the system of record; Threadroot supplies workflows and safety checks without becoming a hosted memory service.

The v0 release supports Claude Code and Codex through two thin native plugin manifests that expose one shared set of provider-neutral skills. It supports creating a new vault, adopting a recognized existing vault, diagnosing configuration, and running a focused set of knowledge workflows.

## Problem

Coding-agent context is usually scoped to one session or one provider. Developers compensate with project instructions, chat summaries, Markdown notes, and host-specific skills, but those sources drift and do not reliably feed later work. A durable solution must remain usable when the model or host changes, must work with an existing Markdown repository, and must not copy private data into the tool's own repository.

## Goals

- Provide a developer-installable tool with a `threadroot` command and native Claude Code and Codex packages.
- Keep workflow behavior in a single provider-neutral `skills/` source of truth.
- Store all user knowledge in a user-owned Markdown and Git vault.
- Support safe setup through `init`, minimal adoption through `adopt`, and read-only diagnosis through `doctor`.
- Make every deterministic write previewable, non-overwriting, path-contained, and inspectable with Git.
- Support a useful end-to-end daily and project workflow without a server, database, or background process.

## Non-goals

- A hosted memory service, synchronization service, context protocol, or operating system.
- An MCP server, RAG pipeline, vector database, GUI, telemetry service, or background daemon.
- Arbitrary Obsidian import, vault reorganization, or semantic Markdown rewriting in the Python core.
- Schema migration, transaction journals, expected-hash rollback, or automatic cleanup of partial writes.
- Marketplace submission, paid plans, or a numeric adoption target as a v0 implementation gate.
- Windows support in v0.

## Supported Environment

- Python 3.11 or newer.
- macOS and Linux.
- Runtime code uses only the Python standard library.
- Git is recommended for inspectability but is not required by `init`, `adopt`, or `doctor`.
- Markdown editors, including Obsidian, may be used but are not required.

## Architecture

```text
Claude Code package ─┐
                     ├── shared provider-neutral skills ──┐
Codex package ───────┘                                     │
                                                           ▼
                                             deterministic Python CLI
                                                           │
                                                           ▼
                                             user-owned Markdown vault
```

### Host packages

`.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` are both checked into the repository. They contain only host packaging metadata and point to the same `skills/` directory. Submission-time conversion may be used by a marketplace, but it is not the source of truth for local or repository installation.

The manifests use `threadroot` as the plugin identifier and keep equivalent name, version, description, and license metadata. Host-specific instructions are permitted only when a host contract genuinely differs.

### Portable skills

Each public workflow lives in `skills/<skill-name>/SKILL.md`. Instructions use `the agent`, `the model`, and `the host`; provider names appear only in host-specific packaging or setup text. Skills perform semantic Markdown work with the host's native read and edit tools. They do not duplicate the CLI's deterministic validation logic.

### Deterministic core

The `threadroot` Python package owns command parsing, root resolution, configuration validation, path containment, non-overwriting scaffolding, structured results, and exit codes. It does not parse arbitrary Markdown into an AST or decide how prose should be rewritten.

### User-owned vault

The vault contains the user's notes, project history, configuration, private skills, and policies. It is external to the Threadroot installation and is never copied into the Threadroot repository, release artifacts, fixtures, or logs. Uninstalling Threadroot leaves the vault unchanged.

## Repository Layout

```text
threadroot/
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
├── AGENTS.md
├── LICENSE
├── README.md
├── pyproject.toml
├── docs/superpowers/specs/
├── docs/superpowers/plans/
├── skills/
│   └── <skill-name>/SKILL.md
├── src/threadroot/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── paths.py
│   ├── operations.py
│   └── results.py
├── templates/vault/config.json
└── tests/
    ├── fixtures/
    ├── test_cli.py
    ├── test_config.py
    ├── test_operations.py
    ├── test_paths.py
    └── test_packaging.py
```

Each Python module has one responsibility: `cli.py` maps arguments to operations, `config.py` parses and validates schemas, `paths.py` resolves roots and enforces containment, `operations.py` plans and applies setup actions, and `results.py` defines stable output records.

## Vault Contract

### Marker

The marker is always `.second-brain/config.json` relative to the vault root. The product name does not appear in the marker path so the user's data format is not coupled to one tool brand.

Schema version 1 is exactly:

```json
{
  "schema_version": 1,
  "paths": {
    "daily": "daily",
    "projects": "wiki/projects",
    "knowledge": "wiki/tech",
    "reviews": "wiki/reviews"
  }
}
```

All four path keys are required. Values must be non-empty relative paths. After normalization and symlink resolution, every configured path must remain inside the resolved vault root. Absolute paths, `..` escapes, unsupported keys, missing keys, non-integer versions, and schema versions other than `1` are errors.

### Canonical content paths

- Daily notes: `<daily>/YYYY-MM-DD.md`
- Project page: `<projects>/<project-slug>/index.md`
- Project decisions: `<projects>/<project-slug>/decisions/YYYY-MM-DD-<decision-slug>.md`
- Durable technical knowledge: `<knowledge>/<topic-slug>.md`
- Weekly review: `<reviews>/weekly-YYYY-Www.md`

Path values may relocate the four top-level content areas, but their internal conventions remain fixed in v0.

### Root resolution

Commands resolve the vault in this order:

1. An explicit `--vault PATH` argument.
2. The `SECOND_BRAIN_ROOT` environment variable.
3. An upward search from the current directory for `.second-brain/config.json`.
4. A machine-local default pointer.

If none of the four sources resolves a vault, the command exits with code `3` and instructs the user to pass `--vault`; it never silently treats the current directory as a vault.

The machine-local pointer is `$XDG_CONFIG_HOME/threadroot/config.json`, falling back to `~/.config/threadroot/config.json`. It contains only an absolute `default_vault` path and never contains vault content. `init` and `adopt` may update it only when both `--apply` and `--set-default` are present and the vault operation succeeds.

## CLI Contract

### Common behavior

The command surface is:

```text
threadroot init [--vault PATH] [--apply] [--set-default] [--json]
threadroot adopt [--vault PATH] [--apply] [--set-default] [--json]
threadroot doctor [--vault PATH] [--json]
```

`init` and `adopt` preview by default. Preview computes and reports an ordered change plan without writing files, creating directories, or changing the default pointer. `--apply` executes that same plan after revalidating every precondition. `doctor` never accepts `--apply` and never writes.

Human-readable output is the default. `--json` emits one JSON object and no decorative text. Results contain no timestamps, random identifiers, note contents, or environment dumps, which keeps output deterministic and safe to snapshot-test.

### `threadroot init`

`init` targets a missing directory or a directory with no entries other than `.git`. Its plan creates the vault root when necessary, the four configured content directories, and `.second-brain/config.json`. It does not create sample notes, rewrite an existing `AGENTS.md`, or initialize Git.

If any planned file already exists, the command stops before writing. A directory that contains user files is rejected with guidance to use `adopt`. Re-running `init` against a valid initialized vault reports that it is already initialized and makes no changes.

### `threadroot adopt`

`adopt` targets an existing markerless Markdown repository. The recognized v0 layout requires all four default directories: `daily`, `wiki/projects`, `wiki/tech`, and `wiki/reviews`. Additional files and directories are allowed.

The preview reports one possible vault marker. With `--apply`, the command creates only `.second-brain/config.json`; it never creates missing content directories, moves files, renames files, rewrites notes, or changes Git history. If the layout is incomplete, adoption fails with a list of missing directories. If a marker already exists, `adopt` validates it and otherwise makes no changes.

### `threadroot doctor`

`doctor` validates root resolution, marker readability, exact schema version, required path keys, path containment, directory existence, path types, and apparent read/write access. A missing optional Git repository is informational. Unsupported schema versions and paths that resolve outside the vault are errors.

The command observes filesystem metadata but does not create probes, touch files, update access markers, or repair problems. Its output separates errors, warnings, and informational findings and gives a concrete remediation message for every error.

## Change and Failure Semantics

Setup commands build an in-memory ordered plan before applying it. Immediately before each create operation, they confirm that the target still does not exist and that its resolved parent remains within the vault. Files are opened with exclusive-create semantics. Directories are created only when listed in the plan.

If an operation fails after earlier operations succeeded, Threadroot stops and reports both completed and unexecuted operations. It does not roll back or delete successful work. The visible filesystem state and Git diff are the recovery record.

Semantic workflow skills re-read their target immediately before editing. When content has drifted since the initial read, the skill stops and asks the user to retry rather than guessing a merge. Structural moves, bulk rewrites, deletion, and new taxonomy require a preview and explicit user confirmation.

## Result and Exit-Code Contract

JSON output follows this shape:

```json
{
  "ok": true,
  "command": "init",
  "applied": false,
  "vault": "/absolute/resolved/path",
  "changes": [
    {"action": "create_directory", "path": "daily"}
  ],
  "issues": []
}
```

Paths under `changes` and `issues` are vault-relative unless the field explicitly identifies the resolved vault root. The stable exit codes are:

- `0`: command completed, including a successful preview or idempotent no-op.
- `2`: invalid command-line usage.
- `3`: vault root or configuration is missing, unreadable, or invalid.
- `4`: unsafe path or path escape.
- `5`: target conflict, non-empty `init` target, or unrecognized adoption layout.
- `6`: filesystem operation failed or the target changed after planning.

## v0 Skills

- `second-brain-setup`: choose `init` or `adopt`, show the preview, obtain explicit apply intent, and run `doctor` afterward.
- `second-brain-doctor`: run and explain `doctor` without making repairs automatically.
- `query`: answer from the smallest relevant set of vault files and cite the source paths; it is read-only.
- `recording`: add completed or in-progress work to the current daily note and the matching project page while preserving existing narrative.
- `morning-review`: read current goals, open project work, and recent context to propose a focused day plan.
- `daily-wrap-up`: reconcile the day's work, unresolved items, and durable lessons into the appropriate vault layers.
- `weekly-review`: synthesize the week's daily notes and project state into one weekly review without inventing missing activity.
- `project-kickoff`: create a project page and minimal local project context after confirming identity, scope, and public/private boundaries.
- `decision-log`: record a durable A-over-B decision with real alternatives, rationale, trade-offs, follow-up work, and project-page backlinks.

Skills may use the host's semantic capabilities, but they must preserve these global rules: least-context reads, no secret payload output, no unrequested commit or push, no private-to-public copying, and no destructive structural changes without confirmation.

## Packaging and Distribution

The Python package uses `pyproject.toml` and exposes `threadroot = threadroot.cli:main`. Its wheel contains the CLI and only the runtime data required by the CLI; its source distribution contains the full public source tree. Release packaging also produces one Claude Code archive and one Codex archive. Each host archive contains its native manifest, the shared skills, public templates, `LICENSE`, and installation documentation. Package metadata uses `Apache-2.0`.

v0 documentation covers installation from a local checkout and a repository for Claude Code and Codex. Both native packages are release artifacts. A universal marketplace submission is deferred until real installation and workflow usage have been observed.

## Safety and Privacy Requirements

- Threadroot performs no telemetry, background networking, content upload, or model call of its own.
- Tests, examples, snapshots, logs, and release artifacts use synthetic identities and content only.
- Commands never traverse unrelated directories or directories named `secrets` as part of discovery or diagnosis.
- Errors describe paths and validation failures without echoing note contents or secret payloads.
- No command commits, pushes, publishes, or modifies Git configuration.
- Uninstall removes only the installed package or plugin files and never removes the vault.
- The host's data-handling policy still governs content the host model reads; Threadroot documentation states this boundary explicitly.

## Testing Strategy

Tests use standard-library `unittest`, `tempfile`, and subprocess execution.

- Unit tests cover config parsing, exact schema enforcement, root precedence, containment, symlink escapes, result serialization, and exit codes.
- Command tests prove preview purity, no-overwrite behavior, idempotent no-ops, adoption limits, read-only diagnosis, drift stops, and partial-failure reporting.
- Packaging tests parse both manifests, compare shared metadata, verify every referenced skill exists, build the wheel, source distribution, and two host archives, and inspect each artifact's contents.
- Provider-neutral wording checks reject `Claude` or `Codex` in shared skill bodies unless an allow-listed host-specific section requires the name.
- Privacy checks reject home-directory paths, real identities, company names, secret-like values, and non-synthetic vault excerpts in tracked fixtures and built artifacts.
- Cross-host contract scenarios assert equivalent files, headings, links, and safety outcomes rather than identical prose.
- CI runs the full suite on macOS and Linux for every supported Python minor version.

## v0 Acceptance Criteria

1. Installing the package provides a working `threadroot` command on Python 3.11 or newer.
2. `init` preview leaves a missing or empty target unchanged; `init --apply` creates exactly the configured directories and marker without overwriting files.
3. `adopt` preview leaves a recognized existing vault unchanged; `adopt --apply` adds only the marker.
4. Unsafe, absolute, escaping, incomplete, and unknown-version configurations fail closed with the documented exit code.
5. `doctor` produces the same findings without changing file contents or modification times.
6. Claude Code and Codex packages expose the same shared v0 skills from one source tree.
7. Synthetic cross-host scenarios produce structurally equivalent vault changes and identical safety decisions.
8. Built artifacts contain no private paths, identities, company material, secrets, telemetry, or network client dependency.
9. Removing the installed package or plugin leaves every test vault byte-for-byte unchanged.

## Deferred Work and Triggers

- Add `migrate` only after a real released schema must change; design its migration and rollback contract from that concrete transition.
- Add transaction journals or expected hashes only after observed concurrent or multi-file failure modes cannot be handled safely with revalidation and visible Git diffs.
- Add MCP or RAG only after user evidence shows file navigation and targeted reads are insufficient.
- Add more hosts only after the shared-skill contract is stable across Claude Code and Codex.
- Add marketplace-specific submission automation only after local and repository installation have demonstrated repeat usage.
