import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from threadroot import __version__
from threadroot.cli import execute, main, render_human, render_json
from threadroot.config import config_text
from threadroot.operations import run_init
from threadroot.results import Change, CommandResult, ExitCode, Issue


class VersionTests(unittest.TestCase):
    def test_version(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), f"threadroot {__version__}\n")


class CommandLineTests(unittest.TestCase):
    def call(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def make_vault(self, root: Path) -> Path:
        result = run_init(root, True, False, {}, root.parent / "home")
        self.assertTrue(result.ok)
        return root.resolve()

    def doctor_args(self, vault: str | None = None) -> object:
        return type("Args", (), {"command": "doctor", "vault": vault, "json": True})()

    def test_init_json_preview_is_one_compact_sorted_object(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            code, stdout, stderr = self.call(["init", "--vault", str(vault), "--json"])
            payload = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(stdout.count("\n"), 1)
            self.assertEqual(
                stdout.rstrip("\n"),
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            self.assertEqual(payload["command"], "init")
            self.assertFalse(payload["applied"])
            self.assertFalse(vault.exists())

    def test_doctor_missing_marker_returns_config_exit(self) -> None:
        with TemporaryDirectory() as directory:
            code, stdout, stderr = self.call(["doctor", "--vault", directory, "--json"])
            self.assertEqual(code, 3)
            self.assertEqual(stderr, "")
            self.assertFalse(json.loads(stdout)["ok"])

    def test_doctor_rejects_apply_and_set_default_as_usage(self) -> None:
        with TemporaryDirectory() as directory:
            for unsupported in ("--apply", "--set-default"):
                with self.subTest(unsupported=unsupported):
                    code, stdout, stderr = self.call(["doctor", "--vault", directory, unsupported])
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn("usage.invalid", stderr)

    def test_abbreviated_and_unknown_flags_are_usage_errors(self) -> None:
        with TemporaryDirectory() as directory:
            for unsupported in ("--va", "--unknown"):
                with self.subTest(unsupported=unsupported):
                    code, stdout, stderr = self.call(["doctor", unsupported, directory])
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn("usage.invalid", stderr)

    def test_missing_and_unknown_commands_are_usage_errors(self) -> None:
        for argv in ([], ["migrate"]):
            with self.subTest(argv=argv):
                code, stdout, stderr = self.call(argv)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("usage.invalid", stderr)

    def test_explicit_vault_wins_over_environment(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            explicit = self.make_vault(base / "explicit")
            environment = self.make_vault(base / "environment")
            result = execute(
                self.doctor_args(str(explicit)),
                cwd=base,
                environ={"SECOND_BRAIN_ROOT": str(environment)},
                home=base / "home",
            )
            self.assertEqual(result.vault, str(explicit))

    def test_environment_wins_over_upward_marker(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            upward = self.make_vault(base / "upward")
            nested = upward / "work"
            nested.mkdir()
            environment = self.make_vault(base / "environment")
            result = execute(
                self.doctor_args(),
                cwd=nested,
                environ={"SECOND_BRAIN_ROOT": str(environment)},
                home=base / "home",
            )
            self.assertEqual(result.vault, str(environment))

    def test_upward_marker_wins_over_default_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            upward = self.make_vault(base / "upward")
            nested = upward / "work"
            nested.mkdir()
            fallback = self.make_vault(base / "fallback")
            home = base / "home"
            pointer = home / ".config/threadroot/config.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_text(json.dumps({"default_vault": str(fallback)}), encoding="utf-8")
            result = execute(self.doctor_args(), cwd=nested, environ={}, home=home)
            self.assertEqual(result.vault, str(upward))

    def test_default_pointer_is_fallback(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            fallback = self.make_vault(base / "fallback")
            home = base / "home"
            pointer = home / ".config/threadroot/config.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_text(json.dumps({"default_vault": str(fallback)}), encoding="utf-8")
            result = execute(self.doctor_args(), cwd=base, environ={}, home=home)
            self.assertEqual(result.vault, str(fallback))

    def test_set_default_preview_is_pure_and_apply_writes_after_init(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            config_home = base / "machine-config"
            pointer = config_home / "threadroot/config.json"
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_home)}, clear=False):
                preview_code, preview_stdout, _ = self.call(
                    ["init", "--vault", str(vault), "--set-default", "--json"]
                )
                self.assertEqual(preview_code, 0)
                self.assertFalse(json.loads(preview_stdout)["applied"])
                self.assertFalse(vault.exists())
                self.assertFalse(pointer.exists())

                apply_code, apply_stdout, _ = self.call(
                    ["init", "--vault", str(vault), "--apply", "--set-default", "--json"]
                )
            self.assertEqual(apply_code, 0)
            self.assertTrue(json.loads(apply_stdout)["applied"])
            self.assertTrue((vault / ".second-brain/config.json").is_file())
            self.assertEqual(
                json.loads(pointer.read_text(encoding="utf-8")),
                {"default_vault": str(vault.resolve())},
            )

    def test_operation_exit_codes_are_preserved(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)

            missing_marker = base / "missing-marker"
            missing_marker.mkdir()
            config_code, _, _ = self.call(["doctor", "--vault", str(missing_marker), "--json"])

            unsafe = base / "unsafe"
            outside = base / "outside"
            unsafe.mkdir()
            outside.mkdir()
            for relative in ("wiki/projects", "wiki/tech", "wiki/reviews"):
                (unsafe / relative).mkdir(parents=True)
            (unsafe / "daily").symlink_to(outside, target_is_directory=True)
            marker = unsafe / ".second-brain/config.json"
            marker.parent.mkdir()
            marker.write_text(config_text(), encoding="utf-8")
            unsafe_code, _, _ = self.call(["doctor", "--vault", str(unsafe), "--json"])

            conflict = base / "conflict"
            conflict.mkdir()
            (conflict / "keep.md").write_text("synthetic\n", encoding="utf-8")
            conflict_code, _, _ = self.call(["init", "--vault", str(conflict), "--apply", "--json"])

            io_vault = base / "io-vault"
            blocked_config = base / "blocked-config"
            blocked_config.write_text("not a directory\n", encoding="utf-8")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(blocked_config)}, clear=False):
                io_code, _, _ = self.call(
                    ["init", "--vault", str(io_vault), "--apply", "--set-default", "--json"]
                )

            self.assertEqual((config_code, unsafe_code, conflict_code, io_code), (3, 4, 5, 6))

    def test_human_output_uses_stdout_for_success_and_stderr_for_error(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            preview = base / "preview"
            code, stdout, stderr = self.call(["init", "--vault", str(preview)])
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(stdout.startswith(f"OK init preview {preview.resolve()}\n"))
            self.assertIn("[planned] create_directory", stdout)

            invalid = base / "invalid"
            invalid.mkdir()
            code, stdout, stderr = self.call(["doctor", "--vault", str(invalid)])
            self.assertEqual(code, 3)
            self.assertEqual(stdout, "")
            self.assertTrue(stderr.startswith(f"ERROR doctor {invalid.resolve()}\n"))
            self.assertIn("ERROR config.invalid:", stderr)

    def test_renderers_do_not_include_exit_code_and_format_optional_issue_path(self) -> None:
        result = CommandResult(
            ok=False,
            command="doctor",
            applied=False,
            vault="/synthetic/vault",
            changes=(Change("create_directory", "daily", "unexecuted"),),
            issues=(
                Issue("error", "config.invalid", "Invalid config"),
                Issue("info", "git.not_found", "Git metadata was not found.", ".git"),
            ),
            exit_code=ExitCode.CONFIG,
        )
        self.assertNotIn("exit_code", json.loads(render_json(result)))
        self.assertEqual(
            render_human(result),
            "ERROR doctor /synthetic/vault\n"
            "[unexecuted] create_directory daily\n"
            "ERROR config.invalid: Invalid config\n"
            "INFO git.not_found: Git metadata was not found. (.git)",
        )

    def test_module_entrypoint_dispatches_real_preview(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
            completed = subprocess.run(
                [sys.executable, "-m", "threadroot", "init", "--vault", str(vault), "--json"],
                cwd=Path(__file__).parents[1],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(json.loads(completed.stdout)["command"], "init")
            self.assertFalse(vault.exists())
