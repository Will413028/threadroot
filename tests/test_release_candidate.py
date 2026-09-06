from __future__ import annotations

from contextlib import contextmanager
import json
import hashlib
import errno
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.release_archives import extract_regular_tar_payload
from scripts import release_candidate as candidate_module
from scripts.release_artifacts import BASE_IMAGE, EXPECTED_PACKAGES
from scripts.release_candidate import (
    CandidateIntegrityError,
    _canonical_json,
    _capture_candidate,
    _parse_manifest,
    _verify_candidate_manifest,
    _write_candidate_manifest,
)


COMMIT_ZERO = "0" * 40
ARTIFACTS = (
    "threadroot-0.1.0-py3-none-any.whl",
    "threadroot-0.1.0.tar.gz",
    "threadroot-claude-0.1.0.zip",
    "threadroot-codex-0.1.0.zip",
)


class CandidateManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repository = self.root / "repository"
        self.candidate = self.root / "candidate"
        self.repository.mkdir()
        self._git("init", "-q")
        self._git("config", "user.name", "Synthetic Release")
        self._git("config", "user.email", "release@example.invalid")
        self._git("config", "core.hooksPath", str(self.root / "no-hooks"))
        (self.repository / "README.md").write_text("synthetic release\n", encoding="utf-8")
        (self.repository / "bin").mkdir()
        tool = self.repository / "bin" / "threadroot"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        (self.repository / "src").mkdir()
        (self.repository / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--no-gpg-sign", "-qm", "synthetic source")
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()
        archive = self._git("archive", "--format=tar", self.commit, text=False).stdout
        self.candidate.mkdir()
        extract_regular_tar_payload(archive, self.candidate / "source-a", self.commit)
        extract_regular_tar_payload(archive, self.candidate / "source-b", self.commit)
        for group in ("candidate-a", "candidate-b", "selected"):
            target = self.candidate / "build" / group
            target.mkdir(parents=True)
            for index, name in enumerate(ARTIFACTS):
                (target / name).write_bytes(f"artifact-{index}\n".encode())
        evidence = self.candidate / "build" / "evidence"
        evidence.mkdir()
        hashes = {name: __import__("hashlib").sha256(f"artifact-{index}\n".encode()).hexdigest()
                  for index, name in enumerate(ARTIFACTS)}
        sizes = {name: len(f"artifact-{index}\n".encode()) for index, name in enumerate(ARTIFACTS)}
        build = {"artifacts": [{"name": name, "sha256": hashes[name], "size": sizes[name]}
                                for name in ARTIFACTS], "commit": self.commit, "schema": 1}
        (evidence / "build.json").write_bytes(_canonical_json(build))
        (evidence / "SHA256SUMS").write_text(
            "".join(f"{hashes[name]}  {name}\n" for name in sorted(ARTIFACTS)), encoding="ascii"
        )

    def _git(self, *args: str, text: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.repository, check=True, capture_output=True, text=text
        )

    @contextmanager
    def _in_repository(self):
        previous = Path.cwd()
        os.chdir(self.repository)
        try:
            yield
        finally:
            os.chdir(previous)

    def _write(self) -> None:
        with self._in_repository():
            _write_candidate_manifest(self.candidate, self.commit)

    def _verify(self, commit: str | None = None) -> None:
        with self._in_repository():
            _verify_candidate_manifest(self.candidate, commit or self.commit)

    def test_clean_manifest_covers_the_complete_tree_and_exact_git_export(self) -> None:
        before = _capture_candidate(self.candidate)
        self._write()
        self._verify()
        document = json.loads((self.candidate / "build/evidence/candidate-integrity.json").read_text())
        self.assertEqual(document["commit"], self.commit)
        self.assertEqual(document["entries"], [entry.as_manifest() for entry in before.entries])
        self.assertEqual(document["entries"], sorted(document["entries"], key=lambda item: item["path"]))

    def test_prefix_siblings_are_sorted_by_full_posix_path(self) -> None:
        directory = self.candidate / "build/a"
        directory.mkdir()
        (directory / "child").write_bytes(b"child\n")
        (self.candidate / "build/a.txt").write_bytes(b"sibling\n")

        snapshot = _capture_candidate(self.candidate)

        paths = [entry.path for entry in snapshot.entries]
        self.assertEqual(paths, sorted(paths))
        self.assertLess(paths.index("build/a.txt"), paths.index("build/a/child"))

    def test_manifest_is_canonical_bounded_and_mode_0444(self) -> None:
        self._write()
        manifest = self.candidate / "build/evidence/candidate-integrity.json"
        payload = manifest.read_bytes()
        self.assertEqual(payload, _canonical_json(json.loads(payload)))
        metadata = manifest.stat()
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o444)
        self.assertEqual(metadata.st_nlink, 1)
        member = self.candidate / "build/selected" / ARTIFACTS[0]
        member.chmod(0o4755)
        with self.assertRaises(CandidateIntegrityError):
            _capture_candidate(self.candidate)

    def test_preexisting_manifest_and_manifest_creation_race_never_overwrite(self) -> None:
        manifest = self.candidate / "build/evidence/candidate-integrity.json"
        manifest.write_bytes(b"keep me")
        with self.assertRaises(CandidateIntegrityError):
            self._write()
        self.assertEqual(manifest.read_bytes(), b"keep me")
        manifest.unlink()
        real_open = os.open
        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            if path == "candidate-integrity.json" and flags & os.O_EXCL:
                manifest.write_bytes(b"competitor")
            return real_open(path, flags, mode, dir_fd=dir_fd)
        with patch("scripts.release_candidate.os.open", side_effect=racing_open):
            with self.assertRaises(CandidateIntegrityError):
                self._write()
        self.assertEqual(manifest.read_bytes(), b"competitor")

    def test_added_modified_replaced_or_mode_changed_member_is_rejected(self) -> None:
        mutations = (
            lambda: (self.candidate / "build/extra").write_bytes(b"x"),
            lambda: (self.candidate / "build/selected" / ARTIFACTS[0]).write_bytes(b"changed"),
            lambda: self._replace(self.candidate / "build/selected" / ARTIFACTS[0]),
            lambda: (self.candidate / "build/selected" / ARTIFACTS[0]).chmod(0o600),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self._write()
                mutate()
                with self.assertRaises(CandidateIntegrityError):
                    self._verify()
                self._restore_fixture()

    def _replace(self, path: Path) -> None:
        payload = path.read_bytes()
        path.unlink()
        path.write_bytes(payload)

    def _restore_fixture(self) -> None:
        shutil.rmtree(self.candidate)
        self.setUp()

    def test_hard_link_symlink_and_special_member_are_rejected(self) -> None:
        target = self.candidate / "build/evidence/build.json"
        cases = ("hard", "symlink", "fifo")
        for kind in cases:
            probe = self.candidate / "build" / f"probe-{kind}"
            if kind == "hard": os.link(target, probe)
            elif kind == "symlink": probe.symlink_to(target)
            else: os.mkfifo(probe)
            with self.subTest(kind=kind), self.assertRaises(CandidateIntegrityError):
                _capture_candidate(self.candidate)
            probe.unlink()
        # The linked original is unsafe too until its extra link is gone.
        self.assertEqual(target.stat().st_nlink, 1)

    def test_source_asymmetry_wrong_commit_and_non_git_source_are_rejected(self) -> None:
        with self.subTest("asymmetry"):
            (self.candidate / "source-b/README.md").write_text("different\n")
            with self.assertRaises(CandidateIntegrityError): self._write()
            (self.candidate / "source-b/README.md").write_text("synthetic release\n")
        with self.subTest("wrong commit"), self.assertRaises(CandidateIntegrityError):
            with self._in_repository(): _write_candidate_manifest(self.candidate, COMMIT_ZERO)
        with self.subTest("non git"):
            (self.candidate / "source-a/untracked").write_bytes(b"x")
            with self.assertRaises(CandidateIntegrityError): self._write()

    def test_entry_file_total_path_and_manifest_bounds_fail_closed(self) -> None:
        cases = (
            ("MAX_ENTRY_COUNT", 2),
            ("MAX_FILE_SIZE", 2),
            ("MAX_TOTAL_FILE_SIZE", 2),
            ("MAX_PATH_BYTES", 4),
            ("MAX_MANIFEST_SIZE", 10),
        )
        for constant, value in cases:
            with self.subTest(constant=constant), patch(f"scripts.release_candidate.{constant}", value):
                with self.assertRaises(CandidateIntegrityError): self._write()

    def test_duplicate_unknown_noncanonical_boolean_and_range_values_are_rejected(self) -> None:
        self._write()
        manifest = self.candidate / "build/evidence/candidate-integrity.json"
        valid = json.loads(manifest.read_bytes())
        variants = (
            b'{"commit":"' + self.commit.encode() + b'","entries":[],"schema":1,"schema":1}\n',
            _canonical_json({**valid, "unknown": 1}),
            json.dumps(valid, indent=2).encode() + b"\n",
            _canonical_json({**valid, "schema": True}),
            _canonical_json({**valid, "schema": 2}),
            _canonical_json({**valid, "entries": [{**valid["entries"][0], "device": -1}]}),
        )
        for payload in variants:
            with self.subTest(payload=payload[:30]):
                manifest.chmod(0o644)
                manifest.write_bytes(payload)
                manifest.chmod(0o444)
                with self.assertRaises(CandidateIntegrityError): self._verify()
        files = [entry for entry in valid["entries"] if entry["kind"] == "file"]
        with patch("scripts.release_candidate.MAX_TOTAL_FILE_SIZE", 1):
            with self.assertRaises(CandidateIntegrityError):
                _parse_manifest(_canonical_json({**valid, "entries": files[:1]}), self.commit)

    def test_c1_controls_are_rejected_during_manifest_capture_and_parse(self):
        self._write()
        valid = json.loads((self.candidate / candidate_module.MANIFEST_RELATIVE).read_bytes())
        _parse_manifest(_canonical_json(valid), self.commit)
        for character in ("\u0080", "\u0085", "\u009f"):
            member = self.candidate / "build" / ("control" + character)
            member.write_bytes(b"synthetic")
            try:
                with self.subTest(character=ord(character), phase="capture"):
                    with self.assertRaises(CandidateIntegrityError):
                        _capture_candidate(self.candidate)
            finally:
                member.unlink()
            entry = {**valid["entries"][0], "path": "build/control" + character}
            with self.subTest(character=ord(character), phase="parse"):
                with self.assertRaises(CandidateIntegrityError):
                    _parse_manifest(_canonical_json({**valid, "entries": [entry]}), self.commit)


class DirectoryAcquisitionTests(unittest.TestCase):
    def test_stable_ancestor_accepts_sibling_churn_but_tree_opener_rejects_it(self):
        for ancestor in (True, False):
            with self.subTest(ancestor=ancestor), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                target = base / "ancestor"
                target.mkdir()
                with candidate_module._held_directory(target):
                    pass
                before = target.stat()
                real_open = os.open
                fired = []
                def churn(path, *args, **kwargs):
                    if path == "ancestor" and not fired:
                        (target / "unrelated-sibling").mkdir()
                        fired.append(True)
                    return real_open(path, *args, **kwargs)
                with patch.object(candidate_module.os, "open", side_effect=churn):
                    if ancestor:
                        with candidate_module._held_directory(target):
                            pass
                    else:
                        parent = real_open(base, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            with self.assertRaises(CandidateIntegrityError):
                                candidate_module._open_dir_at(parent, "ancestor")
                        finally:
                            os.close(parent)
                self.assertEqual(fired, [True])
                self.assertEqual(candidate_module._ancestor_identity(before),
                                 candidate_module._ancestor_identity(target.stat()))
                self.assertNotEqual(candidate_module._identity(before),
                                    candidate_module._identity(target.stat()))

    def test_ancestor_acquisition_rejects_permission_and_replacement_drift(self):
        for mutation in ("mode", "replacement", "symlink"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                target = base / "ancestor"
                target.mkdir(mode=0o755)
                real_open = os.open
                fired = []
                def mutate(path, *args, **kwargs):
                    if path == "ancestor" and not fired:
                        fired.append(True)
                        if mutation == "mode":
                            target.chmod(0o700)
                        else:
                            target.rename(base / "moved")
                            if mutation == "replacement":
                                target.mkdir(mode=0o755)
                            else:
                                target.symlink_to(base / "moved", target_is_directory=True)
                    return real_open(path, *args, **kwargs)
                with patch.object(candidate_module.os, "open", side_effect=mutate):
                    with self.assertRaises((CandidateIntegrityError, OSError)):
                        with candidate_module._held_directory(target):
                            pass
                self.assertEqual(fired, [True])

    def test_initial_fstat_failure_closes_child_and_preserves_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "child").mkdir()
            parent = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
            real_open, real_fstat = os.open, os.fstat
            acquired = []
            def capture(*args, **kwargs):
                descriptor = real_open(*args, **kwargs)
                acquired.append(descriptor)
                return descriptor
            try:
                with patch.object(candidate_module.os, "open", side_effect=capture), \
                     patch.object(candidate_module.os, "fstat", side_effect=OSError(errno.EIO, "synthetic")):
                    with self.assertRaises(OSError):
                        candidate_module._open_dir_at(parent, "child")
                self.assertTrue(stat.S_ISDIR(real_fstat(parent).st_mode))
                self.assertEqual(len(acquired), 1)
                with self.assertRaises(OSError) as caught:
                    real_fstat(acquired[0])
                self.assertEqual(caught.exception.errno, errno.EBADF)
            finally:
                os.close(parent)
                for descriptor in acquired:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass


class CandidateAuthorityTests(unittest.TestCase):
    setUp = CandidateManifestTests.setUp
    _git = CandidateManifestTests._git
    _in_repository = CandidateManifestTests._in_repository

    def _prepare(self):
        self.record = self.root / "authority.json"
        path = self.candidate / "build/evidence/build.json"
        data = json.loads(path.read_bytes())
        data.update(source_date_epoch=int(self._git("show", "-s", "--format=%ct", self.commit).stdout),
                    platform="linux/amd64", python="3.14.7", base_image=BASE_IMAGE,
                    builder_definition_sha256="0" * 64, packages=EXPECTED_PACKAGES)
        path.write_bytes(_canonical_json(data))

    def _bind(self):
        with self._in_repository():
            candidate_module.bind_candidate(self.candidate, self.commit, self.record)

    def _verify(self):
        with self._in_repository():
            return candidate_module.verify_candidate(self.record, self.commit)

    def test_clean_candidate_binds_and_verifies_to_its_recorded_root(self):
        self._prepare()
        self._bind()
        self.assertEqual(self._verify(), self.candidate.resolve())
        data = json.loads(self.record.read_bytes())
        self.assertEqual(set(data), {"schema", "candidate", "candidate_root", "commit", "manifest"})
        self.assertEqual(data["candidate"]["inode"], self.candidate.stat().st_ino)
        self.assertEqual(data["manifest"]["sha256"], hashlib.sha256(
            (self.candidate / "build/evidence/candidate-integrity.json").read_bytes()).hexdigest())

    def test_sticky_temporary_parent_allows_binding_and_verification(self):
        self._prepare()
        self.root.chmod(0o1777)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o1777)
        self._bind()
        self.assertEqual(self._verify(), self.candidate)
        self.assertEqual(json.loads(self.record.read_bytes())["candidate"]["mode"], "0755")

    def test_record_is_canonical_single_link_regular_0400_and_bounded(self):
        self._prepare()
        self._bind()
        self.assertEqual(self.record.read_bytes(), _canonical_json(json.loads(self.record.read_bytes())))
        self.assertEqual(stat.S_IMODE(self.record.stat().st_mode), 0o400)
        self.assertEqual(self.record.stat().st_nlink, 1)
        self.assertLessEqual(self.record.stat().st_size, 16384)
        with patch.object(candidate_module, "MAX_RECORD_SIZE", 2):
            with self.assertRaises(CandidateIntegrityError): self._verify()

    def test_record_path_must_be_absolute_missing_external_and_safe(self):
        self._prepare()
        unsafe = [Path("relative.json"), self.repository / "record", self.candidate / "record",
                  self.root / "missing/record", self.root / "bad\nrecord"]
        link = self.root / "linked"
        link.symlink_to(self.repository, target_is_directory=True)
        unsafe.append(link / "record")
        for path in unsafe:
            with self.subTest(path=path):
                self.record = path
                with self.assertRaises(CandidateIntegrityError): self._bind()
                self.assertFalse((self.candidate / "build/evidence/candidate-integrity.json").exists())

    def test_existing_symlink_pending_and_competing_paths_are_never_replaced(self):
        self._prepare()
        self.record.write_bytes(b"existing")
        with self.assertRaises(CandidateIntegrityError): self._bind()
        self.assertEqual(self.record.read_bytes(), b"existing")
        self.record.unlink()
        self.record.symlink_to(self.root / "missing")
        with self.assertRaises(CandidateIntegrityError): self._bind()
        self.assertTrue(self.record.is_symlink())
        self.record.unlink()
        real_rename = candidate_module._rename_exclusive
        def compete(fd, pending, leaf):
            self.record.write_bytes(b"competitor")
            return real_rename(fd, pending, leaf)
        with patch.object(candidate_module, "_rename_exclusive", side_effect=compete):
            with self.assertRaises(CandidateIntegrityError): self._bind()
        self.assertEqual(self.record.read_bytes(), b"competitor")
        self.assertTrue(list(self.root.glob(".authority.json.*.pending")))

    def test_parent_fsync_or_post_publish_verify_failure_never_reports_success(self):
        self._prepare()
        real_fsync = os.fsync
        def fail_parent(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError("injected")
            real_fsync(fd)
        with patch.object(candidate_module.os, "fsync", side_effect=fail_parent):
            with self.assertRaises(CandidateIntegrityError): self._bind()
        self.assertTrue(self.record.exists())
        self.assertEqual(self._verify(), self.candidate.resolve())

    def test_published_failure_evidence_is_preserved_and_not_repaired(self):
        self._prepare()
        with patch.object(candidate_module, "verify_candidate", side_effect=CandidateIntegrityError("injected")):
            with self.assertRaises(CandidateIntegrityError): self._bind()
        original = self.record.read_bytes()
        with self.assertRaises(CandidateIntegrityError): self._bind()
        self.assertEqual(self.record.read_bytes(), original)

    def test_record_schema_bytes_identity_mode_link_and_replacement_races_fail(self):
        self._prepare()
        self._bind()
        original = self.record.read_bytes()
        data = json.loads(original)
        variants = [b"\xef\xbb\xbf" + original, original + b"\n", b"{\"schema\":1,\"schema\":1}\n",
                    _canonical_json({**data, "schema": True}), _canonical_json({**data, "extra": 1}),
                    _canonical_json({**data, "candidate": {**data["candidate"], "inode": -1}})]
        for payload in variants:
            self.record.chmod(0o600)
            self.record.write_bytes(payload)
            self.record.chmod(0o400)
            with self.assertRaises(CandidateIntegrityError): self._verify()
        self.record.chmod(0o600)
        self.record.write_bytes(original)
        with self.assertRaises(CandidateIntegrityError): self._verify()
        self.record.chmod(0o400)
        os.link(self.record, self.root / "linked-record")
        with self.assertRaises(CandidateIntegrityError): self._verify()
        (self.root / "linked-record").unlink()
        real_sources = candidate_module._require_git_sources
        def replace(snapshot, commit):
            real_sources(snapshot, commit)
            replacement = self.root / "replacement"
            replacement.write_bytes(original)
            replacement.chmod(0o400)
            replacement.replace(self.record)
        with patch.object(candidate_module, "_require_git_sources", side_effect=replace):
            with self.assertRaises(CandidateIntegrityError): self._verify()

    def test_every_candidate_member_and_coedited_artifact_evidence_drift_fails(self):
        for mutation in ("bytecode", "source", "inode", "mode", "hardlink", "extra", "evidence", "artifact", "coedit"):
            with self.subTest(mutation=mutation):
                self._prepare()
                self._bind()
                source = self.candidate / "source-a/README.md"
                artifact = self.candidate / "build/selected" / ARTIFACTS[0]
                if mutation == "bytecode": (self.candidate / "source-a/__pycache__").mkdir()
                elif mutation == "source": source.write_bytes(b"changed")
                elif mutation == "inode":
                    other = self.root / "replacement-source"
                    other.write_bytes(source.read_bytes())
                    other.replace(source)
                elif mutation == "mode": source.chmod(0o600)
                elif mutation == "hardlink": os.link(source, self.root / "source-link")
                elif mutation == "extra": (self.candidate / "build/extra").write_bytes(b"x")
                elif mutation == "evidence": (self.candidate / "build/evidence/build.json").write_bytes(b"{}\n")
                else:
                    artifact.write_bytes(b"changed")
                    if mutation == "coedit":
                        (self.candidate / "build/evidence/SHA256SUMS").write_bytes(b"coedited\n")
                with self.assertRaises(CandidateIntegrityError): self._verify()
                self.setUp()

    def test_repeated_snapshot_detects_a_concurrent_candidate_change(self):
        self._prepare()
        self._bind()
        real_sources = candidate_module._require_git_sources
        def change(snapshot, commit):
            real_sources(snapshot, commit)
            (self.candidate / "build/late").write_bytes(b"drift")
        with patch.object(candidate_module, "_require_git_sources", side_effect=change):
            with self.assertRaises(CandidateIntegrityError): self._verify()

    def test_pending_write_failure_preserves_owned_and_existing_pending_evidence(self):
        self._prepare()
        existing = self.root / ".authority.json.previous.pending"
        existing.write_bytes(b"previous attempt")
        with patch.object(candidate_module.os, "write", side_effect=OSError("injected")):
            with self.assertRaises(CandidateIntegrityError):
                candidate_module._publish_exclusive(self.record, b"payload", final_mode=0o400, maximum_size=100)
        self.assertFalse(self.record.exists())
        self.assertEqual(existing.read_bytes(), b"previous attempt")
        self.assertEqual(len(list(self.root.glob(".authority.json.*.pending"))), 2)

    def test_safe_record_copy_is_valid_but_root_mode_and_manifest_replacement_fail(self):
        self._prepare()
        self.candidate.chmod(0o750)
        self._bind()
        copy = self.root / "copy.json"
        copy.write_bytes(self.record.read_bytes())
        copy.chmod(0o400)
        self.record = copy
        self.assertEqual(self._verify(), self.candidate)
        self.candidate.chmod(0o700)
        with self.assertRaises(CandidateIntegrityError): self._verify()
        self.candidate.chmod(0o750)
        real_sources = candidate_module._require_git_sources
        def replace_manifest(snapshot, commit):
            real_sources(snapshot, commit)
            manifest = self.candidate / "build/evidence/candidate-integrity.json"
            replacement = self.root / "replacement-manifest"
            replacement.write_bytes(manifest.read_bytes())
            replacement.chmod(0o444)
            replacement.replace(manifest)
        with patch.object(candidate_module, "_require_git_sources", side_effect=replace_manifest):
            with self.assertRaises(CandidateIntegrityError): self._verify()

    def test_binding_rejects_invalid_artifact_sets_and_full_evidence_schema(self):
        for mutation in ("extra", "mode", "different", "unknown", "epoch", "boolean", "sums"):
            self._prepare()
            target = self.candidate / "build/candidate-b" / ARTIFACTS[0]
            evidence = self.candidate / "build/evidence/build.json"
            data = json.loads(evidence.read_bytes())
            if mutation == "extra": target.with_name("extra").write_bytes(b"x")
            elif mutation == "mode": target.chmod(0o600)
            elif mutation == "different": target.write_bytes(b"different")
            elif mutation == "unknown": data["extra"] = 1
            elif mutation == "epoch": data["source_date_epoch"] += 1
            elif mutation == "boolean": data["artifacts"][0]["size"] = True
            else: (self.candidate / "build/evidence/SHA256SUMS").write_bytes(b"bad")
            evidence.write_bytes(_canonical_json(data))
            with self.subTest(mutation=mutation), self.assertRaises(CandidateIntegrityError): self._bind()
            self.setUp()


class SuccessfulAttemptTests(unittest.TestCase):
    _git = CandidateManifestTests._git
    _in_repository = CandidateManifestTests._in_repository
    _prepare = CandidateAuthorityTests._prepare
    _bind = CandidateAuthorityTests._bind

    def setUp(self):
        CandidateManifestTests.setUp(self)
        self._prepare()
        self._bind()
        self.receipt = self.root / "success.json"

    def _record_success(self):
        with self._in_repository():
            candidate_module.record_successful_attempt(self.record, self.commit, self.receipt)

    def _verify_success(self):
        with self._in_repository():
            return candidate_module.verify_successful_attempt(
                self.receipt, self.record, self.commit
            )

    def test_receipt_binds_exact_record_bytes_size_and_commit(self):
        self._record_success()
        data = json.loads(self.receipt.read_bytes())
        self.assertEqual(data, {
            "authority_record_sha256": hashlib.sha256(self.record.read_bytes()).hexdigest(),
            "authority_record_size": len(self.record.read_bytes()),
            "commit": self.commit,
            "schema": 1,
        })
        self.assertEqual(self._verify_success(), self.candidate)

    def test_raw_record_alone_is_not_successful_attempt_authority(self):
        with self.assertRaises(CandidateIntegrityError):
            self._verify_success()

    def test_c1_controls_are_rejected_in_record_root_and_external_arguments(self):
        self._record_success()
        self.assertEqual(self._verify_success(), self.candidate)
        data = json.loads(self.record.read_bytes())
        for character in ("\u0080", "\u0085", "\u009f"):
            with self.subTest(character=ord(character), phase="record-root"):
                with self.assertRaises(CandidateIntegrityError):
                    candidate_module._parse_record(_canonical_json({
                        **data, "candidate_root": str(self.candidate) + character}), self.commit)
            record = self.root / ("authority" + character)
            receipt = self.root / ("receipt" + character)
            record.write_bytes(self.record.read_bytes())
            record.chmod(0o400)
            receipt.write_bytes(self.receipt.read_bytes())
            receipt.chmod(0o400)
            with self._in_repository():
                for arguments in ((self.receipt, record), (receipt, self.record)):
                    with self.subTest(character=ord(character), phase="verify", arguments=arguments):
                        with self.assertRaises(CandidateIntegrityError):
                            candidate_module.verify_successful_attempt(*arguments, self.commit)
                with self.subTest(character=ord(character), phase="publish"):
                    destination = self.root / ("new-receipt" + character)
                    with self.assertRaises(CandidateIntegrityError):
                        candidate_module.record_successful_attempt(self.record, self.commit, destination)
                    self.assertFalse(destination.exists())

    def test_receipt_schema_numeric_digest_commit_and_size_boundaries(self):
        self._record_success()
        valid = json.loads(self.receipt.read_bytes())
        self.assertEqual(self._verify_success(), self.candidate)
        for size in (1, 16384):
            self.assertEqual(candidate_module._parse_receipt(_canonical_json({
                **valid, "authority_record_size": size}), self.commit)["authority_record_size"], size)
        mutations = {
            "schema": (True, False, 0, 2, 1.0, "1"),
            "authority_record_size": (True, False, 0, -1, 16385, 1.0, "1"),
            "authority_record_sha256": (None, True, "A" * 64, "g" * 64, "0" * 63, "0" * 65),
            "commit": (None, True, "A" * 40, "g" * 40, "0" * 39, "0" * 41, "0" * 40),
        }
        for key, values in mutations.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(CandidateIntegrityError):
                        candidate_module._parse_receipt(_canonical_json({**valid, key: value}), self.commit)
        for size in (4096, 4097):
            # A canonical, schema-invalid document isolates the bounded read:
            # 4096 reaches parsing; 4097 must fail before JSON decoding.
            payload = _canonical_json({"padding": "x" * (size - 15)})
            self.assertEqual(len(payload), size)
            self.receipt.chmod(0o600)
            self.receipt.write_bytes(payload)
            self.receipt.chmod(0o400)
            with self.subTest(size=size), patch.object(candidate_module, "_parse_receipt", wraps=candidate_module._parse_receipt) as parse:
                with self.assertRaises(CandidateIntegrityError):
                    self._verify_success()
                self.assertEqual(parse.call_count, 1 if size == 4096 else 0)

    def test_receipt_is_canonical_single_link_regular_0400_and_bounded(self):
        self._record_success()
        self.assertEqual(self.receipt.read_bytes(), _canonical_json(json.loads(self.receipt.read_bytes())))
        self.assertTrue(stat.S_ISREG(self.receipt.stat().st_mode))
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o400)
        self.assertEqual(self.receipt.stat().st_nlink, 1)
        self.assertLessEqual(self.receipt.stat().st_size, 4 * 1024)
        self.receipt.chmod(0o600)
        with self.assertRaises(CandidateIntegrityError): self._verify_success()
        self.receipt.chmod(0o400)
        os.link(self.receipt, self.root / "receipt-link")
        with self.assertRaises(CandidateIntegrityError): self._verify_success()

    def test_missing_malformed_noncanonical_changed_or_replaced_receipt_fails(self):
        self._record_success()
        original = self.receipt.read_bytes()
        variants = (b"{}\n", original + b"\n", b'{"schema":1,"schema":1}\n')
        for payload in variants:
            self.receipt.chmod(0o600); self.receipt.write_bytes(payload); self.receipt.chmod(0o400)
            with self.assertRaises(CandidateIntegrityError): self._verify_success()
        self.receipt.chmod(0o600); self.receipt.write_bytes(original); self.receipt.chmod(0o400)
        replacement = self.root / "replacement-receipt"
        replacement.write_bytes(original); replacement.chmod(0o400)
        real = candidate_module._verify_held_record
        def replace(record, commit):
            result = real(record, commit)
            replacement.replace(self.receipt)
            return result
        with patch.object(candidate_module, "_verify_held_record", side_effect=replace):
            with self.assertRaises(CandidateIntegrityError): self._verify_success()

    def test_preexisting_receipt_and_publication_race_never_overwrite(self):
        self.receipt.write_bytes(b"existing")
        with self.assertRaises(CandidateIntegrityError): self._record_success()
        self.assertEqual(self.receipt.read_bytes(), b"existing")
        self.receipt.unlink()
        real = candidate_module._rename_exclusive
        def compete(fd, pending, leaf):
            self.receipt.write_bytes(b"competitor")
            return real(fd, pending, leaf)
        with patch.object(candidate_module, "_rename_exclusive", side_effect=compete):
            with self.assertRaises(CandidateIntegrityError): self._record_success()
        self.assertEqual(self.receipt.read_bytes(), b"competitor")

    def test_postpublication_failure_preserves_receipt_evidence(self):
        real = candidate_module._verify_held_attempt
        calls = 0
        def fail_after_publication(receipt, record, commit):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise CandidateIntegrityError("injected")
            return real(receipt, record, commit)
        with patch.object(candidate_module, "_verify_held_attempt", side_effect=fail_after_publication):
            with self.assertRaises(CandidateIntegrityError): self._record_success()
        self.assertTrue(self.receipt.exists())
        self.assertEqual(self._verify_success(), self.candidate)

    def test_byte_identical_safe_record_and_receipt_copies_remain_valid(self):
        self._record_success()
        record_copy, receipt_copy = self.root / "record-copy", self.root / "receipt-copy"
        record_copy.write_bytes(self.record.read_bytes()); record_copy.chmod(0o400)
        receipt_copy.write_bytes(self.receipt.read_bytes()); receipt_copy.chmod(0o400)
        with self._in_repository():
            self.assertEqual(candidate_module.verify_successful_attempt(
                receipt_copy, record_copy, self.commit), self.candidate)

    def test_record_and_receipt_descriptors_are_held_through_complete_verification(self):
        self._record_success()
        original = self.record.read_bytes()
        replacement = self.root / "replacement-record"
        replacement.write_bytes(original); replacement.chmod(0o400)
        real = candidate_module._require_git_sources
        def replace(snapshot, commit):
            real(snapshot, commit)
            replacement.replace(self.record)
        with patch.object(candidate_module, "_require_git_sources", side_effect=replace):
            with self.assertRaises(CandidateIntegrityError): self._verify_success()


class ReleaseCandidateCliTests(unittest.TestCase):
    _git = CandidateManifestTests._git
    _in_repository = CandidateManifestTests._in_repository
    _prepare = CandidateAuthorityTests._prepare
    _bind = CandidateAuthorityTests._bind

    def setUp(self):
        CandidateManifestTests.setUp(self)
        self._prepare()
        self._bind()
        self.receipt = self.root / "success.json"

    def _cli(self, *arguments):
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])}
        return subprocess.run([sys.executable, "-B", "-m", "scripts.release_candidate", *arguments],
                              cwd=self.repository, env=environment, capture_output=True, text=True)

    def test_all_three_subcommands_are_silent_on_success(self):
        verify = self._cli("verify", "--authority-record", str(self.record),
                           "--expected-commit", self.commit)
        record = self._cli("record-success", "--authority-record", str(self.record),
                           "--expected-commit", self.commit, "--success-receipt", str(self.receipt))
        success = self._cli("verify-success", "--authority-record", str(self.record),
                            "--expected-commit", self.commit, "--success-receipt", str(self.receipt))
        for result in (verify, record, success):
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_all_failures_emit_only_the_fixed_error_and_exit_nonzero(self):
        commands = (("verify",), ("record-success",), ("verify-success",), ("unknown",), ())
        for command in commands:
            result = self._cli(*command)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "candidate integrity verification failed\n")

    def test_raw_lexical_paths_are_rejected_by_every_applicable_cli_option(self):
        self.test_all_three_subcommands_are_silent_on_success()
        saved_receipt = self.receipt.read_bytes()
        for command in ("verify", "record-success", "verify-success"):
            options = ("--authority-record",) if command == "verify" else ("--authority-record", "--success-receipt")
            for option in options:
                for separator, suffix in (("/./", ""), ("//", ""), ("/", "/")):
                    with self.subTest(command=command, option=option, separator=separator, suffix=suffix):
                        if command == "record-success":
                            self.receipt.unlink(missing_ok=True)
                        elif command == "verify-success" and not self.receipt.exists():
                            self.receipt.write_bytes(saved_receipt)
                            self.receipt.chmod(0o400)
                        values = {"--authority-record": str(self.record), "--expected-commit": self.commit}
                        if command != "verify":
                            values["--success-receipt"] = str(self.receipt)
                        path = Path(values[option])
                        values[option] = str(path.parent) + separator + path.name + suffix
                        result = self._cli(command, *(token for pair in values.items() for token in pair))
                        self.assertEqual((result.returncode, result.stdout, result.stderr),
                                         (1, "", "candidate integrity verification failed\n"))
                        if command == "record-success":
                            self.assertFalse(self.receipt.exists())
                        self.assertFalse(list(self.root.glob(".*.pending")))

    def test_unknown_duplicate_options_and_sensitive_malformed_metadata_are_sanitized(self):
        self.test_all_three_subcommands_are_silent_on_success()
        valid_receipt = self.root / "valid-success.json"
        self.receipt.rename(valid_receipt)
        sensitive = self.root / "synthetic-private-marker.json"
        sensitive.write_bytes(b'{"synthetic-private-payload":"secret-marker"}\n')
        sensitive.chmod(0o400)
        matching_receipt = self.root / "matching-malformed-record.json"
        matching_receipt.write_bytes(_canonical_json({
            "schema": 1, "commit": self.commit,
            "authority_record_size": sensitive.stat().st_size,
            "authority_record_sha256": hashlib.sha256(sensitive.read_bytes()).hexdigest(),
        }))
        matching_receipt.chmod(0o400)
        for command in ("verify", "record-success", "verify-success"):
            valid = ["--authority-record", str(self.record), "--expected-commit", self.commit]
            if command != "verify":
                valid += ["--success-receipt", str(valid_receipt if command == "verify-success" else self.receipt)]
            variants = [["--unknown", str(sensitive), *valid[2:]],
                        ["--authority-record", str(sensitive), "--authority-record", str(sensitive), *valid[4:]]]
            if command == "verify-success":
                variants.extend([
                    ["--authority-record", str(sensitive), "--expected-commit", self.commit,
                     "--success-receipt", str(matching_receipt)],
                    ["--authority-record", str(self.record), "--expected-commit", self.commit,
                     "--success-receipt", str(sensitive)],
                ])
            else:
                variants.append(["--authority-record", str(sensitive), *valid[2:]])
            for arguments in variants:
                with self.subTest(command=command, arguments=arguments):
                    result = self._cli(command, *arguments)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (1, "", "candidate integrity verification failed\n"))
                    self.assertFalse(self.receipt.exists())
                    self.assertFalse(list(self.root.glob(".*.pending")))


if __name__ == "__main__":
    unittest.main()
