from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import secrets
from typing import Any

from scripts.release_archives import ReleaseArchiveError, _load_tar_members_payload


MAX_ENTRY_COUNT = 4096
MAX_FILE_SIZE = 64 * 1024 * 1024
MAX_TOTAL_FILE_SIZE = 512 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_MANIFEST_SIZE = 8 * 1024 * 1024
MAX_RECORD_SIZE = 16 * 1024
MAX_UNSIGNED_64 = (1 << 64) - 1
MIN_SIGNED_64 = -(1 << 63)
MAX_SIGNED_64 = (1 << 63) - 1
MANIFEST_RELATIVE = PurePosixPath("build/evidence/candidate-integrity.json")
TOP_LEVEL = ("build", "source-a", "source-b")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MODE = re.compile(r"0[0-7]{3}\Z")


class CandidateIntegrityError(RuntimeError):
    """The release candidate is missing, changed, unsafe, or noncanonical."""


def _fail() -> CandidateIntegrityError:
    return CandidateIntegrityError("candidate integrity verification failed")


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


@dataclass(frozen=True)
class CandidateEntry:
    path: str
    kind: str
    mode: str
    device: int
    inode: int
    uid: int
    gid: int
    nlink: int | None = None
    size: int | None = None
    mtime_ns: int | None = None
    ctime_ns: int | None = None
    sha256: str | None = None

    def as_manifest(self) -> dict[str, object]:
        value: dict[str, object] = {
            "device": self.device, "gid": self.gid, "inode": self.inode,
            "kind": self.kind, "mode": self.mode, "path": self.path, "uid": self.uid,
        }
        if self.kind == "file":
            value.update(nlink=self.nlink, size=self.size, mtime_ns=self.mtime_ns,
                         ctime_ns=self.ctime_ns, sha256=self.sha256)
        return value


@dataclass(frozen=True)
class CandidateSnapshot:
    entries: tuple[CandidateEntry, ...]


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_uid, metadata.st_gid, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns)


def _checked_path(path: PurePosixPath) -> str:
    value = path.as_posix()
    if (not value or value.startswith("/") or value in {".", ".."}
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(ord(character) < 32 or ord(character) == 127
                   or 0xD800 <= ord(character) <= 0xDFFF for character in value)
            or len(value.encode("utf-8")) > MAX_PATH_BYTES):
        raise _fail()
    return value


def _mode(metadata: os.stat_result) -> str:
    permissions = stat.S_IMODE(metadata.st_mode)
    if permissions > 0o777:
        raise _fail()
    return f"0{permissions:03o}"


def _open_dir_at(parent_fd: int, name: str) -> tuple[int, os.stat_result]:
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise _fail()
    descriptor = os.open(
        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent_fd,
    )
    if _identity(before) != _identity(os.fstat(descriptor)):
        os.close(descriptor)
        raise _fail()
    return descriptor, before


def _hash_file(parent_fd: int, name: str, before: os.stat_result) -> str:
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE_SIZE:
        raise _fail()
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd
    )
    try:
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(before):
            raise _fail()
        digest = hashlib.sha256()
        count = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            count += len(chunk)
            if count > MAX_FILE_SIZE:
                raise _fail()
            digest.update(chunk)
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if count != before.st_size or _identity(after) != _identity(before) or _identity(current) != _identity(before):
            raise _fail()
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _walk(parent_fd: int, prefix: PurePosixPath, entries: list[CandidateEntry], totals: list[int]) -> None:
    try:
        names = sorted(os.listdir(parent_fd))
    except OSError as error:
        raise _fail() from error
    for name in names:
        relative = prefix / name
        if relative == MANIFEST_RELATIVE:
            continue
        path = _checked_path(relative)
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if len(entries) >= MAX_ENTRY_COUNT:
                raise _fail()
            if stat.S_ISDIR(metadata.st_mode):
                child, opened = _open_dir_at(parent_fd, name)
                try:
                    entry = CandidateEntry(path, "directory", _mode(opened), opened.st_dev,
                                           opened.st_ino, opened.st_uid, opened.st_gid)
                    entries.append(entry)
                    _walk(child, relative, entries, totals)
                    if _identity(os.fstat(child)) != _identity(opened):
                        raise _fail()
                    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if _identity(current) != _identity(opened):
                        raise _fail()
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1 or metadata.st_size > MAX_FILE_SIZE:
                    raise _fail()
                totals[0] += metadata.st_size
                if totals[0] > MAX_TOTAL_FILE_SIZE:
                    raise _fail()
                digest = _hash_file(parent_fd, name, metadata)
                entries.append(CandidateEntry(
                    path, "file", _mode(metadata), metadata.st_dev, metadata.st_ino,
                    metadata.st_uid, metadata.st_gid, metadata.st_nlink, metadata.st_size,
                    metadata.st_mtime_ns, metadata.st_ctime_ns, digest,
                ))
            else:
                raise _fail()
        except CandidateIntegrityError:
            raise
        except OSError as error:
            raise _fail() from error


