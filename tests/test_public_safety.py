from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import io
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

from scripts.check_public import Finding, scan_path


def private_key_header() -> str:
    return "-----BEGIN " + "PRIVATE KEY-----"


def home_path() -> str:
    return "/" + "Users/example/private-vault"


def credential_line() -> str:
    return "api" + "_key = synthetic-value"


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


class PublicSafetyTests(unittest.TestCase):
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
            [("denied_term", 2)],
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

    def test_crc_damaged_zip_member_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / "damaged.data"
            with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("payload.txt", "synthetic payload\n")
            damage_first_zip_member(artifact)
            self.assertTrue(zipfile.is_zipfile(artifact))

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
