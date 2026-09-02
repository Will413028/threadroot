from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import stat
import tomllib
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HOST_MANIFESTS = {
    "claude": Path(".claude-plugin/plugin.json"),
    "codex": Path(".codex-plugin/plugin.json"),
}
COMMON_ROOTS = (
    Path("LICENSE"),
    Path("README.md"),
    Path("skills"),
    Path("templates"),
)
MARKETPLACE = Path(".claude-plugin/marketplace.json")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class _UTF8ZipInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self) -> tuple[bytes, int]:
        encoded, flags = super()._encodeFilenameFlags()
        return encoded, flags | 0x800


def _relative_name(path: Path) -> str:
    try:
        relative = path.relative_to(REPOSITORY_ROOT)
    except ValueError as error:
        raise ValueError(f"release input escapes repository: {path.name}") from error
    name = relative.as_posix()
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe release path: {name}")
    return name


def _selected_files(path: Path) -> list[Path]:
    if path.is_symlink():
        raise ValueError(f"release input is a symlink: {_relative_name(path)}")
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError(f"release input is not a regular file or directory: {path.name}")

    files: list[Path] = []
    with os.scandir(path) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            child = Path(entry.path)
            if entry.is_symlink():
                raise ValueError(
                    f"release input is a symlink: {_relative_name(child)}"
                )
            if entry.is_dir(follow_symlinks=False):
                files.extend(_selected_files(child))
            elif entry.is_file(follow_symlinks=False):
                files.append(child)
    return files


def _release_inputs(host: str) -> list[tuple[str, bytes]]:
    selected = [REPOSITORY_ROOT / root for root in COMMON_ROOTS]
    selected.extend(
        (
            REPOSITORY_ROOT / MARKETPLACE,
            REPOSITORY_ROOT / HOST_MANIFESTS[host],
        )
    )
    files = [file for root in selected for file in _selected_files(root)]
    named = sorted((_relative_name(path), path.read_bytes()) for path in files)
    names = [name for name, _ in named]
    if len(names) != len(set(names)):
        raise ValueError("duplicate release input")
    return named


def _version() -> str:
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    return str(project["version"])


def build_archive(host: str, output_dir: Path) -> Path:
    if host not in HOST_MANIFESTS:
        raise ValueError(f"unsupported host: {host}")

    version = _version()
    inputs = _release_inputs(host)
    output_dir = Path(output_dir)
    artifact = output_dir / f"threadroot-{host}-{version}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        artifact,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.comment = b""
        for name, payload in inputs:
            info = _UTF8ZipInfo(name, ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.extra = b""
            info.comment = b""
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    for host in HOST_MANIFESTS:
        print(build_archive(host, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