def _capture_candidate(candidate_root: Path) -> CandidateSnapshot:
    root_fd: int | None = None
    try:
        root = Path(candidate_root)
        before = os.lstat(root)
        if not stat.S_ISDIR(before.st_mode):
            raise _fail()
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        if _identity(os.fstat(root_fd)) != _identity(before):
            raise _fail()
        if tuple(sorted(os.listdir(root_fd))) != TOP_LEVEL:
            raise _fail()
        entries: list[CandidateEntry] = []
        _walk(root_fd, PurePosixPath(), entries, [0])
        if _identity(os.fstat(root_fd)) != _identity(before) or _identity(os.lstat(root)) != _identity(before):
            raise _fail()
        return CandidateSnapshot(tuple(sorted(entries, key=lambda entry: entry.path)))
    except CandidateIntegrityError:
        raise
    except OSError as error:
        raise _fail() from error
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _git_authority(commit: str) -> dict[str, tuple[str, str, int, str | None]]:
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise _fail()
    try:
        result = subprocess.run(
            ["git", "archive", "--format=tar", commit], check=True, capture_output=True,
        )
        members = _load_tar_members_payload(result.stdout, commit)
    except (OSError, subprocess.SubprocessError, ReleaseArchiveError) as error:
        raise _fail() from error
    authority: dict[str, tuple[str, str, int, str | None]] = {}
    for path, is_directory, mode, payload in members:
        authority[path.as_posix()] = (
            "directory" if is_directory else "file", f"0{mode:03o}",
            0 if is_directory else len(payload),
            None if is_directory else hashlib.sha256(payload).hexdigest(),
        )
    return authority


def _source_authority(snapshot: CandidateSnapshot, source: str) -> dict[str, tuple[str, str, int, str | None]]:
    prefix = source + "/"
    result: dict[str, tuple[str, str, int, str | None]] = {}
    for entry in snapshot.entries:
        if entry.path.startswith(prefix):
            relative = entry.path[len(prefix):]
            result[relative] = (entry.kind, entry.mode, 0 if entry.kind == "directory" else entry.size or 0,
                                entry.sha256)
    return result


def _require_git_sources(snapshot: CandidateSnapshot, commit: str) -> None:
    expected = _git_authority(commit)
    if _source_authority(snapshot, "source-a") != expected or _source_authority(snapshot, "source-b") != expected:
        raise _fail()


