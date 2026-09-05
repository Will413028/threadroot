from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import release_artifacts
from scripts.release_artifacts import (
    ArtifactSet,
    ReleaseArtifactError,
    compare_artifact_sets,
    expected_asset_names,
)
from tests.test_release_archives import WHEEL_EPOCH, _make_sdist_source, _sdist_entries, _write_sdist


class ArtifactSetTests(unittest.TestCase):
    def test_artifact_set_requires_exact_four_names(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in expected_asset_names("0.1.0")[:-1]:
                (root / name).write_bytes(b"synthetic")
            with self.assertRaisesRegex(
                ReleaseArtifactError, "release output membership mismatch"
            ):
                ArtifactSet.load(root, "0.1.0")

    def test_compare_sets_rejects_one_changed_byte(self) -> None:
        with TemporaryDirectory() as left_dir, TemporaryDirectory() as right_dir:
            for root in (Path(left_dir), Path(right_dir)):
                for name in expected_asset_names("0.1.0"):
                    (root / name).write_bytes(name.encode("utf-8"))
            (Path(right_dir) / "threadroot-0.1.0.tar.gz").write_bytes(b"changed")
            with self.assertRaisesRegex(
                ReleaseArtifactError, "artifact bytes differ: threadroot-0.1.0.tar.gz"
            ):
                compare_artifact_sets(
                    ArtifactSet.load(Path(left_dir), "0.1.0"),
                    ArtifactSet.load(Path(right_dir), "0.1.0"),
                )

    def test_artifact_set_rejects_symlink_member(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in expected_asset_names("0.1.0"):
                target = root / name
                target.write_bytes(b"synthetic")
            outside = root / "outside"
            outside.write_bytes(b"outside")
            (root / expected_asset_names("0.1.0")[-1]).unlink()
            (root / expected_asset_names("0.1.0")[-1]).symlink_to(outside)
            with self.assertRaisesRegex(ReleaseArtifactError, "membership mismatch"):
                ArtifactSet.load(root, "0.1.0")


def _make_source(root: Path) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    (source / "scripts").mkdir()
    (source / "scripts/check_public.py").write_text("# synthetic\n", encoding="utf-8")
    (source / "tools/release").mkdir(parents=True)
    (source / "tools/release/Dockerfile").write_text("FROM synthetic\n", encoding="utf-8")
    (source / "requirements").mkdir()
    lock_rows = ["--only-binary=:all:\n"]
    for package, version in release_artifacts.EXPECTED_PACKAGES.items():
        lock_rows.append(
            f"{package}=={version} " + "\\\n" + "    --hash=sha256:" + "0" * 64 + "\n"
        )
    (source / "requirements/release.txt").write_text(
        "".join(lock_rows),
        encoding="utf-8",
    )
    return source


def _seed_candidate(candidate: Path, *, changed: bool = False) -> None:
    candidate.mkdir(parents=True)
    for name in expected_asset_names("0.1.0"):
        payload = name.encode("utf-8")
        if changed and name.endswith(".tar.gz"):
            payload += b"changed"
        (candidate / name).write_bytes(payload)


def _fake_extract(_artifact: Path, destination: Path, **_kwargs: object) -> None:
    destination.mkdir(parents=True)


class BuildAndVerifyTests(unittest.TestCase):
    def test_lock_requires_exactly_one_approved_option(self) -> None:
        with TemporaryDirectory() as directory:
            lock = Path(directory) / "release.txt"
            row = "build==1.6.0 " + "\\\n" + "    --hash=sha256:" + "0" * 64 + "\n"
            lock.write_text(row, encoding="utf-8")
            with self.assertRaises(ReleaseArtifactError):
                release_artifacts._read_lock_versions(lock)
            lock.write_text("--only-binary=:all:\n" + row, encoding="utf-8")
            self.assertEqual(release_artifacts._read_lock_versions(lock), {"build": "1.6.0"})
            lock.write_text("--only-binary=:all:\n--only-binary=:all:\n" + row, encoding="utf-8")
            with self.assertRaises(ReleaseArtifactError):
                release_artifacts._read_lock_versions(lock)

    def test_installed_package_canonical_duplicate_is_rejected(self) -> None:
        class Distribution:
            def __init__(self, name: str) -> None:
                self.metadata = {"Name": name}
                self.version = "1.0"
        with patch.object(release_artifacts.importlib.metadata, "distributions", return_value=[Distribution("foo-bar"), Distribution("foo_bar")]):
            with self.assertRaises(ReleaseArtifactError):
                release_artifacts._installed_packages()

    def test_missing_fixed_denylist_is_rejected_before_output(self) -> None:
        with patch.object(release_artifacts.os, "lstat", side_effect=FileNotFoundError):
            with self.assertRaises(ReleaseArtifactError):
                release_artifacts._validate_denylist(Path("/run/threadroot/denylist"))

    def test_replay_symlink_wheel_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            evidence = root / "evidence"
            evidence.mkdir()
            def fake_extract(_artifact: Path, destination: Path, **_kwargs: object) -> None:
                (destination / "threadroot-0.1.0").mkdir(parents=True)
            def fake_run(_command: list[str], _environment: dict[str, str]) -> None:
                output = evidence / "replay-wheel"
                output.mkdir(exist_ok=True)
                (output / artifacts.wheel.name).symlink_to(artifacts.wheel)
            with patch.object(release_artifacts, "extract_regular_tar", side_effect=fake_extract), patch.object(release_artifacts, "_run", side_effect=fake_run):
                with self.assertRaises(ReleaseArtifactError):
                    release_artifacts._replay_sdist(artifacts, evidence, 1)

    def test_pending_mode_mutation_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            hashes = {name: release_artifacts._sha256(candidate / name) for name in expected_asset_names("0.1.0")}
            original_publish = release_artifacts._exclusive_publish
            def mutate(*args: object, **kwargs: object) -> None:
                pending = root / "selected.pending" / expected_asset_names("0.1.0")[0]
                pending.chmod(0o777)
                original_publish(*args, **kwargs)
            with patch.object(release_artifacts, "_exclusive_publish", side_effect=mutate):
                with self.assertRaises(ReleaseArtifactError):
                    release_artifacts._promote(root, artifacts, hashes)
    def test_environment_gate_rejects_ambient_epoch_mismatch(self) -> None:
        environment = dict(release_artifacts.EXPECTED_ENVIRONMENT)
        environment["SOURCE_DATE_EPOCH"] = "99"
        with patch.dict(release_artifacts.os.environ, environment, clear=True):
            with patch.object(release_artifacts, "_installed_packages", return_value=release_artifacts.EXPECTED_PACKAGES):
                with patch.object(release_artifacts.platform, "system", return_value="Linux"), patch.object(release_artifacts.platform, "machine", return_value="x86_64"), patch.object(release_artifacts.sys, "version_info", (3, 14, 7)):
                    with self.assertRaisesRegex(ReleaseArtifactError, "SOURCE_DATE_EPOCH mismatch"):
                        release_artifacts._validate_environment(100, release_artifacts.EXPECTED_PACKAGES)

    def test_denylist_gate_rejects_before_output_creation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            with self.assertRaisesRegex(ReleaseArtifactError, "denylist path is not approved"):
                release_artifacts.build_and_verify(source_a, source_b, output, "a" * 40, 1, root / "denylist")
            self.assertFalse(output.exists())

    def test_scanner_uses_sanitized_environment_and_all_explicit_roots(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = root / "a"
            source_b = root / "b"
            source_a.mkdir()
            source_b.mkdir()
            (source_a / "scripts").mkdir()
            scanner = source_a / "scripts/check_public.py"
            scanner.write_text("# scanner\n", encoding="utf-8")
            candidate = root / "candidate"
            _seed_candidate(candidate)
            unpacked = root / "unpacked"
            for name in ("wheel", "sdist", "claude", "codex"):
                (unpacked / name).mkdir(parents=True)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            with patch.object(release_artifacts.subprocess, "run") as run:
                release_artifacts._scan(source_a, source_b, artifacts, unpacked, None)
            command = run.call_args.args[0]
            self.assertEqual(command[0], release_artifacts.sys.executable)
            self.assertEqual(command[1], str(scanner))
            self.assertEqual(command[2:], [str(source_a), str(source_b), *[str(candidate / name) for name in expected_asset_names("0.1.0")], *[str(unpacked / name) for name in ("wheel", "sdist", "claude", "codex")]])
            self.assertEqual(run.call_args.kwargs["env"], {"PATH": release_artifacts.os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "TZ": "UTC"})

    def test_release_lock_parser_rejects_malformed_duplicate_and_extra_lines(self) -> None:
        with TemporaryDirectory() as directory:
            lock = Path(directory) / "release.txt"
            valid = "--only-binary=:all:\npackage==1.0 \\\n+    --hash=sha256:" + "0" * 64 + "\n"
            for mutation in (
                valid.replace("package==1.0", "package==1.0\npackage==1.0"),
                valid.replace("--only-binary=:all:", "--index-url=https://example.invalid"),
                valid.replace("--hash=sha256:", "--hash=sha256:not-a-digest"),
            ):
                lock.write_text(mutation, encoding="utf-8")
                with self.assertRaises(ReleaseArtifactError):
                    release_artifacts._read_lock_versions(lock)

    def test_real_task3_sdist_validates_replays_and_unpacks_without_pax_comment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            sdist = root / "threadroot-0.1.0.tar.gz"
            _write_sdist(sdist, _sdist_entries(source), gzip_mtime=WHEEL_EPOCH)
            release_artifacts.validate_sdist(sdist, source, "0.1.0", WHEEL_EPOCH)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            (candidate / "threadroot-0.1.0.tar.gz").write_bytes(sdist.read_bytes())
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            evidence = root / "evidence"
            evidence.mkdir()

            def fake_run(_command: list[str], _environment: dict[str, str]) -> None:
                replay = evidence / "replay-wheel" / artifacts.wheel.name
                replay.write_bytes(artifacts.wheel.read_bytes())

            with patch.object(release_artifacts, "_run", side_effect=fake_run):
                release_artifacts._replay_sdist(artifacts, evidence, WHEEL_EPOCH)
            release_artifacts.extract_regular_tar(sdist, evidence / "unpacked")
            self.assertTrue((evidence / "unpacked" / "threadroot-0.1.0" / "PKG-INFO").is_file())

    def test_environment_gate_rejects_missing_canonical_flag(self) -> None:
        with patch.dict(release_artifacts.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ReleaseArtifactError, "environment is not enabled"):
                release_artifacts._validate_environment(0, release_artifacts.EXPECTED_PACKAGES)

    def test_input_gate_rejects_shared_source_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            with self.assertRaisesRegex(ReleaseArtifactError, "source roots must be distinct"):
                release_artifacts._validate_roots(source, source, root / "output")

    def test_input_gate_rejects_nonempty_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = root / "source-a"
            source_b = root / "source-b"
            source_a.mkdir()
            source_b.mkdir()
            output = root / "output"
            output.mkdir()
            (output / "unexpected").write_bytes(b"x")
            with self.assertRaisesRegex(ReleaseArtifactError, "output must be missing or empty"):
                release_artifacts._validate_roots(source_a, source_b, output)

    def test_input_gate_rejects_symlink_source_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(ReleaseArtifactError, "real directories"):
                release_artifacts._validate_roots(real, link, root / "output")

    def test_build_one_source_uses_three_isolated_commands_and_environment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            candidate = root / "candidate"
            work = root / "work"
            with patch.object(release_artifacts, "_run") as run:
                release_artifacts._build_one_source(source, candidate, work, 123)
            self.assertEqual(run.call_count, 3)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][2:6], ["build", "--sdist", "--no-isolation", "--outdir"])
            self.assertEqual(commands[1][2:6], ["build", "--wheel", "--no-isolation", "--outdir"])
            self.assertEqual(commands[2][1], str(source / "scripts/build_release.py"))
            environment = run.call_args_list[0].args[1]
            self.assertEqual(environment["SOURCE_DATE_EPOCH"], "123")
            self.assertEqual(environment["TMPDIR"], str(work / "tmp"))
            self.assertEqual(environment["HOME"], str(work / "home"))
            self.assertEqual(environment["XDG_CACHE_HOME"], str(work / "cache"))
            self.assertEqual(environment["THREADROOT_CANONICAL_BUILD"], "1")

    def test_build_and_verify_promotes_only_after_all_mocked_boundaries(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"

            def fake_build(source: Path, candidate: Path, work: Path, epoch: int) -> None:
                work.mkdir(parents=True)
                _seed_candidate(candidate)

            with (
                patch.object(release_artifacts, "_validate_environment"),
                patch.object(release_artifacts, "_build_one_source", side_effect=fake_build) as build,
                patch.object(release_artifacts, "validate_wheel"),
                patch.object(release_artifacts, "validate_sdist"),
                patch.object(release_artifacts, "validate_host_zip"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan"),
                patch.object(release_artifacts, "extract_regular_zip", side_effect=_fake_extract),
                patch.object(release_artifacts, "extract_regular_tar", side_effect=_fake_extract),
            ):
                hashes = release_artifacts.build_and_verify(
                    source_a, source_b, output, "a" * 40, 1
                )

            self.assertEqual(build.call_count, 2)
            self.assertEqual(set(hashes), set(expected_asset_names("0.1.0")))
            self.assertTrue((output / "selected").is_dir())
            self.assertFalse((output / "selected.pending").exists())
            self.assertTrue((output / "evidence/SHA256SUMS").is_file())
            self.assertTrue((output / "evidence/build.json").is_file())

    def test_build_and_verify_rejects_changed_candidate_before_promotion(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"

            def fake_build(source: Path, candidate: Path, work: Path, epoch: int) -> None:
                work.mkdir(parents=True)
                _seed_candidate(candidate, changed=candidate.name == "candidate-b")

            with (
                patch.object(release_artifacts, "_validate_environment"),
                patch.object(release_artifacts, "_build_one_source", side_effect=fake_build),
            ):
                with self.assertRaisesRegex(ReleaseArtifactError, "artifact bytes differ"):
                    release_artifacts.build_and_verify(
                        source_a, source_b, output, "a" * 40, 1
                    )

            self.assertFalse((output / "selected").exists())
            self.assertFalse((output / "selected.pending").exists())

    def test_scanner_failure_leaves_both_promotion_directories_absent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"

            def fake_build(source: Path, candidate: Path, work: Path, epoch: int) -> None:
                work.mkdir(parents=True)
                _seed_candidate(candidate)

            with (
                patch.object(release_artifacts, "_validate_environment"),
                patch.object(release_artifacts, "_build_one_source", side_effect=fake_build),
                patch.object(release_artifacts, "validate_wheel"),
                patch.object(release_artifacts, "validate_sdist"),
                patch.object(release_artifacts, "validate_host_zip"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan", side_effect=ReleaseArtifactError("scan failed")),
                patch.object(release_artifacts, "extract_regular_zip", side_effect=_fake_extract),
                patch.object(release_artifacts, "extract_regular_tar", side_effect=_fake_extract),
            ):
                with self.assertRaisesRegex(ReleaseArtifactError, "scan failed"):
                    release_artifacts.build_and_verify(
                        source_a, source_b, output, "a" * 40, 1
                    )

            self.assertFalse((output / "selected").exists())
            self.assertFalse((output / "selected.pending").exists())

    def test_replay_rejects_changed_wheel_before_promotion(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            evidence = root / "evidence"
            evidence.mkdir()

            def fake_extract(_artifact: Path, destination: Path, **_kwargs: object) -> None:
                (destination / "threadroot-0.1.0").mkdir(parents=True)

            def fake_run(_command: list[str], _environment: dict[str, str]) -> None:
                output = evidence / "replay-wheel"
                (output / "threadroot-0.1.0-py3-none-any.whl").write_bytes(b"changed")

            with (
                patch.object(release_artifacts, "extract_regular_tar", side_effect=fake_extract),
                patch.object(release_artifacts, "_run", side_effect=fake_run),
            ):
                with self.assertRaisesRegex(ReleaseArtifactError, "replay bytes differ"):
                    release_artifacts._replay_sdist(artifacts, evidence, 1)

    def test_copy_failure_leaves_only_pending_promotion_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            hashes = {
                name: release_artifacts._sha256(candidate / name)
                for name in expected_asset_names("0.1.0")
            }
            calls = 0
            original_write = release_artifacts.os.write

            def failing_write(descriptor: int, payload: bytes) -> int:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic copy failure")
                return original_write(descriptor, payload)

            with patch.object(release_artifacts.os, "write", side_effect=failing_write):
                with self.assertRaisesRegex(ReleaseArtifactError, "promotion failed"):
                    release_artifacts._promote(root, artifacts, hashes)
            self.assertTrue((root / "selected.pending").is_dir())
            self.assertFalse((root / "selected").exists())

    def test_promotion_rejects_existing_broken_selected_link(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            hashes = {name: release_artifacts._sha256(candidate / name) for name in expected_asset_names("0.1.0")}
            (root / "selected").symlink_to(root / "missing")
            with self.assertRaisesRegex(ReleaseArtifactError, "already exists"):
                release_artifacts._promote(root, artifacts, hashes)
            self.assertTrue((root / "selected").is_symlink())
            self.assertFalse((root / "selected.pending").exists())

    def test_build_and_verify_rejects_invalid_commit_before_output_creation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            with self.assertRaisesRegex(ReleaseArtifactError, "lowercase 40-hex"):
                release_artifacts.build_and_verify(source_a, source_b, output, "BAD", 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
