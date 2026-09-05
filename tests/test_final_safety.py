import json
import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from threadroot.cli import build_parser, execute, render_json
from threadroot.config import config_text, load_config
from threadroot.operations import run_init, run_adopt, run_doctor, write_default_pointer
from threadroot.paths import resolve_path, find_upward
from threadroot.results import ExitCode, ThreadrootError


class PathBoundaryTests(unittest.TestCase):
    def test_nul_configured_path_is_structured_unsafe(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".second-brain").mkdir()
            document = json.loads(config_text())
            document["paths"]["daily"] = "daily\x00bad"
            (root / ".second-brain/config.json").write_text(json.dumps(document))
            with self.assertRaises(ThreadrootError) as caught:
                load_config(root)
            self.assertEqual((caught.exception.exit_code, caught.exception.code),
                             (ExitCode.UNSAFE_PATH, "path.unsafe"))

    def test_secret_marker_is_rejected_before_open(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "secrets").mkdir()
            (root / "secrets/config.json").write_text(config_text())
            (root / ".second-brain").mkdir()
            (root / ".second-brain/config.json").symlink_to(root / "secrets/config.json")
            with patch.object(Path, "read_text", side_effect=AssertionError("content opened")) as read:
                with self.assertRaises(ThreadrootError) as caught:
                    load_config(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)
                read.assert_not_called()

    def test_init_keeps_unsafe_exit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".second-brain").mkdir()
            document = json.loads(config_text())
            document["paths"]["daily"] = "../outside"
            (root / ".second-brain/config.json").write_text(json.dumps(document))
            result = run_init(root, False, False, {}, root / "unused-home")
            self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)

    def test_init_preview_permission_failure_is_structured(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(Path, "iterdir", side_effect=PermissionError("synthetic I/O")):
                result = run_init(root, False, False, {}, root / "unused-home")
            self.assertEqual((result.exit_code, result.issues[0].code),
                             (ExitCode.IO_OR_DRIFT, "filesystem.failed"))
            self.assertFalse(result.applied)
            self.assertEqual(result.changes, ())

    def test_resolution_io_failure_is_structured_at_api_and_cli(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            failure = OSError(errno.EIO, "synthetic resolution failure", str(root / "opaque"))
            with patch.object(Path, "resolve", side_effect=failure):
                with self.assertRaises(ThreadrootError) as caught:
                    resolve_path(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.IO_OR_DRIFT)
                args = build_parser().parse_args(["doctor", "--vault", str(root), "--json"])
                result = execute(args, root, {}, root)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertNotIn(str(root), json.dumps(result.to_dict()["issues"]))
            self.assertNotIn("Traceback", render_json(result))

    def test_secret_configured_paths_are_rejected(self):
        for relative in ("secrets/daily", "wiki/secrets/daily", ".second-brain/content"):
            with self.subTest(relative=relative), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                (root / ".second-brain").mkdir()
                marker = root / ".second-brain/config.json"
                document = json.loads(config_text())
                document["paths"]["daily"] = relative
                marker.write_text(json.dumps(document))
                real_read = Path.read_text
                def safe_read(path, *args, **kwargs):
                    self.assertEqual(path, marker)
                    return real_read(path, *args, **kwargs)
                with patch.object(Path, "read_text", safe_read):
                    with self.assertRaises(ThreadrootError) as caught:
                        load_config(root)
                    self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)

    def test_upward_secret_marker_is_never_opened(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "secrets").mkdir()
            (root / "secrets/config.json").write_text(config_text())
            (root / ".second-brain").symlink_to(root / "secrets", target_is_directory=True)
            with patch.object(Path, "read_text", side_effect=AssertionError("content opened")) as read:
                with self.assertRaises(ThreadrootError) as caught:
                    find_upward(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)
                read.assert_not_called()

    def test_path_probe_io_is_not_swallowed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(Path, "resolve", return_value=root), patch.object(
                Path, "stat", side_effect=OSError(errno.EIO, "synthetic probe")
            ):
                with self.assertRaises(ThreadrootError) as caught:
                    resolve_path(root)
                self.assertEqual(caught.exception.exit_code, ExitCode.IO_OR_DRIFT)

    def test_cli_invalid_literal_is_private(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for command in ("init", "adopt", "doctor"):
                with self.subTest(command=command):
                    args = build_parser().parse_args([command, "--vault", "bad\x00root", "--json"])
                    result = execute(args, root, {}, root)
                    self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                    issues = json.dumps(result.to_dict()["issues"])
                    self.assertNotIn(str(root), issues)
                    self.assertNotIn("bad", issues)

    def test_configured_secret_symlink_and_component_negative_control(self):
        for secret in (True, False):
            with self.subTest(secret=secret), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                (root / ".second-brain").mkdir()
                destination = root / ("secrets" if secret else "daily-secrets")
                destination.mkdir()
                (root / "daily").symlink_to(destination, target_is_directory=True)
                (root / ".second-brain/config.json").write_text(config_text())
                if secret:
                    with self.assertRaises(ThreadrootError) as caught:
                        load_config(root)
                    self.assertEqual(caught.exception.exit_code, ExitCode.UNSAFE_PATH)
                else:
                    self.assertEqual(load_config(root).paths.daily, "daily")

    def test_direct_operation_resolution_errors_are_structured(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for command in ("init", "adopt", "doctor"):
                with self.subTest(command=command), patch.object(
                    Path, "resolve", side_effect=OSError(errno.EIO, "synthetic failure")
                ):
                    if command == "doctor":
                        result = run_doctor(root)
                    else:
                        operation = run_init if command == "init" else run_adopt
                        result = operation(root, False, False, {}, root)
                    self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)

    def test_usage_errors_do_not_echo_raw_arguments(self):
        with self.assertRaises(ThreadrootError) as caught:
            build_parser().parse_args(["doctor", "--unknown=/synthetic/private-argument"])
        self.assertEqual(caught.exception.exit_code, ExitCode.USAGE)
        self.assertNotIn("/synthetic/private-argument", str(caught.exception))

    def test_dot_content_root_does_not_crash(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".second-brain").mkdir()
            document = json.loads(config_text())
            document["paths"]["daily"] = "."
            (root / ".second-brain/config.json").write_text(json.dumps(document))
            self.assertEqual(load_config(root).paths.daily, ".")

    def test_direct_doctor_literal_and_inspection_failure_are_structured(self):
        result = run_doctor(Path("bad\x00root"))
        self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(Path, "exists", side_effect=PermissionError("synthetic inspection")):
                result = run_doctor(root)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
