from __future__ import annotations

import errno
import os
from collections.abc import Mapping
from pathlib import Path

from .jsonio import loads_unique_json
from .results import ExitCode, ThreadrootError


MARKER_RELATIVE = Path(".second-brain/config.json")


def normalized_absolute(path: str | Path) -> Path:
    """Return an absolute lexical path without following symlinks."""
    return Path(os.path.abspath(path))


def _invalid_config(message: str) -> ThreadrootError:
    return ThreadrootError(ExitCode.CONFIG, "config.invalid", message)


def _unsafe_path() -> ThreadrootError:
    return ThreadrootError(ExitCode.UNSAFE_PATH, "path.unsafe", "Path escapes the vault.")


def resolve_path(path: str | Path, *, strict: bool = False) -> Path:
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=strict)
    except RuntimeError:
        raise _unsafe_path() from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise _unsafe_path() from None
        raise

    try:
        candidate.stat()
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise _unsafe_path() from None
    return resolved


def ensure_within(root: Path, relative: str | Path) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise _unsafe_path()

    resolved_root = resolve_path(root)
    resolved_candidate = resolve_path(resolved_root / candidate)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise _unsafe_path() from error
    return resolved_candidate


def find_upward(start: Path) -> Path | None:
    current = resolve_path(start)
    while True:
        marker = current / MARKER_RELATIVE
        if marker.is_file():
            ensure_within(current, MARKER_RELATIVE)
            return current
        if current.parent == current:
            return None
        current = current.parent


def default_pointer_path(environ: Mapping[str, str], home: Path) -> Path:
    xdg_config_home = environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        if not isinstance(xdg_config_home, str) or not Path(xdg_config_home).is_absolute():
            raise _invalid_config("XDG_CONFIG_HOME must be an absolute path.")
        base = Path(xdg_config_home)
    else:
        base = Path(home) / ".config"
    return base / "threadroot" / "config.json"


def read_default_pointer(path: Path) -> Path | None:
    if not path.exists():
        return None
    if not path.is_file() or not os.access(path, os.R_OK):
        raise _invalid_config("Default vault pointer is not a readable file.")
    try:
        document = loads_unique_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise _invalid_config("Default vault pointer is invalid.") from None
    if type(document) is not dict or set(document) != {"default_vault"}:
        raise _invalid_config("Default vault pointer is invalid.")
    value = document["default_vault"]
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise _invalid_config("Default vault pointer is invalid.")
    return resolve_path(value)


def _normalize_root(value: str | Path, cwd: Path) -> Path:
    try:
        candidate = Path(value)
    except TypeError:
        raise _invalid_config("Vault path is invalid.") from None
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    return resolve_path(candidate)


def resolve_vault(
    explicit: str | Path | None,
    cwd: Path,
    environ: Mapping[str, str],
    home: Path,
) -> Path:
    if explicit:
        return _normalize_root(explicit, cwd)

    environment_root = environ.get("SECOND_BRAIN_ROOT")
    if environment_root:
        return _normalize_root(environment_root, cwd)

    upward = find_upward(cwd)
    if upward is not None:
        return upward

    pointer = read_default_pointer(default_pointer_path(environ, home))
    if pointer is not None:
        return pointer
    raise ThreadrootError(
        ExitCode.CONFIG, "vault.unresolved", "Pass --vault to select a vault."
    )
