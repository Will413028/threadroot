from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import stat
import tempfile

from .config import config_text, load_config
from .paths import (
    MARKER_RELATIVE,
    default_pointer_path,
    ensure_within,
    ensure_outside_secrets,
    ensure_claim_target,
    filesystem_error,
    normalized_absolute,
    resolve_path,
    validate_default_pointer,
)
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

REQUIRED_ADOPT_DIRECTORIES = (
    "daily",
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
    except ThreadrootError as error:
        if error.exit_code == ExitCode.CONFIG:
            raise _config_path_invalid() from None
        raise

    for relative in (
        config.paths.daily,
        config.paths.projects,
        config.paths.knowledge,
        config.paths.reviews,
    ):
        try:
            configured = ensure_outside_secrets(vault, relative)
        except ThreadrootError as error:
            if error.exit_code == ExitCode.CONFIG:
                raise _config_path_invalid() from None
            raise
        if not configured.is_dir():
            raise _config_path_invalid()
    return True


def plan_init(vault: Path) -> tuple[PlannedChange, ...]:
    root = resolve_path(vault)
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


def _validate_existing_adopt_marker(vault: Path) -> None:
    config = load_config(vault)
    for relative in (
        config.paths.daily,
        config.paths.projects,
        config.paths.knowledge,
        config.paths.reviews,
    ):
        configured = ensure_outside_secrets(vault, relative)
        if not configured.is_dir():
            raise _config_path_invalid()


def plan_adopt(vault: Path) -> tuple[PlannedChange, ...]:
    root = resolve_path(vault)
    marker = root / MARKER_RELATIVE
    if os.path.lexists(marker):
        _validate_existing_adopt_marker(root)
        return ()

    if not root.is_dir():
        raise ThreadrootError(
            ExitCode.CONFLICT,
            "layout.unrecognized",
            "Vault layout is missing or has invalid directories: .",
        )

    invalid_directories: list[str] = []
    for relative in REQUIRED_ADOPT_DIRECTORIES:
        configured = ensure_outside_secrets(root, relative)
        if not configured.is_dir():
            invalid_directories.append(relative)
    if invalid_directories:
        raise ThreadrootError(
            ExitCode.CONFLICT,
            "layout.unrecognized",
            "Vault layout is missing or has invalid directories: "
            + ", ".join(sorted(invalid_directories)),
        )

    marker_directory = ensure_outside_secrets(root, ".second-brain")
    changes: list[PlannedChange] = []
    if os.path.lexists(root / ".second-brain"):
        if not marker_directory.is_dir():
            raise ThreadrootError(
                ExitCode.CONFLICT,
                "target.conflict",
                "The .second-brain marker directory is not a directory.",
            )
    else:
        changes.append(PlannedChange("create_directory", root / ".second-brain", ".second-brain"))
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


def plan_claim(vault: Path, relative: str) -> tuple[PlannedChange, ...]:
    root = resolve_path(vault)
    config = load_config(root)
    content_paths = {key: getattr(config.paths, key)
                     for key in ("daily", "projects", "knowledge", "reviews")}
    target = ensure_claim_target(root, relative, content_paths)
    public_path = target.relative_to(root).as_posix()
    if os.path.lexists(target):
        raise ThreadrootError(ExitCode.CONFLICT, "target.conflict",
                              "Target already exists; choose another path.", public_path)
    if not target.parent.is_dir():
        raise ThreadrootError(ExitCode.IO_OR_DRIFT, "filesystem.failed",
                              "Claim requires an existing directory parent.", public_path)
    return (PlannedChange("create_file", target, public_path, ""),)


def _validate_claim(vault: Path, change: PlannedChange) -> None:
    config = load_config(vault)
    content_paths = {key: getattr(config.paths, key)
                     for key in ("daily", "projects", "knowledge", "reviews")}
    target = ensure_claim_target(vault, change.public_path, content_paths)
    if target != change.target:
        raise ValueError("claim target changed")
    _require_directory(vault)
    _require_directory(target.parent)


def _safe_resolve(path: Path, *, strict: bool) -> Path:
    try:
        return path.resolve(strict=strict)
    except RuntimeError as error:
        raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), path) from error


def _resolve_precondition(path: Path, *, strict: bool) -> Path:
    try:
        return _safe_resolve(path, strict=strict)
    except (FileNotFoundError, NotADirectoryError):
        raise ValueError("planned path changed") from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("planned path changed") from None
        raise


def _require_directory(path: Path) -> None:
    try:
        mode = path.stat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        raise ValueError("planned directory changed") from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError("planned directory changed") from None
        raise
    if not stat.S_ISDIR(mode):
        raise ValueError("planned directory changed")


def _validate_root_creation(vault: Path, change: PlannedChange) -> None:
    if (
        change.public_path != "."
        or _resolve_precondition(change.target, strict=False) != vault
    ):
        raise ValueError("planned vault root changed")
    _require_directory(change.target.parent)