def _duplicate_rejector(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _fail()
    return value


def _parse_entry(value: object) -> CandidateEntry:
    if not isinstance(value, dict):
        raise _fail()
    common = {"device", "gid", "inode", "kind", "mode", "path", "uid"}
    kind = value.get("kind")
    expected = common if kind == "directory" else common | {"nlink", "size", "mtime_ns", "ctime_ns", "sha256"}
    if set(value) != expected or kind not in {"directory", "file"}:
        raise _fail()
    path_value, mode_value = value["path"], value["mode"]
    if type(path_value) is not str or _checked_path(PurePosixPath(path_value)) != path_value:
        raise _fail()
    if type(mode_value) is not str or _MODE.fullmatch(mode_value) is None:
        raise _fail()
    common_values = dict(
        path=path_value, kind=kind, mode=mode_value,
        device=_integer(value["device"], 0, MAX_UNSIGNED_64),
        inode=_integer(value["inode"], 0, MAX_UNSIGNED_64),
        uid=_integer(value["uid"], 0, MAX_UNSIGNED_64),
        gid=_integer(value["gid"], 0, MAX_UNSIGNED_64),
    )
    if kind == "directory":
        return CandidateEntry(**common_values)
    digest = value["sha256"]
    if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
        raise _fail()
    return CandidateEntry(
        **common_values,
        nlink=_integer(value["nlink"], 1, 1),
        size=_integer(value["size"], 0, MAX_FILE_SIZE),
        mtime_ns=_integer(value["mtime_ns"], MIN_SIGNED_64, MAX_SIGNED_64),
        ctime_ns=_integer(value["ctime_ns"], MIN_SIGNED_64, MAX_SIGNED_64),
        sha256=digest,
    )


def _parse_manifest(payload: bytes, commit: str) -> CandidateSnapshot:
    if not 1 <= len(payload) <= MAX_MANIFEST_SIZE or payload.startswith(b"\xef\xbb\xbf"):
        raise _fail()
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_duplicate_rejector)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _fail() from None
    if not isinstance(document, dict) or set(document) != {"schema", "commit", "entries"}:
        raise _fail()
    if _integer(document["schema"], 1, 1) != 1 or document["commit"] != commit:
        raise _fail()
    if type(document["commit"]) is not str or _COMMIT.fullmatch(document["commit"]) is None:
        raise _fail()
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_ENTRY_COUNT:
        raise _fail()
    entries = tuple(_parse_entry(value) for value in raw_entries)
    paths = [entry.path for entry in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise _fail()
    if sum(entry.size or 0 for entry in entries) > MAX_TOTAL_FILE_SIZE:
        raise _fail()
    if _canonical_json(document) != payload:
        raise _fail()
    return CandidateSnapshot(entries)


def _read_manifest(candidate_root: Path, commit: str) -> CandidateSnapshot:
    path = Path(candidate_root) / MANIFEST_RELATIVE
    descriptor: int | None = None
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o444:
            raise _fail()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        if _identity(os.fstat(descriptor)) != _identity(before) or before.st_size > MAX_MANIFEST_SIZE:
            raise _fail()
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total += len(chunk)
            if total > MAX_MANIFEST_SIZE:
                raise _fail()
            chunks.append(chunk)
        if _identity(os.fstat(descriptor)) != _identity(before) or _identity(os.lstat(path)) != _identity(before):
            raise _fail()
        return _parse_manifest(b"".join(chunks), commit)
    except CandidateIntegrityError:
        raise
    except OSError as error:
        raise _fail() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_candidate_manifest(candidate_root: Path, commit: str) -> None:
    first = _capture_candidate(candidate_root)
    _require_git_sources(first, commit)
    payload = _canonical_json({"commit": commit, "entries": [entry.as_manifest() for entry in first.entries], "schema": 1})
    if len(payload) > MAX_MANIFEST_SIZE:
        raise _fail()
    root_fd: int | None = None
    build_fd: int | None = None
    directory_fd: int | None = None
    descriptor: int | None = None
    try:
        root_before = os.lstat(candidate_root)
        root_fd = os.open(
            candidate_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        if not stat.S_ISDIR(root_before.st_mode) or _identity(os.fstat(root_fd)) != _identity(root_before):
            raise _fail()
        build_fd, _ = _open_dir_at(root_fd, "build")
        directory_fd, _ = _open_dir_at(build_fd, "evidence")
        descriptor = os.open(
            MANIFEST_RELATIVE.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600, dir_fd=directory_fd,
        )
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o444)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o444:
            raise _fail()
    except CandidateIntegrityError:
        raise
    except OSError as error:
        raise _fail() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)
        if build_fd is not None:
            os.close(build_fd)
        if root_fd is not None:
            os.close(root_fd)
    second = _capture_candidate(candidate_root)
    if second != first:
        raise _fail()
    if _read_manifest(candidate_root, commit) != first:
        raise _fail()


def _verify_candidate_manifest(candidate_root: Path, commit: str) -> None:
    recorded = _read_manifest(candidate_root, commit)
    first = _capture_candidate(candidate_root)
    if first != recorded:
        raise _fail()
    _require_git_sources(first, commit)
    second = _capture_candidate(candidate_root)
    if second != first:
        raise _fail()


