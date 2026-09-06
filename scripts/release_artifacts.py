from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from collections.abc import Callable
import ctypes
import filecmp
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys

from scripts.release_archives import (
    ReleaseArchiveError,
    ReleaseSourceSnapshot,
    capture_release_source,
    extract_regular_tar_payload,
    extract_regular_zip_payload,
    validate_host_zip_payload,
    validate_sdist_payload,
    validate_wheel_payload,
)


class ReleaseArtifactError(RuntimeError):
    """Release artifact validation or promotion failed."""


def expected_asset_names(version: str) -> tuple[str, str, str, str]:
    return (
        f"threadroot-{version}-py3-none-any.whl",
        f"threadroot-{version}.tar.gz",
        f"threadroot-claude-{version}.zip",
        f"threadroot-codex-{version}.zip",
    )


@dataclass(frozen=True)
class ArtifactSet:
    root: Path
    wheel: Path
    sdist: Path
    claude: Path
    codex: Path

    @classmethod
    def load(cls, root: Path, version: str) -> "ArtifactSet":
        root = Path(root)
        try:
            with ExitStack() as stack:
                bindings = _RunBindings(stack)
                directory = bindings.bind(root)
                _capture_set(stack, directory, expected_asset_names(version))
        except (OSError, ReleaseArtifactError) as error:
            raise ReleaseArtifactError("release output membership mismatch") from error
        return cls(root, *(root / name for name in expected_asset_names(version)))


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    file_type: int
    permissions: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass
class _BoundDirectory:
    path: Path
    fd: int
    device: int
    inode: int
    permissions: int
    parent: _BoundDirectory | None = None


@dataclass(frozen=True)
class _ArtifactSnapshot:
    name: str
    fd: int
    identity: _FileIdentity
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class _VerifiedPair:
    candidate_a: tuple[_ArtifactSnapshot, ...]
    candidate_b: tuple[_ArtifactSnapshot, ...]
    hashes: tuple[tuple[str, str], ...]


def _identity(metadata: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode), metadata.st_nlink, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _owned_open(stack: ExitStack, path: Path | str, flags: int, mode: int = 0o777,
                *, dir_fd: int | None = None) -> int:
    descriptor = os.open(path, flags | getattr(os, "O_CLOEXEC", 0), mode, dir_fd=dir_fd)
    stack.callback(os.close, descriptor)
    return descriptor


def _directory_entry(directory: _BoundDirectory) -> os.stat_result:
    if directory.parent is not None:
        return os.stat(directory.path.name, dir_fd=directory.parent.fd, follow_symlinks=False)
    return os.lstat(directory.path)


def _assert_directory(directory: _BoundDirectory) -> None:
    if directory.parent is not None:
        _assert_directory(directory.parent)
    expected = (directory.device, directory.inode, stat.S_IFDIR, directory.permissions)
    for metadata in (_directory_entry(directory), os.fstat(directory.fd)):
        actual = (metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode), stat.S_IMODE(metadata.st_mode))
        if actual != expected:
            raise ReleaseArtifactError("build directory identity changed")


@dataclass
class _RunBindings:
    stack: ExitStack
    directories: list[_BoundDirectory] = field(default_factory=list)

    def bind(self, path: Path, parent: _BoundDirectory | None = None,
             expected: os.stat_result | None = None) -> _BoundDirectory:
        path = Path(path)
        if parent is not None:
            _assert_directory(parent)
        target = path.name if parent is not None else path
        parent_fd = parent.fd if parent is not None else None
        before = os.stat(target, dir_fd=parent_fd, follow_symlinks=False) if expected is None else expected
        if not stat.S_ISDIR(before.st_mode):
            raise ReleaseArtifactError("build roots must be real directories")
        descriptor = _owned_open(self.stack, target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                 dir_fd=parent_fd)
        bound = _BoundDirectory(path, descriptor, before.st_dev, before.st_ino,
                                stat.S_IMODE(before.st_mode), parent)
        _assert_directory(bound)
        self.directories.append(bound)
        return bound

    def mkdir(self, parent: _BoundDirectory, name: str) -> _BoundDirectory:
        _assert_directory(parent)
        os.mkdir(name, 0o755, dir_fd=parent.fd)
        created = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
        return self.bind(parent.path / name, parent, created)

    def check(self) -> None:
        for directory in self.directories:
            _assert_directory(directory)


