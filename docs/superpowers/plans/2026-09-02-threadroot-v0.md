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

### Task 13: Final-Review Safety Fix Wave

**Execution boundary:** This is the active SDD final review's single fix wave. The same final-fix implementer executes every step group below, with no new workspace, plan, subagent, or intermediate reviewer. Commit groups are checkpoints within this one task, not independent SDD tasks. After the full wave, the controller conducts exactly one scoped re-review against the final-review findings and directly affected mechanisms. Do not restart Tasks 1–12 or their host/private-vault procedures. This task supersedes their missing-file creation instructions where they conflict with the approved exclusive-claim design.

**Authority:** `docs/superpowers/specs/2026-09-02-threadroot-v0-design.md`, approved at commit `fe0ff4938dcb2a4f009d0ed623a380be1c84dc9c`. The ignored final-fix brief and final-fix report record the review findings and authorizations. Read repository `AGENTS.md` before execution. Use systematic-debugging for root-cause confirmation, test-driven-development for observable behavior, writing-skills and skill-creator before changing shared skills, and verification-before-completion before commits. The single-implementer constraint overrides skill suggestions to delegate. No new model call or network authorization follows from this plan.

**Global constraints restated for this task:** Python 3.11–3.14, macOS/Linux, runtime standard library only, empty runtime dependency list, existing schema version `1`, plugin/version `threadroot` / `0.1.0`. The CLI receives no note bytes, `claim` creates no parents, and semantic edits remain host-native. Do not add migration, journals, expected hashes, MCP, RAG, telemetry, networking, Windows, marketplace submission, or a new runtime Markdown parser. Malicious replacement of validated filesystem entries between validation and use remains outside the threat model. Preserve user changes; no private vault access, push, tag, publish, remote creation, or marketplace submission. All local document/code edits use the active patch mechanism. Ignore unrelated deferred scanner work.

**File responsibility map:** Line references describe the spec-update baseline; locate named definitions again before editing.

| Exact path | Responsibility and planned change |
|---|---|
| `src/threadroot/paths.py` | `resolve_path:28`, `ensure_within:47`, `find_upward:61`, pointer helpers:73–133; safe literal/I/O translation, lexical/resolved secrets rejection, pointer exclusion, unique claim-root containment |
| `src/threadroot/config.py` | `load_config:58`; reject marker/configured secrets paths before content reads, disallow configured marker namespace |
| `src/threadroot/operations.py` | `_is_initialized:64`, setup planners:85/150, `apply_plan:275`, `write_default_pointer:341`, runners:391/470/587; preserve codes, pointer preflights, claim plan/apply, doctor remediation |
| `src/threadroot/results.py` | Extend only `CommandName` with `claim`; preserve result fields, action/status literals and exit values |
| `src/threadroot/cli.py` | Parser:21, `execute:35`, `main:96`; claim syntax/dispatch and sanitized structured boundary errors |
| `tests/test_final_safety.py` | Create: synthetic path, I/O, init-code, pointer-overlap/cleanup, and doctor regressions |
| `tests/test_claim.py` | Create: claim planning, exclusive apply, CLI, containment, collision, and privacy regressions |
| `tests/skill_contract.py` | Preserve existing contract parser; add named claim invariant keys and a test-only metadata event-trace validator |
| `tests/test_skills.py` | Exact command inventories/invariants, mutations, and existing workflow contracts |
| `tests/test_claim_workflows.py` | Create: executable response/trace rejection oracles and all-five-skill inventory/invariant tests; never claim these simulate a model |
| `skills/README.md` | Shared claim–verify–native-edit protocol and failure behavior |
| `skills/recording/SKILL.md` | Claim missing authorized daily or separately approved knowledge files; preserve daily-only routing when project missing |
| `skills/daily-wrap-up/SKILL.md` | Claim missing daily only after existing direct-creation gate |
| `skills/weekly-review/SKILL.md` | Claim missing review only; retain single-review write set |
| `skills/project-kickoff/SKILL.md` | Claim project page; omit outside-vault adapter without independently exclusive native creation; retain complete-preview gate |
| `skills/decision-log/SKILL.md` | Claim absent ADR; preserve existing matching-content no-op only when observed before claiming, and retain backlink/supersession gates |
| `scripts/check_contract.py` | `_markdown_structure:286`; fence-aware structural extraction, ordinary ATX closing hashes |
| `tests/test_contracts.py` | Fenced decoys, closing hashes, and unchanged prose/hash contract |
| `README.md`, `SECURITY.md`, `docs/testing.md`, `AGENTS.md` | Public command, pointer, privacy, concurrency, workflow, and verification contract consistency |
| `tests/test_documentation.py`, `tests/test_packaging.py`, `tests/test_release.py` | Existing documentation/manifest/build verification; extend only observable command/content packaging coverage if necessary |
| `.superpowers/sdd/2026-09-02-threadroot-v0/final-fix-report.md` | Ignored execution evidence, RED/GREEN commands, commit hashes and final limitations |
| `.superpowers/sdd/2026-09-02-threadroot-v0/task-12-report.md`, `.superpowers/sdd/2026-09-02-threadroot-v0/progress.md` | Ignored historical-summary reconciliation and Task 12/13 ledger status; never stage |

**Interfaces and stable results:** Existing signatures remain unchanged unless explicitly extended here. `Path`, `Mapping`, `Sequence`, `VaultConfig`, `PlannedChange`, `Change`, `Issue`, `CommandResult`, `ThreadrootError`, and `ExitCode` are the existing pathlib/collections/config/operations/results types. New tests import these concrete names; no runtime protocol interpreter is introduced.

| Producer | Exact signature |
|---|---|
| New path helper | `ensure_outside_secrets(root: Path, relative: str \| Path) -> Path` |
| New pointer validator | `validate_default_pointer(vault: Path, pointer: Path) -> Path` |
| New claim path validator | `ensure_claim_target(root: Path, relative: str, content_paths: Mapping[str, str]) -> Path` |
| New claim planner | `plan_claim(vault: Path, relative: str) -> tuple[PlannedChange, ...]` |
| New apply precondition | `_validate_claim(vault: Path, change: PlannedChange) -> None` |
| New command runner | `run_claim(vault: Path, relative: str, apply: bool) -> CommandResult` |
| Existing config reader | `load_config(root: Path) -> VaultConfig` |
| Existing setup runner | `run_init(vault: Path, apply: bool, set_default: bool, environ: Mapping[str, str], home: Path) -> CommandResult` |
| Existing adoption runner | `run_adopt(vault: Path, apply: bool, set_default: bool, environ: Mapping[str, str], home: Path) -> CommandResult` |
| Existing doctor runner | `run_doctor(vault: Path) -> CommandResult` |
| Existing plan application | `apply_plan(command: CommandName, vault: Path, plan: Sequence[PlannedChange]) -> CommandResult` |
| Existing pointer writer | `write_default_pointer(vault: Path, environ: Mapping[str, str], home: Path) -> None` |
| Existing root resolver | `resolve_vault(explicit: str \| Path \| None, cwd: Path, environ: Mapping[str, str], home: Path) -> Path` |
| Existing CLI dispatch | `execute(args: argparse.Namespace, cwd: Path, environ: Mapping[str, str], home: Path) -> CommandResult` |
| Extended doctor result helper | `_doctor_result(root: Path, issues: Sequence[Issue], *, unsafe: bool = False, error_exit: ExitCode \| None = None) -> CommandResult` |
| New doctor message helper | `_doctor_issue(issue: Issue) -> Issue` |
| New verification-only fence helper | `_markdown_visible_lines(text: str) -> list[str]` |
| New test-only trace helper | `validate_claim_trace(events: Sequence[Mapping[str, object]], *, expected_vault: str = "/synthetic/vault", expected_path: str = "daily/2042-04-03.md") -> tuple[str, ...]` |

The GREEN steps define the new interfaces' algorithms below. Keep `Change(action, path, status)` with `planned`, `completed`, `unexecuted`; claim uses `create_file`. Preserve the exact JSON keys `ok`, `command`, `applied`, `vault`, `changes`, `issues`; `exit_code` remains internal. Preview/planning failures have `applied=false`; a failure inside `apply_plan` has `applied=true`, completed/unexecuted changes, and visible state. Diagnostics never interpolate raw exceptions or an unvalidated path. Only the `vault` field/renderer's explicit root display may contain the resolved absolute root; pointer diagnostics use `machine-default-pointer`.

