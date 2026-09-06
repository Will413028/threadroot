from __future__ import annotations

import io
import base64
from dataclasses import FrozenInstanceError
import errno
import gzip
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings
import zipfile
import zlib

from scripts import build_release
from scripts import release_archives
from scripts.build_release import build_archive
from scripts.release_archives import (
    ReleaseArchiveError,
    ReleaseSourceEntry,
    ReleaseSourceSnapshot,
    capture_release_source,
    extract_regular_tar,
    extract_regular_tar_payload,
    extract_regular_zip,
    extract_regular_zip_payload,
    validate_archive_name,
    validate_host_zip,
    validate_host_zip_payload,
    validate_sdist,
    validate_sdist_payload,
    validate_wheel,
    validate_wheel_payload,
)


def _tar_bytes(entries: list[tuple[str, bytes, int, bytes]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload, mode, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.mode = mode
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if kind == tarfile.REGTYPE:
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            else:
                archive.addfile(info)
    return output.getvalue()


def _zip_bytes(entries: list[tuple[str, bytes, int]]) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload, mode in entries:
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
    return output.getvalue()


WHEEL_EPOCH = 1_700_000_000
WHEEL_TIMESTAMP = (2023, 11, 14, 22, 13, 20)


def _make_wheel_source(root: Path) -> Path:
    source = root / "source"
    package = source / "src/threadroot"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b'__version__ = "0.1.0"\n')
    (package / "cli.py").write_bytes(b"def main():\n    return 0\n")
    (source / "README.md").write_bytes(b"# Synthetic Threadroot\n")
    (source / "LICENSE").write_bytes(b"synthetic license\n")
    return source


def _wheel_payloads(source: Path) -> tuple[list[str], dict[str, bytes]]:
    package_names = ["threadroot/__init__.py", "threadroot/cli.py"]
    prefix = "threadroot-0.1.0.dist-info/"
    metadata = (
        "Metadata-Version: 2.5\n"
        "Name: threadroot\n"
        "Version: 0.1.0\n"
        "Summary: Local-first second-brain workflows for coding agents\n"
        "Author: Threadroot contributors\n"
        "License-Expression: Apache-2.0\n"
        "License-File: LICENSE\n"
        "Requires-Python: >=3.11\n"
        "Description-Content-Type: text/markdown\n"
        "Project-URL: Homepage, https://github.com/Will413028/threadroot\n"
        "Project-URL: Repository, https://github.com/Will413028/threadroot\n"
        "Project-URL: Issues, https://github.com/Will413028/threadroot/issues\n"
        "\n"
    ).encode() + (source / "README.md").read_bytes()
    payloads = {
        package_names[0]: (source / "src/threadroot/__init__.py").read_bytes(),
        package_names[1]: (source / "src/threadroot/cli.py").read_bytes(),
        prefix + "METADATA": metadata,
        prefix + "WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: hatchling 1.32.0\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
            "\n"
        ).encode(),
        prefix + "entry_points.txt": b"[console_scripts]\nthreadroot = threadroot.cli:main\n",
        prefix + "licenses/LICENSE": (source / "LICENSE").read_bytes(),
    }
    record_name = prefix + "RECORD"
    order = sorted(package_names) + [
        prefix + "METADATA",
        prefix + "WHEEL",
        prefix + "entry_points.txt",
        prefix + "licenses/LICENSE",
        record_name,
    ]
    rows = []
    for name in order[:-1]:
        digest = base64.urlsafe_b64encode(hashlib.sha256(payloads[name]).digest()).rstrip(b"=").decode()
        rows.append(f"{name},sha256={digest},{len(payloads[name])}\n")
    rows.append(f"{record_name},,\n")
    payloads[record_name] = "".join(rows).encode()
    return order, payloads


def _write_wheel(path: Path, order: list[str], payloads: dict[str, bytes], *, regenerate_record: bool = True) -> None:
    prefix = "threadroot-0.1.0.dist-info/"
    record_name = prefix + "RECORD"
    payloads = dict(payloads)
    if record_name in order and regenerate_record:
        rows = []
        for name in order:
            if name == record_name:
                rows.append(f"{name},,\n")
            else:
                digest = base64.urlsafe_b64encode(hashlib.sha256(payloads[name]).digest()).rstrip(b"=").decode()
                rows.append(f"{name},sha256={digest},{len(payloads[name])}\n")
        payloads[record_name] = "".join(rows).encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in order:
            info = zipfile.ZipInfo(name, WHEEL_TIMESTAMP)
            info.create_system = 3
            info.external_attr = (
                ((stat.S_IFREG | 0o644) << 16)
                if not name.startswith(prefix)
                else (0o644 << 16)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payloads[name])


def _make_sdist_source(root: Path) -> Path:
    source = root / "sdist-source"
    (source / "src/threadroot").mkdir(parents=True)
    (source / "src/threadroot/__init__.py").write_bytes(b'__version__ = "0.1.0"\n')
    (source / "README.md").write_bytes(b"# Synthetic Threadroot\n")
    (source / "LICENSE").write_bytes(b"synthetic license\n")
    (source / ".gitignore").write_bytes(b"dist/\n")
    roots = [
        ".claude-plugin", ".codex-plugin", ".dockerignore", "AGENTS.md", "CONTRIBUTING.md",
        "LICENSE", "README.md", "SECURITY.md", "docs", "requirements", "scripts", "skills",
        "src/threadroot", "templates", "tests", "tools/release",
    ]
    for name in roots:
        path = source / name
        if path.exists():
            continue
        if "." in path.name or path.name.isupper():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((name + "\n").encode())
        else:
            path.mkdir(parents=True)
            (path / "fixture.txt").write_bytes((name + "\n").encode())
    (source / "pyproject.toml").write_text(
        '[project]\nname = "threadroot"\nversion = "0.1.0"\n'
        'description = "Local-first second-brain workflows for coding agents"\n'
        'readme = "README.md"\nrequires-python = ">=3.11"\n'
        'license = "Apache-2.0"\nlicense-files = ["LICENSE"]\n'
        'authors = [{ name = "Threadroot contributors" }]\ndependencies = []\n'
        '[project.urls]\nHomepage = "https://github.com/Will413028/threadroot"\n'
        'Repository = "https://github.com/Will413028/threadroot"\n'
        'Issues = "https://github.com/Will413028/threadroot/issues"\n'
        '[tool.hatch.build.targets.sdist]\nonly-include = ' + repr(roots).replace("'", '"') + '\n',
        encoding="utf-8",
    )
    return source


def _pkg_info(source: Path) -> bytes:
    return (
        "Metadata-Version: 2.5\n"
        "Name: threadroot\n"
        "Version: 0.1.0\n"
        "Summary: Local-first second-brain workflows for coding agents\n"
        "Author: Threadroot contributors\n"
        "License-Expression: Apache-2.0\n"
        "License-File: LICENSE\n"
        "Requires-Python: >=3.11\n"
        "Description-Content-Type: text/markdown\n"
        "Project-URL: Homepage, https://github.com/Will413028/threadroot\n"
        "Project-URL: Repository, https://github.com/Will413028/threadroot\n"
        "Project-URL: Issues, https://github.com/Will413028/threadroot/issues\n"
        "\n"
    ).encode() + (source / "README.md").read_bytes()


def _sdist_entries(source: Path) -> list[dict[str, object]]:
    prefix = "threadroot-0.1.0/"
    names = sorted(
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    )
    entries = [
        {"name": prefix + name, "payload": (source / name).read_bytes(), "kind": tarfile.REGTYPE,
         "mode": 0o644, "mtime": WHEEL_EPOCH, "uid": 0, "gid": 0}
        for name in names
    ]
    entries.append({"name": prefix + "PKG-INFO", "payload": _pkg_info(source), "kind": tarfile.REGTYPE,
                    "mode": 0o644, "mtime": WHEEL_EPOCH, "uid": 0, "gid": 0})
    return entries


def _write_sdist(path: Path, entries: list[dict[str, object]], *, gzip_mtime: int = WHEEL_EPOCH,
                 tar_suffix: bytes = b"", gzip_suffix: bytes = b"") -> None:
    tar_output = io.BytesIO()
    with tarfile.open(fileobj=tar_output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for entry in entries:
            info = tarfile.TarInfo(str(entry["name"]))
            info.type = entry["kind"]  # type: ignore[assignment]
            info.mode = int(entry["mode"])
            info.mtime = int(entry["mtime"])
            info.uid = int(entry["uid"])
            info.gid = int(entry["gid"])
            info.uname = info.gname = ""
            payload = bytes(entry["payload"])
            if info.isfile():
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            else:
                archive.addfile(info)
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", compresslevel=9, mtime=gzip_mtime) as stream:
        stream.write(tar_output.getvalue() + tar_suffix)
    path.write_bytes(compressed.getvalue() + gzip_suffix)


def _make_host_source(root: Path) -> Path:
    source = root / "host-source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    for relative in (
        "LICENSE", "README.md", "CONTRIBUTING.md", "SECURITY.md", "docs/testing.md",
        ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json",
        "skills/example/SKILL.md", "templates/example.md",
    ):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"synthetic {relative}\n", encoding="utf-8")
    return source


def _rewrite_host_zip(
    source_artifact: Path,
    target: Path,
    *,
    mutation: str,
) -> None:
    with zipfile.ZipFile(source_artifact) as archive:
        items = [(info, archive.read(info)) for info in archive.infolist()]
    if mutation == "ordering":
        items.reverse()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (old, payload) in enumerate(items):
            info_class = zipfile.ZipInfo if mutation == "utf8" else build_release._UTF8ZipInfo
            timestamp = (1981, 1, 1, 0, 0, 0) if mutation == "timestamp" and index == 0 else old.date_time
            info = info_class(old.filename, timestamp)
            info.create_system = 0 if mutation == "create-system" and index == 0 else 3
            info.external_attr = (
                (stat.S_IFREG | 0o755) << 16
                if mutation == "mode" and index == 0
                else (stat.S_IFREG | 0o644) << 16
            )
            info.extra = b"xx" if mutation == "extra" and index == 0 else b""
            info.comment = b"comment" if mutation == "comment" and index == 0 else b""
            info.compress_type = zipfile.ZIP_DEFLATED
            if mutation == "source-byte" and index == 0:
                payload += b"changed"
            archive.writestr(info, payload)


def _eocd_offset(payload: bytes) -> int:
    offset = payload.rfind(b"PK\x05\x06")
    if offset < 0:
        raise AssertionError("fixture has no EOCD")
    return offset


def _add_trailing_bytes_to_last_deflate_stream(
    payload: bytes,
    marker: bytes = b"SYNTHETIC-FRAMING-MARKER",
) -> bytes:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        info = archive.infolist()[-1]
    if info.compress_type != zipfile.ZIP_DEFLATED:
        raise AssertionError("last ZIP member is not DEFLATE compressed")

    local_offset = info.header_offset
    name_size = int.from_bytes(payload[local_offset + 26 : local_offset + 28], "little")
    extra_size = int.from_bytes(payload[local_offset + 28 : local_offset + 30], "little")
    data_end = local_offset + 30 + name_size + extra_size + info.compress_size
    eocd = _eocd_offset(payload)
    central_offset = int.from_bytes(payload[eocd + 16 : eocd + 20], "little")
    if data_end != central_offset:
        raise AssertionError("last ZIP member is not adjacent to the central directory")

    central_cursor = central_offset
    target_central: int | None = None
    while central_cursor < eocd:
        if payload[central_cursor : central_cursor + 4] != b"PK\x01\x02":
            raise AssertionError("fixture has an invalid central directory")
        current_local = int.from_bytes(payload[central_cursor + 42 : central_cursor + 46], "little")
        if current_local == local_offset:
            target_central = central_cursor
        central_cursor += (
            46
            + int.from_bytes(payload[central_cursor + 28 : central_cursor + 30], "little")
            + int.from_bytes(payload[central_cursor + 30 : central_cursor + 32], "little")
            + int.from_bytes(payload[central_cursor + 32 : central_cursor + 34], "little")
        )
    if target_central is None:
        raise AssertionError("last ZIP member has no central record")

    changed = bytearray(payload)
    changed[local_offset + 18 : local_offset + 22] = (
        info.compress_size + len(marker)
    ).to_bytes(4, "little")
    changed[target_central + 20 : target_central + 24] = (
        info.compress_size + len(marker)
    ).to_bytes(4, "little")
    changed[data_end:data_end] = marker
    changed[eocd + len(marker) + 16 : eocd + len(marker) + 20] = (
        central_offset + len(marker)
    ).to_bytes(4, "little")
    return bytes(changed)


