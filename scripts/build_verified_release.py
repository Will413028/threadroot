from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata


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
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in text) or "," in text:
        raise VerifiedReleaseError("unsafe host path")


def _validate_identity(uid: int, gid: int) -> None:
    if any(type(value) is not int or value <= 0 for value in (uid, gid)):
        raise VerifiedReleaseError("host UID/GID must be positive")


def _host_identity() -> tuple[int, int]:
    getuid, getgid = getattr(os, "getuid", None), getattr(os, "getgid", None)
    if not callable(getuid) or not callable(getgid):
        raise VerifiedReleaseError("host UID/GID is unsupported")
    uid, gid = getuid(), getgid()
    _validate_identity(uid, gid)
    return uid, gid


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


def _canonical_run_argv(image: str, source_a: Path, source_b: Path, output: Path,
                        commit: str, epoch: int, uid: int, gid: int,
                        denylist: Path | None) -> list[str]:
    if not isinstance(image, str) or not re.fullmatch(r"threadroot-release-builder:[0-9a-f]{64}", image):
        raise VerifiedReleaseError("invalid builder image")
    _validate_identity(uid, gid)
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


def docker_run_argv(image: str, source_a: Path, source_b: Path, output: Path,
                    commit: str, epoch: int, uid: int, gid: int,
                    denylist: Path | None) -> list[str]:
    return _canonical_run_argv(image, source_a, source_b, output, commit, epoch, uid, gid, denylist)


def _docker_build_argv(image: str, source_a: Path) -> list[str]:
    return ["docker", "build", "--platform", "linux/amd64", "--pull", "--file",
            str(source_a / "tools/release/Dockerfile"), "--tag", image, str(source_a)]


def _validate_docker_run_argv(argv: list[str], *, image: str, source_a: Path,
                             source_b: Path, output: Path, commit: str, epoch: int,
                             uid: int, gid: int, denylist: Path | None) -> None:
    expected = _canonical_run_argv(image, source_a, source_b, output, commit, epoch, uid, gid, denylist)
    if argv != expected:
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
    try:
        parent = path.parent.resolve(strict=True)
        repository = REPOSITORY.resolve(strict=True)
        resolved = path.resolve()
        if (not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK)
                or resolved == repository or repository in resolved.parents):
            raise OSError
    except (OSError, RuntimeError):
        raise VerifiedReleaseError("output must be absolute and outside repository") from None
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise VerifiedReleaseError("output must be missing or empty")


def _validate_host_denylist(path: Path | None) -> None:
    if path is None:
        return
    _reject_path(path)
    if not path.is_absolute():
        raise VerifiedReleaseError("denylist is missing or unsafe")
    try:
        metadata = path.lstat()
    except OSError as error:
        raise VerifiedReleaseError("denylist is missing or unsafe") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise VerifiedReleaseError("denylist is missing or unsafe")


def _observed_labels(stdout: object, stderr: object,
                     paths: tuple[tuple[str, str], ...]) -> set[str]:
    # Child detail is untrusted. Only a lossy projection onto fixed labels can
    # leave this function; never retain raw words, argv, or exception repr.
    text = "\n".join(value if isinstance(value, str) else value.decode("utf-8", errors="replace")
                     for value in (stdout, stderr) if isinstance(value, (str, bytes)))
    observed = set()
    for source, label in sorted(paths, key=lambda item: len(item[0]), reverse=True):
        if source in text:
            observed.add(label)
            text = text.replace(source, "\0")
    return observed


def _public_status(message: str, observed: set[str],
                   paths: tuple[tuple[str, str], ...]) -> str:
    return " ".join([message, *(label for _, label in paths if label in observed)])


def _run_docker(argv: list[str], phase: str,
                paths: tuple[tuple[str, str], ...]) -> set[str]:
    try:
        result = subprocess.run(argv, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        labels = _observed_labels(error.stdout, error.stderr, paths)
        raise VerifiedReleaseError(_public_status(f"verified release {phase} failed", labels, paths)) from None
    except OSError:
        raise VerifiedReleaseError(f"verified release {phase} failed") from None
    return _observed_labels(result.stdout, result.stderr, paths)


def _inside(args: argparse.Namespace) -> int:
    if os.environ.get("THREADROOT_CANONICAL_BUILD") != "1":
        raise VerifiedReleaseError("canonical container sentinel is required")
    if (args.source_a, args.source_b, args.output) != ("/source-a", "/source-b", "/release-output"):
        raise VerifiedReleaseError("noncanonical container paths")
    from scripts.release_artifacts import build_and_verify
    build_and_verify(Path(args.source_a), Path(args.source_b), Path(args.output), args.commit, args.epoch,
                     Path(args.denylist) if args.denylist else None)
    return 0


class _PublicArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VerifiedReleaseError("invalid command line arguments")


def _parser() -> argparse.ArgumentParser:
    parser = _PublicArgumentParser(prog="build_verified_release")
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
        uid, gid = _host_identity()
        _safe_output(Path(args.output))
        denylist = Path(args.denylist) if args.denylist else None
        _validate_host_denylist(denylist)
        if _git("status", "--porcelain=v1", "--untracked-files=all"):
            raise VerifiedReleaseError("repository must be clean")
        if _git("rev-parse", "--verify", args.commit + "^{commit}").strip() != args.commit:
            raise VerifiedReleaseError("commit must resolve to itself")
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
        from scripts.release_archives import extract_regular_tar_payload
        output.mkdir(exist_ok=True)
        extract_regular_tar_payload(_archive_commit(args.commit), source_a, expected_global_comment=args.commit)
        extract_regular_tar_payload(_archive_commit(args.commit), source_b, expected_global_comment=args.commit)
        build.mkdir()
        image = canonical_image_tag(source_a / "tools/release/Dockerfile", source_a / "requirements/release.txt")
        run_argv = docker_run_argv(image, source_a, source_b, build, args.commit, epoch, uid, gid, denylist)
        _validate_docker_run_argv(run_argv, image=image, source_a=source_a, source_b=source_b,
                                 output=build, commit=args.commit, epoch=epoch, uid=uid, gid=gid, denylist=denylist)
        paths = ((str(REPOSITORY), "[repository]"), (str(source_a), "[source-a]"),
                 (str(source_b), "[source-b]"), (str(output), "[output]"))
        if denylist is not None:
            paths += ((str(denylist), "[denylist]"),)
        observed = _run_docker(_docker_build_argv(image, source_a), "builder", paths)
        observed.update(_run_docker(run_argv, "artifact phase", paths))
        print(_public_status("verified release completed", observed, paths))
        return 0
    except VerifiedReleaseError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("verified release subprocess failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
