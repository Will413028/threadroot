from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import stat
import tomllib
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
MARKETPLACE = Path(".claude-plugin/marketplace.json")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
DIRECTORY_FLAGS = READ_FLAGS | os.O_DIRECTORY


class ReleaseInputError(ValueError):
    pass


class _UTF8ZipInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self) -> tuple[bytes, int]:
        encoded, flags = super()._encodeFilenameFlags()
        return encoded, flags | 0x800


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _changed(display_path: str) -> ReleaseInputError:
    return ReleaseInputError(f"release input changed or is unsafe: {display_path}")


def _lstat_at(parent_fd: int, name: str, display_path: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        raise _changed(display_path) from None


def _open_at(
    parent_fd: int,
    name: str,
    flags: int,
    expected: os.stat_result,
    display_path: str,
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise _changed(display_path) from None
    if _stat_signature(opened) != _stat_signature(expected):
        os.close(descriptor)
        raise _changed(display_path)
    return descriptor


def _read_open_file(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    display_path: str,
) -> bytes:
    descriptor = _open_at(parent_fd, name, READ_FLAGS, expected, display_path)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after_read = os.fstat(descriptor)
        current = _lstat_at(parent_fd, name, display_path)
        if (
            _stat_signature(after_read) != _stat_signature(expected)
            or _stat_signature(current) != _stat_signature(expected)
        ):
            raise _changed(display_path)
        return b"".join(chunks)
    except OSError:
        raise _changed(display_path) from None
    finally:
        os.close(descriptor)


def _collect_entry(
    parent_fd: int,
    name: str,
    display_path: str,
) -> list[tuple[str, bytes]]:
    metadata = _lstat_at(parent_fd, name, display_path)
    if stat.S_ISLNK(metadata.st_mode):
        raise ReleaseInputError(f"release input is a symlink: {display_path}")
    if stat.S_ISREG(metadata.st_mode):
        return [
            (
                display_path,
                _read_open_file(parent_fd, name, metadata, display_path),
            )
        ]
    if not stat.S_ISDIR(metadata.st_mode):
        return []

    descriptor = _open_at(
        parent_fd, name, DIRECTORY_FLAGS, metadata, display_path
    )
    try:
        collected: list[tuple[str, bytes]] = []
        try:
            names = sorted(os.listdir(descriptor))
        except OSError:
            raise _changed(display_path) from None
        for child_name in names:
            child_display = f"{display_path}/{child_name}"
            collected.extend(_collect_entry(descriptor, child_name, child_display))
        current = _lstat_at(parent_fd, name, display_path)
        if _stat_signature(current) != _stat_signature(metadata):
            raise _changed(display_path)
        return collected
    finally:
        os.close(descriptor)


def _collect_path(root_fd: int, relative: Path) -> list[tuple[str, bytes]]:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ReleaseInputError("release input path is unsafe")

    def descend(parent_fd: int, parts: tuple[str, ...], prefix: str) -> list[tuple[str, bytes]]:
        name = parts[0]
        display = name if not prefix else f"{prefix}/{name}"
        if len(parts) == 1:
            return _collect_entry(parent_fd, name, display)
        metadata = _lstat_at(parent_fd, name, display)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise _changed(display)
        descriptor = _open_at(parent_fd, name, DIRECTORY_FLAGS, metadata, display)
        try:
            result = descend(descriptor, parts[1:], display)
            current = _lstat_at(parent_fd, name, display)
            if _stat_signature(current) != _stat_signature(metadata):
                raise _changed(display)
            return result
        finally:
            os.close(descriptor)

    return descend(root_fd, pure.parts, "")


def _release_material(host: str) -> tuple[str, list[tuple[str, bytes]]]:
    root_fd: int | None = None
    try:
        root_metadata = os.stat(REPOSITORY_ROOT, follow_symlinks=False)
        if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
            raise _changed("repository")
        root_fd = os.open(REPOSITORY_ROOT, DIRECTORY_FLAGS)
        opened_root = os.fstat(root_fd)
    except OSError:
        if root_fd is not None:
            os.close(root_fd)
        raise _changed("repository") from None
    if _stat_signature(opened_root) != _stat_signature(root_metadata):
        os.close(root_fd)
        raise _changed("repository")

    try:
        version_payload = _collect_path(root_fd, Path("pyproject.toml"))[0][1]
        try:
            version = str(
                tomllib.loads(version_payload.decode("utf-8"))["project"]["version"]
            )
        except (KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            raise ReleaseInputError("release version metadata is invalid") from None

        selected = list(COMMON_ROOTS)
        selected.extend((MARKETPLACE, HOST_MANIFESTS[host]))
        inputs = [item for root in selected for item in _collect_path(root_fd, root)]
        current_root = os.stat(REPOSITORY_ROOT, follow_symlinks=False)
        if _stat_signature(current_root) != _stat_signature(root_metadata):
            raise _changed("repository")
    except OSError:
        raise _changed("repository") from None
    finally:
        os.close(root_fd)

    named = sorted(inputs)
    names = [name for name, _ in named]
    if len(names) != len(set(names)):
        raise ReleaseInputError("duplicate release input")
    return version, named


def build_archive(host: str, output_dir: Path) -> Path:
    if host not in HOST_MANIFESTS:
        raise ValueError(f"unsupported host: {host}")

    version, inputs = _release_material(host)
    output_dir = Path(output_dir)
    artifact = output_dir / f"threadroot-{host}-{version}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        artifact,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.comment = b""
        for name, payload in inputs:
            info = _UTF8ZipInfo(name, ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.extra = b""
            info.comment = b""
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    for host in HOST_MANIFESTS:
        print(build_archive(host, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