def _validate_descendant(vault: Path, change: PlannedChange) -> None:
    _require_directory(vault)
    if _resolve_precondition(vault, strict=True) != vault:
        raise ValueError("vault root changed")
    relative = change.target.relative_to(vault).as_posix()
    parent = _resolve_precondition(change.target.parent, strict=True)
    try:
        parent.relative_to(vault)
    except ValueError:
        raise ValueError("planned path changed") from None
    if relative != change.public_path:
        raise ValueError("planned path changed")
    _require_directory(parent)


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
            if command == "claim":
                _validate_claim(root, change)
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
        except ThreadrootError as error:
            return CommandResult(
                ok=False, command=command, applied=True, vault=str(root),
                changes=_changes_with_status(plan, completed),
                issues=(Issue("error", error.code, error.message, error.path),),
                exit_code=error.exit_code,
            )
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
    content = json.dumps(
        {"default_vault": str(_safe_resolve(Path(vault), strict=True))},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    validate_default_pointer(vault, pointer)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        validate_default_pointer(vault, pointer)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{pointer.name}.", suffix=".tmp", dir=pointer.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = None
            output.write(content)
        validate_default_pointer(vault, pointer)
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


_DOCTOR_REMEDIATIONS = {
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


def _doctor_issue(issue: Issue) -> Issue:
    if issue.level != "error" or " Remediation: " in issue.message:
        return issue
    return Issue(issue.level, issue.code,
                 issue.message + " Remediation: " + _DOCTOR_REMEDIATIONS[issue.code],
                 issue.path)


def _error_result(command: CommandName, vault: Path | None, error: ThreadrootError) -> CommandResult:
    issue = Issue("error", error.code, error.message, error.path)
    if command == "doctor":
        issue = _doctor_issue(issue)
    return CommandResult(
        ok=False,
        command=command,
        applied=False,
        vault=str(vault) if vault is not None else None,
        issues=(issue,),
        exit_code=error.exit_code,
    )


def run_claim(vault: Path, relative: str, apply: bool) -> CommandResult:
    root = None
    try:
        root = resolve_path(vault)
        plan = plan_claim(root, relative)
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return _error_result("claim", root, error)
    if not apply:
        return CommandResult(ok=True, command="claim", applied=False,
                             vault=str(root), changes=_planned_changes(plan))
    return apply_plan("claim", root, plan)


def run_init(
    vault: Path,
    apply: bool,
    set_default: bool,
    environ: Mapping[str, str],
    home: Path,
) -> CommandResult:
    root = None
    try:
        root = resolve_path(vault)
        vault_plan = plan_init(root)
        pointer_change = (
            PlannedChange(
                "write_default_pointer",
                validate_default_pointer(root, default_pointer_path(environ, home)),
                "machine-default-pointer",
            )
            if set_default
            else None
        )
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
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

    try:
        if pointer_change is not None:
            validate_default_pointer(root, pointer_change.target)
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return _error_result("init", root, error)
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
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
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
                    error.code,
                    error.message,
                    "machine-default-pointer",
                ),
            ),
            exit_code=error.exit_code,
        )
    return CommandResult(
        ok=True,
        command="init",
        applied=True,
        vault=str(root),
        changes=result.changes
        + (Change("write_default_pointer", "machine-default-pointer", "completed"),),
    )


