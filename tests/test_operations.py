import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from threadroot.operations import PlannedChange, apply_plan, plan_init, run_init
from threadroot.results import ExitCode


class InitTests(unittest.TestCase):
    def test_preview_of_missing_target_is_pure(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "new-vault"
            result = run_init(vault, apply=False, set_default=False, environ={}, home=Path(directory))
            self.assertTrue(result.ok)
            self.assertFalse(result.applied)
            self.assertFalse(vault.exists())
            self.assertTrue(all(change.status == "planned" for change in result.changes))

    def test_apply_creates_exact_default_structure(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "new-vault"
            result = run_init(vault, apply=True, set_default=False, environ={}, home=Path(directory))
            self.assertTrue(result.ok)
            self.assertEqual(
                {
                    path.relative_to(vault).as_posix()
                    for path in vault.rglob("*")
                },
                {
                    ".second-brain",
                    ".second-brain/config.json",
                    "daily",
                    "wiki",
                    "wiki/projects",
                    "wiki/reviews",
                    "wiki/tech",
                },
            )
            self.assertEqual(
                json.loads((vault / ".second-brain/config.json").read_text()),
                {
                    "schema_version": 1,
                    "paths": {
                        "daily": "daily",
                        "projects": "wiki/projects",
                        "knowledge": "wiki/tech",
                        "reviews": "wiki/reviews",
                    },
                },
            )

    def test_non_empty_target_is_a_conflict(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / "notes.md").write_text("keep me", encoding="utf-8")
            result = run_init(vault, apply=True, set_default=False, environ={}, home=vault)
            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.CONFLICT)
            self.assertEqual((vault / "notes.md").read_text(), "keep me")

    def test_apply_stops_at_collision_and_keeps_completed_changes(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            plan = plan_init(vault)
            collision = plan[1].target
            collision.mkdir()
            sentinel = collision / "pre-existing.txt"
            sentinel.write_text("untouched", encoding="utf-8")

            result = apply_plan("init", vault, plan)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].code, "target.drifted")
            self.assertEqual(result.changes[0].status, "completed")
            self.assertTrue(all(change.status == "unexecuted" for change in result.changes[1:]))
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
            self.assertTrue(plan[0].target.is_dir())

    def test_git_only_directory_is_accepted(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            git_directory = vault / ".git"
            git_directory.mkdir()

            result = run_init(vault, apply=True, set_default=False, environ={}, home=vault)

            self.assertTrue(result.ok)
            self.assertTrue(git_directory.is_dir())
            self.assertTrue((vault / ".second-brain/config.json").is_file())

    def test_missing_direct_parent_fails_preview_without_creating_ancestors(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            missing_parent = base / "missing"
            vault = missing_parent / "vault"

            result = run_init(vault, apply=False, set_default=False, environ={}, home=base)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.CONFLICT)
            self.assertEqual(result.issues[0].code, "target.parent_invalid")
            self.assertFalse(missing_parent.exists())

    def test_valid_initialized_vault_is_an_exit_zero_noop(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            first = run_init(vault, apply=True, set_default=False, environ={}, home=Path(directory))
            self.assertTrue(first.ok)

            result = run_init(vault, apply=True, set_default=False, environ={}, home=Path(directory))

            self.assertTrue(result.ok)
            self.assertEqual(result.exit_code, ExitCode.OK)
            self.assertEqual(result.changes, ())

    def test_invalid_existing_marker_is_not_initialized(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory)
            marker = vault / ".second-brain/config.json"
            marker.parent.mkdir()
            marker.write_text("{", encoding="utf-8")

            result = run_init(vault, apply=False, set_default=False, environ={}, home=vault)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.CONFIG)
            self.assertEqual(result.issues[0].code, "config.path_invalid")
            self.assertEqual(marker.read_text(encoding="utf-8"), "{")

    def test_missing_configured_directory_makes_existing_marker_invalid(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"
            initialized = run_init(
                vault, apply=True, set_default=False, environ={}, home=Path(directory)
            )
            self.assertTrue(initialized.ok)
            (vault / "daily").rmdir()

            result = run_init(vault, apply=False, set_default=False, environ={}, home=Path(directory))

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.CONFIG)
            self.assertEqual(result.issues[0].code, "config.path_invalid")

    def test_set_default_preview_writes_nothing(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            home = base / "home"

            result = run_init(vault, apply=False, set_default=True, environ={}, home=home)

            self.assertTrue(result.ok)
            self.assertFalse(vault.exists())
            self.assertFalse(home.exists())
            self.assertEqual(result.changes[-1].action, "write_default_pointer")
            self.assertEqual(result.changes[-1].path, "machine-default-pointer")
            self.assertEqual(result.changes[-1].status, "planned")

    def test_apply_set_default_creates_missing_machine_directory_and_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            home = base / "home"
            pointer = home / ".config/threadroot/config.json"

            preview = run_init(vault, apply=False, set_default=True, environ={}, home=home)
            self.assertTrue(preview.ok)
            self.assertFalse(pointer.parent.exists())

            result = run_init(vault, apply=True, set_default=True, environ={}, home=home)

            self.assertTrue(result.ok)
            self.assertEqual(
                pointer.read_text(encoding="utf-8"),
                '{"default_vault":"' + str(vault.resolve()) + '"}\n',
            )
            self.assertEqual(result.changes[-1].path, "machine-default-pointer")
            self.assertEqual(result.changes[-1].status, "completed")

    def test_vault_failure_prevents_default_pointer_write(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            vault.mkdir()
            (vault / "notes.md").write_text("keep", encoding="utf-8")
            home = base / "home"

            result = run_init(vault, apply=True, set_default=True, environ={}, home=home)

            self.assertFalse(result.ok)
            self.assertFalse(home.exists())

    def test_pointer_failure_keeps_completed_vault_and_hides_machine_path(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            home = base / "home"
            home.mkdir()
            (home / ".config").write_text("blocks directory creation", encoding="utf-8")

            result = run_init(vault, apply=True, set_default=True, environ={}, home=home)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertTrue((vault / ".second-brain/config.json").is_file())
            self.assertTrue(all(change.status == "completed" for change in result.changes[:-1]))
            self.assertEqual(result.changes[-1].status, "unexecuted")
            self.assertEqual(result.changes[-1].path, "machine-default-pointer")
            self.assertEqual(result.issues[0].path, "machine-default-pointer")
            self.assertNotIn(str(home), str(result.to_dict()))

    def test_apply_rejects_descendant_whose_parent_symlink_escapes(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            outside = base / "outside"
            vault.mkdir()
            outside.mkdir()
            (vault / "linked").symlink_to(outside, target_is_directory=True)
            plan = (
                PlannedChange(
                    "create_file",
                    vault / "linked/escaped.txt",
                    "linked/escaped.txt",
                    "must stay inside\n",
                ),
            )

            result = apply_plan("init", vault, plan)

            self.assertFalse(result.ok)
            self.assertEqual(result.issues[0].code, "target.drifted")
            self.assertFalse((outside / "escaped.txt").exists())

    def test_apply_rejects_vault_parent_replaced_by_symlink_after_plan(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            parent = base / "parent"
            outside = base / "outside"
            parent.mkdir()
            outside.mkdir()
            vault = parent / "vault"
            plan = plan_init(vault)
            parent.rmdir()
            parent.symlink_to(outside, target_is_directory=True)

            result = apply_plan("init", vault, plan)

            self.assertFalse(result.ok)
            self.assertEqual(result.issues[0].code, "target.drifted")
            self.assertFalse((outside / "vault").exists())

    def test_init_without_set_default_ignores_invalid_pointer_environment(self) -> None:
        with TemporaryDirectory() as directory:
            vault = Path(directory) / "vault"

            result = run_init(
                vault,
                apply=False,
                set_default=False,
                environ={"XDG_CONFIG_HOME": "relative"},
                home=Path(directory),
            )

            self.assertTrue(result.ok)
            self.assertTrue(all(change.action != "write_default_pointer" for change in result.changes))

    def test_parent_inspection_io_error_is_not_reported_as_drift(self) -> None:
        with TemporaryDirectory() as directory:
            vault = (Path(directory) / "vault").resolve()
            locked = vault / "locked"
            parent = locked / "parent"
            parent.mkdir(parents=True)
            plan = (
                PlannedChange(
                    "create_file",
                    parent / "note.md",
                    "locked/parent/note.md",
                    "synthetic\n",
                ),
            )
            locked.chmod(0)
            try:
                result = apply_plan("init", vault, plan)
            finally:
                locked.chmod(0o700)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].code, "filesystem.failed")

    def test_apply_reports_symlink_loop_as_drift_without_crashing(self) -> None:
        with TemporaryDirectory() as directory:
            vault = (Path(directory) / "vault").resolve()
            vault.mkdir()
            (vault / "loop").symlink_to("loop")
            plan = (
                PlannedChange(
                    "create_file",
                    vault / "loop/note.md",
                    "loop/note.md",
                    "synthetic\n",
                ),
            )

            result = apply_plan("init", vault, plan)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].code, "target.drifted")

    def test_root_action_symlink_loop_is_reported_as_drift(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            vault = base / "vault"
            plan = plan_init(vault)
            vault.symlink_to("vault")

            try:
                result = apply_plan("init", vault, plan)
            except RuntimeError as error:
                self.fail(f"root-action symlink loop escaped as RuntimeError: {error}")

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].code, "target.drifted")
            self.assertTrue(all(change.status == "unexecuted" for change in result.changes))

    def test_pointer_stage_symlink_loop_is_a_filesystem_failure(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            vault = base / "vault"
            preserved = base / "completed-vault"
            loop_peer = base / "vault-loop"
            xdg = base / "machine-config"

            class LoopVaultOnSecondLookup(dict[str, str]):
                def __init__(self) -> None:
                    super().__init__(XDG_CONFIG_HOME=str(xdg))
                    self.lookups = 0

                def get(self, key: str, default: str | None = None) -> str | None:
                    if key == "XDG_CONFIG_HOME":
                        self.lookups += 1
                        if self.lookups == 2:
                            self.assert_vault_completed()
                            vault.rename(preserved)
                            vault.symlink_to(loop_peer.name)
                            loop_peer.symlink_to(vault.name)
                    return super().get(key, default)

                @staticmethod
                def assert_vault_completed() -> None:
                    if not (vault / ".second-brain/config.json").is_file():
                        raise AssertionError("pointer stage started before vault completion")

            try:
                result = run_init(
                    vault,
                    apply=True,
                    set_default=True,
                    environ=LoopVaultOnSecondLookup(),
                    home=base,
                )
            except RuntimeError as error:
                self.fail(f"pointer-stage symlink loop escaped as RuntimeError: {error}")

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].code, "filesystem.failed")
            self.assertTrue(all(change.status == "completed" for change in result.changes[:-1]))
            self.assertEqual(result.changes[-1].status, "unexecuted")
            self.assertTrue((preserved / ".second-brain/config.json").is_file())
            self.assertFalse((xdg / "threadroot/config.json").exists())

    def test_descendant_vault_stat_error_is_a_filesystem_failure(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            vault = base / "vault"
            vault.mkdir()
            plan = plan_init(vault)
            base.chmod(0)
            try:
                result = apply_plan("init", vault, plan)
            finally:
                base.chmod(0o700)

            self.assertFalse(result.ok)
            self.assertEqual(result.exit_code, ExitCode.IO_OR_DRIFT)
            self.assertEqual(result.issues[0].code, "filesystem.failed")
