from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import zipfile


SKIPPED_DIRECTORIES = frozenset({".git", ".venv", "__pycache__"})
HOME_PATH_PATTERN = re.compile("/" + r"(?:Users|home)/[^/\s]+/")
PRIVATE_KEY_PATTERN = re.compile(
    "-----BEGIN " + r"(?:RSA |EC |OPENSSH )?" + "PRIVATE KEY-----"
)
CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?<!\w)[\"']?"
    r"(?:api_key|access_token|client_secret|password|secret)"
    r"[\"']?\s*[:=]\s*(?P<value>.+)$"
)
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:/")
READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
DIRECTORY_FLAGS = READ_FLAGS | os.O_DIRECTORY


class PublicScanError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("public scan failed")


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int | None
    message: str


def _active_terms(denied_terms: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(term for term in denied_terms if term != "")


def _sanitize_display(value: str, denied_terms: tuple[str, ...]) -> str:
    for term in denied_terms:
        value = value.replace(term, "[redacted]")
    return "".join(
        {"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(character, character)
        for character in value
    )


def _finding(
    code: str,
    display_path: str,
    line: int | None,
    denied_terms: tuple[str, ...],
) -> Finding:
    messages = {
        "absolute_home_path": "absolute home-directory path detected",
        "private_key": "private-key header detected",
        "credential_assignment": "credential-like assignment detected",
        "denied_term": "denied term detected",
        "symlink_entry": "filesystem symlink is not allowed",
        "path_escape": "archive member path or link escapes archive root",
    }
    return Finding(
        code,
        _sanitize_display(display_path, denied_terms),
        line,
        messages[code],
    )


def _nonempty_assignment(match: re.Match[str]) -> bool:
    value = match.group("value").strip()
    value = re.sub(r"\s+#.*$", "", value).strip()
    empty_values = {"", '""', "''", "null", "none", "unset", "~", "{}", "[]"}
    if value.casefold() in empty_values:
        return False
    while value.endswith((",", "}", "]")):
        value = value[:-1].rstrip()
        if value.casefold() in empty_values:
            return False
    return True


def _scan_text(
    payload: bytes,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    if b"\x00" in payload:
        return []
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if HOME_PATH_PATTERN.search(line):
            findings.append(
                _finding(
                    "absolute_home_path", display_path, line_number, denied_terms
                )
            )
        if PRIVATE_KEY_PATTERN.search(line):
            findings.append(
                _finding("private_key", display_path, line_number, denied_terms)
            )
        assignment = CREDENTIAL_PATTERN.search(line)
        if assignment is not None and _nonempty_assignment(assignment):
            findings.append(
                _finding(
                    "credential_assignment", display_path, line_number, denied_terms
                )
            )
        if any(term in line for term in denied_terms):
            findings.append(
                _finding("denied_term", display_path, line_number, denied_terms)
            )
    return findings


def _normalized_archive_path(name: str) -> str:
    return name.replace("\\", "/")


def _is_absolute_archive_path(name: str) -> bool:
    normalized = _normalized_archive_path(name)
    return normalized.startswith("/") or bool(
        WINDOWS_ABSOLUTE_PATTERN.match(normalized)
    )


def _member_name_is_unsafe(name: str) -> bool:
    normalized = _normalized_archive_path(name)
    return _is_absolute_archive_path(normalized) or ".." in PurePosixPath(
        normalized
    ).parts


def _link_escapes(member_name: str, target: str, *, relative_to_member: bool) -> bool:
    target = _normalized_archive_path(target)
    if _is_absolute_archive_path(target):
        return True
    base_parts = (
        list(PurePosixPath(_normalized_archive_path(member_name)).parent.parts)
        if relative_to_member
        else []
    )
    for part in PurePosixPath(target).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not base_parts:
                return True
            base_parts.pop()
        else:
            base_parts.append(part)
    return False


def _archive_display(container: str, member: str) -> str:
    return f"{container}!{member}"


def _scan_zip(
    payload: bytes,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
                member_display = _archive_display(display_path, info.filename)
                unsafe = _member_name_is_unsafe(info.filename)
                mode = info.external_attr >> 16
                is_link = stat.S_ISLNK(mode)
                if unsafe:
                    findings.append(
                        _finding("path_escape", member_display, None, denied_terms)
                    )
                if is_link:
                    target = archive.read(info).decode("utf-8")
                    if not unsafe and target and _link_escapes(
                        info.filename, target, relative_to_member=True
                    ):
                        findings.append(
                            _finding("path_escape", member_display, None, denied_terms)
                        )
                    continue
                if info.is_dir():
                    continue
                member_payload = archive.read(info)
                findings.extend(
                    _scan_text(member_payload, member_display, denied_terms)
                )
    except Exception:
        raise PublicScanError() from None
    return findings


def _scan_open_tar(
    archive: tarfile.TarFile,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            member_display = _archive_display(display_path, member.name)
            unsafe = _member_name_is_unsafe(member.name)
            if unsafe:
                findings.append(
                    _finding("path_escape", member_display, None, denied_terms)
                )
            if member.issym() or member.islnk():
                if not unsafe and _link_escapes(
                    member.name,
                    member.linkname,
                    relative_to_member=member.issym(),
                ):
                    findings.append(
                        _finding("path_escape", member_display, None, denied_terms)
                    )
                continue
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise PublicScanError()
            findings.extend(_scan_text(stream.read(), member_display, denied_terms))
    except Exception:
        raise PublicScanError() from None
    return findings


def _scan_regular_payload(
    payload: bytes,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    if zipfile.is_zipfile(io.BytesIO(payload)):
        return _scan_zip(payload, display_path, denied_terms)
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
    except tarfile.ReadError:
        return _scan_text(payload, display_path, denied_terms)
    except Exception:
        raise PublicScanError() from None
    with archive:
        return _scan_open_tar(archive, display_path, denied_terms)


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _lstat_at(parent_fd: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        raise PublicScanError() from None


def _open_at(
    parent_fd: int,
    name: str,
    flags: int,
    expected: os.stat_result,
) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise PublicScanError() from None
    if _stat_signature(opened) != _stat_signature(expected):
        os.close(descriptor)
        raise PublicScanError()
    return descriptor


def _read_at(parent_fd: int, name: str, expected: os.stat_result) -> bytes:
    descriptor = _open_at(parent_fd, name, READ_FLAGS, expected)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after_read = os.fstat(descriptor)
        current = _lstat_at(parent_fd, name)
        if (
            _stat_signature(after_read) != _stat_signature(expected)
            or _stat_signature(current) != _stat_signature(expected)
        ):
            raise PublicScanError()
        return b"".join(chunks)
    except OSError:
        raise PublicScanError() from None
    finally:
        os.close(descriptor)


def _scan_directory(
    descriptor: int,
    prefix: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    try:
        names = sorted(os.listdir(descriptor))
    except OSError:
        raise PublicScanError() from None
    findings: list[Finding] = []
    for name in names:
        display = name if not prefix else f"{prefix}/{name}"
        metadata = _lstat_at(descriptor, name)
        if name in SKIPPED_DIRECTORIES and not stat.S_ISLNK(metadata.st_mode):
            continue
        if stat.S_ISLNK(metadata.st_mode):
            findings.append(_finding("symlink_entry", display, None, denied_terms))
            continue
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = _open_at(descriptor, name, DIRECTORY_FLAGS, metadata)
            try:
                findings.extend(_scan_directory(child_fd, display, denied_terms))
                current = _lstat_at(descriptor, name)
                if _stat_signature(current) != _stat_signature(metadata):
                    raise PublicScanError()
            finally:
                os.close(child_fd)
            continue
        if stat.S_ISREG(metadata.st_mode):
            payload = _read_at(descriptor, name, metadata)
            findings.extend(_scan_regular_payload(payload, display, denied_terms))
    return findings


def _open_root(path: Path, metadata: os.stat_result, flags: int) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise PublicScanError() from None
    if _stat_signature(opened) != _stat_signature(metadata):
        os.close(descriptor)
        raise PublicScanError()
    return descriptor


def _current_root(path: Path) -> os.stat_result:
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError:
        raise PublicScanError() from None


def _sort_key(finding: Finding) -> tuple[str, int, str]:
    line = -1 if finding.line is None else finding.line
    return finding.path, line, finding.code


def scan_path(
    path: Path,
    denied_terms: tuple[str, ...] | list[str] = (),
) -> list[Finding]:
    path = Path(path)
    terms = _active_terms(denied_terms)
    metadata = _current_root(path)
    if stat.S_ISLNK(metadata.st_mode):
        return [_finding("symlink_entry", path.name, None, terms)]
    if stat.S_ISDIR(metadata.st_mode):
        descriptor = _open_root(path, metadata, DIRECTORY_FLAGS)
        try:
            findings = _scan_directory(descriptor, "", terms)
            current = _current_root(path)
            if _stat_signature(current) != _stat_signature(metadata):
                raise PublicScanError()
        finally:
            os.close(descriptor)
        return sorted(findings, key=_sort_key)
    if stat.S_ISREG(metadata.st_mode):
        descriptor = _open_root(path, metadata, READ_FLAGS)
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            after_read = os.fstat(descriptor)
            current = _current_root(path)
            if (
                _stat_signature(after_read) != _stat_signature(metadata)
                or _stat_signature(current) != _stat_signature(metadata)
            ):
                raise PublicScanError()
        except OSError:
            raise PublicScanError() from None
        finally:
            os.close(descriptor)
        return sorted(
            _scan_regular_payload(b"".join(chunks), path.name, terms),
            key=_sort_key,
        )
    raise PublicScanError()


def _read_denylist(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    return tuple(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line != ""
    )


def _render(finding: Finding) -> str:
    location = finding.path
    if finding.line is not None:
        location += f":{finding.line}"
    return f"{location}: {finding.code}: {finding.message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--denylist", type=Path)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    try:
        denied_terms = _read_denylist(args.denylist)
        paths = args.paths or [Path(".")]
        findings: list[Finding] = []
        for index, scan_target in enumerate(paths, start=1):
            scanned = scan_path(scan_target, denied_terms)
            if len(paths) > 1:
                scanned = [
                    Finding(
                        finding.code,
                        f"input-{index}/{finding.path}",
                        finding.line,
                        finding.message,
                    )
                    for finding in scanned
                ]
            findings.extend(scanned)
        findings.sort(key=_sort_key)
    except (OSError, UnicodeError, PublicScanError):
        print("public scan failed", file=sys.stderr)
        return 2
    for finding in findings:
        print(_render(finding))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
