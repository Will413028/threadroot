# Threadroot

Root your work across sessions.

Threadroot is a local-first second-brain developer tool for people who work with coding agents. It combines nine portable Agent Skills with a small deterministic CLI for setting up, adopting, and checking a Markdown vault.

Your Markdown, Git history, and private context stay in a vault you own. Threadroot supplies workflows and safety checks; it is not a hosted memory service and does not copy your vault into its installation.

## Ownership boundaries

| What Threadroot owns | What you own |
| --- | --- |
| CLI validation, previews, non-overwriting setup, and structured results | The Markdown vault, its contents, location, permissions, and Git history |
| One provider-neutral `skills/` tree and thin host manifests | Host account, model, workspace approvals, and data-policy choices |
| Public source and release artifacts | Backups, review of proposed edits, and publication decisions |

## Requirements

- Python 3.11 or newer.
- macOS or Linux.
- Claude Code or Codex for the Agent Skills.
- Git is recommended for inspecting changes, but the CLI does not require it.

## Install the CLI from a checkout

From the repository root, use a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
threadroot --version
```

This installs the deterministic CLI. Install or load the host package separately to make the skills available to an agent.

## Install from release artifacts

Release artifacts have two layers: the wheel provides the CLI, while the host archive provides the nine skills. Install both layers for the complete workflow.

```bash
python -m pip install ./threadroot-0.1.0-py3-none-any.whl
claude --plugin-dir ./threadroot-claude-0.1.0.zip

python -m zipfile -e ./threadroot-codex-0.1.0.zip ./threadroot-codex-0.1.0
codex plugin marketplace add ./threadroot-codex-0.1.0
codex plugin add threadroot@threadroot
```

Direct Claude Code ZIP loading requires Claude Code v2.1.128 or later. On older versions, extract the archive and pass its directory instead.

## Load the plugin for one Claude Code session

From a checkout or extracted Claude archive:

```bash
claude --plugin-dir "$PWD"
```

This loads the plugin for that invocation without installing it into a marketplace.

## Install through a local marketplace

From a checkout or extracted host archive:

```bash
claude plugin marketplace add . --scope user
claude plugin install threadroot@threadroot

codex plugin marketplace add .
codex plugin add threadroot@threadroot
```

## Install from a Git repository after a remote exists

`OWNER/threadroot` is a placeholder, not a live repository claim. Replace `OWNER` with the actual repository owner only after a remote exists.

```bash
git clone https://github.com/OWNER/threadroot.git
cd threadroot
python -m pip install .
claude plugin marketplace add OWNER/threadroot --scope user
codex plugin marketplace add OWNER/threadroot
```

Install `threadroot@threadroot` with the relevant host after adding the repository marketplace.

## Allow access to an external vault

CLI filesystem access and host workspace permission are separate. Pass the vault to the CLI explicitly, and grant the host access only to that vault when the host requires approval:

```bash
export SECOND_BRAIN_ROOT=/path/to/your/markdown-vault
claude --add-dir "$SECOND_BRAIN_ROOT"
codex --add-dir "$SECOND_BRAIN_ROOT"
```

Do not disable the host sandbox or copy a private vault into a code repository to make it visible.

## Create or adopt a vault

`init` is for a missing or empty target. It previews by default; inspect the plan before applying it:

```bash
threadroot init --vault "$SECOND_BRAIN_ROOT"
threadroot init --vault "$SECOND_BRAIN_ROOT" --apply
```

`adopt` is for an existing recognized Markdown layout. It also previews first and, when applied, adds only the marker:

```bash
threadroot adopt --vault "$SECOND_BRAIN_ROOT"
threadroot adopt --vault "$SECOND_BRAIN_ROOT" --apply
```

Check either vault without writing:

```bash
threadroot doctor --vault "$SECOND_BRAIN_ROOT"
```

## Skills

- `daily-wrap-up`
- `decision-log`
- `morning-review`
- `project-kickoff`
- `query`
- `recording`
- `second-brain-doctor`
- `second-brain-setup`
- `weekly-review`

## Uninstall

Remove the CLI and either host installation independently:

```bash
python -m pip uninstall threadroot
claude plugin remove threadroot@threadroot
codex plugin remove threadroot@threadroot
```

Removing a marketplace entry is optional and separate. None of these uninstall commands accepts a vault path, deletes user Markdown, or rewrites Git history.

## Safety

No telemetry. The Threadroot runtime makes no network requests, background uploads, or model calls. It previews setup changes, rejects unsafe configured paths, does not overwrite existing files, and leaves partial failures visible for inspection.

The host model or service may read files you approve and is governed by that host's own data-handling policy. Threadroot's no-network runtime does not change that policy. See [Security](SECURITY.md) for the threat model and reporting guidance.

## Development

Run the suite, build all artifacts, and scan public inputs before submitting a change:

```bash
PYTHONPATH=src:. python -m unittest discover -s tests -v
python -m build
python scripts/build_release.py --output dist
python scripts/check_public.py .
python scripts/check_public.py dist
```

See [Testing](docs/testing.md) for native host validation and isolated installation checks.

## Contributing and security

Read [Contributing](CONTRIBUTING.md) before opening a change. Report vulnerabilities as described in [Security](SECURITY.md), without posting private vault content.

## License

Threadroot is distributed under the [Apache License 2.0](LICENSE). The license covers Threadroot contributions; it does not license user vault content or project trademarks.
