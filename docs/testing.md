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

The structural contract tooling introduced with the cross-host gate uses only the synthetic cases under `tests/fixtures/contracts`. After obtaining explicit authorization to launch each installed host and incur its normal model or network usage:

1. Materialize each case once below ignored `.dogfood/` storage with `python scripts/check_contract.py materialize --case CASE --output DIRECTORY`.
2. Copy that pristine fixture into separate Claude-result and Codex-result directories.
3. Load the local host package, submit the fixture's exact `request`, and permit reads only from `allowed_reads` plus validated configuration and filesystem metadata.
4. Run `python scripts/check_contract.py validate --case CASE --before PRISTINE --after RESULT` for each result.
5. Compare structure and safety outcomes across hosts; prose does not need to be identical.

Generated vaults, prompts containing real context, host transcripts, private paths, and diffs must remain outside Git.

## Private dogfood records

Private-vault testing requires explicit user authorization. Store its record outside this public repository and record only pass/fail and the tool version. Never record the vault path, note text, private identity, host transcript, or generated diff.

See [Contributing](../CONTRIBUTING.md) for the public/private boundary and [Security](../SECURITY.md) for the threat model.
