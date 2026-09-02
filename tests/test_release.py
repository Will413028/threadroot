from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_release
from scripts.build_release import build_archive


class ReleaseArchiveTests(unittest.TestCase):
    def test_host_archives_have_exact_native_manifest_and_shared_content(self) -> None:
        common_files = {
            "LICENSE",
            "README.md",
            ".claude-plugin/marketplace.json",
            *(
                path.as_posix()
                for root in (Path("skills"), Path("templates"))
                for path in root.rglob("*")
                if path.is_file()
            ),
        }
        with TemporaryDirectory() as directory:
            output = Path(directory)
            claude = build_archive("claude", output)
            codex = build_archive("codex", output)

            with zipfile.ZipFile(claude) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    common_files | {".claude-plugin/plugin.json"},
                )
                self.assertNotIn(".codex-plugin/plugin.json", names)

            with zipfile.ZipFile(codex) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    common_files | {".codex-plugin/plugin.json"},
                )
                self.assertNotIn(".claude-plugin/plugin.json", names)

    def test_archive_metadata_is_canonical_and_members_are_sorted(self) -> None:
        with TemporaryDirectory() as directory:
            artifact = build_archive("codex", Path(directory))
            raw_archive = artifact.read_bytes()
            with zipfile.ZipFile(artifact) as archive:
                infos = archive.infolist()
                archive_comment = archive.comment

        self.assertEqual(
            [info.filename for info in infos],
            sorted(info.filename for info in infos),
        )
        self.assertTrue(infos)
        self.assertEqual(archive_comment, b"")
        for info in infos:
            with self.subTest(member=info.filename):
                self.assertFalse(info.is_dir())
                self.assertFalse(Path(info.filename).is_absolute())
                self.assertNotIn("..", Path(info.filename).parts)
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.create_system, 3)
                self.assertEqual(info.flag_bits & 0x800, 0x800)
                self.assertEqual(info.external_attr >> 16, stat.S_IFREG | 0o644)
                self.assertEqual(info.extra, b"")
                self.assertEqual(info.comment, b"")
                self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)
                local_flags = int.from_bytes(
                    raw_archive[info.header_offset + 6 : info.header_offset + 8],
                    "little",
                )
                self.assertEqual(local_flags & 0x800, 0x800)

    def test_repeated_builds_are_byte_identical(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                with TemporaryDirectory() as first, TemporaryDirectory() as second:
                    one = build_archive(host, Path(first)).read_bytes()
                    two = build_archive(host, Path(second)).read_bytes()
                self.assertEqual(one, two)

    def test_build_uses_repository_next_to_script_not_caller_directory(self) -> None:
        original_cwd = Path.cwd()
        with TemporaryDirectory() as caller, TemporaryDirectory() as output:
            try:
                os.chdir(caller)
                artifact = build_archive("claude", Path(output))
            finally:
                os.chdir(original_cwd)

        self.assertEqual(artifact.name, "threadroot-claude-0.1.0.zip")

    def test_invalid_host_creates_no_output(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, "unsupported host"):
                build_archive("other", output)
            self.assertEqual(list(output.iterdir()), [])

    def test_selected_symlink_is_rejected_without_reading_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (root / "LICENSE").write_text("synthetic\n", encoding="utf-8")
            (root / "README.md").write_text("synthetic\n", encoding="utf-8")
            for relative in (
                ".claude-plugin/plugin.json",
                ".claude-plugin/marketplace.json",
                ".codex-plugin/plugin.json",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("{}\n", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("must not be packaged\n", encoding="utf-8")
            (root / "skills").symlink_to(outside)
            (root / "templates").mkdir()

            with patch.object(build_release, "REPOSITORY_ROOT", root):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    build_archive("codex", root / "dist")

            self.assertFalse((root / "dist").exists())

    def test_nested_selected_symlink_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[project]\nversion = "0.1.0"\n', encoding="utf-8"
            )
            for relative in (
                "LICENSE",
                "README.md",
                ".claude-plugin/plugin.json",
                ".claude-plugin/marketplace.json",
                ".codex-plugin/plugin.json",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("synthetic\n", encoding="utf-8")
            (root / "skills/nested").mkdir(parents=True)
            (root / "templates").mkdir()
            outside = root / "outside.txt"
            outside.write_text("must not be packaged\n", encoding="utf-8")
            (root / "skills/nested/link.txt").symlink_to(outside)

            with patch.object(build_release, "REPOSITORY_ROOT", root):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    build_archive("claude", root / "dist")

            self.assertFalse((root / "dist").exists())

    def test_cli_builds_both_versioned_archives(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "scripts/build_release.py"),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "threadroot-claude-0.1.0.zip",
                    "threadroot-codex-0.1.0.zip",
                },
            )


if __name__ == "__main__":
    unittest.main()
