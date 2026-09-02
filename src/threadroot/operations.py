from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import tempfile

from .config import config_text, load_config
from .paths import MARKER_RELATIVE, default_pointer_path, ensure_within, normalized_absolute
from .results import (
    ActionName,
    Change,
    CommandName,
    CommandResult,
    ExitCode,
    Issue,
    ThreadrootError,
)


_DIRECTORIES = (
    ".second-brain",
    "daily",
    "wiki",
    "wiki/projects",
    "wiki/tech",
    "wiki/reviews",
)


@dataclass(frozen=True)
class PlannedChange:
    action: ActionName
    target: Path
    public_path: str
    content: str | None = None


def _config_path_invalid() -> ThreadrootError:
    return ThreadrootError(
        ExitCode.CONFIG,
        "config.path_invalid",
        "Vault config or a configured content directory is invalid.",
    )


def _is_initialized(vault: Path) -> bool:
    try:
        config = load_config(vault)
    except ThreadrootError:
        raise _config_path_invalid() from None

    for relative in (
        config.paths.daily,
        config.paths.projects,
        config.paths.knowledge,
        config.paths.reviews,
    ):
        try:
            configured = ensure_within(vault, relative)
        except ThreadrootError:
            raise _config_path_invalid() from None
        if not configured.is_dir():
            raise _config_path_invalid()
    return True


def plan_init(vault: Path) -> tuple[PlannedChange, ...]:
    root = Path(vault).resolve(strict=False)
    marker = root / MARKER_RELATIVE
    if os.path.lexists(marker):
        _is_initialized(root)
        return ()

    changes: list[PlannedChange] = []
    if root.exists():
        if not root.is_dir():
            raise ThreadrootError(
                ExitCode.CONFLICT,
                "target.conflict",
                "Vault target is not a directory.",
            )
        entries = list(root.iterdir())
        allows_git_only = (
            len(entries) == 1
            and entries[0].name == ".git"
            and entries[0].is_dir()
            and not entries[0].is_symlink()
        )
        if entries and not allows_git_only:
            raise ThreadrootError(
                ExitCode.CONFLICT,
                "target.conflict",
                "Vault target is not empty.",
            )
    else:
        if not root.parent.is_dir():
            raise ThreadrootError(
                ExitCode.CONFLICT,
                "target.parent_invalid",
                "Vault target requires an existing directory parent.",
            )
        changes.append(PlannedChange("create_directory", root, "."))

    changes.extend(
        PlannedChange("create_directory", root / relative, relative)
        for relative in _DIRECTORIES
    )
    changes.append(
        PlannedChange(
            "create_file",
            root / MARKER_RELATIVE,
            MARKER_RELATIVE.as_posix(),
            config_text(),
        )
    )
    return tuple(changes)


def _changes_with_status(
    plan: Sequence[PlannedChange], completed: int
) -> tuple[Change, ...]:
    return tuple(
        Change(change.action, change.public_path, "completed" if index < completed else "unexecuted")
        for index, change in enumerate(plan)
    )


def _validate_root_creation(vault: Path, change: PlannedChange) -> None:
    if change.public_path != "." or change.target.resolve(strict=False) != vault:
        raise ValueError("planned vault root changed")
    if not change.target.parent.is_dir():
        raise ValueError("vault parent changed")


def _validate_descendant(vault: Path, change: PlannedChange) -> None:
    if not vault.is_dir() or vault.resolve(strict=True) != vault:
        raise ValueError("vault root changed")
    try:
        relative = change.target.relative_to(vault).as_posix()
        parent = change.target.parent.resolve(strict=True)
        parent.relative_to(vault)
    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError):
        raise ValueError("planned path changed") from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("planned path changed") from None
        raise
    if relative != change.public_path or not parent.is_dir():
        raise ValueError("planned path changed")


def _planned_root(vault: Path, plan: Sequence[PlannedChange]) -> Path:
    if not plan:
        return Path(vault).resolve(strict=False)
    first = plan[0]
    target = normalized_absolute(first.target)
    if first.public_path == ".":
        return target
    for _ in Path(first.public_path).parts:
        target = target.parent
    return target