def _absolute_path(value: object) -> Path:
    if not isinstance(value, (str, Path)):
        raise _fail()
    raw = str(value)
    if (not raw or len(raw.encode("utf-8", errors="surrogatepass")) > MAX_PATH_BYTES
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in raw)):
        raise _fail()
    path = Path(raw)
    if not path.is_absolute() or str(path) != raw or ".." in path.parts:
        raise _fail()
    return path


def _directory_identity(metadata: os.stat_result) -> dict[str, object]:
    if not stat.S_ISDIR(metadata.st_mode):
        raise _fail()
    return dict(device=metadata.st_dev, inode=metadata.st_ino, uid=metadata.st_uid,
                gid=metadata.st_gid, mode=_mode(metadata))


@contextmanager
def _held_directory(path: Path):
    """Hold every real ancestor and detect renames or permission drift."""
    path = _absolute_path(path)
    with ExitStack() as stack:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        bindings = []
        for part in path.parts[1:]:
            parent = fd
            fd, before = _open_dir_at(parent, part)
            stack.callback(os.close, fd)
            bindings.append((parent, part, fd, _directory_identity(before)))
        def check():
            for parent, part, child, identity in bindings:
                if (_directory_identity(os.fstat(child)) != identity
                        or _directory_identity(os.stat(part, dir_fd=parent, follow_symlinks=False)) != identity):
                    raise _fail()
        check()
        yield fd, check
        check()


def _repository_root() -> Path:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)
    return Path(result.stdout.strip()).resolve(strict=True)


def validate_authority_path(destination: Path, candidate_root: Path, *, missing: bool = True) -> Path:
    """Read-only external-path preflight, reusable before Docker provisioning."""
    try:
        destination = _absolute_path(destination)
        candidate_root = _absolute_path(candidate_root)
        parent = destination.parent.resolve(strict=True)
        canonical = parent / destination.name
        for excluded in (_repository_root(), candidate_root.resolve(strict=False)):
            if canonical == excluded or canonical.is_relative_to(excluded):
                raise _fail()
        with _held_directory(parent):
            if missing and os.path.lexists(canonical):
                raise _fail()
        return canonical
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise _fail() from error


@dataclass(frozen=True)
class _HeldFile:
    path: Path
    fd: int
    parent_fd: int
    metadata: os.stat_result
    payload: bytes

    def check(self) -> None:
        if (_identity(os.fstat(self.fd)) != _identity(self.metadata)
                or _identity(os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)) != _identity(self.metadata)):
            raise _fail()


@contextmanager
def _hold_file(path: Path, *, mode: int, maximum_size: int):
    path = _absolute_path(path)
    with _held_directory(path.parent) as (parent_fd, check_parent):
        before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != mode or not 1 <= before.st_size <= maximum_size):
            raise _fail()
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            if _identity(os.fstat(fd)) != _identity(before):
                raise _fail()
            chunks, total = [], 0
            while chunk := os.read(fd, min(1024 * 1024, maximum_size + 1)):
                total += len(chunk)
                if total > maximum_size:
                    raise _fail()
                chunks.append(chunk)
            if total != before.st_size:
                raise _fail()
            held = _HeldFile(path, fd, parent_fd, before, b"".join(chunks))
            held.check()
            yield held
            held.check()
            check_parent()
        finally:
            os.close(fd)


def _rename_exclusive(parent_fd: int, pending: str, leaf: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if os.uname().sysname == "Linux" and hasattr(library, "renameat2"):
        function, flags = library.renameat2, 1
    elif os.uname().sysname == "Darwin" and hasattr(library, "renameatx_np"):
        function, flags = library.renameatx_np, 0x4
    else:
        raise _fail()
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent_fd, os.fsencode(pending), parent_fd, os.fsencode(leaf), flags) != 0:
        raise _fail()


