# Testing Threadroot

All examples run from the repository root and use synthetic data. Install the `build` package in the active development environment before building distributions.

## Unit suite

```bash
PYTHONPATH=src:. python -m unittest discover -s tests -v
```

Run the suite on every supported Python minor version available locally. CI defines the complete macOS/Linux and Python 3.11–3.14 matrix.

## Build and inspect artifacts

Build a wheel, source distribution, and both host archives from a clean tree:

```bash
python -m build
python scripts/build_release.py --output dist
python -m zipfile -l dist/threadroot-claude-0.1.0.zip
python -m zipfile -l dist/threadroot-codex-0.1.0.zip
```

The wheel contains the CLI. The source distribution contains the public source tree. Each host ZIP contains the shared skills, templates, public entry documents, marketplace catalog, and only that host's native manifest.

Use a disposable virtual environment for the wheel smoke test:

```bash
threadroot_wheel_test_root="$(mktemp -d)"
python3 -m venv "$threadroot_wheel_test_root/venv"
"$threadroot_wheel_test_root/venv/bin/python" -m pip install --no-deps --force-reinstall dist/threadroot-0.1.0-py3-none-any.whl
"$threadroot_wheel_test_root/venv/bin/threadroot" --version
```

Leave the temporary directory for operating-system cleanup; do not use a broad recursive delete command.

## Public-safety scans

Scan the checkout, the complete distribution directory, and each release artifact:

```bash
python scripts/check_public.py .
python scripts/check_public.py dist
python scripts/check_public.py dist/threadroot-0.1.0.tar.gz
python scripts/check_public.py dist/threadroot-claude-0.1.0.zip
python scripts/check_public.py dist/threadroot-codex-0.1.0.zip
```

For maintainer-specific identity or organization terms, create an untracked machine-local denylist with one literal term per line and pass it explicitly:

```bash
python scripts/check_public.py --denylist /path/to/untracked-denylist.txt . dist
```

Never print, commit, or copy the denylist into an artifact.

## Native host validation

Validate the Claude manifest and skills when Claude Code is installed:

```bash
claude plugin validate --strict .
```

Validate the Codex marketplace without changing the normal Codex configuration:

```bash
threadroot_codex_test_root="$(mktemp -d)"
CODEX_HOME="$threadroot_codex_test_root" codex plugin marketplace add "$PWD" --json
CODEX_HOME="$threadroot_codex_test_root" codex plugin add threadroot@threadroot --json
CODEX_HOME="$threadroot_codex_test_root" codex plugin list --json
```

Require all commands to exit zero and the final JSON to mark `threadroot@threadroot` installed. Leave the temporary root for operating-system cleanup.

## Synthetic cross-host contracts

The structural contract tooling uses only the executable ten-field cases under `tests/fixtures/contracts`. A case declares its synthetic directories and exact initial file bytes separately from its request, allowed semantic reads, expected writes, required headings and document links, forbidden actions, and forbidden paths. The checker hashes bytes, records file kinds and empty directories, and compares normalized Markdown structure without scoring or comparing generated prose.

Run its focused automated tests without launching a model:

```bash
PYTHONPATH=src:. python -m unittest tests.test_contracts -v
```

Materialization accepts only a missing or empty output directory. Validation prints only stable failure codes and fixture-relative paths:

```bash
mkdir -p .dogfood/daily-lifecycle
python scripts/check_contract.py materialize \
  --case tests/fixtures/contracts/daily-lifecycle.json \
  --output .dogfood/daily-lifecycle/pristine
python scripts/check_contract.py validate \
  --case tests/fixtures/contracts/daily-lifecycle.json \
  --before .dogfood/daily-lifecycle/pristine \
  --after .dogfood/daily-lifecycle/result
```

Do not run the second command until a result directory exists. A failed materialization must be investigated instead of reused.

After obtaining explicit authorization to launch each installed host and incur its normal model or network usage:

