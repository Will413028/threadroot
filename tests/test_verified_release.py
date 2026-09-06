from __future__ import annotations

import ast
import builtins
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib
import inspect
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, call, patch

from scripts import build_verified_release as entry
from scripts import release_candidate as authority
from scripts.release_artifacts import BASE_IMAGE, EXPECTED_PACKAGES


SHA = "a" * 40
IMAGE = "threadroot-release-builder:" + "0" * 64
STATUS = ("status", "--porcelain=v1", "--untracked-files=all")
RESOLVE = ("rev-parse", "--verify", SHA + "^{commit}")
KIND = ("cat-file", "-t", SHA)
EPOCH = ("show", "-s", "--format=%ct", SHA)
PERIMETER = "docker artifact perimeter is incomplete"
CONTEXT = dict(image=IMAGE, source_a=Path("/outside/source-a"),
               source_b=Path("/outside/source-b"), output=Path("/outside/build"),
               commit=SHA, epoch=123, uid=501, gid=20, denylist=None)
EXPECTED_RUNNER_FILES = (
    ".dockerignore", "requirements/release.txt", "tools/release/Dockerfile",
    "pyproject.toml", "scripts/build_verified_release.py", "scripts/release_archives.py",
    "scripts/release_artifacts.py", "scripts/build_release.py", "scripts/check_public.py",
    "scripts/release_candidate.py",
)


