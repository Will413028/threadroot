from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import stat
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
    return value not in {'""', "''"}


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
    path: Path,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    with zipfile.ZipFile(path) as archive:
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
                try:
                    target = archive.read(info).decode("utf-8")
                except (KeyError, OSError, RuntimeError, UnicodeDecodeError):
                    target = ""
                if not unsafe and target and _link_escapes(
                    info.filename, target, relative_to_member=True
                ):
                    findings.append(
                        _finding("path_escape", member_display, None, denied_terms)
                    )
                continue
            if info.is_dir():
                continue
            try:
                payload = archive.read(info)
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
                continue
            findings.extend(_scan_text(payload, member_display, denied_terms))
    return findings


def _scan_tar(
    path: Path,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    with tarfile.open(path, "r:*") as archive:
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
            try:
                stream = archive.extractfile(member)
                payload = b"" if stream is None else stream.read()
            except (KeyError, OSError, tarfile.TarError):
                continue
            findings.extend(_scan_text(payload, member_display, denied_terms))
    return findings


def _scan_regular_file(
    path: Path,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    if zipfile.is_zipfile(path):
        return _scan_zip(path, display_path, denied_terms)
    if tarfile.is_tarfile(path):
        return _scan_tar(path, display_path, denied_terms)
    return _scan_text(path.read_bytes(), display_path, denied_terms)


def _walk_directory(root: Path) -> list[tuple[Path, str, bool]]:
    found: list[tuple[Path, str, bool]] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                if entry.name in SKIPPED_DIRECTORIES and not entry.is_symlink():
                    continue
                child = Path(entry.path)
                relative = child.relative_to(root).as_posix()
                if entry.is_symlink():
                    found.append((child, relative, True))
                elif entry.is_dir(follow_symlinks=False):
                    visit(child)
                elif entry.is_file(follow_symlinks=False):
                    found.append((child, relative, False))

    visit(root)
    return found


def _sort_key(finding: Finding) -> tuple[str, int, str]:
    line = -1 if finding.line is None else finding.line
    return finding.path, line, finding.code


def scan_path(
    path: Path,
    denied_terms: tuple[str, ...] | list[str] = (),
) -> list[Finding]:
    path = Path(path)
    terms = _active_terms(denied_terms)
    if path.is_symlink():
        return [_finding("symlink_entry", path.name, None, terms)]
    if path.is_dir():
        findings: list[Finding] = []
        for child, display, is_link in _walk_directory(path):
            if is_link:
                findings.append(_finding("symlink_entry", display, None, terms))
            else:
                findings.extend(_scan_regular_file(child, display, terms))
        return sorted(findings, key=_sort_key)
    if path.is_file():
        return sorted(_scan_regular_file(path, path.name, terms), key=_sort_key)
    raise FileNotFoundError(path)


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
    denied_terms = _read_denylist(args.denylist)
    paths = args.paths or [Path(".")]
    findings = sorted(
        (
            finding
            for scan_target in paths
            for finding in scan_path(scan_target, denied_terms)
        ),
        key=_sort_key,
    )
    for finding in findings:
        print(_render(finding))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
