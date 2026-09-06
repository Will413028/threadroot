from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

from scripts.release_archives import extract_regular_tar_payload


class VerifiedReleaseError(RuntimeError):
    """Stable public error for verified-release validation failures."""


REPOSITORY = Path(__file__).resolve().parent.parent
RUNNER_FILES = (
    ".dockerignore", "requirements/release.txt", "tools/release/Dockerfile",
    "pyproject.toml", "scripts/build_verified_release.py", "scripts/release_archives.py",
    "scripts/release_artifacts.py", "scripts/build_release.py", "scripts/check_public.py",
)


def _reject_path(value: str | Path) -> None:
    text = os.fspath(value)
    if any(ord(char) < 32 for char in text) or "," in text:
        raise VerifiedReleaseError("unsafe host path")


def _read_regular(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            payload = b"".join(iter(lambda: os.read(descriptor, 1024 * 1024), b""))
        finally:
            os.close(descriptor)
        return payload
    except OSError as error:
        raise VerifiedReleaseError("required input is missing or unsafe") from error


def canonical_image_tag(dockerfile: Path, lockfile: Path) -> str:
    digest = hashlib.sha256(_read_regular(Path(dockerfile)) + b"\0" + _read_regular(Path(lockfile))).hexdigest()
    return f"threadroot-release-builder:{digest}"


def _mount(path: Path, destination: str, readonly: bool = True) -> str:
    if not path.is_absolute():
        raise VerifiedReleaseError("host path must be absolute")
    _reject_path(path)
    return f"type=bind,src={path},dst={destination}" + (",readonly" if readonly else "")


def docker_run_argv(image: str, source_a: Path, source_b: Path, output: Path,
                    commit: str, epoch: int, uid: int, gid: int,
                    denylist: Path | None) -> list[str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or epoch < 0:
        raise VerifiedReleaseError("invalid commit or epoch")
    if denylist is not None:
        _reject_path(denylist)
    argv = ["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=512m",
            "--user", f"{uid}:{gid}", "--workdir", "/source-a",
            "--env", "THREADROOT_CANONICAL_BUILD=1", "--env", f"SOURCE_DATE_EPOCH={epoch}",
            "--env", "TZ=UTC", "--env", "LC_ALL=C.UTF-8", "--env", "LANG=C.UTF-8",
            "--env", "PYTHONHASHSEED=0", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "HOME=/tmp", "--mount", _mount(source_a, "/source-a"),
            "--mount", _mount(source_b, "/source-b"), "--mount", _mount(output, "/release-output", False)]
    if denylist is not None:
        argv.extend(["--mount", _mount(denylist, "/run/threadroot/denylist")])
    argv.extend([image, "python", "-m", "scripts.build_verified_release", "--inside",
                  "--source-a", "/source-a", "--source-b", "/source-b", "--output",
                  "/release-output", "--commit", commit, "--epoch", str(epoch)])
    if denylist is not None:
        argv.extend(["--denylist", "/run/threadroot/denylist"])
    return argv


def _docker_build_argv(image: str, source_a: Path) -> list[str]:
    return ["docker", "build", "--platform", "linux/amd64", "--pull", "--file",
            str(source_a / "tools/release/Dockerfile"), "--tag", image, str(source_a)]


def _validate_docker_run_argv(argv: list[str]) -> None:
    if argv[:4] != ["docker", "run", "--rm", "--platform"] or argv[4] != "linux/amd64":
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    for option in ("--read-only", "--network", "--cap-drop", "--security-opt", "--user", "--workdir", "--pids-limit", "--tmpfs"):
        if argv.count(option) != 1:
            raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    if argv[argv.index("--network") + 1] != "none" or argv[argv.index("--cap-drop") + 1] != "ALL":
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    if argv[argv.index("--security-opt") + 1] != "no-new-privileges" or "--privileged" in argv:
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    if argv[argv.index("--pids-limit") + 1] != "256" or argv[argv.index("--tmpfs") + 1] != "/tmp:rw,nosuid,nodev,noexec,size=512m":
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    if argv[argv.index("--workdir") + 1] != "/source-a":
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    mounts = [value for index, value in enumerate(argv) if index and argv[index - 1] == "--mount"]
    if len(mounts) not in {3, 4} or not any("dst=/release-output" in value and ",readonly" not in value for value in mounts):
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    if sum(",readonly" not in value for value in mounts) != 1:
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")
    if "python" not in argv or "-m" not in argv or "scripts.build_verified_release" not in argv or "--inside" not in argv:
        raise VerifiedReleaseError("docker artifact perimeter is incomplete")


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPOSITORY, check=True,
                            capture_output=True, text=True)
    return result.stdout


def _archive_commit(commit: str) -> bytes:
    result = subprocess.run(["git", "archive", "--format=tar", commit], cwd=REPOSITORY,
                            check=True, capture_output=True)
    return result.stdout


def _runner_bytes_match(commit: str) -> bool:
    for name in RUNNER_FILES:
        if _read_regular(REPOSITORY / name) != subprocess.run(
                ["git", "show", f"{commit}:{name}"], cwd=REPOSITORY, check=True,
                capture_output=True).stdout:
            return False
    return True


def _safe_output(path: Path) -> None:
    _reject_path(path)
    if not path.is_absolute() or path.is_symlink() or path == REPOSITORY or REPOSITORY in path.parents:
        raise VerifiedReleaseError("output must be absolute and outside repository")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise VerifiedReleaseError("output must be missing or empty")


def _validate_host_denylist(path: Path | None) -> None:
    if path is None:
        return
    _reject_path(path)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise VerifiedReleaseError("denylist is missing or unsafe") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise VerifiedReleaseError("denylist is missing or unsafe")


def _sanitized_failure(error: subprocess.CalledProcessError, args: argparse.Namespace) -> str:
    text = " ".join(str(value) for value in (error.stdout, error.stderr) if value)
    labels = ((str(REPOSITORY), "[repository]"), (str(Path(args.output)), "[output]"))
    if args.denylist:
        labels += ((str(Path(args.denylist)), "[denylist]"),)
    for source, label in labels:
        text = text.replace(source, label)
    return text or "verified release subprocess failed"


def _inside(args: argparse.Namespace) -> int:
    if os.environ.get("THREADROOT_CANONICAL_BUILD") != "1":
        raise VerifiedReleaseError("canonical container sentinel is required")
    if (args.source_a, args.source_b, args.output) != ("/source-a", "/source-b", "/release-output"):
        raise VerifiedReleaseError("noncanonical container paths")
    from scripts.release_artifacts import build_and_verify
    build_and_verify(Path(args.source_a), Path(args.source_b), Path(args.output), args.commit, args.epoch,
                     Path(args.denylist) if args.denylist else None)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build_verified_release")
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--source-a")
    parser.add_argument("--source-b")
    parser.add_argument("--output", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--epoch", type=int)
    parser.add_argument("--denylist")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.inside:
            if args.epoch is None:
                raise VerifiedReleaseError("epoch is required")
            return _inside(args)
        if args.epoch is not None:
            raise VerifiedReleaseError("epoch is outer-controlled")
        if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
            raise VerifiedReleaseError("commit must be a full 40-character SHA")
        _safe_output(Path(args.output))
        if _git("status", "--porcelain=v1", "--untracked-files=all"):
            raise VerifiedReleaseError("repository must be clean")
        if _git("cat-file", "-t", args.commit).strip() != "commit":
            raise VerifiedReleaseError("commit must identify a commit object")
        if not _runner_bytes_match(args.commit):
            raise VerifiedReleaseError("runner files differ from selected commit")
        epoch_text = _git("show", "-s", "--format=%ct", args.commit).strip()
        if not epoch_text.isdecimal() or int(epoch_text) < 0:
            raise VerifiedReleaseError("commit epoch is invalid")
        epoch = int(epoch_text)
        output = Path(args.output)
        source_a, source_b, build = output / "source-a", output / "source-b", output / "build"
        _validate_host_denylist(Path(args.denylist) if args.denylist else None)
        output.mkdir(parents=True, exist_ok=True)
        extract_regular_tar_payload(_archive_commit(args.commit), source_a, expected_global_comment=args.commit)
        extract_regular_tar_payload(_archive_commit(args.commit), source_b, expected_global_comment=args.commit)
        build.mkdir()
        image = canonical_image_tag(source_a / "tools/release/Dockerfile", source_a / "requirements/release.txt")
        subprocess.run(_docker_build_argv(image, source_a),
                       check=True, capture_output=True, text=True)
        uid, gid = os.getuid(), os.getgid()
        run_argv = docker_run_argv(image, source_a, source_b, build, args.commit, epoch, uid, gid,
                                   Path(args.denylist) if args.denylist else None)
        _validate_docker_run_argv(run_argv)
        subprocess.run(run_argv,
                       check=True, capture_output=True, text=True)
        return 0
    except subprocess.CalledProcessError as error:
        print(_sanitized_failure(error, args), file=sys.stderr)
        return 1
    except OSError:
        print("verified release subprocess failed", file=sys.stderr)
        return 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
