# Threadroot Contributor Instructions

## Mission

Threadroot is a local-first second-brain developer tool for people who use coding agents. It provides portable Agent Skills and a small deterministic CLI while leaving every user's Markdown, Git history, and private context under that user's control.

The v0 product is an installable tool, not a hosted memory service, context protocol, RAG framework, or operating system.

## Architecture Boundaries

- Keep provider-neutral workflow instructions in one shared `skills/` source of truth.
- Keep `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` as thin native packaging manifests. Do not duplicate workflow behavior in host adapters.
- Keep the Python 3.11+ core deterministic and standard-library-only unless a dependency is explicitly justified.
- Use the core for root and config resolution, validation, non-overwriting scaffolding, path safety, and structured results. Semantic Markdown edits belong to the host agent's native edit mechanism.
- Treat the user's vault as an external, user-owned system of record. Never copy personal vault content into this repository.

## v0 Contract

- `init` supports only new or empty targets, previews by default, writes only with explicit apply intent, and never overwrites existing files.
- `adopt` validates recognized layouts, remains read-only by default, and may add only `.second-brain/config.json` when explicitly applied. It must not move or rewrite existing content.
- `doctor` is always read-only and fails closed for unsupported schema versions or unsafe paths.
- `claim` previews by default and, only with explicit apply intent, exclusively reserves one empty regular file within exactly one configured content root. It receives no note bytes and creates no parents. New-file skills require claim, native same-identity/empty verification, then native semantic edit; failed gates stop with visible partial state.
- Defer `migrate`, transaction journals, rollback hashes, MCP, RAG, GUI, telemetry, and background synchronization until a demonstrated use case requires them.

## Safety and Privacy

- Default to no network access and no telemetry.
- Use only synthetic fixtures in tests, examples, logs, and release artifacts.
- Reject absolute paths, path traversal, and configured paths that escape the resolved vault root.
- Reject lexical/resolved exact secrets components and content access through the marker namespace. Default-pointer destinations must remain outside the selected vault, including after parent-symlink resolution, before setup writes begin.
- Re-read a target before writing and stop on concurrent drift rather than guessing a merge.
- Leave partial failures visible and inspectable; do not hide them with automatic cleanup or rollback machinery.
- Never commit secrets, private paths, identities, company material, or real vault excerpts.
- Uninstalling Threadroot must never delete or rewrite the user's Markdown or Git repository.

## Development Conventions

- Write public documentation and shared skill instructions in clear English.
- In shared skills, say `the agent`, `the model`, or `the host` as appropriate; use provider names only for genuinely host-specific packaging or instructions.
- Add or update tests before changing observable behavior. Prefer standard-library `unittest` while the core remains dependency-free.
- Keep modules focused and interfaces explicit. Avoid speculative abstractions for future providers or schema versions.
- Test behavior across Claude Code and Codex using the same synthetic scenarios. Require structural equivalence, not identical prose.
- Run unit, manifest-parity, provider-neutral wording, privacy, and packaging checks before declaring a change complete.

## Git Hygiene

- Preserve unrelated worktree changes and stage exact paths only.
- Do not commit generated user vaults, dogfood output, local configuration, or host-private context.
- Do not commit, push, publish, or create a release unless the current task explicitly authorizes it.