def _acquire_output(bindings: _RunBindings, path: Path) -> _BoundDirectory:
    parent = bindings.bind(path.parent)
    try:
        before = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            output = bindings.mkdir(parent, path.name)
        except FileExistsError as error:
            raise ReleaseArtifactError("output appeared during creation") from error
    else:
        output = bindings.bind(path, parent, before)
    if os.listdir(output.fd):
        raise ReleaseArtifactError("output must be missing or empty")
    _assert_directory(output)
    return output


def _stream_descriptor(descriptor: int, *, capture: bool = False) -> tuple[bytes, str, int]:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
        total += len(chunk)
        if capture:
            chunks.append(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return b"".join(chunks), digest.hexdigest(), total


def _require_artifact(identity: _FileIdentity) -> None:
    if identity.file_type != stat.S_IFREG or identity.links != 1 or identity.permissions != 0o644:
        raise ReleaseArtifactError("artifact input must be a single-link regular 0644 file")


def _capture_member(stack: ExitStack, directory: _BoundDirectory, name: str) -> _ArtifactSnapshot:
    _assert_directory(directory)
    before = _identity(os.stat(name, dir_fd=directory.fd, follow_symlinks=False))
    _require_artifact(before)
    descriptor = _owned_open(stack, name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory.fd)
    if _identity(os.fstat(descriptor)) != before:
        raise ReleaseArtifactError("artifact input identity changed")
    payload, digest, size = _stream_descriptor(descriptor, capture=True)
    snapshot = _ArtifactSnapshot(name, descriptor, before, payload, digest)
    if size != before.size:
        raise ReleaseArtifactError("artifact input changed while reading")
    _assert_snapshot(directory, snapshot, rehash=False)
    return snapshot


def _assert_snapshot(directory: _BoundDirectory, snapshot: _ArtifactSnapshot, *, rehash: bool = True) -> None:
    _assert_directory(directory)
    for metadata in (os.stat(snapshot.name, dir_fd=directory.fd, follow_symlinks=False), os.fstat(snapshot.fd)):
        if _identity(metadata) != snapshot.identity:
            raise ReleaseArtifactError("artifact input identity changed")
    if rehash:
        _, digest, size = _stream_descriptor(snapshot.fd)
        if digest != snapshot.sha256 or size != snapshot.identity.size:
            raise ReleaseArtifactError("artifact input bytes changed")
        _assert_snapshot(directory, snapshot, rehash=False)


def _assert_set(directory: _BoundDirectory, snapshots: tuple[_ArtifactSnapshot, ...]) -> None:
    _assert_directory(directory)
    if sorted(os.listdir(directory.fd)) != sorted(item.name for item in snapshots):
        raise ReleaseArtifactError("artifact membership changed")
    for snapshot in snapshots:
        _assert_snapshot(directory, snapshot)
    # Reading a later member must not hide drift in an earlier table entry.
    for snapshot in snapshots:
        _assert_snapshot(directory, snapshot, rehash=False)
    if sorted(os.listdir(directory.fd)) != sorted(item.name for item in snapshots):
        raise ReleaseArtifactError("artifact membership changed")


def _capture_set(stack: ExitStack, directory: _BoundDirectory,
                 names: tuple[str, ...]) -> tuple[_ArtifactSnapshot, ...]:
    if sorted(os.listdir(directory.fd)) != sorted(names):
        raise ReleaseArtifactError("release output membership mismatch")
    snapshots = tuple(_capture_member(stack, directory, name) for name in names)
    identities = {(item.identity.device, item.identity.inode) for item in snapshots}
    if len(identities) != len(snapshots):
        raise ReleaseArtifactError("artifact inputs contain duplicate inodes")
    _assert_set(directory, snapshots)
    return snapshots


def _compare_snapshots(left: _BoundDirectory, right: _BoundDirectory,
                       a: tuple[_ArtifactSnapshot, ...], b: tuple[_ArtifactSnapshot, ...]) -> _VerifiedPair:
    _assert_set(left, a)
    _assert_set(right, b)
    for first, second in zip(a, b, strict=True):
        if first.name != second.name or not filecmp.cmp(left.path / first.name, right.path / second.name, shallow=False):
            raise ReleaseArtifactError(f"artifact bytes differ: {first.name}")
        if first.payload != second.payload or first.sha256 != second.sha256:
            raise ReleaseArtifactError(f"artifact bytes differ: {first.name}")
    identities = {(item.identity.device, item.identity.inode) for item in (*a, *b)}
    if len(identities) != len(a) + len(b):
        raise ReleaseArtifactError("artifact inputs contain duplicate inodes")
    _assert_set(left, a)
    _assert_set(right, b)
    return _VerifiedPair(a, b, tuple((item.name, item.sha256) for item in a))


def compare_artifact_sets(left: ArtifactSet, right: ArtifactSet) -> dict[str, str]:
    version = left.wheel.name.removeprefix("threadroot-").removesuffix("-py3-none-any.whl")
    try:
        with ExitStack() as stack:
            bindings = _RunBindings(stack)
            left_root, right_root = bindings.bind(left.root), bindings.bind(right.root)
            names = expected_asset_names(version)
            pair = _compare_snapshots(left_root, right_root, _capture_set(stack, left_root, names),
                                      _capture_set(stack, right_root, names))
            return dict(pair.hashes)
    except OSError as error:
        raise ReleaseArtifactError("artifact input changed or is unreadable") from error


EXPECTED_PACKAGES = {
    "build": "1.6.0",
    "hatchling": "1.32.0",
    "packaging": "26.3",
    "pathspec": "1.1.1",
    "pip": "26.2.1",
    "pluggy": "1.6.0",
    "pyproject-hooks": "1.2.0",
    "tomlkit": "0.15.1",
    "trove-classifiers": "2026.6.1.19",
}
EXPECTED_ENVIRONMENT = {
    "THREADROOT_CANONICAL_BUILD": "1",
    "TZ": "UTC",
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "PIP_CONFIG_FILE": "/dev/null",
    "PIP_INDEX_URL": "https://pypi.org/simple",
    "PIP_EXTRA_INDEX_URL": "",
    "PIP_FIND_LINKS": "",
    "PIP_NO_CACHE_DIR": "1",
}
BASE_IMAGE = (
    "python:3.14.7-slim-bookworm@"
    "sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9"
)


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _installed_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for item in importlib.metadata.distributions():
        name = item.metadata.get("Name")
        if not name:
            raise ReleaseArtifactError("installed distribution has no Name")
        canonical = _canonical_name(name)
        if canonical in packages:
            raise ReleaseArtifactError("installed distribution canonical duplicate")
        packages[canonical] = item.version
    return packages


def _parse_lock_versions(text: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    lines = text.splitlines()
    option_seen = False
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line or line.startswith("#"):
            continue
        if line == "--only-binary=:all:":
            if option_seen:
                raise ReleaseArtifactError("release lock contains duplicate option")
            option_seen = True
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+) \\", line)
        if not match or index >= len(lines) or not re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", lines[index].strip()):
            raise ReleaseArtifactError("release lock line is malformed")
        index += 1
        name = _canonical_name(match.group(1))
        if name in versions:
            raise ReleaseArtifactError("release lock contains duplicate package")
        versions[name] = match.group(2)
    if not versions:
        raise ReleaseArtifactError("release lock is empty")
    if not option_seen:
        raise ReleaseArtifactError("release lock is missing approved option")
    return versions


def _validate_environment(epoch: int, expected_packages: dict[str, str]) -> None:
    if os.environ.get("THREADROOT_CANONICAL_BUILD") != "1":
        raise ReleaseArtifactError("canonical build environment is not enabled")
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ReleaseArtifactError("canonical build requires Linux x86_64")
    if tuple(sys.version_info[:3]) != (3, 14, 7):
        raise ReleaseArtifactError("canonical build requires Python 3.14.7")
    if epoch < 0:
        raise ReleaseArtifactError("source epoch must be non-negative")
    if os.environ.get("SOURCE_DATE_EPOCH") != str(epoch):
        raise ReleaseArtifactError("SOURCE_DATE_EPOCH mismatch")
    actual = _installed_packages()
    if actual != expected_packages:
        raise ReleaseArtifactError("canonical package set mismatch")
    for key, value in EXPECTED_ENVIRONMENT.items():
        if os.environ.get(key) != value:
            raise ReleaseArtifactError(f"canonical environment mismatch: {key}")


def _build_environment(work: Path, epoch: int) -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", "")}
    environment.update(EXPECTED_ENVIRONMENT)
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    environment["TMPDIR"] = str(work / "tmp")
    environment["HOME"] = str(work / "home")
    environment["XDG_CACHE_HOME"] = str(work / "cache")
    return environment


def _run(command: list[str], environment: dict[str, str]) -> None:
    subprocess.run(command, check=True, shell=False, env=environment)


def _build_one_source(source: Path, candidate: Path, work: Path, epoch: int,
                      *, guard: Callable[[], None] = lambda: None) -> None:
    environment = _build_environment(work, epoch)
    commands = [
        [sys.executable, "-m", "build", "--sdist", "--no-isolation", "--outdir", str(candidate), str(source)],
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(candidate), str(source)],
        [sys.executable, str(source / "scripts/build_release.py"), "--output", str(candidate)],
    ]
    for command in commands:
        guard()
        _run(command, environment)
        guard()