1. For each of `daily-lifecycle.json` and `project-decision.json`, materialize one pristine fixture below ignored `.dogfood/` storage.
2. Copy the pristine directory, preserving empty directories and symlinks, into separate Claude-result and Codex-result directories before either host runs.
3. For each Claude run, freshly extract the Claude archive, make that extracted bundle the primary working directory, and invoke `claude --plugin-dir "$PWD"` from there. Set `SECOND_BRAIN_ROOT` to the absolute fresh Claude-result path and pass that same vault, and no other path, as `--add-dir`.
4. Take complete pre-run and post-run snapshots of both the extracted bundle and the result vault, including file bytes, kinds, symlink targets, and empty directories. Restricted mode exposes the primary working directory and every `--add-dir` as read/edit roots, so treat the bundle as immutable and fail the run if it changes.
5. Do not pass the Claude ZIP directly while using the result vault as cwd: under restricted mode, Claude's runtime extraction does not thereby become a working directory, so mandatory plugin support resources can remain inaccessible.
6. For every Codex run, create fresh ignored `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, and `XDG_STATE_HOME` directories and set an explicit isolated `CODEX_HOME`. Do not rely on `CODEX_HOME` alone: Codex also discovers user skills below `$HOME/.agents/skills`, so inheriting the normal home can inject personal paths and catalog entries before any tool call.
7. Put only the synthetic date, permitted-read set, and safety boundary in `developer_instructions` within an ignored isolated `$CODEX_HOME/<profile>.config.toml`. Submit the fixture's exact `request` as the sole user message; never append harness text, expected writes, headings, links, approval, or real context to it.
8. Before launching Codex, verify that every home/XDG variable names a fresh user-only directory below ignored dogfood storage and that `CODEX_HOME` names only the isolated authenticated configuration with the local Threadroot plugin enabled. Disable remote plugins and apps in the profile while retaining local plugins. Do not use `--ignore-user-config`, because the isolated configuration enables the installed plugin.
9. Run Codex with the fresh result as its primary and only workspace, explicitly selecting the isolated profile by name: `codex exec --json --sandbox workspace-write -C RESULT --skip-git-repo-check --ignore-rules --profile PROFILE`, without `--add-dir` or a sandbox bypass. Set `approval_policy="never"`, `sandbox_workspace_write.network_access=false`, `sandbox_workspace_write.exclude_slash_tmp=true`, `sandbox_workspace_write.exclude_tmpdir_env_var=true`, `web_search="disabled"`, `agents.enabled=false`, `features.skill_mcp_dependency_install=false`, and the top-level `allow_login_shell=false`. A resumed turn must reuse the same isolated home/XDG/Codex roots and explicitly reassert every safety override supported by `codex exec resume`; do not assume first-turn settings carry over.
10. Snapshot the Codex result, installed plugin cache/package, developer profile, and isolated home/XDG roots before and after each turn. Audit JSONL and isolated persisted session metadata for exact user-message separation, non-login shells, mandatory installed-plugin resource reads, workspace and network policy, file changes, commands, web/MCP/subagent/escalation events, and any outside or normal-host path or catalog entry. Normal-context injection fails even when the structural contract passes; contained host-runtime metadata is separate from model mutation only when no model command targeted it.
11. Load the local host package, give each host the case's exact `request`, and permit semantic content reads only from `allowed_reads`. Validated `.second-brain/config.json` and filesystem metadata are setup reads.
12. Keep Claude inside the paired bundle and result roots, and keep every other host inside its result copy. Stop before any commit, push, deletion, bulk rewrite, or unapproved apply.
13. For Claude, require native file-tool access to every mandatory plugin support resource; a denied native read or shell fallback fails the run. Also require the post-run bundle snapshot to equal its pre-run snapshot.
14. When a skill requires approval, inspect its complete preview in the same host session before responding. Only then send a second-turn approval limited exactly to that evidence-supported complete preview; never preapprove, approve an incomplete preview, or add or infer facts in the approval.
15. When cross-host acceptance requires an exact new path, include that path in the fixture request so every host receives the same evidence. Never infer it from one host or adapt another host's expectation; a preview path mismatch blocks approval.
16. Validate pristine to Claude-result and pristine to Codex-result separately. Both commands must print `PASS` and exit zero. This proves the same path, heading, link, and safety contract even when prose differs.
17. Confirm the secrets sentinel and all unrelated bytes remain unchanged. Do not open or print the sentinel while reviewing results.

Generated vaults, prompts containing real context, host transcripts, private paths, and diffs must remain outside Git.

## Private dogfood records

Private-vault testing is a separate manual gate. It requires explicit user authorization and an explicitly selected vault; never infer a target from the checkout. Bind that path only in the local shell:

```bash
THREADROOT_DOGFOOD_VAULT="/explicit/user-selected/path"
threadroot doctor --vault "$THREADROOT_DOGFOOD_VAULT"
threadroot adopt --vault "$THREADROOT_DOGFOOD_VAULT"
```

First confirm that `doctor` made no changes. If the marker is absent, inspect the complete read-only `adopt` preview. Run `adopt --apply` only after a separate explicit confirmation. Then, if authorized, run one morning-review → recording → daily-wrap-up → weekly-review cycle.

Store the record outside this public repository. Record only the Threadroot version, host version, pass/fail, stable issue codes, and remediation outcome. Never record the vault path, note text, private identity, host transcript, generated fixture, or diff. A gate that was declined or not run must remain reported as unexecuted.

## Disposable uninstall check

The uninstall check removes only installation state created below one fresh temporary root. It must not use a vault as an uninstall target or touch normal Claude Code or Codex configuration. Build `dist` first, then run the complete sequence:

```bash
threadroot_uninstall_root="$(mktemp -d)"
threadroot_claude_bundle="$threadroot_uninstall_root/claude-marketplace"
threadroot_codex_bundle="$threadroot_uninstall_root/codex-marketplace"
threadroot_claude_config="$threadroot_uninstall_root/claude-config"
threadroot_codex_config="$threadroot_uninstall_root/codex-config"
mkdir "$threadroot_claude_config" "$threadroot_codex_config"
mkdir "$threadroot_claude_config/plugins"