def _tar_checksum(header: bytearray) -> None:
    header[148:156] = b"        "
    header[148:156] = f"{sum(header):06o}\0 ".encode("ascii")


def _git_tar_checksum(header: bytearray) -> None:
    header[148:156] = b"        "
    header[148:156] = f"{sum(header):07o}\0".encode("ascii")


def _mutate_first_tar_header(
    payload: bytes,
    *,
    typeflag: bytes | None = None,
    linkname: bytes | None = None,
    reserved_tail: bytes | None = None,
    padding_marker: bytes | None = None,
    name_tail: bytes | None = None,
    name: bytes | None = None,
    size_field: bytes | None = None,
) -> bytes:
    changed = bytearray(payload)
    if changed[257:262] != b"ustar":
        raise AssertionError("fixture has no first ustar header")
    header = changed[:512]
    if typeflag is not None:
        if len(typeflag) != 1:
            raise AssertionError("tar typeflag must be exactly one byte")
        header[156:157] = typeflag
    if linkname is not None:
        if len(linkname) > 100:
            raise AssertionError("tar linkname marker is too long")
        header[157:257] = linkname.ljust(100, b"\0")
    if reserved_tail is not None:
        if len(reserved_tail) > 12:
            raise AssertionError("tar reserved-tail marker is too long")
        header[500:512] = reserved_tail.ljust(12, b"\0")
    if name_tail is not None:
        name_end = header[:100].find(b"\0")
        if name_end < 0 or name_end + 1 + len(name_tail) > 100:
            raise AssertionError("first tar name has insufficient NUL padding")
        header[name_end + 1 : name_end + 1 + len(name_tail)] = name_tail
    if name is not None:
        if not name or len(name) > 100:
            raise AssertionError("first tar name must be 1-100 bytes")
        header[:100] = name.ljust(100, b"\0")
    if size_field is not None:
        if len(size_field) != 12:
            raise AssertionError("tar size field must be exactly 12 bytes")
        header[124:136] = size_field
    if any(
        value is not None
        for value in (typeflag, linkname, reserved_tail, name_tail, name, size_field)
    ):
        _tar_checksum(header)
        changed[:512] = header
    if padding_marker is not None:
        size_field = bytes(header[124:136]).rstrip(b"\0 ") or b"0"
        size = int(size_field, 8)
        padding_start = 512 + size
        padding_end = 512 + ((size + 511) // 512) * 512
        if not padding_marker or padding_start + len(padding_marker) > padding_end:
            raise AssertionError("first tar member has insufficient alignment padding")
        changed[padding_start : padding_start + len(padding_marker)] = padding_marker
    return bytes(changed)


def _tar_metadata_member(typeflag: bytes, payload: bytes) -> bytes:
    info = tarfile.TarInfo("././@SyntheticMeta")
    info.type = typeflag
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.size = len(payload)
    header = info.tobuf(format=tarfile.PAX_FORMAT)
    return header + payload.ljust(((len(payload) + 511) // 512) * 512, b"\0")


def _prepend_tar_metadata_header(
    payload: bytes,
    typeflag: bytes,
    metadata: bytes = b"\0SYNTHETIC-HIDDEN",
) -> bytes:
    return _tar_metadata_member(typeflag, metadata) + payload


def _hide_metadata_behind_directory_size(payload: bytes) -> bytes:
    if payload[156:157] != tarfile.DIRTYPE:
        raise AssertionError("fixture does not start with a directory")
    metadata = _tar_metadata_member(
        tarfile.GNUTYPE_LONGNAME,
        b"safe/file.txt\0SYNTHETIC-HIDDEN",
    )
    changed = payload[:512] + metadata + payload[512:]
    return _mutate_first_tar_header(
        changed,
        size_field=f"{len(metadata):011o}\0".encode("ascii"),
    )


def _prepend_gnu_longname_header(payload: bytes, member_name: str) -> bytes:
    hidden_suffix = b"\0SYNTHETIC-LONGNAME-TRAILER"
    longname = member_name.encode("utf-8") + hidden_suffix
    info = tarfile.TarInfo("././@LongLink")
    info.type = tarfile.GNUTYPE_LONGNAME
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.size = len(longname)
    header = info.tobuf(format=tarfile.GNU_FORMAT)
    padded = longname.ljust(((len(longname) + 511) // 512) * 512, b"\0")
    return header + padded + payload


def _gzip_tar_payload(payload: bytes, *, mtime: int = WHEEL_EPOCH) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        fileobj=output,
        mode="wb",
        filename="",
        compresslevel=9,
        mtime=mtime,
    ) as stream:
        stream.write(payload)
    return output.getvalue()


def _mutate_local_zip(payload: bytes, mutation: str) -> bytes:
    changed = bytearray(payload)
    if changed[:4] != b"PK\x03\x04":
        raise AssertionError("fixture has no first local header")
    name_size = int.from_bytes(changed[26:28], "little")
    extra_size = int.from_bytes(changed[28:30], "little")
    if mutation == "timestamp":
        changed[10:12] = (1).to_bytes(2, "little")
    elif mutation == "crc":
        changed[14:18] = (0).to_bytes(4, "little")
    elif mutation == "compression":
        changed[8:10] = zipfile.ZIP_STORED.to_bytes(2, "little")
    elif mutation == "extra":
        insertion = 30 + name_size + extra_size
        changed[28:30] = (extra_size + 2).to_bytes(2, "little")
        changed[insertion:insertion] = b"xx"
        eocd = _eocd_offset(changed)
        central = int.from_bytes(changed[eocd + 16 : eocd + 20], "little")
        changed[eocd + 16 : eocd + 20] = (central + 2).to_bytes(4, "little")
    elif mutation == "interstitial":
        eocd = _eocd_offset(changed)
        central = int.from_bytes(changed[eocd + 16 : eocd + 20], "little")
        changed[central:central] = b"JUNK"
        eocd += 4
        changed[eocd + 16 : eocd + 20] = (central + 4).to_bytes(4, "little")
    elif mutation == "nul-name":
        local_name = 30
        changed[local_name + name_size - 1] = 0
        eocd = _eocd_offset(changed)
        central = int.from_bytes(changed[eocd + 16 : eocd + 20], "little")
        central_name_size = int.from_bytes(changed[central + 28 : central + 30], "little")
        if central_name_size != name_size:
            raise AssertionError("fixture filename lengths differ")
        changed[central + 46 + central_name_size - 1] = 0
    else:
        raise AssertionError(mutation)
    result = bytes(changed)
    if result == payload:
        raise AssertionError("mutation did not change fixture")
    return result


def _mutate_zip_fixed_header(payload: bytes, mutation: str) -> bytes:
    changed = bytearray(payload)
    eocd = _eocd_offset(changed)
    central = int.from_bytes(changed[eocd + 16 : eocd + 20], "little")
    if changed[central : central + 4] != b"PK\x01\x02":
        raise AssertionError("fixture has no first central header")
    local = int.from_bytes(changed[central + 42 : central + 46], "little")
    if changed[local : local + 4] != b"PK\x03\x04":
        raise AssertionError("fixture has no matching local header")

    mutations = {
        "local-needed": ((local + 4, b"\x15\x00"),),
        "central-needed": ((central + 6, b"\x15\x00"),),
        "consistent-needed": (
            (local + 4, b"\x15\x00"),
            (central + 6, b"\x15\x00"),
        ),
        "made-version": ((central + 4, b"\x15"),),
        "made-system": ((central + 5, b"\x04"),),
        "disk-start": ((central + 34, b"\x01\x00"),),
        "internal-attrs": ((central + 36, b"\x01\x00"),),
        "clear-utf8-flags": (
            (local + 6, b"\x00\x00"),
            (central + 8, b"\x00\x00"),
        ),
        "external-low-bits": (
            (
                central + 38,
                (
                    int.from_bytes(changed[central + 38 : central + 42], "little")
                    | 1
                ).to_bytes(4, "little"),
            ),
        ),
    }
    try:
        edits = mutations[mutation]
    except KeyError:
        raise AssertionError(mutation) from None
    for offset, value in edits:
        changed[offset : offset + len(value)] = value
    result = bytes(changed)
    if result == payload:
        raise AssertionError("mutation did not change fixture")
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        info = archive.infolist()[0]
        archive.read(info)
    return result


def _mutate_first_zip_declared_size(payload: bytes, size: int) -> bytes:
    changed = bytearray(payload)
    eocd = _eocd_offset(changed)
    central = int.from_bytes(changed[eocd + 16 : eocd + 20], "little")
    if changed[central : central + 4] != b"PK\x01\x02":
        raise AssertionError("fixture has no first central header")
    local = int.from_bytes(changed[central + 42 : central + 46], "little")
    if changed[local : local + 4] != b"PK\x03\x04":
        raise AssertionError("fixture has no matching local header")
    encoded = size.to_bytes(4, "little")
    changed[local + 22 : local + 26] = encoded
    changed[central + 24 : central + 28] = encoded
    result = bytes(changed)
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        if archive.infolist()[0].file_size != size:
            raise AssertionError("declared ZIP size mutation was not observed")
    return result


class CommonArchiveTests(unittest.TestCase):
    def test_artifact_same_size_rewrite_with_restored_mtime_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "archive.tar"
            artifact.write_bytes(_tar_bytes([("safe.txt", b"safe\n", 0o644, tarfile.REGTYPE)]))
            metadata = artifact.stat()
            original_read = os.read
            changed = False

            def racing_read(descriptor: int, size: int) -> bytes:
                nonlocal changed
                payload = original_read(descriptor, size)
                if payload and not changed:
                    changed = True
                    replacement = bytearray(artifact.read_bytes())
                    replacement[-1] ^= 1
                    artifact.write_bytes(replacement)
                    os.utime(artifact, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                return payload

            with patch("scripts.release_archives.os.read", side_effect=racing_read), self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(artifact, root / "out")
            self.assertTrue(changed)

    def test_validate_archive_name_rejects_unsafe_forms(self) -> None:
        invalid = ("", "/absolute", "../escape", "safe/../../escape", "dir\\file")
        for name in invalid:
            with self.subTest(name=name), self.assertRaisesRegex(
                ReleaseArchiveError, "unsafe archive path"
            ):
                validate_archive_name(name)

    def test_validate_archive_name_rejects_empty_nul_and_backslash_components(self) -> None:
        for name in ("a//b", "a/./b", "a/../b", "a\0b", "a\\b"):
            with self.subTest(name=name), self.assertRaises(ReleaseArchiveError) as raised:
                validate_archive_name(name)
            self.assertEqual(raised.exception.code, "unsafe_path")

    def test_extractors_reject_existing_or_unsafe_destination(self) -> None:
        tar_payload = _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)])
        zip_payload = _zip_bytes([("safe/file.txt", b"safe\n", stat.S_IFREG | 0o644)])
        for label, payload, suffix, extractor in (
            ("tar", tar_payload, ".tar", extract_regular_tar),
            ("zip", zip_payload, ".zip", extract_regular_zip),
        ):
            for state in ("empty", "nonempty", "symlink-parent"):
                with self.subTest(format=label, state=state), TemporaryDirectory() as directory:
                    root = Path(directory)
                    artifact = root / f"artifact{suffix}"
                    artifact.write_bytes(payload)
                    if state == "symlink-parent":
                        real = root / "real"
                        real.mkdir()
                        parent = root / "linked"
                        parent.symlink_to(real, target_is_directory=True)
                        destination = parent / "out"
                    else:
                        destination = root / "out"
                        destination.mkdir()
                        if state == "nonempty":
                            (destination / "existing").write_text("keep\n", encoding="utf-8")
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        extractor(artifact, destination)
                    self.assertEqual(raised.exception.code, "unsafe_destination")
                    if state != "symlink-parent":
                        self.assertTrue(destination.is_dir())

    def test_extractors_reject_symlink_artifacts_without_creating_destination(self) -> None:
        tar_payload = _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)])
        zip_payload = _zip_bytes([("safe/file.txt", b"safe\n", stat.S_IFREG | 0o644)])
        for label, payload, suffix, extractor in (
            ("tar", tar_payload, ".tar", extract_regular_tar),
            ("zip", zip_payload, ".zip", extract_regular_zip),
        ):
            with self.subTest(format=label), TemporaryDirectory() as directory:
                root = Path(directory)
                real = root / f"real{suffix}"
                real.write_bytes(payload)
                artifact = root / f"linked{suffix}"
                artifact.symlink_to(real)
                destination = root / "out"
                with self.assertRaises(ReleaseArchiveError) as raised:
                    extractor(artifact, destination)
                self.assertEqual(raised.exception.code, "invalid_archive")
                self.assertFalse(destination.exists())

    def test_tar_global_comment_is_exact_and_path_overrides_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "comment.tar"
            output = io.BytesIO()
            with tarfile.open(
                fileobj=output,
                mode="w",
                format=tarfile.PAX_FORMAT,
                pax_headers={"comment": "commit-sha"},
            ) as archive:
                info = tarfile.TarInfo("safe/file.txt")
                info.mode = 0o644
                info.size = 5
                archive.addfile(info, io.BytesIO(b"safe\n"))
            artifact.write_bytes(output.getvalue())
            destination = root / "out"
            extract_regular_tar(artifact, destination, expected_global_comment="commit-sha")
            self.assertEqual((destination / "safe/file.txt").read_bytes(), b"safe\n")
            with self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(artifact, root / "other")

            overridden = root / "override.tar"
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT, pax_headers={"comment": "commit-sha"}) as archive:
                info = tarfile.TarInfo("safe/file.txt")
                info.mode = 0o644
                info.size = 5
                info.pax_headers = {"path": "renamed/file.txt"}
                archive.addfile(info, io.BytesIO(b"safe\n"))
            overridden.write_bytes(output.getvalue())
            with tarfile.open(overridden, "r:") as archive:
                self.assertEqual(archive.getmembers()[0].pax_headers["path"], "renamed/file.txt")
            with self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(overridden, root / "override-out", expected_global_comment="commit-sha")

            hidden = root / "hidden-global.tar"
            regular = _tar_bytes(
                [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
            )
            hidden.write_bytes(
                _prepend_tar_metadata_header(
                    regular,
                    tarfile.XGLTYPE,
                    b"22 comment=commit-sha\n\0SYNTHETIC-HIDDEN",
                )
            )
            with self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(
                    hidden,
                    root / "hidden-out",
                    expected_global_comment="commit-sha",
                )
            self.assertFalse((root / "hidden-out").exists())

    def test_tar_rejects_unsafe_duplicate_link_special_mode_and_archive_data(self) -> None:
        regular = ("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)
        cases = {
            "absolute": ([_tar_entry("/absolute", tarfile.REGTYPE)], None, "unsafe_path"),
            "parent": ([_tar_entry("../escape", tarfile.REGTYPE)], None, "unsafe_path"),
            "backslash": ([_tar_entry("safe\\file", tarfile.REGTYPE)], None, "unsafe_path"),
            "empty-component": ([_tar_entry("safe//file", tarfile.REGTYPE)], None, "unsafe_path"),
            "nul": (None, b"not a tar with nul\0", "invalid_archive"),
            "duplicate": ([regular, regular], None, "duplicate_member"),
            "symlink": ([_tar_entry("safe/link", tarfile.SYMTYPE)], None, "unsupported_member"),
            "hardlink": ([_tar_entry("safe/link", tarfile.LNKTYPE)], None, "unsupported_member"),
            "character": ([_tar_entry("safe/dev", tarfile.CHRTYPE)], None, "unsupported_member"),
            "block": ([_tar_entry("safe/dev", tarfile.BLKTYPE)], None, "unsupported_member"),
            "fifo": ([_tar_entry("safe/fifo", tarfile.FIFOTYPE)], None, "unsupported_member"),
            "mode": ([("safe/file.txt", b"safe\n", 0o600, tarfile.REGTYPE)], None, "unsupported_mode"),
            "leading-data": (None, b"prefix", "invalid_archive"),
            "trailing-data": (None, b"suffix", "invalid_archive"),
        }
        for label, (entries, raw_marker, code) in cases.items():
            with self.subTest(case=label), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "artifact.tar"
                if entries is not None:
                    payload = _tar_bytes(entries)
                elif label == "leading-data":
                    payload = raw_marker + _tar_bytes([regular])
                elif label == "trailing-data":
                    payload = _tar_bytes([regular]) + raw_marker
                else:
                    payload = raw_marker
                artifact.write_bytes(payload)
                destination = root / "out"
                with self.assertRaises(ReleaseArchiveError) as raised:
                    extract_regular_tar(artifact, destination)
                self.assertEqual(raised.exception.code, code)
                self.assertFalse(destination.exists())

    def test_tar_extractors_reject_non_regular_isfile_types_before_destination_access(self) -> None:
        original = _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)])
        for typeflag in (tarfile.GNUTYPE_SPARSE, tarfile.CONTTYPE):
            payload = _mutate_first_tar_header(original, typeflag=typeflag)
            self.assertEqual(payload[156:157], typeflag)
            for api in ("path", "payload"):
                with self.subTest(typeflag=typeflag, api=api), TemporaryDirectory() as directory:
                    root = Path(directory)
                    artifact = root / "artifact.tar"
                    artifact.write_bytes(payload)
                    destination = root / "out"
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        if api == "path":
                            extract_regular_tar(artifact, destination)
                        else:
                            extract_regular_tar_payload(payload, destination)
                    self.assertEqual(raised.exception.code, "unsupported_member")
                    self.assertFalse(destination.exists())

    def test_generic_tar_extractor_accepts_legacy_regular_type(self) -> None:
        original = _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)])
        payload = _mutate_first_tar_header(original, typeflag=tarfile.AREGTYPE)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out"
            extract_regular_tar_payload(payload, destination)
            self.assertEqual((destination / "safe/file.txt").read_bytes(), b"safe\n")

    def test_generic_tar_extractor_accepts_git_checksum_encoding(self) -> None:
        payload = bytearray(
            _tar_bytes(
                [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
            )
        )
        header = payload[:512]
        _git_tar_checksum(header)
        payload[:512] = header
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out"
            extract_regular_tar_payload(bytes(payload), destination)
            self.assertEqual(
                (destination / "safe/file.txt").read_bytes(),
                b"safe\n",
            )

    def test_tar_framing_rejects_every_unaligned_zero_suffix(self) -> None:
        original = _tar_bytes(
            [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
        )
        self.assertEqual(len(original) % 512, 0)
        for suffix_size in range(1, 512):
            with self.subTest(suffix_size=suffix_size):
                with self.assertRaises(ReleaseArchiveError) as raised:
                    release_archives.validate_tar_framing(
                        original + bytes(suffix_size)
                    )
                self.assertEqual(raised.exception.code, "invalid_archive")

    def test_tar_extractors_reject_unaligned_zero_suffix_before_destination(self) -> None:
        original = _tar_bytes(
            [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
        )
        for suffix_size in (1, 511):
            payload = original + bytes(suffix_size)
            for api in ("path", "payload"):
                with self.subTest(
                    suffix_size=suffix_size,
                    api=api,
                ), TemporaryDirectory() as directory:
                    root = Path(directory)
                    artifact = root / "artifact.tar"
                    artifact.write_bytes(payload)
                    destination = root / "out"
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        if api == "path":
                            extract_regular_tar(artifact, destination)
                        else:
                            extract_regular_tar_payload(payload, destination)
                    self.assertEqual(raised.exception.code, "invalid_archive")
                    self.assertFalse(destination.exists())

    def test_tar_framing_accepts_standard_library_and_real_git_archives(self) -> None:
        standard = _tar_bytes(
            [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
        )
        release_archives.validate_tar_framing(standard)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            (repository / "safe.txt").write_bytes(b"safe\n")
            for command in (
                ["git", "init", "-q"],
                ["git", "add", "safe.txt"],
                [
                    "git",
                    "-c",
                    "user.name=Synthetic Test",
                    "-c",
                    "user.email=synthetic@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "test: synthetic fixture",
                ],
            ):
                subprocess.run(
                    command,
                    cwd=repository,
                    check=True,
                    capture_output=True,
                )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            archived = subprocess.run(
                ["git", "archive", "--format=tar", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
            ).stdout
            self.assertEqual(len(archived) % 512, 0)
            destination = root / "git-out"
            extract_regular_tar_payload(archived, destination, commit)
            self.assertEqual((destination / "safe.txt").read_bytes(), b"safe\n")

    def test_tar_extractors_reject_nonzero_padding_and_regular_linkname(self) -> None:
        original = _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)])
        mutations = {
            "padding": _mutate_first_tar_header(
                original,
                padding_marker=b"SYNTHETIC-PADDING-MARKER",
            ),
            "linkname": _mutate_first_tar_header(
                original,
                linkname=b"SYNTHETIC-LINKNAME-MARKER",
            ),
            "reserved-tail": _mutate_first_tar_header(
                original,
                reserved_tail=b"SYNTHETIC",
            ),
        }
        for mutation, payload in mutations.items():
            for api in ("path", "payload"):
                with self.subTest(mutation=mutation, api=api), TemporaryDirectory() as directory:
                    root = Path(directory)
                    artifact = root / "artifact.tar"
                    artifact.write_bytes(payload)
                    destination = root / "out"
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        if api == "path":
                            extract_regular_tar(artifact, destination)
                        else:
                            extract_regular_tar_payload(payload, destination)
                    self.assertEqual(raised.exception.code, "invalid_archive")
                    self.assertFalse(destination.exists())

    def test_tar_extractors_reject_consumed_gnu_longname_header(self) -> None:
        original = _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)])
        payload = _prepend_gnu_longname_header(original, "safe/file.txt")
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            self.assertEqual([info.name for info in archive.getmembers()], ["safe/file.txt"])
        for api in ("path", "payload"):
            with self.subTest(api=api), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "artifact.tar"
                artifact.write_bytes(payload)
                destination = root / "out"
                with self.assertRaises(ReleaseArchiveError) as raised:
                    if api == "path":
                        extract_regular_tar(artifact, destination)
                    else:
                        extract_regular_tar_payload(payload, destination)
                self.assertEqual(raised.exception.code, "unsupported_member")
                self.assertFalse(destination.exists())

    def test_tar_extractors_reject_all_consumed_metadata_and_hidden_header_bytes(self) -> None:
        regular = _tar_bytes(
            [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
        )
        directory_first = _tar_bytes(
            [
                ("safe/", b"", 0o755, tarfile.DIRTYPE),
                ("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE),
            ]
        )
        mutations = {
            f"pax-{typeflag.decode('ascii')}": _prepend_tar_metadata_header(
                regular,
                typeflag,
            )
            for typeflag in (
                tarfile.XGLTYPE,
                tarfile.XHDTYPE,
                tarfile.SOLARIS_XHDTYPE,
            )
        }
        mutations["name-nul-tail"] = _mutate_first_tar_header(
            regular,
            name_tail=b"SYNTHETIC-HIDDEN",
        )
        mutations["directory-size-skip"] = _hide_metadata_behind_directory_size(
            directory_first
        )

        for mutation, payload in mutations.items():
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                self.assertTrue(archive.getmembers())
            for api in ("path", "payload"):
                with self.subTest(mutation=mutation, api=api), TemporaryDirectory() as directory:
                    root = Path(directory)
                    artifact = root / "artifact.tar"
                    artifact.write_bytes(payload)
                    destination = root / "out"
                    with self.assertRaises(ReleaseArchiveError):
                        if api == "path":
                            extract_regular_tar(artifact, destination)
                        else:
                            extract_regular_tar_payload(payload, destination)
                    self.assertFalse(destination.exists())

    def test_negative_tar_size_is_rejected_without_hanging(self) -> None:
        payload = _mutate_first_tar_header(
            _tar_bytes(
                [("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
            ),
            size_field=b"-0000001001\0",
        )
        program = (
            "import sys\n"
            "from scripts.release_archives import ReleaseArchiveError, validate_tar_framing\n"
            "try:\n"
            "    validate_tar_framing(sys.stdin.buffer.read())\n"
            "except ReleaseArchiveError:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            input=payload,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())

    def test_tar_rejects_leading_zero_block_before_valid_members(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "leading-zero.tar"
            artifact.write_bytes(bytes(512) + _tar_bytes([("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE)]))
            with self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(artifact, root / "out")

    def test_member_tree_accepts_directory_after_child_and_rejects_file_relations(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.tar"
            valid.write_bytes(_tar_bytes([
                ("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE),
                ("safe", b"", 0o755, tarfile.DIRTYPE),
            ]))
            extract_regular_tar(valid, root / "valid-out")
            self.assertEqual((root / "valid-out/safe/file.txt").read_bytes(), b"safe\n")

            for label, entries in (
                ("file-ancestor", [("safe", b"x", 0o644, tarfile.REGTYPE), ("safe/file", b"x", 0o644, tarfile.REGTYPE)]),
                ("file-descendant", [("safe/file", b"x", 0o644, tarfile.REGTYPE), ("safe", b"x", 0o644, tarfile.REGTYPE)]),
                ("directory-duplicate", [("safe/", b"", 0o755, tarfile.DIRTYPE), ("safe", b"", 0o755, tarfile.DIRTYPE)]),
                ("file-trailing-slash", [("safe/file/", b"x", 0o644, tarfile.REGTYPE)]),
                ("file-before-descendant-dir", [("a", b"x", 0o644, tarfile.REGTYPE), ("a/b", b"", 0o755, tarfile.DIRTYPE)]),
                ("descendant-dir-before-file", [("a/b", b"", 0o755, tarfile.DIRTYPE), ("a", b"x", 0o644, tarfile.REGTYPE)]),
            ):
                with self.subTest(case=label):
                    artifact = root / f"{label}.tar"
                    artifact.write_bytes(_tar_bytes(entries))
                    with self.assertRaises(ReleaseArchiveError):
                        extract_regular_tar(artifact, root / f"{label}-out")

    def test_zip_rejects_local_header_and_raw_layout_mutations(self) -> None:
        valid = _zip_bytes([("safe/file.txt", b"safe\n", stat.S_IFREG | 0o644)])
        for mutation in ("timestamp", "crc", "compression", "extra", "interstitial", "nul-name"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "mutated.zip"
                artifact.write_bytes(_mutate_local_zip(valid, mutation))
                with self.assertRaises(ReleaseArchiveError):
                    extract_regular_zip(artifact, root / "out")

    def test_zip_framing_rejects_noncanonical_fixed_header_fields(self) -> None:
        original = _zip_bytes(
            [("safe/file.txt", b"safe\n", stat.S_IFREG | 0o644)]
        )
        for mutation in (
            "local-needed",
            "central-needed",
            "consistent-needed",
            "made-version",
            "made-system",
            "disk-start",
            "internal-attrs",
        ):
            payload = _mutate_zip_fixed_header(original, mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ReleaseArchiveError) as raised:
                    release_archives.validate_zip_framing(payload)
                self.assertEqual(raised.exception.code, "invalid_archive")

    def test_zip_member_limit_rejects_declared_oversize_before_decode_or_crc(self) -> None:
        cap = 32
        for method in (zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=method) as archive:
                archive.writestr("safe.txt", b"safe\n")
            payload = _mutate_first_zip_declared_size(output.getvalue(), cap + 1)
            with self.subTest(method=method), patch.object(
                release_archives.zlib,
                "decompressobj",
                side_effect=AssertionError("decoder must not be called"),
            ) as decoder, patch.object(
                release_archives.binascii,
                "crc32",
                side_effect=AssertionError("CRC must not be called"),
            ) as crc:
                try:
                    release_archives.validate_zip_framing(
                        payload,
                        max_member_size=cap,
                    )
                except TypeError:
                    self.fail("ZIP framing validator has no member-size contract")
                except ReleaseArchiveError as error:
                    self.assertEqual(error.code, "invalid_archive")
                else:
                    self.fail("declared oversize ZIP member was accepted")
                decoder.assert_not_called()
                crc.assert_not_called()

    def test_zip_member_limit_bounds_a_deflate_stream_that_lies_about_size(self) -> None:
        cap = 32
        original = _zip_bytes(
            [("safe.txt", b"x" * (cap + 1), stat.S_IFREG | 0o644)]
        )
        payload = _mutate_first_zip_declared_size(original, cap)
        real_decompressobj = zlib.decompressobj
        calls: list[int] = []
        flush_calls: list[bool] = []

        class TrackingDecoder:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self._decoder = real_decompressobj(*args, **kwargs)

            def decompress(self, value: bytes, max_length: int = 0) -> bytes:
                calls.append(max_length)
                if max_length == 0:
                    raise ReleaseArchiveError(
                        "invalid_archive",
                        "synthetic unbounded decoder call",
                    )
                return self._decoder.decompress(value, max_length)

            def flush(self) -> bytes:
                flush_calls.append(True)
                raise AssertionError("unbounded DEFLATE flush must not be called")

            def __getattr__(self, name: str) -> object:
                return getattr(self._decoder, name)

        with patch.object(
            release_archives.zlib,
            "decompressobj",
            side_effect=TrackingDecoder,
        ):
            try:
                release_archives.validate_zip_framing(
                    payload,
                    max_member_size=cap,
                )
            except TypeError:
                self.fail("ZIP framing validator has no member-size contract")
            except ReleaseArchiveError as error:
                self.assertEqual(error.code, "invalid_archive")
            else:
                self.fail("lying ZIP size was accepted")

        self.assertEqual(calls, [cap + 1])
        self.assertEqual(flush_calls, [])

    def test_stored_zip_size_lie_is_rejected_before_member_slice_path(self) -> None:
        cap = 32
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_STORED,
        ) as archive:
            archive.writestr("safe.txt", b"x" * (cap + 1))
        payload = _mutate_first_zip_declared_size(output.getvalue(), cap)
        sentinel = ReleaseArchiveError(
            "invalid_archive",
            "synthetic member-stream call",
        )
        with patch.object(
            release_archives,
            "_validate_zip_member_stream",
            side_effect=sentinel,
        ) as member_stream, patch.object(
            release_archives.binascii,
            "crc32",
            side_effect=AssertionError("CRC must not be called"),
        ) as crc:
            with self.assertRaises(ReleaseArchiveError) as raised:
                release_archives.validate_zip_framing(
                    payload,
                    max_member_size=cap,
                )
            self.assertEqual(raised.exception.code, "invalid_archive")
            member_stream.assert_not_called()
            crc.assert_not_called()

    def test_generic_zip_extractor_preserves_approved_external_attr_behavior(self) -> None:
        payload = _mutate_zip_fixed_header(
            _zip_bytes(
                [("safe.txt", b"safe\n", stat.S_IFREG | 0o644)]
            ),
            "external-low-bits",
        )
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out"
            extract_regular_zip_payload(payload, destination)
            self.assertEqual((destination / "safe.txt").read_bytes(), b"safe\n")

    def test_zip_extractors_reject_bytes_after_member_deflate_eof(self) -> None:
        original = _zip_bytes([("safe/file.txt", b"safe\n", stat.S_IFREG | 0o644)])
        payload = _add_trailing_bytes_to_last_deflate_stream(original)
        for api in ("path", "payload"):
            with self.subTest(api=api), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "artifact.zip"
                artifact.write_bytes(payload)
                destination = root / "out"
                with self.assertRaises(ReleaseArchiveError) as raised:
                    if api == "path":
                        extract_regular_zip(artifact, destination)
                    else:
                        extract_regular_zip_payload(payload, destination)
                self.assertEqual(raised.exception.code, "invalid_archive")
                self.assertFalse(destination.exists())

    def test_zip_rejects_unsafe_duplicate_link_special_mode_and_archive_data(self) -> None:
        regular = ("safe/file.txt", b"safe\n", stat.S_IFREG | 0o644)
        cases = {
            "absolute": ([('/absolute', b'x', stat.S_IFREG | 0o644)], None, "unsafe_path"),
            "parent": ([('../escape', b'x', stat.S_IFREG | 0o644)], None, "unsafe_path"),
            "backslash": ([('safe\\file', b'x', stat.S_IFREG | 0o644)], None, "unsafe_path"),
            "empty-component": ([('safe//file', b'x', stat.S_IFREG | 0o644)], None, "unsafe_path"),
            "nul": (None, b"not a zip with nul\0", "invalid_archive"),
            "duplicate": ([regular, regular], None, "duplicate_member"),
            "symlink": ([('safe/link', b'target', stat.S_IFLNK | 0o777)], None, "unsupported_member"),
            "character": ([('safe/dev', b'', stat.S_IFCHR | 0o644)], None, "unsupported_member"),
            "block": ([('safe/dev', b'', stat.S_IFBLK | 0o644)], None, "unsupported_member"),
            "fifo": ([('safe/fifo', b'', stat.S_IFIFO | 0o644)], None, "unsupported_member"),
            "mode": ([('safe/file.txt', b'x', stat.S_IFREG | 0o600)], None, "unsupported_mode"),
            "leading-data": (None, b"prefix", "invalid_archive"),
            "trailing-data": (None, b"suffix", "invalid_archive"),
        }
        for label, (entries, raw_marker, code) in cases.items():
            with self.subTest(case=label), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "artifact.zip"
                if entries is not None:
                    payload = _zip_bytes(entries)
                elif label == "leading-data":
                    payload = raw_marker + _zip_bytes([regular])
                elif label == "trailing-data":
                    payload = _zip_bytes([regular]) + raw_marker
                else:
                    payload = raw_marker
                artifact.write_bytes(payload)
                destination = root / "out"
                with self.assertRaises(ReleaseArchiveError) as raised:
                    extract_regular_zip(artifact, destination)
                self.assertEqual(raised.exception.code, code)
                self.assertFalse(destination.exists())

    def test_extractors_write_only_regular_files_with_normalized_modes(self) -> None:
        tar_payload = _tar_bytes([
            ("safe/", b"", 0o775, tarfile.DIRTYPE),
            ("safe/plain.txt", b"plain\n", 0o664, tarfile.REGTYPE),
            ("safe/run.sh", b"#!/bin/sh\n", 0o775, tarfile.REGTYPE),
        ])
        zip_payload = _zip_bytes([
            ("safe/", b"", stat.S_IFDIR | 0o775),
            ("safe/plain.txt", b"plain\n", stat.S_IFREG | 0o664),
            ("safe/run.sh", b"#!/bin/sh\n", stat.S_IFREG | 0o775),
        ])
        for label, payload, suffix, extractor in (
            ("tar", tar_payload, ".tar", extract_regular_tar),
            ("zip", zip_payload, ".zip", extract_regular_zip),
        ):
            with self.subTest(format=label), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / f"artifact{suffix}"
                artifact.write_bytes(payload)
                destination = root / "out"
                extractor(artifact, destination)
                self.assertEqual((destination / "safe/plain.txt").read_bytes(), b"plain\n")
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((destination / "safe").stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((destination / "safe/plain.txt").stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE((destination / "safe/run.sh").stat().st_mode), 0o755)

    def _assert_extraction_failure_closes_descriptors(self, failure: str) -> None:
        payload = _tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)])
        for api in ("path", "payload"):
            for competitor in (False, True):
                with self.subTest(api=api, competitor=competitor), TemporaryDirectory() as directory:
                    root = Path(directory)
                    artifact = root / "artifact.tar"
                    artifact.write_bytes(payload)
                    destination = root / "out"
                    (root / "caller-sentinel").write_bytes(b"keep caller")
                    original_open, original_dup = os.open, os.dup
                    original_fstat, original_fchmod = os.fstat, os.fchmod
                    caller_fd = original_open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    caller_identity = original_fstat(caller_fd)
                    captured: list[int] = []
                    target_fd: int | None = None
                    failed = False
                    replacement: Path | None = None

                    def capture_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
                        nonlocal target_fd
                        descriptor = original_open(path, flags, *args, **kwargs)
                        captured.append(descriptor)
                        if (failure == "parent-fstat" and path == root) or (
                            failure == "child-fchmod" and path == "safe"
                        ):
                            target_fd = descriptor
                        return descriptor

                    def capture_dup(descriptor: int) -> int:
                        duplicate = original_dup(descriptor)
                        captured.append(duplicate)
                        return duplicate

                    def inject_failure() -> None:
                        nonlocal failed, replacement
                        failed = True
                        if competitor:
                            if failure == "parent-fstat":
                                replacement = destination
                            else:
                                stages = list(root.glob(".out.stage-*"))
                                self.assertEqual(len(stages), 1)
                                replacement = stages[0]
                                replacement.rename(root / "owned-parked")
                            replacement.mkdir()
                            (replacement / "competitor").write_bytes(b"keep competitor")
                        raise OSError(errno.EIO, "injected extraction descriptor failure")

                    def fail_fstat(descriptor: int) -> os.stat_result:
                        if failure == "parent-fstat" and descriptor == target_fd and not failed:
                            inject_failure()
                        return original_fstat(descriptor)

                    def fail_fchmod(descriptor: int, mode: int) -> None:
                        if failure == "child-fchmod" and descriptor == target_fd and not failed:
                            inject_failure()
                        original_fchmod(descriptor, mode)

                    try:
                        with (
                            patch("scripts.release_archives.os.open", side_effect=capture_open),
                            patch("scripts.release_archives.os.dup", side_effect=capture_dup),
                            patch("scripts.release_archives.os.fstat", side_effect=fail_fstat),
                            patch("scripts.release_archives.os.fchmod", side_effect=fail_fchmod),
                            self.assertRaises(ReleaseArchiveError) as raised,
                        ):
                            if api == "path":
                                extract_regular_tar(artifact, destination)
                            else:
                                extract_regular_tar_payload(payload, destination)
                        self.assertTrue(failed)
                        self.assertIsNotNone(target_fd)
                        self.assertIn(target_fd, captured)
                        self.assertEqual(raised.exception.code, "unsafe_destination")
                        caller_after = original_fstat(caller_fd)
                        self.assertEqual(
                            (caller_after.st_dev, caller_after.st_ino, caller_after.st_mode),
                            (caller_identity.st_dev, caller_identity.st_ino, caller_identity.st_mode),
                        )
                        self.assertEqual((root / "caller-sentinel").read_bytes(), b"keep caller")
                        if competitor:
                            self.assertEqual((replacement / "competitor").read_bytes(), b"keep competitor")
                            self.assertEqual(list(replacement.iterdir()), [replacement / "competitor"])
                        else:
                            self.assertFalse(destination.exists())
                            self.assertEqual(list(root.glob(".out.stage-*")), [])
                        if failure == "child-fchmod":
                            self.assertFalse(destination.exists())
                        for descriptor in set(captured):
                            with self.subTest(descriptor=descriptor):
                                with self.assertRaises(OSError) as closed:
                                    original_fstat(descriptor)
                                self.assertEqual(closed.exception.errno, errno.EBADF)
                    finally:
                        # Also release leaked descriptors when this regression test is RED.
                        for descriptor in set(captured):
                            try:
                                os.close(descriptor)
                            except OSError as error:
                                if error.errno != errno.EBADF:
                                    raise
                        os.close(caller_fd)

    def test_parent_fstat_failure_closes_extraction_descriptors(self) -> None:
        self._assert_extraction_failure_closes_descriptors("parent-fstat")

    def test_child_fchmod_failure_closes_extraction_descriptors(self) -> None:
        self._assert_extraction_failure_closes_descriptors("child-fchmod")

    def test_publication_never_replaces_competing_destination(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.tar"
            artifact.write_bytes(_tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)]))
            destination = root / "out"
            original = getattr(release_archives, "_exclusive_rename", None)

            def race(parent_fd: int, stage_name: str, destination_name: str, stage_fd: int, identity: os.stat_result) -> None:
                os.mkdir(destination_name, dir_fd=parent_fd)
                if original is None:
                    return
                original(parent_fd, stage_name, destination_name, stage_fd, identity)

            with patch.object(release_archives, "_exclusive_rename", side_effect=race, create=True):
                with self.assertRaises(ReleaseArchiveError):
                    extract_regular_tar(artifact, destination)
            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])

    def test_staging_replacement_before_first_open_is_not_owned_or_removed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.tar"
            artifact.write_bytes(_tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)]))
            original_open = os.open
            replacement: Path | None = None

            def race(path: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal replacement
                if isinstance(path, str) and path.startswith(".out.stage-") and replacement is None:
                    stage = root / path
                    stage.rename(root / "owned-parked")
                    stage.mkdir()
                    (stage / "competitor").write_text("keep")
                    replacement = stage
                return original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

            with patch("scripts.release_archives.os.open", side_effect=race), self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(artifact, root / "out")
            self.assertEqual((replacement / "competitor").read_text(), "keep")  # type: ignore[operator]

    def test_first_staging_open_failure_cleans_owned_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.tar"
            artifact.write_bytes(_tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)]))
            original = release_archives._open_directory
            failed = False

            def fail_once(parent_fd: int, name: str) -> int:
                nonlocal failed
                if name.startswith(".out.stage-") and not failed:
                    failed = True
                    raise OSError("first open failure")
                return original(parent_fd, name)

            with patch.object(release_archives, "_open_directory", side_effect=fail_once), self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(artifact, root / "out")
            self.assertTrue(failed)
            self.assertFalse((root / "out").exists())
            self.assertEqual(list(root.glob(".out.stage-*")), [])

    def test_staging_replacement_before_publication_is_not_published_or_removed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.tar"
            artifact.write_bytes(_tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)]))
            original = release_archives._exclusive_rename
            replacement: Path | None = None

            def race(parent_fd: int, stage: str, destination: str, stage_fd: int, identity: os.stat_result) -> None:
                nonlocal replacement
                (root / stage).rename(root / "owned-parked")
                (root / stage).mkdir()
                (root / stage / "competitor").write_text("keep")
                replacement = root / stage
                original(parent_fd, stage, destination, stage_fd, identity)

            with patch.object(release_archives, "_exclusive_rename", side_effect=race), self.assertRaises(ReleaseArchiveError):
                extract_regular_tar(artifact, root / "out")
            self.assertEqual((replacement / "competitor").read_text(), "keep")  # type: ignore[operator]

    def test_destination_parent_identity_is_bound_across_open(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.tar"
            artifact.write_bytes(_tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)]))
            parent = root / "parent"
            parent.mkdir()
            destination = parent / "out"
            parked = root / "parked"
            real_open = os.open
            swapped = False

            def swap_open(file: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal swapped
                if not swapped and file == parent:
                    parent.rename(parked)
                    parent.mkdir()
                    swapped = True
                return real_open(file, flags, *args, **kwargs)  # type: ignore[arg-type]

            with patch.object(release_archives.os, "open", side_effect=swap_open):
                with self.assertRaises(ReleaseArchiveError):
                    extract_regular_tar(artifact, destination)
            self.assertFalse(destination.exists())

    def test_cleanup_does_not_remove_replacement_at_staging_name(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.tar"
            artifact.write_bytes(_tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)]))
            destination = root / "out"
            parked = root / "owned-parked"
            real_open = os.open
            replacement: Path | None = None

            def fail_write(file: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal replacement
                if flags & os.O_WRONLY and kwargs.get("dir_fd") is not None:
                    stages = list(root.glob(".out.stage-*"))
                    self.assertEqual(len(stages), 1)
                    stage = stages[0]
                    stage.rename(parked)
                    stage.mkdir()
                    (stage / "competitor.txt").write_text("keep\n", encoding="utf-8")
                    replacement = stage
                    raise OSError("synthetic write failure")
                return real_open(file, flags, *args, **kwargs)  # type: ignore[arg-type]

            with patch.object(release_archives.os, "open", side_effect=fail_write):
                with self.assertRaises(ReleaseArchiveError):
                    extract_regular_tar(artifact, destination)
            self.assertIsNotNone(replacement)
            self.assertEqual((replacement / "competitor.txt").read_text(encoding="utf-8"), "keep\n")  # type: ignore[operator]


class WheelContractTests(unittest.TestCase):
    def test_wheel_path_and_payload_require_exact_external_attributes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                ["src/threadroot", "README.md", "LICENSE"],
            )
            order, payloads = _wheel_payloads(source)
            valid = root / "valid.whl"
            _write_wheel(valid, order, payloads)
            payload = _mutate_zip_fixed_header(
                valid.read_bytes(),
                "external-low-bits",
            )
            artifact = root / "external-attrs.whl"
            artifact.write_bytes(payload)

            for api in ("path", "payload"):
                with self.subTest(api=api):
                    try:
                        if api == "path":
                            validate_wheel(
                                artifact,
                                source,
                                "0.1.0",
                                WHEEL_EPOCH,
                            )
                        else:
                            validate_wheel_payload(
                                payload,
                                snapshot,
                                "0.1.0",
                                WHEEL_EPOCH,
                            )
                    except ReleaseArchiveError as error:
                        self.assertEqual(error.code, "metadata_mismatch")
                    else:
                        self.fail("wheel accepted noncanonical external attributes")

    def test_wheel_path_and_payload_validators_reject_fixed_header_covert_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                ["src/threadroot", "README.md", "LICENSE"],
            )
            order, payloads = _wheel_payloads(source)
            valid = root / "valid.whl"
            _write_wheel(valid, order, payloads)
            for mutation in (
                "local-needed",
                "central-needed",
                "consistent-needed",
                "made-version",
                "made-system",
                "disk-start",
                "internal-attrs",
            ):
                payload = _mutate_zip_fixed_header(valid.read_bytes(), mutation)
                artifact = root / f"{mutation}.whl"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(mutation=mutation, api=api):
                        with self.assertRaises(ReleaseArchiveError) as raised:
                            if api == "path":
                                validate_wheel(
                                    artifact,
                                    source,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                            else:
                                validate_wheel_payload(
                                    payload,
                                    snapshot,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                        self.assertEqual(raised.exception.code, "invalid_archive")

    def test_source_root_identity_mismatch_closes_descriptor(self) -> None:
        with TemporaryDirectory() as directory:
            source = _make_wheel_source(Path(directory))
            original_open = os.open
            captured: list[int] = []

            def tracking_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
                descriptor = original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
                if Path(path) == source:  # type: ignore[arg-type]
                    captured.append(descriptor)
                return descriptor

            with patch("scripts.release_archives.os.open", side_effect=tracking_open), patch(
                "scripts.release_archives._same_identity", return_value=False
            ), self.assertRaises(ReleaseArchiveError):
                release_archives._source_snapshot(source, ["README.md"])
            self.assertEqual(len(captured), 1)
            with self.assertRaises(OSError):
                os.fstat(captured[0])

    def test_wheel_rejects_nonempty_wheel_metadata_body(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            order, payloads = _wheel_payloads(source)
            valid = root / "valid.whl"
            _write_wheel(valid, order, payloads)
            validate_wheel(valid, source, "0.1.0", WHEEL_EPOCH)
            wheel_name = "threadroot-0.1.0.dist-info/WHEEL"
            payloads[wheel_name] += b"unexpected body\n"
            artifact = root / "body.whl"
            _write_wheel(artifact, order, payloads)
            with self.assertRaises(ReleaseArchiveError):
                validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)

    def test_wheel_rejects_multipart_header_payload_as_structured_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            order, payloads = _wheel_payloads(source)
            wheel = "threadroot-0.1.0.dist-info/WHEEL"
            payloads[wheel] = payloads[wheel].rstrip(b"\n") + (
                b"\nContent-Type: multipart/mixed; boundary=x\nMIME-Version: 1.0\n\n"
                b"--x\nContent-Type: text/plain\n\nbody\n--x--\n"
            )
            artifact = root / "multipart.whl"
            _write_wheel(artifact, order, payloads)
            with self.assertRaises(ReleaseArchiveError) as raised:
                validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)
            self.assertEqual(raised.exception.code, "metadata_mismatch")

    def test_wheel_rejects_malformed_record_fields_without_regeneration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            order, original = _wheel_payloads(source)
            record = "threadroot-0.1.0.dist-info/RECORD"
            valid = root / "valid.whl"
            _write_wheel(valid, order, original, regenerate_record=False)
            validate_wheel(valid, source, "0.1.0", WHEEL_EPOCH)
            rows = original[record].decode().splitlines()
            mutations = {
                "digest": rows[0].replace("sha256=", "sha256=x", 1),
                "size": rows[0].rsplit(",", 1)[0] + ",999",
                "self-digest": f"{record},sha256=eA,",
                "self-size": f"{record},,1",
            }
            for label, changed in mutations.items():
                with self.subTest(label=label):
                    payloads = dict(original)
                    changed_rows = list(rows)
                    changed_rows[0 if not label.startswith("self-") else -1] = changed
                    if label.startswith("self-"):
                        self.assertEqual(len(changed.split(",")), 3)
                    payloads[record] = ("\n".join(changed_rows) + "\n").encode()
                    self.assertNotEqual(payloads[record], original[record])
                    artifact = root / f"record-{label}.whl"
                    _write_wheel(artifact, order, payloads, regenerate_record=False)
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)
                    self.assertEqual(raised.exception.code, "record_mismatch")
                    if label.startswith("self-"):
                        self.assertIn("self-row", str(raised.exception))
    def test_wheel_rejects_source_swap_at_descriptor_open(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            order, payloads = _wheel_payloads(source)
            artifact = root / "valid.whl"
            _write_wheel(artifact, order, payloads)
            victim = source / "src/threadroot/__init__.py"
            outside = root / "outside.py"
            outside.write_bytes(victim.read_bytes())
            original_open = os.open
            changed = False

            def racing_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal changed
                if path == "__init__.py" and kwargs.get("dir_fd") is not None and not changed:
                    changed = True
                    victim.unlink()
                    victim.symlink_to(outside)
                return original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

            with patch("scripts.release_archives.os.open", side_effect=racing_open), self.assertRaises(ReleaseArchiveError):
                validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)
            self.assertTrue(changed)

    def test_wheel_accepts_header_only_wheel_metadata_with_single_newline(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            order, payloads = _wheel_payloads(source)
            wheel_name = "threadroot-0.1.0.dist-info/WHEEL"
            payloads[wheel_name] = payloads[wheel_name].rstrip(b"\n") + b"\n"
            artifact = root / "header-only.whl"
            _write_wheel(artifact, order, payloads)
            validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)

    def test_wheel_path_and_payload_validators_reject_bytes_after_deflate_eof(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                ["src/threadroot", "README.md", "LICENSE"],
            )
            order, payloads = _wheel_payloads(source)
            artifact = root / "framing.whl"
            _write_wheel(artifact, order, payloads)
            payload = _add_trailing_bytes_to_last_deflate_stream(artifact.read_bytes())
            artifact.write_bytes(payload)
            for api in ("path", "payload"):
                with self.subTest(api=api):
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        if api == "path":
                            validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)
                        else:
                            validate_wheel_payload(payload, snapshot, "0.1.0", WHEEL_EPOCH)
                    self.assertEqual(raised.exception.code, "invalid_archive")

    def test_wheel_requires_exact_source_metadata_entry_point_license_and_record(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_wheel_source(root)
            original_order, original_payloads = _wheel_payloads(source)
            valid = root / "valid.whl"
            _write_wheel(valid, original_order, original_payloads)
            validate_wheel(valid, source, "0.1.0", WHEEL_EPOCH)

            prefix = "threadroot-0.1.0.dist-info/"
            mutations: dict[str, tuple[list[str], dict[str, bytes]]] = {}
            for required in (
                prefix + "METADATA",
                prefix + "WHEEL",
                prefix + "entry_points.txt",
                prefix + "licenses/LICENSE",
                prefix + "RECORD",
            ):
                mutations[f"missing-{Path(required).name}"] = (
                    [name for name in original_order if name != required],
                    dict(original_payloads),
                )
            extra_payloads = dict(original_payloads)
            extra_payloads["other/__init__.py"] = b"unexpected\n"
            mutations["undeclared-package"] = (
                [*original_order[:-5], "other/__init__.py", *original_order[-5:]],
                extra_payloads,
            )
            changed_source = dict(original_payloads)
            changed_source["threadroot/cli.py"] = b"changed\n"
            mutations["changed-source"] = (list(original_order), changed_source)
            requires_dist = dict(original_payloads)
            requires_dist[prefix + "METADATA"] = requires_dist[prefix + "METADATA"].replace(
                b"\n\n", b"\nRequires-Dist: bad\n\n", 1
            )
            mutations["requires-dist"] = (list(original_order), requires_dist)
            project_url = dict(original_payloads)
            project_url[prefix + "METADATA"] = project_url[prefix + "METADATA"].replace(
                b"https://github.com/Will413028/threadroot/issues", b"https://example.invalid"
            )
            mutations["project-url"] = (list(original_order), project_url)
            entry_point = dict(original_payloads)
            entry_point[prefix + "entry_points.txt"] = b"[console_scripts]\nthreadroot = wrong:main\n"
            mutations["entry-point"] = (list(original_order), entry_point)

            for label, (order, payloads) in mutations.items():
                with self.subTest(mutation=label):
                    artifact = root / f"{label}.whl"
                    _write_wheel(artifact, order, payloads)
                    with self.assertRaises(ReleaseArchiveError):
                        validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)


