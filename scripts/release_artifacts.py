from __future__ import annotations

from dataclasses import dataclass
import filecmp
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from scripts.release_archives import (
    extract_regular_tar,
    extract_regular_zip,
    validate_host_zip,
    validate_sdist,
    validate_wheel,
)


class ReleaseArtifactError(RuntimeError):
    """Release artifact validation or promotion failed."""


def expected_asset_names(version: str) -> tuple[str, str, str, str]:
    return (
        f"threadroot-{version}-py3-none-any.whl",
        f"threadroot-{version}.tar.gz",
        f"threadroot-claude-{version}.zip",
        f"threadroot-codex-{version}.zip",
    )


@dataclass(frozen=True)
class ArtifactSet:
    root: Path
    wheel: Path
    sdist: Path
    claude: Path
    codex: Path

    @classmethod
    def load(cls, root: Path, version: str) -> "ArtifactSet":
        root = Path(root)
        names = expected_asset_names(version)
        entries = list(root.iterdir()) if root.is_dir() and not root.is_symlink() else []
        if (
            sorted(path.name for path in entries) != sorted(names)
            or any(path.is_symlink() or not path.is_file() for path in entries)
        ):
            raise ReleaseArtifactError("release output membership mismatch")
        return cls(
            root=root,
            wheel=root / names[0],
            sdist=root / names[1],
            claude=root / names[2],
            codex=root / names[3],
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def compare_artifact_sets(left: ArtifactSet, right: ArtifactSet) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in expected_asset_names(left.wheel.name.split("-")[1]):
        left_path = left.root / name
        right_path = right.root / name
        if not filecmp.cmp(left_path, right_path, shallow=False):
            raise ReleaseArtifactError(f"artifact bytes differ: {name}")
        hashes[name] = _sha256(left_path)
    return hashes


EXPECTED_PACKAGES = {
    "build": "1.6.0",
    "hatchling": "1.32.0",
    "packaging": "26.3",
    "pathspec": "1.1.1",
    "pip": "26.2.1",
    "pluggy": "1.6.0",
    "pyproject-hooks": "1.2.0",
    "tomlkit": "0.15.1",
    "trove-classifiers": "2026.6.1.19",
}
EXPECTED_ENVIRONMENT = {
    "THREADROOT_CANONICAL_BUILD": "1",
    "TZ": "UTC",
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "PIP_CONFIG_FILE": "/dev/null",
    "PIP_INDEX_URL": "https://pypi.org/simple",
    "PIP_EXTRA_INDEX_URL": "",
    "PIP_FIND_LINKS": "",
    "PIP_NO_CACHE_DIR": "1",
}
BASE_IMAGE = (
    "python:3.14.7-slim-bookworm@"
    "sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9"
)


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _installed_packages() -> dict[str, str]:
    return {
        _canonical_name(item.metadata["Name"]): item.version
        for item in importlib.metadata.distributions()
    }


def _read_lock_versions(lock: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in Path(lock).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+) \\", line)
        if match:
            versions[_canonical_name(match.group(1))] = match.group(2)
    return versions


def _validate_environment(epoch: int) -> None:
    if os.environ.get("THREADROOT_CANONICAL_BUILD") != "1":
        raise ReleaseArtifactError("canonical build environment is not enabled")
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ReleaseArtifactError("canonical build requires Linux x86_64")
    if tuple(sys.version_info[:3]) != (3, 14, 7):
        raise ReleaseArtifactError("canonical build requires Python 3.14.7")
    if epoch < 0:
        raise ReleaseArtifactError("source epoch must be non-negative")
    actual = _installed_packages()
    if actual != EXPECTED_PACKAGES:
        raise ReleaseArtifactError("canonical package set mismatch")
    for key, value in EXPECTED_ENVIRONMENT.items():
        if os.environ.get(key) != value:
            raise ReleaseArtifactError(f"canonical environment mismatch: {key}")


def _validate_roots(source_a: Path, source_b: Path, output: Path) -> None:
    roots = (Path(source_a), Path(source_b))
    if any(root.is_symlink() or not root.is_dir() for root in roots):
        raise ReleaseArtifactError("source roots must be real directories")
    try:
        if roots[0].samefile(roots[1]):
            raise ReleaseArtifactError("source roots must be distinct")
    except FileNotFoundError:
        raise ReleaseArtifactError("source roots must be real directories") from None
    output = Path(output)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ReleaseArtifactError("output must be missing or empty")


def _build_environment(work: Path, epoch: int) -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", "")}
    environment.update(EXPECTED_ENVIRONMENT)
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    environment["TMPDIR"] = str(work / "tmp")
    environment["HOME"] = str(work / "home")
    environment["XDG_CACHE_HOME"] = str(work / "cache")
    return environment


def _run(command: list[str], environment: dict[str, str]) -> None:
    subprocess.run(command, check=True, shell=False, env=environment)


def _build_one_source(source: Path, candidate: Path, work: Path, epoch: int) -> None:
    for name in ("tmp", "home", "cache"):
        (work / name).mkdir(parents=True, exist_ok=False)
    candidate.mkdir(parents=True, exist_ok=False)
    environment = _build_environment(work, epoch)
    python = sys.executable
    _run([python, "-m", "build", "--sdist", "--no-isolation", "--outdir", str(candidate), str(source)], environment)
    _run([python, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(candidate), str(source)], environment)
    _run([python, str(source / "scripts/build_release.py"), "--output", str(candidate)], environment)


def _replay_sdist(artifacts: ArtifactSet, evidence: Path, commit: str, epoch: int) -> None:
    extracted = evidence / "replay-source"
    replay_output = evidence / "replay-wheel"
    extract_regular_tar(artifacts.sdist, extracted, expected_global_comment=commit)
    roots = list(extracted.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ReleaseArtifactError("sdist extraction root mismatch")
    replay_output.mkdir(parents=True, exist_ok=False)
    environment = _build_environment(evidence / "replay-work", epoch)
    for name in ("tmp", "home", "cache"):
        (evidence / "replay-work" / name).mkdir(parents=True, exist_ok=False)
    _run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(replay_output), str(roots[0])], environment)
    wheels = list(replay_output.iterdir())
    if len(wheels) != 1 or wheels[0].name != artifacts.wheel.name:
        raise ReleaseArtifactError("sdist wheel replay membership mismatch")
    if not filecmp.cmp(wheels[0], artifacts.wheel, shallow=False):
        raise ReleaseArtifactError("sdist wheel replay bytes differ")


