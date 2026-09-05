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


DOCTOR_REMEDIATIONS = {
    "vault.unresolved": "Pass --vault to select an existing configured vault.",
    "vault.not_found": "Pass --vault for an existing vault or preview init for a new target.",
    "vault.not_directory": "Pass --vault for a directory.",
    "config.invalid": "Restore a readable schema-v1 .second-brain/config.json or preview adopt for a markerless vault.",
    "config.unsupported_version": "Use a compatible Threadroot version; do not rewrite the marker with this version.",
    "config.path_invalid": "Correct the configured paths to existing content directories and rerun doctor.",
    "path.unsafe": "Correct the path or symlink to stay inside the vault and outside secrets, then rerun doctor.",
    "path.not_found": "Restore the configured directory or correct its config path, then rerun doctor.",
    "path.not_directory": "Select a directory in the config and rerun doctor.",
    "path.not_readable": "Grant read access to the configured directory and rerun doctor.",
    "filesystem.failed": "Check filesystem availability and directory access, then rerun doctor.",
}


class DoctorRemediationTests(unittest.TestCase):
    def test_content_inspection_io_preserves_exit_six(self):
        from threadroot import operations
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "vault"
            self.assertTrue(run_init(root, True, False, {}, base / "home").ok)
            real_check = operations.ensure_outside_secrets
            def fail_content_check(vault, relative):
                if relative == "daily":
                    raise ThreadrootError(ExitCode.IO_OR_DRIFT, "filesystem.failed",
                                          "Synthetic inspection failure.")
                return real_check(vault, relative)
            before = {path.relative_to(base): path.lstat()
                      for path in [base, *base.rglob("*")]}
            with patch.object(operations, "ensure_outside_secrets", side_effect=fail_content_check):
                result = run_doctor(root)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertFalse(result.ok)
            self.assertFalse(result.applied)
            self.assertEqual(result.changes, ())
            self.assertEqual(result.issues[0].code, "filesystem.failed")
            self.assertTrue(result.issues[0].message.endswith(DOCTOR_REMEDIATIONS["filesystem.failed"]))
            self.assertEqual(before, {path.relative_to(base): path.lstat()
                                      for path in [base, *base.rglob("*")]})

    def test_every_error_has_concrete_remediation(self):
        for scenario in ("missing-root", "file-root", "missing-marker", "malformed",
                         "unknown-schema", "missing-directory", "file-directory", "unsafe"):
            with self.subTest(scenario=scenario), TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "vault"
                if scenario == "file-root":
                    root.write_text("synthetic")
                elif scenario == "missing-marker":
                    root.mkdir()
                elif scenario != "missing-root":
                    self.assertTrue(run_init(root, True, False, {}, base / "home").ok)
                    marker = root / ".second-brain/config.json"
                    if scenario == "malformed":
                        marker.write_text("{")
                    elif scenario in ("unknown-schema", "unsafe"):
                        document = json.loads(config_text())
                        if scenario == "unknown-schema":
                            document["schema_version"] = 2
                        else:
                            document["paths"]["daily"] = "../outside"
                        marker.write_text(json.dumps(document))
                    else:
                        (root / "daily").rmdir()
                        if scenario == "file-directory":
                            (root / "daily").write_text("synthetic")
                def metadata():
                    return {p.relative_to(base).as_posix():
                            (p.lstat().st_mode, p.lstat().st_mtime_ns,
                             os.readlink(p) if p.is_symlink() else None)
                            for p in [base, *base.rglob("*")]}
                before = metadata()
                with patch.object(Path, "mkdir") as mkdir, patch.object(Path, "touch") as touch, \
                     patch.object(Path, "write_text") as write, patch.object(Path, "unlink") as unlink, \
                     patch("threadroot.operations.os.replace") as replace:
                    result = run_doctor(root)
                self.assertEqual(metadata(), before)
                for operation in (mkdir, touch, write, unlink, replace):
                    operation.assert_not_called()
                self.assertFalse(result.ok)
                self.assertFalse(result.applied)
                self.assertEqual(result.changes, ())
                for issue in result.issues:
                    if issue.level == "error":
                        self.assertIn("Remediation: ", issue.message)
                        self.assertEqual(issue.message.split("Remediation: ", 1)[1],
                                         DOCTOR_REMEDIATIONS[issue.code])

    def test_io_remediation_keeps_exit_six_and_is_read_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root.lstat().st_mtime_ns
            with patch.object(Path, "resolve", side_effect=OSError(errno.EIO, "synthetic I/O")), \
                 patch.object(Path, "mkdir") as mkdir, patch.object(Path, "touch") as touch, \
                 patch.object(Path, "write_text") as write, patch.object(Path, "unlink") as unlink, \
                 patch("threadroot.operations.os.replace") as replace:
                result = run_doctor(root)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].message.split("Remediation: ", 1)[1],
                             DOCTOR_REMEDIATIONS["filesystem.failed"])
            for operation in (mkdir, touch, write, unlink, replace):
                operation.assert_not_called()
            self.assertEqual(root.lstat().st_mtime_ns, before)

    def test_unresolved_cli_doctor_has_remediation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            failure = ThreadrootError(ExitCode.CONFIG, "vault.unresolved", "Pass --vault.")
            with patch("threadroot.cli.resolve_vault", side_effect=failure):
                result = execute(build_parser().parse_args(["doctor", "--json"]), root, {}, root)
            self.assertEqual(result.exit_code, ExitCode.CONFIG)
            self.assertEqual(result.issues[0].message.split("Remediation: ", 1)[1],
                             DOCTOR_REMEDIATIONS["vault.unresolved"])

    def test_apparent_unreadability_and_all_issue_codes_are_read_only(self):
        import stat
        from threadroot import operations
        from threadroot.results import Issue
        decorate = getattr(operations, "_doctor_issue", None)
        self.assertTrue(callable(decorate), "doctor remediation decorator is required")
        for code, remediation in DOCTOR_REMEDIATIONS.items():
            issue = Issue("error", code, "Synthetic diagnosis.", "daily")
            self.assertEqual(decorate(issue).message, "Synthetic diagnosis. Remediation: " + remediation)
            self.assertEqual(decorate(decorate(issue)), decorate(issue))
        for level in ("warning", "info"):
            issue = Issue(level, "synthetic.non_error", "Unchanged.", ".")
            self.assertEqual(decorate(issue), issue)
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "vault"
            self.assertTrue(run_init(root, True, False, {}, base / "home").ok)
            def metadata():
                return {p.relative_to(root).as_posix():
                        (stat.S_IFMT(p.lstat().st_mode), p.lstat().st_mtime_ns,
                         os.readlink(p) if p.is_symlink() else None)
                        for p in [root, *root.rglob("*")]}
            for relative, expected in ((".second-brain/config.json", "config.invalid"),
                                       ("daily", "path.not_readable")):
                before = metadata()
                real_access = os.access
                def access(path, mode):
                    return False if Path(path) == root / relative and mode == os.R_OK else real_access(path, mode)
                with patch("threadroot.operations.os.access", side_effect=access), \
                     patch.object(Path, "mkdir") as mkdir, patch.object(Path, "touch") as touch, \
                     patch.object(Path, "write_text") as write, patch.object(Path, "unlink") as unlink, \
                     patch("threadroot.operations.os.replace") as replace:
                    result = run_doctor(root)
                errors = [issue for issue in result.issues if issue.level == "error"]
                self.assertEqual([issue.code for issue in errors], [expected])
                self.assertTrue(errors[0].message.endswith(DOCTOR_REMEDIATIONS[expected]))
                self.assertEqual(metadata(), before)
                for operation in (mkdir, touch, write, unlink, replace):
                    operation.assert_not_called()


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
            with self.subTest(uses_reserved_component=secret), TemporaryDirectory() as temporary:
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


