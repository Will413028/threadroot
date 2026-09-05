from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import cast, Sequence


CASE_KEYS = frozenset(
    {
        "name",
        "request",
        "allowed_reads",
        "expected_writes",
        "required_headings",
        "required_links",
        "forbidden_actions",
        "fixture_files",
        "fixture_directories",
        "forbidden_paths",
    }
)
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*$")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]\r\n]+)\]\]")
MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!!)\[[^\]\r\n]*\]\(\s*(?:<([^>\r\n]+)>|([^\s)\r\n]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW
DIRECTORY_FLAGS = READ_FLAGS | getattr(os, "O_DIRECTORY", 0)


class ContractError(ValueError):
    """A controlled contract, path, or filesystem rejection."""


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    sha256: str
    headings: tuple[str, ...]
    document_links: tuple[str, ...]


@dataclass(frozen=True)
class LinkSnapshot:
    path: str
    target_sha256: str


@dataclass(frozen=True)
class VaultSnapshot:
    files: tuple[FileSnapshot, ...]
    directories: tuple[str, ...]
    links: tuple[LinkSnapshot, ...]


@dataclass(frozen=True)
class ContractFailure:
    code: str
    path: str
    message: str


def _reject() -> None:
    raise ContractError("contract is invalid")


def _require_nofollow() -> None:
    if not NOFOLLOW or not getattr(os, "O_DIRECTORY", 0):
        _reject()


def _path(value: object, *, allow_dot: bool = False) -> str:
    if type(value) is not str or not value or "\0" in value or "\\" in value:
        _reject()
    if value == ".":
        if allow_dot:
            return value
        _reject()
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        _reject()
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _reject()
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.as_posix() != value:
        _reject()
    return value


def _string(value: object) -> str:
    if type(value) is not str or not value:
        _reject()
    return value


def _string_list(value: object) -> list[str]:
    if type(value) is not list:
        _reject()
    result = [_string(item) for item in value]
    if len(result) != len(set(result)):
        _reject()
    return result


def _path_list(value: object, *, allow_dot: bool = False) -> list[str]:
    if type(value) is not list:
        _reject()
    result = [_path(item, allow_dot=allow_dot) for item in value]
    if len(result) != len(set(result)):
        _reject()
    return result


def _path_mapping(value: object) -> dict[str, list[str]]:
    if type(value) is not dict:
        _reject()
    result: dict[str, list[str]] = {}
    for raw_path, raw_values in value.items():
        path = _path(raw_path)
        result[path] = _string_list(raw_values)
    return result


def _file_mapping(value: object) -> dict[str, str]:
    if type(value) is not dict:
        _reject()
    result: dict[str, str] = {}
    for raw_path, raw_payload in value.items():
        path = _path(raw_path)
        if type(raw_payload) is not str:
            _reject()
        result[path] = raw_payload
    return result


def _parent(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _at_or_below(path: str, parent: str) -> bool:
    return parent == "." or path == parent or path.startswith(parent + "/")


def _validate_case(case: object) -> dict[str, object]:
    if type(case) is not dict or set(case) != CASE_KEYS:
        _reject()

    name = _string(case["name"])
    request = _string(case["request"])
    allowed_reads = _path_list(case["allowed_reads"])
    expected_writes = _path_list(case["expected_writes"])
    required_headings = _path_mapping(case["required_headings"])
    required_links = _path_mapping(case["required_links"])
    forbidden_actions = _string_list(case["forbidden_actions"])
    fixture_files = _file_mapping(case["fixture_files"])
    fixture_directories = _path_list(case["fixture_directories"])
    forbidden_paths = _path_list(case["forbidden_paths"], allow_dot=True)

    if "." in forbidden_paths and forbidden_paths != ["."]:
        _reject()

    expected_set = set(expected_writes)
    directory_set = set(fixture_directories)
    file_set = set(fixture_files)
    if set(required_headings) != expected_set:
        _reject()
    if not set(required_links).issubset(expected_set):
        _reject()
    if not set(allowed_reads).issubset(file_set):
        _reject()
    if file_set & directory_set or expected_set & directory_set:
        _reject()

    declared = file_set | directory_set
    for file_path in file_set:
        if _parent(file_path) not in directory_set | {""}:
            _reject()
        if any(
            other != file_path and other.startswith(file_path + "/")
            for other in declared
        ):
            _reject()
    for directory in directory_set:
        if _parent(directory) not in directory_set | {""}:
            _reject()
    for expected in expected_set:
        if _parent(expected) not in directory_set | {""}:
            _reject()
    return {
        "name": name,
        "request": request,
        "allowed_reads": allowed_reads,
        "expected_writes": expected_writes,
        "required_headings": required_headings,
        "required_links": required_links,
        "forbidden_actions": forbidden_actions,
        "fixture_files": fixture_files,
        "fixture_directories": fixture_directories,
        "forbidden_paths": forbidden_paths,
    }


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _lstat_at(parent_fd: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        _reject()


def _open_at(
    parent_fd: int,
    name: str,
    flags: int,
    expected: os.stat_result,
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        _reject()
    if _stat_signature(opened) != _stat_signature(expected):
        os.close(descriptor)
        _reject()
    return descriptor


def _read_regular(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
) -> bytes:
    descriptor = _open_at(parent_fd, name, READ_FLAGS, expected)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after_read = os.fstat(descriptor)
        current = _lstat_at(parent_fd, name)
        if (
            _stat_signature(after_read) != _stat_signature(expected)
            or _stat_signature(current) != _stat_signature(expected)
        ):
            _reject()
        return b"".join(chunks)
    except OSError:
        _reject()
    finally:
        os.close(descriptor)


def _normalize_destination(value: str) -> str:
    destination = value.strip().split("|", 1)[0].strip()
    destination = destination.split("#", 1)[0].strip()
    if destination.endswith(".md"):
        destination = destination[:-3]
    return destination


def _markdown_structure(payload: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return (), ()

    headings = []
    for line in text.splitlines():
        match = HEADING_PATTERN.match(line)
        if match:
            headings.append(match.group(1))

    destinations = []
    for match in WIKILINK_PATTERN.finditer(text):
        normalized = _normalize_destination(match.group(1))
        if normalized:
            destinations.append(normalized)
    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        normalized = _normalize_destination(match.group(1) or match.group(2))
        if normalized:
            destinations.append(normalized)
    return tuple(sorted(headings)), tuple(sorted(set(destinations)))


def _walk_snapshot(
    descriptor: int,
    prefix: str,
    files: list[FileSnapshot],
    directories: list[str],
    links: list[LinkSnapshot],
) -> None:
    try:
        names = sorted(os.listdir(descriptor))
    except OSError:
        _reject()
    for name in names:
        relative = name if not prefix else f"{prefix}/{name}"
        metadata = _lstat_at(descriptor, name)
        if stat.S_ISLNK(metadata.st_mode):
            try:
                target = os.readlink(name, dir_fd=descriptor)
            except OSError:
                _reject()
            current = _lstat_at(descriptor, name)
            if _stat_signature(current) != _stat_signature(metadata):
                _reject()
            links.append(
                LinkSnapshot(
                    relative,
                    hashlib.sha256(os.fsencode(target)).hexdigest(),
                )
            )
            continue
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(relative)
            child_fd = _open_at(descriptor, name, DIRECTORY_FLAGS, metadata)
            try:
                _walk_snapshot(child_fd, relative, files, directories, links)
                current = _lstat_at(descriptor, name)
                if _stat_signature(current) != _stat_signature(metadata):
                    _reject()
            finally:
                os.close(child_fd)
            continue
        if stat.S_ISREG(metadata.st_mode):
            payload = _read_regular(descriptor, name, metadata)
            headings: tuple[str, ...] = ()
            document_links: tuple[str, ...] = ()
            if relative.lower().endswith(".md"):
                headings, document_links = _markdown_structure(payload)
            files.append(
                FileSnapshot(
                    relative,
                    hashlib.sha256(payload).hexdigest(),
                    headings,
                    document_links,
                )
            )
            continue
        _reject()


def _open_root(root: Path) -> tuple[int, os.stat_result]:
    _require_nofollow()
    descriptor: int | None = None
    try:
        metadata = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode):
            _reject()
        descriptor = os.open(root, DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
    except ContractError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        _reject()
    if _stat_signature(opened) != _stat_signature(metadata):
        os.close(descriptor)
        _reject()
    return descriptor, metadata


def snapshot(root: Path) -> VaultSnapshot:
    root = Path(root)
    descriptor, metadata = _open_root(root)
    files: list[FileSnapshot] = []
    directories: list[str] = []
    links: list[LinkSnapshot] = []
    try:
        _walk_snapshot(descriptor, "", files, directories, links)
        try:
            current = os.stat(root, follow_symlinks=False)
        except OSError:
            _reject()
        if _stat_signature(current) != _stat_signature(metadata):
            _reject()
    finally:
        os.close(descriptor)
    return VaultSnapshot(
        files=tuple(sorted(files, key=lambda item: item.path)),
        directories=tuple(sorted(directories)),
        links=tuple(sorted(links, key=lambda item: item.path)),
    )


def _open_output(output: Path) -> tuple[int, os.stat_result]:
    _require_nofollow()
    try:
        metadata = os.stat(output, follow_symlinks=False)
    except FileNotFoundError:
        parent_fd: int | None = None
        try:
            parent_metadata = os.stat(output.parent, follow_symlinks=False)
            if not stat.S_ISDIR(parent_metadata.st_mode):
                _reject()
            parent_fd = os.open(output.parent, DIRECTORY_FLAGS)
            if _stat_signature(os.fstat(parent_fd)) != _stat_signature(parent_metadata):
                _reject()
            os.mkdir(output.name, mode=0o755, dir_fd=parent_fd)
            metadata = _lstat_at(parent_fd, output.name)
        except ContractError:
            raise
        except OSError:
            _reject()
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
    except OSError:
        _reject()

    if not stat.S_ISDIR(metadata.st_mode):
        _reject()
    descriptor: int | None = None
    try:
        descriptor = os.open(output, DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        if _stat_signature(opened) != _stat_signature(metadata):
            _reject()
        if os.listdir(descriptor):
            _reject()
    except ContractError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        _reject()
    return descriptor, metadata


def _write_exclusive(parent_fd: int, name: str, payload: bytes) -> None:
    descriptor: int | None = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW
    try:
        descriptor = os.open(name, flags, 0o644, dir_fd=parent_fd)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                _reject()
            offset += written
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            _reject()
    except ContractError:
        raise
    except OSError:
        _reject()
    finally:
        if descriptor is not None:
            os.close(descriptor)
    current = _lstat_at(parent_fd, name)
    if _stat_signature(current) != _stat_signature(opened):
        _reject()


def materialize_fixture(case: object, output: Path) -> None:
    prepared = _validate_case(case)
    output = Path(output)
    root_fd, root_metadata = _open_output(output)
    descriptors: dict[str, int] = {"": root_fd}
    directory_metadata: dict[str, tuple[str, str, os.stat_result]] = {}
    try:
        directories = cast(list[str], prepared["fixture_directories"])
        for relative in sorted(directories, key=lambda item: (item.count("/"), item)):
            parent = _parent(relative)
            name = PurePosixPath(relative).name
            parent_fd = descriptors[parent]
            try:
                os.mkdir(name, mode=0o755, dir_fd=parent_fd)
            except OSError:
                _reject()
            metadata = _lstat_at(parent_fd, name)
            if not stat.S_ISDIR(metadata.st_mode):
                _reject()
            descriptors[relative] = _open_at(
                parent_fd, name, DIRECTORY_FLAGS, metadata
            )
            directory_metadata[relative] = (parent, name, metadata)

        fixture_files = cast(dict[str, str], prepared["fixture_files"])
        for relative in sorted(fixture_files):
            parent = _parent(relative)
            name = PurePosixPath(relative).name
            payload = fixture_files[relative]
            _write_exclusive(descriptors[parent], name, payload.encode("utf-8"))

        for relative in sorted(directory_metadata, reverse=True):
            parent, name, expected = directory_metadata[relative]
            current = _lstat_at(descriptors[parent], name)
            if _identity(current) != _identity(expected):
                _reject()
        try:
            current_root = os.stat(output, follow_symlinks=False)
        except OSError:
            _reject()
        if _identity(current_root) != _identity(root_metadata):
            _reject()
    finally:
        for relative in sorted(descriptors, key=lambda item: item.count("/"), reverse=True):
            os.close(descriptors[relative])


def _entries(value: VaultSnapshot) -> dict[str, tuple[str, str]]:
    entries = {item.path: ("file", item.sha256) for item in value.files}
    entries.update({path: ("directory", "") for path in value.directories})
    entries.update({item.path: ("link", item.target_sha256) for item in value.links})
    return entries


def _failure(code: str, path: str) -> ContractFailure:
    messages = {
        "contract.invalid": "contract is invalid",
        "missing_expected_write": "expected file write is missing",
        "missing_heading": "required heading is missing",
        "missing_link": "required document link is missing",
        "unexpected_write": "path changed outside the write contract",
        "forbidden_write": "forbidden path changed",
    }
    return ContractFailure(code, path, messages[code])


def validate_contract(
    case: object,
    before: Path,
    after: Path,
) -> list[ContractFailure]:
    try:
        prepared = _validate_case(case)
    except ContractError:
        return [_failure("contract.invalid", ".")]

    try:
        before_snapshot = snapshot(Path(before))
        after_snapshot = snapshot(Path(after))
    except ContractError:
        return [_failure("contract.invalid", ".")]

    before_entries = _entries(before_snapshot)
    after_entries = _entries(after_snapshot)
    all_paths = set(before_entries) | set(after_entries)
    changed = {
        path for path in all_paths if before_entries.get(path) != after_entries.get(path)
    }
    expected = set(cast(list[str], prepared["expected_writes"]))
    forbidden_paths = cast(list[str], prepared["forbidden_paths"])
    failures: dict[tuple[str, str], ContractFailure] = {}

    def add(code: str, path: str) -> None:
        failures[(code, path)] = _failure(code, path)

    for path in changed:
        if path not in expected:
            add("unexpected_write", path)
        if any(_at_or_below(path, forbidden) for forbidden in forbidden_paths):
            add("forbidden_write", path)

    final_files = {item.path: item for item in after_snapshot.files}
    required_headings = cast(dict[str, list[str]], prepared["required_headings"])
    required_links = cast(dict[str, list[str]], prepared["required_links"])
    for path in expected:
        final_file = final_files.get(path)
        if path not in changed or final_file is None:
            add("missing_expected_write", path)
        if final_file is None:
            continue
        headings = set(final_file.headings)
        if not set(required_headings[path]).issubset(headings):
            add("missing_heading", path)
        links = set(final_file.document_links)
        if not set(required_links.get(path, [])).issubset(links):
            add("missing_link", path)

    return [failures[key] for key in sorted(failures)]


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _load_case(path: Path) -> object:
    _require_nofollow()
    descriptor: int | None = None
    try:
        metadata = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            _reject()
        descriptor = os.open(path, READ_FLAGS)
        if _stat_signature(os.fstat(descriptor)) != _stat_signature(metadata):
            _reject()
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after_read = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        if (
            _stat_signature(after_read) != _stat_signature(metadata)
            or _stat_signature(current) != _stat_signature(metadata)
        ):
            _reject()
        return json.loads(
            b"".join(chunks).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except ContractError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _reject()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a synthetic vault contract")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--case", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--case", type=Path, required=True)
    validate.add_argument("--before", type=Path, required=True)
    validate.add_argument("--after", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        case = _load_case(arguments.case)
        if arguments.mode == "materialize":
            materialize_fixture(case, arguments.output)
            print("PASS")
            return 0

        failures = validate_contract(case, arguments.before, arguments.after)
        if not failures:
            print("PASS")
            return 0
        for failure in failures:
            print(f"FAIL {failure.code} {failure.path}")
        return 1
    except Exception:
        print("FAIL contract.invalid .")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
