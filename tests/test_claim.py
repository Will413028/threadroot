import json
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from threadroot import operations
from threadroot.cli import build_parser, execute
from threadroot.config import config_text
from threadroot.results import ExitCode


class ClaimTests(unittest.TestCase):
    def vault(self, base):
        root = base / "vault"
        self.assertTrue(operations.run_init(root, True, False, {}, base / "home").ok)
        self.assertTrue(callable(getattr(operations, "run_claim", None)), "run_claim capability is required")
        return root

    def test_preview_and_apply_create_one_empty_regular_file(self):
        claim = getattr(operations, "run_claim", None)
        self.assertTrue(callable(claim), "run_claim capability is required")
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            self.assertTrue(operations.run_init(vault, True, False, {}, base / "home").ok)
            target = vault / "daily/2042-04-03.md"
            preview = claim(vault, "daily/2042-04-03.md", False)
            self.assertTrue(preview.ok)
            self.assertFalse(preview.applied)
            self.assertFalse(target.exists())
            self.assertEqual(preview.to_dict()["changes"], [{"action": "create_file",
                "path": "daily/2042-04-03.md", "status": "planned"}])
            result = claim(vault, "daily/2042-04-03.md", True)
            self.assertEqual(result.exit_code, ExitCode.OK)
            self.assertTrue(result.applied)
            self.assertEqual(target.read_bytes(), b"")
            self.assertTrue(stat.S_ISREG(target.lstat().st_mode))
            self.assertEqual(result.to_dict()["changes"][0]["status"], "completed")
            self.assertEqual(set(result.to_dict()),
                             {"ok", "command", "applied", "vault", "changes", "issues"})
            again = claim(vault, "daily/2042-04-03.md", True)
            self.assertEqual(again.exit_code, ExitCode.CONFLICT)

    def test_cli_claim_has_required_path_and_no_content_or_default_flag(self):
        parser = build_parser()
        args = parser.parse_args(["claim", "--path", "daily/2042-04-03.md", "--json"])
        self.assertEqual((args.command, args.path, args.apply),
                         ("claim", "daily/2042-04-03.md", False))
        from threadroot.results import ThreadrootError
        for suffix in ([], ["--path", "daily/a.md", "--set-default"],
                       ["--path", "daily/a.md", "--content", "synthetic"],
                       ["--pa", "daily/a.md"]):
            with self.subTest(suffix=suffix), self.assertRaises(ThreadrootError) as caught:
                parser.parse_args(["claim", *suffix])
            self.assertEqual(caught.exception.exit_code, ExitCode.USAGE)

    def test_apply_collision_preserves_competing_bytes(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            vault = base / "vault"
            self.assertTrue(operations.run_init(vault, True, False, {}, base / "home").ok)
            plan = operations.plan_claim(vault, "daily/2042-04-03.md")
            target = plan[0].target
            real_open = Path.open
            def competing_open(path, mode="r", *args, **kwargs):
                if path == target and mode == "x":
                    with real_open(path, "xb") as competitor:
                        competitor.write(b"synthetic competitor")
                return real_open(path, mode, *args, **kwargs)
            with patch.object(Path, "open", competing_open):
                result = operations.apply_plan("claim", vault, plan)
            self.assertEqual((result.exit_code, result.issues[0].code),
                             (ExitCode.IO_OR_DRIFT, "target.drifted"))
            self.assertEqual(target.read_bytes(), b"synthetic competitor")
            self.assertEqual(result.changes[0].status, "unexecuted")

    def test_two_preview_plans_have_one_winner(self):
        with TemporaryDirectory() as temporary:
            root = self.vault(Path(temporary).resolve())
            first = operations.plan_claim(root, "daily/a.md")
            second = operations.plan_claim(root, "daily/a.md")
            self.assertEqual(operations.apply_plan("claim", root, first).exit_code, ExitCode.OK)
            metadata = first[0].target.lstat()
            result = operations.apply_plan("claim", root, second)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(first[0].target.lstat(), metadata)

    def test_target_present_after_plan_is_drift(self):
        with TemporaryDirectory() as temporary:
            root = self.vault(Path(temporary).resolve())
            plan = operations.plan_claim(root, "daily/a.md")
            plan[0].target.write_bytes(b"synthetic competitor")
            result = operations.apply_plan("claim", root, plan)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(plan[0].target.read_bytes(), b"synthetic competitor")

    def test_unsafe_claim_paths_are_zero_write(self):
        with TemporaryDirectory() as temporary:
            root = self.vault(Path(temporary).resolve())
            real_open = Path.open
            writes = []
            def safe_open(path, mode="r", *args, **kwargs):
                if any(flag in mode for flag in "wax+"):
                    writes.append(path)
                return real_open(path, mode, *args, **kwargs)
            for relative in ("", "../a.md", "/synthetic/a.md", "daily/../a.md", "daily/a\x00.md",
                             ".second-brain/a.md", "secrets/a.md", "daily/secrets/a.md", "outside/a.md", "daily"):
                for apply in (False, True):
                    with self.subTest(relative=relative, apply=apply), patch.object(Path, "open", safe_open), \
                         patch.object(Path, "mkdir") as mkdir:
                        result = operations.run_claim(root, relative, apply)
                    self.assertEqual(result.exit_code, ExitCode.UNSAFE_PATH)
                    mkdir.assert_not_called()
            self.assertEqual(writes, [])

    def test_claim_uses_exactly_one_configured_root(self):
        for scenario in ("duplicate", "nested", "custom", "cross-root", "marker-alias"):
            with self.subTest(scenario=scenario), TemporaryDirectory() as temporary:
                root = self.vault(Path(temporary).resolve())
                document = json.loads(config_text())
                relative = "daily/a.md"
                expected = ExitCode.UNSAFE_PATH
                if scenario == "duplicate":
                    document["paths"]["reviews"] = "daily"
                elif scenario == "nested":
                    (root / "daily/archive").mkdir()
                    document["paths"]["knowledge"] = "daily/archive"
                    relative = "daily/archive/a.md"
                elif scenario == "custom":
                    (root / "notes/days").mkdir(parents=True)
                    document["paths"]["daily"] = "notes/days"
                    relative, expected = "notes/days/a.md", ExitCode.OK
                elif scenario == "cross-root":
                    (root / "daily/bridge").symlink_to(root / "wiki/reviews", target_is_directory=True)
                    relative = "daily/bridge/a.md"
                else:
                    (root / "daily/bridge").symlink_to(root / ".second-brain", target_is_directory=True)
                    relative = "daily/bridge/a.md"
                (root / ".second-brain/config.json").write_text(json.dumps(document))
                result = operations.run_claim(root, relative, True)
                self.assertEqual(result.exit_code, expected)

    def test_claim_parent_and_target_kinds(self):
        for kind, expected in (("missing-parent", 6), ("file-parent", 6), ("file", 5),
                               ("directory", 5), ("dangling", 5), ("secret", 4), ("safe-link", 0)):
            with self.subTest(kind=kind), TemporaryDirectory() as temporary:
                root = self.vault(Path(temporary).resolve())
                target = root / "daily/a.md"
                if kind == "missing-parent":
                    target = root / "daily/missing/a.md"
                elif kind == "file-parent":
                    (root / "daily/file").write_bytes(b"synthetic")
                    target = root / "daily/file/a.md"
                elif kind == "file":
                    target.write_bytes(b"")
                elif kind == "directory":
                    target.mkdir()
                elif kind == "dangling":
                    target.symlink_to(root / "daily/absent.md")
                else:
                    destination = root / ("secrets" if kind == "secret" else "daily/real")
                    destination.mkdir()
                    (root / "daily/link").symlink_to(destination, target_is_directory=True)
                    target = root / "daily/link/a.md"
                result = operations.run_claim(root, target.relative_to(root).as_posix(), True)
                self.assertEqual(result.exit_code, expected)

    def test_claim_revalidates_config_and_parent(self):
        for change, expected in (("config", 4), ("outside", 4), ("secret", 4), ("missing", 6)):
            with self.subTest(change=change), TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = self.vault(base)
                parent = root / "daily/parent"
                parent.mkdir()
                plan = operations.plan_claim(root, "daily/parent/a.md")
                if change == "config":
                    document = json.loads(config_text())
                    document["paths"]["daily"] = "other"
                    (root / ".second-brain/config.json").write_text(json.dumps(document))
                else:
                    parent.rmdir()
                    if change != "missing":
                        destination = base / "outside" if change == "outside" else root / "secrets"
                        destination.mkdir()
                        parent.symlink_to(destination, target_is_directory=True)
                result = operations.apply_plan("claim", root, plan)
                self.assertEqual(result.exit_code, expected)
                self.assertFalse((base / "outside/a.md").exists())
                self.assertFalse((root / "secrets/a.md").exists())

    def test_claim_io_and_privacy(self):
        with TemporaryDirectory() as temporary:
            root = self.vault(Path(temporary).resolve())
            real_open = Path.open
            for failure in (PermissionError("synthetic private text"), OSError("synthetic private text")):
                def failing_open(path, mode="r", *args, **kwargs):
                    if mode == "x":
                        raise failure
                    return real_open(path, mode, *args, **kwargs)
                with patch.object(Path, "open", failing_open):
                    result = operations.run_claim(root, "daily/a.md", True)
                self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
                self.assertEqual(result.changes[0].status, "unexecuted")
                issues = json.dumps(result.to_dict()["issues"])
                self.assertNotIn(str(root), issues)
                self.assertNotIn("synthetic private text", issues)
            marker = root / ".second-brain/config.json"
            for scenario, expected in (("nul", 4), ("schema", 3), ("missing", 3)):
                document = json.loads(config_text())
                if scenario == "nul":
                    document["paths"]["daily"] = "daily\x00bad"
                elif scenario == "schema":
                    document["schema_version"] = 2
                marker.write_text(json.dumps(document))
                if scenario == "missing":
                    marker.unlink()
                self.assertEqual(operations.run_claim(root, "daily/a.md", False).exit_code, expected)

    def test_claim_does_not_create_parents_or_accept_content(self):
        with TemporaryDirectory() as temporary:
            root = self.vault(Path(temporary).resolve())
            for apply in (False, True):
                with patch.object(Path, "mkdir") as mkdir, patch("threadroot.operations.write_default_pointer") as pointer:
                    args = ["claim", "--path", "daily/a.md", "--vault", str(root), "--json"]
                    if apply:
                        args.append("--apply")
                    result = execute(build_parser().parse_args(args), root, {}, root)
                self.assertTrue(result.ok)
                self.assertEqual(result.command, "claim")
                mkdir.assert_not_called()
                pointer.assert_not_called()
            from threadroot.results import ThreadrootError
            for extra in (("--content", "synthetic"), ("--text", "synthetic"), ("synthetic",), ("--set-default",)):
                with self.assertRaises(ThreadrootError) as caught:
                    build_parser().parse_args(["claim", "--path", "daily/a.md", *extra])
                self.assertEqual(caught.exception.exit_code, ExitCode.USAGE)
