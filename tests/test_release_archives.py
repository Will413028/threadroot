from __future__ import annotations

import io
import base64
import gzip
import hashlib
import os
from pathlib import Path
import stat
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts import build_release
from scripts import release_archives
from scripts.build_release import build_archive
from scripts.release_archives import (
    ReleaseArchiveError,
    extract_regular_tar,
    extract_regular_zip,
    validate_archive_name,
    validate_host_zip,
    validate_sdist,
    validate_wheel,
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
                "self": rows[-1] + "sha256=x,1",
            }
            for label, changed in mutations.items():
                with self.subTest(label=label):
                    payloads = dict(original)
                    changed_rows = list(rows)
                    changed_rows[0 if label != "self" else -1] = changed
                    payloads[record] = ("\n".join(changed_rows) + "\n").encode()
                    self.assertNotEqual(payloads[record], original[record])
                    artifact = root / f"record-{label}.whl"
                    _write_wheel(artifact, order, payloads, regenerate_record=False)
                    with self.assertRaises(ReleaseArchiveError) as raised:
                        validate_wheel(artifact, source, "0.1.0", WHEEL_EPOCH)
                    self.assertEqual(raised.exception.code, "record_mismatch")
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


def _tar_entry(name: str, kind: bytes) -> tuple[str, bytes, int, bytes]:
    return (name, b"x", 0o644, kind)


if __name__ == "__main__":
    unittest.main()