def _scan(source_a: Path, source_b: Path, artifacts: ArtifactSet, unpacked: Path, denylist: Path | None) -> None:
    paths = [source_a, source_b, artifacts.wheel, artifacts.sdist, artifacts.claude, artifacts.codex, unpacked]
    command = [sys.executable, str(source_a / "scripts/check_public.py")]
    if denylist is not None:
        command.extend(("--denylist", str(denylist)))
    command.extend(str(path) for path in paths)
    subprocess.run(command, check=True, shell=False, capture_output=True, text=True)


def _write_evidence(evidence: Path, source: Path, artifacts: ArtifactSet, commit: str, epoch: int) -> None:
    names = expected_asset_names("0.1.0")
    hashes = {name: _sha256(artifacts.root / name) for name in names}
    lines = [f"{hashes[name]}  {name}" for name in sorted(names)]
    (evidence / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dockerfile = source / "tools/release/Dockerfile"
    lockfile = source / "requirements/release.txt"
    payload = {
        "schema": 1,
        "commit": commit,
        "source_date_epoch": epoch,
        "platform": "linux/amd64",
        "python": "3.14.7",
        "base_image": BASE_IMAGE,
        "builder_definition_sha256": hashlib.sha256(dockerfile.read_bytes() + b"\0" + lockfile.read_bytes()).hexdigest(),
        "packages": _read_lock_versions(lockfile),
        "artifacts": [
            {"name": name, "sha256": hashes[name], "size": (artifacts.root / name).stat().st_size}
            for name in names
        ],
    }
    (evidence / "build.json").write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _promote(output: Path, artifacts: ArtifactSet, hashes: dict[str, str]) -> None:
    pending = output / "selected.pending"
    selected = output / "selected"
    if selected.exists() or pending.exists():
        raise ReleaseArtifactError("selected output already exists")
    pending.mkdir()
    try:
        for name in expected_asset_names("0.1.0"):
            shutil.copyfile(artifacts.root / name, pending / name)
            if _sha256(pending / name) != hashes[name] or (pending / name).stat().st_size != (artifacts.root / name).stat().st_size:
                raise ReleaseArtifactError("selected artifact changed during promotion")
        os.rename(pending, selected)
    except OSError as error:
        raise ReleaseArtifactError("selected artifact promotion failed") from error


def build_and_verify(
    source_a: Path,
    source_b: Path,
    output: Path,
    commit: str,
    epoch: int,
    denylist: Path | None = None,
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseArtifactError("commit must be lowercase 40-hex")
    _validate_environment(epoch)
    _validate_roots(Path(source_a), Path(source_b), Path(output))
    previous_umask = os.umask(0o022)
    try:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        candidate_a_root = output / "candidate-a"
        candidate_b_root = output / "candidate-b"
        evidence = output / "evidence"
        (evidence / "work").mkdir(parents=True, exist_ok=False)
        _build_one_source(Path(source_a), candidate_a_root, evidence / "work" / "a", epoch)
        _build_one_source(Path(source_b), candidate_b_root, evidence / "work" / "b", epoch)
        candidate_a = ArtifactSet.load(candidate_a_root, "0.1.0")
        candidate_b = ArtifactSet.load(candidate_b_root, "0.1.0")
        hashes = compare_artifact_sets(candidate_a, candidate_b)
        for artifacts, source in ((candidate_a, Path(source_a)), (candidate_b, Path(source_b))):
            validate_wheel(artifacts.wheel, source, "0.1.0", epoch)
            validate_sdist(artifacts.sdist, source, "0.1.0", epoch)
            validate_host_zip(artifacts.claude, source, "claude")
            validate_host_zip(artifacts.codex, source, "codex")
        _replay_sdist(candidate_a, evidence, commit, epoch)
        unpacked = evidence / "unpacked"
        unpacked.mkdir(parents=True, exist_ok=False)
        extract_regular_zip(candidate_a.wheel, unpacked / "wheel")
        extract_regular_tar(candidate_a.sdist, unpacked / "sdist", expected_global_comment=commit)
        extract_regular_zip(candidate_a.claude, unpacked / "claude")
        extract_regular_zip(candidate_a.codex, unpacked / "codex")
        _scan(Path(source_a), Path(source_b), candidate_a, unpacked, denylist)
        _write_evidence(evidence, Path(source_a), candidate_a, commit, epoch)
        _promote(output, candidate_a, hashes)
        return hashes
    finally:
        os.umask(previous_umask)