def _publish_exclusive(destination: Path, payload: bytes, *, final_mode: int, maximum_size: int) -> None:
    try:
        destination = _absolute_path(destination)
        if not 1 <= len(payload) <= maximum_size:
            raise _fail()
        with _held_directory(destination.parent) as (parent, check_parent):
            pending = f".{destination.name}.{secrets.token_hex(16)}.pending"
            fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise _fail()
                    view = view[written:]
                os.fchmod(fd, final_mode)
                os.fsync(fd)
                before = os.fstat(fd)
                if _identity(os.stat(pending, dir_fd=parent, follow_symlinks=False)) != _identity(before):
                    raise _fail()
                check_parent()
                _rename_exclusive(parent, pending, destination.name)
                os.fsync(parent)
                with _hold_file(destination, mode=final_mode, maximum_size=maximum_size) as held:
                    # Rename may update ctime; all other identity fields and bytes must survive.
                    if (_identity(held.metadata)[:-1] != _identity(before)[:-1] or held.payload != payload
                            or _identity(os.fstat(fd)) != _identity(held.metadata)):
                        raise _fail()
            finally:
                os.close(fd)
    except (OSError, ValueError) as error:
        raise _fail() from error


def _strict_document(payload: bytes, maximum_size: int) -> dict[str, Any]:
    if not 1 <= len(payload) <= maximum_size:
        raise _fail()
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_duplicate_rejector)
        if type(value) is not dict or _canonical_json(value) != payload:
            raise _fail()
        return value
    except (UnicodeError, ValueError, RecursionError) as error:
        raise _fail() from error


def _file_identity(held: _HeldFile) -> dict[str, object]:
    meta = held.metadata
    return dict(device=meta.st_dev, inode=meta.st_ino, uid=meta.st_uid, gid=meta.st_gid,
                mode=_mode(meta), nlink=meta.st_nlink, size=meta.st_size,
                mtime_ns=meta.st_mtime_ns, ctime_ns=meta.st_ctime_ns,
                sha256=hashlib.sha256(held.payload).hexdigest())


def _parse_record(payload: bytes, expected_commit: str) -> dict[str, Any]:
    data = _strict_document(payload, MAX_RECORD_SIZE)
    if (set(data) != {"schema", "candidate", "candidate_root", "commit", "manifest"}
            or type(expected_commit) is not str or not _COMMIT.fullmatch(expected_commit)
            or data["commit"] != expected_commit):
        raise _fail()
    _integer(data["schema"], 1, 1)
    _absolute_path(data["candidate_root"])
    for name in ("candidate", "manifest"):
        item = data[name]
        keys = {"device", "inode", "uid", "gid", "mode"}
        if name == "manifest":
            keys |= {"nlink", "size", "mtime_ns", "ctime_ns", "sha256"}
        if type(item) is not dict or set(item) != keys:
            raise _fail()
        for key in ("device", "inode", "uid", "gid"):
            _integer(item[key], 0, MAX_UNSIGNED_64)
        if type(item["mode"]) is not str or not _MODE.fullmatch(item["mode"]):
            raise _fail()
        if name == "manifest":
            if item["mode"] != "0444" or type(item["sha256"]) is not str or not _DIGEST.fullmatch(item["sha256"]):
                raise _fail()
            _integer(item["size"], 1, MAX_MANIFEST_SIZE)
            _integer(item["nlink"], 1, 1)
            for key in ("mtime_ns", "ctime_ns"):
                _integer(item[key], MIN_SIGNED_64, MAX_SIGNED_64)
    return data