def run_adopt(
    vault: Path,
    apply: bool,
    set_default: bool,
    environ: Mapping[str, str],
    home: Path,
) -> CommandResult:
    root = None
    try:
        root = resolve_path(vault)
        vault_plan = plan_adopt(root)
        pointer_change = (
            PlannedChange(
                "write_default_pointer",
                validate_default_pointer(root, default_pointer_path(environ, home)),
                "machine-default-pointer",
            )
            if set_default
            else None
        )
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return _error_result("adopt", root, error)

    full_plan = vault_plan + ((pointer_change,) if pointer_change is not None else ())
    if not apply:
        return CommandResult(
            ok=True,
            command="adopt",
            applied=False,
            vault=str(root),
            changes=_planned_changes(full_plan),
        )

    try:
        if pointer_change is not None:
            validate_default_pointer(root, pointer_change.target)
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return _error_result("adopt", root, error)
    result = apply_plan("adopt", root, vault_plan)
    if not result.ok:
        if set_default:
            return CommandResult(
                ok=False,
                command="adopt",
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
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return CommandResult(
            ok=False,
            command="adopt",
            applied=True,
            vault=str(root),
            changes=result.changes
            + (Change("write_default_pointer", "machine-default-pointer", "unexecuted"),),
            issues=(
                Issue(
                    "error",
                    error.code,
                    error.message,
                    "machine-default-pointer",
                ),
            ),
            exit_code=error.exit_code,
        )
    return CommandResult(
        ok=True,
        command="adopt",
        applied=True,
        vault=str(root),
        changes=result.changes
        + (Change("write_default_pointer", "machine-default-pointer", "completed"),),
    )


_ISSUE_SEVERITY = {"error": 0, "warning": 1, "info": 2}


def _doctor_result(
    root: Path,
    issues: Sequence[Issue],
    *,
    unsafe: bool = False,
    error_exit: ExitCode | None = None,
) -> CommandResult:
    ordered = tuple(
        sorted(
            (_doctor_issue(issue) for issue in issues),
            key=lambda issue: (
                _ISSUE_SEVERITY[issue.level],
                issue.code,
                issue.path or "",
            ),
        )
    )
    has_errors = any(issue.level == "error" for issue in ordered)
    exit_code = error_exit if error_exit is not None else (
        ExitCode.UNSAFE_PATH
        if unsafe
        else ExitCode.CONFIG
        if has_errors
        else ExitCode.OK
    )
    return CommandResult(
        ok=not has_errors,
        command="doctor",
        applied=False,
        vault=str(root),
        changes=(),
        issues=ordered,
        exit_code=exit_code,
    )


def run_doctor(vault: Path) -> CommandResult:
    try:
        return _inspect_doctor(vault)
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return _error_result("doctor", None, error)


def _inspect_doctor(vault: Path) -> CommandResult:
    root = normalized_absolute(vault)
    try:
        root = resolve_path(root)
    except ThreadrootError as error:
        return _doctor_result(
            root,
            (Issue("error", error.code, error.message, "."),),
            unsafe=error.exit_code == ExitCode.UNSAFE_PATH,
            error_exit=error.exit_code,
        )
    issues: list[Issue] = []

    if not root.exists():
        issues.append(
            Issue("error", "vault.not_found", "Vault root does not exist.", ".")
        )
        return _doctor_result(root, issues)
    if not root.is_dir():
        issues.append(
            Issue(
                "error",
                "vault.not_directory",
                "Vault root is not a directory.",
                ".",
            )
        )
        return _doctor_result(root, issues)

    marker = root / MARKER_RELATIVE
    try:
        ensure_outside_secrets(root, MARKER_RELATIVE)
    except ThreadrootError as error:
        issues.append(
            Issue("error", error.code, error.message, MARKER_RELATIVE.as_posix())
        )
        if not (root / ".git").exists():
            issues.append(Issue("info", "git.not_found", "Git metadata was not found.", ".git"))
        return _doctor_result(root, issues, error_exit=error.exit_code)

    if not marker.is_file() or not os.access(marker, os.R_OK):
        issues.append(
            Issue(
                "error",
                "config.invalid",
                "Vault config is not a readable file.",
                MARKER_RELATIVE.as_posix(),
            )
        )
        if not (root / ".git").exists():
            issues.append(Issue("info", "git.not_found", "Git metadata was not found.", ".git"))
        return _doctor_result(root, issues)

    try:
        config = load_config(root)
    except ThreadrootError as error:
        issues.append(Issue("error", error.code, error.message, error.path))
        if not (root / ".git").exists():
            issues.append(Issue("info", "git.not_found", "Git metadata was not found.", ".git"))
        return _doctor_result(root, issues, error_exit=error.exit_code)

    unsafe = False
    error_exit: ExitCode | None = None
    for relative in (
        config.paths.daily,
        config.paths.projects,
        config.paths.knowledge,
        config.paths.reviews,
    ):
        try:
            target = ensure_outside_secrets(root, relative)
        except ThreadrootError as error:
            issues.append(Issue("error", error.code, error.message, relative))
            unsafe = unsafe or error.exit_code == ExitCode.UNSAFE_PATH
            if error.exit_code == ExitCode.IO_OR_DRIFT:
                error_exit = error.exit_code
            continue
        if not target.exists():
            issues.append(
                Issue(
                    "error",
                    "path.not_found",
                    "Configured directory does not exist.",
                    relative,
                )
            )
        elif not target.is_dir():
            issues.append(
                Issue(
                    "error",
                    "path.not_directory",
                    "Configured path is not a directory.",
                    relative,
                )
            )
        else:
            if not os.access(target, os.R_OK):
                issues.append(
                    Issue(
                        "error",
                        "path.not_readable",
                        "Configured directory is not readable.",
                        relative,
                    )
                )
            if not os.access(target, os.W_OK):
                issues.append(
                    Issue(
                        "warning",
                        "path.not_writable",
                        "Configured directory is not writable.",
                        relative,
                    )
                )

    if not (root / ".git").exists():
        issues.append(Issue("info", "git.not_found", "Git metadata was not found.", ".git"))
    return _doctor_result(root, issues, unsafe=unsafe, error_exit=error_exit)
