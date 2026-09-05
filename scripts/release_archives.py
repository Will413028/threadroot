from __future__ import annotations

import binascii
import base64
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
import io
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import tarfile
import tomllib
import zipfile
import zlib

from scripts.build_release import COMMON_ROOTS, HOST_MANIFESTS, MARKETPLACE, ZIP_TIMESTAMP


class ReleaseArchiveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> ReleaseArchiveError:
    return ReleaseArchiveError(code, message)


def _read_artifact(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise OSError("artifact is not a regular file")
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (before.st_dev, before.st_ino, before.st_mode):
            raise OSError("artifact changed before open")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = path.lstat()
        if (
            (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size, opened.st_mtime_ns)
            or (current.st_dev, current.st_ino, current.st_mode, current.st_size, current.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size, opened.st_mtime_ns)
        ):
            raise OSError("artifact changed while reading")
        return b"".join(chunks)
    except OSError:
        raise _fail("invalid_archive", "archive input is missing, changed, or unsafe") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def validate_archive_name(name: str) -> PurePosixPath:
    if (
        not name
        or "\0" in name
        or "\\" in name
        or name.startswith("/")
        or name.endswith("/")
    ):
        raise _fail("unsafe_path", "unsafe archive path")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _fail("unsafe_path", "unsafe archive path")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise _fail("unsafe_path", "unsafe archive path")
    return path


def _member_path(name: str, is_directory: bool) -> PurePosixPath:
    if name.endswith("/"):
        if not is_directory or name.endswith("//"):
            raise _fail("unsafe_path", "unsafe archive path")
        name = name[:-1]
    return validate_archive_name(name)


def _normalized_mode(mode: int) -> int:
    permission = mode & 0o7777
    if permission not in {0o644, 0o664, 0o755, 0o775}:
        raise _fail("unsupported_mode", "unsupported archive mode")
    return 0o755 if permission & 0o111 else 0o644


def _validate_member_table(
    members: list[tuple[PurePosixPath, bool, int, bytes]],
) -> None:
    seen: set[str] = set()
    files: set[str] = set()
    for path, is_directory, _mode, _payload in members:
        normalized = path.as_posix()
        if normalized in seen:
            raise _fail("duplicate_member", "duplicate archive member")
        seen.add(normalized)
        for parent in path.parents:
            if parent == PurePosixPath("."):
                continue
            if parent.as_posix() in files:
                raise _fail("unsupported_member", "archive member parent is a file")
        if not is_directory:
            files.add(normalized)
        if is_directory and any(item.startswith(normalized + "/") for item in files):
            raise _fail("unsupported_member", "archive directory conflicts with a file")


def _zip_has_exact_bounds(payload: bytes, infos: list[zipfile.ZipInfo]) -> bool:
    if not infos or min(info.header_offset for info in infos) != 0:
        return False
    marker = payload.rfind(b"PK\x05\x06")
    if marker < 0 or marker + 22 > len(payload):
        return False
    comment_size = int.from_bytes(payload[marker + 20 : marker + 22], "little")
    return marker + 22 + comment_size == len(payload)


def _load_zip_members(artifact: Path) -> list[tuple[PurePosixPath, bool, int, bytes]]:
    try:
        raw = _read_artifact(artifact)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not _zip_has_exact_bounds(raw, infos):
                raise _fail("invalid_archive", "invalid ZIP structure")
            members: list[tuple[PurePosixPath, bool, int, bytes]] = []
            for info in infos:
                type_bits = stat.S_IFMT(info.external_attr >> 16)
                is_directory = info.is_dir()
                if is_directory:
                    if type_bits != stat.S_IFDIR:
                        raise _fail("unsupported_member", "unsupported ZIP member")
                elif type_bits not in {0, stat.S_IFREG}:
                    raise _fail("unsupported_member", "unsupported ZIP member")
                path = _member_path(info.filename, is_directory)
                mode = _normalized_mode(info.external_attr >> 16)
                try:
                    data = b"" if is_directory else archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
                    raise _fail("invalid_archive", "invalid ZIP payload") from None
                if len(data) != info.file_size or (binascii.crc32(data) & 0xFFFFFFFF) != info.CRC:
                    raise _fail("invalid_archive", "invalid ZIP size or CRC")
                members.append((path, is_directory, mode, data))
    except ReleaseArchiveError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error):
        raise _fail("invalid_archive", "invalid ZIP archive") from None
    _validate_member_table(members)
    return members


