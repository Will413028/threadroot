from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from .jsonio import loads_unique_json
from .paths import MARKER_RELATIVE, ensure_within
from .results import ExitCode, ThreadrootError


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


def _invalid_config(message: str) -> ThreadrootError:
    return ThreadrootError(ExitCode.CONFIG, "config.invalid", message)


def config_text() -> str:
    return json.dumps(
        {
            "schema_version": DEFAULT_CONFIG.schema_version,
            "paths": {
                "daily": DEFAULT_CONFIG.paths.daily,
                "projects": DEFAULT_CONFIG.paths.projects,
                "knowledge": DEFAULT_CONFIG.paths.knowledge,
                "reviews": DEFAULT_CONFIG.paths.reviews,
            },
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def load_config(root: Path) -> VaultConfig:
    marker = ensure_within(root, MARKER_RELATIVE)
    if not marker.is_file() or not os.access(marker, os.R_OK):
        raise _invalid_config("Vault config is not a readable file.")
    try:
        document = loads_unique_json(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise _invalid_config("Vault config is invalid.") from None

    if type(document) is not dict or set(document) != {"schema_version", "paths"}:
        raise _invalid_config("Vault config is invalid.")
    schema_version = document["schema_version"]
    if type(schema_version) is not int:
        raise _invalid_config("Vault config is invalid.")
    if schema_version != 1:
        raise ThreadrootError(
            ExitCode.CONFIG,
            "config.unsupported_version",
            "Vault config schema version is unsupported.",
        )

    paths = document["paths"]
    expected_paths = {"daily", "projects", "knowledge", "reviews"}
    if type(paths) is not dict or set(paths) != expected_paths:
        raise _invalid_config("Vault config is invalid.")
    for value in paths.values():
        if not isinstance(value, str) or not value.strip():
            raise _invalid_config("Vault config is invalid.")
        ensure_within(root, value)
    return VaultConfig(schema_version=schema_version, paths=VaultPaths(**paths))