def apply_plan(
    command: CommandName,
    vault: Path,
    plan: Sequence[PlannedChange],
) -> CommandResult:
    root = _planned_root(vault, plan)
    completed = 0
    for change in plan:
        try:
            if change.action == "create_directory" and change.public_path == ".":
                _validate_root_creation(root, change)
            else:
                _validate_descendant(root, change)

            if change.action == "create_directory":
                change.target.mkdir()
            elif change.action == "create_file" and change.content is not None:
                with change.target.open("x", encoding="utf-8", newline="\n") as output:
                    output.write(change.content)
            else:
                raise ValueError("invalid planned action")
        except (FileExistsError, FileNotFoundError, NotADirectoryError, ValueError):
            return CommandResult(
                ok=False,
                command=command,
                applied=True,
                vault=str(root),
                changes=_changes_with_status(plan, completed),
                issues=(
                    Issue(
                        "error",
                        "target.drifted",
                        "The target changed after preview.",
                        change.public_path,
                    ),
                ),
                exit_code=ExitCode.IO_OR_DRIFT,
            )
        except OSError:
            return CommandResult(
                ok=False,
                command=command,
                applied=True,
                vault=str(root),
                changes=_changes_with_status(plan, completed),
                issues=(
                    Issue(
                        "error",
                        "filesystem.failed",
                        "A filesystem operation failed.",
                        change.public_path,
                    ),
                ),
                exit_code=ExitCode.IO_OR_DRIFT,
            )
        completed += 1

    return CommandResult(
        ok=True,
        command=command,
        applied=True,
        vault=str(root),
        changes=_changes_with_status(plan, completed),
    )


def write_default_pointer(
    vault: Path,
    environ: Mapping[str, str],
    home: Path,
) -> None:
    pointer = default_pointer_path(environ, home)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        {"default_vault": str(Path(vault).resolve())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{pointer.name}.", suffix=".tmp", dir=pointer.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = None
            output.write(content)
        os.replace(temporary, pointer)
        temporary = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _planned_changes(plan: Sequence[PlannedChange]) -> tuple[Change, ...]:
    return tuple(Change(change.action, change.public_path, "planned") for change in plan)


def _error_result(command: CommandName, vault: Path, error: ThreadrootError) -> CommandResult:
    return CommandResult(
        ok=False,
        command=command,
        applied=False,
        vault=str(vault),
        issues=(Issue("error", error.code, error.message, error.path),),
        exit_code=error.exit_code,
    )


def run_init(
    vault: Path,
    apply: bool,
    set_default: bool,
    environ: Mapping[str, str],
    home: Path,
) -> CommandResult:
    root = Path(vault).resolve(strict=False)
    try:
        vault_plan = plan_init(root)
        pointer_change = (
            PlannedChange(
                "write_default_pointer",
                default_pointer_path(environ, home),
                "machine-default-pointer",
            )
            if set_default
            else None
        )
    except ThreadrootError as error:
        return _error_result("init", root, error)

    full_plan = vault_plan + ((pointer_change,) if pointer_change is not None else ())
    if not apply:
        return CommandResult(
            ok=True,
            command="init",
            applied=False,
            vault=str(root),
            changes=_planned_changes(full_plan),
        )

    result = apply_plan("init", root, vault_plan)
    if not result.ok:
        if set_default:
            return CommandResult(
                ok=False,
                command="init",
                applied=result.applied,
                vault=result.vault,
                changes=result.changes
                + (Change("write_default_pointer", "machine-default-pointer", "unexecuted"),),
                issues=result.issues,
                exit_code=result.exit_code,
            )
        return result

    if not set_default:
        return result
    try:
        write_default_pointer(root, environ, home)
    except OSError:
        return CommandResult(
            ok=False,
            command="init",
            applied=True,
            vault=str(root),
            changes=result.changes
            + (Change("write_default_pointer", "machine-default-pointer", "unexecuted"),),
            issues=(
                Issue(
                    "error",
                    "filesystem.failed",
                    "The default vault pointer could not be written.",
                    "machine-default-pointer",
                ),
            ),
            exit_code=ExitCode.IO_OR_DRIFT,
        )
    return CommandResult(
        ok=True,
        command="init",
        applied=True,
        vault=str(root),
        changes=result.changes
        + (Change("write_default_pointer", "machine-default-pointer", "completed"),),
    )