def _create_work(bindings: _RunBindings, parent: _BoundDirectory, name: str) -> _BoundDirectory:
    work = bindings.mkdir(parent, name)
    for child in ("tmp", "home", "cache"):
        bindings.mkdir(work, child)
    return work


def _replay_sdist(bindings: _RunBindings, artifacts: tuple[_ArtifactSnapshot, ...],
                  evidence: _BoundDirectory, epoch: int) -> None:
    wheel, sdist = artifacts[:2]
    bindings.check()
    extract_regular_tar_payload(sdist.payload, evidence.path / "replay-source")
    bindings.check()
    extracted = bindings.bind(evidence.path / "replay-source", evidence)
    names = os.listdir(extracted.fd)
    if names != ["threadroot-0.1.0"]:
        raise ReleaseArtifactError("sdist extraction root mismatch")
    source = bindings.bind(extracted.path / names[0], extracted)
    output = bindings.mkdir(evidence, "replay-wheel")
    work = _create_work(bindings, evidence, "replay-work")
    bindings.check()
    _run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output.path),
          str(source.path)], _build_environment(work.path, epoch))
    bindings.check()
    if os.listdir(output.fd) != [wheel.name]:
        raise ReleaseArtifactError("sdist wheel replay membership mismatch")
    replay = _capture_member(bindings.stack, output, wheel.name)
    if replay.payload != wheel.payload or replay.sha256 != wheel.sha256:
        raise ReleaseArtifactError("sdist wheel replay bytes differ")