| Trigger | Exit / issue code |
|---|---|
| Successful preview/apply | `0`, no error issue |
| Missing required CLI argument, unsupported/abbreviated flag, note-content argument | `2` / `usage.invalid` |
| Missing/unreadable/malformed root/config input | `3` / existing `vault.unresolved`, `config.invalid`, `config.unsupported_version`, `config.path_invalid` |
| Absolute/traversing/NUL/escaping/secrets/marker claim path, ambiguous content root, unsafe pointer | `4` / `path.unsafe` |
| Safe claim target already exists at planning, including empty file or dangling symlink | `5` / `target.conflict` |
| Claim parent absent or not a directory at planning | `6` / `filesystem.failed` |
| Target or safe parent changes after planning; exclusive open collision | `6` / `target.drifted` |
| Ordinary metadata/resolution/open/write/replace I/O failure | `6` / `filesystem.failed` |

Unsafe revalidation retains exit `4`, including in `init`; it is never flattened to `3` or a generic drift. Missing config/readability failures remain `3`; directory enumeration or resolution `PermissionError` is an operation failure `6`. Keep prior setup-specific conflict semantics where this task does not change them.

#### Group A — Path, secrets, I/O, and init error boundaries

- [ ] **A1: Reproduce and record the current boundary failures without edits.** Read `paths.py`, `config.py`, `_is_initialized`, setup runners, and `cli.execute`. Record these root causes in the ignored final-fix report: raw `ValueError` from NUL; ordinary resolution `OSError` re-raised or swallowed by the stat probe; unguarded setup `resolve`/`iterdir`; `_is_initialized` catches every `ThreadrootError` as configuration invalidity; marker containment permits a symlink into an internal `secrets` directory. Run `git status --short` and `PYTHONPATH=src:. python3 -m unittest tests.test_paths tests.test_config tests.test_operations tests.test_cli -v` as the baseline.

- [ ] **A2: Write the path regressions in `tests/test_final_safety.py`.** Use this complete initial class and append all four A5 test methods and its listed additional rows now, before A3/A4. All content is synthetic. Tests assert issue values and absence of content opens, rather than only checking a message substring.

~~~python
import json
import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from threadroot.cli import build_parser, execute, render_json
from threadroot.config import config_text, load_config
from threadroot.operations import run_init, run_adopt, run_doctor, write_default_pointer
from threadroot.paths import resolve_path, find_upward
from threadroot.results import ExitCode, ThreadrootError