class SdistContractTests(unittest.TestCase):
    def test_sdist_path_and_payload_validators_reject_unaligned_zero_suffix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [*release_archives.SDIST_ROOTS, ".gitignore", "pyproject.toml"],
            )
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source))
            raw_tar = gzip.decompress(valid.read_bytes())
            self.assertEqual(len(raw_tar) % 512, 0)
            validate_sdist(valid, source, "0.1.0", WHEEL_EPOCH)
            for suffix_size in (1, 511):
                payload = _gzip_tar_payload(raw_tar + bytes(suffix_size))
                artifact = root / f"suffix-{suffix_size}.tar.gz"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(suffix_size=suffix_size, api=api):
                        with self.assertRaises(ReleaseArchiveError) as raised:
                            if api == "path":
                                validate_sdist(
                                    artifact,
                                    source,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                            else:
                                validate_sdist_payload(
                                    payload,
                                    snapshot,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                        self.assertEqual(raised.exception.code, "invalid_archive")

    def test_sdist_path_and_payload_validators_require_canonical_regular_type(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [*release_archives.SDIST_ROOTS, ".gitignore", "pyproject.toml"],
            )
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source))
            raw_tar = gzip.decompress(valid.read_bytes())
            for typeflag in (
                tarfile.GNUTYPE_SPARSE,
                tarfile.CONTTYPE,
                tarfile.AREGTYPE,
            ):
                payload = _gzip_tar_payload(
                    _mutate_first_tar_header(raw_tar, typeflag=typeflag)
                )
                artifact = root / f"type-{typeflag.hex()}.tar.gz"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(typeflag=typeflag, api=api):
                        with self.assertRaises(ReleaseArchiveError) as raised:
                            if api == "path":
                                validate_sdist(artifact, source, "0.1.0", WHEEL_EPOCH)
                            else:
                                validate_sdist_payload(
                                    payload,
                                    snapshot,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                        self.assertEqual(raised.exception.code, "unsupported_member")

    def test_sdist_path_and_payload_validators_reject_unowned_tar_header_and_padding_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [*release_archives.SDIST_ROOTS, ".gitignore", "pyproject.toml"],
            )
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source))
            raw_tar = gzip.decompress(valid.read_bytes())
            mutations = {
                "padding": _mutate_first_tar_header(
                    raw_tar,
                    padding_marker=b"SYNTHETIC-PADDING-MARKER",
                ),
                "linkname": _mutate_first_tar_header(
                    raw_tar,
                    linkname=b"SYNTHETIC-LINKNAME-MARKER",
                ),
                "reserved-tail": _mutate_first_tar_header(
                    raw_tar,
                    reserved_tail=b"SYNTHETIC",
                ),
            }
            for mutation, changed_tar in mutations.items():
                payload = _gzip_tar_payload(changed_tar)
                artifact = root / f"{mutation}.tar.gz"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(mutation=mutation, api=api):
                        with self.assertRaises(ReleaseArchiveError) as raised:
                            if api == "path":
                                validate_sdist(artifact, source, "0.1.0", WHEEL_EPOCH)
                            else:
                                validate_sdist_payload(
                                    payload,
                                    snapshot,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                        self.assertEqual(raised.exception.code, "invalid_archive")

    def test_sdist_path_and_payload_validators_reject_consumed_gnu_longname_header(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [*release_archives.SDIST_ROOTS, ".gitignore", "pyproject.toml"],
            )
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source))
            raw_tar = gzip.decompress(valid.read_bytes())
            with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
                first_name = archive.getmembers()[0].name
            changed_tar = _prepend_gnu_longname_header(raw_tar, first_name)
            with tarfile.open(fileobj=io.BytesIO(changed_tar), mode="r:") as archive:
                self.assertEqual(archive.getmembers()[0].name, first_name)
            payload = _gzip_tar_payload(changed_tar)
            artifact = root / "gnu-longname.tar.gz"
            artifact.write_bytes(payload)
            for api in ("path", "payload"):
                with self.subTest(api=api):
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        if api == "path":
                            validate_sdist(artifact, source, "0.1.0", WHEEL_EPOCH)
                        else:
                            validate_sdist_payload(
                                payload,
                                snapshot,
                                "0.1.0",
                                WHEEL_EPOCH,
                            )
                    self.assertEqual(raised.exception.code, "unsupported_member")

    def test_sdist_validators_reject_consumed_metadata_and_hidden_header_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [*release_archives.SDIST_ROOTS, ".gitignore", "pyproject.toml"],
            )
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source))
            raw_tar = gzip.decompress(valid.read_bytes())
            mutations = {
                f"pax-{typeflag.decode('ascii')}": _prepend_tar_metadata_header(
                    raw_tar,
                    typeflag,
                )
                for typeflag in (
                    tarfile.XGLTYPE,
                    tarfile.XHDTYPE,
                    tarfile.SOLARIS_XHDTYPE,
                )
            }
            mutations["name-nul-tail"] = _mutate_first_tar_header(
                raw_tar,
                name_tail=b"SYNTHETIC-HIDDEN",
            )

            for mutation, changed_tar in mutations.items():
                payload = _gzip_tar_payload(changed_tar)
                artifact = root / f"{mutation}.tar.gz"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(mutation=mutation, api=api):
                        with self.assertRaises(ReleaseArchiveError):
                            if api == "path":
                                validate_sdist(
                                    artifact,
                                    source,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )
                            else:
                                validate_sdist_payload(
                                    payload,
                                    snapshot,
                                    "0.1.0",
                                    WHEEL_EPOCH,
                                )

    def test_sdist_requires_exact_allowlisted_source_and_generated_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            originals = _sdist_entries(source)
            valid = root / "valid.tar.gz"
            _write_sdist(valid, originals)
            validate_sdist(valid, source, "0.1.0", WHEEL_EPOCH)

            def changed(index: int, **updates: object) -> list[dict[str, object]]:
                result = [dict(entry) for entry in originals]
                result[index].update(updates)
                return result

            extra = [*map(dict, originals), {"name": "threadroot-0.1.0/extra.txt", "payload": b"x",
                     "kind": tarfile.REGTYPE, "mode": 0o644, "mtime": WHEEL_EPOCH, "uid": 0, "gid": 0}]
            forbidden = {}
            for name in ("MANIFEST.in", "setup.cfg", "src/threadroot.egg-info/PKG-INFO"):
                item = dict(extra[-1])
                item["name"] = "threadroot-0.1.0/" + name
                forbidden[name] = [*map(dict, originals), item]
            cases: dict[str, tuple[list[dict[str, object]], dict[str, object]]] = {
                "extra": (extra, {}),
                "missing": ([*map(dict, originals[1:])], {}),
                "changed-source": (changed(1, payload=b"changed\n"), {}),
                "second-top-level": (changed(0, name="other-0.1.0/.gitignore"), {}),
                "directory": (changed(0, kind=tarfile.DIRTYPE, payload=b""), {}),
                "link": (changed(0, kind=tarfile.SYMTYPE, payload=b""), {}),
                "special": (changed(0, kind=tarfile.FIFOTYPE, payload=b""), {}),
                "wrong-tar-time": (changed(0, mtime=WHEEL_EPOCH + 1), {}),
                "wrong-owner": (changed(0, uid=1), {}),
                "wrong-mode": (changed(0, mode=0o600), {}),
                "wrong-gzip-time": ([*map(dict, originals)], {"gzip_mtime": WHEEL_EPOCH + 1}),
                "tar-trailing-data": ([*map(dict, originals)], {"tar_suffix": b"trailing"}),
                "gzip-trailing-data": ([*map(dict, originals)], {"gzip_suffix": b"trailing"}),
                **{f"forbidden-{name}": (entries, {}) for name, entries in forbidden.items()},
            }
            for label, (entries, options) in cases.items():
                with self.subTest(mutation=label):
                    artifact = root / f"{label.replace('/', '_')}.tar.gz"
                    _write_sdist(artifact, entries, **options)  # type: ignore[arg-type]
                    with self.assertRaises(ReleaseArchiveError):
                        validate_sdist(artifact, source, "0.1.0", WHEEL_EPOCH)


