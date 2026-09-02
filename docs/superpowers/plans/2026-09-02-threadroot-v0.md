# Threadroot v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a local-first `threadroot` CLI and one provider-neutral skill set that developers can install for Claude Code and Codex without moving or exposing their Markdown vault.

**Architecture:** A Python 3.11+ standard-library core owns deterministic root/config resolution, validation, previews, and the `init`, `adopt`, and `doctor` commands. Shared Markdown skills own semantic workflows, while thin native manifests and reproducible release archives expose the same skills to both hosts.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `json`, `pathlib`, `unittest`, GitHub Actions, Claude Code and Codex plugin manifests.

**Spec:** `docs/superpowers/specs/2026-09-02-threadroot-v0-design.md`

## Global Constraints

- Runtime code uses only the Python standard library; `project.dependencies` stays empty.
- Support macOS and Linux on Python 3.11, 3.12, 3.13, and 3.14.
- The CLI is `threadroot`; the plugin identifier is `threadroot`; the first development version is `0.1.0`.
- The vault marker is exactly `.second-brain/config.json` with schema version `1`.
- `init` and `adopt` preview by default and write only with `--apply`; `doctor` is always read-only.
- Never overwrite vault files, follow a configured path outside the vault, emit note contents in diagnostics, or delete vault content.
- Shared skill bodies contain neither `Claude` nor `Codex`; host-specific prose belongs only in manifests and repository documentation, including `AGENTS.md`.
- Tests, fixtures, examples, logs, and artifacts use synthetic content only.
- Do not add `migrate`, rollback journals, expected hashes, MCP, RAG, GUI, telemetry, background networking, Windows support, or marketplace submission.
- Stage exact paths and run the task's focused tests before every commit.

---

## File Responsibility Map

| Path | Responsibility |
|---|---|
| `src/threadroot/results.py` | Stable changes, issues, command results, exit codes, and domain errors |
| `src/threadroot/jsonio.py` | Unique-key JSON parsing shared by vault markers and local pointers |
| `src/threadroot/paths.py` | Vault precedence, upward marker search, local default pointer, and containment |
| `src/threadroot/config.py` | Exact schema-v1 parsing, serialization, and configured-path validation |
| `src/threadroot/operations.py` | Pure plans plus explicit apply logic for `init`, `adopt`, and `doctor` |
| `src/threadroot/cli.py` | Argument parsing, operation dispatch, JSON/human rendering, and process exits |
| `skills/*/SKILL.md` | Provider-neutral semantic workflows |
| `templates/vault/*` | Synthetic starter structures referenced by skills and release packages |
| `.claude-plugin/*` | Claude plugin and canonical cross-host marketplace metadata |
| `.codex-plugin/plugin.json` | Codex-native plugin metadata |
| `scripts/build_release.py` | Reproducible Claude and Codex plugin archives |
| `scripts/check_public.py` | Privacy, secret-pattern, and artifact-boundary scan |
| `tests/*` | Unit, command, skill-contract, packaging, privacy, and structural-contract tests |

### Task 1: Package Skeleton and Stable Result Types

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `src/threadroot/__init__.py`
- Create: `src/threadroot/__main__.py`
- Create: `src/threadroot/cli.py`
- Create: `src/threadroot/results.py`
- Create: `tests/__init__.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_results.py`

**Interfaces:**
- Consumes: no application code.
- Produces: `threadroot.__version__: str`, `ExitCode`, `Change`, `Issue`, `CommandResult`, `ThreadrootError`, and `threadroot.cli.main(argv) -> int`.

- [ ] **Step 1: Write failing result and version tests**

~~~python
# tests/test_results.py
import unittest

from threadroot.results import Change, CommandResult, ExitCode, Issue


class CommandResultTests(unittest.TestCase):
    def test_to_dict_uses_stable_public_shape(self) -> None:
        result = CommandResult(
            ok=False,
            command="doctor",
            applied=False,
            vault="/tmp/example-vault",
            changes=(Change("create_directory", "daily", "planned"),),
            issues=(Issue("error", "config.invalid", "Invalid config", ".second-brain/config.json"),),
            exit_code=ExitCode.CONFIG,
        )

        self.assertEqual(
            result.to_dict(),
            {
                "ok": False,
                "command": "doctor",
                "applied": False,
                "vault": "/tmp/example-vault",
                "changes": [
                    {"action": "create_directory", "path": "daily", "status": "planned"}
                ],
                "issues": [
                    {
                        "level": "error",
                        "code": "config.invalid",
                        "message": "Invalid config",
                        "path": ".second-brain/config.json",
                    }
                ],
            },
        )
~~~

~~~python
# tests/test_cli.py
import contextlib
import io
import unittest

from threadroot import __version__
from threadroot.cli import main


class VersionTests(unittest.TestCase):
    def test_version(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), f"threadroot {__version__}\n")
~~~

- [ ] **Step 2: Run the focused tests and confirm the package does not exist**

Run: `PYTHONPATH=src python -m unittest tests.test_results tests.test_cli -v`
Expected: FAIL because `threadroot.results` and `threadroot.cli` do not exist.

- [ ] **Step 3: Create packaging metadata and result primitives**

Use this project metadata:

~~~toml
# pyproject.toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "threadroot"
version = "0.1.0"
description = "Local-first second-brain workflows for coding agents"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [{ name = "Threadroot contributors" }]
dependencies = []

[project.scripts]
threadroot = "threadroot.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
~~~

Create a minimal `README.md` containing the product name, tagline, one-paragraph summary, the Python requirement, and links to the design and plan. Add `.venv/`, `__pycache__/`, `*.py[cod]`, `build/`, `dist/`, `*.egg-info/`, and `.dogfood/` to `.gitignore`.

Implement the public types exactly:

~~~python
# src/threadroot/results.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Literal

CommandName = Literal["init", "adopt", "doctor"]
ActionName = Literal["create_directory", "create_file", "write_default_pointer"]
ChangeStatus = Literal["planned", "completed", "unexecuted"]
IssueLevel = Literal["error", "warning", "info"]


class ExitCode(IntEnum):
    OK = 0
    USAGE = 2
    CONFIG = 3
    UNSAFE_PATH = 4
    CONFLICT = 5
    IO_OR_DRIFT = 6


@dataclass(frozen=True)
class Change:
    action: ActionName
    path: str
    status: ChangeStatus


@dataclass(frozen=True)
class Issue:
    level: IssueLevel
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    command: CommandName
    applied: bool
    vault: str | None
    changes: tuple[Change, ...] = ()
    issues: tuple[Issue, ...] = ()
    exit_code: ExitCode = ExitCode.OK

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "command": self.command,
            "applied": self.applied,
            "vault": self.vault,
            "changes": [asdict(change) for change in self.changes],
            "issues": [asdict(issue) for issue in self.issues],
        }


class ThreadrootError(Exception):
    def __init__(
        self,
        exit_code: ExitCode,
        code: str,
        message: str,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.message = message
        self.path = path
~~~

`CommandResult.applied` records execution mode: it is true when a setup command was invoked with `--apply`, even when the validated plan is an idempotent no-op. The empty `changes` tuple communicates that no filesystem entry changed. It is always false for previews and `doctor`.

Set `__version__ = "0.1.0"` in `src/threadroot/__init__.py`. Implement `cli.main` with an `argparse.ArgumentParser(prog="threadroot")` and `--version`; when called without a command, print help to stderr and return `ExitCode.USAGE`. Make `src/threadroot/__main__.py` call `raise SystemExit(main())`.

- [ ] **Step 4: Run tests and the module entrypoint**

Run: `PYTHONPATH=src python -m unittest tests.test_results tests.test_cli -v`
Expected: 2 tests PASS.

Run: `PYTHONPATH=src python -m threadroot --version`
Expected: exactly `threadroot 0.1.0`.

- [ ] **Step 5: Commit the package foundation**

~~~bash
git add .gitignore README.md pyproject.toml src/threadroot tests/__init__.py tests/test_cli.py tests/test_results.py
git diff --cached --check
git commit -m "feat: establish Threadroot package foundation"
~~~

### Task 2: Schema-v1 Validation and Vault Resolution

**Files:**
- Create: `templates/vault/config.json`
- Create: `src/threadroot/jsonio.py`
- Create: `src/threadroot/config.py`
- Create: `src/threadroot/paths.py`
- Create: `tests/test_config.py`
- Create: `tests/test_paths.py`

**Interfaces:**
- Consumes: `ExitCode` and `ThreadrootError` from Task 1.
- Produces: `loads_unique_json(text)`, `VaultPaths`, `VaultConfig`, `DEFAULT_CONFIG`, `config_text()`, `load_config(root)`, `ensure_within(root, relative)`, `find_upward(start)`, `default_pointer_path(environ, home)`, `read_default_pointer(path)`, and `resolve_vault(explicit, cwd, environ, home)`.

- [ ] **Step 1: Write failing configuration tests**

~~~python
# tests/test_config.py
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from threadroot.config import DEFAULT_CONFIG, config_text, load_config
from threadroot.results import ExitCode, ThreadrootError


class ConfigTests(unittest.TestCase):
    def test_default_config_round_trips(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".second-brain" / "config.json"
            marker.parent.mkdir()
            marker.write_text(config_text(), encoding="utf-8")
            self.assertEqual(load_config(root), DEFAULT_CONFIG)

    def test_unknown_version_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".second-brain" / "config.json"
            marker.parent.mkdir()
            document = json.loads(config_text())
            document["schema_version"] = 2
            marker.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ThreadrootError) as raised:
                load_config(root)
            self.assertEqual(raised.exception.exit_code, ExitCode.CONFIG)

    def test_absolute_configured_path_is_unsafe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".second-brain" / "config.json"
            marker.parent.mkdir()
            document = json.loads(config_text())
            document["paths"]["daily"] = "/tmp/outside"
            marker.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ThreadrootError) as raised:
                load_config(root)
            self.assertEqual(raised.exception.exit_code, ExitCode.UNSAFE_PATH)
~~~

- [ ] **Step 2: Write failing path precedence and containment tests**

~~~python
# tests/test_paths.py
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from threadroot.paths import MARKER_RELATIVE, ensure_within, resolve_vault
from threadroot.results import ExitCode, ThreadrootError


class PathTests(unittest.TestCase):
    def test_explicit_path_wins_over_environment(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            explicit = base / "explicit"
            env_root = base / "environment"
            resolved = resolve_vault(
                explicit=explicit,
                cwd=base,
                environ={"SECOND_BRAIN_ROOT": str(env_root)},
                home=base / "home",
            )
            self.assertEqual(resolved, explicit.resolve())

    def test_upward_marker_wins_over_default_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            nested = vault / "work" / "repo"
            nested.mkdir(parents=True)
            marker = vault / MARKER_RELATIVE
            marker.parent.mkdir()
            marker.write_text("{}\n", encoding="utf-8")
            pointer = base / "home" / ".config" / "threadroot" / "config.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_text(json.dumps({"default_vault": str(base / "other")}), encoding="utf-8")
            self.assertEqual(
                resolve_vault(None, nested, {}, base / "home"),
                vault.resolve(),
            )

    def test_parent_escape_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ThreadrootError) as raised:
                ensure_within(root, "../outside")
            self.assertEqual(raised.exception.exit_code, ExitCode.UNSAFE_PATH)
~~~

- [ ] **Step 3: Run the focused tests and confirm missing modules**

Run: `PYTHONPATH=src python -m unittest tests.test_config tests.test_paths -v`
Expected: FAIL because `threadroot.config` and `threadroot.paths` do not exist.

- [ ] **Step 4: Implement exact schema parsing**

Use frozen value objects:

