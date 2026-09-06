from __future__ import annotations

from contextlib import ExitStack, contextmanager
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
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
from scripts import release_archives
from tests.test_release_archives import (
    WHEEL_EPOCH,
    _add_trailing_bytes_to_last_deflate_stream,
    _gzip_tar_payload,
    _make_release_source,
    _make_sdist_source,
    _mutate_zip_fixed_header,
    _prepend_tar_metadata_header,
    _sdist_entries,
    _wheel_payloads,
    _write_sdist,
    _write_wheel,
)


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
            root = Path(directory) / "candidate"
            root.mkdir()
            for name in expected_asset_names("0.1.0"):
                target = root / name
                target.write_bytes(b"synthetic")
            outside = Path(directory) / "outside"
            outside.write_bytes(b"outside")
            (root / expected_asset_names("0.1.0")[-1]).unlink()
            (root / expected_asset_names("0.1.0")[-1]).symlink_to(outside)
            with self.assertRaisesRegex(ReleaseArtifactError, "membership mismatch"):
                ArtifactSet.load(root, "0.1.0")


def _make_source(root: Path) -> Path:
    root.mkdir(parents=True)
    source = _make_release_source(root)
    (source / "scripts/check_public.py").write_text("# synthetic\n", encoding="utf-8")
    (source / "tools/release/Dockerfile").write_text("FROM synthetic\n", encoding="utf-8")
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
    candidate.mkdir(parents=True, exist_ok=True)
    for name in expected_asset_names("0.1.0"):
        payload = name.encode("utf-8")
        if changed and name.endswith(".tar.gz"):
            payload += b"changed"
        (candidate / name).write_bytes(payload)


def _fake_extract(_artifact: Path, destination: Path, **_kwargs: object) -> None:
    destination.mkdir(parents=True)


@contextmanager
def _bound_test_candidate(root: Path, artifacts: ArtifactSet):
    with ExitStack() as stack:
        bindings = release_artifacts._RunBindings(stack)
        output = bindings.bind(root)
        candidate = bindings.bind(artifacts.root, output)
        snapshots = release_artifacts._capture_set(stack, candidate, expected_asset_names("0.1.0"))
        pair = release_artifacts._VerifiedPair(snapshots, (), tuple((item.name, item.sha256) for item in snapshots))
        yield bindings, output, pair, lambda: release_artifacts._assert_set(candidate, snapshots)


def _replay_test_candidate(artifacts: ArtifactSet, evidence: Path, epoch: int) -> None:
    with _bound_test_candidate(evidence.parent, artifacts) as (bindings, output, pair, guard):
        bound_evidence = bindings.bind(evidence, output)
        release_artifacts._replay_sdist(bindings, pair.candidate_a, bound_evidence, epoch)
        guard()


def _promote_test_candidate(root: Path, artifacts: ArtifactSet) -> None:
    with _bound_test_candidate(root, artifacts) as (bindings, output, pair, guard):
        release_artifacts._promote(bindings, output, pair, guard)


@contextmanager
def _canonical_environment(epoch: int = 123):
    class Distribution:
        def __init__(self, name: str, version: str) -> None:
            self.metadata = {"Name": name}
            self.version = version

    environment = {
        **release_artifacts.EXPECTED_ENVIRONMENT,
        "SOURCE_DATE_EPOCH": str(epoch),
        "PATH": "/synthetic/bin",
    }
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        stack.enter_context(patch.object(release_artifacts.platform, "system", return_value="Linux"))
        stack.enter_context(patch.object(release_artifacts.platform, "machine", return_value="x86_64"))
        stack.enter_context(patch.object(release_artifacts.sys, "version_info", (3, 14, 7)))
        stack.enter_context(patch.object(release_artifacts.importlib.metadata, "distributions", return_value=[
            Distribution(name, version) for name, version in release_artifacts.EXPECTED_PACKAGES.items()
        ]))
        yield Distribution


@contextmanager
def _mock_release_phases(*, build=None, replay=None, scan=None, validator=None):
    def seed(source: Path, candidate: Path, work: Path, epoch: int, **kwargs: object) -> None:
        _seed_candidate(candidate)

    with ExitStack() as stack:
        stack.enter_context(patch.object(release_artifacts, "_build_one_source", side_effect=build or seed))
        stack.enter_context(patch.object(release_artifacts, "_replay_sdist", side_effect=replay))
        stack.enter_context(patch.object(release_artifacts, "_scan", side_effect=scan))
        for name in ("validate_wheel", "validate_sdist", "validate_host_zip",
                     "validate_wheel_payload", "validate_sdist_payload", "validate_host_zip_payload"):
            stack.enter_context(patch.object(release_artifacts, name, side_effect=validator, create=True))
        for name in ("extract_regular_zip", "extract_regular_tar", "extract_regular_zip_payload", "extract_regular_tar_payload"):
            stack.enter_context(patch.object(release_artifacts, name, side_effect=_fake_extract, create=True))
        yield