def _gzip_payload(raw: bytes) -> bytes:
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decompressor.decompress(raw) + decompressor.flush()
    except zlib.error:
        raise _fail("invalid_archive", "invalid gzip archive") from None
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise _fail("invalid_archive", "invalid gzip boundary")
    return payload


def _validate_tar_boundary(raw: bytes) -> None:
    offset = 0
    zero_blocks = 0
    while offset + 512 <= len(raw):
        block = raw[offset : offset + 512]
        if block == bytes(512):
            zero_blocks += 1
            offset += 512
            if zero_blocks == 2:
                if any(raw[offset:]):
                    raise _fail("invalid_archive", "invalid tar trailing data")
                return
            continue
        zero_blocks = 0
        try:
            size_field = block[124:136].rstrip(b"\0 ") or b"0"
            size = int(size_field, 8)
        except ValueError:
            raise _fail("invalid_archive", "invalid tar header") from None
        offset += 512 + ((size + 511) // 512) * 512
    raise _fail("invalid_archive", "invalid tar boundary")


def _load_tar_members(
    artifact: Path,
    expected_global_comment: str | None,
) -> list[tuple[PurePosixPath, bool, int, bytes]]:
    try:
        raw_artifact = _read_artifact(artifact)
        raw_tar = _gzip_payload(raw_artifact) if raw_artifact.startswith(b"\x1f\x8b") else raw_artifact
        _validate_tar_boundary(raw_tar)
        with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
            expected_pax = {} if expected_global_comment is None else {"comment": expected_global_comment}
            if archive.pax_headers != expected_pax:
                raise _fail("invalid_archive", "unexpected global PAX data")
            members: list[tuple[PurePosixPath, bool, int, bytes]] = []
            for info in archive.getmembers():
                if info.pax_headers != expected_pax:
                    raise _fail("invalid_archive", "unexpected member PAX data")
                if not (info.isfile() or info.isdir()):
                    raise _fail("unsupported_member", "unsupported tar member")
                path = _member_path(info.name, info.isdir())
                mode = _normalized_mode(info.mode)
                if info.isdir():
                    data = b""
                else:
                    stream = archive.extractfile(info)
                    if stream is None:
                        raise _fail("invalid_archive", "missing tar payload")
                    data = stream.read()
                    if len(data) != info.size:
                        raise _fail("invalid_archive", "invalid tar size")
                members.append((path, info.isdir(), mode, data))
    except ReleaseArchiveError:
        raise
    except (OSError, ValueError, tarfile.TarError):
        raise _fail("invalid_archive", "invalid tar archive") from None
    _validate_member_table(members)
    return members


def _open_directory(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    return os.open(name, flags, dir_fd=parent_fd)


def _ensure_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o755, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = _open_directory(descriptor, part)
            os.fchmod(child, 0o755)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _extract_members(
    destination: Path,
    members: list[tuple[PurePosixPath, bool, int, bytes]],
) -> None:
    destination = Path(destination)
    parent = destination.parent
    try:
        parent_metadata = os.lstat(parent)
        if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode):
            raise _fail("unsafe_destination", "unsafe extraction destination")
        os.lstat(destination)
    except FileNotFoundError:
        pass
    except ReleaseArchiveError:
        raise
    except OSError:
        raise _fail("unsafe_destination", "unsafe extraction destination") from None
    else:
        raise _fail("unsafe_destination", "unsafe extraction destination")

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        parent_fd = os.open(parent, flags)
    except OSError:
        raise _fail("unsafe_destination", "unsafe extraction destination") from None
    stage_name = f".{destination.name}.stage-{secrets.token_hex(8)}"
    stage_path = parent / stage_name
    created = False
    try:
        os.mkdir(stage_name, 0o700, dir_fd=parent_fd)
        created = True
        stage_fd = _open_directory(parent_fd, stage_name)
        try:
            for path, is_directory, mode, payload in members:
                parts = path.parts
                if is_directory:
                    descriptor = _ensure_directory(stage_fd, parts)
                    os.close(descriptor)
                    continue
                directory_fd = _ensure_directory(stage_fd, parts[:-1])
                try:
                    file_fd = os.open(
                        parts[-1],
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        mode,
                        dir_fd=directory_fd,
                    )
                    try:
                        view = memoryview(payload)
                        while view:
                            written = os.write(file_fd, view)
                            if written <= 0:
                                raise OSError("short archive write")
                            view = view[written:]
                        os.fchmod(file_fd, mode)
                    finally:
                        os.close(file_fd)
                finally:
                        os.close(directory_fd)
            os.fchmod(stage_fd, 0o755)
            try:
                os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise _fail("unsafe_destination", "unsafe extraction destination")
            os.rename(stage_name, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            created = False
        finally:
            os.close(stage_fd)
    except ReleaseArchiveError:
        raise
    except OSError:
        raise _fail("unsafe_destination", "unsafe extraction destination") from None
    finally:
        os.close(parent_fd)
        if created:
            shutil.rmtree(stage_path, ignore_errors=True)


def extract_regular_tar(
    artifact: Path,
    destination: Path,
    expected_global_comment: str | None = None,
) -> None:
    members = _load_tar_members(Path(artifact), expected_global_comment)
    _extract_members(Path(destination), members)


def extract_regular_zip(artifact: Path, destination: Path) -> None:
    members = _load_zip_members(Path(artifact))
    _extract_members(Path(destination), members)


def _source_regular_files(root: Path) -> dict[str, tuple[bytes, int]]:
    if not root.is_dir() or root.is_symlink():
        raise _fail("source_mismatch", "invalid source tree")
    result: dict[str, tuple[bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            if stat.S_ISDIR(metadata.st_mode):
                continue
            raise _fail("source_mismatch", "unsupported source member")
        relative = path.relative_to(root).as_posix()
        result[relative] = (path.read_bytes(), 0o755 if metadata.st_mode & 0o111 else 0o644)
    return result


def _expected_dos_timestamp(epoch: int) -> tuple[int, int, int, int, int, int]:
    moment = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc)
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second // 2 * 2)


def _parse_metadata(payload: bytes) -> tuple[object, bytes]:
    separator = b"\r\n\r\n" if b"\r\n\r\n" in payload else b"\n\n"
    if separator not in payload:
        raise _fail("metadata_mismatch", "metadata has no description body")
    header, body = payload.split(separator, 1)
    try:
        message = BytesParser(policy=email_policy).parsebytes(header + b"\n\n")
    except Exception:
        raise _fail("metadata_mismatch", "invalid metadata") from None
    return message, body


def _require_one(message: object, key: str, value: str) -> None:
    values = message.get_all(key, [])  # type: ignore[attr-defined]
    if values != [value]:
        raise _fail("metadata_mismatch", f"invalid {key}")


def _validate_python_metadata(payload: bytes, source: Path, version: str) -> None:
    message, body = _parse_metadata(payload)
    for key, value in (
        ("Metadata-Version", "2.5"),
        ("Name", "threadroot"),
        ("Version", version),
        ("Summary", "Local-first second-brain workflows for coding agents"),
        ("Author", "Threadroot contributors"),
        ("License-Expression", "Apache-2.0"),
        ("License-File", "LICENSE"),
        ("Requires-Python", ">=3.11"),
        ("Description-Content-Type", "text/markdown"),
    ):
        _require_one(message, key, value)
    if message.get_all("Project-URL", []) != [  # type: ignore[attr-defined]
        "Homepage, https://github.com/Will413028/threadroot",
        "Repository, https://github.com/Will413028/threadroot",
        "Issues, https://github.com/Will413028/threadroot/issues",
    ]:
        raise _fail("metadata_mismatch", "invalid Project-URL metadata")
    if message.get_all("Requires-Dist", []):  # type: ignore[attr-defined]
        raise _fail("metadata_mismatch", "runtime dependencies are forbidden")
    if body != (source / "README.md").read_bytes():
        raise _fail("source_mismatch", "README description differs from source")


def _validate_record(payload: bytes, order: list[str], contents: dict[str, bytes]) -> None:
    try:
        rows = list(csv.reader(io.StringIO(payload.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error):
        raise _fail("record_mismatch", "invalid wheel RECORD") from None
    if len(rows) != len(order) or [row[0] for row in rows if len(row) == 3] != order:
        raise _fail("record_mismatch", "wheel RECORD membership mismatch")
    for row, name in zip(rows, order, strict=True):
        if len(row) != 3:
            raise _fail("record_mismatch", "invalid wheel RECORD row")
        if name == order[-1]:
            if row[1:] != ["", ""]:
                raise _fail("record_mismatch", "wheel RECORD self-row is not empty")
            continue
        digest = base64.urlsafe_b64encode(hashlib_sha256(contents[name])).rstrip(b"=").decode()
        if row[1:] != [f"sha256={digest}", str(len(contents[name]))]:
            raise _fail("record_mismatch", "wheel RECORD hash or size mismatch")


def hashlib_sha256(payload: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(payload).digest()


def validate_wheel(artifact: Path, source: Path, version: str, epoch: int) -> None:
    artifact = Path(artifact)
    source = Path(source)
    package_source = _source_regular_files(source / "src/threadroot")
    package_names = sorted(f"threadroot/{name}" for name in package_source)
    prefix = f"threadroot-{version}.dist-info/"
    metadata_names = [
        prefix + "METADATA",
        prefix + "WHEEL",
        prefix + "entry_points.txt",
        prefix + "licenses/LICENSE",
        prefix + "RECORD",
    ]
    expected_order = package_names + metadata_names
    try:
        raw = _read_artifact(artifact)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not _zip_has_exact_bounds(raw, infos) or archive.comment:
                raise _fail("invalid_archive", "invalid wheel ZIP boundary")
            if [info.filename for info in infos] != expected_order:
                raise _fail("membership_mismatch", "wheel membership or order mismatch")
            contents: dict[str, bytes] = {}
            expected_timestamp = _expected_dos_timestamp(epoch)
            for info in infos:
                if info.is_dir():
                    raise _fail("unsupported_member", "wheel contains a directory")
                validate_archive_name(info.filename)
                type_bits = stat.S_IFMT(info.external_attr >> 16)
                expected_type = stat.S_IFREG if info.filename in package_names else 0
                if type_bits != expected_type:
                    raise _fail("metadata_mismatch", "wheel file type mismatch")
                expected_mode = (
                    package_source[info.filename.removeprefix("threadroot/")][1]
                    if info.filename in package_names
                    else 0o644
                )
                if stat.S_IMODE(info.external_attr >> 16) != expected_mode:
                    raise _fail("unsupported_mode", "wheel mode mismatch")
                local_flags = int.from_bytes(raw[info.header_offset + 6 : info.header_offset + 8], "little")
                if (
                    info.date_time != expected_timestamp
                    or info.create_system != 3
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    or info.flag_bits != 0
                    or local_flags != 0
                    or info.extra
                    or info.comment
                ):
                    raise _fail("metadata_mismatch", "wheel ZIP metadata mismatch")
                data = archive.read(info)
                if len(data) != info.file_size or (binascii.crc32(data) & 0xFFFFFFFF) != info.CRC:
                    raise _fail("invalid_archive", "wheel CRC or size mismatch")
                contents[info.filename] = data
    except ReleaseArchiveError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error):
        raise _fail("invalid_archive", "invalid wheel") from None

    for name, (payload, _mode) in package_source.items():
        if contents[f"threadroot/{name}"] != payload:
            raise _fail("source_mismatch", "wheel package differs from source")
    if contents[prefix + "licenses/LICENSE"] != (source / "LICENSE").read_bytes():
        raise _fail("source_mismatch", "wheel license differs from source")
    _validate_python_metadata(contents[prefix + "METADATA"], source, version)
    if contents[prefix + "entry_points.txt"] != b"[console_scripts]\nthreadroot = threadroot.cli:main\n":
        raise _fail("metadata_mismatch", "wheel entry point mismatch")
    wheel_message, wheel_body = _parse_metadata(contents[prefix + "WHEEL"])
    if wheel_body:
        raise _fail("metadata_mismatch", "unexpected WHEEL body")
    for key, value in (
        ("Wheel-Version", "1.0"),
        ("Generator", "hatchling 1.32.0"),
        ("Root-Is-Purelib", "true"),
        ("Tag", "py3-none-any"),
    ):
        _require_one(wheel_message, key, value)
    _validate_record(contents[prefix + "RECORD"], expected_order, contents)


def _selected_source_files(source: Path, roots: list[str]) -> dict[str, tuple[bytes, int]]:
    selected: dict[str, tuple[bytes, int]] = {}
    for root_name in roots:
        relative = validate_archive_name(root_name)
        target = source.joinpath(*relative.parts)
        try:
            metadata = target.lstat()
        except OSError:
            raise _fail("source_mismatch", "selected source root is missing") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise _fail("source_mismatch", "selected source root is a symlink")
        if stat.S_ISREG(metadata.st_mode):
            selected[relative.as_posix()] = (
                target.read_bytes(),
                0o755 if metadata.st_mode & 0o111 else 0o644,
            )
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise _fail("source_mismatch", "unsupported selected source root")
        for path in sorted(target.rglob("*")):
            item = path.lstat()
            if stat.S_ISDIR(item.st_mode):
                continue
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
                raise _fail("source_mismatch", "unsupported selected source member")
            name = path.relative_to(source).as_posix()
            selected[name] = (path.read_bytes(), 0o755 if item.st_mode & 0o111 else 0o644)
    for required in (".gitignore", "pyproject.toml"):
        path = source / required
        try:
            item = path.lstat()
        except OSError:
            raise _fail("source_mismatch", f"missing {required}") from None
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
            raise _fail("source_mismatch", f"invalid {required}")
        selected[required] = (path.read_bytes(), 0o755 if item.st_mode & 0o111 else 0o644)
    return selected


def validate_sdist(artifact: Path, source: Path, version: str, epoch: int) -> None:
    artifact = Path(artifact)
    source = Path(source)
    try:
        project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
        roots = project["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
        if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
            raise KeyError("only-include")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        raise _fail("source_mismatch", "invalid sdist source configuration") from None
    source_files = _selected_source_files(source, roots)
    prefix = f"threadroot-{version}/"
    pkg_name = "PKG-INFO"
    expected_names = set(source_files) | {pkg_name}

    try:
        raw_gzip = _read_artifact(artifact)
        if len(raw_gzip) < 10 or raw_gzip[:3] != b"\x1f\x8b\x08":
            raise _fail("invalid_archive", "invalid gzip header")
        flags = raw_gzip[3]
        gzip_mtime = int.from_bytes(raw_gzip[4:8], "little")
        if flags != 0 or gzip_mtime != epoch or raw_gzip[8] != 2 or raw_gzip[9] != 255:
            raise _fail("metadata_mismatch", "noncanonical gzip metadata")
        raw_tar = _gzip_payload(raw_gzip)
        _validate_tar_boundary(raw_tar)
        with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
            if archive.pax_headers:
                raise _fail("metadata_mismatch", "unexpected global PAX metadata")
            infos = archive.getmembers()
            names: list[str] = []
            contents: dict[str, bytes] = {}
            for info in infos:
                if not info.isfile():
                    raise _fail("unsupported_member", "sdist member is not a regular file")
                if info.pax_headers:
                    raise _fail("metadata_mismatch", "unexpected member PAX metadata")
                full = validate_archive_name(info.name).as_posix()
                if not full.startswith(prefix):
                    raise _fail("membership_mismatch", "sdist top-level prefix mismatch")
                name = full[len(prefix):]
                validate_archive_name(name)
                if name in contents:
                    raise _fail("duplicate_member", "duplicate sdist member")
                if (
                    info.uid != 0
                    or info.gid != 0
                    or info.uname
                    or info.gname
                    or info.mtime != epoch
                ):
                    raise _fail("metadata_mismatch", "sdist tar metadata mismatch")
                expected_mode = 0o644 if name == pkg_name else source_files.get(name, (b"", -1))[1]
                if info.mode != expected_mode:
                    raise _fail("unsupported_mode", "sdist mode mismatch")
                stream = archive.extractfile(info)
                if stream is None:
                    raise _fail("invalid_archive", "missing sdist payload")
                payload = stream.read()
                if len(payload) != info.size:
                    raise _fail("invalid_archive", "sdist size mismatch")
                names.append(name)
                contents[name] = payload
    except ReleaseArchiveError:
        raise
    except (OSError, ValueError, tarfile.TarError, zlib.error):
        raise _fail("invalid_archive", "invalid sdist") from None

    if set(names) != expected_names or len(names) != len(expected_names):
        raise _fail("membership_mismatch", "sdist membership mismatch")
    for name, (payload, _mode) in source_files.items():
        if contents[name] != payload:
            raise _fail("source_mismatch", "sdist payload differs from source")
    _validate_python_metadata(contents[pkg_name], source, version)


def _host_source_files(source: Path, host: str) -> dict[str, bytes]:
    if host not in HOST_MANIFESTS:
        raise _fail("unsupported_host", "unsupported release host")
    selected = [*COMMON_ROOTS, MARKETPLACE, HOST_MANIFESTS[host]]
    result: dict[str, bytes] = {}
    for relative in selected:
        target = source / relative
        try:
            metadata = target.lstat()
        except OSError:
            raise _fail("source_mismatch", "host source input is missing") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise _fail("source_mismatch", "host source input is a symlink")
        if stat.S_ISREG(metadata.st_mode):
            result[relative.as_posix()] = target.read_bytes()
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise _fail("source_mismatch", "unsupported host source input")
        for path in sorted(target.rglob("*")):
            item = path.lstat()
            if stat.S_ISDIR(item.st_mode):
                continue
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
                raise _fail("source_mismatch", "unsupported host source member")
            result[path.relative_to(source).as_posix()] = path.read_bytes()
    return result


def validate_host_zip(artifact: Path, source: Path, host: str) -> None:
    expected = _host_source_files(Path(source), host)
    expected_names = sorted(expected)
    try:
        raw = _read_artifact(Path(artifact))
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not _zip_has_exact_bounds(raw, infos) or archive.comment:
                raise _fail("invalid_archive", "invalid host ZIP boundary")
            if [info.filename for info in infos] != expected_names:
                raise _fail("membership_mismatch", "host ZIP membership or order mismatch")
            for info in infos:
                validate_archive_name(info.filename)
                local_flags = int.from_bytes(raw[info.header_offset + 6 : info.header_offset + 8], "little")
                if (
                    info.is_dir()
                    or info.date_time != ZIP_TIMESTAMP
                    or info.create_system != 3
                    or info.flag_bits != 0x800
                    or local_flags != 0x800
                    or info.external_attr >> 16 != stat.S_IFREG | 0o644
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    or info.extra
                    or info.comment
                ):
                    raise _fail("metadata_mismatch", "host ZIP metadata mismatch")
                payload = archive.read(info)
                if (
                    len(payload) != info.file_size
                    or (binascii.crc32(payload) & 0xFFFFFFFF) != info.CRC
                ):
                    raise _fail("invalid_archive", "host ZIP CRC or size mismatch")
                if payload != expected[info.filename]:
                    raise _fail("source_mismatch", "host ZIP payload differs from source")
    except ReleaseArchiveError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, zlib.error):
        raise _fail("invalid_archive", "invalid host ZIP") from None