class PathBoundaryTests(unittest.TestCase):
    def test_nul_configured_path_is_structured_unsafe(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".second-brain").mkdir()
            document = json.loads(config_text())
            document["paths"]["daily"] = "daily\x00bad"
            (root / ".second-brain/config.json").write_text(json.dumps(document))
            with self.assertRaises(ThreadrootError) as caught:
                load_config(root)
            self.assertEqual((caught.exception.exit_code, caught.exception.code),
                             (ExitCode.UNSAFE_PATH, "path.unsafe"))

    def test_secret_marker_is_rejected_before_open(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "secrets").mkdir()
            (root / "secrets/config.json").write_text(config_text())
            (root / ".second-brain").mkdir()
            (root / ".second-brain/config.json").symlink_to(root / "secrets/config.json")
            with patch.object(Path, "read_text", side_effect=AssertionError("content opened")) as read:
                with self.assertRaises(ThreadrootError) as caught:
                    load_config(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)
                read.assert_not_called()

    def test_init_keeps_unsafe_exit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".second-brain").mkdir()
            document = json.loads(config_text())
            document["paths"]["daily"] = "../outside"
            (root / ".second-brain/config.json").write_text(json.dumps(document))
            result = run_init(root, False, False, {}, root / "unused-home")
            self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)

    def test_init_preview_permission_failure_is_structured(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(Path, "iterdir", side_effect=PermissionError("synthetic I/O")):
                result = run_init(root, False, False, {}, root / "unused-home")
            self.assertEqual((result.exit_code, result.issues[0].code),
                             (ExitCode.IO_OR_DRIFT, "filesystem.failed"))
            self.assertFalse(result.applied)
            self.assertEqual(result.changes, ())

    def test_resolution_io_failure_is_structured_at_api_and_cli(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            failure = OSError(errno.EIO, "synthetic resolution failure", str(root / "opaque"))
            with patch.object(Path, "resolve", side_effect=failure):
                with self.assertRaises(ThreadrootError) as caught:
                    resolve_path(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.IO_OR_DRIFT)
                args = build_parser().parse_args(["doctor", "--vault", str(root), "--json"])
                result = execute(args, root, {}, root)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertNotIn(str(root), json.dumps(result.to_dict()["issues"]))
            self.assertNotIn("Traceback", render_json(result))
~~~

- [ ] **A3: Confirm RED separately for each blocker.** Run `PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PathBoundaryTests -v`. Expected failures: raw NUL/resolution/enumeration errors, secret marker opens, and init returning `3` instead of `4`. Record the individual failing method and actual exception/assertion. Do not accept missing imports, syntax errors, or a broken fixture as the intended RED.

- [ ] **A4: Implement minimal path/operation translations.** Keep existing modules. Reject NUL before pathlib normalization and translate `ValueError` only around path construction/resolution as `path.unsafe`. In `resolve_path`, translate `RuntimeError`/`ELOOP` to unsafe, non-ENOENT/non-ENOTDIR `OSError` to `filesystem.failed`; ignore only missing/not-directory from the optional non-strict stat probe. Preserve strict missing failures for the caller's precondition classification. Do not swallow ordinary I/O. Use this helper and call it before any marker/content read in `load_config`, `find_upward`, adopted-layout discovery, and doctor:

~~~python
def ensure_outside_secrets(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if "secrets" in candidate.parts:
        raise _unsafe_path()
    resolved = ensure_within(root, relative)
    resolved_root = resolve_path(root)
    if "secrets" in resolved.relative_to(resolved_root).parts:
        raise _unsafe_path()
    return resolved
~~~

For config values, additionally reject lexical `.second-brain` as the first component and resolved paths at/below the resolved marker directory. Do not ban the marker itself from marker validation. `find_upward` must perform the safety check before `is_file` or content access when the candidate marker exists; use lexical existence without opening content. Resolve the selected root before comparing vault-relative components; an unrelated absolute ancestor named `secrets` is not a configured vault component.

Move setup root resolution inside guarded boundaries. At public operation and `cli.execute` boundaries convert uncategorized ordinary `OSError` to a constant-message `ThreadrootError(ExitCode.IO_OR_DRIFT, "filesystem.failed", "A filesystem operation failed; check directory access and retry.")` and the existing `CommandResult`. Never print `str(error)`. In `_is_initialized`, translate only `error.exit_code == ExitCode.CONFIG` to `_config_path_invalid()`; re-raise unsafe/I/O errors unchanged. Preserve `config.invalid` for actual marker decoding/readability failures. `_doctor_result` gains keyword `error_exit: ExitCode | None = None` after its existing `unsafe` keyword so resolution/operation failures preserve `6`; existing calls continue to work. Root-resolution errors returned by `execute` keep the original exit. `main` must sanitize argparse errors (do not echo unknown raw arguments) while retaining exit `2` and the existing stderr usage-error behavior; parsed commands with `--json` continue returning one structured object.

- [ ] **A5: Verify the boundary expansion cases written in A2.** These are the four concrete test methods A2 appends to `PathBoundaryTests`; they must already have participated in A3's RED run before A4:

~~~python
    def test_secret_configured_paths_are_rejected(self):
        for relative in ("secrets/daily", "wiki/secrets/daily", ".second-brain/content"):
            with self.subTest(relative=relative), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                (root / ".second-brain").mkdir()
                marker = root / ".second-brain/config.json"
                document = json.loads(config_text())
                document["paths"]["daily"] = relative
                marker.write_text(json.dumps(document))
                real_read = Path.read_text
                def safe_read(path, *args, **kwargs):
                    self.assertEqual(path, marker)
                    return real_read(path, *args, **kwargs)
                with patch.object(Path, "read_text", safe_read):
                    with self.assertRaises(ThreadrootError) as caught:
                        load_config(root)
                    self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)

    def test_upward_secret_marker_is_never_opened(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "secrets").mkdir()
            (root / "secrets/config.json").write_text(config_text())
            (root / ".second-brain").symlink_to(root / "secrets", target_is_directory=True)
            with patch.object(Path, "read_text", side_effect=AssertionError("content opened")) as read:
                with self.assertRaises(ThreadrootError) as caught:
                    find_upward(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)
                read.assert_not_called()

    def test_path_probe_io_is_not_swallowed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(Path, "resolve", return_value=root), patch.object(
                Path, "stat", side_effect=OSError(errno.EIO, "synthetic probe")
            ):
                with self.assertRaises(ThreadrootError) as caught:
                    resolve_path(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.IO_OR_DRIFT)

    def test_cli_invalid_literal_is_private(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for command in ("init", "adopt", "doctor"):
                with self.subTest(command=command):
                    args = build_parser().parse_args([command, "--vault", "bad\x00root", "--json"])
                    result = execute(args, root, {}, root)
                    self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                    issues = json.dumps(result.to_dict()["issues"])
                    self.assertNotIn(str(root), issues)
                    self.assertNotIn("bad", issues)
~~~

Also extend the configured-path test with a `daily` symlink into `secrets/daily` and `daily-secrets` as an allowed negative control; the existing escaping-marker regression remains required. Run each command before and after its corresponding minimal correction, recording already-GREEN cases honestly:

~~~bash
PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PathBoundaryTests.test_secret_configured_paths_are_rejected -v
PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PathBoundaryTests.test_upward_secret_marker_is_never_opened -v
PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PathBoundaryTests.test_path_probe_io_is_not_swallowed -v
PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PathBoundaryTests.test_cli_invalid_literal_is_private -v
PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PathBoundaryTests tests.test_paths tests.test_config tests.test_operations tests.test_cli -v
~~~

- [ ] **A6: Commit the path/error fix.**

~~~bash
git add -- src/threadroot/paths.py src/threadroot/config.py src/threadroot/operations.py src/threadroot/cli.py tests/test_final_safety.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: preserve safe path and filesystem error boundaries"
~~~

Require exactly those five staged paths; if a concurrent session staged unrelated files, preserve their edits and remove only their index entries before committing. Every subsequent commit block has the same exact-staged-set rule.

#### Group B — Default-pointer vault exclusion and owned temporary cleanup

- [ ] **B1: Write all pointer regressions before changing the writer.** Add `PointerSafetyTests` to `tests/test_final_safety.py`, including the five B4 methods and cleanup code below, before B2/B3. This representative test directly exercises the critical overwrite route:

~~~python
class PointerSafetyTests(unittest.TestCase):
    def test_direct_and_parent_symlink_overlap_are_zero_write(self):
        for operation in (run_init, run_adopt):
            for apply in (False, True):
                for symlink_parent in (False, True):
                    with self.subTest(operation=operation.__name__, apply=apply,
                                      symlink_parent=symlink_parent), TemporaryDirectory() as temporary:
                        base = Path(temporary).resolve()
                        vault = base / "vault"
                        self.assertTrue(run_init(vault, True, False, {}, base / "home").ok)
                        (vault / "threadroot").mkdir()
                        protected = vault / "threadroot/config.json"
                        protected.write_bytes(b"synthetic vault content")
                        xdg = base / "xdg"
                        if symlink_parent:
                            xdg.mkdir()
                            (xdg / "threadroot").symlink_to(vault / "threadroot", target_is_directory=True)
                        else:
                            xdg = vault
                        before = protected.read_bytes(), protected.stat().st_mtime_ns
                        with patch("threadroot.operations.os.replace") as replace:
                            result = operation(vault, apply, True,
                                               {"XDG_CONFIG_HOME": str(xdg)}, base / "home")
                        self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                        self.assertFalse(result.applied)
                        self.assertEqual(result.changes, ())
                        replace.assert_not_called()
                        self.assertEqual(before, (protected.read_bytes(), protected.stat().st_mtime_ns))
~~~

- [ ] **B2: Confirm the critical RED.** Run `PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PointerSafetyTests -v`, including B4's already-written revalidation cases. The baseline incorrectly reports success or reaches `os.replace`; the failure must be the missing unsafe rejection, not fixture setup. Keep `os.replace` mocked in the overlap case so the synthetic protected note is never actually overwritten during RED. Revalidation tests may report the explicitly missing `validate_default_pointer` capability until B3 adds it; cleanup may already pass and must be recorded honestly.

- [ ] **B3: Implement the pointer exclusion interface.**

~~~python
def validate_default_pointer(vault: Path, pointer: Path) -> Path:
    root = resolve_path(vault)
    destination = resolve_path(pointer)
    if destination == root or root in destination.parents:
        raise ThreadrootError(
            ExitCode.UNSAFE_PATH, "path.unsafe",
            "Default pointer must stay outside the vault; choose another config directory.",
            "machine-default-pointer",
        )
    return pointer
~~~

Call it while constructing both setup runners' pointer plans before any mutation. For apply call it again immediately before `apply_plan`, then inside `write_default_pointer` before `pointer.parent.mkdir`, before `mkstemp`, and immediately before `os.replace`. Resolve existing parent symlinks each time. Update both runners' pointer-stage exception handling to retain `ThreadrootError.exit_code` while reporting completed vault changes and an unexecuted pointer; ordinary `OSError` remains `6`. Preserve the existing `try/finally` descriptor and owned-temp cleanup; never enumerate/delete arbitrary `.tmp` files. A newly detected overlap after prior vault writes is visible partial state, while an initially unsafe destination is zero-write.

- [ ] **B4: Verify revalidation and cleanup regressions written in B1.** The methods are `test_initial_overlap_does_not_create_vault_or_pointer_parents`, `test_pointer_destination_equal_to_vault_is_unsafe`, `test_apply_revalidates_before_first_write`, `test_writer_revalidates_before_mkdir_and_replace`, and `test_replace_failure_preserves_old_pointer_and_cleans_only_owned_temp`. Use a missing init root under `base/xdg/threadroot/config.json` for equality; patch planned destination changes through `validate_default_pointer` call side effects to test call-boundary rejection without simulating a malicious process. Patch `Path.mkdir`, `tempfile.mkstemp`, and `os.replace` at their `threadroot.operations` lookup sites and assert mutation order; a rejection at the first writer check must call none of them. For the cleanup case create an old machine pointer outside the vault plus unrelated `keep.tmp`, patch only `os.replace` to raise `OSError`, call the real writer, and assert old bytes/mtime and `keep.tmp` survive while its one created temporary is gone. Never delete the old pointer to make the test pass.

~~~python
    def test_replace_failure_preserves_old_pointer_and_cleans_only_owned_temp(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            vault.mkdir()
            pointer = base / "xdg/threadroot/config.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_bytes(b'{"default_vault":"/synthetic/previous"}\n')
            sentinel = pointer.parent / "keep.tmp"
            sentinel.write_bytes(b"unrelated")
            before = pointer.read_bytes(), pointer.stat().st_mtime_ns
            with patch("threadroot.operations.os.replace", side_effect=OSError("synthetic replace")):
                with self.assertRaises(OSError):
                    write_default_pointer(vault, {"XDG_CONFIG_HOME": str(base / "xdg")}, base / "home")
            self.assertEqual(before, (pointer.read_bytes(), pointer.stat().st_mtime_ns))
            self.assertEqual({"config.json", "keep.tmp"}, {p.name for p in pointer.parent.iterdir()})
            self.assertEqual(sentinel.read_bytes(), b"unrelated")
~~~

Run `PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.PointerSafetyTests -v` before each required revalidation change; confirm the newly added assertion is the RED, or record existing coverage as GREEN. Repeat after the minimal adjustment, then run `PYTHONPATH=src:. python3 -m unittest tests.test_final_safety tests.test_operations tests.test_cli -v`.

- [ ] **B5: Commit pointer safety.**

~~~bash
git add -- src/threadroot/paths.py src/threadroot/operations.py tests/test_final_safety.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: keep default pointers outside vaults"
~~~

#### Group C — Exclusive claim command and deterministic result contract

- [ ] **C1: Write the claim tests in new `tests/test_claim.py`.** Import the existing operations module so the first RED is an explicit missing capability assertion. Include C4's collision methods and every C5 matrix method in this initial test edit before C2/C3. Use `getattr` plus a callable assertion for new entry points until implemented; a missing named capability is a valid first RED, unlike an unrelated broken import. Extend from this complete initial class, which creates only synthetic vaults:

~~~python
import json
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from threadroot import operations
from threadroot.cli import build_parser, execute
from threadroot.config import config_text
from threadroot.results import ExitCode


class ClaimTests(unittest.TestCase):
    def test_preview_and_apply_create_one_empty_regular_file(self):
        claim = getattr(operations, "run_claim", None)
        self.assertTrue(callable(claim), "run_claim capability is required")
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            self.assertTrue(operations.run_init(vault, True, False, {}, base / "home").ok)
            target = vault / "daily/2042-04-03.md"
            preview = claim(vault, "daily/2042-04-03.md", False)
            self.assertTrue(preview.ok)
            self.assertFalse(preview.applied)
            self.assertFalse(target.exists())
            self.assertEqual(preview.to_dict()["changes"], [{"action": "create_file",
                "path": "daily/2042-04-03.md", "status": "planned"}])
            result = claim(vault, "daily/2042-04-03.md", True)
            self.assertEqual(result.exit_code, ExitCode.OK)
            self.assertTrue(result.applied)
            self.assertEqual(target.read_bytes(), b"")
            self.assertTrue(stat.S_ISREG(target.lstat().st_mode))
            self.assertEqual(result.to_dict()["changes"][0]["status"], "completed")
            self.assertEqual(set(result.to_dict()),
                             {"ok", "command", "applied", "vault", "changes", "issues"})
            again = claim(vault, "daily/2042-04-03.md", True)
            self.assertEqual(again.exit_code, ExitCode.CONFLICT)

    def test_cli_claim_has_required_path_and_no_content_or_default_flag(self):
        parser = build_parser()
        args = parser.parse_args(["claim", "--path", "daily/2042-04-03.md", "--json"])
        self.assertEqual((args.command, args.path, args.apply),
                         ("claim", "daily/2042-04-03.md", False))
        from threadroot.results import ThreadrootError
        for suffix in ([], ["--path", "daily/a.md", "--set-default"],
                       ["--path", "daily/a.md", "--content", "synthetic"],
                       ["--pa", "daily/a.md"]):
            with self.subTest(suffix=suffix), self.assertRaises(ThreadrootError) as caught:
                parser.parse_args(["claim", *suffix])
            self.assertEqual(caught.exception.exit_code, ExitCode.USAGE)
~~~

- [ ] **C2: Confirm basic RED.** Run `PYTHONPATH=src:. python3 -m unittest tests.test_claim.ClaimTests -v`. Expect `run_claim capability is required` and parser `usage.invalid` for the valid claim command. Correct any unrelated test setup error first.

- [ ] **C3: Implement the claim path validator and planner.** Extend `CommandName = Literal["init", "adopt", "doctor", "claim"]`. In `ensure_claim_target`, reject empty/NUL/absolute/`..` literals, reject lexical `.second-brain` at the vault root and exact `secrets` components, then use `ensure_outside_secrets`. Compute normalized lexical paths with `normalized_absolute` and resolved paths with `resolve_path`; collect configured-root keys for which the target is a strict descendant in each representation. Both sets must contain exactly the same one key; otherwise raise `path.unsafe`. Exclude both lexical/resolved marker namespace. Return the lexical absolute target under the resolved vault, so the final exclusive open addresses that reservation name, not an existing symlink's referent. Use a mapping built from the four `VaultConfig.paths` fields, without importing config back into paths.

~~~python
def plan_claim(vault: Path, relative: str) -> tuple[PlannedChange, ...]:
    root = resolve_path(vault)
    config = load_config(root)
    content_paths = {key: getattr(config.paths, key)
                     for key in ("daily", "projects", "knowledge", "reviews")}
    target = ensure_claim_target(root, relative, content_paths)
    if os.path.lexists(target):
        raise ThreadrootError(ExitCode.CONFLICT, "target.conflict",
                              "Target already exists; choose another path.",
                              target.relative_to(root).as_posix())
    if not target.parent.is_dir():
        raise ThreadrootError(ExitCode.IO_OR_DRIFT, "filesystem.failed",
                              "Claim requires an existing directory parent.",
                              target.relative_to(root).as_posix())
    return (PlannedChange("create_file", target,
                          target.relative_to(root).as_posix(), ""),)
~~~

`run_claim` guards root resolution/planning exactly like the repaired setup runners, returns planned changes for preview, and calls `apply_plan("claim", root, plan)` for apply. `_validate_claim` reloads config and calls `ensure_claim_target(root, change.public_path, content_paths)`, requires equality with `change.target`, then uses `_require_directory` for the root and existing parent. Call `_validate_claim` immediately before the ordinary descendant check in `apply_plan` for command `claim`. It must revalidate containment without invoking `plan_claim`'s planning-time conflict check. Add a `ThreadrootError` handler in `apply_plan` that preserves the error's exit/code and current completed/unexecuted status. Existing `open("x")` with `content=""` provides OS-exclusive zero-byte creation; do not add a note-content parameter, parent `mkdir`, inode result field, or alternate create action. Existing-file collision from exclusive open remains `target.drifted` / `6`.

In `build_parser`, include claim with `--vault`, `--json`, required `--path`, and `--apply`; keep `--set-default` only for init/adopt. In `execute`, dispatch `run_claim(root, args.path, args.apply)`. A version check alone is not capability proof; a valid pure claim preview supplies it.

- [ ] **C4: Verify claim GREEN and collision regressions written in C1.** Run `PYTHONPATH=src:. python3 -m unittest tests.test_claim.ClaimTests -v`. The collision test included in C1 is:

~~~python
    def test_apply_collision_preserves_competing_bytes(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            self.assertTrue(operations.run_init(vault, True, False, {}, base / "home").ok)
            plan = operations.plan_claim(vault, "daily/2042-04-03.md")
            target = plan[0].target
            real_open = Path.open
            def competing_open(path, mode="r", *args, **kwargs):
                if path == target and mode == "x":
                    with real_open(path, "xb") as competitor:
                        competitor.write(b"synthetic competitor")
                return real_open(path, mode, *args, **kwargs)
            with patch.object(Path, "open", competing_open):
                result = operations.apply_plan("claim", vault, plan)
            self.assertEqual((result.exit_code, result.issues[0].code),
                             (ExitCode.IO_OR_DRIFT, "target.drifted"))
            self.assertEqual(target.read_bytes(), b"synthetic competitor")
            self.assertEqual(result.changes[0].status, "unexecuted")
~~~

Run `PYTHONPATH=src:. python3 -m unittest tests.test_claim.ClaimTests.test_apply_collision_preserves_competing_bytes -v`. Existing exclusive-open behavior may already pass; record that fact, never force a fake RED. C1 also writes `test_target_present_after_plan_is_drift` with a file created between `plan_claim` and `apply_plan`, and `test_two_preview_plans_have_one_winner` using two plans before either apply; expect first `0`, second `6`, and unchanged first reservation. These tests prove the OS/create boundary, not host-model behavior.

- [ ] **C5: Complete containment/error GREEN for the C1 tests.** C1 writes the following named methods, each using a fresh initialized synthetic vault and `subTest` rows, and C2 runs them before implementation. Run the focused suite before any further adjustment and then rerun it; keep already-GREEN rows as regressions.

| Method in `ClaimTests` | Inputs and exact assertions |
|---|---|
| `test_unsafe_claim_paths_are_zero_write` | `../a.md`, `/synthetic/a.md`, `daily/../a.md`, `daily/a\x00.md`, `.second-brain/a.md`, `secrets/a.md`, `daily/secrets/a.md`, `outside/a.md`, and `daily` all produce `4`; no `Path.open`/`mkdir` call |
| `test_claim_uses_exactly_one_configured_root` | Duplicate daily/reviews roots and nested `daily/archive` knowledge root reject ambiguous child with `4`; custom `notes/days` root accepts its safe child; a symlink crossing from daily to reviews rejects with `4` |
| `test_claim_parent_and_target_kinds` | Missing parent and file parent give `6`; existing file/directory/safe dangling link give `5`; `.second-brain` or secrets symlink destination gives `4`; safe directory symlink within the same content root may create its child |
| `test_claim_revalidates_config_and_parent` | Between plan/apply, change root mapping or symlink parent to outside/secrets: `4`; remove safe parent: `6`; no file outside vault |
| `test_claim_io_and_privacy` | Patch exclusive `Path.open` with `PermissionError`/EIO: `6`, unexecuted change, no raw exception path; NUL config: `4`; unknown schema: `3`; missing marker: `3`; JSON one object, no note bytes, no diagnostic absolute paths |
| `test_claim_does_not_create_parents_or_accept_content` | Patch `Path.mkdir` and pointer writer during valid claim preview/apply: neither called; parser rejects `--content`, `--text`, positional bytes and `--set-default` with `2` |

Use `PYTHONPATH=src:. python3 -m unittest tests.test_claim -v` for the focused complete group, then `PYTHONPATH=src:. python3 -m unittest discover -s tests -v`. Inspect every new failure before modifying code; do not loosen existing no-overwrite or privacy assertions.

- [ ] **C6: Commit the deterministic claim capability.**

~~~bash
git add -- src/threadroot/results.py src/threadroot/paths.py src/threadroot/operations.py src/threadroot/cli.py tests/test_claim.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: add exclusive empty-file claims"
~~~

#### Group D — Shared skills and capability/partial-state contracts

- [ ] **D1: Read required writing-skills and skill-creator instructions, then write contract REDs.** The five file-creating skills are exactly `recording`, `daily-wrap-up`, `weekly-review`, `project-kickoff`, and `decision-log`. In `tests/test_skills.py`, extend only those five `CORE_COMMANDS` inventories with these exact strings:

~~~text
threadroot claim --path <relative> --vault <vault> --json
threadroot claim --path <relative> --vault <vault> --json --apply
~~~

Add the following invariant names to expected `BASE_INVARIANTS` and the synthetic shared fixture, but not yet to production skills or `CONTRACT_KEYS`. All shared consumers inherit the rules; read-only workflows acquire no claim command.

~~~text
new-file=claim-verify-native-edit
claim-failure=stop
claim-verification=same-identity-empty-regular
partial-state=preserve-and-report
outside-vault-create=independent-native-exclusive-or-omit
~~~

Change kickoff's expected `local-adapter` value to `host-native-auto-loaded-already-git-ignored-and-exclusive`. Add missing/inverted mutations for each new invariant using the existing `EffectiveSkillContractTests._write_fixture` and `load_effective_contract` pattern. Run `PYTHONPATH=src:. python3 -m unittest tests.test_skills.EffectiveSkillContractTests tests.test_skills.ProjectKickoffSkillContractTests -v`. Expected RED is missing claim inventory/invariants or unsupported invariant keys. Do not bypass exact command inventory validation.

- [ ] **D2: Write the shared GREEN protocol and minimally adapt the five procedures.** Add the five keys to `tests/skill_contract.py:CONTRACT_KEYS`, enforce their exact values in the loader's `required` mapping, and add them to `skills/README.md`'s shared contract. Put new command strings only in each skill's canonical `threadroot-commands` block; shared skill bodies use inventory-entry names to preserve the no-command-outside-inventory contract. Use the following complete protocol text as the new shared section:

> For an authorized missing vault file, finish the semantic draft in the host first. Require an existing safe parent; if it is missing, report the unmet precondition and stop this file workflow. Invoke the claim-preview inventory entry with the diagnosed vault and the exact vault-relative target. Require exit 0, one JSON object with the existing result shape, `ok=true`, `command=claim`, `applied=false`, the diagnosed `vault`, exactly one `create_file` change for that target with `status=planned`, and no error issue. Missing executable, unsupported command, malformed or mismatched output, unsafe path, or conflict means stop without any native create or edit. Do not install or substitute another write mechanism.
>
> With the workflow's explicit apply intent, invoke the claim-apply inventory entry. Require the same checks with `applied=true` and `status=completed`. A successful apply reserves one zero-byte file; it has not written the draft. Immediately observe the target with the host's native metadata capability without following a link, record its file identity (`device` and `inode` on supported systems), and require a regular file of size zero. Immediately before the native edit, repeat that observation and require the identical identity, regular type and zero size. If the host cannot establish this evidence, stop. Under the cooperative-session threat model the successful exclusive claim and these observations bind the reservation; they do not protect against malicious replacement between the CLI and first observation.
>
> Only then fill the reserved file with the host's native edit mechanism. A generic native Write or an absence check is not exclusive-create proof. Another session's existing empty file is a collision, never a reservation to reuse. If apply succeeded but verification or native editing fails, report the visible empty reservation or partial edit and every unexecuted action. Do not delete, roll back, retry as an existing-file edit, or report that nothing was created. Existing files continue to use read/draft/re-read/drift-stop/native-edit.
>
> A proposed local adapter outside the diagnosed vault is omitted unless its parent already exists, the host independently guarantees exclusive native creation, the exact adapter path is already ignored by Git, and the adapter is a native auto-loaded convention. The vault claim command never authorizes that outside path.

In recording, daily-wrap-up and weekly-review replace only their missing-target native-exclusive clauses with the shared protocol, retaining their respective authorization/routing rules. In kickoff require the already-existing project directory; remove directory creation from its preview/apply write set and report missing parent as an unmet precondition. Retain its five confirmations and complete preview; require the third adapter fact (exclusive native create), plus existing parent. In decision-log require the existing decisions directory rather than creating it in this workflow. Keep matching-content no-op only for an ADR already observed/read before entering the new-file route; a path appearing after an absent preview is always a collision, even if bytes would match. Stop subsequent project/backlink updates after claim/verification/edit failure, retain partial state, and never inspect a competing file's content to justify continuing. Update stale Safety/Output claims about directories created. Run `PYTHONPATH=src:. python3 -m unittest tests.test_skills -v` to confirm GREEN.

- [ ] **D3: Add executable capability-response and trace REDs without pretending to run a model.** Create `tests/test_claim_workflows.py`. Add the test-only `validate_claim_trace` interface declared above to `tests/skill_contract.py` only after the tests below fail for missing validator. The keyword defaults are the synthetic test fixture; auditing a separately authorized real-host synthetic trace must pass that run's diagnosed vault and approved relative target explicitly. Event records contain metadata/results only, never note bytes. Their exact shapes are: `{"kind":"preview"|"apply", "exit":int,"result":object}`, `{"kind":"verify","identity":[int,int],"regular":bool,"size":int}`, `{"kind":"native-edit","ok":bool}`, and `{"kind":"stop","partial":bool}`. No other events are permitted; in particular `native-write`, `mkdir`, `delete`, `rollback`, and `retry-existing` are invalid. Use this positive sequence and independent rejection examples:

~~~python
from copy import deepcopy
from pathlib import Path
import unittest
from tests import skill_contract


def claim_result(applied: bool) -> dict[str, object]:
    return {"ok": True, "command": "claim", "applied": applied,
            "vault": "/synthetic/vault", "changes": [{"action": "create_file",
            "path": "daily/2042-04-03.md",
            "status": "completed" if applied else "planned"}], "issues": []}


def success_events() -> list[dict[str, object]]:
    return [{"kind": "preview", "exit": 0, "result": claim_result(False)},
            {"kind": "apply", "exit": 0, "result": claim_result(True)},
            {"kind": "verify", "identity": [1, 7], "regular": True, "size": 0},
            {"kind": "verify", "identity": [1, 7], "regular": True, "size": 0},
            {"kind": "native-edit", "ok": True}]


class ClaimWorkflowTests(unittest.TestCase):
    def test_success_and_missing_invalid_unsupported_capability(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        self.assertEqual(validate(success_events()), ())
        for code, payload in ((127, None), (2, None), (0, "invalid JSON"),
                              (0, {}), (5, {"ok": False})):
            failed = {"kind": "preview", "exit": code, "result": payload}
            self.assertEqual(validate([failed, {"kind": "stop", "partial": False}]), ())
            self.assertIn("claim.unsafe-continuation",
                          validate([failed, {"kind": "native-edit", "ok": True}]))

    def test_identity_collision_and_partial_failure_gates(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        for field, value in (("identity", [1, 8]), ("size", 1), ("regular", False)):
            events = success_events()
            events[3][field] = value
            self.assertIn("claim.unsafe-continuation", validate(events))
            self.assertEqual(validate(events[:4] + [{"kind": "stop", "partial": True}]), ())
        events = success_events()
        events[1] = {"kind": "apply", "exit": 6, "result": {"ok": False}}
        self.assertIn("claim.unsafe-continuation", validate(events))
        self.assertEqual(validate(events[:2] + [{"kind": "stop", "partial": False}]), ())
        events = success_events()
        events[-1]["ok"] = False
        self.assertEqual(validate(events + [{"kind": "stop", "partial": True}]), ())
        self.assertIn("claim.unsafe-continuation", validate(events + [{"kind": "delete"}]))
~~~

Run `PYTHONPATH=src:. python3 -m unittest tests.test_claim_workflows -v`; expected RED is the missing validator assertion. Add all four expansion tests named below before implementing the oracle. Then add these concrete test-only functions in `tests/skill_contract.py`, importing `Mapping` and `Sequence` from `collections.abc`:

~~~python
def _claim_result_pair(event: Mapping[str, object], applied: bool) -> tuple[str, str] | None:
    result = event.get("result")
    if (type(event.get("exit")) is not int or event["exit"] != 0
            or type(result) is not dict
            or set(result) != {"ok", "command", "applied", "vault", "changes", "issues"}):
        return None
    if (result["ok"] is not True or result["applied"] is not applied
            or result["command"] != "claim" or result["issues"] != []
            or type(result["vault"]) is not str or not result["vault"]):
        return None
    changes = result["changes"]
    if type(changes) is not list or len(changes) != 1 or type(changes[0]) is not dict:
        return None
    change = changes[0]
    if (set(change) != {"action", "path", "status"}
            or change["action"] != "create_file"
            or change["status"] != ("completed" if applied else "planned")
            or type(change["path"]) is not str or not change["path"]):
        return None
    return result["vault"], change["path"]


def validate_claim_trace(
    events: Sequence[Mapping[str, object]], *,
    expected_vault: str = "/synthetic/vault",
    expected_path: str = "daily/2042-04-03.md",
) -> tuple[str, ...]:
    state = "preview"
    pair = (expected_vault, expected_path)
    identity: list[int] | None = None
    partial = False
    failure = ("claim.unsafe-continuation",)
    for event in events:
        kind = event.get("kind")
        if kind == "stop":
            if (set(event) != {"kind", "partial"} or state != "stop"
                    or event.get("partial") is not partial):
                return failure
            state = "done"
            continue
        if state in ("stop", "done"):
            return failure
        if state in ("preview", "apply"):
            if kind != state or set(event) != {"kind", "exit", "result"}:
                return failure
            applying = state == "apply"
            if applying:
                result = event.get("result")
                changes = result.get("changes", []) if type(result) is dict else []
                completed = type(changes) is list and any(
                    type(change) is dict and change.get("status") == "completed"
                    for change in changes
                )
                partial = event.get("exit") == 0 or completed
            observed = _claim_result_pair(event, applying)
            if observed != pair:
                state = "stop"
            elif applying:
                state = "verify-first"
            else:
                state = "apply"
        elif state in ("verify-first", "verify-second"):
            if kind != "verify":
                return failure
            observed = event.get("identity")
            valid = (set(event) == {"kind", "identity", "regular", "size"}
                     and type(observed) is list and len(observed) == 2
                     and all(type(value) is int for value in observed)
                     and event.get("regular") is True
                     and type(event.get("size")) is int and event["size"] == 0)
            if not valid or (state == "verify-second" and observed != identity):
                state = "stop"
            elif state == "verify-first":
                identity = list(observed)
                state = "verify-second"
            else:
                state = "edit"
        elif state == "edit":
            if (kind != "native-edit" or set(event) != {"kind", "ok"}
                    or type(event.get("ok")) is not bool):
                return failure
            state = "done" if event["ok"] else "stop"
    return () if state == "done" else failure
~~~

The oracle checks result consistency, event order and metadata only; the CLI remains the path-safety authority. A zero-exit apply with malformed output conservatively marks possible partial state and allows only reporting/stopping, never cleanup. No filesystem or host tool is called by the oracle. The pairing helper's exact signature is `_claim_result_pair(event: Mapping[str, object], applied: bool) -> tuple[str, str] | None`.

Add named tests `test_mismatched_claim_payloads_stop_before_edit`, `test_forbidden_native_fallbacks_are_rejected`, `test_completed_apply_failure_preserves_partial_state`, and `test_all_five_skills_declare_claim_protocol`. Mutate successful payload command/vault/path/action/status/applied/ok and missing/extra fields; assert only stop is accepted. Exercise duplicate verify with changed identity, missing metadata, non-integer identity, nonzero size, symlink type, successful apply followed by malformed result, and forbidden events. The last test loads every named skill through `load_effective_contract` using `CORE_COMMANDS` imported from `tests.test_skills`, and verifies the exact shared invariants. Run `PYTHONPATH=src:. python3 -m unittest tests.test_claim_workflows tests.test_skills -v` after minimal oracle adjustments.

These tests prove the executable oracle and declared contract reject missing/invalid/unsupported capability, collision, identity drift, and hidden partial state. They do not prove that a live host follows the prose. Real-host pressure runs using this oracle are the separately authorized manual checkpoint in Group F; record them unexecuted until authorized. Do not introduce phrase-presence tests for prose or count prior dogfood as atomic-exclusivity evidence.

- [ ] **D4: Self-review each consuming skill, run focused/full GREEN, and commit.** Trace one authorized missing file, one collision, one unavailable capability, one unverifiable identity and one failed native edit through each skill without invoking a model. Verify no instruction falls back to native creation inside the vault, creates missing parents, or continues to downstream backlinks after a stopped claim. Run `PYTHONPATH=src:. python3 -m unittest tests.test_skills tests.test_claim_workflows tests.test_packaging tests.test_claim -v`, then `PYTHONPATH=src:. python3 -m unittest discover -s tests -v`.

~~~bash
git add -- skills/README.md skills/recording/SKILL.md skills/daily-wrap-up/SKILL.md skills/weekly-review/SKILL.md skills/project-kickoff/SKILL.md skills/decision-log/SKILL.md tests/skill_contract.py tests/test_skills.py tests/test_claim_workflows.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: gate new skill files through exclusive claims"
~~~

#### Group E — Fence-aware structure and doctor remediation

- [ ] **E1: Write fence/closing-hash REDs in `tests/test_contracts.py`.** Add `MarkdownFenceTests` using the existing private extractor's exact signature, including the E2 paragraph's additional fence/ATX rows before E2 changes the extractor; this is verification tooling only.

~~~python
class MarkdownFenceTests(unittest.TestCase):
    def test_fenced_decoys_do_not_supply_structure(self):
        from scripts.check_contract import _markdown_structure
        for fence in ("```", "~~~~", "````"):
            with self.subTest(fence=fence):
                payload = (f"## Real ###\n\n{fence}text\n## Decoy\n"
                           f"[[hidden]] [hidden](hidden.md)\n{fence}\n[[visible]]\n").encode()
                self.assertEqual(_markdown_structure(payload), (("Real",), ("visible",)))

    def test_shorter_or_wrong_fence_does_not_close(self):
        from scripts.check_contract import _markdown_structure
        payload = b"````\n```\n## Hidden\n~~~\n[[hidden]]\n````\n## Real ###\n"
        self.assertEqual(_markdown_structure(payload), (("Real",), ()))
~~~

Run `PYTHONPATH=src:. python3 -m unittest tests.test_contracts.MarkdownFenceTests -v`; expect leaked Decoy/hidden structure and unstripped closing hashes. Add this end-to-end test before E2 and run `PYTHONPATH=src:. python3 -m unittest tests.test_contracts.ValidationTests.test_fenced_heading_and_link_cannot_satisfy_case -v`; expect the baseline to accept fenced decoys and miss both required failures. Keep byte hashes/prose comparison unchanged.

~~~python
    def test_fenced_heading_and_link_cannot_satisfy_case(self):
        from scripts.check_contract import materialize_fixture, validate_contract
        case = json.loads(Path("tests/fixtures/contracts/project-decision.json").read_text())
        with TemporaryDirectory() as temporary:
            before = Path(temporary) / "before"
            after = Path(temporary) / "after"
            materialize_fixture(case, before)
            materialize_fixture(case, after)
            project = after / "wiki/projects/orchard-cli/index.md"
            project.write_text(project.read_text() + "\n[[decisions/2042-04-03-json-storage]]\n")
            adr = "wiki/projects/orchard-cli/decisions/2042-04-03-json-storage.md"
            (after / adr).write_text("```\n## Options Considered\n## Decision\n"
                                     "## Rationale\n[[../index]]\n```\n")
            failures = {(item.code, item.path) for item in validate_contract(case, before, after)}
            self.assertIn(("missing_heading", adr), failures)
            self.assertIn(("missing_link", adr), failures)
~~~

- [ ] **E2: Implement a minimal line-state filter.** Add `_markdown_visible_lines(text: str) -> list[str]` in `scripts/check_contract.py`. The exact algorithm is:

~~~python
def _markdown_visible_lines(text: str) -> list[str]:
    visible: list[str] = []
    fence_character = ""
    fence_length = 0
    for line in text.splitlines():
        if fence_character:
            closing = re.fullmatch(r" {0,3}(" + re.escape(fence_character)
                                   + r"{" + str(fence_length) + r",})[ \t]*", line)
            if closing:
                fence_character = ""
                fence_length = 0
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence_character = opening.group(1)[0]
            fence_length = len(opening.group(1))
            continue
        visible.append(line)
    return visible
~~~

Feed only `"\n".join(_markdown_visible_lines(text))` into heading/link extraction. Extend ATX recognition to zero-to-three leading spaces, one-to-six hashes followed by space/tab or line end; strip a closing hash run only when preceded by whitespace and followed solely by whitespace. Preserve literal trailing hashes in `## C#`; preserve link normalization, sorted tuples and non-UTF8 behavior. Add indented opening/longer closing, unclosed fence, info-string backtick, tilde info-string, and `C#` cases to `MarkdownFenceTests`. Run `PYTHONPATH=src:. python3 -m unittest tests.test_contracts -v`, then `PYTHONPATH=src:. python3 -m unittest discover -s tests -v`.

- [ ] **E3: Commit structural extraction.**

~~~bash
git add -- scripts/check_contract.py tests/test_contracts.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: ignore fenced Markdown in structural contracts"
~~~

- [ ] **E4: Write doctor remediation REDs in `tests/test_final_safety.py`.** Add `DoctorRemediationTests.test_every_error_has_concrete_remediation` and `test_io_remediation_keeps_exit_six_and_is_read_only`. The first builds synthetic missing root, file root, missing/unreadable marker, unknown schema, malformed config, unsafe path, missing/non-directory/unreadable content directories, and injected resolution-I/O cases. For every returned error require a nonempty `Remediation: ` suffix and the exact instruction selected from this mapping:

~~~python
DOCTOR_REMEDIATIONS = {
    "vault.unresolved": "Pass --vault to select an existing configured vault.",
    "vault.not_found": "Pass --vault for an existing vault or preview init for a new target.",
    "vault.not_directory": "Pass --vault for a directory.",
    "config.invalid": "Restore a readable schema-v1 .second-brain/config.json or preview adopt for a markerless vault.",
    "config.unsupported_version": "Use a compatible Threadroot version; do not rewrite the marker with this version.",
    "config.path_invalid": "Correct the configured paths to existing content directories and rerun doctor.",
    "path.unsafe": "Correct the path or symlink to stay inside the vault and outside secrets, then rerun doctor.",
    "path.not_found": "Restore the configured directory or correct its config path, then rerun doctor.",
    "path.not_directory": "Select a directory in the config and rerun doctor.",
    "path.not_readable": "Grant read access to the configured directory and rerun doctor.",
    "filesystem.failed": "Check filesystem availability and directory access, then rerun doctor.",
}
~~~

Use this class with the mapping above. Add non-directory/missing configured paths and a configured `../outside` case by changing the initialized synthetic config/entry before the guarded call; retain the existing unsafe and unsupported-version result expectations. The mapping comparison checks concrete instructions rather than accepting any arbitrary advice suffix.

~~~python
class DoctorRemediationTests(unittest.TestCase):
    def test_every_error_has_concrete_remediation(self):
        for scenario in ("missing-root", "file-root", "missing-marker", "malformed",
                         "unknown-schema", "missing-directory", "file-directory", "unsafe"):
            with self.subTest(scenario=scenario), TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "vault"
                if scenario == "file-root":
                    root.write_text("synthetic")
                elif scenario == "missing-marker":
                    root.mkdir()
                elif scenario != "missing-root":
                    self.assertTrue(run_init(root, True, False, {}, base / "home").ok)
                    marker = root / ".second-brain/config.json"
                    if scenario == "malformed":
                        marker.write_text("{")
                    elif scenario in ("unknown-schema", "unsafe"):
                        document = json.loads(config_text())
                        if scenario == "unknown-schema":
                            document["schema_version"] = 2
                        else:
                            document["paths"]["daily"] = "../outside"
                        marker.write_text(json.dumps(document))
                    else:
                        (root / "daily").rmdir()
                        if scenario == "file-directory":
                            (root / "daily").write_text("synthetic")
                result = run_doctor(root)
                self.assertFalse(result.ok)
                self.assertFalse(result.applied)
                self.assertEqual(result.changes, ())
                for issue in result.issues:
                    if issue.level == "error":
                        self.assertIn("Remediation: ", issue.message)
                        self.assertEqual(issue.message.split("Remediation: ", 1)[1],
                                         DOCTOR_REMEDIATIONS[issue.code])

    def test_io_remediation_keeps_exit_six_and_is_read_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root.lstat().st_mtime_ns
            with patch.object(Path, "resolve", side_effect=OSError(errno.EIO, "synthetic I/O")), \
                 patch.object(Path, "mkdir") as mkdir, patch.object(Path, "touch") as touch, \
                 patch.object(Path, "write_text") as write, patch.object(Path, "unlink") as unlink, \
                 patch("threadroot.operations.os.replace") as replace:
                result = run_doctor(root)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].message.split("Remediation: ", 1)[1],
                             DOCTOR_REMEDIATIONS["filesystem.failed"])
            for operation in (mkdir, touch, write, unlink, replace):
                operation.assert_not_called()
            self.assertEqual(root.lstat().st_mtime_ns, before)

    def test_unresolved_cli_doctor_has_remediation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            failure = ThreadrootError(ExitCode.CONFIG, "vault.unresolved", "Pass --vault.")
            with patch("threadroot.cli.resolve_vault", side_effect=failure):
                result = execute(build_parser().parse_args(["doctor", "--json"]), root, {}, root)
            self.assertEqual(result.exit_code, ExitCode.CONFIG)
            self.assertEqual(result.issues[0].message.split("Remediation: ", 1)[1],
                             DOCTOR_REMEDIATIONS["vault.unresolved"])
~~~

Extend the first method with marker-unreadable and content-unreadable cases using `patch("threadroot.operations.os.access")`: return false only for the selected marker or content path's read check and delegate other calls to the saved real `os.access`; do not rely on OS privilege level. For each real-tree doctor call snapshot synthetic `lstat` kind/mtime/link entries before/after and intercept the five mutation APIs after fixture setup, as in the I/O case. Run `PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.DoctorRemediationTests -v`; expect missing remediation assertions, not changed exits.

- [ ] **E5: Add concrete remediation without schema changes and verify GREEN.** Define `_doctor_issue(issue: Issue) -> Issue` in `operations.py`, with the mapping above as `_DOCTOR_REMEDIATIONS`:

~~~python
def _doctor_issue(issue: Issue) -> Issue:
    if issue.level != "error" or " Remediation: " in issue.message:
        return issue
    return Issue(issue.level, issue.code,
                 issue.message + " Remediation: " + _DOCTOR_REMEDIATIONS[issue.code],
                 issue.path)
~~~

Apply it in `_doctor_result` and `_error_result` when command is doctor; in CLI resolution-error handling use the same helper for doctor. Retain existing issue codes/order, `applied=false`, empty changes, and the Group A `error_exit` preservation. E4 includes the unresolved-root case before this change, so a doctor error raised before root resolution must also receive remediation. Run `PYTHONPATH=src:. python3 -m unittest tests.test_final_safety.DoctorRemediationTests tests.test_operations.DoctorTests tests.test_cli -v`, then `PYTHONPATH=src:. python3 -m unittest discover -s tests -v`.

~~~bash
git add -- src/threadroot/operations.py src/threadroot/cli.py tests/test_final_safety.py
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: give doctor errors concrete remediation"
~~~

#### Group F — Public contracts, final verification, and one review handoff

- [ ] **F1: Update public docs and verify packaging contract consistency.** In README command inventory add the exact approved claim syntax and a synthetic two-command preview/apply example for `daily/2042-04-03.md`; explain that only an empty reservation is created. State existing-parent and claim–verify–native-edit requirements, exits `4`/`5`/`6`, capability failure stops, and visible partial state. In SECURITY update Path containment, Non-overwriting writes, and Partial failures for lexical/resolved secrets and marker exclusions, pointer overlap rejection before writes, owned pointer-temp cleanup only, and cooperative-session limits. Preserve the existing pointer `--apply --set-default` / after-vault-success relationship checked by `tests/test_documentation.py`. In AGENTS add claim to v0 contract and state no parents/no note bytes. In `docs/testing.md` add exact focused commands for the three new test modules, fence regressions and claim smoke; distinguish local oracle checks from separately authorized model runs. Keep shared skills provider-neutral.

Use these executable examples in README/testing (an existing configured synthetic vault with a daily parent is required):

~~~bash
threadroot claim --path daily/2042-04-03.md --vault ./synthetic-vault --json
threadroot claim --path daily/2042-04-03.md --vault ./synthetic-vault --json --apply
~~~

Review both native manifests, existing manifest parity tests, release exact-member tests and privacy scan inputs: no new skill name or dependency is needed, so manifests/catalog/version remain unchanged. New test files must appear in source distribution via the existing manifest rules; host archives must carry the updated shared skill bytes from the single source tree. Runtime wheel must expose claim. Verify through build/archive inspection and CLI smoke rather than adding README phrase tests. If an existing exact-content assertion needs a changed expected value, first run its targeted test to show the legitimate RED and update only that assertion; do not bypass package parity or privacy checks.

- [ ] **F2: Verify docs and commit exact public paths.** Run `PYTHONPATH=src:. python3 -m unittest tests.test_documentation tests.test_packaging tests.test_release tests.test_public_safety -v`, `python3 scripts/check_public.py .`, and `git diff --check`. Review spec criteria 1–14 against groups A–F. Existing manifest and package assertions already derive shipped content from the shared tree, so F1 requires no manifest, catalog, dependency, version, or packaging-test mutation. If evidence contradicts that assumption, report the concrete new finding to the controller; do not create an unnamed conditional commit or weaken an assertion.

~~~bash
git add -- README.md SECURITY.md docs/testing.md AGENTS.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: explain claim and final safety verification"
~~~

- [ ] **F3: Run the available local interpreter matrix.** Use the installed interpreters only; do not install missing interpreters or dependencies through the network. Report each absent interpreter as unavailable, and do not call this a completed eight-cell CI matrix. Run this exact loop from the repository root; any nonzero test/compile exit stops the loop:

~~~bash
for threadroot_python in python3.11 python3.12 python3.13 python3.14; do
  if command -v "$threadroot_python" >/dev/null 2>&1; then
    "$threadroot_python" --version
    PYTHONPATH=src:. "$threadroot_python" -m unittest discover -s tests -v || exit 1
    "$threadroot_python" -m compileall -q src scripts tests || exit 1
  else
    printf '%s unavailable locally\n' "$threadroot_python"
  fi
done
~~~

The existing CI matrix remains macOS/Linux × Python 3.11–3.14. A local macOS run cannot prove Linux behavior; no remote exists, so record hosted CI as unexecuted unless the controller supplies separate execution evidence. Do not push to obtain CI.

- [ ] **F4: Build fresh artifacts without implicit network access and run wheel smoke.** Locate an already available Python environment containing `build` and setuptools `>=69`; verify with `python3 -m build --version` and `python3 -c 'import setuptools; print(setuptools.__version__)'`. If the default interpreter lacks them, inspect already known local build environments and record the chosen executable in the ignored report. Missing local build tooling is an external prerequisite: report it and request separate authorization for network installation, never silently install. Use that executable as `threadroot_build_python`; this variable holds the discovered exact Python path and is not a system option. Then run:

~~~bash
"$threadroot_build_python" -m build --no-isolation
python3 scripts/build_release.py --output dist
python3 -m zipfile -l dist/threadroot-claude-0.1.0.zip
python3 -m zipfile -l dist/threadroot-codex-0.1.0.zip
python3 scripts/check_public.py . dist
python3 scripts/check_public.py dist/threadroot-0.1.0-py3-none-any.whl dist/threadroot-0.1.0.tar.gz dist/threadroot-claude-0.1.0.zip dist/threadroot-codex-0.1.0.zip
threadroot_smoke_root="$(mktemp -d)"
python3 -m venv "$threadroot_smoke_root/venv"
"$threadroot_smoke_root/venv/bin/python" -m pip install --no-index --no-deps dist/threadroot-0.1.0-py3-none-any.whl
"$threadroot_smoke_root/venv/bin/threadroot" --version
"$threadroot_smoke_root/venv/bin/threadroot" init --vault "$threadroot_smoke_root/vault" --apply --json
"$threadroot_smoke_root/venv/bin/threadroot" claim --vault "$threadroot_smoke_root/vault" --path daily/2042-04-03.md --json
test ! -e "$threadroot_smoke_root/vault/daily/2042-04-03.md"
"$threadroot_smoke_root/venv/bin/threadroot" claim --vault "$threadroot_smoke_root/vault" --path daily/2042-04-03.md --apply --json
test -f "$threadroot_smoke_root/vault/daily/2042-04-03.md"
test ! -s "$threadroot_smoke_root/vault/daily/2042-04-03.md"
~~~

Execute each dependent command only after the previous exit is checked. Parse both claim JSON results and require the exact schema/status/target; repeat apply and require exit `5`. Run host archive tests against freshly built sources and inspect ZIP member bytes for all five changed skills plus shared README. Inspect wheel/sdist members for `claim` runtime code and all new tests in the sdist, no private/generated files, valid archive paths and no symlinks. Leave the temporary root for OS cleanup; do not recursively delete it.

- [ ] **F5: Perform only local native validation within existing authority; gate new host/model usage.** `claude plugin validate --strict .` is a local no-model validation; run it only if the installed command does not require network or normal-state mutation. Require exit `0`. Run `PYTHONPATH=src:. python3 -m unittest tests.test_packaging tests.test_release -v` for both native archive/manifests regardless of host binary availability. Do not automatically repeat plugin installs, marketplace add/remove, or previous Task 12 dogfood. A live disposable Codex registry/install check is a manual checkpoint if not separately authorized; package static validation remains automated. After that separate authorization, the exact local registry commands are:

~~~bash
threadroot_native_root="$(mktemp -d)"
CODEX_HOME="$threadroot_native_root" codex plugin marketplace add "$PWD" --json
CODEX_HOME="$threadroot_native_root" codex plugin add threadroot@threadroot --json
CODEX_HOME="$threadroot_native_root" codex plugin list --json
~~~

Check each exit before proceeding and parse the final JSON for the installed Threadroot entry. Record only versions, exits and installed-entry boolean. These commands must use the disposable config root on every invocation and must not launch a model or contact a remote marketplace; stop if the installed host cannot meet those conditions. Leave this temporary root for OS cleanup.

Fresh Claude/Codex model or network synthetic runs require separate explicit authorization even though previous Task 12 runs were authorized. Before asking, finish F1–F4 and prepare the concrete changed artifacts and these cases for controller review: (1) missing daily claim success; (2) missing review claim success; (3) kickoff/ADR with pre-existing parents; (4) unsupported command exit `2` and missing executable; (5) invalid/mismatched preview/apply JSON; (6) competing empty reservation; (7) identity or size change before native edit; (8) native edit failure retaining reservation; (9) outside-vault adapter without exclusive capability. Use only synthetic fixtures, scoped roots and no private context. The oracle in D3 audits recorded metadata events, and the existing structural checker audits final files/headings/links. Report each actual host run separately from oracle tests. Do not infer atomic exclusivity from earlier Write-tool or dogfood success, and never launch a new model, copy credentials, weaken isolation, or use the private vault to fill an evidence gap. If separate authorization is absent, mark these manual cases unexecuted and hand off that limitation; do not claim fresh cross-host behavior verified.

- [ ] **F6: Reconcile only ignored historical reports and ledger.** Read `.superpowers/sdd/2026-09-02-threadroot-v0/task-12-report.md` and `progress.md`. The latter is the actual ledger filename. Replace the Task 12 report's initial stale Status paragraph with one unique current summary: Task 12 automated, disposable uninstall, authorized synthetic host runs and the authorized stable-baseline private rerun were completed at `0456d0eff3df7b1b378048357ab77323afccacea`; their earlier checkpoints are historical and do not prove the new claim contract. Mark earlier private adoption-boundary/drift-stop and pre-final-verification summaries `Superseded by the final Task 12 checkpoint` while preserving their evidence paragraphs. Do not reopen/read the private vault or recreate transcripts. Change only `- [ ] Task 12` to `- [x] Task 12` in `progress.md`, append Task 13's commit/evidence summary, and leave its review status pending the controller's one re-review. Append all exact RED/GREEN/final commands, exits, counts, commit hashes, unavailable environments and manual gates to `final-fix-report.md`. Verify all three files with `git check-ignore`; never stage them.

- [ ] **F7: Self-review and final single-review handoff.** Check the approved spec's 14 acceptance criteria; requirements introduced here map to A (4, 13), B (12), C (10), D (11), E (5, 14), F (1–3, 6–9 and regression coverage). Confirm matching function signatures, result codes, command inventories and no placeholder implementation remains. Run `git diff --check`, `git diff --cached --name-only`, `git status --short`, and `git log --oneline -8`. Expected clean worktree/index with only the exact scope commits. Return DONE or DONE_WITH_CONCERNS, commits, automated evidence and explicit unexecuted manual gates. The controller now performs exactly one scoped final re-review; do not create another fix task or launch a reviewer yourself.

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