class StaticGateTableTests(unittest.TestCase):
    def test_missing_builder_files_fail_with_structured_error_before_output(self) -> None:
        for name in ("requirements/release.txt", "tools/release/Dockerfile"):
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                (a / name).unlink()
                output = root / "output"
                with _canonical_environment(), self.assertRaisesRegex(ReleaseArtifactError, "builder input"):
                    release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertFalse(output.exists())

    def test_environment_lock_and_input_rejections_precede_candidate_creation(self) -> None:
        cases = [*(f"env:{key}" for key in release_artifacts.EXPECTED_ENVIRONMENT),
                 "platform", "architecture", "python", "negative-epoch", "ambient-epoch",
                 "package-missing", "package-extra", "package-wrong", "package-duplicate",
                 "lock-option-missing", "lock-option-duplicate", "lock-option-wrong", "lock-hash",
                 "lock-package-missing", "lock-package-extra", "lock-package-wrong", "lock-package-duplicate",
                 "lock-bytes-diverge", "requirements-link", "tools-link", "relative-source", "same-source",
                 "source-link", "output-nonempty", "output-link", "denylist-arbitrary",
                 "denylist-missing", "denylist-link", "denylist-nonregular"]
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                epoch, denylist = 123, None
                with _canonical_environment() as Distribution, ExitStack() as stack:
                    if case.startswith("env:"):
                        os.environ[case.removeprefix("env:")] = "unapproved"
                    elif case in ("platform", "architecture"):
                        stack.enter_context(patch.object(release_artifacts.platform, "system" if case == "platform" else "machine", return_value="unapproved"))
                    elif case == "python":
                        stack.enter_context(patch.object(release_artifacts.sys, "version_info", (3, 14, 6)))
                    elif case == "negative-epoch":
                        epoch = -1
                        os.environ["SOURCE_DATE_EPOCH"] = "-1"
                    elif case == "ambient-epoch":
                        os.environ["SOURCE_DATE_EPOCH"] = "124"
                    elif case.startswith("package-"):
                        packages = dict(release_artifacts.EXPECTED_PACKAGES)
                        if case == "package-missing":
                            packages.pop("build")
                        elif case == "package-extra":
                            packages["extra"] = "1.0"
                        elif case == "package-wrong":
                            packages["build"] = "0.0"
                        distributions = [Distribution(name, version) for name, version in packages.items()]
                        if case == "package-duplicate":
                            distributions.append(Distribution("pyproject_hooks", packages["pyproject-hooks"]))
                        stack.enter_context(patch.object(release_artifacts.importlib.metadata, "distributions", return_value=distributions))
                    elif case.startswith("lock-"):
                        target = b / "requirements/release.txt"
                        original = target.read_text()
                        lines = original.splitlines(keepends=True)
                        replacements = {
                            "lock-option-missing": "".join(lines[1:]),
                            "lock-option-duplicate": lines[0] + original,
                            "lock-option-wrong": original.replace("--only-binary=:all:", "--no-index"),
                            "lock-hash": original.replace("--hash=sha256:0", "--hash=sha256:G", 1),
                            "lock-package-missing": "".join([lines[0], *lines[3:]]),
                            "lock-package-extra": original + "extra==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n",
                            "lock-package-wrong": original.replace("build==1.6.0", "build==0.0"),
                            "lock-package-duplicate": original + "".join(lines[1:3]),
                            "lock-bytes-diverge": original + "# different bytes, same package mapping\n",
                        }
                        target.write_text(replacements[case])
                        self.assertNotEqual(target.read_text(), original)
                    elif case in ("requirements-link", "tools-link"):
                        target = b / ("requirements" if case == "requirements-link" else "tools")
                        parked = root / "parked"
                        target.rename(parked)
                        target.symlink_to(parked, target_is_directory=True)
                    elif case == "relative-source":
                        a = Path("relative")
                    elif case == "same-source":
                        b = a
                    elif case == "source-link":
                        linked = root / "linked"
                        linked.symlink_to(a, target_is_directory=True)
                        a = linked
                    elif case == "output-nonempty":
                        output.mkdir()
                        (output / "keep").write_bytes(b"keep")
                    elif case == "output-link":
                        (root / "real-output").mkdir()
                        output.symlink_to(root / "real-output", target_is_directory=True)
                    elif case == "denylist-arbitrary":
                        denylist = root / "arbitrary"
                    elif case.startswith("denylist-"):
                        denylist = Path("/run/threadroot/denylist")
                        real_lstat = os.lstat
                        fake = root / "denylist-fixture"
                        if case == "denylist-link":
                            fake.symlink_to(root / "missing")
                        elif case == "denylist-nonregular":
                            fake.mkdir()

                        def deny_stat(path: object, *args: object, **kwargs: object):
                            if path == denylist:
                                if case == "denylist-missing":
                                    raise FileNotFoundError("synthetic missing denylist")
                                return real_lstat(fake)
                            return real_lstat(path, *args, **kwargs)

                        stack.enter_context(patch.object(os, "lstat", side_effect=deny_stat))
                    with _mock_release_phases(), self.assertRaises(ReleaseArtifactError):
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, epoch, denylist)
                    for name in ("candidate-a", "candidate-b", "evidence", "selected.pending", "selected"):
                        self.assertFalse((output / name).exists(), f"{case} created {name}")