class PointerSafetyTests(unittest.TestCase):
    def test_direct_and_parent_symlink_overlap_are_zero_write(self):
        for operation in (run_init, run_adopt):
            for apply in (False, True):
                for symlink_parent in (False, True):
                    with self.subTest(operation=operation.__name__, apply=apply,
                                      symlink_parent=symlink_parent), TemporaryDirectory() as temporary:
                        base = Path(temporary).resolve()
                        vault = base / "vault"
                        self.assertTrue(run_init(vault, True, False, {}, base / "home").ok)
                        (vault / "threadroot").mkdir()
                        protected = vault / "threadroot/config.json"
                        protected.write_bytes(b"synthetic vault content")
                        xdg = base / "xdg"
                        if symlink_parent:
                            xdg.mkdir()
                            (xdg / "threadroot").symlink_to(vault / "threadroot", target_is_directory=True)
                        else:
                            xdg = vault
                        before = protected.read_bytes(), protected.stat().st_mtime_ns
                        with patch("threadroot.operations.os.replace") as replace:
                            result = operation(vault, apply, True,
                                               {"XDG_CONFIG_HOME": str(xdg)}, base / "home")
                        self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                        self.assertFalse(result.applied)
                        self.assertEqual(result.changes, ())
                        replace.assert_not_called()
                        self.assertEqual(before, (protected.read_bytes(), protected.stat().st_mtime_ns))

    def test_replace_failure_preserves_old_pointer_and_cleans_only_owned_temp(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            vault.mkdir()
            pointer = base / "xdg/threadroot/config.json"
            pointer.parent.mkdir(parents=True)
            pointer.write_bytes(b'{"default_vault":"/synthetic/previous"}\n')
            sentinel = pointer.parent / "keep.tmp"
            sentinel.write_bytes(b"unrelated")
            before = pointer.read_bytes(), pointer.stat().st_mtime_ns
            with patch("threadroot.operations.os.replace", side_effect=OSError("synthetic replace")):
                with self.assertRaises(OSError):
                    write_default_pointer(vault, {"XDG_CONFIG_HOME": str(base / "xdg")}, base / "home")
            self.assertEqual(before, (pointer.read_bytes(), pointer.stat().st_mtime_ns))
            self.assertEqual({"config.json", "keep.tmp"}, {p.name for p in pointer.parent.iterdir()})
            self.assertEqual(sentinel.read_bytes(), b"unrelated")

    def test_initial_overlap_does_not_create_vault_or_pointer_parents(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            for apply in (False, True):
                result = run_init(vault, apply, True,
                                  {"XDG_CONFIG_HOME": str(vault)}, base / "home")
                self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                self.assertFalse(vault.exists())

    def test_pointer_destination_equal_to_vault_is_unsafe(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            (base / "xdg/threadroot").mkdir(parents=True)
            vault = base / "xdg/threadroot/config.json"
            result = run_init(vault, True, True,
                              {"XDG_CONFIG_HOME": str(base / "xdg")}, base / "home")
            self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
            self.assertFalse(vault.exists())

    def test_apply_revalidates_before_first_write(self):
        from threadroot import operations
        self.assertTrue(callable(getattr(operations, "validate_default_pointer", None)))
        for operation in (run_init, run_adopt):
            with self.subTest(operation=operation.__name__), TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                vault = base / "vault"
                if operation is run_adopt:
                    self.assertTrue(run_init(vault, True, False, {}, base / "home").ok)
                pointer = base / "xdg/threadroot/config.json"
                failure = ThreadrootError(ExitCode.UNSAFE_PATH, "path.unsafe", "Synthetic overlap.")
                with patch("threadroot.operations.validate_default_pointer", side_effect=[pointer, failure]), \
                     patch("threadroot.operations.apply_plan") as apply_plan:
                    result = operation(vault, True, True,
                                       {"XDG_CONFIG_HOME": str(base / "xdg")}, base / "home")
                self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                self.assertFalse(result.applied)
                apply_plan.assert_not_called()

    def test_writer_revalidates_before_mkdir_and_replace(self):
        from threadroot import operations
        self.assertTrue(callable(getattr(operations, "validate_default_pointer", None)))
        for stage in (1, 2, 3):
            with self.subTest(stage=stage), TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                vault = base / "vault"
                vault.mkdir()
                pointer = base / "xdg/threadroot/config.json"
                pointer.parent.mkdir(parents=True)
                pointer.write_bytes(b"synthetic previous pointer")
                failure = ThreadrootError(ExitCode.UNSAFE_PATH, "path.unsafe", "Synthetic overlap.")
                events = []
                real_mkdir = Path.mkdir
                def mkdir(path, *args, **kwargs):
                    events.append("mkdir")
                    return real_mkdir(path, *args, **kwargs)
                with patch("threadroot.operations.validate_default_pointer",
                           side_effect=[pointer] * (stage - 1) + [failure]), \
                     patch.object(Path, "mkdir", mkdir), patch("threadroot.operations.os.replace") as replace:
                    with self.assertRaises(ThreadrootError):
                        write_default_pointer(vault, {"XDG_CONFIG_HOME": str(base / "xdg")}, base / "home")
                replace.assert_not_called()
                self.assertEqual(events, [] if stage == 1 else ["mkdir"])
                self.assertEqual(pointer.read_bytes(), b"synthetic previous pointer")
                self.assertEqual(["config.json"], [p.name for p in pointer.parent.iterdir()])