def _scan(source_a: Path, source_b: Path, artifacts: ArtifactSet, unpacked: Path, denylist: Path | None) -> None:
    if denylist is not None and Path(denylist) != Path("/run/threadroot/denylist"):
        raise ReleaseArtifactError("denylist path is not approved")
    paths = [source_a, source_b, artifacts.wheel, artifacts.sdist, artifacts.claude, artifacts.codex,
             unpacked / "wheel", unpacked / "sdist", unpacked / "claude", unpacked / "codex"]
    command = [sys.executable, str(source_a / "scripts/check_public.py")]
    if denylist is not None:
        command.extend(("--denylist", str(denylist)))
    command.extend(str(path) for path in paths)
    scanner_environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONHASHSEED": "0",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }
    subprocess.run(command, check=True, shell=False, capture_output=True, text=True, env=scanner_environment)


def _validate_denylist(denylist: Path | None) -> None:
    if denylist is None:
        return
    denylist = Path(denylist)
    if denylist != Path("/run/threadroot/denylist"):
        raise ReleaseArtifactError("denylist path is not approved")
    try:
        metadata = os.lstat(denylist)
    except FileNotFoundError:
        raise ReleaseArtifactError("denylist is missing")
    except OSError as error:
        raise ReleaseArtifactError("denylist is unreadable") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ReleaseArtifactError("denylist must be a regular file")


