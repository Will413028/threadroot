from __future__ import annotations

from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
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


if __name__ == "__main__":
    unittest.main()