~~~python
# src/threadroot/config.py
@dataclass(frozen=True)
class VaultPaths:
    daily: str
    projects: str
    knowledge: str
    reviews: str


@dataclass(frozen=True)
class VaultConfig:
    schema_version: int
    paths: VaultPaths


DEFAULT_CONFIG = VaultConfig(
    schema_version=1,
    paths=VaultPaths(
        daily="daily",
        projects="wiki/projects",
        knowledge="wiki/tech",
        reviews="wiki/reviews",
    ),
)
~~~

`config_text()` returns the exact template document with `indent=2`, insertion-order keys, `ensure_ascii=False`, and one trailing newline. `load_config(root)` locates `root / ".second-brain/config.json"` and applies these checks in order:

1. `ensure_within` proves the marker itself resolves inside the vault before any read.
2. The marker is a regular readable file containing valid JSON.
3. The top-level key set is exactly `{"schema_version", "paths"}`.
4. `type(schema_version) is int` and its value is `1`.
5. The path key set is exactly `{"daily", "projects", "knowledge", "reviews"}`.
6. Every path value is a non-empty string after `strip()`.
7. `ensure_within(root, value)` accepts every configured path.

Implement `loads_unique_json` in `jsonio.py` with an `object_pairs_hook` that raises `ValueError` for duplicate keys at every object depth. Both callers translate parse failures into their public domain errors. Malformed JSON, duplicate keys, wrong types, missing keys, and extra keys raise `ThreadrootError(ExitCode.CONFIG, "config.invalid", ...)`. Unsupported versions use code `config.unsupported_version`. An escaping marker symlink or unsafe configured value retains `ExitCode.UNSAFE_PATH` from `ensure_within`; the escaping marker target is never opened.

Write the same JSON bytes to `templates/vault/config.json` and assert `config_text() == template.read_text()` in `tests/test_config.py`.

- [ ] **Step 5: Implement deterministic path resolution**

Define `MARKER_RELATIVE = Path(".second-brain/config.json")`. `ensure_within` must reject absolute input and any `..` path component before resolving; then resolve the candidate with `strict=False` and require `candidate.relative_to(root.resolve())` to succeed. This second check rejects existing symlinks that escape the vault.

`resolve_vault` applies exactly this order:

1. Non-empty explicit value.
2. Non-empty `SECOND_BRAIN_ROOT`.
3. `find_upward(cwd)`, checking the current directory and each parent for a regular marker file.
4. `read_default_pointer(default_pointer_path(environ, home))`.

Select the first present source and either return it or fail on that source; never fall through to a lower-precedence source after malformed or unsafe input.

Normalize explicit and `SECOND_BRAIN_ROOT` candidates against the injected `cwd` when they are relative, then resolve with `strict=False`; never let `Path.resolve()` implicitly use the process's unrelated current directory. When `XDG_CONFIG_HOME` is non-empty, require it to be absolute and use `XDG_CONFIG_HOME/threadroot/config.json`; when it is unset or empty, use `home/.config/threadroot/config.json`. A non-empty relative `XDG_CONFIG_HOME` is `config.invalid`. The pointer JSON key set is exactly `{"default_vault"}` and the value must be an absolute non-empty string. If no source exists, raise `ThreadrootError(ExitCode.CONFIG, "vault.unresolved", "Pass --vault to select a vault.")`.

Use the same duplicate-key parser for the default pointer. Add tests for relative explicit/environment candidates using the injected `cwd`, environment-over-upward precedence, valid pointer fallback, malformed or duplicate-key pointer JSON, missing resolution, a relative pointer, a relative `XDG_CONFIG_HOME`, a duplicate marker/path key, an escaping configured-directory symlink, and an escaping marker symlink whose target is rejected before its bytes are parsed.

- [ ] **Step 6: Run all path/config tests**

Run: `PYTHONPATH=src python -m unittest tests.test_config tests.test_paths -v`
Expected: all tests PASS, including template byte equality and symlink containment.

- [ ] **Step 7: Commit schema and path resolution**

~~~bash
git add templates/vault/config.json src/threadroot/jsonio.py src/threadroot/config.py src/threadroot/paths.py tests/test_config.py tests/test_paths.py
git diff --cached --check
git commit -m "feat: validate vault schema and resolve roots"
~~~

### Task 3: Preview-First `init` With Visible Partial Failure

**Files:**
- Create: `src/threadroot/operations.py`
- Create: `tests/test_operations.py`
- Modify: `src/threadroot/paths.py`

**Interfaces:**
- Consumes: `DEFAULT_CONFIG`, `config_text()`, `load_config()`, `default_pointer_path()`, `Change`, `CommandResult`, `ExitCode`, and `ThreadrootError`.
- Produces: `PlannedChange`, `plan_init(vault)`, `apply_plan(command, vault, plan)`, `write_default_pointer(vault, environ, home)`, and `run_init(vault, apply, set_default, environ, home)`.

- [ ] **Step 1: Write failing `init` behavior tests**

~~~python
# tests/test_operations.py
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from threadroot.operations import apply_plan, plan_init, run_init
from threadroot.results import ExitCode