@contextmanager
def outer_fixture(*, git_values=None, parity=True):
    """Keep filesystem effects real; isolate Git, extraction, and Docker."""
    with TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        repository = root / "repository"
        repository.mkdir()
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w", format=tarfile.PAX_FORMAT,
                          pax_headers={"comment": SHA}) as archive_file:
            for name, data in (("tools", None), ("tools/release", None),
                               ("requirements", None),
                               ("tools/release/Dockerfile", b"FROM pinned\n"),
                               ("requirements/release.txt", b"lock\n")):
                member = tarfile.TarInfo(name)
                member.mode = 0o755 if data is None else 0o644
                member.type = tarfile.DIRTYPE if data is None else tarfile.REGTYPE
                member.size = len(data) if data else 0
                archive_file.addfile(member, io.BytesIO(data) if data else None)

        def authority_git(argv, **kwargs):
            if argv == ["git", "archive", "--format=tar", SHA]:
                return subprocess.CompletedProcess(argv, 0, payload.getvalue())
            if argv == ["git", "rev-parse", "--show-toplevel"]:
                return subprocess.CompletedProcess(argv, 0, str(repository))
            if argv == ["git", "show", "-s", "--format=%ct", SHA]:
                return subprocess.CompletedProcess(argv, 0, "123\n")
            raise AssertionError(argv)

        stack.enter_context(patch.object(authority, "subprocess", types.SimpleNamespace(
            run=authority_git, SubprocessError=subprocess.SubprocessError)))
        events = []
        answers = {STATUS: "", RESOLVE: SHA + "\n", KIND: "commit\n", EPOCH: "123\n"}
        answers.update(git_values or {})

        def git(*args):
            events.append(("git", args))
            return answers[args]

        def archive(commit):
            events.append(("archive", commit))
            return b"synthetic git archive"

        def extract(payload, destination, *, expected_global_comment):
            destination.mkdir(parents=True)
            (destination / "tools/release").mkdir(parents=True)
            (destination / "requirements").mkdir()
            (destination / "tools/release/Dockerfile").write_bytes(b"FROM pinned\n")
            (destination / "requirements/release.txt").write_bytes(b"lock\n")
        def populate(destination):
            if destination.name == "source-b":
                artifacts = []
                names = ("threadroot-0.1.0-py3-none-any.whl", "threadroot-0.1.0.tar.gz",
                         "threadroot-claude-0.1.0.zip", "threadroot-codex-0.1.0.zip")
                for name in names:
                    data = (name + "\n").encode()
                    artifacts.append(dict(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
                    for group in ("candidate-a", "candidate-b", "selected"):
                        target = destination.parent / "build" / group
                        target.mkdir(parents=True, exist_ok=True)
                        (target / name).write_bytes(data)
                evidence = destination.parent / "build/evidence"
                evidence.mkdir()
                evidence.joinpath("build.json").write_bytes(authority._canonical_json(dict(
                    schema=1, commit=SHA, source_date_epoch=123, platform="linux/amd64",
                    python="3.14.7", base_image=BASE_IMAGE, builder_definition_sha256="0" * 64,
                    packages=EXPECTED_PACKAGES, artifacts=artifacts)))
                evidence.joinpath("SHA256SUMS").write_text("".join(
                    f"{item['sha256']}  {item['name']}\n" for item in sorted(artifacts, key=lambda item: item['name'])))

        # Reload binds today's eager import to the dependency seam. A future
        # function-local import uses exactly the same seam, without a new target.
        extractor = stack.enter_context(patch("scripts.release_archives.extract_regular_tar_payload", side_effect=extract))
        importlib.reload(entry)
        stack.enter_context(patch.object(entry, "REPOSITORY", repository))
        fixture = types.SimpleNamespace(root=root, repository=repository, output=root / "output",
            authority=root / "authority.json", events=events, extractor=extractor,
            git=stack.enter_context(patch.object(entry, "_git", side_effect=git)),
            parity=stack.enter_context(patch.object(entry, "_runner_bytes_match", return_value=parity)),
            archive=stack.enter_context(patch.object(entry, "_archive_commit", side_effect=archive)),
            run=Mock(return_value=subprocess.CompletedProcess([], 0, "", "")))
        def docker(argv, **kwargs):
            result = fixture.run(argv, **kwargs)
            if argv[:2] == ["docker", "run"]:
                populate(fixture.output / "source-b")
            return result
        stack.enter_context(patch.object(entry, "subprocess", types.SimpleNamespace(
            run=docker, CalledProcessError=subprocess.CalledProcessError)))
        stack.enter_context(patch.object(entry.os, "getuid", return_value=501, create=True))
        stack.enter_context(patch.object(entry.os, "getgid", return_value=20, create=True))
        try:
            yield fixture
        finally:
            stack.close()
            importlib.reload(entry)


def invoke(args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = entry.main(args)
    return status, stdout.getvalue(), stderr.getvalue()


def outer_args(fixture, **changes):
    values = {"commit": SHA, "output": str(fixture.output),
              "authority-record": str(fixture.authority), **changes}
    return [item for key, value in values.items() for item in ("--" + key, str(value))]


def validate(argv, context):
    # Support the intended bound validator and today's legacy implementation
    # without making private parameter ordering a tested public contract.
    if "image" in inspect.signature(entry._validate_docker_run_argv).parameters:
        entry._validate_docker_run_argv(argv, **context)
    else:
        entry._validate_docker_run_argv(argv)


class VerifiedReleaseTests(unittest.TestCase):
    def test_outer_mode_requires_an_absolute_missing_external_authority_record(self):
        for kind in ("missing", "relative", "existing", "repository", "candidate", "parent", "control", "symlink"):
            with self.subTest(kind=kind), outer_fixture() as fixture:
                value = fixture.authority
                if kind == "relative": value = Path("authority.json")
                elif kind == "existing": value.write_bytes(b"keep")
                elif kind == "repository": value = fixture.repository / "authority.json"
                elif kind == "candidate": value = fixture.output / "authority.json"
                elif kind == "parent": value = fixture.root / "missing/authority.json"
                elif kind == "control": value = fixture.root / "secret\nname"
                elif kind == "symlink": value.symlink_to(fixture.root / "absent")
                args = outer_args(fixture, **{"authority-record": value})
                if kind == "missing": args = args[:-2]
                self.assert_rejected(fixture, args, "candidate integrity verification failed")

    def test_authority_preflight_fails_before_any_docker_command(self):
        with outer_fixture() as fixture:
            fixture.authority.write_bytes(b"competitor")
            self.assert_rejected(fixture, outer_args(fixture), "candidate integrity verification failed")
            self.assertEqual(fixture.authority.read_bytes(), b"competitor")

    def test_inside_mode_rejects_authority_record(self):
        with outer_fixture() as fixture:
            result = invoke(outer_args(fixture, epoch=123) + ["--inside"])
            self.assertEqual(result, (1, "", "candidate integrity verification failed\n"))
            fixture.run.assert_not_called()

    def test_builder_binds_then_verifies_before_fixed_success_message(self):
        with outer_fixture() as fixture:
            self.assertEqual(invoke(outer_args(fixture)), (0, "verified release build completed\n", ""))
            self.assertEqual(authority.verify_candidate(fixture.authority, SHA), fixture.output)
            self.assertEqual({p.name for p in fixture.root.iterdir()}, {"repository", "output", "authority.json"})

    def test_builder_failure_never_creates_a_success_receipt(self):
        with outer_fixture() as fixture:
            original = authority.verify_candidate
            def fail_after_bind(record, commit):
                original(record, commit)
                raise authority.CandidateIntegrityError("SYNTHETIC_PRIVATE_PAYLOAD")
            with patch.object(authority, "verify_candidate", side_effect=fail_after_bind):
                self.assertEqual(invoke(outer_args(fixture)), (1, "", "candidate integrity verification failed\n"))
            self.assertTrue(fixture.authority.exists())
            self.assertEqual({p.name for p in fixture.root.iterdir()}, {"repository", "output", "authority.json"})

    def test_outer_builder_with_real_git_exports_and_authority(self):
        from tests import test_release_candidate as fixtures
        fixture = fixtures.CandidateAuthorityTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._prepare()
        for name, data in (("tools/release/Dockerfile", b"FROM pinned\n"),
                           ("requirements/release.txt", b"lock\n")):
            target = fixture.repository / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        fixture._git("add", "tools/release/Dockerfile", "requirements/release.txt")
        fixture._git("commit", "--no-gpg-sign", "-qm", "synthetic builder inputs")
        commit = fixture._git("rev-parse", "HEAD").stdout.strip()
        output = fixture.root / "actual-output"
        def artifact_phase(argv, phase, paths):
            if phase == "artifact phase":
                shutil.copytree(fixture.candidate / "build", output / "build", dirs_exist_ok=True)
                evidence = output / "build/evidence/build.json"
                data = json.loads(evidence.read_bytes())
                data.update(commit=commit, source_date_epoch=int(fixture._git(
                    "show", "-s", "--format=%ct", commit).stdout))
                evidence.write_bytes(authority._canonical_json(data))
            return set()
        with fixture._in_repository(), patch.object(entry, "REPOSITORY", fixture.repository), \
             patch.object(entry, "_host_identity", return_value=(501, 20)), \
             patch.object(entry, "_runner_bytes_match", return_value=True), \
             patch.object(entry, "_run_docker", side_effect=artifact_phase):
            self.assertEqual(invoke(["--commit", commit, "--output", str(output),
                                    "--authority-record", str(fixture.record)]),
                             (0, "verified release build completed\n", ""))
            self.assertEqual(authority.verify_candidate(fixture.record, commit), output)
            receipt = fixture.root / "success.json"
            authority.record_successful_attempt(fixture.record, commit, receipt)
            self.assertEqual(authority.verify_successful_attempt(receipt, fixture.record, commit), output)

    def assert_rejected(self, fixture, args, message, *, no_git=False):
        result = invoke(args)
        with self.subTest(check="public error"):
            self.assertEqual(result, (1, "", message + "\n"))
        with self.subTest(check="no archive/extraction/subprocess/output"):
            fixture.archive.assert_not_called()
            fixture.extractor.assert_not_called()
            fixture.run.assert_not_called()
            if no_git:
                fixture.git.assert_not_called()
            self.assertFalse(fixture.output.exists())

    def test_image_tag_depends_on_dockerfile_and_lock_bytes(self):
        with TemporaryDirectory() as directory:
            dockerfile, lock = Path(directory) / "Dockerfile", Path(directory) / "release.txt"
            dockerfile.write_bytes(b"FROM pinned\n")
            lock.write_bytes(b"build==1.6.0\n")
            self.assertEqual(entry.canonical_image_tag(dockerfile, lock),
                "threadroot-release-builder:" + hashlib.sha256(b"FROM pinned\n\0build==1.6.0\n").hexdigest())
            first = entry.canonical_image_tag(dockerfile, lock)
            lock.write_bytes(b"build==1.6.1\n")
            second = entry.canonical_image_tag(dockerfile, lock)
            dockerfile.write_bytes(b"FROM other\n")
            self.assertNotEqual(first, second)
            self.assertNotEqual(second, entry.canonical_image_tag(dockerfile, lock))

    def test_builder_image_requires_exact_approved_tag_before_argv_acceptance(self):
        prefix = "threadroot-release-builder:"
        for image in (IMAGE, prefix + "0123456789abcdef" * 4):
            with self.subTest(valid=image):
                context = {**CONTEXT, "image": image}
                argv = entry.docker_run_argv(**context)
                self.assertIn(image, argv)
                validate(argv, context)
        baseline = entry.docker_run_argv(**CONTEXT)
        for image in ("--privileged", "--network=host", "", "other-builder:" + "a" * 64,
                      prefix + "a" * 63, prefix + "A" * 64, prefix + "g" * 64):
            context = {**CONTEXT, "image": image}
            with self.subTest(image=image, boundary="public builder"):
                with self.assertRaises(entry.VerifiedReleaseError) as raised:
                    entry.docker_run_argv(**context)
                self.assertEqual(str(raised.exception), "invalid builder image")
            # A matching malicious context must not legitimize an option token.
            mutated = list(baseline)
            mutated[baseline.index(IMAGE)] = image
            with self.subTest(image=image, boundary="perimeter validator"):
                with self.assertRaises(entry.VerifiedReleaseError) as raised:
                    validate(mutated, context)
                self.assertEqual(str(raised.exception), "invalid builder image")

    def test_invalid_builder_image_stops_main_before_any_docker_subprocess(self):
        with outer_fixture() as fixture:
            with patch.object(entry, "canonical_image_tag", return_value="--privileged") as image_tag:
                result = invoke(outer_args(fixture))
            source = fixture.output / "source-a"
            image_tag.assert_called_once_with(source / "tools/release/Dockerfile", source / "requirements/release.txt")
            with self.subTest(check="stable public error"):
                self.assertEqual(result, (1, "", "invalid builder image\n"))
            fixture.run.assert_not_called()

    def test_docker_run_is_offline_read_only_and_unprivileged(self):
        argv = entry.docker_run_argv(**CONTEXT)
        self.assertEqual(argv[:20], ["docker", "run", "--rm", "--platform", "linux/amd64",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt",
            "no-new-privileges", "--pids-limit", "256", "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=512m", "--user", "501:20", "--workdir", "/source-a"])
        self.assertEqual([argv[i + 1] for i, value in enumerate(argv) if value == "--env"],
            ["THREADROOT_CANONICAL_BUILD=1", "SOURCE_DATE_EPOCH=123", "TZ=UTC", "LC_ALL=C.UTF-8",
             "LANG=C.UTF-8", "PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1", "HOME=/tmp"])

    def test_docker_run_exactly_establishes_artifact_identity_perimeter(self):
        for denylist in (None, Path("/outside/denylist")):
            with self.subTest(denylist=denylist):
                context = {**CONTEXT, "denylist": denylist}
                argv = entry.docker_run_argv(**context)
                mounts = [argv[i + 1] for i, value in enumerate(argv) if value == "--mount"]
                expected = ["type=bind,src=/outside/source-a,dst=/source-a,readonly",
                    "type=bind,src=/outside/source-b,dst=/source-b,readonly",
                    "type=bind,src=/outside/build,dst=/release-output"]
                if denylist:
                    expected += ["type=bind,src=/outside/denylist,dst=/run/threadroot/denylist,readonly"]
                self.assertEqual(mounts, expected)
                self.assertEqual(sum(not mount.endswith(",readonly") for mount in mounts), 1)
                self.assertEqual(argv[argv.index(IMAGE):], [IMAGE, "python", "-m", "scripts.build_verified_release",
                    "--inside", "--source-a", "/source-a", "--source-b", "/source-b", "--output",
                    "/release-output", "--commit", SHA, "--epoch", "123"] +
                    (["--denylist", "/run/threadroot/denylist"] if denylist else []))
                validate(argv, context)

    def test_perimeter_mutations_reject_exactly(self):
        for denylist in (None, Path("/outside/denylist")):
            context = {**CONTEXT, "denylist": denylist}
            baseline = entry.docker_run_argv(**context)
            pairs = {"--platform", "--network", "--cap-drop", "--security-opt", "--pids-limit",
                     "--tmpfs", "--user", "--workdir", "--env", "--mount", "--source-a",
                     "--source-b", "--output", "--commit", "--epoch", "--denylist"}
            mutations = []
            index = 0
            while index < len(baseline):
                width = 2 if baseline[index] in pairs else 1
                group = baseline[index:index + width]
                for operation in ("delete", "duplicate", "change"):
                    replacement = [] if operation == "delete" else group * 2 if operation == "duplicate" else [*group[:-1], "wrong"]
                    mutations.append((f"{index}-{group[0]}-{operation}", baseline[:index] + replacement + baseline[index + width:]))
                if group[0] == "--mount":
                    mount = group[1]
                    for field in ("src", "dst"):
                        changed = [field + "=/wrong" if value.startswith(field + "=") else value for value in mount.split(",")]
                        mutations.append((f"{index}-{field}", baseline[:index + 1] + [",".join(changed)] + baseline[index + 2:]))
                    changed = mount.removesuffix(",readonly") if mount.endswith(",readonly") else mount + ",readonly"
                    mutations.append((f"{index}-readonly", baseline[:index + 1] + [changed] + baseline[index + 2:]))
                index += width
            for user in ("0:20", "501:0", "0:0", "502:20"):
                changed = list(baseline)
                changed[baseline.index("--user") + 1] = user
                mutations.append(("user-" + user, changed))
            image_index = baseline.index(IMAGE)
            mutations.extend([
                ("extra-readonly", baseline[:image_index] + ["--mount", "type=bind,src=/etc,dst=/etc,readonly"] + baseline[image_index:]),
                ("extra-tail", baseline + ["--unexpected"]),
                ("denylist-presence", entry.docker_run_argv(**{**context, "denylist": None if denylist else Path("/outside/denylist")})),
            ])
            for name, changed in mutations:
                with self.subTest(denylist=denylist, mutation=name):
                    self.assertNotEqual(changed, baseline)
                    try:
                        validate(changed, context)
                    except entry.VerifiedReleaseError as error:
                        self.assertEqual(str(error), PERIMETER)
                    except Exception as error:
                        self.fail(f"validator leaked {type(error).__name__}, expected stable perimeter error")
                    else:
                        self.fail("unsafe perimeter accepted")

    def test_main_checks_perimeter_before_docker_provisioning(self):
        with outer_fixture() as fixture:
            original = entry.docker_run_argv
            def unsafe(*args, **kwargs):
                return original(*args, **kwargs) + ["--unexpected"]
            with patch.object(entry, "docker_run_argv", side_effect=unsafe) as builder:
                result = invoke(outer_args(fixture))
            builder.assert_called_once()
            with self.subTest(check="message"):
                self.assertEqual(result, (1, "", PERIMETER + "\n"))
            fixture.run.assert_not_called()

    def test_requires_full_commit_and_absolute_output_outside_repository(self):
        for changes, message in (({"commit": "bad"}, "commit must be a full 40-character SHA"),
                                 ({"output": "relative"}, "output must be absolute and outside repository")):
            with self.subTest(changes=changes), outer_fixture() as fixture:
                self.assert_rejected(fixture, outer_args(fixture, **changes), message, no_git=True)

    def test_rejects_nonempty_output_and_symlink_output(self):
        for kind in ("inside", "final-symlink", "intermediate-symlink", "nonempty"):
            with self.subTest(kind=kind), outer_fixture() as fixture:
                candidate = fixture.output
                message = "output must be absolute and outside repository"
                if kind == "inside":
                    candidate = fixture.repository / "release"
                elif kind == "final-symlink":
                    candidate = fixture.root / "link"
                    candidate.symlink_to(fixture.repository, target_is_directory=True)
                elif kind == "intermediate-symlink":
                    link = fixture.root / "link"
                    link.symlink_to(fixture.repository, target_is_directory=True)
                    candidate = link / "release"
                else:
                    candidate = fixture.root / "occupied"
                    candidate.mkdir()
                    (candidate / "sentinel").write_bytes(b"keep")
                    message = "output must be missing or empty"
                self.assert_rejected(fixture, outer_args(fixture, output=candidate), message, no_git=True)
                if kind == "nonempty":
                    self.assertEqual((candidate / "sentinel").read_bytes(), b"keep")
                elif kind != "final-symlink":
                    self.assertFalse(candidate.exists())

    def test_rejects_dirty_tracked_or_untracked_repository_state(self):
        for dirty in (" M tracked\n", "?? untracked\n"):
            with self.subTest(dirty=dirty), outer_fixture(git_values={STATUS: dirty}) as fixture:
                self.assert_rejected(fixture, outer_args(fixture), "repository must be clean")
                self.assertEqual(fixture.git.call_args_list, [call(*STATUS)])
                fixture.parity.assert_not_called()

    def test_commit_resolution_and_object_type_reject_before_runner(self):
        for values, message, calls in (({RESOLVE: "b" * 40 + "\n"}, "commit must resolve to itself", [STATUS, RESOLVE]),
                                      ({KIND: "tree\n"}, "commit must identify a commit object", [STATUS, RESOLVE, KIND])):
            with self.subTest(values=values), outer_fixture(git_values=values) as fixture:
                self.assert_rejected(fixture, outer_args(fixture), message)
                with self.subTest(check="no runner"):
                    fixture.parity.assert_not_called()
                self.assertEqual(fixture.git.call_args_list, [call(*args) for args in calls])

    def test_runner_files_must_match_the_selected_commit(self):
        with outer_fixture(parity=False) as fixture:
            accesses = []
            real_import = builtins.__import__
            real_import_module = importlib.import_module

            def is_runner(name):
                return name.rsplit(".", 1)[-1] in {"release_archives", "release_artifacts"}

            def watch_import(name, globals=None, locals=None, fromlist=(), level=0):
                if is_runner(name) or (name == "scripts" and any(is_runner(item) for item in fromlist)):
                    accesses.append(("import", name, fromlist))
                return real_import(name, globals, locals, fromlist, level)

            def watch_import_module(name, package=None):
                if is_runner(name):
                    accesses.append(("import_module", name))
                return real_import_module(name, package)

            class WatchedModule(types.ModuleType):
                def __getattribute__(self, name):
                    if name in {"extract_regular_tar_payload", "build_and_verify"}:
                        accesses.append(("attribute", name))
                    return super().__getattribute__(name)

            archives = WatchedModule("scripts.release_archives")
            archives.extract_regular_tar_payload = fixture.extractor
            artifacts = WatchedModule("scripts.release_artifacts")
            artifacts.build_and_verify = Mock()
            # Only invoke is instrumented: fixture imports and recorder setup
            # cannot masquerade as current-tree runner use by main. Patching
            # both cache and package attributes also covers cached module access.
            with patch.dict(sys.modules, {"scripts.release_archives": archives, "scripts.release_artifacts": artifacts}), \
                 patch.object(sys.modules["scripts"], "release_archives", archives), \
                 patch.object(sys.modules["scripts"], "release_artifacts", artifacts, create=True), \
                 patch("builtins.__import__", side_effect=watch_import), \
                 patch("importlib.import_module", side_effect=watch_import_module):
                result = invoke(outer_args(fixture))
            self.assertEqual(result, (1, "", "runner files differ from selected commit\n"))
            self.assertEqual(accesses, [])
            fixture.parity.assert_called_once_with(SHA)
            fixture.archive.assert_not_called()
            fixture.extractor.assert_not_called()
            fixture.run.assert_not_called()
            self.assertFalse(fixture.output.exists())
        tree = ast.parse(Path(entry.__file__).read_text())
        modules = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = ("scripts." if node.level else "") + (node.module or "")
                modules.append(module.rstrip("."))
                modules.extend(f"{module.rstrip('.')}.{alias.name}" for alias in node.names)
        self.assertFalse(any(name == module or name.startswith(module + ".")
            for name in modules for module in ("scripts.release_archives", "scripts.release_artifacts")), modules)

    def test_runner_files_bind_release_candidate_module_bytes(self):
        self.assertEqual(entry.RUNNER_FILES, EXPECTED_RUNNER_FILES)
        repository = Path("/synthetic/repository")
        payloads = {name: f"synthetic runner {index}\n".encode() for index, name in enumerate(EXPECTED_RUNNER_FILES)}
        expected_reads = [call(repository / name) for name in EXPECTED_RUNNER_FILES]
        expected_git = [call(["git", "show", f"{SHA}:{name}"], cwd=repository,
                             check=True, capture_output=True) for name in EXPECTED_RUNNER_FILES]
        for mismatch in (None, *EXPECTED_RUNNER_FILES):
            with self.subTest(mismatch=mismatch):
                def read(path):
                    return payloads[path.relative_to(repository).as_posix()]

                def git(argv, **kwargs):
                    name = argv[2].split(":", 1)[1]
                    return subprocess.CompletedProcess(argv, 0,
                        b"different committed bytes" if name == mismatch else payloads[name], b"")

                with patch.object(entry, "REPOSITORY", repository), \
                     patch.object(entry, "_read_regular", side_effect=read) as reads, \
                     patch.object(entry.subprocess, "run", side_effect=git) as run:
                    self.assertIs(entry._runner_bytes_match(SHA), mismatch is None)
                if mismatch is None:
                    self.assertEqual(reads.call_args_list, expected_reads)
                    self.assertEqual(run.call_args_list, expected_git)
                else:
                    # A mismatch may short-circuit or finish read-only checks;
                    # either way it must inspect the actual mismatched pair.
                    index = EXPECTED_RUNNER_FILES.index(mismatch)
                    self.assertIn(expected_reads[index], reads.call_args_list)
                    self.assertIn(expected_git[index], run.call_args_list)
                    self.assertEqual(reads.call_args_list, expected_reads[:len(reads.call_args_list)])
                    self.assertEqual(run.call_args_list, expected_git[:len(run.call_args_list)])

    def test_host_identity_rejects_unsupported_or_nonpositive_before_export_or_docker(self):
        cases = [("missing-uid", "getuid", None), ("missing-gid", "getgid", None),
                 ("zero-uid", "getuid", 0), ("zero-gid", "getgid", 0),
                 ("negative-uid", "getuid", -1), ("negative-gid", "getgid", -1)]
        for name, accessor, value in cases:
            with self.subTest(case=name), outer_fixture() as fixture:
                fixture.output = fixture.root / name
                if value is None:
                    delattr(entry.os, accessor)
                    message = "host UID/GID is unsupported"
                else:
                    getattr(entry.os, accessor).return_value = value
                    message = "host UID/GID must be positive"
                self.assert_rejected(fixture, outer_args(fixture), message)

    def test_rejects_docker_mount_delimiters_and_control_characters(self):
        for field in ("source_a", "source_b", "output", "denylist"):
            for character in (",", "\0", "\n", "\r", "\x7f", "\x81"):
                with self.subTest(field=field, character=repr(character)):
                    with self.assertRaises(entry.VerifiedReleaseError) as raised:
                        entry.docker_run_argv(**{**CONTEXT, field: Path("/outside/bad" + character + "path")})
                    self.assertEqual(str(raised.exception), "unsafe host path")
        for field in ("output", "denylist"):
            with self.subTest(public_field=field), outer_fixture() as fixture:
                self.assert_rejected(fixture, outer_args(fixture, **{field: str(fixture.root / "bad,path")}),
                                     "unsafe host path", no_git=True)

    def test_denylist_invalid_objects_reject_via_main_before_export_or_docker(self):
        for kind in ("relative", "missing", "symlink", "directory", "fifo", "hardlink"):
            with self.subTest(kind=kind), outer_fixture() as fixture:
                denylist = fixture.root / "denylist"
                if kind == "relative":
                    denylist.write_bytes(b"synthetic")
                    denylist = Path(os.path.relpath(denylist, Path.cwd()))
                    self.assertFalse(denylist.is_absolute())
                    self.assertTrue(denylist.is_file())
                elif kind == "symlink":
                    target = fixture.root / "target"
                    target.write_bytes(b"synthetic")
                    denylist.symlink_to(target)
                elif kind == "directory":
                    denylist.mkdir()
                elif kind == "fifo":
                    os.mkfifo(denylist)
                elif kind == "hardlink":
                    denylist.write_bytes(b"synthetic")
                    os.link(denylist, fixture.root / "second-name")
                    self.assertGreater(denylist.stat().st_nlink, 1)
                self.assert_rejected(fixture, outer_args(fixture, denylist=denylist),
                                     "denylist is missing or unsafe")

    def test_exports_exact_commit_twice_without_links_or_unsafe_names(self):
        for existing in (False, True):
            with self.subTest(empty_output=existing), outer_fixture() as fixture:
                if existing:
                    fixture.output.mkdir()
                status, _, stderr = invoke(outer_args(fixture))
                self.assertEqual((status, stderr), (0, ""))
                self.assertEqual(fixture.archive.call_args_list, [call(SHA), call(SHA)])
                self.assertEqual(fixture.extractor.call_args_list, [
                    call(b"synthetic git archive", fixture.output / "source-a", expected_global_comment=SHA),
                    call(b"synthetic git archive", fixture.output / "source-b", expected_global_comment=SHA)])
                self.assertTrue((fixture.output / "build").is_dir())
                self.assertIn(("git", RESOLVE), fixture.events)
                self.assertLess(fixture.events.index(("git", RESOLVE)), fixture.events.index(("archive", SHA)))

    def test_docker_build_uses_exact_platform_dockerfile_and_export_context(self):
        with outer_fixture() as fixture:
            status, _, stderr = invoke(outer_args(fixture))
            self.assertEqual((status, stderr), (0, ""))
            source = fixture.output / "source-a"
            image = "threadroot-release-builder:" + hashlib.sha256(b"FROM pinned\n\0lock\n").hexdigest()
            self.assertEqual(fixture.run.call_count, 2)
            self.assertEqual(fixture.run.call_args_list[0], call(["docker", "build", "--platform", "linux/amd64", "--pull",
                "--file", str(source / "tools/release/Dockerfile"), "--tag", image, str(source)],
                check=True, capture_output=True, text=True))
            self.assertEqual(fixture.run.call_args_list[1].args[0][:2], ["docker", "run"])

    def test_optional_denylist_is_mounted_read_only_without_entering_argv_logs(self):
        with outer_fixture() as fixture:
            denylist = fixture.root / "private-denylist-name"
            denylist.write_bytes(b"SYNTHETIC_SECRET_TOKEN")
            denylist.chmod(0o644)  # Host trust does not require mode 0444.
            self.assertEqual(denylist.stat().st_nlink, 1)
            result = invoke(outer_args(fixture, denylist=denylist))
            with self.subTest(check="status"):
                self.assertEqual(result, (0, "verified release build completed\n", ""))
            argv = fixture.run.call_args_list[-1].args[0]
            mounts = [argv[i + 1] for i, value in enumerate(argv) if value == "--mount"]
            self.assertEqual(len(mounts), 4)
            self.assertEqual(mounts[-1], f"type=bind,src={denylist},dst=/run/threadroot/denylist,readonly")
            self.assertEqual(argv[argv.index("--denylist"):], ["--denylist", "/run/threadroot/denylist"])

    def test_child_output_is_projected_to_fixed_status_and_exact_path_labels(self):
        for denylisted in (False, True):
            for phase in ("success", "builder", "artifact phase"):
                with self.subTest(denylist=denylisted, phase=phase), outer_fixture() as fixture:
                    denylist = fixture.root / "private-denylist-name"
                    denylist.write_bytes(b"SYNTHETIC_SECRET_TOKEN")
                    paths = [fixture.repository, fixture.output / "source-a", fixture.output / "source-b", fixture.output]
                    labels = "[repository] [source-a] [source-b] [output]"
                    if denylisted:
                        paths.append(denylist)
                        labels += " [denylist]"
                    raw = "SYNTHETIC_SECRET_TOKEN private-denylist-name /secret/path ENV=credential " + " ".join(map(str, paths))
                    def child(argv, **kwargs):
                        if phase == "builder" or (phase == "artifact phase" and argv[1] == "run"):
                            raise subprocess.CalledProcessError(1, ["docker", "ARGV_SECRET"], output=raw, stderr=raw)
                        return subprocess.CompletedProcess(argv, 0, raw, raw)
                    fixture.run.side_effect = child
                    result = invoke(outer_args(fixture, **({"denylist": denylist} if denylisted else {})))
                    if phase == "success":
                        self.assertEqual(result, (0, "verified release build completed\n", ""))
                    else:
                        self.assertEqual(result, (1, "", "verified release " + phase + " failed " + labels + "\n"))

    def test_child_projection_emits_only_observed_labels_with_specific_paths_first(self):
        for observed in ("source-a", "none"):
            with self.subTest(observed=observed), outer_fixture() as fixture:
                raw = "SYNTHETIC_SECRET_TOKEN /secret/path ENV=credential"
                if observed == "source-a":
                    raw += " " + str(fixture.output / "source-a")
                fixture.run.return_value = subprocess.CompletedProcess([], 0, raw, raw)
                self.assertEqual(invoke(outer_args(fixture)), (0, "verified release build completed\n", ""))

    def test_inside_mode_requires_container_sentinel_and_calls_build_and_verify(self):
        args = ["--inside", "--source-a", "/source-a", "--source-b", "/source-b", "--output",
                "/release-output", "--commit", SHA, "--epoch", "123"]
        fake = types.ModuleType("scripts.release_artifacts")
        fake.build_and_verify = Mock()
        real_import = builtins.__import__
        imported = []
        def watch_import(name, *args, **kwargs):
            if name == "scripts.release_artifacts":
                imported.append(name)
            return real_import(name, *args, **kwargs)
        with patch.dict("sys.modules", {"scripts.release_artifacts": fake}), patch("builtins.__import__", side_effect=watch_import), patch.object(entry.subprocess, "run") as run:
            for field in (None, "--source-a", "--source-b", "--output"):
                with self.subTest(field=field), patch.dict(os.environ, {} if field is None else {"THREADROOT_CANONICAL_BUILD": "1"}, clear=True):
                    changed = list(args)
                    if field:
                        changed[changed.index(field) + 1] = "/wrong"
                    message = "canonical container sentinel is required" if field is None else "noncanonical container paths"
                    self.assertEqual(invoke(changed), (1, "", message + "\n"))
                    self.assertEqual(imported, [])
                    fake.build_and_verify.assert_not_called()
                    run.assert_not_called()
            fake.build_and_verify.reset_mock()
            with patch.dict(os.environ, {"THREADROOT_CANONICAL_BUILD": "1"}, clear=True):
                self.assertEqual(invoke(args), (0, "", ""))
            fake.build_and_verify.assert_called_once_with(Path("/source-a"), Path("/source-b"), Path("/release-output"), SHA, 123, None)
            self.assertEqual(imported, ["scripts.release_artifacts"])


if __name__ == "__main__":
    unittest.main()
