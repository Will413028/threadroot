from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import subprocess
from unittest.mock import patch

from scripts.build_verified_release import (
    VerifiedReleaseError,
    canonical_image_tag,
    docker_run_argv,
    main,
)


class VerifiedReleaseTests(unittest.TestCase):
    def test_image_tag_depends_on_dockerfile_and_lock_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = root / "Dockerfile"
            lock = root / "release.txt"
            dockerfile.write_bytes(b"FROM pinned\n")
            lock.write_bytes(b"build==1.6.0\n")
            first = canonical_image_tag(dockerfile, lock)
            lock.write_bytes(b"build==1.6.1\n")
            second = canonical_image_tag(dockerfile, lock)
        self.assertRegex(first, r"^threadroot-release-builder:[0-9a-f]{64}$")
        self.assertNotEqual(first, second)

    def test_docker_run_is_offline_read_only_and_unprivileged(self) -> None:
        argv = docker_run_argv(
            image="threadroot-release-builder:" + "0" * 64,
            source_a=Path("/outside/source-a"), source_b=Path("/outside/source-b"),
            output=Path("/outside/build"), commit="a" * 40, epoch=123,
            uid=501, gid=20, denylist=None,
        )
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("--read-only", argv)
        self.assertEqual(argv.count("--cap-drop"), 1)
        self.assertIn("ALL", argv)
        self.assertIn("no-new-privileges", argv)
        self.assertNotIn("--privileged", argv)

    def test_docker_run_exactly_establishes_artifact_identity_perimeter(self) -> None:
        argv = docker_run_argv("threadroot-release-builder:" + "0" * 64,
                                Path("/outside/source-a"), Path("/outside/source-b"),
                                Path("/outside/build"), "a" * 40, 123, 501, 20, None)
        mounts = [value for index, value in enumerate(argv) if argv[index - 1] == "--mount"]
        self.assertEqual(mounts, [
            "type=bind,src=/outside/source-a,dst=/source-a,readonly",
            "type=bind,src=/outside/source-b,dst=/source-b,readonly",
            "type=bind,src=/outside/build,dst=/release-output",
        ])
        self.assertEqual(argv.count("--read-only"), 1)
        self.assertEqual(argv.count("--network"), 1)
        self.assertEqual(argv.count("--cap-drop"), 1)
        self.assertEqual(argv.count("--security-opt"), 1)
        self.assertIn("--user", argv)
        self.assertIn("--workdir", argv)

    def test_security_option_mutations_fail_closed_before_run(self) -> None:
        from scripts.build_verified_release import _validate_docker_run_argv
        argv = docker_run_argv("image", Path("/outside/source-a"), Path("/outside/source-b"),
                               Path("/outside/build"), "a" * 40, 1, 1, 1, None)
        mutations = []
        for option in ("--read-only", "--network", "--cap-drop", "--security-opt", "--user", "--workdir"):
            mutated = list(argv)
            mutated.remove(option)
            mutations.append(mutated)
        for mutated in mutations:
            with self.assertRaises(VerifiedReleaseError):
                _validate_docker_run_argv(mutated)

    def test_requires_full_commit_and_absolute_output_outside_repository(self) -> None:
        self.assertEqual(main(["--commit", "bad", "--output", "relative"]), 1)

    def test_rejects_docker_mount_delimiters_and_control_characters(self) -> None:
        with self.assertRaises(VerifiedReleaseError):
            docker_run_argv("image", Path("/outside/a,b"), Path("/outside/b"),
                            Path("/outside/build"), "a" * 40, 1, 1, 1, None)
        with self.assertRaises(VerifiedReleaseError):
            docker_run_argv("image", Path("/outside/a\n"), Path("/outside/b"),
                            Path("/outside/build"), "a" * 40, 1, 1, 1, None)

    def test_rejects_dirty_tracked_or_untracked_repository_state(self) -> None:
        with patch("scripts.build_verified_release._git", return_value=" M tracked"):
            self.assertEqual(main(["--commit", "a" * 40, "--output", "/outside/release"]), 1)

    def test_rejects_nonempty_output_and_symlink_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "existing").write_text("x", encoding="utf-8")
            self.assertEqual(main(["--commit", "a" * 40, "--output", str(output)]), 1)

    def test_rejects_symlink_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            output = root / "output"
            output.symlink_to(target, target_is_directory=True)
            self.assertEqual(main(["--commit", "a" * 40, "--output", str(output)]), 1)

    def test_exports_exact_commit_twice_without_links_or_unsafe_names(self) -> None:
        with patch("scripts.build_verified_release._archive_commit") as archive:
            self.assertEqual(main(["--commit", "a" * 40, "--output", "/outside/release"]), 1)
            self.assertLessEqual(archive.call_count, 2)

    def test_outer_success_exports_twice_and_runs_exact_build_then_run(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "release"
            def extract(_payload: bytes, destination: Path, **_kwargs: object) -> None:
                destination.mkdir(parents=True)
                (destination / "tools/release").mkdir(parents=True)
                (destination / "requirements").mkdir()
                (destination / "tools/release/Dockerfile").write_bytes(b"FROM pinned\n")
                (destination / "requirements/release.txt").write_bytes(b"lock\n")
            def git(*args: str) -> str:
                if args[0] == "status":
                    return ""
                if args[0] == "cat-file":
                    return "commit\n"
                return "123\n"
            with patch("scripts.build_verified_release._git", side_effect=git), \
                 patch("scripts.build_verified_release._runner_bytes_match", return_value=True), \
                 patch("scripts.build_verified_release._archive_commit", return_value=b"archive") as archive, \
                 patch("scripts.build_verified_release.extract_regular_tar_payload", side_effect=extract), \
                 patch("scripts.build_verified_release.canonical_image_tag", return_value="image"), \
                 patch("scripts.build_verified_release.subprocess.run") as run:
                self.assertEqual(main(["--commit", "a" * 40, "--output", str(output)]), 0)
            self.assertEqual(archive.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0][:5], ["docker", "build", "--platform", "linux/amd64", "--pull"])
            self.assertEqual(run.call_args_list[1].args[0][0:8], ["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none", "--read-only"])
            self.assertTrue((output / "build").is_dir())

    def test_docker_failure_sanitizes_host_paths_and_does_not_echo_argv(self) -> None:
        from argparse import Namespace
        from scripts.build_verified_release import _sanitized_failure
        error = subprocess.CalledProcessError(1, ["docker", "run"], output="/outside/private-denylist", stderr="/outside/release")
        message = _sanitized_failure(error, Namespace(output="/outside/release", denylist="/outside/private-denylist"))
        self.assertNotIn("private-denylist", message)
        self.assertNotIn("/outside/release", message)
        self.assertIn("[output]", message)
        self.assertIn("[denylist]", message)

    def test_runner_files_must_match_the_selected_commit(self) -> None:
        with patch("scripts.build_verified_release._runner_bytes_match", return_value=False):
            self.assertEqual(main(["--commit", "a" * 40, "--output", "/outside/release"]), 1)

    def test_docker_build_uses_exact_platform_dockerfile_and_export_context(self) -> None:
        from scripts.build_verified_release import _docker_build_argv
        argv = _docker_build_argv("image", Path("/outside/source-a"))
        self.assertEqual(argv, ["docker", "build", "--platform", "linux/amd64", "--pull",
                                "--file", "/outside/source-a/tools/release/Dockerfile",
                                "--tag", "image", "/outside/source-a"])

    def test_optional_denylist_is_mounted_read_only_without_entering_argv_logs(self) -> None:
        argv = docker_run_argv("image", Path("/outside/source-a"), Path("/outside/source-b"),
                               Path("/outside/build"), "a" * 40, 1, 1, 1,
                               Path("/outside/private-denylist"))
        self.assertIn("dst=/run/threadroot/denylist,readonly", " ".join(argv))
        self.assertNotIn("private-denylist", argv)

    def test_denylist_host_path_must_be_absolute(self) -> None:
        with self.assertRaises(VerifiedReleaseError):
            docker_run_argv("image", Path("/outside/source-a"), Path("/outside/source-b"),
                            Path("/outside/build"), "a" * 40, 1, 1, 1, Path("denylist"))

    def test_inside_paths_reject_before_lazy_task4_import(self) -> None:
        with patch.dict("os.environ", {"THREADROOT_CANONICAL_BUILD": "1"}, clear=True), \
             patch.dict("sys.modules", {"scripts.release_artifacts": None}):
            self.assertEqual(main(["--inside", "--source-a", "/bad", "--source-b", "/source-b",
                                   "--output", "/release-output", "--commit", "a" * 40, "--epoch", "1"]), 1)

    def test_inside_mode_requires_container_sentinel_and_calls_build_and_verify(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(main(["--inside", "--source-a", "/source-a",
                                   "--source-b", "/source-b", "--output",
                                   "/release-output", "--commit", "a" * 40,
                                   "--epoch", "1"]), 1)


if __name__ == "__main__":
    unittest.main()