def _require_artifact_evidence(root: Path, snapshot: CandidateSnapshot, commit: str) -> None:
    from scripts.release_artifacts import BASE_IMAGE, EXPECTED_PACKAGES
    names = ("threadroot-0.1.0-py3-none-any.whl", "threadroot-0.1.0.tar.gz",
             "threadroot-claude-0.1.0.zip", "threadroot-codex-0.1.0.zip")
    approved = None
    for group in ("candidate-a", "candidate-b", "selected"):
        prefix = f"build/{group}/"
        entries = [entry for entry in snapshot.entries if entry.path.startswith(prefix)]
        if {entry.path[len(prefix):] for entry in entries} != set(names):
            raise _fail()
        by_name = {entry.path[len(prefix):]: entry for entry in entries}
        current = []
        for name in names:
            entry = by_name[name]
            if entry.kind != "file" or entry.mode != "0644" or entry.nlink != 1:
                raise _fail()
            current.append(dict(name=name, sha256=entry.sha256, size=entry.size))
        if approved is not None and current != approved:
            raise _fail()
        approved = current
    with _hold_file(root / "build/evidence/build.json", mode=0o644, maximum_size=MAX_FILE_SIZE) as build:
        data = _strict_document(build.payload, MAX_FILE_SIZE)
        if set(data) != {"schema", "commit", "source_date_epoch", "platform", "python", "base_image",
                         "builder_definition_sha256", "packages", "artifacts"}:
            raise _fail()
        _integer(data["schema"], 1, 1)
        epoch = _integer(data["source_date_epoch"], 0, MAX_SIGNED_64)
        expected_epoch = int(subprocess.run(["git", "show", "-s", "--format=%ct", commit],
                                            check=True, capture_output=True, text=True).stdout.strip())
        if (data["commit"] != commit or epoch != expected_epoch or data["platform"] != "linux/amd64"
                or data["python"] != "3.14.7" or data["base_image"] != BASE_IMAGE
                or data["packages"] != EXPECTED_PACKAGES or data["artifacts"] != approved):
            raise _fail()
        digest = data["builder_definition_sha256"]
        if type(digest) is not str or not _DIGEST.fullmatch(digest):
            raise _fail()
        for item in data["artifacts"]:
            _integer(item["size"], 0, MAX_FILE_SIZE)
        sums = "".join(f"{item['sha256']}  {item['name']}\n" for item in sorted(approved, key=lambda item: item["name"])).encode()
        with _hold_file(root / "build/evidence/SHA256SUMS", mode=0o644, maximum_size=MAX_FILE_SIZE) as held:
            if held.payload != sums:
                raise _fail()


def _verify_held_record(record: _HeldFile, expected_commit: str) -> Path:
    """Complete verifier using caller-held record bytes; never reopen its trust."""
    data = _parse_record(record.payload, expected_commit)
    root = _absolute_path(data["candidate_root"])
    if root.resolve(strict=True) != root:
        raise _fail()
    if validate_authority_path(record.path, root, missing=False) != record.path:
        raise _fail()
    with _held_directory(root) as (root_fd, check_root):
        if _directory_identity(os.fstat(root_fd)) != data["candidate"]:
            raise _fail()
        with _hold_file(root / MANIFEST_RELATIVE, mode=0o444, maximum_size=MAX_MANIFEST_SIZE) as manifest:
            if _file_identity(manifest) != data["manifest"]:
                raise _fail()
            recorded = _parse_manifest(manifest.payload, expected_commit)
            first = _capture_candidate(root)
            if first != recorded:
                raise _fail()
            _require_git_sources(first, expected_commit)
            _require_artifact_evidence(root, first, expected_commit)
            if _capture_candidate(root) != first:
                raise _fail()
            check_root()
            manifest.check()
            record.check()
    return root


def verify_candidate(authority_record: Path, expected_commit: str) -> Path:
    try:
        path = _absolute_path(authority_record)
        path = path.parent.resolve(strict=True) / path.name
        with _hold_file(path, mode=0o400, maximum_size=MAX_RECORD_SIZE) as record:
            return _verify_held_record(record, expected_commit)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError) as error:
        raise _fail() from error


def bind_candidate(candidate_root: Path, commit: str, authority_record: Path) -> None:
    try:
        root = _absolute_path(candidate_root)
        if root.resolve(strict=True) != root:
            raise _fail()
        destination = validate_authority_path(authority_record, root)
        with _held_directory(root) as (root_fd, check_root):
            identity = _directory_identity(os.fstat(root_fd))
            _write_candidate_manifest(root, commit)
            with _hold_file(root / MANIFEST_RELATIVE, mode=0o444, maximum_size=MAX_MANIFEST_SIZE) as manifest:
                payload = _canonical_json(dict(schema=1, candidate=identity, candidate_root=str(root),
                                               commit=commit, manifest=_file_identity(manifest)))
                _parse_record(payload, commit)
                check_root()
                _publish_exclusive(destination, payload, final_mode=0o400, maximum_size=MAX_RECORD_SIZE)
                verify_candidate(destination, commit)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError) as error:
        raise _fail() from error