python3 -m venv "$threadroot_uninstall_root/venv"
"$threadroot_uninstall_root/venv/bin/python" -m pip install \
  dist/threadroot-0.1.0-py3-none-any.whl
"$threadroot_uninstall_root/venv/bin/threadroot" init \
  --vault "$threadroot_uninstall_root/vault" --apply
cp -R "$threadroot_uninstall_root/vault" "$threadroot_uninstall_root/pristine"

python -m zipfile -e dist/threadroot-claude-0.1.0.zip \
  "$threadroot_claude_bundle"
python -m zipfile -e dist/threadroot-codex-0.1.0.zip \
  "$threadroot_codex_bundle"
CLAUDE_CONFIG_DIR="$threadroot_claude_config" \
CLAUDE_CODE_PLUGIN_CACHE_DIR="$threadroot_claude_config/plugins" \
  claude plugin marketplace add "$threadroot_claude_bundle" --scope user
CLAUDE_CONFIG_DIR="$threadroot_claude_config" \
CLAUDE_CODE_PLUGIN_CACHE_DIR="$threadroot_claude_config/plugins" \
  claude plugin install threadroot@threadroot --scope user
CLAUDE_CONFIG_DIR="$threadroot_claude_config" \
CLAUDE_CODE_PLUGIN_CACHE_DIR="$threadroot_claude_config/plugins" \
  claude plugin list --json
CODEX_HOME="$threadroot_codex_config" \
  codex plugin marketplace add "$threadroot_codex_bundle" --json
CODEX_HOME="$threadroot_codex_config" \
  codex plugin add threadroot@threadroot --json
CODEX_HOME="$threadroot_codex_config" codex plugin list --json

"$threadroot_uninstall_root/venv/bin/python" -m pip uninstall -y threadroot
CLAUDE_CONFIG_DIR="$threadroot_claude_config" \
CLAUDE_CODE_PLUGIN_CACHE_DIR="$threadroot_claude_config/plugins" \
  claude plugin remove threadroot@threadroot --scope user
CLAUDE_CONFIG_DIR="$threadroot_claude_config" \
CLAUDE_CODE_PLUGIN_CACHE_DIR="$threadroot_claude_config/plugins" \
  claude plugin marketplace remove threadroot --scope user
CODEX_HOME="$threadroot_codex_config" \
  codex plugin remove threadroot@threadroot --json
CODEX_HOME="$threadroot_codex_config" \
  codex plugin marketplace remove threadroot --json
python scripts/check_contract.py validate \
  --case tests/fixtures/contracts/uninstall-no-write.json \
  --before "$threadroot_uninstall_root/pristine" \
  --after "$threadroot_uninstall_root/vault"
```

Before removal, parse both list results and require an installed `threadroot` entry. Both `CLAUDE_CONFIG_DIR` and `CLAUDE_CODE_PLUGIN_CACHE_DIR` must be explicit on every disposable Claude plugin command: the first isolates configuration and the second prevents an inherited or default plugin-cache root from touching normal host state. Require every install, list, removal, and final contract command to exit zero; the last command must print `PASS`. Capture only tool versions, exit statuses, the two installed-entry booleans, and the final structural result. Do not log the temporary path or complete host JSON. Leave the temporary root for operating-system cleanup rather than deleting it recursively.

See [Contributing](../CONTRIBUTING.md) for the public/private boundary and [Security](../SECURITY.md) for the threat model.