class IdentityLifecycleTests(unittest.TestCase):
    def assert_no_success(self, output: Path) -> None:
        self.assertFalse((output / "selected").exists())
        self.assertFalse((output / "evidence/build.json").exists())
        self.assertFalse((output / "evidence/SHA256SUMS").exists())

    def test_candidate_b_drift_after_validation_blocks_evidence_and_selection(self) -> None:
        for mutation in ("changed-bytes", "same-bytes-new-inode"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                validated = []
                changed = False

                def validate(*args: object) -> None:
                    validated.append(args)

                def mutate(*args: object, **kwargs: object) -> None:
                    nonlocal changed
                    self.assertEqual(len(validated), 8)
                    path = output / "candidate-b" / expected_asset_names("0.1.0")[0]
                    original = path.read_bytes()
                    path.unlink()
                    path.write_bytes(original if mutation == "same-bytes-new-inode" else b"changed")
                    changed = True

                with _canonical_environment(), _mock_release_phases(replay=mutate, validator=validate):
                    with self.assertRaisesRegex(ReleaseArtifactError, "changed|drift|identity"):
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(changed)
                self.assert_no_success(output)

    def test_candidate_metadata_or_membership_drift_blocks_selection(self) -> None:
        for side in ("a", "b"):
            for mutation in ("mode", "hardlink", "extra", "replacement"):
                with self.subTest(side=side, mutation=mutation), TemporaryDirectory() as directory:
                    root = Path(directory)
                    a, b = _make_source(root / "a"), _make_source(root / "b")
                    output = root / "output"
                    changed = False

                    def mutate(*args: object, **kwargs: object) -> None:
                        nonlocal changed
                        candidate = output / f"candidate-{side}"
                        path = candidate / expected_asset_names("0.1.0")[0]
                        if mutation == "mode":
                            path.chmod(0o755)
                        elif mutation == "hardlink":
                            os.link(path, root / "alias")
                        elif mutation == "extra":
                            (candidate / "extra").write_bytes(b"extra")
                        else:
                            payload = path.read_bytes()
                            path.unlink()
                            path.write_bytes(payload)
                        changed = True

                    with _canonical_environment(), _mock_release_phases(replay=mutate):
                        with self.assertRaises(ReleaseArtifactError):
                            release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                    self.assertTrue(changed)
                    self.assert_no_success(output)

    def test_root_and_artifact_descriptors_are_run_scoped_and_closed(self) -> None:
        for failure in (None, "build", "validator", "replay", "scan"):
            with self.subTest(failure=failure), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                real_open, real_dup = os.open, os.dup
                acquired: list[int] = []
                held_seen = False

                def track_open(*args: object, **kwargs: object) -> int:
                    descriptor = real_open(*args, **kwargs)
                    acquired.append(descriptor)
                    return descriptor

                def track_dup(descriptor: int) -> int:
                    duplicate = real_dup(descriptor)
                    acquired.append(duplicate)
                    return duplicate

                def build(source: Path, candidate: Path, work: Path, epoch: int, **kwargs: object) -> None:
                    nonlocal held_seen
                    wanted = {(path.stat().st_dev, path.stat().st_ino) for path in (a, b, output)}
                    observed = set()
                    for fd in set(acquired):
                        try:
                            current = os.fstat(fd)
                        except OSError:
                            continue
                        observed.add((current.st_dev, current.st_ino))
                    self.assertTrue(wanted <= observed, "source/output roots are not held across the build")
                    held_seen = True
                    if failure == "build":
                        raise ReleaseArtifactError("injected build failure")
                    _seed_candidate(candidate)

                def fail(phase: str):
                    def hook(*args: object, **kwargs: object) -> None:
                        if failure == phase:
                            raise ReleaseArtifactError(f"injected {phase} failure")
                    return hook

                with _canonical_environment(), patch.object(os, "open", side_effect=track_open), patch.object(
                    os, "dup", side_effect=track_dup
                ), _mock_release_phases(build=build, validator=fail("validator"), replay=fail("replay"), scan=fail("scan")):
                    if failure:
                        with self.assertRaisesRegex(ReleaseArtifactError, "injected"):
                            release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                    else:
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(held_seen)
                for fd in set(acquired):
                    with self.assertRaises(OSError) as raised:
                        os.fstat(fd)
                    self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_all_validators_consume_payloads_and_own_source_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = _make_source(root / "a"), _make_source(root / "b")
            output = root / "output"
            captured = []
            calls = []
            real_capture = release_archives.capture_release_source

            def capture(fd: int):
                snapshot = real_capture(fd)
                captured.append(snapshot)
                return snapshot

            def validate(payload: bytes, source: object, *args: object) -> None:
                self.assertIsInstance(payload, bytes, "validator reopened archive pathname")
                self.assertIsInstance(source, release_archives.ReleaseSourceSnapshot)
                calls.append((payload, source, args))

            with _canonical_environment(), _mock_release_phases(validator=validate), patch.object(
                release_artifacts, "capture_release_source", side_effect=capture, create=True
            ):
                release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
            self.assertEqual(len(captured), 2)
            self.assertEqual(len(calls), 8)
            for index, (payload, source, args) in enumerate(calls):
                self.assertIs(source, captured[index // 4])
                self.assertEqual(payload, expected_asset_names("0.1.0")[index % 4].encode())
                self.assertEqual(args, ("0.1.0", 123) if index % 4 < 2 else (("claude",) if index % 4 == 2 else ("codex",)))

    def test_scanner_drift_jointly_revalidates_both_sets(self) -> None:
        for side in ("a", "b"):
            with self.subTest(side=side), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                changed = False

                def scan(*args: object, **kwargs: object) -> None:
                    nonlocal changed
                    path = output / f"candidate-{side}" / expected_asset_names("0.1.0")[0]
                    payload = path.read_bytes()
                    path.unlink()
                    path.write_bytes(payload)
                    changed = True

                with _canonical_environment(), _mock_release_phases(scan=scan):
                    with self.assertRaises(ReleaseArtifactError):
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(changed)
                self.assert_no_success(output)

    def test_root_swaps_after_build_leave_only_diagnostic_state(self) -> None:
        for target in ("source", "output"):
            with self.subTest(target=target), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                changed = False

                def build(source: Path, candidate: Path, work: Path, epoch: int, **kwargs: object) -> None:
                    nonlocal changed
                    _seed_candidate(candidate)
                    if not changed:
                        victim = a if target == "source" else output
                        victim.rename(root / "parked")
                        victim.mkdir()
                        (victim / "competitor").write_bytes(b"keep")
                        changed = True

                with _canonical_environment(), _mock_release_phases(build=build):
                    with self.assertRaises(ReleaseArtifactError):
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(changed)
                self.assert_no_success(output)
                self.assert_no_success(root / "parked")
                self.assertEqual(((a if target == "source" else output) / "competitor").read_bytes(), b"keep")

    def test_each_build_subprocess_is_bracketed_by_root_checks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = _make_source(root / "a"), _make_source(root / "b")
            output = root / "output"
            original_build = release_artifacts._build_one_source
            commands = []

            def run(command: list[str], environment: dict[str, str]) -> None:
                commands.append(command)
                if len(commands) == 1:
                    a.rename(root / "parked")
                    a.mkdir()
                    (a / "competitor").write_bytes(b"keep")

            with _canonical_environment(), _mock_release_phases(build=original_build), patch.object(
                release_artifacts, "_run", side_effect=run
            ), self.assertRaisesRegex(ReleaseArtifactError, "identity changed"):
                release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
            self.assertEqual(len(commands), 1)
            self.assertEqual((a / "competitor").read_bytes(), b"keep")
            self.assert_no_success(output)

    def test_missing_output_creation_never_adopts_competitor(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = _make_source(root / "a"), _make_source(root / "b")
            output = root / "output"
            real_mkdir = os.mkdir
            raced = False

            def race(path: object, mode: int = 0o777, *, dir_fd=None) -> None:
                nonlocal raced
                if not raced and (path == output or (path == "output" and dir_fd is not None)):
                    real_mkdir(path, mode, dir_fd=dir_fd)
                    raced = True
                real_mkdir(path, mode, dir_fd=dir_fd)

            with _canonical_environment(), _mock_release_phases(), patch.object(os, "mkdir", side_effect=race):
                with self.assertRaises(ReleaseArtifactError):
                    release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
            self.assertTrue(raced)
            self.assertEqual(list(output.iterdir()), [])

    def test_evidence_uses_only_original_snapshot_authority(self) -> None:
        for mutation in (None, "docker", "lock"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                docker = (a / "tools/release/Dockerfile").read_bytes()
                lock = (a / "requirements/release.txt").read_bytes()
                names = expected_asset_names("0.1.0")
                hashes = {name: hashlib.sha256(name.encode()).hexdigest() for name in names}
                expected = {
                    "schema": 1, "commit": "a" * 40, "source_date_epoch": 123,
                    "platform": "linux/amd64", "python": "3.14.7",
                    "base_image": release_artifacts.BASE_IMAGE,
                    "builder_definition_sha256": hashlib.sha256(docker + b"\0" + lock).hexdigest(),
                    "packages": dict(release_artifacts.EXPECTED_PACKAGES),
                    "artifacts": [{"name": name, "sha256": hashes[name], "size": len(name.encode())} for name in names],
                }

                def scan(*args: object, **kwargs: object) -> None:
                    if mutation:
                        target = a / ("tools/release/Dockerfile" if mutation == "docker" else "requirements/release.txt")
                        target.unlink()
                        target.write_bytes(b"new authority must never be used")

                with _canonical_environment(), _mock_release_phases(scan=scan):
                    try:
                        actual_hashes = release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                    except ReleaseArtifactError:
                        self.assertIsNotNone(mutation)
                        self.assert_no_success(output)
                        continue
                self.assertEqual(actual_hashes, hashes)
                self.assertEqual(json.loads((output / "evidence/build.json").read_text()), expected)
                self.assertEqual((output / "evidence/build.json").read_text(), json.dumps(expected, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
                self.assertEqual((output / "evidence/SHA256SUMS").read_text(), "".join(f"{hashes[name]}  {name}\n" for name in sorted(names)))

    def test_replay_consumes_captured_sdist_and_rejects_changed_or_linked_wheel(self) -> None:
        for mutation in (None, "changed", "symlink"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                original_replay = release_artifacts._replay_sdist
                extracted = []

                def extract(payload: bytes, destination: Path, **kwargs: object) -> None:
                    self.assertIsInstance(payload, bytes, "replay extraction reopens a pathname")
                    self.assertEqual(payload, expected_asset_names("0.1.0")[1].encode())
                    extracted.append(payload)
                    (destination / "threadroot-0.1.0").mkdir(parents=True)

                def run(command: list[str], environment: dict[str, str]) -> None:
                    destination = Path(command[command.index("--outdir") + 1])
                    wheel = destination / expected_asset_names("0.1.0")[0]
                    if mutation == "symlink":
                        wheel.symlink_to(output / "candidate-a" / wheel.name)
                    else:
                        wheel.write_bytes(b"changed" if mutation else wheel.name.encode())

                with _canonical_environment(), _mock_release_phases(replay=original_replay), patch.object(
                    release_artifacts, "_run", side_effect=run
                ), patch.object(release_artifacts, "extract_regular_tar_payload", side_effect=extract, create=True), patch.object(
                    release_artifacts, "extract_regular_tar", side_effect=extract, create=True
                ):
                    if mutation:
                        with self.assertRaises(ReleaseArtifactError):
                            release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                        self.assert_no_success(output)
                    else:
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(extracted)


class PromotionIdentityTests(unittest.TestCase):
    def test_promotion_never_reopens_candidate_to_choose_copy_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            paths = ArtifactSet.load(candidate, "0.1.0")
            original_open = os.open
            with _bound_test_candidate(root, paths) as (bindings, output, pair, guard):
                candidate_fd = next(item.fd for item in bindings.directories if item.path == candidate)

                def reject_reopen(path: object, flags: int, *args: object, **kwargs: object) -> int:
                    if kwargs.get("dir_fd") == candidate_fd or isinstance(path, Path) and path.parent == candidate:
                        raise AssertionError("promotion reopened candidate pathname")
                    return original_open(path, flags, *args, **kwargs)

                with patch.object(os, "open", side_effect=reject_reopen):
                    release_artifacts._promote(bindings, output, pair, guard)
            for item in pair.candidate_a:
                self.assertEqual((root / "selected" / item.name).read_bytes(), item.payload)

    def test_pending_table_drift_during_last_hash_blocks_publication(self) -> None:
        for mutation in ("extra", "earlier-replacement"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                names = expected_asset_names("0.1.0")
                original_publish, original_read = release_artifacts._exclusive_publish, os.read
                checking = False
                changed = False

                def publish(*args: object, **kwargs: object) -> None:
                    nonlocal checking
                    checking = True
                    original_publish(*args, **kwargs)

                def mutate(fd: int, size: int) -> bytes:
                    nonlocal changed
                    payload = original_read(fd, size)
                    last = output / "selected.pending" / names[-1]
                    if checking and not changed and payload and last.exists():
                        current, target = os.fstat(fd), last.stat()
                        if (current.st_dev, current.st_ino) == (target.st_dev, target.st_ino):
                            if mutation == "extra":
                                (last.parent / "extra").write_bytes(b"unapproved")
                            else:
                                first = last.parent / names[0]
                                data = first.read_bytes()
                                first.unlink()
                                first.write_bytes(data)
                            changed = True
                    return payload

                with _canonical_environment(), _mock_release_phases(), patch.object(
                    release_artifacts, "_exclusive_publish", side_effect=publish
                ), patch.object(os, "read", side_effect=mutate):
                    with self.assertRaisesRegex(ReleaseArtifactError, "promotion failed"):
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(changed)
                self.assertFalse((output / "selected").exists())

    def test_short_writes_complete_snapshot_payloads_and_close_all_fds(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = _make_source(root / "a"), _make_source(root / "b")
            output = root / "output"
            real_write = os.write
            shortened = False

            def short_write(fd: int, payload: bytes) -> int:
                nonlocal shortened
                shortened = True
                return real_write(fd, payload[:3])

            with _canonical_environment(), _mock_release_phases(), patch.object(os, "write", side_effect=short_write):
                release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
            self.assertTrue(shortened)
            self.assertEqual(sorted(path.name for path in (output / "selected").iterdir()), sorted(expected_asset_names("0.1.0")))
            for name in expected_asset_names("0.1.0"):
                path = output / "selected" / name
                self.assertEqual(path.read_bytes(), name.encode())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
                self.assertEqual(path.stat().st_nlink, 1)

    def test_pending_mutations_preserve_competitors_and_close_descriptors(self) -> None:
        mutations = ("extra", "bytes", "mode", "hardlink", "member-replacement", "pending-replacement",
                     "selected-directory", "selected-file", "selected-symlink", "selected-broken")
        for mutation in mutations:
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                a, b = _make_source(root / "a"), _make_source(root / "b")
                output = root / "output"
                original = release_artifacts._exclusive_publish
                original_open, original_dup = os.open, os.dup
                acquired = []
                changed = False
                competitor_identity = None

                def track_open(*args: object, **kwargs: object) -> int:
                    fd = original_open(*args, **kwargs)
                    acquired.append(fd)
                    return fd

                def track_dup(fd: int) -> int:
                    duplicate = original_dup(fd)
                    acquired.append(duplicate)
                    return duplicate

                def mutate(*args: object, **kwargs: object) -> None:
                    nonlocal changed, competitor_identity
                    pending = output / "selected.pending"
                    member = pending / expected_asset_names("0.1.0")[0]
                    selected = output / "selected"
                    if mutation == "extra":
                        (pending / "extra").write_bytes(b"extra")
                    elif mutation == "bytes":
                        member.write_bytes(b"unapproved")
                    elif mutation == "mode":
                        member.chmod(0o777)
                    elif mutation == "hardlink":
                        os.link(member, root / "alias")
                    elif mutation == "member-replacement":
                        original_bytes = member.read_bytes()
                        member.unlink()
                        member.write_bytes(original_bytes)
                    elif mutation == "pending-replacement":
                        pending.rename(root / "parked-pending")
                        pending.mkdir()
                        (pending / "keep").write_bytes(b"competitor")
                    elif mutation == "selected-directory":
                        selected.mkdir()
                    elif mutation == "selected-file":
                        selected.write_bytes(b"competitor")
                    else:
                        target = root / "target"
                        if mutation == "selected-symlink":
                            target.write_bytes(b"competitor")
                        selected.symlink_to(target)
                    if mutation.startswith("selected-"):
                        competitor_identity = selected.lstat().st_ino
                    changed = True
                    original(*args, **kwargs)

                with _canonical_environment(), _mock_release_phases(), patch.object(os, "open", side_effect=track_open), patch.object(
                    os, "dup", side_effect=track_dup
                ), patch.object(release_artifacts, "_exclusive_publish", side_effect=mutate):
                    with self.assertRaisesRegex(ReleaseArtifactError, "promotion|changed|identity"):
                        release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
                self.assertTrue(changed)
                if competitor_identity is not None:
                    self.assertEqual((output / "selected").lstat().st_ino, competitor_identity)
                else:
                    self.assertFalse((output / "selected").exists())
                if mutation == "pending-replacement":
                    self.assertEqual((output / "selected.pending/keep").read_bytes(), b"competitor")
                for fd in set(acquired):
                    with self.assertRaises(OSError) as raised:
                        os.fstat(fd)
                    self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_pending_write_failure_leaves_owned_pending(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = _make_source(root / "a"), _make_source(root / "b")
            output = root / "output"
            original = os.write
            failed = False

            def fail(fd: int, payload: bytes) -> int:
                nonlocal failed
                if (output / "selected.pending").exists():
                    failed = True
                    raise OSError("synthetic pending write failure")
                return original(fd, payload)

            with _canonical_environment(), _mock_release_phases(), patch.object(os, "write", side_effect=fail):
                with self.assertRaisesRegex(ReleaseArtifactError, "promotion failed"):
                    release_artifacts.build_and_verify(a, b, output, "a" * 40, 123)
            self.assertTrue(failed)
            self.assertTrue((output / "selected.pending").is_dir())
            self.assertFalse((output / "selected").exists())


class BuildAndVerifyTests(unittest.TestCase):
    def test_byte_identical_wheel_with_covert_fixed_header_fails_before_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            wheel = root / "valid.whl"
            order, payloads = _wheel_payloads(source_a)
            _write_wheel(wheel, order, payloads)
            malformed = _mutate_zip_fixed_header(
                wheel.read_bytes(),
                "consistent-needed",
            )

            def build(
                source: Path,
                candidate: Path,
                work: Path,
                epoch: int,
                **kwargs: object,
            ) -> None:
                candidate.mkdir(parents=True, exist_ok=True)
                for name in expected_asset_names("0.1.0"):
                    payload = malformed if name.endswith(".whl") else name.encode()
                    (candidate / name).write_bytes(payload)

            with (
                _canonical_environment(WHEEL_EPOCH),
                patch.object(
                    release_artifacts,
                    "_build_one_source",
                    side_effect=build,
                ),
                patch.object(release_artifacts, "validate_sdist_payload"),
                patch.object(release_artifacts, "validate_host_zip_payload"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan"),
                patch.object(
                    release_artifacts,
                    "extract_regular_zip_payload",
                    side_effect=_fake_extract,
                ),
                patch.object(
                    release_artifacts,
                    "extract_regular_tar_payload",
                    side_effect=_fake_extract,
                ),
                self.assertRaises(ReleaseArtifactError),
            ):
                release_artifacts.build_and_verify(
                    source_a,
                    source_b,
                    output,
                    "a" * 40,
                    WHEEL_EPOCH,
                )

            wheel_name = expected_asset_names("0.1.0")[0]
            self.assertEqual(
                (output / "candidate-a" / wheel_name).read_bytes(),
                (output / "candidate-b" / wheel_name).read_bytes(),
            )
            self.assertFalse((output / "selected").exists())
            self.assertFalse((output / "selected.pending").exists())
            self.assertFalse((output / "evidence/build.json").exists())
            self.assertFalse((output / "evidence/SHA256SUMS").exists())

    def test_byte_identical_sdist_with_unaligned_zero_suffix_fails_before_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source_a))
            malformed = _gzip_tar_payload(
                gzip.decompress(valid.read_bytes()) + b"\0"
            )

            def build(
                source: Path,
                candidate: Path,
                work: Path,
                epoch: int,
                **kwargs: object,
            ) -> None:
                candidate.mkdir(parents=True, exist_ok=True)
                for name in expected_asset_names("0.1.0"):
                    payload = malformed if name.endswith(".tar.gz") else name.encode()
                    (candidate / name).write_bytes(payload)

            with (
                _canonical_environment(WHEEL_EPOCH),
                patch.object(
                    release_artifacts,
                    "_build_one_source",
                    side_effect=build,
                ),
                patch.object(release_artifacts, "validate_wheel_payload"),
                patch.object(release_artifacts, "validate_host_zip_payload"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan"),
                patch.object(
                    release_artifacts,
                    "extract_regular_zip_payload",
                    side_effect=_fake_extract,
                ),
                patch.object(
                    release_artifacts,
                    "extract_regular_tar_payload",
                    side_effect=_fake_extract,
                ),
                self.assertRaises(ReleaseArtifactError),
            ):
                release_artifacts.build_and_verify(
                    source_a,
                    source_b,
                    output,
                    "a" * 40,
                    WHEEL_EPOCH,
                )

            sdist_name = expected_asset_names("0.1.0")[1]
            self.assertEqual(
                (output / "candidate-a" / sdist_name).read_bytes(),
                (output / "candidate-b" / sdist_name).read_bytes(),
            )
            self.assertFalse((output / "selected").exists())
            self.assertFalse((output / "selected.pending").exists())
            self.assertFalse((output / "evidence/build.json").exists())
            self.assertFalse((output / "evidence/SHA256SUMS").exists())

    def test_byte_identical_malformed_archives_fail_before_promotion(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            wheel = root / "valid.whl"
            order, payloads = _wheel_payloads(source_a)
            _write_wheel(wheel, order, payloads)
            malformed = _add_trailing_bytes_to_last_deflate_stream(
                wheel.read_bytes()
            )

            def build(
                source: Path,
                candidate: Path,
                work: Path,
                epoch: int,
                **kwargs: object,
            ) -> None:
                candidate.mkdir(parents=True, exist_ok=True)
                for name in expected_asset_names("0.1.0"):
                    payload = malformed if name.endswith(".whl") else name.encode()
                    (candidate / name).write_bytes(payload)

            with (
                _canonical_environment(WHEEL_EPOCH),
                patch.object(
                    release_artifacts,
                    "_build_one_source",
                    side_effect=build,
                ),
                patch.object(release_artifacts, "validate_sdist_payload"),
                patch.object(release_artifacts, "validate_host_zip_payload"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan"),
                patch.object(
                    release_artifacts,
                    "extract_regular_zip_payload",
                    side_effect=_fake_extract,
                ),
                patch.object(
                    release_artifacts,
                    "extract_regular_tar_payload",
                    side_effect=_fake_extract,
                ),
                self.assertRaisesRegex(
                    ReleaseArtifactError,
                    "invalid ZIP compressed boundary",
                ),
            ):
                release_artifacts.build_and_verify(
                    source_a,
                    source_b,
                    output,
                    "a" * 40,
                    WHEEL_EPOCH,
                )

            wheel_name = expected_asset_names("0.1.0")[0]
            self.assertEqual(
                (output / "candidate-a" / wheel_name).read_bytes(),
                (output / "candidate-b" / wheel_name).read_bytes(),
            )
            self.assertFalse((output / "selected").exists())
            self.assertFalse((output / "selected.pending").exists())
            self.assertFalse((output / "evidence/build.json").exists())

    def test_byte_identical_sdist_with_hidden_metadata_fails_before_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            valid = root / "valid.tar.gz"
            _write_sdist(valid, _sdist_entries(source_a))
            malformed = _gzip_tar_payload(
                _prepend_tar_metadata_header(
                    gzip.decompress(valid.read_bytes()),
                    b"g",
                )
            )

            def build(
                source: Path,
                candidate: Path,
                work: Path,
                epoch: int,
                **kwargs: object,
            ) -> None:
                candidate.mkdir(parents=True, exist_ok=True)
                for name in expected_asset_names("0.1.0"):
                    payload = malformed if name.endswith(".tar.gz") else name.encode()
                    (candidate / name).write_bytes(payload)

            with (
                _canonical_environment(WHEEL_EPOCH),
                patch.object(
                    release_artifacts,
                    "_build_one_source",
                    side_effect=build,
                ),
                patch.object(release_artifacts, "validate_wheel_payload"),
                patch.object(release_artifacts, "validate_host_zip_payload"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan"),
                patch.object(
                    release_artifacts,
                    "extract_regular_zip_payload",
                    side_effect=_fake_extract,
                ),
                patch.object(
                    release_artifacts,
                    "extract_regular_tar_payload",
                    side_effect=_fake_extract,
                ),
                self.assertRaises(ReleaseArtifactError),
            ):
                release_artifacts.build_and_verify(
                    source_a,
                    source_b,
                    output,
                    "a" * 40,
                    WHEEL_EPOCH,
                )

            sdist_name = expected_asset_names("0.1.0")[1]
            self.assertEqual(
                (output / "candidate-a" / sdist_name).read_bytes(),
                (output / "candidate-b" / sdist_name).read_bytes(),
            )
            self.assertFalse((output / "selected").exists())
            self.assertFalse((output / "selected.pending").exists())
            self.assertFalse((output / "evidence/build.json").exists())
            self.assertFalse((output / "evidence/SHA256SUMS").exists())

    def test_lock_requires_exactly_one_approved_option(self) -> None:
        with TemporaryDirectory() as directory:
            lock = Path(directory) / "release.txt"
            row = "build==1.6.0 " + "\\\n" + "    --hash=sha256:" + "0" * 64 + "\n"
            lock.write_text(row, encoding="utf-8")
            with self.assertRaises(ReleaseArtifactError):
                release_artifacts._parse_lock_versions(lock.read_text())
            lock.write_text("--only-binary=:all:\n" + row, encoding="utf-8")
            self.assertEqual(release_artifacts._parse_lock_versions(lock.read_text()), {"build": "1.6.0"})
            lock.write_text("--only-binary=:all:\n--only-binary=:all:\n" + row, encoding="utf-8")
            with self.assertRaises(ReleaseArtifactError):
                release_artifacts._parse_lock_versions(lock.read_text())

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
            with patch.object(release_artifacts, "extract_regular_tar_payload", side_effect=fake_extract), patch.object(release_artifacts, "_run", side_effect=fake_run):
                with self.assertRaises(ReleaseArtifactError):
                    _replay_test_candidate(artifacts, evidence, 1)

    def test_pending_mode_mutation_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            original_publish = release_artifacts._exclusive_publish
            def mutate(*args: object, **kwargs: object) -> None:
                pending = root / "selected.pending" / expected_asset_names("0.1.0")[0]
                pending.chmod(0o777)
                original_publish(*args, **kwargs)
            with patch.object(release_artifacts, "_exclusive_publish", side_effect=mutate):
                with self.assertRaises(ReleaseArtifactError):
                    _promote_test_candidate(root, artifacts)
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
            for denylist in (None, Path("/run/threadroot/denylist")):
                with self.subTest(denylist=denylist), patch.object(release_artifacts.subprocess, "run") as run:
                    release_artifacts._scan(source_a, source_b, artifacts, unpacked, denylist)
                command = run.call_args.args[0]
                prefix = [release_artifacts.sys.executable, str(scanner)]
                if denylist:
                    prefix.extend(("--denylist", "/run/threadroot/denylist"))
                self.assertEqual(command, [*prefix, str(source_a), str(source_b), *[str(candidate / name) for name in expected_asset_names("0.1.0")], *[str(unpacked / name) for name in ("wheel", "sdist", "claude", "codex")]])
                self.assertEqual(run.call_args.kwargs, {
                    "check": True, "shell": False, "capture_output": True, "text": True,
                    "env": {"PATH": release_artifacts.os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "TZ": "UTC"},
                })

    def test_release_lock_parser_rejects_malformed_duplicate_and_extra_lines(self) -> None:
        with TemporaryDirectory() as directory:
            lock = Path(directory) / "release.txt"
            valid = "--only-binary=:all:\npackage==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n"
            self.assertEqual(release_artifacts._parse_lock_versions(valid), {"package": "1.0"})
            for mutation in (
                valid.replace("package==1.0", "package==1.0\npackage==1.0"),
                valid.replace("--only-binary=:all:", "--index-url=https://example.invalid"),
                valid.replace("--hash=sha256:", "--hash=sha256:not-a-digest"),
            ):
                lock.write_text(mutation, encoding="utf-8")
                with self.assertRaises(ReleaseArtifactError):
                    release_artifacts._parse_lock_versions(lock.read_text())

    def test_real_task3_sdist_validates_replays_and_unpacks_without_pax_comment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = _make_sdist_source(root)
            sdist = root / "threadroot-0.1.0.tar.gz"
            _write_sdist(sdist, _sdist_entries(source), gzip_mtime=WHEEL_EPOCH)
            release_archives.validate_sdist(sdist, source, "0.1.0", WHEEL_EPOCH)
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
                _replay_test_candidate(artifacts, evidence, WHEEL_EPOCH)
            release_artifacts.extract_regular_tar_payload(sdist.read_bytes(), evidence / "unpacked")
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
            with patch.object(release_artifacts, "_validate_environment"), self.assertRaisesRegex(ReleaseArtifactError, "source roots must be distinct"):
                release_artifacts.build_and_verify(source, source, root / "output", "a" * 40, 123)

    def test_input_gate_rejects_nonempty_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = _make_source(root / "a")
            source_b = _make_source(root / "b")
            output = root / "output"
            output.mkdir()
            (output / "unexpected").write_bytes(b"x")
            with patch.object(release_artifacts, "_validate_environment"), self.assertRaisesRegex(ReleaseArtifactError, "output must be missing or empty"):
                release_artifacts.build_and_verify(source_a, source_b, output, "a" * 40, 123)

    def test_input_gate_rejects_symlink_source_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            with patch.object(release_artifacts, "_validate_environment"), self.assertRaisesRegex(ReleaseArtifactError, "real directories"):
                release_artifacts.build_and_verify(real, link, root / "output", "a" * 40, 123)

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

            def fake_build(source: Path, candidate: Path, work: Path, epoch: int, **kwargs: object) -> None:
                _seed_candidate(candidate)

            with (
                patch.object(release_artifacts, "_validate_environment"),
                patch.object(release_artifacts, "_build_one_source", side_effect=fake_build) as build,
                patch.object(release_artifacts, "validate_wheel_payload"),
                patch.object(release_artifacts, "validate_sdist_payload"),
                patch.object(release_artifacts, "validate_host_zip_payload"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan"),
                patch.object(release_artifacts, "extract_regular_zip_payload", side_effect=_fake_extract),
                patch.object(release_artifacts, "extract_regular_tar_payload", side_effect=_fake_extract),
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

            def fake_build(source: Path, candidate: Path, work: Path, epoch: int, **kwargs: object) -> None:
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

            def fake_build(source: Path, candidate: Path, work: Path, epoch: int, **kwargs: object) -> None:
                _seed_candidate(candidate)

            with (
                patch.object(release_artifacts, "_validate_environment"),
                patch.object(release_artifacts, "_build_one_source", side_effect=fake_build),
                patch.object(release_artifacts, "validate_wheel_payload"),
                patch.object(release_artifacts, "validate_sdist_payload"),
                patch.object(release_artifacts, "validate_host_zip_payload"),
                patch.object(release_artifacts, "_replay_sdist"),
                patch.object(release_artifacts, "_scan", side_effect=ReleaseArtifactError("scan failed")),
                patch.object(release_artifacts, "extract_regular_zip_payload", side_effect=_fake_extract),
                patch.object(release_artifacts, "extract_regular_tar_payload", side_effect=_fake_extract),
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
                patch.object(release_artifacts, "extract_regular_tar_payload", side_effect=fake_extract),
                patch.object(release_artifacts, "_run", side_effect=fake_run),
            ):
                with self.assertRaisesRegex(ReleaseArtifactError, "replay bytes differ"):
                    _replay_test_candidate(artifacts, evidence, 1)

    def test_copy_failure_leaves_only_pending_promotion_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
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
                    _promote_test_candidate(root, artifacts)
            self.assertTrue((root / "selected.pending").is_dir())
            self.assertFalse((root / "selected").exists())

    def test_promotion_rejects_existing_broken_selected_link(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            _seed_candidate(candidate)
            artifacts = ArtifactSet.load(candidate, "0.1.0")
            (root / "selected").symlink_to(root / "missing")
            with self.assertRaisesRegex(ReleaseArtifactError, "already exists"):
                _promote_test_candidate(root, artifacts)
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