class InitTests(unittest.TestCase):
    def test_preview_of_missing_target_is_pure(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "new-vault"
            result = run_init(vault, apply=False, set_default=False, environ={}, home=Path(directory))
            self.assertTrue(result.ok)
            self.assertFalse(result.applied)
            self.assertFalse(vault.exists())
            self.assertTrue(all(change.status == "planned" for change in result.changes))

    def test_apply_creates_exact_default_structure(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "new-vault"
            result = run_init(vault, apply=True, set_default=False, environ={}, home=Path(directory))
            self.assertTrue(result.ok)
            self.assertEqual(
                {
                    path.relative_to(vault).as_posix()
                    for path in vault.rglob("*")
                },
                {
                    ".second-brain",
                    ".second-brain/config.json",
                    "daily",
                    "wiki",
                    "wiki/projects",
                    "wiki/reviews",
                    "wiki/tech",
                },
            )
            self.assertEqual(
                json.loads((vault / ".second-brain/config.json").read_text()),
                {
                    "schema_version": 1,
                    "paths": {
                        "daily": "daily",
                        "projects": "wiki/projects",
                        "knowledge": "wiki/tech",
                        "reviews": "wiki/reviews",
                    },
                },
            )

    def test_non_empty_target_is_a_conflict(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / "notes.md").write_text("keep me", encoding="utf-8")
            result = run_init(vault, apply=True, set_default=False, environ={}, home=vault)
            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.CONFLICT)
            self.assertEqual((vault / "notes.md").read_text(), "keep me")
~~~

- [ ] **Step 2: Run the focused tests and confirm `operations` is missing**

Run: `PYTHONPATH=src python -m unittest tests.test_operations.InitTests -v`
Expected: FAIL because `threadroot.operations` does not exist.

- [ ] **Step 3: Implement the immutable plan model**

~~~python
# src/threadroot/operations.py
@dataclass(frozen=True)
class PlannedChange:
    action: ActionName
    target: Path
    public_path: str
    content: str | None = None
~~~

`public_path` is `"."` for the root, a vault-relative POSIX path for vault descendants, and the stable label `"machine-default-pointer"` for the external pointer. Never expose the machine's config-directory path through `changes` or `issues`; only `CommandResult.vault` intentionally carries the resolved absolute vault root.

When a marker already exists, `plan_init(vault)` returns an empty tuple only after `load_config` succeeds and every configured content path exists as a directory. A malformed marker or missing/invalid configured directory raises `ThreadrootError(ExitCode.CONFIG, "config.path_invalid", ...)`. Otherwise it rejects a non-directory target and any existing entry other than a single `.git` directory with `ExitCode.CONFLICT`. A missing vault requires an existing directory parent; reject a missing/non-directory parent with `ExitCode.CONFLICT` and code `target.parent_invalid` rather than creating unpreviewed ancestors. The first planned directory is then the vault root with public path `"."`. Plan these exact descendant paths in parent-before-child order:

~~~python
(".second-brain", "daily", "wiki", "wiki/projects", "wiki/tech", "wiki/reviews")
~~~

The final vault change is an exclusive-create of `.second-brain/config.json` with `config_text()`.

- [ ] **Step 4: Implement apply, drift detection, and partial-result reporting**

`apply_plan` executes `Path.mkdir()` without `exist_ok` for directory actions and `Path.open("x", encoding="utf-8", newline="\n")` for file actions. Immediately before each descendant operation, re-resolve its parent and confirm containment. The special vault-root creation action instead confirms that its normalized absolute target still equals the planned vault and that its parent remains an existing directory; a parent is not expected to be inside the child vault. On `FileExistsError` or any changed precondition, stop with `ExitCode.IO_OR_DRIFT` and issue code `target.drifted`. On other `OSError`, stop with issue code `filesystem.failed`.

The returned `changes` tuple includes every planned operation in original order: successful entries are `completed` and the failed plus later entries are `unexecuted`. Never delete already-created entries.

`write_default_pointer` serializes `{"default_vault": str(vault.resolve())}` with `ensure_ascii=False`, `sort_keys=True`, compact separators, and one trailing newline. The single previewed `write_default_pointer` action explicitly includes creating its missing machine-local parent directories, writing a temporary sibling file, and replacing the pointer with `os.replace`; it removes only a temporary file it created itself if replacement fails. It runs only after the vault plan succeeds. In preview mode, `run_init` includes that logical change only when `set_default` is true. In apply mode, a pointer-write failure returns exit `6`, retains completed vault changes, marks the pointer change `unexecuted`, and never rolls the vault back.

- [ ] **Step 5: Add race and partial-failure tests**

Create a plan for an empty existing vault, then create the second planned directory before calling `apply_plan`. Assert that the first change is `completed`, the collision and remaining changes are `unexecuted`, the exit code is `6`, and the pre-existing directory is untouched. Also test:

- A directory containing only `.git` is accepted.
- A missing vault whose direct parent does not exist fails during preview without creating ancestors.
- Re-running against a valid initialized vault is an exit-0 no-op.
- An invalid existing marker is not treated as initialized.
- `--set-default` preview writes nothing.
- Applied `set_default=True` writes only the machine-local pointer after the vault succeeds.
- A missing machine-local config directory is created only during `--apply --set-default` and is covered by the one previewed pointer action.

- [ ] **Step 6: Run operation and regression tests**

Run: `PYTHONPATH=src python -m unittest tests.test_operations tests.test_config tests.test_paths -v`
Expected: all tests PASS.

- [ ] **Step 7: Commit preview-first initialization**

~~~bash
git add src/threadroot/operations.py src/threadroot/paths.py tests/test_operations.py
git diff --cached --check
git commit -m "feat: add preview-first vault initialization"
~~~

### Task 4: Minimal, Non-Rewriting `adopt`

**Files:**
- Modify: `src/threadroot/operations.py`
- Modify: `tests/test_operations.py`

**Interfaces:**
- Consumes: `PlannedChange` and `apply_plan` from Task 3.
- Produces: `plan_adopt(vault)` and `run_adopt(vault, apply, set_default, environ, home)`.

- [ ] **Step 1: Write failing adoption tests**

~~~python
# append to tests/test_operations.py
class AdoptTests(unittest.TestCase):
    def make_existing_vault(self, root: Path) -> None:
        for relative in ("daily", "wiki/projects", "wiki/tech", "wiki/reviews"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "wiki/projects/demo/index.md").parent.mkdir(parents=True)
        (root / "wiki/projects/demo/index.md").write_text("# Synthetic Demo\n", encoding="utf-8")

    def test_preview_does_not_change_existing_vault(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_existing_vault(root)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            result = run_adopt(root, apply=False, set_default=False, environ={}, home=root / "home")
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertTrue(result.ok)
            self.assertEqual(before, after)
            self.assertFalse((root / ".second-brain").exists())

    def test_apply_adds_only_marker(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_existing_vault(root)
            original = (root / "wiki/projects/demo/index.md").read_bytes()
            result = run_adopt(root, apply=True, set_default=False, environ={}, home=root / "home")
            self.assertTrue(result.ok)
            self.assertEqual((root / "wiki/projects/demo/index.md").read_bytes(), original)
            self.assertTrue((root / ".second-brain/config.json").is_file())

    def test_incomplete_layout_lists_missing_directories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "daily").mkdir()
            result = run_adopt(root, apply=True, set_default=False, environ={}, home=root / "home")
            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.CONFLICT)
            self.assertIn("wiki/projects", result.issues[0].message)
~~~

- [ ] **Step 2: Run the adoption tests and confirm missing functions**

Run: `PYTHONPATH=src python -m unittest tests.test_operations.AdoptTests -v`
Expected: FAIL because `run_adopt` and `plan_adopt` are undefined.

- [ ] **Step 3: Implement the recognized-layout gate**

`plan_adopt` requires an existing directory and all four directories below:

~~~python
REQUIRED_ADOPT_DIRECTORIES = (
    "daily",
    "wiki/projects",
    "wiki/tech",
    "wiki/reviews",
)
~~~

Additional entries are accepted. Check for the marker before applying the default-layout gate: when it exists, validate it with `load_config`, require every configured content path to exist as a directory, and return no vault changes. For a markerless target, pass every required default path through `ensure_within` before testing its type; an escaping symlink returns `ExitCode.UNSAFE_PATH`, while missing or non-directory paths produce one `layout.unrecognized` error listing sorted missing/invalid paths and `ExitCode.CONFLICT`. Otherwise, plan `.second-brain` only when that path is absent, then plan the exclusive-create marker. An existing `.second-brain` must itself resolve inside the vault and be a directory; any other case is an unsafe-path error or conflict respectively. `run_adopt` uses the same preview, apply, and optional default-pointer path as `run_init`.

- [ ] **Step 4: Add no-rewrite and idempotency coverage**

Test an existing vault with extra files, Unicode note contents, and an unrelated `AGENTS.md`. Snapshot relative paths, bytes, and modification times before and after apply; the only new entries must be `.second-brain` and its config. Add a case with an existing `.second-brain` directory that plans and creates only `config.json`, an escaping required-directory symlink that returns exit `4`, and a second-run test that returns exit `0` without modifying the marker.

- [ ] **Step 5: Run all operation tests**

Run: `PYTHONPATH=src python -m unittest tests.test_operations -v`
Expected: all `init` and `adopt` tests PASS.

- [ ] **Step 6: Commit minimal adoption**

~~~bash
git add src/threadroot/operations.py tests/test_operations.py
git diff --cached --check
git commit -m "feat: adopt recognized vaults without rewriting"
~~~

### Task 5: Read-Only `doctor` and Complete CLI Dispatch

**Files:**
- Modify: `src/threadroot/operations.py`
- Modify: `src/threadroot/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_operations.py`

**Interfaces:**
- Consumes: `resolve_vault`, `load_config`, all Task 1 result types, and Task 3/4 runners.
- Produces: `run_doctor(vault)`, `build_parser()`, `execute(args, cwd, environ, home)`, `render_json(result)`, `render_human(result)`, and the complete `main(argv) -> int`.

- [ ] **Step 1: Write failing read-only doctor tests**

~~~python
# append to tests/test_operations.py
class DoctorTests(unittest.TestCase):
    def test_valid_vault_is_not_modified(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            init_result = run_init(root, apply=True, set_default=False, environ={}, home=root / "home")
            self.assertTrue(init_result.ok)
            before = {
                path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                for path in root.rglob("*")
                if path.is_file()
            }
            result = run_doctor(root)
            after = {
                path.relative_to(root): (path.stat().st_mtime_ns, path.read_bytes())
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertTrue(result.ok)
            self.assertEqual(before, after)

    def test_escaping_symlink_is_an_error(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "vault"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            for relative in ("wiki/projects", "wiki/tech", "wiki/reviews"):
                (root / relative).mkdir(parents=True)
            (root / "daily").symlink_to(outside, target_is_directory=True)
            marker = root / ".second-brain/config.json"
            marker.parent.mkdir()
            marker.write_text(config_text(), encoding="utf-8")
            result = run_doctor(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
~~~

- [ ] **Step 2: Write failing CLI JSON and exit-code tests**

~~~python
# append to tests/test_cli.py
import json
from pathlib import Path
from tempfile import TemporaryDirectory


class CommandLineTests(unittest.TestCase):
    def call(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_init_json_preview_is_one_object(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            code, stdout, stderr = self.call(["init", "--vault", str(vault), "--json"])
            payload = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(payload["command"], "init")
            self.assertFalse(payload["applied"])
            self.assertFalse(vault.exists())

    def test_doctor_missing_marker_returns_config_exit(self) -> None:
        with TemporaryDirectory() as directory:
            code, stdout, _ = self.call(["doctor", "--vault", directory, "--json"])
            self.assertEqual(code, 3)
            self.assertFalse(json.loads(stdout)["ok"])

    def test_doctor_rejects_apply_flag_as_usage(self) -> None:
        with TemporaryDirectory() as directory:
            code, _, _ = self.call(["doctor", "--vault", directory, "--apply"])
            self.assertEqual(code, 2)
~~~

- [ ] **Step 3: Run focused tests and confirm doctor/dispatch failures**

Run: `PYTHONPATH=src python -m unittest tests.test_operations.DoctorTests tests.test_cli.CommandLineTests -v`
Expected: FAIL because `run_doctor` and complete subcommand dispatch are absent.

- [ ] **Step 4: Implement read-only diagnosis**

`run_doctor` performs checks without creating a probe:

1. Root exists and is a directory.
2. Marker is a regular readable file.
3. `load_config` accepts exact schema v1.
4. Each configured target passes `ensure_within`, exists, and is a directory.
5. `os.access(path, os.R_OK)` is true; false is an error.
6. `os.access(path, os.W_OK)` is true; false is a warning.
7. `root / ".git"` missing is one `info` issue with code `git.not_found`.

Return `ok=True` when there are no error-level issues. Select `ExitCode.UNSAFE_PATH` if any containment error exists, otherwise `ExitCode.CONFIG` for any other error, otherwise `ExitCode.OK`. Sort findings by severity (`error`, `warning`, `info`), then code and relative path so repeat runs are stable. `changes` is always empty and `applied` is always false.

- [ ] **Step 5: Implement parser, dispatch, and renderers**

`build_parser()` creates `init`, `adopt`, and `doctor` subparsers with `allow_abbrev=False`. All receive `--vault` and `--json`. Only `init` and `adopt` receive `--apply` and `--set-default`. Do not use `parse_known_args`. Use a small `argparse.ArgumentParser` subclass whose `error(message)` raises `ThreadrootError(ExitCode.USAGE, "usage.invalid", message)` so invalid flags return exit `2` through `main` instead of raising `SystemExit`.

After parsing a valid command, `execute` resolves the vault once, dispatches to the matching runner, and converts operation-time `ThreadrootError` into one error `Issue` without a traceback. Parser-time usage errors have no valid `CommandName`, so `main` catches them before `execute`, prints one concise human error to stderr, and returns `2`; it does not fabricate a `CommandResult`. For valid commands, `main` injects real `Path.cwd()`, `os.environ`, and `Path.home()`, prints JSON to stdout when requested, prints successful human output to stdout, prints human errors to stderr, and returns `int(result.exit_code)`.

Use stable JSON:

~~~python
def render_json(result: CommandResult) -> str:
    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
~~~

Human output begins with exactly one summary line:

~~~text
OK init preview /resolved/vault
OK adopt applied /resolved/vault
OK doctor checked /resolved/vault
ERROR doctor /resolved/vault
~~~

Then print changes as `[planned] action path` or `[completed] action path` and issues as `LEVEL code: message (path)`; omit the parenthesized suffix when `Issue.path` is `None`. Never print file contents or the full environment.

- [ ] **Step 6: Complete CLI and default-pointer coverage**

Add subprocess coverage for `python -m threadroot`; the installed console-script smoke test belongs to Task 10 after a wheel exists. Add direct tests for:

- Explicit `--vault` over `SECOND_BRAIN_ROOT`.
- Environment over upward marker.
- Upward marker over default pointer.
- Default pointer fallback.
- `init --set-default` without `--apply` remains a pure preview.
- `init --apply --set-default` changes the pointer only after successful initialization.
- Argparse usage errors return `2`.
- Abbreviated long options and unsupported flags are rejected rather than guessed.
- Config errors return `3`, path escapes `4`, conflicts `5`, and drift/I/O `6`.

- [ ] **Step 7: Run the full Python suite**

Run: `PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 8: Commit the completed CLI**

~~~bash
git add src/threadroot/cli.py src/threadroot/operations.py tests/test_cli.py tests/test_operations.py
git diff --cached --check
git commit -m "feat: add read-only doctor and CLI dispatch"
~~~

### Task 6: Shared Skill Contract, Vault Templates, and Core Skills

**Required task skills:** Before writing any `SKILL.md`, invoke the `superpowers:writing-skills` and `skill-creator` skills and preserve this plan's provider-neutral and public-safety constraints.

**Files:**
- Create: `skills/README.md`
- Create: `skills/second-brain-setup/SKILL.md`
- Create: `skills/second-brain-doctor/SKILL.md`
- Create: `skills/query/SKILL.md`
- Create: `templates/vault/daily.md`
- Create: `templates/vault/project.md`
- Create: `templates/vault/decision.md`
- Create: `templates/vault/weekly-review.md`
- Create: `tests/skill_contract.py`
- Create: `tests/test_skills.py`

**Interfaces:**
- Consumes: the installed `threadroot` CLI and schema-v1 paths.
- Produces: a reusable static validator `load_skill(name) -> SkillDocument`, four public vault templates, and the setup/doctor/query workflows.

- [ ] **Step 1: Write the failing skill-contract tests**

~~~python
# tests/skill_contract.py
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class SkillDocument:
    name: str
    description: str
    body: str


def load_skill(name: str) -> SkillDocument:
    path = Path("skills") / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"{path} must have one YAML frontmatter block")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"invalid frontmatter line in {path}: {line}")
        fields[key.strip()] = value.strip().strip('"')
    if set(fields) != {"name", "description"}:
        raise AssertionError(f"{path} frontmatter keys must be name and description")
    return SkillDocument(fields["name"], fields["description"], match.group(2))
~~~

~~~python
# tests/test_skills.py
from pathlib import Path
import re
import unittest

from tests.skill_contract import load_skill


class CoreSkillContractTests(unittest.TestCase):
    def test_core_skills_are_provider_neutral_and_structured(self) -> None:
        for name in ("second-brain-setup", "second-brain-doctor", "query"):
            with self.subTest(name=name):
                skill = load_skill(name)
                self.assertEqual(skill.name, name)
                self.assertNotRegex(skill.body, r"\b(?:Claude|Codex)\b")
                for heading in ("## Inputs", "## Procedure", "## Safety", "## Output"):
                    self.assertIn(heading, skill.body)

    def test_config_template_matches_runtime(self) -> None:
        from threadroot.config import config_text
        self.assertEqual(
            Path("templates/vault/config.json").read_text(encoding="utf-8"),
            config_text(),
        )
~~~

- [ ] **Step 2: Run the core skill tests and confirm missing files**

Run: `PYTHONPATH=src python -m unittest tests.test_skills.CoreSkillContractTests -v`
Expected: FAIL because the three skill files and helper do not exist.

- [ ] **Step 3: Create the shared skill-writing contract**

`skills/README.md` defines these rules:

- Frontmatter contains only `name` and trigger-focused `description`.
- Every skill has `Inputs`, `Procedure`, `Safety`, and `Output` sections.
- Read only files needed for the active workflow.
- Before any CLI-dependent workflow, run `threadroot --version`; if unavailable, stop and point to installation instructions without installing automatically.
- Before semantic work, run `threadroot doctor --json` and require an exit-0 result. Use its `vault` field as the resolved root, then read exactly that root's already-validated `.second-brain/config.json` to obtain the four configured path strings; do not duplicate or weaken the CLI's validation in prompt logic.
- Check the marker's metadata immediately before and after that one read. If it changes across the read or the document no longer has the diagnosed shape, stop and rerun diagnosis. If the host denies access to an external vault, stop and ask the user to add that vault as an approved working directory; never copy it into the current project as a workaround.
- Re-read a target immediately before editing and stop on drift.
- Use host-native read/edit tools for Markdown; never implement semantic edits in the CLI.
- Do not read `secrets`, print secret payloads, copy private content into public code, or commit/push without a direct request.
- Preview structural moves, bulk rewrites, taxonomy changes, and deletion, then wait for explicit confirmation.
- Use `the agent`, `the model`, and `the host` in shared instructions.

- [ ] **Step 4: Create four exact public templates**

Use these heading contracts:

`templates/vault/daily.md`:

~~~markdown
# {{date}}

## Focus

## Work Log

## Decisions

## Follow-up
~~~

`templates/vault/project.md`:

~~~markdown
# {{project_name}}

## Current Status

## Pending

## Recent Activity

## Lessons Learned

## Key Decisions
~~~

`templates/vault/decision.md`:

~~~markdown
# {{decision_title}}

## Context

## Options Considered

## Decision

## Rationale

## Expected Outcome

## Followup

## Review Notes

## Related
~~~

`templates/vault/weekly-review.md`:

~~~markdown
# Weekly Review {{iso_week}}

## Outcomes

## Decisions

## Carry Forward

## Lessons
~~~

- [ ] **Step 5: Write the three core skill procedures**

Each skill uses the common contract and the following exact workflow:

| Skill | Required procedure |
|---|---|
| `second-brain-setup` | Determine new vs existing target; run `threadroot init` or `threadroot adopt` without `--apply`; show the complete plan; obtain explicit apply intent; rerun with `--apply`; finish with `threadroot doctor`. |
| `second-brain-doctor` | Run `threadroot doctor --json`; group errors before warnings and info; explain one remediation per issue; never repair or add `--apply` automatically. |
| `query` | Confirm `doctor` passes; identify the smallest relevant configured area; search filenames/headings first; read only matched sections and explicit links; answer with vault-relative source paths; remain read-only. |

Each of these three skills first checks `threadroot --version`. If the executable is unavailable, stop with the README's CLI-install instruction; do not auto-install software or reimplement config/path validation in prompt logic. The `second-brain-setup` safety section must state that `init` is only for missing/empty targets, `adopt` adds only the marker, and neither command moves existing notes. The `query` output section must distinguish sourced facts from inference.

- [ ] **Step 6: Expand static tests**

Assert that each core skill contains its exact CLI command names, the drift-stop rule, and a no-secret rule. Recursively scan `skills/**/*.md` for absolute home paths, secret assignment patterns, and provider names. Ensure the templates contain only the headings above and `{{date}}`, `{{project_name}}`, `{{decision_title}}`, or `{{iso_week}}` variables.

- [ ] **Step 7: Run skill and Python regression tests**

Run: `PYTHONPATH=src python -m unittest tests.test_skills -v`
Expected: all core skill-contract tests PASS.

Run: `PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: the full suite PASS.

- [ ] **Step 8: Commit the shared skill foundation**

~~~bash
git add skills/README.md skills/second-brain-setup skills/second-brain-doctor skills/query templates/vault tests/skill_contract.py tests/test_skills.py
git diff --cached --check
git commit -m "feat: add provider-neutral core skills"
~~~

### Task 7: Daily and Weekly Lifecycle Skills

**Required task skills:** Invoke `superpowers:writing-skills` and `skill-creator` before editing the four skills.

**Files:**
- Create: `skills/recording/SKILL.md`
- Create: `skills/morning-review/SKILL.md`
- Create: `skills/daily-wrap-up/SKILL.md`
- Create: `skills/weekly-review/SKILL.md`
- Create: `tests/fixtures/contracts/daily-lifecycle.json`
- Modify: `tests/test_skills.py`

**Interfaces:**
- Consumes: schema-v1 daily, projects, knowledge, and reviews paths plus the common skill contract.
- Produces: four lifecycle workflows and one synthetic structural contract shared by both hosts.

- [ ] **Step 1: Add failing lifecycle contract tests**

~~~python
# append to tests/test_skills.py
class LifecycleSkillContractTests(unittest.TestCase):
    REQUIRED = {
        "recording": ("Current Status", "Pending", "Recent Activity", "Lessons Learned"),
        "morning-review": ("Focus", "Pending", "read-only"),
        "daily-wrap-up": ("Work Log", "Follow-up", "Lessons"),
        "weekly-review": ("Outcomes", "Decisions", "Carry Forward", "Lessons"),
    }

    def test_lifecycle_skills_publish_required_contracts(self) -> None:
        for name, phrases in self.REQUIRED.items():
            with self.subTest(name=name):
                skill = load_skill(name)
                self.assertEqual(skill.name, name)
                self.assertNotRegex(skill.body, r"\b(?:Claude|Codex)\b")
                for phrase in phrases:
                    self.assertIn(phrase, skill.body)
~~~

Load `tests/fixtures/contracts/daily-lifecycle.json` and assert it has the exact keys `name`, `request`, `allowed_reads`, `expected_writes`, `required_headings`, `required_links`, and `forbidden_actions`.

- [ ] **Step 2: Run the lifecycle tests and confirm missing skills**

Run: `PYTHONPATH=src python -m unittest tests.test_skills.LifecycleSkillContractTests -v`
Expected: FAIL because the four lifecycle skills are absent.

- [ ] **Step 3: Write `recording` and `morning-review`**

`recording`:

1. Run doctor and resolve the current daily and matching project paths.
2. Read the current daily note when present and only the matching project's Current Status, Pending, Recent Activity, and Lessons Learned sections. If today's note is missing, draft it from `templates/vault/daily.md` and exclusive-create it only after rechecking absence. If no matching project page exists, record only the daily entry and report that project routing was skipped; do not create a project implicitly.
3. Deduplicate work using an existing commit hash, issue/PR reference, or exact event fingerprint.
4. Draft an additive daily narrative and a concise project update.
5. Re-read both targets, stop on drift, then apply.
6. Never infer that a Pending item is complete; require evidence or user confirmation.
7. Route a lesson to durable knowledge only after two concrete cross-project cases; otherwise retain it on the project page.

`morning-review`:

1. Remain read-only.
2. Read today's daily note if present and unchecked Pending items from active projects. Read a goal page only when the user supplies its path or a selected daily/project page explicitly links to it; schema v1 has no implicit goals directory.
3. Separate executable work from unresolved choices and vague ideas.
4. Propose no more than three Focus items with explicit completion conditions.
5. Cite each proposed item with a vault-relative project or goal path.

- [ ] **Step 4: Write `daily-wrap-up` and `weekly-review`**

`daily-wrap-up`:

1. Read today's Focus and Work Log plus only projects referenced by today's work. If today's note is absent, disclose that no day record exists and ask before creating one from the daily template.
2. Reconcile completed, in-progress, blocked, decision, and follow-up items without inventing activity.
3. Draft daily and project updates, identify durable decisions and lessons, and show ambiguous completions before changing Pending.
4. Re-read each target and apply additive edits.
5. End with carry-forward items and source paths.

`weekly-review`:

1. Read exactly the seven daily-note paths for the requested ISO week; missing days remain explicit.
2. Read only project pages referenced by those notes.
3. Produce one review from `templates/vault/weekly-review.md`.
4. Deduplicate outcomes and decisions by source reference.
5. Exclusive-create a missing weekly-review path. If it exists, preview an additive reconciliation and stop on drift; never replace the whole file.
6. Do not modify daily or project pages unless the user separately requests reconciliation.

- [ ] **Step 5: Add the synthetic lifecycle contract**

Use only these synthetic values:

~~~json
{
  "name": "daily-lifecycle",
  "request": "Record a completed parser task and prepare tomorrow's focus.",
  "allowed_reads": [
    "daily/2042-04-03.md",
    "wiki/projects/orchard-cli/index.md"
  ],
  "expected_writes": [
    "daily/2042-04-03.md",
    "wiki/projects/orchard-cli/index.md"
  ],
  "required_headings": {
    "daily/2042-04-03.md": [
      "Work Log"
    ],
    "wiki/projects/orchard-cli/index.md": [
      "Recent Activity",
      "Pending"
    ]
  },
  "required_links": {},
  "forbidden_actions": [
    "read secrets",
    "commit",
    "push",
    "bulk rewrite"
  ]
}
~~~

- [ ] **Step 6: Run lifecycle and regression tests**

Run: `PYTHONPATH=src python -m unittest tests.test_skills.LifecycleSkillContractTests -v`
Expected: lifecycle tests PASS.

Run: `PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: full suite PASS.

- [ ] **Step 7: Commit lifecycle workflows**

~~~bash
git add skills/recording skills/morning-review skills/daily-wrap-up skills/weekly-review tests/fixtures/contracts/daily-lifecycle.json tests/test_skills.py
git diff --cached --check
git commit -m "feat: add daily and weekly knowledge workflows"
~~~

### Task 8: Project Kickoff and Decision Log Skills

**Required task skills:** Invoke `superpowers:writing-skills` and `skill-creator` before editing both skills.

**Files:**
- Create: `skills/project-kickoff/SKILL.md`
- Create: `skills/decision-log/SKILL.md`
- Create: `tests/fixtures/contracts/project-decision.json`
- Modify: `tests/test_skills.py`

**Interfaces:**
- Consumes: project and decision templates plus the common skill contract.
- Produces: safe project creation, durable A-over-B decisions, backlinks, and actionable follow-up routing.

- [ ] **Step 1: Add failing project/decision tests**

~~~python
# append to tests/test_skills.py
class ProjectSkillContractTests(unittest.TestCase):
    def test_project_kickoff_has_confirmation_boundaries(self) -> None:
        body = load_skill("project-kickoff").body
        for phrase in (
            "identity",
            "public/private",
            "auto-loaded",
            "ignored by Git",
            "preview",
            "explicit confirmation",
        ):
            self.assertIn(phrase, body)

    def test_decision_log_requires_real_tradeoffs_and_backlinks(self) -> None:
        body = load_skill("decision-log").body
        for phrase in (
            "two real alternatives",
            "trade-off",
            "Followup",
            "Pending",
            "Key Decisions",
            "supersede",
        ):
            self.assertIn(phrase, body)
~~~

- [ ] **Step 2: Run the tests and confirm both skills are absent**

Run: `PYTHONPATH=src python -m unittest tests.test_skills.ProjectSkillContractTests -v`
Expected: FAIL because the two skill files do not exist.

- [ ] **Step 3: Write `project-kickoff`**

The procedure must:

1. Confirm project identity, purpose, repository visibility, target user, and public/private boundary one question at a time.
2. Inspect the target, its tracked instructions, and ignore rules before proposing any structure.
3. Present the exact project-page path. Propose a project-local context path only when the active host exposes a native auto-loaded local-instruction convention and that exact path is ignored by Git; otherwise report that no safe local adapter was discovered and do not invent an inert file.
4. Show a complete preview of every proposed path and obtain explicit confirmation, then create only the project page, the confirmed local adapter when eligible, and currently required directories; do not initialize, publish, or push a code repository without separate authorization.
5. Keep private paths, identities, personal workflows, and company context out of tracked public files.
6. Finish with verifiable paths and concrete Pending work.

- [ ] **Step 4: Write `decision-log`**

The procedure must:

1. Classify the input as a genuine choice only when at least two real alternatives and a trade-off exist.
2. Route product decisions to the matching project's `decisions/` directory.
3. Draft from `templates/vault/decision.md`, remain self-contained, and show the complete draft before writing.
4. Require Context, Options Considered, Decision, Rationale, Expected Outcome, Followup when work remains, Review Notes, and Related.
5. After approval, re-read the project page, write the ADR, deduplicate Followup into Pending, and add a Key Decisions backlink.
6. Supersede rather than delete an obsolete ADR and maintain both directions of the relationship.
7. Use retrievable URLs, PR/issue identifiers, or commit hashes for external provenance.
8. Exclusive-create a new ADR path. If it already exists, treat matching content as a no-op and otherwise stop for a naming decision; never overwrite it. If the ADR succeeds but the project backlink fails, report both the completed and pending repair explicitly rather than deleting the ADR.

- [ ] **Step 5: Add the synthetic decision contract**

Create this complete fixture:

~~~json
{
  "name": "project-decision",
  "request": "Record the decision to use JSON files instead of SQLite or hosted storage for orchard-cli.",
  "allowed_reads": [
    "wiki/projects/orchard-cli/index.md"
  ],
  "expected_writes": [
    "wiki/projects/orchard-cli/index.md",
    "wiki/projects/orchard-cli/decisions/2042-04-03-json-storage.md"
  ],
  "required_headings": {
    "wiki/projects/orchard-cli/index.md": [
      "Key Decisions"
    ],
    "wiki/projects/orchard-cli/decisions/2042-04-03-json-storage.md": [
      "Options Considered",
      "Decision",
      "Rationale"
    ]
  },
  "required_links": {
    "wiki/projects/orchard-cli/index.md": [
      "decisions/2042-04-03-json-storage"
    ],
    "wiki/projects/orchard-cli/decisions/2042-04-03-json-storage.md": [
      "../index"
    ]
  },
  "forbidden_actions": [
    "read secrets",
    "publish repository",
    "delete files",
    "commit",
    "push"
  ]
}
~~~

- [ ] **Step 6: Assert the complete skill set**

Extend `tests/test_skills.py` with:

~~~python
EXPECTED_SKILLS = {
    "second-brain-setup",
    "second-brain-doctor",
    "query",
    "recording",
    "morning-review",
    "daily-wrap-up",
    "weekly-review",
    "project-kickoff",
    "decision-log",
}


class CompleteSkillSetTests(unittest.TestCase):
    def test_exact_v0_skill_set(self) -> None:
        actual = {path.parent.name for path in Path("skills").glob("*/SKILL.md")}
        self.assertEqual(actual, EXPECTED_SKILLS)
~~~

- [ ] **Step 7: Run all skill and Python tests**

Run: `PYTHONPATH=src python -m unittest tests.test_skills -v`
Expected: all skill-contract tests PASS.

Run: `PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: full suite PASS.

- [ ] **Step 8: Commit project knowledge workflows**

~~~bash
git add skills/project-kickoff skills/decision-log tests/fixtures/contracts/project-decision.json tests/test_skills.py
git diff --cached --check
git commit -m "feat: add project and decision workflows"
~~~

### Task 9: Native Manifests and One Canonical Marketplace Catalog

**Required task skill:** Invoke `plugin-creator` before creating or updating the native manifests, and use its validation contract for `.codex-plugin/plugin.json`. Do not run its personal-marketplace scaffold or create `.agents/plugins/marketplace.json`; this public repository's explicitly approved cross-host catalog layout overrides that default.

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`
- Create: `.codex-plugin/plugin.json`
- Create: `tests/test_packaging.py`

**Interfaces:**
- Consumes: the exact nine-skill directory from Task 8 and version `0.1.0`.
- Produces: a Claude-native manifest, a Codex-native manifest, and a Claude-compatible marketplace catalog accepted by Codex import without a separately maintained `.agents/plugins/marketplace.json`.

- [ ] **Step 1: Write failing manifest parity tests**

~~~python
# tests/test_packaging.py
import json
from pathlib import Path
import tomllib
import unittest

from threadroot import __version__


def load_json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ManifestTests(unittest.TestCase):
    def test_version_matches_python_package_metadata(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        claude = load_json(".claude-plugin/plugin.json")
        codex = load_json(".codex-plugin/plugin.json")
        marketplace = load_json(".claude-plugin/marketplace.json")
        self.assertEqual(
            {
                __version__,
                project["version"],
                claude["version"],
                codex["version"],
                marketplace["plugins"][0]["version"],
            },
            {"0.1.0"},
        )

    def test_native_manifests_share_public_metadata(self) -> None:
        claude = load_json(".claude-plugin/plugin.json")
        codex = load_json(".codex-plugin/plugin.json")
        for key in ("name", "version", "description", "author", "license", "keywords"):
            self.assertEqual(claude[key], codex[key])
        self.assertEqual(codex["skills"], "./skills/")

    def test_codex_manifest_has_complete_interface_metadata(self) -> None:
        interface = load_json(".codex-plugin/plugin.json")["interface"]
        self.assertEqual(
            set(interface),
            {
                "displayName",
                "shortDescription",
                "longDescription",
                "developerName",
                "category",
                "capabilities",
                "defaultPrompt",
            },
        )
        self.assertEqual(interface["displayName"], "Threadroot")
        self.assertEqual(interface["developerName"], "Threadroot contributors")
        self.assertEqual(interface["category"], "Developer Tools")
        self.assertEqual(interface["capabilities"], ["Interactive", "Read", "Write"])
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in interface["defaultPrompt"]))

    def test_marketplace_points_to_the_repository_plugin(self) -> None:
        marketplace = load_json(".claude-plugin/marketplace.json")
        self.assertEqual(marketplace["name"], "threadroot")
        self.assertEqual(len(marketplace["plugins"]), 1)
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "threadroot")
        self.assertEqual(plugin["version"], "0.1.0")
        self.assertEqual(plugin["source"], "./")

    def test_every_manifest_skill_exists(self) -> None:
        expected = {
            "second-brain-setup",
            "second-brain-doctor",
            "query",
            "recording",
            "morning-review",
            "daily-wrap-up",
            "weekly-review",
            "project-kickoff",
            "decision-log",
        }
        actual = {path.parent.name for path in Path("skills").glob("*/SKILL.md")}
        self.assertEqual(actual, expected)
~~~

- [ ] **Step 2: Run packaging tests and confirm manifests are missing**

Run: `PYTHONPATH=src python -m unittest tests.test_packaging -v`
Expected: FAIL with `FileNotFoundError` for the native manifests.

- [ ] **Step 3: Create exact native manifests**

Use the same values in both files:

~~~json
{
  "name": "threadroot",
  "version": "0.1.0",
  "description": "Local-first second-brain workflows for coding agents",
  "author": {
    "name": "Threadroot contributors"
  },
  "license": "Apache-2.0",
  "keywords": [
    "second-brain",
    "agent-skills",
    "local-first",
    "developer-tools"
  ]
}
~~~

The Claude file is exactly that object. In the Codex file, add the required comma after the common `keywords` array and append these two top-level fields:

~~~json
"skills": "./skills/",
"interface": {
  "displayName": "Threadroot",
  "shortDescription": "Local-first second-brain workflows",
  "longDescription": "Set up, query, and maintain a user-owned Markdown vault across coding-agent sessions.",
  "developerName": "Threadroot contributors",
  "category": "Developer Tools",
  "capabilities": [
    "Interactive",
    "Read",
    "Write"
  ],
  "defaultPrompt": [
    "Set up a user-owned second-brain vault.",
    "Review today's work from my second brain.",
    "Record this work in my second brain."
  ]
}
~~~

Keep both as formatted JSON with two-space indentation and one trailing newline. The Codex `interface` is required presentation metadata, not an instruction adapter; do not put workflow procedures in either manifest. Omit URLs and image fields until real public destinations and assets exist.

- [ ] **Step 4: Create the canonical marketplace catalog**

`.claude-plugin/marketplace.json` is:

~~~json
{
  "name": "threadroot",
  "description": "Threadroot local and repository installations",
  "owner": {
    "name": "Threadroot contributors"
  },
  "plugins": [
    {
      "name": "threadroot",
      "description": "Local-first second-brain workflows for coding agents",
      "version": "0.1.0",
      "source": "./",
      "author": {
        "name": "Threadroot contributors"
      },
      "license": "Apache-2.0",
      "keywords": [
        "second-brain",
        "agent-skills",
        "local-first",
        "developer-tools"
      ]
    }
  ]
}
~~~

Do not create `.agents/plugins/marketplace.json` in v0. The checked-in `.codex-plugin/plugin.json` is thin metadata for direct local/repository Codex installation and verification, not a second workflow tree or a marketplace-submission adapter. If Threadroot later enters OpenAI's skills-only submission flow, upload the Claude archive: the portal converts `.claude-plugin/plugin.json` to `.codex-plugin/plugin.json`, while `.claude-plugin/marketplace.json` is not a submission dependency. Review the generated manifest instead of assuming byte identity. Conversion alone does not make Threadroot submission-ready: the same official guide requires contacting an OpenAI partner when a plugin's core value depends on local execution or arbitrary local-file access, so submission remains deferred in v0: [Submit your Claude Code plugin to OpenAI](https://developers.openai.com/plugins/guides/submit-claude-plugin).

The `"source": "./"` entry follows Claude Code's relative-source contract: the value starts with `./` and resolves from the marketplace root. Validate both that catalog and the plugin with the documented CLI flow: [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

- [ ] **Step 5: Add metadata and wording guards**

Extend `tests/test_packaging.py` to assert:

- Both manifests have only the common keys above, plus `skills` and `interface` in the Codex file; the interface has exactly the seven tested fields and every prompt is non-empty.
- The catalog's plugin metadata equals the native common metadata for name, version, description, author, license, and keywords; `source` is its only marketplace-specific field.
- Every JSON file parses and ends with one newline.
- `.agents/plugins/marketplace.json` is absent.
- No `skills/*/SKILL.md` body contains `Claude` or `Codex`.
- Host-specific prose is limited to `.claude-plugin/`, `.codex-plugin/`, `AGENTS.md`, `README.md`, and `docs/`; test code may name hosts only to enforce or exercise that boundary.

- [ ] **Step 6: Run static and native host validation**

Run: `PYTHONPATH=src python -m unittest tests.test_packaging tests.test_skills -v`
Expected: all tests PASS.

When the executable is available, run: `claude plugin validate --strict .`
Expected: validation succeeds without warnings.

For Codex, use a disposable config root rather than modifying the developer's normal plugin configuration:

~~~bash
threadroot_codex_test_root="$(mktemp -d)"
CODEX_HOME="$threadroot_codex_test_root" codex plugin marketplace add "$PWD" --json
CODEX_HOME="$threadroot_codex_test_root" codex plugin add threadroot@threadroot --json
CODEX_HOME="$threadroot_codex_test_root" codex plugin list --json
~~~

Expected: all three commands return successful JSON and the list marks `threadroot@threadroot` installed. Combined with the exact-skill-set packaging test, this proves the installed source contains the nine skills. Leave the disposable directory for operating-system cleanup; do not use a broad recursive delete command.

- [ ] **Step 7: Commit native packaging metadata**

~~~bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json .codex-plugin/plugin.json tests/test_packaging.py
git diff --cached --check
git commit -m "feat: package shared skills for Claude and Codex"
~~~

### Task 10: Reproducible Release Archives and Public-Safety Scan

**Files:**
- Create: `MANIFEST.in`
- Create: `scripts/build_release.py`
- Create: `scripts/check_public.py`
- Create: `tests/test_release.py`
- Create: `tests/test_public_safety.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: version, native manifests, shared skills, templates, license, README, and an optional machine-local denylist for private identities or organization names.
- Produces: `build_archive(host, output_dir) -> Path`, `scan_path(path, denied_terms=()) -> list[Finding]`, a wheel, a source distribution, and `threadroot-{claude,codex}-0.1.0.zip`.

- [ ] **Step 1: Write failing release-content tests**

~~~python
# tests/test_release.py
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from scripts.build_release import build_archive


class ReleaseArchiveTests(unittest.TestCase):
    def test_host_archives_have_native_manifest_and_shared_content(self) -> None:
        expected_common = {
            "LICENSE",
            "README.md",
            "skills/query/SKILL.md",
            "skills/second-brain-setup/SKILL.md",
            "templates/vault/config.json",
        }
        with TemporaryDirectory() as directory:
            output = Path(directory)
            claude = build_archive("claude", output)
            codex = build_archive("codex", output)
            with zipfile.ZipFile(claude) as archive:
                names = set(archive.namelist())
                self.assertTrue(expected_common <= names)
                self.assertIn(".claude-plugin/plugin.json", names)
                self.assertIn(".claude-plugin/marketplace.json", names)
                self.assertNotIn(".codex-plugin/plugin.json", names)
            with zipfile.ZipFile(codex) as archive:
                names = set(archive.namelist())
                self.assertTrue(expected_common <= names)
                self.assertIn(".codex-plugin/plugin.json", names)
                self.assertIn(".claude-plugin/marketplace.json", names)
                self.assertNotIn(".claude-plugin/plugin.json", names)

    def test_repeated_builds_are_byte_identical(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            one = build_archive("codex", Path(first)).read_bytes()
            two = build_archive("codex", Path(second)).read_bytes()
            self.assertEqual(one, two)
~~~

- [ ] **Step 2: Write failing privacy-scanner tests**

~~~python
# tests/test_public_safety.py
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import tomllib
import unittest

from scripts.check_public import scan_path


class PublicSafetyTests(unittest.TestCase):
    def test_detects_home_path_and_private_key(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            home_path = "/" + "Users/example/private-vault\n"
            key_header = "-----BEGIN " + "PRIVATE KEY-----\n"
            (root / "bad.txt").write_text(
                home_path + key_header + "synthetic-test-material\n",
                encoding="utf-8",
            )
            codes = {finding.code for finding in scan_path(root)}
            self.assertEqual(codes, {"absolute_home_path", "private_key"})

    def test_detects_machine_local_denied_term_without_echoing_it(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            denied = "Synthetic " + "Orchard LLC"
            (root / "bad.txt").write_text(denied + "\n", encoding="utf-8")
            findings = scan_path(root, denied_terms=(denied,))
            self.assertEqual([finding.code for finding in findings], ["denied_term"])
            self.assertNotIn(denied, findings[0].message)

    def test_rejects_filesystem_symlink_without_reading_its_target(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "scan-root"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text(
                "-----BEGIN " + "PRIVATE KEY-----\nsynthetic-test-material\n",
                encoding="utf-8",
            )
            (root / "linked.txt").symlink_to(outside)
            findings = scan_path(root)
            self.assertEqual([finding.code for finding in findings], ["symlink_entry"])

    def test_repository_sources_are_clean(self) -> None:
        self.assertEqual(scan_path(Path(".")), [])

    def test_runtime_has_no_network_client_imports(self) -> None:
        forbidden = {"aiohttp", "ftplib", "http", "requests", "smtplib", "socket", "urllib"}
        imported: set[str] = set()
        for path in Path("src/threadroot").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
        self.assertEqual(imported & forbidden, set())

    def test_runtime_dependency_list_is_empty(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["dependencies"], [])
~~~

- [ ] **Step 3: Run focused tests and confirm release modules are missing**

Run: `PYTHONPATH=src:. python -m unittest tests.test_release tests.test_public_safety -v`
Expected: FAIL because `scripts.build_release` and `scripts.check_public` do not exist.

- [ ] **Step 4: Implement deterministic host archives**

`build_release.py` exposes:

~~~python
HOST_MANIFESTS = {
    "claude": Path(".claude-plugin/plugin.json"),
    "codex": Path(".codex-plugin/plugin.json"),
}
COMMON_ROOTS = (
    Path("LICENSE"),
    Path("README.md"),
    Path("skills"),
    Path("templates"),
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
~~~

`build_archive` rejects hosts outside `HOST_MANIFESTS`, rejects symlinks anywhere in its selected inputs, discovers regular files under common roots in sorted POSIX-path order, and writes each `ZipInfo` with `ZIP_TIMESTAMP`, `create_system = 3`, UTF-8 flag, `external_attr = 0o100644 << 16`, empty extra/comment fields, and `ZIP_DEFLATED` at compression level `9`. Do not emit directory entries. Both archives include the canonical `.claude-plugin/marketplace.json`, which both hosts can import; each archive includes only its own native `plugin.json`. Archive paths are repository-relative, never absolute, and never contain `..`. The CLI accepts `--output` with default `dist` and builds both archives.

Read the canonical release version from `pyproject.toml` with `tomllib`; the packaging parity test proves every other copy matches it. Do not introduce another release-version constant. For v0 this produces `threadroot-claude-0.1.0.zip` and `threadroot-codex-0.1.0.zip`. Confirm that Task 1's `.gitignore` still excludes `dist/`.

- [ ] **Step 5: Implement source and artifact privacy scanning**

Define:

~~~python
@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int | None
    message: str
~~~

`scan_path` recursively scans text files and text members inside ZIP-compatible archives (including wheels) and tar archives (including source distributions). Detect archives by content with `zipfile.is_zipfile` and `tarfile.is_tarfile`, not filename alone. Walk the source filesystem without following symlinks; report every filesystem symlink as `symlink_entry` and never read its target. Skip only `.git`, `.venv`, `__pycache__`, and binary members. Report, without echoing the matched payload:

- `absolute_home_path` using a pattern assembled as `re.compile("/" + r"(?:Users|home)/[^/\s]+/")`.
- `private_key` using a PEM-header pattern assembled from separate string fragments so the scanner's own source does not contain the complete sentinel.
- `credential_assignment` for non-empty values assigned to names matching `api_key`, `access_token`, `client_secret`, `password`, or `secret`, case-insensitively.
- `denied_term` for a case-sensitive literal supplied through an optional machine-local denylist; never include the term in output.
- `symlink_entry` for any filesystem symlink encountered below a scanned source path.
- `path_escape` for archive members that are absolute, contain `..`, or are links whose targets escape the archive root.

The CLI accepts zero or more input paths and an optional `--denylist FILE`; zero paths means the current directory, and each non-empty denylist line is a literal private identity or organization term. It prints only findings sorted by relative file/member path, line number, and code, then exits `1` when findings exist. It must not print denylist contents or copy the denylist into an artifact. The clean-repository test scans the scanner, its tests, this plan, and all fixtures; there is no exact-file exemption. Building each synthetic sentinel from separate string fragments lets the positive test coexist with that self-scan.

- [ ] **Step 6: Configure complete source distributions**

`MANIFEST.in` includes `LICENSE`, `README.md`, `AGENTS.md`, `skills`, `templates`, both native manifest directories, `.claude-plugin/marketplace.json`, `docs`, and `scripts`. Exclude `.git`, `.dogfood`, build directories, bytecode, and `dist`. Configure setuptools package data only for data imported by the Python runtime; do not duplicate `skills` inside `src/threadroot`.

- [ ] **Step 7: Run release, privacy, and build checks**

Run: `PYTHONPATH=src:. python -m unittest tests.test_release tests.test_public_safety -v`
Expected: all focused tests PASS.

Run:

~~~bash
python -m pip install build
python -m build
threadroot_wheel_venv="$(mktemp -d)/venv"
python3 -m venv "$threadroot_wheel_venv"
"$threadroot_wheel_venv/bin/python" -m pip install dist/threadroot-0.1.0-py3-none-any.whl
"$threadroot_wheel_venv/bin/threadroot" --version
python scripts/build_release.py --output dist
python scripts/check_public.py .
python scripts/check_public.py dist
~~~

Expected: wheel, source distribution, and both host archives build; the installed console script prints `threadroot 0.1.0`; both scans exit `0`.

For a release candidate, bind an untracked machine-local file containing the maintainer's private identity and organization terms to `THREADROOT_PUBLIC_DENYLIST`, then run `python scripts/check_public.py --denylist "$THREADROOT_PUBLIC_DENYLIST" . dist`. The command must exit `0`, and neither the variable value nor file contents may enter logs or Git.

- [ ] **Step 8: Commit release tooling**

~~~bash
git add MANIFEST.in pyproject.toml scripts/build_release.py scripts/check_public.py tests/test_release.py tests/test_public_safety.py
git diff --cached --check
git commit -m "build: add reproducible public release artifacts"
~~~

### Task 11: Installation Documentation and CI Matrix

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `docs/testing.md`
- Modify: `MANIFEST.in`
- Modify: `README.md`
- Modify: `scripts/build_release.py`
- Modify: `tests/test_release.py`
- Create: `tests/test_documentation.py`

**Interfaces:**
- Consumes: all CLI commands, manifests, build scripts, safety boundaries, and acceptance commands.
- Produces: complete local/repository installation paths and automated macOS/Linux validation for Python 3.11–3.14.

- [ ] **Step 1: Write failing documentation-contract tests**

~~~python
# tests/test_documentation.py
from pathlib import Path
import unittest


class DocumentationTests(unittest.TestCase):
    def test_readme_documents_all_install_and_safety_paths(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        for phrase in (
            "Root your work across sessions.",
            "python -m pip install .",
            "threadroot-0.1.0-py3-none-any.whl",
            "threadroot-codex-0.1.0.zip",
            "OWNER/threadroot",
            "claude --plugin-dir",
            "claude plugin marketplace add",
            "codex plugin marketplace add",
            "codex plugin add threadroot@threadroot",
            "threadroot init",
            "threadroot adopt",
            "threadroot doctor",
            "pip uninstall threadroot",
            "plugin remove threadroot@threadroot",
            "--add-dir \"$SECOND_BRAIN_ROOT\"",
            "No telemetry",
            "user-owned",
        ):
            self.assertIn(phrase, readme)

    def test_security_doc_states_the_data_boundary(self) -> None:
        security = Path("SECURITY.md").read_text(encoding="utf-8")
        for phrase in ("Threat model", "Path containment", "Secrets", "Host data policy", "Reporting"):
            self.assertIn(phrase, security)

    def test_contributing_doc_has_a_public_safe_workflow(self) -> None:
        contributing = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        for phrase in ("Development", "Tests", "Pull requests", "Public/private boundary", "Apache-2.0"):
            self.assertIn(phrase, contributing)
~~~

- [ ] **Step 2: Run documentation tests and confirm the minimal README fails**

Run: `PYTHONPATH=src python -m unittest tests.test_documentation -v`
Expected: FAIL because installation and security documentation are incomplete.

- [ ] **Step 3: Expand `README.md` into the v0 entry point**

Replace the Task 1 README wholesale with the install-facing content below; remove its temporary relative links to repository-only design/plan files so release archives remain self-contained. Preserve no stale claims from the skeleton README. Use these sections in order:

1. Product name, tagline, and a two-paragraph explanation.
2. `What Threadroot owns` and `What you own` boundary table.
3. `Requirements`: Python 3.11+, macOS/Linux, supported host, optional Git.
4. `Install the CLI from a checkout`:

~~~bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
threadroot --version
~~~

5. `Install from release artifacts`, clearly stating that the wheel provides the CLI and the host archive provides the skills; users need both layers:

~~~bash
python -m pip install ./threadroot-0.1.0-py3-none-any.whl
claude --plugin-dir ./threadroot-claude-0.1.0.zip

python -m zipfile -e ./threadroot-codex-0.1.0.zip ./threadroot-codex-0.1.0
codex plugin marketplace add ./threadroot-codex-0.1.0
codex plugin add threadroot@threadroot
~~~

6. `Load the plugin for one Claude Code session`:

~~~bash
claude --plugin-dir "$PWD"
~~~

7. `Install through the local marketplace`:

~~~bash
claude plugin marketplace add . --scope user
claude plugin install threadroot@threadroot

codex plugin marketplace add .
codex plugin add threadroot@threadroot
~~~

8. `Install from a Git repository after a remote exists`, clearly labeling `OWNER/threadroot` as a value to replace rather than a live repository claim:

~~~bash
git clone https://github.com/OWNER/threadroot.git
cd threadroot
python -m pip install .
claude plugin marketplace add OWNER/threadroot --scope user
codex plugin marketplace add OWNER/threadroot
~~~

9. `Allow access to an external vault`, explaining that CLI filesystem access and host workspace permission are separate. Use `claude --add-dir "$SECOND_BRAIN_ROOT"` and `codex --add-dir "$SECOND_BRAIN_ROOT"` examples; never recommend disabling the sandbox or copying the vault into a code repository.
10. `Create or adopt a vault` with preview followed by explicit `--apply` examples.
11. `Skills` listing the exact nine names.
12. `Uninstall`, with `python -m pip uninstall threadroot`, `claude plugin remove threadroot@threadroot`, and `codex plugin remove threadroot@threadroot`; marketplace removal is optional and separate. State that none of these commands accepts a vault path or removes user data.
13. `Safety` beginning with `No telemetry` and explaining host data-policy boundaries.
14. `Development` with test, build, artifact, and public-scan commands.
15. `Contributing and security` linking root `CONTRIBUTING.md` and `SECURITY.md`.
16. `License` linking `LICENSE` and stating Apache-2.0 does not license user vault content or project trademarks.

Do not claim PyPI, marketplace-directory, hosted, Windows, MCP, or RAG availability.

- [ ] **Step 4: Write the security and testing guides**

`SECURITY.md` contains `Threat model`, `Trust boundaries`, `Path containment`, `Non-overwriting writes`, `Partial failures`, `Secrets`, `Host data policy`, `Dependency policy`, and `Reporting`. Explain that host workspace approval (such as `--add-dir`) grants the host—not Threadroot—filesystem capability and should be scoped to the vault only. State explicitly that v0 protects against malformed configuration and ordinary concurrent drift, but not a malicious or privileged local process that can replace filesystem entries between validation and use. Direct reports to GitHub's private vulnerability-reporting feature after a remote exists; until then, instruct reporters not to include secrets or private vault samples in a public issue.

`CONTRIBUTING.md` contains `Development`, `Tests`, `Pull requests`, `Public/private boundary`, and `License`. It explains the standard-library runtime boundary, test-first workflow, exact-path staging, synthetic-fixture rule, required public scan, and that submitted contributions are distributed under Apache-2.0. Do not add a CLA, DCO, governance model, or Code of Conduct in v0 without a concrete project need and maintainer decision.

Add `CONTRIBUTING.md` and `SECURITY.md` to `MANIFEST.in` now that both files exist, and extend the documentation test to assert both entries are present. The subsequent clean build and artifact scan prove the source distribution remains valid without making unit tests depend on a stale `dist/` directory.

Extend the release archive's common roots with `CONTRIBUTING.md`, `SECURITY.md`, and `docs/testing.md`, then extend `tests/test_release.py` to require all three in both host archives. Keep design specs and implementation plans repository-only so install artifacts stay focused.

`docs/testing.md` documents:

- `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Wheel/source/plugin artifact builds.
- Public-safety scans for source and `dist`.
- `claude plugin validate --strict .`.
- Disposable `CODEX_HOME` local marketplace validation.
- Optional machine-local denylist scanning for maintainer identities and organization names.
- Synthetic cross-host contract procedure from Task 12.
- Private dogfood rule: record only pass/fail and tool version, never vault path, note text, or generated diff.

- [ ] **Step 5: Add the exact CI workflow**

~~~yaml
name: ci

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.12", "3.13", "3.14"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install --upgrade pip build
      - run: python -m unittest discover -s tests -v
        env:
          PYTHONPATH: src:.
      - run: python -m build
      - run: python -m pip install --force-reinstall dist/threadroot-0.1.0-py3-none-any.whl
      - run: threadroot --version
      - run: python scripts/build_release.py --output dist
      - run: python scripts/check_public.py .
      - run: python scripts/check_public.py dist
~~~

Keep network use limited to checkout and installing build tooling; the Threadroot runtime and tests make no network request.

The pinned SHAs are the current official v7 releases at plan approval time; re-check them before implementation rather than copying an older major: [actions/checkout releases](https://github.com/actions/checkout/releases/latest) and [actions/setup-python releases](https://github.com/actions/setup-python/releases/latest).

- [ ] **Step 6: Run documentation, suite, and artifact checks**

Run: `PYTHONPATH=src:. python -m unittest tests.test_documentation -v`
Expected: documentation tests PASS.

Run:

~~~bash
PYTHONPATH=src:. python -m unittest discover -s tests -v
python -m build
python scripts/build_release.py --output dist
python scripts/check_public.py .
python scripts/check_public.py dist
~~~

Expected: all commands exit `0`.

- [ ] **Step 7: Commit public documentation and CI**

~~~bash
git add .github/workflows/ci.yml README.md CONTRIBUTING.md SECURITY.md MANIFEST.in docs/testing.md scripts/build_release.py tests/test_release.py tests/test_documentation.py
git diff --cached --check
git commit -m "docs: add installation security and CI guidance"
~~~

### Task 12: Structural Cross-Host Contract and Private Dogfood Gate

**Files:**
- Create: `scripts/check_contract.py`
- Create: `tests/test_contracts.py`
- Create: `tests/fixtures/contracts/uninstall-no-write.json`
- Modify: `docs/testing.md`
- Modify: `tests/fixtures/contracts/daily-lifecycle.json`
- Modify: `tests/fixtures/contracts/project-decision.json`
- Modify: `tests/test_skills.py`

**Interfaces:**
- Consumes: synthetic contract JSON, a pristine synthetic vault, and one post-run vault per host.
- Produces: `materialize_fixture(case, output)`, `snapshot(root) -> VaultSnapshot`, `validate_contract(case, before, after) -> list[ContractFailure]`, and repeatable uninstall/private-dogfood checklists.

- [ ] **Step 1: Write failing structural-contract tests**

~~~python
# tests/test_contracts.py
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_contract import validate_contract


class ContractTests(unittest.TestCase):
    def test_equivalent_prose_with_same_structure_passes(self) -> None:
        case = {
            "expected_writes": ["daily/2042-04-03.md"],
            "required_headings": {
                "daily/2042-04-03.md": ["Work Log", "Follow-up"]
            },
            "required_links": {},
            "forbidden_paths": ["secrets"],
        }
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            after = base / "after"
            (before / "daily").mkdir(parents=True)
            (after / "daily").mkdir(parents=True)
            (after / "daily/2042-04-03.md").write_text(
                "# 2042-04-03\n\n## Work Log\n\nDifferent prose.\n\n## Follow-up\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_contract(case, before, after), [])

    def test_unexpected_write_and_missing_heading_fail(self) -> None:
        case = {
            "expected_writes": ["daily/2042-04-03.md"],
            "required_headings": {"daily/2042-04-03.md": ["Work Log"]},
            "required_links": {},
            "forbidden_paths": ["secrets"],
        }
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            after = base / "after"
            before.mkdir()
            (after / "wiki").mkdir(parents=True)
            (after / "wiki/extra.md").write_text("unexpected\n", encoding="utf-8")
            codes = {failure.code for failure in validate_contract(case, before, after)}
            self.assertEqual(codes, {"missing_expected_write", "unexpected_write"})

    def test_no_write_contract_requires_byte_identity(self) -> None:
        case = {
            "expected_writes": [],
            "required_headings": {},
            "required_links": {},
            "forbidden_paths": ["."],
        }
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            after = base / "after"
            before.mkdir()
            after.mkdir()
            for root in (before, after):
                (root / "daily").mkdir()
                (root / "wiki/reviews").mkdir(parents=True)
                (root / "daily/2042-04-03.md").write_text(
                    "# 2042-04-03\n\nSynthetic note.\n", encoding="utf-8"
                )
            self.assertEqual(validate_contract(case, before, after), [])
            (after / "wiki/reviews").rmdir()
            codes = {failure.code for failure in validate_contract(case, before, after)}
            self.assertEqual(codes, {"forbidden_write", "unexpected_write"})
~~~

Add one focused case whose changed project page contains the required heading but omits its mapped decision link; assert the sole failure code is `missing_link`.

Add materialization tests for exact synthetic bytes, an already non-empty output, an absolute fixture path, a parent traversal, and a file/directory collision. Every rejected case must leave the output unchanged.

- [ ] **Step 2: Run the focused tests and confirm the checker is missing**

Run: `PYTHONPATH=src:. python -m unittest tests.test_contracts -v`
Expected: FAIL because `scripts.check_contract` does not exist.

- [ ] **Step 3: Implement structure-only comparison**

Define immutable `FileSnapshot(path, sha256, headings, document_links)`, `LinkSnapshot(path, target_sha256)`, `VaultSnapshot(files, directories, links)`, and `ContractFailure(code, path, message)`. Walk without following symlinks; record every relative directory path, hash each regular file's bytes, and hash rather than expose each symlink target. From decodable Markdown files, extract ATX headings with `re.match(r"^#{1,6}\s+(.+?)\s*$", line)` and normalized link destinations from both `[[target|label]]`/`[[target]]` wikilinks and ordinary Markdown links. Remove display labels, anchors, and a terminal `.md` before comparison, but do not resolve links outside the fixture root.

`materialize_fixture` accepts only a missing or empty explicit output directory. Validate every `fixture_directories` and `fixture_files` key as a relative POSIX path with no empty, `.` or `..` components; reject duplicate/file-directory conflicts. Create declared directories in sorted parent-first order and files with exclusive-create semantics. Never materialize `request`, `allowed_reads`, or any host output as vault content.

`validate_contract`:

1. Computes added, removed, kind-changed, and byte-changed relative paths across regular files, directories, and symlinks.
2. Allows changes only at `expected_writes`.
3. Requires every expected write to be added or byte-changed and to exist afterward.
4. Requires the `required_headings` key set to equal `expected_writes`, then checks each file against only the headings mapped to its path.
5. Requires every `required_links` key to name an expected write, then checks the normalized destinations mapped to that file.
6. Rejects any changed path equal to or below a `forbidden_paths` entry; the sole special value `"."` means the entire fixture root and is valid only in `forbidden_paths`.
7. Ignores prose equality; matching file paths, headings, required links, and safety outcomes define equivalence.
8. Returns failures sorted by code then path and never prints file contents.

Use stable failure codes `contract.invalid`, `missing_expected_write`, `missing_heading`, `missing_link`, `unexpected_write`, and `forbidden_write`. Reject malformed fixture schemas before comparing snapshots.

The command has two explicit modes: `materialize --case CASE --output DIRECTORY` and `validate --case CASE --before DIRECTORY --after DIRECTORY`. It prints only pass/fail plus relative paths and exits `1` on any validation or contract failure.

- [ ] **Step 4: Make all contract fixtures executable**

Add `fixture_files`, `fixture_directories`, and `forbidden_paths` to the two cross-host JSON cases. `allowed_reads` names semantic user-content reads; the validated `.second-brain/config.json` and filesystem metadata are always permitted setup reads. Across fixtures and expected outputs, use only the marker plus these synthetic content paths:

- `daily/2042-04-03.md`.
- `wiki/projects/orchard-cli/index.md`.
- `wiki/projects/orchard-cli/decisions/2042-04-03-json-storage.md`.
- `secrets/synthetic-do-not-read.md`.

Use this exact `fixture_directories` value in both cross-host cases so every parent, including the empty decisions directory, exists before a host run:

~~~json
[
  ".second-brain",
  "daily",
  "wiki",
  "wiki/projects",
  "wiki/projects/orchard-cli",
  "wiki/projects/orchard-cli/decisions",
  "wiki/tech",
  "wiki/reviews",
  "secrets"
]
~~~

Use this exact `fixture_files` object for `daily-lifecycle.json`:

~~~json
{
  ".second-brain/config.json": "{\n  \"schema_version\": 1,\n  \"paths\": {\n    \"daily\": \"daily\",\n    \"projects\": \"wiki/projects\",\n    \"knowledge\": \"wiki/tech\",\n    \"reviews\": \"wiki/reviews\"\n  }\n}\n",
  "daily/2042-04-03.md": "# 2042-04-03\n\n## Focus\n\n- Complete the parser task.\n\n## Work Log\n\nThe parser task is in progress.\n\n## Decisions\n\n## Follow-up\n\n- Prepare tomorrow's focus.\n",
  "wiki/projects/orchard-cli/index.md": "# Orchard CLI\n\n## Current Status\n\nParser implementation is active.\n\n## Pending\n\n- [ ] Complete the parser task.\n\n## Recent Activity\n\n- Project created.\n\n## Lessons Learned\n\n## Key Decisions\n",
  "secrets/synthetic-do-not-read.md": "# Synthetic Sentinel\n\nThis fixture must remain unchanged.\n"
}
~~~

Use this exact `fixture_files` object for `project-decision.json`:

~~~json
{
  ".second-brain/config.json": "{\n  \"schema_version\": 1,\n  \"paths\": {\n    \"daily\": \"daily\",\n    \"projects\": \"wiki/projects\",\n    \"knowledge\": \"wiki/tech\",\n    \"reviews\": \"wiki/reviews\"\n  }\n}\n",
  "wiki/projects/orchard-cli/index.md": "# Orchard CLI\n\n## Current Status\n\nStorage selection is pending.\n\n## Pending\n\n- [ ] Choose a storage format.\n\n## Recent Activity\n\n- Compared local storage options.\n\n## Lessons Learned\n\n## Key Decisions\n",
  "secrets/synthetic-do-not-read.md": "# Synthetic Sentinel\n\nThis fixture must remain unchanged.\n"
}
~~~

Set `forbidden_paths` to `["secrets"]` in both cases. The daily lifecycle case allows exactly the daily and project-page writes. The project-decision case allows exactly the absent ADR and existing project-page writes. Neither case allows deletion or any change below `secrets`; the empty decisions directory keeps ADR parent creation out of `expected_writes`.

Update the Task 7 fixture-schema assertion in `tests/test_skills.py` so the final exact key set is the original seven keys plus `fixture_files`, `fixture_directories`, and `forbidden_paths`. Apply the same exact-schema assertion to all three contract fixtures.

Create `uninstall-no-write.json` with the same seven base keys plus the three materialization keys. Use request `Remove the Threadroot installation without changing this vault.`, empty `allowed_reads`, empty `expected_writes`, empty `required_headings`, empty `required_links`, forbidden actions `modify vault` and `delete vault content`, and `forbidden_paths: ["."]`. This case is for installation-state removal only, not a model prompt. Its exact materialization fields are:

~~~json
{
  "fixture_directories": [
    ".second-brain",
    "daily",
    "wiki",
    "wiki/projects",
    "wiki/tech",
    "wiki/reviews"
  ],
  "fixture_files": {
    ".second-brain/config.json": "{\n  \"schema_version\": 1,\n  \"paths\": {\n    \"daily\": \"daily\",\n    \"projects\": \"wiki/projects\",\n    \"knowledge\": \"wiki/tech\",\n    \"reviews\": \"wiki/reviews\"\n  }\n}\n",
    "daily/2042-04-03.md": "# 2042-04-03\n\n## Work Log\n\nSynthetic note.\n"
  },
  "forbidden_paths": ["."]
}
~~~

- [ ] **Step 5: Run structural tests and the full automated gate**

Run: `PYTHONPATH=src:. python -m unittest tests.test_contracts -v`
Expected: focused tests PASS.

Run:

~~~bash
PYTHONPATH=src:. python -m unittest discover -s tests -v
python -m build
python scripts/build_release.py --output dist
python scripts/check_public.py .
python scripts/check_public.py dist
git diff --check
~~~

Expected: all tests and artifact checks pass with no whitespace errors.

- [ ] **Step 6: Perform synthetic cross-host validation**

After obtaining explicit authorization to launch the installed hosts and incur their normal model/network usage, follow `docs/testing.md` to materialize each fixture once below `.dogfood/`, then copy it into pristine, Claude-result, and Codex-result directories. Load the local plugin in each host, issue the exact fixture request, and run `scripts/check_contract.py validate` from pristine to each result. Compare the two result snapshots structurally; prose may differ.

Acceptance requires both hosts to:

- Touch only expected write paths.
- Preserve the `secrets` sentinel and all unrelated bytes.
- Produce the required headings and backlinks.
- Stop before commit, push, deletion, bulk rewrite, or an unapproved apply.

Do not commit prompts containing real context, host transcripts, generated vaults, paths, or diffs.

- [ ] **Step 7: Perform private-vault dogfood**

Against a user-authorized private vault:

1. Bind the user-selected path to `THREADROOT_DOGFOOD_VAULT`, run `threadroot doctor --vault "$THREADROOT_DOGFOOD_VAULT"`, and confirm it is read-only.
2. If no marker exists, run `threadroot adopt --vault "$THREADROOT_DOGFOOD_VAULT"` without `--apply` and inspect the full preview.
3. Apply adoption only after separate explicit confirmation.
4. Run one complete morning-review → recording → daily-wrap-up → weekly-review cycle.
5. Record outside this public repository only: Threadroot version, host version, pass/fail, issue codes, and remediation outcome.

Any private path, note content, fixture, transcript, or diff in the public worktree fails the gate.

- [ ] **Step 8: Verify uninstall is vault-neutral**

Use one `mktemp -d` root containing a virtual environment, extracted host archives, isolated host configuration, a synthetic vault, and a pristine vault copy. Run this complete setup, removal, and comparison sequence after building `dist`:

~~~bash
threadroot_uninstall_root="$(mktemp -d)"
threadroot_claude_bundle="$threadroot_uninstall_root/claude-marketplace"
threadroot_codex_bundle="$threadroot_uninstall_root/codex-marketplace"
threadroot_claude_config="$threadroot_uninstall_root/claude-config"
threadroot_codex_config="$threadroot_uninstall_root/codex-config"

python3 -m venv "$threadroot_uninstall_root/venv"
"$threadroot_uninstall_root/venv/bin/python" -m pip install dist/threadroot-0.1.0-py3-none-any.whl
"$threadroot_uninstall_root/venv/bin/threadroot" init --vault "$threadroot_uninstall_root/vault" --apply
cp -R "$threadroot_uninstall_root/vault" "$threadroot_uninstall_root/pristine"

python -m zipfile -e dist/threadroot-claude-0.1.0.zip "$threadroot_claude_bundle"
python -m zipfile -e dist/threadroot-codex-0.1.0.zip "$threadroot_codex_bundle"
CLAUDE_CONFIG_DIR="$threadroot_claude_config" claude plugin marketplace add "$threadroot_claude_bundle" --scope user
CLAUDE_CONFIG_DIR="$threadroot_claude_config" claude plugin install threadroot@threadroot --scope user
CLAUDE_CONFIG_DIR="$threadroot_claude_config" claude plugin list --json
CODEX_HOME="$threadroot_codex_config" codex plugin marketplace add "$threadroot_codex_bundle" --json
CODEX_HOME="$threadroot_codex_config" codex plugin add threadroot@threadroot --json
CODEX_HOME="$threadroot_codex_config" codex plugin list --json

"$threadroot_uninstall_root/venv/bin/python" -m pip uninstall -y threadroot
CLAUDE_CONFIG_DIR="$threadroot_claude_config" claude plugin remove threadroot@threadroot --scope user
CLAUDE_CONFIG_DIR="$threadroot_claude_config" claude plugin marketplace remove threadroot --scope user
CODEX_HOME="$threadroot_codex_config" codex plugin remove threadroot@threadroot --json
CODEX_HOME="$threadroot_codex_config" codex plugin marketplace remove threadroot --json
python scripts/check_contract.py validate \
  --case tests/fixtures/contracts/uninstall-no-write.json \
  --before "$threadroot_uninstall_root/pristine" \
  --after "$threadroot_uninstall_root/vault"
~~~

Assert that both JSON list results contain an installed `threadroot` entry before removal, then require every removal command and the final contract check to exit `0`. Document this sequence in `docs/testing.md`. This test may remove only disposable installation state created under `threadroot_uninstall_root`; it must never use the vault as an uninstall target. Leave the temporary root for operating-system cleanup instead of using a broad recursive deletion command.

- [ ] **Step 9: Commit the contract harness**

~~~bash
git add scripts/check_contract.py tests/test_contracts.py tests/test_skills.py tests/fixtures/contracts/daily-lifecycle.json tests/fixtures/contracts/project-decision.json tests/fixtures/contracts/uninstall-no-write.json docs/testing.md
git diff --cached --check
git commit -m "test: add cross-host structural contract gate"
~~~

- [ ] **Step 10: Run the final v0 verification**

Run:

~~~bash
PYTHONPATH=src:. python -m unittest discover -s tests -v
python -m build
python scripts/build_release.py --output dist
python scripts/check_public.py .
python scripts/check_public.py dist
claude plugin validate --strict .
git status --short
~~~

Expected: tests, builds, scans, and Claude validation exit `0`; `git status --short` is empty. Repeat disposable-Codex validation from Task 9 and require successful JSON.

Do not tag, push, publish, create a remote, submit to a marketplace, or claim private dogfood success unless those steps were separately authorized and completed.

## Acceptance-Criteria Coverage

| Spec criterion | Implemented and proved by |
|---|---|
| Installable Python 3.11+ command | Tasks 1, 5, and 11 |
| Pure `init` preview and exact non-overwriting apply | Task 3 |
| Minimal `adopt` preview/apply | Task 4 |
| Fail-closed config and path handling | Tasks 2 and 5 |
| Read-only `doctor` | Task 5 |
| One shared skill tree for both hosts | Tasks 6–9 |
| Cross-host structural equivalence | Task 12 |
| No private content, telemetry, or network dependency | Tasks 6, 10, and 12 |
| Uninstall leaves the vault unchanged | Tasks 10–12 via archive inspection and before/after snapshots |

## Execution Checkpoints

- Tasks 1–5 produce a complete deterministic CLI and are the first review checkpoint.
- Tasks 6–8 produce the complete provider-neutral workflow set and are the second review checkpoint.
- Tasks 9–11 produce installable artifacts, documentation, and CI and are the third review checkpoint.
- Task 12 is the release-candidate verification checkpoint; private dogfood remains separately authorized.
