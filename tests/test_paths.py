import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from threadroot.paths import (
    MARKER_RELATIVE,
    default_pointer_path,
    ensure_within,
    resolve_vault,
)
from threadroot.results import ExitCode, ThreadrootError


class PathTests(unittest.TestCase):
    def test_explicit_path_wins_over_environment(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            explicit = base / "explicit"
            env_root = base / "environment"
            resolved = resolve_vault(
                explicit=explicit,
                cwd=base,
                environ={"SECOND_BRAIN_ROOT": str(env_root)},
                home=base / "home",
            )
            self.assertEqual(resolved, explicit.resolve())

    def test_relative_explicit_and_environment_use_injected_cwd(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            cwd = base / "cwd"
            cwd.mkdir()
            self.assertEqual(
                resolve_vault("relative", cwd, {}, base / "home"),
                (cwd / "relative").resolve(),
            )
            self.assertEqual(
                resolve_vault(None, cwd, {"SECOND_BRAIN_ROOT": "from-env"}, base / "home"),
                (cwd / "from-env").resolve(),
            )

    def test_environment_wins_over_upward_marker(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            nested = vault / "work"
            nested.mkdir(parents=True)
            marker = vault / MARKER_RELATIVE
            marker.parent.mkdir()
            marker.write_text("{}\n", encoding="utf-8")
            self.assertEqual(
                resolve_vault(None, nested, {"SECOND_BRAIN_ROOT": "environment"}, base / "home"),
                (nested / "environment").resolve(),
            )

    def test_upward_marker_wins_over_default_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            nested = vault / "work" / "repo"
            nested.mkdir(parents=True)
            marker = vault / MARKER_RELATIVE
            marker.parent.mkdir()
            marker.write_text("{}\n", encoding="utf-8")
            pointer = base / "home" / ".config" / "threadroot" / "config.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_text(json.dumps({"default_vault": str(base / "other")}), encoding="utf-8")
            self.assertEqual(resolve_vault(None, nested, {}, base / "home"), vault.resolve())

    def test_valid_pointer_is_used_when_higher_sources_absent(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            pointer = home / ".config" / "threadroot" / "config.json"
            pointer.parent.mkdir(parents=True)
            target = base / "vault"
            pointer.write_text(json.dumps({"default_vault": str(target)}), encoding="utf-8")
            self.assertEqual(resolve_vault(None, base, {}, home), target.resolve())

    def test_malformed_duplicate_and_relative_pointers_fail_without_fallthrough(self) -> None:
        documents = ("{", '{"default_vault": "/one", "default_vault": "/two"}', '{"default_vault": "relative"}')
        for document in documents:
            with self.subTest(document=document), TemporaryDirectory() as directory:
                base = Path(directory)
                home = base / "home"
                pointer = home / ".config" / "threadroot" / "config.json"
                pointer.parent.mkdir(parents=True)
                pointer.write_text(document, encoding="utf-8")
                with self.assertRaises(ThreadrootError) as raised:
                    resolve_vault(None, base, {}, home)
                self.assertEqual(raised.exception.exit_code, ExitCode.CONFIG)
                self.assertEqual(raised.exception.code, "config.invalid")

    def test_missing_resolution_is_an_error(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(ThreadrootError) as raised:
                resolve_vault(None, base, {}, base / "home")
            self.assertEqual(raised.exception.exit_code, ExitCode.CONFIG)
            self.assertEqual(raised.exception.code, "vault.unresolved")
            self.assertEqual(raised.exception.message, "Pass --vault to select a vault.")

    def test_relative_xdg_config_home_is_invalid(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(ThreadrootError) as raised:
                default_pointer_path({"XDG_CONFIG_HOME": "relative"}, base / "home")
            self.assertEqual(raised.exception.exit_code, ExitCode.CONFIG)
            self.assertEqual(raised.exception.code, "config.invalid")

    def test_parent_and_absolute_paths_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ("../outside", "/tmp/outside"):
                with self.subTest(value=value), self.assertRaises(ThreadrootError) as raised:
                    ensure_within(root, value)
                self.assertEqual(raised.exception.exit_code, ExitCode.UNSAFE_PATH)
