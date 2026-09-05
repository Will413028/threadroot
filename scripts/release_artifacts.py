from __future__ import annotations

from dataclasses import dataclass
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
    extract_regular_tar,
    extract_regular_zip,
    validate_host_zip,
    validate_sdist,
    validate_wheel,
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
        names = expected_asset_names(version)
        entries = list(root.iterdir()) if root.is_dir() and not root.is_symlink() else []
        if (
            sorted(path.name for path in entries) != sorted(names)
            or any(path.is_symlink() or not path.is_file() for path in entries)
        ):
            raise ReleaseArtifactError("release output membership mismatch")
        for path in entries:
            _regular_identity(path)
        return cls(
            root=root,
            wheel=root / names[0],
            sdist=root / names[1],
            claude=root / names[2],
            codex=root / names[3],
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_identity(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ReleaseArtifactError("artifact input is unreadable") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ReleaseArtifactError("artifact input must be an unlinked regular file")
    return metadata


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), value.st_mode & 0o7777, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _dir_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), value.st_mode & 0o7777)


def _hash_descriptor(descriptor: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
        total += len(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest(), total


def _read_regular_bound_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    identity = _regular_identity(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ReleaseArtifactError("input read failed") from error
    try:
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(identity):
            raise ReleaseArtifactError("input identity changed")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _identity(after) != _identity(identity) or _identity(_regular_identity(path)) != _identity(after):
            raise ReleaseArtifactError("input changed while reading")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def _bound_sha256(path: Path, identity: os.stat_result) -> tuple[str, int]:
    before = _regular_identity(path)
    if (before.st_dev, before.st_ino) != (identity.st_dev, identity.st_ino):
        raise ReleaseArtifactError("artifact input identity changed")
    digest = hashlib.sha256()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ReleaseArtifactError("artifact input is unreadable") from error
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (identity.st_dev, identity.st_ino):
            raise ReleaseArtifactError("artifact input identity changed")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        current = _regular_identity(path)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns
        ) or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise ReleaseArtifactError("artifact input changed while reading")
        return digest.hexdigest(), after.st_size
    finally:
        os.close(descriptor)


def compare_artifact_sets(left: ArtifactSet, right: ArtifactSet) -> dict[str, str]:
    hashes: dict[str, str] = {}
    version = left.wheel.name.removeprefix("threadroot-").removesuffix("-py3-none-any.whl")
    identities: dict[str, os.stat_result] = {}
    for name in expected_asset_names(version):
        left_path = left.root / name
        right_path = right.root / name
        identities[name] = _regular_identity(left_path)
        right_identity = _regular_identity(right_path)
        if not filecmp.cmp(left_path, right_path, shallow=False):
            raise ReleaseArtifactError(f"artifact bytes differ: {name}")
        hashes[name], _ = _bound_sha256(left_path, identities[name])
        right_hash, _ = _bound_sha256(right_path, right_identity)
        if right_hash != hashes[name]:
            raise ReleaseArtifactError(f"artifact bytes differ: {name}")
    return hashes


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


def _read_lock_versions(lock: Path) -> dict[str, str]:
    payload, _ = _read_regular_bound_bytes(lock)
    try:
        return _parse_lock_versions(payload.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ReleaseArtifactError("release lock is not UTF-8") from error


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


def _validate_roots(source_a: Path, source_b: Path, output: Path) -> None:
    if not Path(source_a).is_absolute() or not Path(source_b).is_absolute() or not Path(output).is_absolute():
        raise ReleaseArtifactError("all build paths must be absolute")
    roots = (Path(source_a), Path(source_b))
    if any(root.is_symlink() or not root.is_dir() for root in roots):
        raise ReleaseArtifactError("source roots must be real directories")
    try:
        if roots[0].samefile(roots[1]):
            raise ReleaseArtifactError("source roots must be distinct")
    except FileNotFoundError:
        raise ReleaseArtifactError("source roots must be real directories") from None
    output = Path(output)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ReleaseArtifactError("output must be missing or empty")


def _root_identity(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ReleaseArtifactError("build root is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ReleaseArtifactError("build root must be a real directory")
    return metadata


def _assert_root_identity(path: Path, expected: os.stat_result) -> None:
    if _dir_identity(_root_identity(path)) != _dir_identity(expected):
        raise ReleaseArtifactError("build root identity changed")


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


def _build_one_source(source: Path, candidate: Path, work: Path, epoch: int) -> None:
    for name in ("tmp", "home", "cache"):
        (work / name).mkdir(parents=True, exist_ok=False)
    candidate.mkdir(parents=True, exist_ok=False)
    environment = _build_environment(work, epoch)
    python = sys.executable
    _run([python, "-m", "build", "--sdist", "--no-isolation", "--outdir", str(candidate), str(source)], environment)
    _run([python, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(candidate), str(source)], environment)
    _run([python, str(source / "scripts/build_release.py"), "--output", str(candidate)], environment)


def _replay_sdist(artifacts: ArtifactSet, evidence: Path, epoch: int) -> None:
    extracted = evidence / "replay-source"
    replay_output = evidence / "replay-wheel"
    extract_regular_tar(artifacts.sdist, extracted)
    roots = list(extracted.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ReleaseArtifactError("sdist extraction root mismatch")
    replay_output.mkdir(parents=True, exist_ok=False)
    environment = _build_environment(evidence / "replay-work", epoch)
    for name in ("tmp", "home", "cache"):
        (evidence / "replay-work" / name).mkdir(parents=True, exist_ok=False)
    _run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(replay_output), str(roots[0])], environment)
    wheels = list(replay_output.iterdir())
    if len(wheels) != 1 or wheels[0].name != artifacts.wheel.name:
        raise ReleaseArtifactError("sdist wheel replay membership mismatch")
    replay_identity = _regular_identity(wheels[0])
    approved_identity = _regular_identity(artifacts.wheel)
    replay_hash, replay_size = _bound_sha256(wheels[0], replay_identity)
    approved_hash, approved_size = _bound_sha256(artifacts.wheel, approved_identity)
    if replay_hash != approved_hash or replay_size != approved_size:
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


def _write_evidence(evidence: Path, source: Path, artifacts: ArtifactSet, commit: str, epoch: int, hashes: dict[str, str], sizes: dict[str, int], packages: dict[str, str], dockerfile_bytes: bytes, lockfile_bytes: bytes) -> None:
    names = expected_asset_names("0.1.0")
    lines = [f"{hashes[name]}  {name}" for name in sorted(names)]
    (evidence / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "schema": 1,
        "commit": commit,
        "source_date_epoch": epoch,
        "platform": "linux/amd64",
        "python": "3.14.7",
        "base_image": BASE_IMAGE,
        "builder_definition_sha256": hashlib.sha256(dockerfile_bytes + b"\0" + lockfile_bytes).hexdigest(),
        "packages": packages,
        "artifacts": [
            {"name": name, "sha256": hashes[name], "size": sizes[name]}
            for name in names
        ],
    }
    (evidence / "build.json").write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _exclusive_publish(parent_fd: int, pending: str, selected: str, pending_fd: int, identity: os.stat_result, approved: dict[str, tuple[str, int]]) -> None:
    try:
        current = os.stat(pending, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(pending_fd)
        if _dir_identity(current) != _dir_identity(identity) or _dir_identity(opened) != _dir_identity(identity):
            raise OSError("pending identity changed")
        if sorted(os.listdir(pending_fd)) != sorted(approved):
            raise OSError("pending membership changed")
        for name, (expected_hash, expected_size) in approved.items():
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=pending_fd)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o7777 != 0o644 or metadata.st_nlink != 1 or metadata.st_size != expected_size:
                    raise OSError("pending member changed")
                actual_hash, actual_size = _hash_descriptor(descriptor)
                if actual_hash != expected_hash or actual_size != expected_size:
                    raise OSError("pending member bytes changed")
                after = os.fstat(descriptor)
                if _identity(after) != _identity(metadata):
                    raise OSError("pending member changed while reading")
            finally:
                os.close(descriptor)
        library = ctypes.CDLL(None, use_errno=True)
        if os.uname().sysname == "Linux" and hasattr(library, "renameat2"):
            function = library.renameat2
            function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            function.restype = ctypes.c_int
            result = function(parent_fd, os.fsencode(pending), parent_fd, os.fsencode(selected), 1)
        elif os.uname().sysname == "Darwin" and hasattr(library, "renameatx_np"):
            function = library.renameatx_np
            function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            function.restype = ctypes.c_int
            result = function(parent_fd, os.fsencode(pending), parent_fd, os.fsencode(selected), 0x4)
        else:
            raise OSError("exclusive publication unavailable")
        if result != 0:
            raise OSError("selected appeared during publication")
    except OSError as error:
        raise ReleaseArtifactError("selected artifact promotion failed") from error


def _promote(output: Path, artifacts: ArtifactSet, hashes: dict[str, str]) -> None:
    output = Path(output)
    names = expected_asset_names("0.1.0")
    try:
        parent_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ReleaseArtifactError("selected artifact promotion failed") from error
    pending_fd: int | None = None
    pending_identity: os.stat_result | None = None
    try:
        for name in ("selected", "selected.pending"):
            try:
                os.lstat(name, dir_fd=parent_fd)
            except FileNotFoundError:
                continue
            raise ReleaseArtifactError("selected output already exists")
        os.mkdir("selected.pending", 0o755, dir_fd=parent_fd)
        pending_identity = os.stat("selected.pending", dir_fd=parent_fd, follow_symlinks=False)
        pending_fd = os.open("selected.pending", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        if (os.fstat(pending_fd).st_dev, os.fstat(pending_fd).st_ino) != (pending_identity.st_dev, pending_identity.st_ino):
            raise ReleaseArtifactError("selected artifact promotion failed")
        source_identities: dict[str, os.stat_result] = {}
        sizes: dict[str, int] = {}
        for name in names:
            source = artifacts.root / name
            identity = _regular_identity(source)
            source_identities[name] = identity
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(descriptor)
                if opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != (identity.st_dev, identity.st_ino):
                    raise ReleaseArtifactError("artifact input identity changed")
                destination = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=pending_fd)
                digest = hashlib.sha256()
                try:
                    while chunk := os.read(descriptor, 1024 * 1024):
                        digest.update(chunk)
                        os.write(destination, chunk)
                finally:
                    os.close(destination)
                if digest.hexdigest() != hashes[name] or os.stat(name, dir_fd=pending_fd, follow_symlinks=False).st_size != identity.st_size:
                    raise ReleaseArtifactError("selected artifact changed during promotion")
                sizes[name] = identity.st_size
            finally:
                os.close(descriptor)
        for name in names:
            identity = source_identities[name]
            digest, size = _bound_sha256(artifacts.root / name, identity)
            if digest != hashes[name] or size != identity.st_size:
                raise ReleaseArtifactError("artifact input changed before promotion")
        _exclusive_publish(parent_fd, "selected.pending", "selected", pending_fd, pending_identity,
                           {name: (hashes[name], sizes[name]) for name in names})
        os.close(pending_fd)
        pending_fd = None
    except ReleaseArtifactError:
        raise
    except OSError as error:
        raise ReleaseArtifactError("selected artifact promotion failed") from error
    finally:
        if pending_fd is not None:
            os.close(pending_fd)
        os.close(parent_fd)


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
    source_a = Path(source_a)
    source_b = Path(source_b)
    output = Path(output)
    if not source_a.is_absolute() or not source_b.is_absolute() or not output.is_absolute():
        raise ReleaseArtifactError("all build paths must be absolute")
    _validate_denylist(denylist)
    _validate_roots(source_a, source_b, output)
    source_a_identity = _root_identity(source_a)
    source_b_identity = _root_identity(source_b)
    lock_a_bytes, _ = _read_regular_bound_bytes(source_a / "requirements/release.txt")
    lock_b_bytes, _ = _read_regular_bound_bytes(source_b / "requirements/release.txt")
    docker_a_bytes, _ = _read_regular_bound_bytes(source_a / "tools/release/Dockerfile")
    docker_b_bytes, _ = _read_regular_bound_bytes(source_b / "tools/release/Dockerfile")
    try:
        lock_a = _parse_lock_versions(lock_a_bytes.decode("utf-8"))
        lock_b = _parse_lock_versions(lock_b_bytes.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ReleaseArtifactError("release input is not UTF-8") from error
    if lock_a != lock_b:
        raise ReleaseArtifactError("source release locks differ")
    if lock_a != EXPECTED_PACKAGES or docker_a_bytes != docker_b_bytes:
        raise ReleaseArtifactError("builder inputs differ from approved definition")
    _validate_environment(epoch, lock_a)
    _validate_roots(source_a, source_b, output)
    previous_umask = os.umask(0o022)
    try:
        output = Path(output)
        if output.exists() and output.is_symlink():
            raise ReleaseArtifactError("output must be a real directory")
        output.mkdir(parents=True, exist_ok=True)
        output_identity = _root_identity(output)
        candidate_a_root = output / "candidate-a"
        candidate_b_root = output / "candidate-b"
        evidence = output / "evidence"
        (evidence / "work").mkdir(parents=True, exist_ok=False)
        _assert_root_identity(source_a, source_a_identity)
        _assert_root_identity(source_b, source_b_identity)
        _assert_root_identity(output, output_identity)
        _build_one_source(Path(source_a), candidate_a_root, evidence / "work" / "a", epoch)
        _assert_root_identity(source_a, source_a_identity)
        _assert_root_identity(source_b, source_b_identity)
        _assert_root_identity(output, output_identity)
        _build_one_source(Path(source_b), candidate_b_root, evidence / "work" / "b", epoch)
        candidate_a = ArtifactSet.load(candidate_a_root, "0.1.0")
        candidate_b = ArtifactSet.load(candidate_b_root, "0.1.0")
        hashes = compare_artifact_sets(candidate_a, candidate_b)
        for artifacts, source in ((candidate_a, Path(source_a)), (candidate_b, Path(source_b))):
            _assert_root_identity(source, source_a_identity if source == source_a else source_b_identity)
            validate_wheel(artifacts.wheel, source, "0.1.0", epoch)
            validate_sdist(artifacts.sdist, source, "0.1.0", epoch)
            validate_host_zip(artifacts.claude, source, "claude")
            validate_host_zip(artifacts.codex, source, "codex")
        _replay_sdist(candidate_a, evidence, epoch)
        unpacked = evidence / "unpacked"
        unpacked.mkdir(parents=True, exist_ok=False)
        extract_regular_zip(candidate_a.wheel, unpacked / "wheel")
        extract_regular_tar(candidate_a.sdist, unpacked / "sdist")
        extract_regular_zip(candidate_a.claude, unpacked / "claude")
        extract_regular_zip(candidate_a.codex, unpacked / "codex")
        _scan(Path(source_a), Path(source_b), candidate_a, unpacked, denylist)
        _assert_root_identity(source_a, source_a_identity)
        _assert_root_identity(source_b, source_b_identity)
        _assert_root_identity(output, output_identity)
        sizes: dict[str, int] = {}
        for name in expected_asset_names("0.1.0"):
            identity = _regular_identity(candidate_a.root / name)
            digest, size = _bound_sha256(candidate_a.root / name, identity)
            if digest != hashes[name] or size != identity.st_size:
                raise ReleaseArtifactError("approved artifact changed before evidence")
            sizes[name] = size
        _write_evidence(evidence, Path(source_a), candidate_a, commit, epoch, hashes, sizes, lock_a,
                        docker_a_bytes, lock_a_bytes)
        _promote(output, candidate_a, hashes)
        return hashes
    finally:
        os.umask(previous_umask)