class HostZipContractTests(unittest.TestCase):
    def test_both_host_zip_apis_require_exact_external_attributes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_host_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [
                    *(item.as_posix() for item in release_archives.COMMON_ROOTS),
                    release_archives.MARKETPLACE.as_posix(),
                    *(item.as_posix() for item in release_archives.HOST_MANIFESTS.values()),
                ],
            )
            output = root / "artifacts"
            with patch.object(build_release, "REPOSITORY_ROOT", source):
                valid = {
                    host: build_archive(host, output)
                    for host in ("claude", "codex")
                }

            for host, original in valid.items():
                payload = _mutate_zip_fixed_header(
                    original.read_bytes(),
                    "external-low-bits",
                )
                artifact = root / f"{host}-external-attrs.zip"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(host=host, api=api):
                        try:
                            if api == "path":
                                validate_host_zip(artifact, source, host)
                            else:
                                validate_host_zip_payload(payload, snapshot, host)
                        except ReleaseArchiveError as error:
                            self.assertEqual(error.code, "metadata_mismatch")
                        else:
                            self.fail(
                                "host ZIP accepted noncanonical external attributes"
                            )

    def test_host_zip_path_and_payload_validators_reject_fixed_header_covert_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_host_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [
                    *(item.as_posix() for item in release_archives.COMMON_ROOTS),
                    release_archives.MARKETPLACE.as_posix(),
                    *(item.as_posix() for item in release_archives.HOST_MANIFESTS.values()),
                ],
            )
            output = root / "artifacts"
            with patch.object(build_release, "REPOSITORY_ROOT", source):
                valid = build_archive("claude", output)
            for mutation in (
                "local-needed",
                "central-needed",
                "consistent-needed",
                "made-version",
                "made-system",
                "disk-start",
                "internal-attrs",
            ):
                payload = _mutate_zip_fixed_header(valid.read_bytes(), mutation)
                artifact = root / f"{mutation}.zip"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(mutation=mutation, api=api):
                        with self.assertRaises(ReleaseArchiveError) as raised:
                            if api == "path":
                                validate_host_zip(artifact, source, "claude")
                            else:
                                validate_host_zip_payload(payload, snapshot, "claude")
                        self.assertEqual(raised.exception.code, "invalid_archive")

    def test_host_zip_path_and_payload_validators_reject_bytes_after_deflate_eof(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_host_source(root)
            snapshot = release_archives._capture_path_source(
                source,
                [
                    item.as_posix()
                    for item in (
                        *build_release.COMMON_ROOTS,
                        build_release.MARKETPLACE,
                        *build_release.HOST_MANIFESTS.values(),
                    )
                ],
            )
            output = root / "artifacts"
            with patch.object(build_release, "REPOSITORY_ROOT", source):
                valid = {
                    host: build_archive(host, output)
                    for host in ("claude", "codex")
                }
            for host, original in valid.items():
                payload = _add_trailing_bytes_to_last_deflate_stream(
                    original.read_bytes()
                )
                artifact = root / f"{host}-framing.zip"
                artifact.write_bytes(payload)
                for api in ("path", "payload"):
                    with self.subTest(host=host, api=api):
                        with self.assertRaises(ReleaseArchiveError) as raised:
                            if api == "path":
                                validate_host_zip(artifact, source, host)
                            else:
                                validate_host_zip_payload(payload, snapshot, host)
                        self.assertEqual(raised.exception.code, "invalid_archive")

    def test_host_zip_requires_native_manifest_canonical_metadata_order_and_source_parity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_host_source(root)
            output = root / "artifacts"
            with patch.object(build_release, "REPOSITORY_ROOT", source):
                valid = {host: build_archive(host, output) for host in ("claude", "codex")}

            for host in ("claude", "codex"):
                with self.subTest(host=host, mutation="valid"):
                    validate_host_zip(valid[host], source, host)
                other = "codex" if host == "claude" else "claude"
                with self.subTest(host=host, mutation="native-manifest"), self.assertRaises(ReleaseArchiveError):
                    validate_host_zip(valid[other], source, host)
                for mutation in (
                    "timestamp", "utf8", "create-system", "mode", "extra", "comment", "ordering", "source-byte"
                ):
                    with self.subTest(host=host, mutation=mutation):
                        artifact = root / f"{host}-{mutation}.zip"
                        _rewrite_host_zip(valid[host], artifact, mutation=mutation)
                        with self.assertRaises(ReleaseArchiveError):
                            validate_host_zip(artifact, source, host)


def _make_release_source(root: Path) -> Path:
    source = _make_sdist_source(root)
    for name in (".claude-plugin", ".codex-plugin"):
        (source / name).unlink()
        (source / name).mkdir()
    for name in (
        ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
        ".codex-plugin/plugin.json", "docs/testing.md", "requirements/release.txt",
        "tools/release/Dockerfile", "scripts/check_public.py", "scripts/build_release.py",
    ):
        (source / name).write_bytes(f"synthetic {name}\n".encode())
    (source / "src/threadroot/cli.py").write_bytes(b"def main():\n    return 0\n")
    return source


def _capture_fixture(source: Path) -> ReleaseSourceSnapshot:
    descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return capture_release_source(descriptor)
    finally:
        os.close(descriptor)


class ReleaseSourceSnapshotTests(unittest.TestCase):
    def test_capture_is_exact_sorted_immutable_union_with_normalized_modes(self) -> None:
        with TemporaryDirectory() as directory:
            source = _make_release_source(Path(directory))
            (source / "outside-union.txt").write_bytes(b"not selected")
            (source / "outside-link").symlink_to("outside-union.txt")
            (source / "scripts/check_public.py").chmod(0o775)
            (source / "README.md").chmod(0o664)
            snapshot = _capture_fixture(source)
            expected = {
                ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                ".codex-plugin/plugin.json", ".dockerignore", ".gitignore", "AGENTS.md",
                "CONTRIBUTING.md", "LICENSE", "README.md", "SECURITY.md", "pyproject.toml",
                "docs/fixture.txt", "docs/testing.md", "requirements/fixture.txt",
                "requirements/release.txt", "scripts/fixture.txt", "scripts/check_public.py",
                "scripts/build_release.py", "skills/fixture.txt", "templates/fixture.txt",
                "tests/fixture.txt", "tools/release/fixture.txt", "tools/release/Dockerfile",
                "src/threadroot/__init__.py", "src/threadroot/cli.py",
            }
            self.assertIsInstance(snapshot.entries, tuple)
            self.assertEqual([entry.path for entry in snapshot.entries], sorted(expected))
            for entry in snapshot.entries:
                self.assertIsInstance(entry, ReleaseSourceEntry)
                self.assertIsInstance(entry.payload, bytes)
                self.assertEqual(entry.payload, (source / entry.path).read_bytes())
                self.assertEqual(entry.mode, 0o755 if entry.path == "scripts/check_public.py" else 0o644)
            with self.assertRaises(FrozenInstanceError):
                snapshot.entries = ()
            with self.assertRaises(FrozenInstanceError):
                snapshot.entries[0].payload = b"changed"
            (source / "README.md").write_bytes(b"changed after capture")
            self.assertEqual(next(entry.payload for entry in snapshot.entries if entry.path == "README.md"),
                             b"# Synthetic Threadroot\n")

    def test_capture_uses_held_root_after_pathname_replacement(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                source.rename(root / "parked")
                source.mkdir()
                snapshot = capture_release_source(descriptor)
                self.assertIn("README.md", [entry.path for entry in snapshot.entries])
                self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
                self.assertEqual(list(source.iterdir()), [])
            finally:
                os.close(descriptor)

    def test_capture_rejects_intermediate_symlink_and_keeps_root_fd_open(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            outside = root / "outside"
            outside.mkdir()
            (outside / "release.txt").write_bytes(b"outside")
            (source / "requirements").rename(source / "requirements.real")
            (source / "requirements").symlink_to(outside, target_is_directory=True)
            descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with self.assertRaisesRegex(ReleaseArchiveError, "source tree") as raised:
                    capture_release_source(descriptor)
                self.assertEqual(raised.exception.code, "source_mismatch")
                os.fstat(descriptor)
            finally:
                os.close(descriptor)

    def test_capture_rejects_leaf_links_special_files_and_non_directory_fd(self) -> None:
        for mutation in ("symlink", "fifo", "regular-root"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                source = _make_release_source(Path(directory))
                if mutation == "regular-root":
                    descriptor = os.open(source / "README.md", os.O_RDONLY | os.O_NOFOLLOW)
                else:
                    leaf = source / "scripts/check_public.py"
                    leaf.unlink()
                    if mutation == "symlink":
                        leaf.symlink_to(source / "README.md")
                    else:
                        os.mkfifo(leaf)
                    descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        capture_release_source(descriptor)
                    self.assertEqual(raised.exception.code, "source_mismatch")
                    os.fstat(descriptor)
                finally:
                    os.close(descriptor)

    def test_capture_rejects_directory_replacement_during_read_and_closes_owned_fds(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            real_read, real_open, real_dup = os.read, os.open, os.dup
            opened: list[int] = []
            changed = False
            victim_identity = (source / "requirements/release.txt").stat()

            def track_open(*args: object, **kwargs: object) -> int:
                result = real_open(*args, **kwargs)
                opened.append(result)
                return result

            def track_dup(fd: int) -> int:
                result = real_dup(fd)
                opened.append(result)
                return result

            def race(fd: int, size: int) -> bytes:
                nonlocal changed
                payload = real_read(fd, size)
                current = os.fstat(fd)
                if payload and not changed and (current.st_dev, current.st_ino) == (victim_identity.st_dev, victim_identity.st_ino):
                    changed = True
                    (source / "requirements").rename(root / "parked-requirements")
                    (source / "requirements").mkdir()
                return payload

            try:
                with patch.object(release_archives.os, "open", side_effect=track_open), patch.object(
                    release_archives.os, "dup", side_effect=track_dup
                ), patch.object(release_archives.os, "read", side_effect=race):
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        capture_release_source(descriptor)
                self.assertTrue(changed)
                self.assertEqual(raised.exception.code, "source_mismatch")
                os.fstat(descriptor)
                for fd in set(opened):
                    with self.assertRaises(OSError):
                        os.fstat(fd)
            finally:
                os.close(descriptor)

    def test_capture_rejects_overlapping_roots_instead_of_collapsing_duplicates(self) -> None:
        with TemporaryDirectory() as directory:
            source = _make_release_source(Path(directory))
            descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with self.assertRaises(ReleaseArchiveError) as raised:
                    release_archives._capture_source_roots(descriptor, ["scripts", "scripts/check_public.py"])
                self.assertEqual(raised.exception.code, "source_mismatch")
                os.fstat(descriptor)
            finally:
                os.close(descriptor)

    def test_capture_rejects_leaf_mode_change_between_stat_and_open(self) -> None:
        with TemporaryDirectory() as directory:
            source = _make_release_source(Path(directory))
            victim = source / "scripts/check_public.py"
            original_open = os.open
            changed = False

            def race(path: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal changed
                if path == "check_public.py" and kwargs.get("dir_fd") is not None and not changed:
                    changed = True
                    victim.chmod(0o755)
                return original_open(path, flags, *args, **kwargs)

            with patch.object(release_archives.os, "open", side_effect=race):
                with self.assertRaises(ReleaseArchiveError) as raised:
                    _capture_fixture(source)
            self.assertTrue(changed)
            self.assertEqual(raised.exception.code, "source_mismatch")

    def test_capture_closes_intermediate_directory_if_fstat_fails(self) -> None:
        with TemporaryDirectory() as directory:
            source = _make_release_source(Path(directory))
            original_open, original_fstat = os.open, os.fstat
            child_fd: int | None = None
            failed = False

            def track_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal child_fd
                fd = original_open(path, flags, *args, **kwargs)
                if path == "src" and kwargs.get("dir_fd") is not None:
                    child_fd = fd
                return fd

            def fail_once(fd: int) -> os.stat_result:
                nonlocal failed
                if fd == child_fd and not failed:
                    failed = True
                    raise OSError("synthetic fstat failure")
                return original_fstat(fd)

            descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with patch.object(release_archives.os, "open", side_effect=track_open), patch.object(
                    release_archives.os, "fstat", side_effect=fail_once
                ), self.assertRaises(ReleaseArchiveError) as raised:
                    capture_release_source(descriptor)
                self.assertTrue(failed)
                self.assertEqual(raised.exception.code, "source_mismatch")
                os.fstat(descriptor)
                with self.assertRaises(OSError):
                    os.fstat(child_fd)
            finally:
                os.close(descriptor)
                if child_fd is not None:
                    try:
                        os.close(child_fd)
                    except OSError:
                        pass


class PayloadArchiveApiTests(unittest.TestCase):
    def test_validators_accept_same_valid_archives_without_reopening_captured_sources(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            snapshot = _capture_fixture(source)
            wheel = root / "valid.whl"
            order, payloads = _wheel_payloads(source)
            _write_wheel(wheel, order, payloads)
            sdist = root / "valid.tar.gz"
            _write_sdist(sdist, _sdist_entries(source))
            with patch.object(build_release, "REPOSITORY_ROOT", source):
                hosts = {host: build_archive(host, root / "hosts") for host in ("claude", "codex")}
            validate_wheel(wheel, source, "0.1.0", WHEEL_EPOCH)
            validate_sdist(sdist, source, "0.1.0", WHEEL_EPOCH)
            for host, artifact in hosts.items():
                validate_host_zip(artifact, source, host)
            captured_wheel, captured_sdist = wheel.read_bytes(), sdist.read_bytes()
            captured_hosts = {host: artifact.read_bytes() for host, artifact in hosts.items()}
            source.rename(root / "parked-source")
            wheel.unlink()
            sdist.unlink()
            for artifact in hosts.values():
                artifact.unlink()
            validate_wheel_payload(captured_wheel, snapshot, "0.1.0", WHEEL_EPOCH)
            validate_sdist_payload(captured_sdist, snapshot, "0.1.0", WHEEL_EPOCH)
            for host, payload in captured_hosts.items():
                validate_host_zip_payload(payload, snapshot, host)

    def test_wheel_payload_preserves_metadata_membership_source_record_and_boundary_errors(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            snapshot = _capture_fixture(source)
            order, original = _wheel_payloads(source)
            prefix = "threadroot-0.1.0.dist-info/"
            for mutation, code in (
                ("boundary", "invalid_archive"), ("membership", "membership_mismatch"),
                ("metadata", "metadata_mismatch"), ("source", "source_mismatch"),
                ("record", "record_mismatch"),
            ):
                with self.subTest(mutation=mutation):
                    payloads, changed_order = dict(original), list(order)
                    if mutation == "membership":
                        changed_order.remove(prefix + "WHEEL")
                    elif mutation == "metadata":
                        payloads[prefix + "WHEEL"] += b"nonempty body\n"
                    elif mutation == "source":
                        payloads["threadroot/cli.py"] += b"# changed\n"
                    elif mutation == "record":
                        payloads[prefix + "RECORD"] = payloads[prefix + "RECORD"].replace(b"sha256=", b"sha256=x", 1)
                    artifact = root / f"{mutation}.whl"
                    _write_wheel(artifact, changed_order, payloads, regenerate_record=mutation != "record")
                    if mutation == "boundary":
                        artifact.write_bytes(artifact.read_bytes() + b"JUNK")
                    with self.assertRaises(ReleaseArchiveError) as path_error:
                        validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)
                    with self.assertRaises(ReleaseArchiveError) as payload_error:
                        validate_wheel_payload(artifact.read_bytes(), snapshot, "0.1.0", WHEEL_EPOCH)
                    self.assertEqual(path_error.exception.code, code)
                    self.assertEqual(payload_error.exception.code, code)

    def test_sdist_payload_preserves_duplicate_member_type_mode_and_path_errors(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            snapshot = _capture_fixture(source)
            original = _sdist_entries(source)
            for mutation, code in (
                ("duplicate", "duplicate_member"), ("type", "unsupported_member"),
                ("mode", "unsupported_mode"), ("path", "unsafe_path"),
            ):
                with self.subTest(mutation=mutation):
                    entries = [dict(entry) for entry in original]
                    if mutation == "duplicate":
                        entries.append(dict(entries[0]))
                    elif mutation == "type":
                        entries[0].update(kind=tarfile.FIFOTYPE, payload=b"")
                    elif mutation == "mode":
                        entries[0]["mode"] = 0o600
                    else:
                        entries[0]["name"] = "../escape"
                    artifact = root / f"{mutation}.tar.gz"
                    _write_sdist(artifact, entries)
                    with self.assertRaises(ReleaseArchiveError) as path_error:
                        validate_sdist(artifact, source, "0.1.0", WHEEL_EPOCH)
                    with self.assertRaises(ReleaseArchiveError) as payload_error:
                        validate_sdist_payload(artifact.read_bytes(), snapshot, "0.1.0", WHEEL_EPOCH)
                    self.assertEqual(path_error.exception.code, code)
                    self.assertEqual(payload_error.exception.code, code)

    def test_host_payload_preserves_unsupported_host_and_source_errors(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_release_source(root)
            snapshot = _capture_fixture(source)
            with patch.object(build_release, "REPOSITORY_ROOT", source):
                valid = build_archive("claude", root / "hosts")
            changed = root / "changed.zip"
            _rewrite_host_zip(valid, changed, mutation="source-byte")
            for host, artifact, code in (("unknown", valid, "unsupported_host"), ("claude", changed, "source_mismatch")):
                with self.subTest(host=host):
                    with self.assertRaises(ReleaseArchiveError) as path_error:
                        validate_host_zip(artifact, source, host)
                    with self.assertRaises(ReleaseArchiveError) as payload_error:
                        validate_host_zip_payload(artifact.read_bytes(), snapshot, host)
                    self.assertEqual(path_error.exception.code, code)
                    self.assertEqual(payload_error.exception.code, code)

    def test_payload_extractors_preserve_content_and_normalized_modes(self) -> None:
        tar_payload = _tar_bytes([("safe/", b"", 0o775, tarfile.DIRTYPE),
                                  ("safe/run.sh", b"#!/bin/sh\n", 0o775, tarfile.REGTYPE)])
        zip_payload = _zip_bytes([("safe/", b"", stat.S_IFDIR | 0o775),
                                  ("safe/run.sh", b"#!/bin/sh\n", stat.S_IFREG | 0o775)])
        for payload, path_api, payload_api in (
            (tar_payload, extract_regular_tar, extract_regular_tar_payload),
            (zip_payload, extract_regular_zip, extract_regular_zip_payload),
        ):
            with self.subTest(api=payload_api.__name__), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "artifact"
                artifact.write_bytes(payload)
                path_api(artifact, root / "path-out")
                payload_api(payload, root / "payload-out")
                for name in ("path-out", "payload-out"):
                    self.assertEqual((root / name / "safe/run.sh").read_bytes(), b"#!/bin/sh\n")
                    self.assertEqual(stat.S_IMODE((root / name / "safe/run.sh").stat().st_mode), 0o755)
                    self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o755)

    def test_payload_extractors_validate_members_before_destination_access(self) -> None:
        for api, payload, code in (
            (extract_regular_tar_payload, _tar_bytes([("../escape", b"x", 0o644, tarfile.REGTYPE)]), "unsafe_path"),
            (extract_regular_tar_payload, _tar_bytes([("fifo", b"", 0o644, tarfile.FIFOTYPE)]), "unsupported_member"),
            (extract_regular_zip_payload, _zip_bytes([("../escape", b"x", stat.S_IFREG | 0o644)]), "unsafe_path"),
            (extract_regular_zip_payload, _zip_bytes([("link", b"x", stat.S_IFLNK | 0o777)]), "unsupported_member"),
        ):
            with self.subTest(api=api.__name__, code=code), TemporaryDirectory() as directory:
                destination = Path(directory) / "out"
                with patch.object(release_archives.os, "lstat", side_effect=AssertionError("destination accessed")):
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        api(payload, destination)
                self.assertEqual(raised.exception.code, code)
                self.assertFalse(destination.exists())

    def test_payload_extractors_preserve_destination_rejections(self) -> None:
        for api, payload in (
            (extract_regular_tar_payload, _tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)])),
            (extract_regular_zip_payload, _zip_bytes([("safe/file", b"safe", stat.S_IFREG | 0o644)])),
        ):
            for state in ("empty", "nonempty", "symlink-parent"):
                with self.subTest(api=api.__name__, state=state), TemporaryDirectory() as directory:
                    root = Path(directory)
                    if state == "symlink-parent":
                        (root / "real").mkdir()
                        (root / "linked").symlink_to(root / "real", target_is_directory=True)
                        destination = root / "linked/out"
                    else:
                        destination = root / "out"
                        destination.mkdir()
                        if state == "nonempty":
                            (destination / "keep").write_bytes(b"keep")
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        api(payload, destination)
                    self.assertEqual(raised.exception.code, "unsafe_destination")
                    if state == "nonempty":
                        self.assertEqual((destination / "keep").read_bytes(), b"keep")
                    elif state == "symlink-parent":
                        self.assertEqual(list((root / "real").iterdir()), [])

    def test_payload_extractors_preserve_raced_destination_and_cleanup_owned_staging(self) -> None:
        for api, payload in (
            (extract_regular_tar_payload, _tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)])),
            (extract_regular_zip_payload, _zip_bytes([("safe/file", b"safe", stat.S_IFREG | 0o644)])),
        ):
            with self.subTest(api=api.__name__), TemporaryDirectory() as directory:
                root = Path(directory)
                original = release_archives._exclusive_rename
                raced = False

                def race(parent_fd: int, stage: str, destination: str, stage_fd: int, identity: os.stat_result) -> None:
                    nonlocal raced
                    raced = True
                    os.mkdir(destination, dir_fd=parent_fd)
                    original(parent_fd, stage, destination, stage_fd, identity)

                with patch.object(release_archives, "_exclusive_rename", side_effect=race):
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        api(payload, root / "out")
                self.assertTrue(raced)
                self.assertEqual(raised.exception.code, "unsafe_destination")
                self.assertEqual(list((root / "out").iterdir()), [])
                self.assertEqual(list(root.glob(".out.stage-*")), [])

    def test_payload_extractors_never_cleanup_replacement_staging(self) -> None:
        for api, payload in (
            (extract_regular_tar_payload, _tar_bytes([("safe/file", b"safe", 0o644, tarfile.REGTYPE)])),
            (extract_regular_zip_payload, _zip_bytes([("safe/file", b"safe", stat.S_IFREG | 0o644)])),
        ):
            with self.subTest(api=api.__name__), TemporaryDirectory() as directory:
                root = Path(directory)
                original = release_archives._exclusive_rename
                replacement: Path | None = None

                def race(parent_fd: int, stage: str, destination: str, stage_fd: int, identity: os.stat_result) -> None:
                    nonlocal replacement
                    (root / stage).rename(root / "parked")
                    replacement = root / stage
                    replacement.mkdir()
                    (replacement / "keep").write_bytes(b"competitor")
                    original(parent_fd, stage, destination, stage_fd, identity)

                with patch.object(release_archives, "_exclusive_rename", side_effect=race):
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        api(payload, root / "out")
                self.assertEqual(raised.exception.code, "unsafe_destination")
                self.assertIsNotNone(replacement)
                self.assertEqual((replacement / "keep").read_bytes(), b"competitor")
                self.assertFalse((root / "out").exists())

    def test_tar_payload_preserves_exact_global_pax_comment(self) -> None:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT,
                          pax_headers={"comment": "commit-sha"}) as archive:
            info = tarfile.TarInfo("safe.txt")
            info.mode, info.size = 0o644, 4
            archive.addfile(info, io.BytesIO(b"safe"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            extract_regular_tar_payload(output.getvalue(), root / "valid", "commit-sha")
            self.assertEqual((root / "valid/safe.txt").read_bytes(), b"safe")
            with self.assertRaises(ReleaseArchiveError) as raised:
                extract_regular_tar_payload(output.getvalue(), root / "invalid")
            self.assertEqual(raised.exception.code, "invalid_archive")
            self.assertFalse((root / "invalid").exists())


def _tar_entry(name: str, kind: bytes) -> tuple[str, bytes, int, bytes]:
    return (name, b"x", 0o644, kind)


if __name__ == "__main__":
    unittest.main()