def _write_payload(bindings: _RunBindings, directory: _BoundDirectory,
                   name: str, payload: bytes) -> _ArtifactSnapshot:
    _assert_directory(directory)
    descriptor = _owned_open(bindings.stack, name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644, dir_fd=directory.fd)
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short release write")
        view = view[written:]
    identity = _identity(os.fstat(descriptor))
    _require_artifact(identity)
    snapshot = _ArtifactSnapshot(name, descriptor, identity, payload, hashlib.sha256(payload).hexdigest())
    _assert_snapshot(directory, snapshot)
    return snapshot


def _write_evidence(bindings: _RunBindings, evidence: _BoundDirectory, pair: _VerifiedPair,
                    commit: str, epoch: int, packages: dict[str, str],
                    dockerfile_bytes: bytes, lockfile_bytes: bytes) -> tuple[_ArtifactSnapshot, ...]:
    hashes = dict(pair.hashes)
    sums = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode()
    data = {
        "schema": 1,
        "commit": commit,
        "source_date_epoch": epoch,
        "platform": "linux/amd64",
        "python": "3.14.7",
        "base_image": BASE_IMAGE,
        "builder_definition_sha256": hashlib.sha256(dockerfile_bytes + b"\0" + lockfile_bytes).hexdigest(),
        "packages": packages,
        "artifacts": [{"name": item.name, "sha256": item.sha256, "size": item.identity.size}
                      for item in pair.candidate_a],
    }
    payload = (json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return (_write_payload(bindings, evidence, "SHA256SUMS", sums),
            _write_payload(bindings, evidence, "build.json", payload))


def _exclusive_publish(bindings: _RunBindings, output: _BoundDirectory, pending: _BoundDirectory,
                       snapshots: tuple[_ArtifactSnapshot, ...], pair: _VerifiedPair,
                       final_check: Callable[[], None]) -> None:
    try:
        bindings.check()
        final_check()
        _assert_set(pending, snapshots)
        for written, approved in zip(snapshots, pair.candidate_a, strict=True):
            if (written.name, written.identity.size, written.sha256, written.payload) != (
                approved.name, approved.identity.size, approved.sha256, approved.payload
            ):
                raise ReleaseArtifactError("pending artifact differs from approved snapshot")
        library = ctypes.CDLL(None, use_errno=True)
        if os.uname().sysname == "Linux" and hasattr(library, "renameat2"):
            function = library.renameat2
            function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            function.restype = ctypes.c_int
            result = function(output.fd, b"selected.pending", output.fd, b"selected", 1)
        elif os.uname().sysname == "Darwin" and hasattr(library, "renameatx_np"):
            function = library.renameatx_np
            function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            function.restype = ctypes.c_int
            result = function(output.fd, b"selected.pending", output.fd, b"selected", 0x4)
        else:
            raise OSError("exclusive publication unavailable")
        if result != 0:
            raise OSError("selected appeared during publication")
    except (OSError, ReleaseArtifactError) as error:
        raise ReleaseArtifactError("selected artifact promotion failed") from error


def _promote(bindings: _RunBindings, output: _BoundDirectory, pair: _VerifiedPair,
             final_check: Callable[[], None]) -> None:
    try:
        bindings.check()
        final_check()
        for name in ("selected", "selected.pending"):
            try:
                os.stat(name, dir_fd=output.fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ReleaseArtifactError("selected output already exists")
        pending = bindings.mkdir(output, "selected.pending")
        written = tuple(_write_payload(bindings, pending, item.name, item.payload) for item in pair.candidate_a)
        _exclusive_publish(bindings, output, pending, written, pair, final_check)
    except OSError as error:
        raise ReleaseArtifactError("selected artifact promotion failed") from error


def _builder_inputs(source: ReleaseSourceSnapshot) -> tuple[bytes, bytes]:
    selected = {entry.path: entry.payload for entry in source.entries}
    try:
        return selected["tools/release/Dockerfile"], selected["requirements/release.txt"]
    except KeyError as error:
        raise ReleaseArtifactError("required builder input is missing") from error


def build_and_verify(
    source_a: Path,
    source_b: Path,
    output: Path,
    commit: str,
    epoch: int,
    denylist: Path | None = None,
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseArtifactError("commit must be lowercase 40-hex")
    source_a, source_b, output = Path(source_a), Path(source_b), Path(output)
    if not all(path.is_absolute() for path in (source_a, source_b, output)):
        raise ReleaseArtifactError("all build paths must be absolute")
    _validate_denylist(denylist)
    _validate_environment(epoch, EXPECTED_PACKAGES)
    previous_umask = os.umask(0o022)
    try:
        with ExitStack() as stack:
            bindings = _RunBindings(stack)
            a_root, b_root = bindings.bind(source_a), bindings.bind(source_b)
            if (a_root.device, a_root.inode) == (b_root.device, b_root.inode):
                raise ReleaseArtifactError("source roots must be distinct")
            a_source = capture_release_source(a_root.fd)
            b_source = capture_release_source(b_root.fd)
            docker_a, lock_a = _builder_inputs(a_source)
            docker_b, lock_b = _builder_inputs(b_source)
            if docker_a != docker_b or lock_a != lock_b:
                raise ReleaseArtifactError("builder inputs differ from approved definition")
            try:
                packages = _parse_lock_versions(lock_a.decode("utf-8"))
            except UnicodeDecodeError as error:
                raise ReleaseArtifactError("release lock is not UTF-8") from error
            if packages != EXPECTED_PACKAGES:
                raise ReleaseArtifactError("source release lock package mismatch")
            bindings.check()
            output_root = _acquire_output(bindings, output)
            evidence = bindings.mkdir(output_root, "evidence")
            work_root = bindings.mkdir(evidence, "work")
            a_work = _create_work(bindings, work_root, "a")
            candidate_a = bindings.mkdir(output_root, "candidate-a")
            bindings.check()
            _build_one_source(a_root.path, candidate_a.path, a_work.path, epoch, guard=bindings.check)
            bindings.check()
            names = expected_asset_names("0.1.0")
            a = _capture_set(stack, candidate_a, names)
            b_work = _create_work(bindings, work_root, "b")
            candidate_b = bindings.mkdir(output_root, "candidate-b")
            bindings.check()
            _build_one_source(b_root.path, candidate_b.path, b_work.path, epoch, guard=bindings.check)
            bindings.check()
            b = _capture_set(stack, candidate_b, names)
            pair = _compare_snapshots(candidate_a, candidate_b, a, b)

            def joint_check() -> None:
                bindings.check()
                _assert_set(candidate_a, pair.candidate_a)
                _assert_set(candidate_b, pair.candidate_b)

            for artifacts, source in ((pair.candidate_a, a_source), (pair.candidate_b, b_source)):
                joint_check()
                validate_wheel_payload(artifacts[0].payload, source, "0.1.0", epoch)
                validate_sdist_payload(artifacts[1].payload, source, "0.1.0", epoch)
                validate_host_zip_payload(artifacts[2].payload, source, "claude")
                validate_host_zip_payload(artifacts[3].payload, source, "codex")
            joint_check()
            _replay_sdist(bindings, pair.candidate_a, evidence, epoch)
            joint_check()
            unpacked = bindings.mkdir(evidence, "unpacked")
            for item, label, extract in zip(pair.candidate_a, ("wheel", "sdist", "claude", "codex"),
                                           (extract_regular_zip_payload, extract_regular_tar_payload,
                                            extract_regular_zip_payload, extract_regular_zip_payload), strict=True):
                joint_check()
                extract(item.payload, unpacked.path / label)
                bindings.bind(unpacked.path / label, unpacked)
            joint_check()
            paths = ArtifactSet(candidate_a.path, *(candidate_a.path / name for name in names))
            _scan(a_root.path, b_root.path, paths, unpacked.path, denylist)
            joint_check()
            records = _write_evidence(bindings, evidence, pair, commit, epoch, packages, docker_a, lock_a)

            def final_check() -> None:
                joint_check()
                for record in records:
                    _assert_snapshot(evidence, record)

            _promote(bindings, output_root, pair, final_check)
            return dict(pair.hashes)
    except ReleaseArchiveError as error:
        raise ReleaseArtifactError(str(error)) from error
    except OSError as error:
        raise ReleaseArtifactError("release input changed or is unreadable") from error
    finally:
        os.umask(previous_umask)
