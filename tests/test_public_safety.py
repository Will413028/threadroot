from __future__ import annotations

import ast
import bz2
from dataclasses import FrozenInstanceError
import gzip
import io
import lzma
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import tomllib
import unittest
import zipfile
from unittest.mock import patch

from scripts import check_public
from scripts.check_public import Finding, scan_path
from tests.test_release_archives import (
    _add_trailing_bytes_to_last_deflate_stream,
    _gzip_tar_payload,
    _hide_metadata_behind_directory_size,
    _mutate_first_tar_header,
    _mutate_first_zip_declared_size,
    _mutate_zip_fixed_header,
    _prepend_gnu_longname_header,
    _prepend_tar_metadata_header,
    _tar_bytes,
    _zip_directory_bytes,
)


def private_key_header() -> str:
    return "-----BEGIN " + "PRIVATE KEY-----"


def home_path() -> str:
    return "/" + "Users/example/private-vault"


def credential_line() -> str:
    return "api" + "_key = synthetic-value"


def run_public_cli(
    *arguments: str | Path,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts/check_public.py"),
            *(str(argument) for argument in arguments),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def run_public_main_with_argv0(
    argv0: str,
    *arguments: str | Path,
) -> subprocess.CompletedProcess[str]:
    repository_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        item
        for item in (str(repository_root), existing_pythonpath)
        if item
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from scripts.check_public import main; "
            "sys.argv = sys.argv[1:]; raise SystemExit(main())",
            argv0,
            *(str(argument) for argument in arguments),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repository_root,
        env=environment,
    )


