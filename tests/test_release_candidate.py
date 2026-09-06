from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.release_archives import extract_regular_tar_payload
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
        self.root = Path(self.temporary.name)
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


if __name__ == "__main__":
    unittest.main()