def damage_first_zip_member(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        info = archive.infolist()[0]
    payload = bytearray(path.read_bytes())
    offset = info.header_offset
    name_length = int.from_bytes(payload[offset + 26 : offset + 28], "little")
    extra_length = int.from_bytes(payload[offset + 28 : offset + 30], "little")
    data_offset = offset + 30 + name_length + extra_length
    payload[data_offset] ^= 0xFF
    path.write_bytes(payload)


def truncate_zip_end_record(path: Path) -> None:
    payload = path.read_bytes()
    end_record = payload.rfind(b"PK\x05\x06")
    if end_record < 0:
        raise AssertionError("ZIP end record was not found")
    path.write_bytes(payload[:end_record])


def damage_tar_header_checksum(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    if payload[257:262] != b"ustar":
        raise AssertionError("ustar signature was not found")
    payload[148:156] = b"000000\0 "
    path.write_bytes(payload)


def damage_compressed_tar_header_checksum(path: Path, compression: str) -> None:
    decompressors = {
        "gzip": gzip.decompress,
        "bzip2": bz2.decompress,
        "xz": lzma.decompress,
    }
    compressors = {
        "gzip": lambda payload: gzip.compress(payload, mtime=0),
        "bzip2": bz2.compress,
        "xz": lzma.compress,
    }
    payload = bytearray(decompressors[compression](path.read_bytes()))
    if payload[257:262] != b"ustar":
        raise AssertionError("ustar signature was not found")
    payload[148:156] = b"000000\0 "
    path.write_bytes(compressors[compression](bytes(payload)))


def gzip_with_metadata(
    payload: bytes,
    *,
    extra: bytes = b"",
    filename: bytes = b"",
    comment: bytes = b"",
) -> bytes:
    compressed = gzip.compress(payload, mtime=0)
    flags = 0
    metadata = bytearray()
    if extra:
        flags |= 0x04
        metadata.extend(len(extra).to_bytes(2, "little"))
        metadata.extend(extra)
    if filename:
        flags |= 0x08
        metadata.extend(filename + b"\0")
    if comment:
        flags |= 0x10
        metadata.extend(comment + b"\0")
    header = bytearray(compressed[:10])
    header[3] = flags
    result = bytes(header + metadata + compressed[10:])
    if gzip.decompress(result) != payload:
        raise AssertionError("gzip metadata fixture is not readable")
    return result


class PublicSafetyTests(unittest.TestCase):
    def test_zip_scanner_rejects_directory_payload_as_unreadable(self) -> None:
        denied = "Synthetic " + "Directory Payload"
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(method=method), TemporaryDirectory() as directory:
                artifact = Path(directory) / "archive.data"
                artifact.write_bytes(_zip_directory_bytes(denied.encode(), method))

                with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                    scan_path(artifact, denied_terms=(denied,))

    def test_cli_directory_payload_failure_is_sanitized_and_exit_two(self) -> None:
        denied = "Synthetic " + "Directory Payload"
        member = "safe/"
        internal_error = "ZIP directory payload must be empty"
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(method=method), TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "unsafe-archive-\x1b.data"
                artifact.write_bytes(_zip_directory_bytes(denied.encode(), method))
                denylist = root / "denylist.txt"
                denylist.write_text(denied + "\n", encoding="utf-8")

                completed = run_public_cli(
                    "--denylist",
                    denylist,
                    artifact,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertEqual(completed.stderr, "public scan failed\n")
                for stream in (completed.stdout, completed.stderr):
                    self.assertNotIn(denied, stream)
                    self.assertNotIn(artifact.name, stream)
                    self.assertNotIn(member, stream)
                    self.assertNotIn("\x1b", stream)
                    self.assertNotIn(internal_error, stream)

    def test_finding_is_frozen(self) -> None:
        finding = Finding("code", "path", None, "message")
        with self.assertRaises(FrozenInstanceError):
            finding.code = "changed"  # type: ignore[misc]

    def test_detects_sensitive_content_with_line_numbers(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.txt").write_text(
                "safe\n"
                + home_path()
                + "\n"
                + private_key_header()
                + "\n"
                + credential_line()
                + "\n",
                encoding="utf-8",
            )
            findings = scan_path(root)

        self.assertEqual(
            [(finding.code, finding.line) for finding in findings],
            [
                ("absolute_home_path", 2),
                ("private_key", 3),
                ("credential_assignment", 4),
            ],
        )
        rendered = "\n".join(finding.message for finding in findings)
        self.assertNotIn("private-vault", rendered)
        self.assertNotIn("synthetic-value", rendered)

    def test_detects_linux_home_and_each_nonempty_credential_name(self) -> None:
        names = ("api_key", "access_token", "client_secret", "password", "secret")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lines = ["/" + "home/example/vault"]
            lines.extend(f'{name}: "synthetic"' for name in names)
            lines.extend(f'{name}: ""' for name in names)
            (root / "bad.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            findings = scan_path(root)

        self.assertEqual(
            [(finding.code, finding.line) for finding in findings],
            [("absolute_home_path", 1)]
            + [("credential_assignment", line) for line in range(2, 7)],
        )

    def test_empty_or_null_credential_values_are_not_findings(self) -> None:
        empty_values = (
            "",
            '\"\"',
            "''",
            "null",
            "None",
            "unset",
            "~",
            "{}",
            "[]",
            '\"\" # blank',
            "'' # blank",
            "null,",
            '\"\"}, # blank',
        )
        names = ("api_key", "access_token", "client_secret", "password", "secret")
        lines = [f"{name} = {value}" for name in names for value in empty_values]
        with TemporaryDirectory() as directory:
            target = Path(directory) / "empty.txt"
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual(scan_path(target), [])

    def test_delimiter_only_credential_values_are_findings(self) -> None:
        names = ("pass" + "word", "sec" + "ret", "api" + "_key")
        lines = tuple(
            f"{name} = {value}" for name, value in zip(names, ("}", "]", ","))
        )
        with TemporaryDirectory() as directory:
            target = Path(directory) / "delimiters.txt"
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            findings = scan_path(target)

        self.assertEqual(
            [(finding.code, finding.line) for finding in findings],
            [
                ("credential_assignment", 1),
                ("credential_assignment", 2),
                ("credential_assignment", 3),
            ],
        )

    def test_comment_only_and_structurally_empty_credentials_are_clean(self) -> None:
        empty_values = (
            "# blank",
            "{ }",
            "[ ]",
            "[{ }, [ ]]",
            "{[ ], { }}",
            '\"\"}, # blank',
            "null]}, # blank",
            "unset, } # blank",
        )
        name = "pass" + "word"
        lines = [f"{name} = {value}" for value in empty_values]
        with TemporaryDirectory() as directory:
            target = Path(directory) / "structurally-empty.txt"
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual(scan_path(target), [])

    def test_denied_term_is_literal_case_sensitive_and_sanitized(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            denied = "Synthetic " + "Orchard LLC"
            (root / f"{denied}.txt").write_text(
                denied.lower() + "\n" + denied + "\n",
                encoding="utf-8",
            )
            findings = scan_path(root, denied_terms=("", denied))

        self.assertEqual(
            [(finding.code, finding.line) for finding in findings],
            [("denied_term", None), ("denied_term", 2)],
        )
        self.assertNotIn(denied, repr(findings))

    def test_finding_path_suppresses_placeholder_conflicting_terms(self) -> None:
        for denied in ("redacted", "act"):
            with self.subTest(denied=denied), TemporaryDirectory() as directory:
                target = Path(directory) / f"{denied}.txt"
                target.write_text("safe\n", encoding="utf-8")

                findings = scan_path(target, denied_terms=(denied,))

                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].code, "denied_term")
                self.assertNotIn(denied, findings[0].path)
                self.assertNotIn(denied, repr(findings))

    def test_filesystem_finding_paths_escape_unsafe_unicode(self) -> None:
        cases = (
            ("newline", "\n", r"\n"),
            ("carriage-return", "\r", r"\r"),
            ("tab", "\t", r"\t"),
            ("bell", "\x07", r"\u0007"),
            ("escape", "\x1b", r"\u001b"),
            ("delete", "\x7f", r"\u007f"),
            ("soft-hyphen", "\u00ad", r"\u00ad"),
            ("bidi-override", "\u202e", r"\u202e"),
            ("bidi-isolate", "\u2066", r"\u2066"),
            ("line-separator", "\u2028", r"\u2028"),
            ("paragraph-separator", "\u2029", r"\u2029"),
        )
        for label, unsafe, escaped in cases:
            with self.subTest(character=label), TemporaryDirectory() as directory:
                target = Path(directory) / f"unsafe{unsafe}.txt"
                target.write_text(private_key_header() + "\n", encoding="utf-8")

                findings = scan_path(target)
                completed = run_public_cli(target)

                self.assertEqual(
                    [(finding.code, finding.path, finding.line) for finding in findings],
                    [("private_key", f"unsafe{escaped}.txt", 1)],
                )
                self.assertNotIn(unsafe, findings[0].path)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stderr, "")
                self.assertEqual(
                    completed.stdout,
                    f"unsafe{escaped}.txt:1: private_key: "
                    "private-key header detected\n",
                )
                self.assertNotIn(unsafe, completed.stdout.removesuffix("\n"))

    def test_zip_member_finding_paths_escape_unsafe_unicode(self) -> None:
        cases = (
            ("bell", "\x07", r"\u0007"),
            ("escape", "\x1b", r"\u001b"),
            ("delete", "\x7f", r"\u007f"),
            ("soft-hyphen", "\u00ad", r"\u00ad"),
            ("bidi-override", "\u202e", r"\u202e"),
            ("bidi-isolate", "\u2066", r"\u2066"),
            ("line-separator", "\u2028", r"\u2028"),
            ("paragraph-separator", "\u2029", r"\u2029"),
        )
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "unsafe-names.zip"
            with zipfile.ZipFile(artifact, "w") as archive:
                for label, unsafe, _escaped in cases:
                    archive.writestr(
                        f"notes/{label}-{unsafe}.txt",
                        private_key_header() + "\n",
                    )

            findings = scan_path(artifact)
            completed = run_public_cli(artifact)

        self.assertCountEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [
                (
                    "private_key",
                    f"unsafe-names.zip!notes/{label}-{escaped}.txt",
                    1,
                )
                for label, _unsafe, escaped in cases
            ],
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.splitlines()), len(cases))
        for _label, unsafe, escaped in cases:
            self.assertNotIn(unsafe, completed.stdout)
            self.assertIn(escaped, completed.stdout)

    def test_denied_term_is_detected_in_each_filesystem_path_component(self) -> None:
        denied = "Synthetic " + "Juniper Works"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / denied / "safe.txt"
            nested.parent.mkdir()
            nested.write_text("safe\n", encoding="utf-8")
            findings = scan_path(root, denied_terms=(denied,))

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [("denied_term", "[redacted]", None)],
        )
        self.assertNotIn(denied, repr(findings))

    def test_scans_one_regular_file(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "one.txt"
            target.write_text(home_path() + "\n", encoding="utf-8")
            findings = scan_path(target)
        self.assertEqual([(item.path, item.line) for item in findings], [("one.txt", 1)])

    def test_rejects_filesystem_symlinks_without_reading_targets(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "scan-root"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text(private_key_header() + "\n", encoding="utf-8")
            (root / "linked.txt").symlink_to(outside)
            (root / "linked-dir").symlink_to(base, target_is_directory=True)

            findings = scan_path(root)

        self.assertEqual(
            [(finding.code, finding.path) for finding in findings],
            [
                ("symlink_entry", "linked-dir"),
                ("symlink_entry", "linked.txt"),
            ],
        )

    def test_symlink_scan_root_is_reported_without_following(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text(private_key_header() + "\n", encoding="utf-8")
            link = root / "scan-link"
            link.symlink_to(target)
            findings = scan_path(link)

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [("symlink_entry", "scan-link", None)],
        )

    def test_skips_only_named_cache_directories_and_binary_payloads(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (".git", ".venv", "__pycache__"):
                skipped = root / name
                skipped.mkdir()
                (skipped / "bad.txt").write_text(home_path(), encoding="utf-8")
            (root / "binary.dat").write_bytes(b"\x00" + home_path().encode())
            self.assertEqual(scan_path(root), [])

    def test_hidden_orchestration_directory_remains_in_scope(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / ".superpowers/evidence.txt"
            evidence.parent.mkdir()
            evidence.write_text(home_path() + "\n", encoding="utf-8")

            findings = scan_path(root)

        self.assertEqual(
            [(finding.code, finding.path) for finding in findings],
            [("absolute_home_path", ".superpowers/evidence.txt")],
        )

    def test_zip_is_detected_by_content_and_scans_text_members(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "renamed.data"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("notes/bad.txt", home_path() + "\n")

            findings = scan_path(root)

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [("absolute_home_path", "renamed.data!notes/bad.txt", 1)],
        )

    def test_denylist_scans_zip_names_comments_and_extra_fields(self) -> None:
        denied = "Synthetic " + "Maple Studio"
        marker = denied.encode("utf-8")
        extra = b"\xfe\xca" + len(marker).to_bytes(2, "little") + marker
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "bundle.data"
            with zipfile.ZipFile(
                artifact,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.comment = marker
                info = zipfile.ZipInfo(f"notes/{denied}.txt")
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.comment = marker
                info.extra = extra
                archive.writestr(info, b"safe\n")
            findings = scan_path(artifact, denied_terms=(denied,))

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [
                ("denied_term", "bundle.data!<archive-comment>", None),
                ("denied_term", "bundle.data!notes/[redacted].txt", None),
                (
                    "denied_term",
                    "bundle.data!notes/[redacted].txt!<comment>",
                    None,
                ),
                (
                    "denied_term",
                    "bundle.data!notes/[redacted].txt!<extra>",
                    None,
                ),
            ],
        )
        self.assertNotIn(denied, repr(findings))

    def test_denylist_scans_exact_raw_zip_name_when_utf8_flag_is_cleared(self) -> None:
        denied = "Synthetic Caf" + "\N{LATIN SMALL LETTER E WITH ACUTE}"
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(f"notes/{denied}.txt", b"safe\n")
        payload = _mutate_zip_fixed_header(
            output.getvalue(),
            "clear-utf8-flags",
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertNotIn(denied, archive.infolist()[0].filename)

        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "bundle.data"
            artifact.write_bytes(payload)
            findings = scan_path(artifact, denied_terms=(denied,))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "denied_term")
        self.assertNotIn(denied, repr(findings))

    def test_denylist_decodes_zip_member_comment_with_flag_encoding(self) -> None:
        denied = "Synthetic Caf" + "\N{LATIN SMALL LETTER E WITH ACUTE}"
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            info = zipfile.ZipInfo("safe.txt")
            info.comment = denied.encode("cp437")
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, b"safe\n")

        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "bundle.data"
            artifact.write_bytes(output.getvalue())
            findings = scan_path(artifact, denied_terms=(denied,))

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [("denied_term", "bundle.data!safe.txt!<comment>", None)],
        )
        self.assertNotIn(denied, repr(findings))

    def test_zip_scanner_enforces_member_cap_before_shared_decoder(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("safe.txt", b"x" * 33)
        payload = _mutate_first_zip_declared_size(output.getvalue(), 33)

        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "oversize.data"
            artifact.write_bytes(payload)
            with patch.object(
                check_public,
                "MAX_DECOMPRESSED_BYTES",
                32,
            ), patch(
                "scripts.release_archives.zlib.decompressobj",
                side_effect=AssertionError("decoder must not be called"),
            ) as decoder, self.assertRaisesRegex(
                RuntimeError,
                "public scan failed",
            ):
                scan_path(artifact)
            decoder.assert_not_called()

    def test_zip_fixed_header_covert_bytes_fail_closed(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("safe.txt", b"safe\n")
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "mutated.data"
            for mutation in (
                "local-needed",
                "central-needed",
                "consistent-needed",
                "made-version",
                "made-system",
                "disk-start",
                "internal-attrs",
            ):
                with self.subTest(mutation=mutation):
                    artifact.write_bytes(
                        _mutate_zip_fixed_header(output.getvalue(), mutation)
                    )
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "public scan failed",
                    ):
                        scan_path(artifact)

    def test_crc_damaged_zip_member_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "damaged.data"
            with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("payload.txt", "synthetic payload\n")
            damage_first_zip_member(artifact)
            self.assertTrue(zipfile.is_zipfile(artifact))

            with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(artifact)

    def test_truncated_zip_structure_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "truncated.data"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("payload.txt", credential_line() + "\n")
            truncate_zip_end_record(artifact)
            self.assertFalse(zipfile.is_zipfile(artifact))

            with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(artifact)

    def test_incomplete_zip_structural_signatures_fail_closed(self) -> None:
        signatures = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "incomplete.data"
            for signature in signatures:
                with self.subTest(signature=signature.hex()):
                    artifact.write_bytes(signature + b"\x00" * 2)
                    self.assertFalse(zipfile.is_zipfile(artifact))
                    with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                        scan_path(artifact)

    def test_central_directory_zip_structure_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "central.data"
            artifact.write_bytes(b"PK\x01\x02" + b"\x00" * 42)
            self.assertFalse(zipfile.is_zipfile(artifact))

            with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(artifact)

    def test_non_utf8_zip_symlink_target_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "link.data"
            with zipfile.ZipFile(artifact, "w") as archive:
                link = zipfile.ZipInfo("nested/link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, b"\xff../../outside.txt")

            with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(artifact)

    def test_tar_is_detected_by_content_and_scans_text_members(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "renamed.payload"
            payload = private_key_header().encode() + b"\n"
            with tarfile.open(artifact, "w:gz") as archive:
                info = tarfile.TarInfo("notes/bad.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            findings = scan_path(root)

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [("private_key", "renamed.payload!notes/bad.txt", 1)],
        )

    def test_denylist_scans_tar_names_owner_names_and_link_targets(self) -> None:
        denied = "Synthetic " + "Willow Lab"
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "bundle.data"
            with tarfile.open(artifact, "w") as archive:
                regular = tarfile.TarInfo(f"notes/{denied}.txt")
                regular.size = len(b"safe\n")
                regular.uname = denied
                regular.gname = denied
                archive.addfile(regular, io.BytesIO(b"safe\n"))
                symbolic = tarfile.TarInfo("links/safe")
                symbolic.type = tarfile.SYMTYPE
                symbolic.linkname = denied
                archive.addfile(symbolic)
            findings = scan_path(artifact, denied_terms=(denied,))

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [
                (
                    "denied_term",
                    "bundle.data!links/safe!<link-target>",
                    None,
                ),
                ("denied_term", "bundle.data!notes/[redacted].txt", None),
                (
                    "denied_term",
                    "bundle.data!notes/[redacted].txt!<gname>",
                    None,
                ),
                (
                    "denied_term",
                    "bundle.data!notes/[redacted].txt!<uname>",
                    None,
                ),
            ],
        )
        self.assertNotIn(denied, repr(findings))

    def test_tar_member_read_error_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "broken.payload"
            payload = b"synthetic\n"
            with tarfile.open(artifact, "w") as archive:
                info = tarfile.TarInfo("payload.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            with (
                patch.object(tarfile.TarFile, "extractfile", side_effect=OSError("read failed")),
                self.assertRaisesRegex(RuntimeError, "public scan failed"),
            ):
                scan_path(artifact)

    def test_damaged_tar_header_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "damaged.payload"
            payload = (credential_line() + "\n").encode()
            with tarfile.open(artifact, "w") as archive:
                info = tarfile.TarInfo("payload.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            damage_tar_header_checksum(artifact)
            with self.assertRaises(tarfile.ReadError):
                tarfile.open(artifact, "r:*")

            with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(artifact)

    def test_damaged_compressed_tar_fails_closed(self) -> None:
        cases = (
            ("gzip", "w:gz"),
            ("bzip2", "w:bz2"),
            ("xz", "w:xz"),
        )
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "damaged.data"
            for compression, mode in cases:
                with self.subTest(compression=compression):
                    payload = (credential_line() + "\n").encode()
                    with tarfile.open(artifact, mode) as archive:
                        info = tarfile.TarInfo("payload.txt")
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
                    damage_compressed_tar_header_checksum(artifact, compression)
                    with self.assertRaises(tarfile.ReadError):
                        tarfile.open(artifact, "r:*")

                    with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                        scan_path(artifact)

    def test_corrupt_compression_envelopes_fail_closed(self) -> None:
        envelopes = {
            "gzip": b"\x1f\x8b",
            "bzip2": b"BZh",
            "xz": b"\xfd7zXZ\x00",
        }
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "corrupt.data"
            for compression, signature in envelopes.items():
                with self.subTest(compression=compression):
                    artifact.write_bytes(signature + b"not-an-archive")
                    with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                        scan_path(artifact)

    def test_denylist_scans_standalone_compression_payloads(self) -> None:
        denied = "Synthetic " + "Birch Collective"
        compressors = {
            "gzip": lambda payload: gzip.compress(payload, mtime=0),
            "bzip2": bz2.compress,
            "xz": lzma.compress,
        }
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "compressed.data"
            for compression, compress in compressors.items():
                with self.subTest(compression=compression):
                    artifact.write_bytes(compress((denied + "\n").encode("utf-8")))
                    findings = scan_path(artifact, denied_terms=(denied,))
                    self.assertEqual(
                        [
                            (finding.code, finding.path, finding.line)
                            for finding in findings
                        ],
                        [("denied_term", "compressed.data", 1)],
                    )
                    self.assertNotIn(denied, repr(findings))

    def test_denylist_scans_gzip_extra_filename_and_comment_metadata(self) -> None:
        denied = "Synthetic " + "Aspen House"
        marker = denied.encode("utf-8")
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "compressed.data"
            artifact.write_bytes(
                gzip_with_metadata(
                    b"safe\n",
                    extra=marker,
                    filename=marker,
                    comment=marker,
                )
            )
            findings = scan_path(artifact, denied_terms=(denied,))

        self.assertEqual(
            [(finding.code, finding.path, finding.line) for finding in findings],
            [
                ("denied_term", "compressed.data!<gzip-comment>", None),
                ("denied_term", "compressed.data!<gzip-extra>", None),
                ("denied_term", "compressed.data!<gzip-filename>", None),
            ],
        )
        self.assertNotIn(denied, repr(findings))

    def test_denylist_scans_latin1_gzip_filename_and_comment_semantics(self) -> None:
        denied = "Synthetic Caf" + "\N{LATIN SMALL LETTER E WITH ACUTE}"
        filename_output = io.BytesIO()
        with gzip.GzipFile(
            fileobj=filename_output,
            mode="wb",
            filename=denied,
            mtime=0,
        ) as stream:
            stream.write(b"safe\n")
        fixtures = {
            "filename": filename_output.getvalue(),
            "comment": gzip_with_metadata(
                b"safe\n",
                comment=denied.encode("latin-1"),
            ),
        }

        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "compressed.data"
            for label, payload in fixtures.items():
                with self.subTest(label=label):
                    artifact.write_bytes(payload)
                    findings = scan_path(artifact, denied_terms=(denied,))
                    self.assertEqual(len(findings), 1)
                    self.assertEqual(findings[0].code, "denied_term")
                    self.assertIn(f"<gzip-{label}>", findings[0].path)
                    self.assertNotIn(denied, repr(findings))

    def test_standalone_compression_expansion_is_bounded(self) -> None:
        compressors = {
            "gzip": lambda payload: gzip.compress(payload, mtime=0),
            "bzip2": bz2.compress,
            "xz": lzma.compress,
        }
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "compressed.data"
            for compression, compress in compressors.items():
                with self.subTest(compression=compression):
                    artifact.write_bytes(compress(b"x" * 33))
                    with patch.object(
                        check_public,
                        "MAX_DECOMPRESSED_BYTES",
                        32,
                        create=True,
                    ), self.assertRaisesRegex(RuntimeError, "public scan failed"):
                        scan_path(artifact)

    def test_xz_decoder_has_an_explicit_memory_limit(self) -> None:
        high_dictionary = lzma.compress(
            b"safe\n",
            format=lzma.FORMAT_XZ,
            filters=[
                {
                    "id": lzma.FILTER_LZMA2,
                    "dict_size": 16 * 1024 * 1024,
                }
            ],
        )
        ordinary = lzma.compress(b"safe\n", format=lzma.FORMAT_XZ)
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "compressed.data"
            artifact.write_bytes(high_dictionary)
            with patch.object(
                check_public,
                "MAX_XZ_DECODER_MEMORY",
                1024 * 1024,
                create=True,
            ), self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(artifact)

            artifact.write_bytes(ordinary)
            self.assertEqual(scan_path(artifact), [])

    def test_unrepresentable_filesystem_and_tar_names_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "safe.txt"
            safe.write_bytes(b"safe\n")
            with self.subTest(kind="filesystem"), patch.object(
                check_public.os,
                "listdir",
                return_value=["safe-\udcff.txt"],
            ), patch.object(
                check_public,
                "_lstat_at",
                return_value=safe.lstat(),
            ), patch.object(
                check_public,
                "_read_at",
                return_value=b"safe\n",
            ), self.assertRaisesRegex(RuntimeError, "public scan failed"):
                scan_path(root)

            tar_payload = _mutate_first_tar_header(
                _tar_bytes(
                    [("safe.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
                ),
                name=b"safe-\xff.txt",
            )
            artifact = root / "opaque.data"
            artifact.write_bytes(tar_payload)
            with self.subTest(kind="tar"), self.assertRaisesRegex(
                RuntimeError,
                "public scan failed",
            ):
                scan_path(artifact)

    def test_valid_compressed_and_empty_archives_are_clean(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index, mode in enumerate(("w:gz", "w:bz2", "w:xz")):
                artifact = root / f"valid-{index}.data"
                with tarfile.open(artifact, mode) as archive:
                    info = tarfile.TarInfo("safe.txt")
                    info.size = len(b"safe\n")
                    archive.addfile(info, io.BytesIO(b"safe\n"))
                self.assertEqual(scan_path(artifact), [])

            empty_zip = root / "empty-zip.data"
            with zipfile.ZipFile(empty_zip, "w"):
                pass
            empty_tar = root / "empty-tar.data"
            with tarfile.open(empty_tar, "w"):
                pass
            self.assertEqual(scan_path(empty_zip), [])
            self.assertEqual(scan_path(empty_tar), [])

    def test_malformed_zip_and_tar_framing_fails_closed(self) -> None:
        zip_output = io.BytesIO()
        with zipfile.ZipFile(
            zip_output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("safe.txt", b"safe\n")
        tar_payload = _tar_bytes(
            [("safe.txt", b"safe\n", 0o644, tarfile.REGTYPE)]
        )
        cases = {
            "deflate-trailing": _add_trailing_bytes_to_last_deflate_stream(
                zip_output.getvalue()
            ),
            "tar-padding": _gzip_tar_payload(
                _mutate_first_tar_header(
                    tar_payload,
                    padding_marker=b"SYNTHETIC-PADDING-MARKER",
                )
            ),
            "tar-linkname": _gzip_tar_payload(
                _mutate_first_tar_header(
                    tar_payload,
                    linkname=b"SYNTHETIC-LINKNAME-MARKER",
                )
            ),
            "tar-reserved-tail": _gzip_tar_payload(
                _mutate_first_tar_header(
                    tar_payload,
                    reserved_tail=b"SYNTHETIC",
                )
            ),
            "tar-gnu-longname": _gzip_tar_payload(
                _prepend_gnu_longname_header(tar_payload, "safe.txt")
            ),
            "tar-pax-global": _gzip_tar_payload(
                _prepend_tar_metadata_header(tar_payload, tarfile.XGLTYPE)
            ),
            "tar-pax-member": _gzip_tar_payload(
                _prepend_tar_metadata_header(tar_payload, tarfile.XHDTYPE)
            ),
            "tar-pax-solaris": _gzip_tar_payload(
                _prepend_tar_metadata_header(
                    tar_payload,
                    tarfile.SOLARIS_XHDTYPE,
                )
            ),
            "tar-name-nul-tail": _gzip_tar_payload(
                _mutate_first_tar_header(
                    tar_payload,
                    name_tail=b"SYNTHETIC-HIDDEN",
                )
            ),
            "tar-directory-size-skip": _gzip_tar_payload(
                _hide_metadata_behind_directory_size(
                    _tar_bytes(
                        [
                            ("safe/", b"", 0o755, tarfile.DIRTYPE),
                            ("safe/file.txt", b"safe\n", 0o644, tarfile.REGTYPE),
                        ]
                    )
                )
            ),
            "tar-unaligned-zero-suffix": _gzip_tar_payload(
                tar_payload + b"\0"
            ),
        }
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "malformed.data"
            for mutation, payload in cases.items():
                with self.subTest(mutation=mutation):
                    artifact.write_bytes(payload)
                    with self.assertRaisesRegex(RuntimeError, "public scan failed"):
                        scan_path(artifact)

    def test_cli_deflate_trailing_bytes_fail_with_generic_message_and_exit_two(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("safe.txt", b"safe\n")
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "malformed.data"
            artifact.write_bytes(
                _add_trailing_bytes_to_last_deflate_stream(output.getvalue())
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    str(artifact),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "public scan failed\n")

    def test_zip_reports_unsafe_names_and_escaping_symlink_without_following(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            scan_root = base / "scan"
            scan_root.mkdir()
            artifact = scan_root / "unsafe.bin"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("../outside.txt", private_key_header() + "\n")
                archive.writestr("/absolute.txt", "safe\n")
                archive.writestr("C:\\drive.txt", "safe\n")
                link = zipfile.ZipInfo("nested/link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, "../../outside.txt")
                windows_link = zipfile.ZipInfo("nested/windows-link")
                windows_link.create_system = 3
                windows_link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(windows_link, "C:\\outside.txt")

            findings = scan_path(artifact)
            self.assertFalse((base / "outside.txt").exists())

        self.assertEqual(
            [(finding.code, finding.path) for finding in findings],
            [
                ("path_escape", "unsafe.bin!../outside.txt"),
                ("private_key", "unsafe.bin!../outside.txt"),
                ("path_escape", "unsafe.bin!/absolute.txt"),
                ("path_escape", "unsafe.bin!C:\\drive.txt"),
                ("path_escape", "unsafe.bin!nested/link"),
                ("path_escape", "unsafe.bin!nested/windows-link"),
            ],
        )

    def test_safe_zip_symlink_is_not_dereferenced_or_reported(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "safe.bin"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("target.txt", private_key_header() + "\n")
                link = zipfile.ZipInfo("nested/link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(link, "../target.txt")

            findings = scan_path(artifact)

        self.assertEqual(
            [(finding.code, finding.path) for finding in findings],
            [("private_key", "safe.bin!target.txt")],
        )

    def test_tar_reports_unsafe_names_and_escaping_links_without_following(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            scan_root = base / "scan"
            scan_root.mkdir()
            artifact = scan_root / "unsafe.payload"
            with tarfile.open(artifact, "w") as archive:
                escaped = tarfile.TarInfo("../outside.txt")
                escaped.size = 0
                archive.addfile(escaped, io.BytesIO())
                symbolic = tarfile.TarInfo("nested/symbolic")
                symbolic.type = tarfile.SYMTYPE
                symbolic.linkname = "../../outside.txt"
                archive.addfile(symbolic)
                hard = tarfile.TarInfo("nested/hard")
                hard.type = tarfile.LNKTYPE
                hard.linkname = "../outside.txt"
                archive.addfile(hard)

            findings = scan_path(artifact)
            self.assertFalse((base / "outside.txt").exists())

        self.assertEqual(
            [(finding.code, finding.path) for finding in findings],
            [
                ("path_escape", "unsafe.payload!../outside.txt"),
                ("path_escape", "unsafe.payload!nested/hard"),
                ("path_escape", "unsafe.payload!nested/symbolic"),
            ],
        )

    def test_safe_tar_links_are_not_dereferenced_or_reported(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "safe.payload"
            payload = private_key_header().encode() + b"\n"
            with tarfile.open(artifact, "w") as archive:
                target = tarfile.TarInfo("target.txt")
                target.size = len(payload)
                archive.addfile(target, io.BytesIO(payload))
                symbolic = tarfile.TarInfo("nested/symbolic")
                symbolic.type = tarfile.SYMTYPE
                symbolic.linkname = "../target.txt"
                archive.addfile(symbolic)
                hard = tarfile.TarInfo("hard")
                hard.type = tarfile.LNKTYPE
                hard.linkname = "target.txt"
                archive.addfile(hard)

            findings = scan_path(artifact)

        self.assertEqual(
            [(finding.code, finding.path) for finding in findings],
            [("private_key", "safe.payload!target.txt")],
        )

    def test_finding_order_is_path_line_then_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z-link").symlink_to(root / "missing")
            (root / "a.txt").write_text(
                private_key_header() + " " + home_path() + "\n",
                encoding="utf-8",
            )
            findings = scan_path(root)

        self.assertEqual(
            [(finding.path, finding.line, finding.code) for finding in findings],
            [
                ("a.txt", 1, "absolute_home_path"),
                ("a.txt", 1, "private_key"),
                ("z-link", None, "symlink_entry"),
            ],
        )

    def test_cli_scans_multiple_paths_and_never_echoes_denied_payload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "z.txt"
            second = root / "a.txt"
            denied = "Synthetic " + "Cedar Group"
            first.write_text(denied + "\n", encoding="utf-8")
            second.write_text(home_path() + "\n", encoding="utf-8")
            denylist = root / "deny.txt"
            denylist.write_text("\n" + denied + "\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    "--denylist",
                    str(denylist),
                    str(first),
                    str(second),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertNotIn(denied, completed.stdout)
        self.assertNotIn("private-vault", completed.stdout)
        lines = completed.stdout.splitlines()
        self.assertIn("denied_term", lines[0])
        self.assertIn("absolute_home_path", lines[1])

    def test_cli_never_echoes_placeholder_conflicting_terms(self) -> None:
        for denied in ("redacted", "act"):
            with self.subTest(denied=denied), TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / f"{denied}.txt"
                target.write_text("safe\n", encoding="utf-8")
                denylist = root / "denylist.txt"
                denylist.write_text(denied + "\n", encoding="utf-8")

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).parents[1] / "scripts/check_public.py"),
                        "--denylist",
                        str(denylist),
                        str(target),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stderr, "")
                self.assertIn("denied_term", completed.stdout)
                self.assertNotIn(denied, completed.stdout)
                self.assertNotIn(denied, completed.stderr)

    def test_cli_sanitizes_terms_in_finding_code_and_message(self) -> None:
        for denied in ("denied", "term", "detected"):
            with self.subTest(denied=denied), TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "finding.txt"
                target.write_text(denied + "\n", encoding="utf-8")
                denylist = root / "denylist.txt"
                denylist.write_text(denied + "\n", encoding="utf-8")

                completed = run_public_cli(
                    "--denylist",
                    denylist,
                    target,
                )

                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stderr, "")
                self.assertNotEqual(completed.stdout, "")
                self.assertNotIn(denied, completed.stdout)

    def test_cli_sanitizes_multi_input_prefix_and_numeric_locations(self) -> None:
        cases = (
            ("input-prefix", "input", 1, 1),
            ("input-index", "2", 2, 1),
            ("line-number", "7", 1, 7),
        )
        for label, denied, selected_index, line_number in cases:
            with self.subTest(case=label), TemporaryDirectory() as directory:
                root = Path(directory)
                targets = [root / "first.txt", root / "second.txt"]
                for target in targets:
                    target.write_text("safe\n", encoding="utf-8")
                targets[selected_index - 1].write_text(
                    "safe\n" * (line_number - 1) + private_key_header() + "\n",
                    encoding="utf-8",
                )
                denylist = root / "denylist.txt"
                denylist.write_text(denied + "\n", encoding="utf-8")

                completed = run_public_cli(
                    "--denylist",
                    denylist,
                    *targets,
                )

                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stderr, "")
                self.assertNotEqual(completed.stdout, "")
                self.assertNotIn(denied, completed.stdout)

    def test_cli_sanitizes_terms_spanning_rendered_components(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "finding.txt"
            target.write_text(private_key_header() + "\n", encoding="utf-8")
            denied = "txt:1"
            denylist = root / "denylist.txt"
            denylist.write_text(denied + "\n", encoding="utf-8")

            completed = run_public_cli(
                "--denylist",
                denylist,
                target,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertNotEqual(completed.stdout, "")
        self.assertNotIn(denied, completed.stdout)

    def test_cli_suppresses_line_if_redaction_creates_another_denied_term(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "unsafe\x1b.txt"
            target.write_text("denied\n", encoding="utf-8")
            denied_terms = ("redacted", "denied")
            denylist = root / "denylist.txt"
            denylist.write_text("\n".join(denied_terms) + "\n", encoding="utf-8")

            completed = run_public_cli(
                "--denylist",
                denylist,
                target,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "")
        for denied in denied_terms:
            self.assertNotIn(denied, completed.stdout)
            self.assertNotIn(denied, completed.stderr)
        self.assertNotIn("\x1b", completed.stdout)
        self.assertNotIn("\x1b", completed.stderr)

    def test_cli_sanitizes_generic_failure_output_with_denylist(self) -> None:
        cases = (
            (("failed",), "public scan [redacted]\n"),
            (("redacted", "failed"), ""),
        )
        for denied_terms, expected_stderr in cases:
            with self.subTest(denied_terms=denied_terms), TemporaryDirectory() as directory:
                root = Path(directory)
                denylist = root / "denylist.txt"
                denylist.write_text("\n".join(denied_terms) + "\n", encoding="utf-8")

                completed = run_public_cli(
                    "--denylist",
                    denylist,
                    root / "missing.txt",
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertEqual(completed.stderr, expected_stderr)
                for denied in denied_terms:
                    self.assertNotIn(denied, completed.stderr)

    def test_cli_safe_ordinary_finding_remains_readable(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "ordinary.txt"
            target.write_text(private_key_header() + "\n", encoding="utf-8")

            completed = run_public_cli(target)

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(
            completed.stdout,
            "ordinary.txt:1: private_key: private-key header detected\n",
        )

    def test_cli_bare_option_like_real_filename_parse_error_is_silent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            denied = "unsafe-marker"
            filename = f"--{denied}-\x1b.txt"
            (root / filename).write_text(
                private_key_header() + "\n",
                encoding="utf-8",
            )
            denylist = root / "denylist.txt"
            denylist.write_text(denied + "\n", encoding="utf-8")

            completed = run_public_cli(
                "--denylist",
                denylist.name,
                filename,
                cwd=root,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "")

    def test_cli_malformed_options_are_silent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            denylist = root / "denylist.txt"
            denylist.write_text("unsafe-marker\n", encoding="utf-8")
            cases = (
                (
                    "unknown-option",
                    ("--denylist", denylist, "--unsafe-marker-\x1b"),
                ),
                ("missing-denylist-value", ("--denylist",)),
            )
            for label, arguments in cases:
                with self.subTest(case=label):
                    completed = run_public_cli(*arguments, cwd=root)

                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(completed.stderr, "")

    def test_cli_help_uses_fixed_safe_program_name(self) -> None:
        unsafe_prog = "unsafe-marker-\x1b"

        completed = run_public_main_with_argv0(unsafe_prog, "--help")

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertIn("usage: check_public.py", completed.stdout)
        self.assertNotIn("unsafe-marker", completed.stdout)
        self.assertNotIn("\x1b", completed.stdout)

    def test_cli_short_and_long_help_are_useful(self) -> None:
        for option in ("-h", "--help"):
            with self.subTest(option=option):
                completed = run_public_cli(option)

                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stderr, "")
                self.assertIn("usage: check_public.py", completed.stdout)
                self.assertIn("--denylist", completed.stdout)
                self.assertIn("-h, --help", completed.stdout)

    def test_cli_help_sanitizes_denylist_collisions(self) -> None:
        cases = (
            (("usage",), "[redacted]: check_public.py"),
            (("redacted", "usage"), None),
        )
        for denied_terms, expected_fragment in cases:
            with self.subTest(denied_terms=denied_terms), TemporaryDirectory() as directory:
                root = Path(directory)
                denylist = root / "denylist.txt"
                denylist.write_text("\n".join(denied_terms) + "\n", encoding="utf-8")

                completed = run_public_cli(
                    "--denylist",
                    denylist,
                    "--help",
                )

                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stderr, "")
                self.assertNotEqual(completed.stdout, "")
                for denied in denied_terms:
                    self.assertNotIn(denied, completed.stdout)
                if expected_fragment is not None:
                    self.assertIn(expected_fragment, completed.stdout)

    def test_cli_help_denylist_preload_failure_is_silent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.txt"
            invalid.write_bytes(b"\xff")
            for label, denylist in (
                ("missing", root / "missing.txt"),
                ("invalid-utf8", invalid),
            ):
                with self.subTest(case=label):
                    completed = run_public_cli(
                        "--denylist",
                        denylist,
                        "--help",
                    )

                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(completed.stderr, "")

    def test_cli_double_dash_scans_and_sanitizes_option_like_filename(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            denied = "unsafe-marker"
            filename = f"--{denied}-\x1b.txt"
            (root / filename).write_text(
                private_key_header() + "\n",
                encoding="utf-8",
            )
            denylist = root / "denylist.txt"
            denylist.write_text(denied + "\n", encoding="utf-8")

            completed = run_public_cli(
                "--denylist",
                denylist.name,
                "--",
                filename,
                cwd=root,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertNotEqual(completed.stdout, "")
        self.assertIn("denied_term", completed.stdout)
        self.assertIn("private_key", completed.stdout)
        self.assertIn(r"\u001b", completed.stdout)
        self.assertNotIn(denied, completed.stdout)
        self.assertNotIn("\x1b", completed.stdout)

    def test_cli_disambiguates_same_basename_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            left = base / "left/same.txt"
            right = base / "right/same.txt"
            left.parent.mkdir()
            right.parent.mkdir()
            left.write_text(home_path() + "\n", encoding="utf-8")
            right.write_text(home_path() + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    str(left),
                    str(right),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 1)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("input-1/same.txt", lines[0])
        self.assertIn("input-2/same.txt", lines[1])
        self.assertNotIn(str(base), completed.stdout)

    def test_cli_disambiguates_same_basename_directory_trees(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            left = base / "left/same"
            right = base / "right/same"
            left.mkdir(parents=True)
            right.mkdir(parents=True)
            (left / "nested.txt").write_text(home_path() + "\n", encoding="utf-8")
            (right / "nested.txt").write_text(home_path() + "\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    str(left),
                    str(right),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 1)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("input-1/nested.txt", lines[0])
        self.assertIn("input-2/nested.txt", lines[1])
        self.assertNotIn(str(base), completed.stdout)

    def test_cli_archive_read_error_is_generic_and_exit_two(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "damaged.data"
            with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("payload.txt", "synthetic payload\n")
            damage_first_zip_member(artifact)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    str(artifact),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "public scan failed\n")

    def test_cli_damaged_archive_structure_is_generic_and_exit_two(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            zip_path = root / "truncated.data"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("payload.txt", credential_line() + "\n")
            truncate_zip_end_record(zip_path)

            tar_path = root / "damaged.payload"
            payload = (credential_line() + "\n").encode()
            with tarfile.open(tar_path, "w") as archive:
                info = tarfile.TarInfo("payload.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            damage_tar_header_checksum(tar_path)

            for artifact in (zip_path, tar_path):
                with self.subTest(kind=artifact.suffix):
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).parents[1] / "scripts/check_public.py"),
                            str(artifact),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(completed.stdout, "")
                    self.assertEqual(completed.stderr, "public scan failed\n")

    def test_cli_damaged_compressed_tar_is_generic_and_exit_two(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "damaged.data"
            payload = (credential_line() + "\n").encode()
            with tarfile.open(artifact, "w:gz") as archive:
                info = tarfile.TarInfo("payload.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            damage_compressed_tar_header_checksum(artifact, "gzip")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    str(artifact),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "public scan failed\n")

    def test_cli_central_directory_zip_error_is_generic_and_exit_two(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "central.data"
            artifact.write_bytes(b"PK\x01\x02" + b"\x00" * 42)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                    str(artifact),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "public scan failed\n")

    def test_scanner_cannot_follow_file_swap_to_symlink(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "scan"
            root.mkdir()
            selected = root / "item.txt"
            selected.write_text("selected\n", encoding="utf-8")
            outside = base / "outside.txt"
            outside.write_text(home_path() + "\n", encoding="utf-8")
            original_read_bytes = Path.read_bytes
            original_open = os.open
            swapped = False

            def swap() -> None:
                nonlocal swapped
                if not swapped:
                    selected.unlink()
                    selected.symlink_to(outside)
                    swapped = True

            def pathname_read(path: Path) -> bytes:
                if path == selected:
                    swap()
                return original_read_bytes(path)

            def descriptor_open(file: object, flags: int, *args: object, **kwargs: object) -> int:
                if file == selected.name and kwargs.get("dir_fd") is not None:
                    swap()
                return original_open(file, flags, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch.object(Path, "read_bytes", autospec=True, side_effect=pathname_read),
                patch("scripts.check_public.os.open", side_effect=descriptor_open),
                self.assertRaisesRegex(RuntimeError, "public scan failed"),
            ):
                scan_path(root)

    def test_scanner_fails_closed_on_directory_component_swap(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "scan"
            nested = root / "nested"
            nested.mkdir(parents=True)
            selected = nested / "item.txt"
            selected.write_text("selected\n", encoding="utf-8")
            outside = base / "outside"
            outside.mkdir()
            (outside / "item.txt").write_text(home_path() + "\n", encoding="utf-8")
            parked = root / "original"
            original_read_bytes = Path.read_bytes
            original_open = os.open
            swapped = False

            def swap() -> None:
                nonlocal swapped
                if not swapped:
                    nested.rename(parked)
                    nested.symlink_to(outside, target_is_directory=True)
                    swapped = True

            def pathname_read(path: Path) -> bytes:
                if path == selected:
                    swap()
                return original_read_bytes(path)

            def descriptor_open(file: object, flags: int, *args: object, **kwargs: object) -> int:
                if file == nested.name and kwargs.get("dir_fd") is not None:
                    swap()
                return original_open(file, flags, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch.object(Path, "read_bytes", autospec=True, side_effect=pathname_read),
                patch("scripts.check_public.os.open", side_effect=descriptor_open),
                self.assertRaisesRegex(RuntimeError, "public scan failed"),
            ):
                scan_path(root)

    def test_cli_defaults_to_current_directory_and_clean_input_exits_zero(self) -> None:
        with TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/check_public.py"),
                ],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr, "")

    def test_repository_sources_are_clean(self) -> None:
        self.assertEqual(scan_path(Path(".")), [])

    def test_runtime_has_no_network_client_imports(self) -> None:
        forbidden = {"aiohttp", "ftplib", "http", "requests", "smtplib", "socket", "urllib"}
        imported: set[str] = set()
        for path in Path("src/threadroot").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
        self.assertEqual(imported & forbidden, set())

    def test_runtime_dependency_list_is_empty(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["dependencies"], [])


if __name__ == "__main__":
    unittest.main()
