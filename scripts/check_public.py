from __future__ import annotations

import argparse
import bz2
from dataclasses import dataclass
import io
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
from typing import BinaryIO, TextIO
import unicodedata
import zipfile
import zlib

if __package__:
    from scripts.release_archives import (
        ValidatedZipMember,
        validate_tar_framing,
        validate_zip_framing,
    )
else:
    from release_archives import (
        ValidatedZipMember,
        validate_tar_framing,
        validate_zip_framing,
    )


SKIPPED_DIRECTORIES = frozenset({".git", ".venv", "__pycache__"})
HOME_PATH_PATTERN = re.compile("/" + r"(?:Users|home)/[^/\s]+/")
PRIVATE_KEY_PATTERN = re.compile(
    "-----BEGIN " + r"(?:RSA |EC |OPENSSH )?" + "PRIVATE KEY-----"
)
CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?<!\w)[\"']?"
    r"(?:api_key|access_token|client_secret|password|secret)"
    r"[\"']?\s*[:=](?P<value>.*)$"
)
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:/")
EMPTY_SCALAR_PATTERN = re.compile(
    r"(?i)(?:\"\"|''|null(?![\w-])|none(?![\w-])|unset(?![\w-])|~)"
)
ZIP_STRUCTURAL_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x01\x02",
    b"PK\x05\x06",
    b"PK\x07\x08",
)
COMPRESSION_SIGNATURES = (
    ("gzip", b"\x1f\x8b"),
    ("bzip2", b"BZh"),
    ("xz", b"\xfd7zXZ\x00"),
)
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_XZ_DECODER_MEMORY = 64 * 1024 * 1024
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
    active_terms = _active_terms(denied_terms)
    for term in active_terms:
        value = value.replace(term, "[redacted]")
    characters: list[str] = []
    short_escapes = {"\n": r"\n", "\r": r"\r", "\t": r"\t"}
    for character in value:
        if character in short_escapes:
            characters.append(short_escapes[character])
        elif unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}:
            codepoint = ord(character)
            if codepoint <= 0xFFFF:
                characters.append(f"\\u{codepoint:04x}")
            else:
                characters.append(f"\\U{codepoint:08x}")
        else:
            characters.append(character)
    sanitized = "".join(characters)
    if any(term in sanitized for term in active_terms):
        return ""
    return sanitized


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


def _empty_container_end(value: str) -> int | None:
    expected_closers: list[str] = []
    pairs = {"{": "}", "[": "]"}
    if not value or value[0] not in pairs:
        return None
    for index, character in enumerate(value):
        if character in pairs:
            expected_closers.append(pairs[character])
        elif character in "}]":
            if not expected_closers or character != expected_closers.pop():
                return None
            if not expected_closers:
                return index + 1
        elif not character.isspace() and character != ",":
            return None
    return None


def _nonempty_assignment(match: re.Match[str]) -> bool:
    value = re.sub(r"\s+#.*$", "", match.group("value")).strip()
    if value == "":
        return False
    empty_scalar = EMPTY_SCALAR_PATTERN.match(value)
    empty_end = (
        empty_scalar.end()
        if empty_scalar is not None
        else _empty_container_end(value)
    )
    if empty_end is None:
        return True
    return any(
        not character.isspace() and character not in ",}]"
        for character in value[empty_end:]
    )


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


def _metadata_contains_denied(
    value: str | bytes,
    denied_terms: tuple[str, ...],
) -> bool:
    try:
        if isinstance(value, str):
            value.encode("utf-8")
            return any(term in value for term in denied_terms)
        return any(term.encode("utf-8") in value for term in denied_terms)
    except UnicodeError:
        raise PublicScanError() from None


def _scan_denied_metadata_values(
    values: tuple[str | bytes, ...],
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    if not any(
        _metadata_contains_denied(value, denied_terms)
        for value in values
    ):
        return []
    return [_finding("denied_term", display_path, None, denied_terms)]


def _scan_denied_metadata(
    value: str | bytes,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    return _scan_denied_metadata_values(
        (value,),
        display_path,
        denied_terms,
    )


def _read_bounded(stream: BinaryIO, expected_size: int) -> bytes:
    if expected_size < 0 or expected_size > MAX_DECOMPRESSED_BYTES:
        raise PublicScanError()
    try:
        payload = stream.read(MAX_DECOMPRESSED_BYTES + 1)
    except Exception:
        raise PublicScanError() from None
    if len(payload) != expected_size or len(payload) > MAX_DECOMPRESSED_BYTES:
        raise PublicScanError()
    return payload


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
    validated_members: tuple[ValidatedZipMember, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) != len(validated_members) or any(
                info.filename != validated.filename
                for info, validated in zip(
                    infos,
                    validated_members,
                    strict=True,
                )
            ):
                raise PublicScanError()
            findings.extend(
                _scan_denied_metadata(
                    archive.comment,
                    _archive_display(display_path, "<archive-comment>"),
                    denied_terms,
                )
            )
            pairs = zip(infos, validated_members, strict=True)
            for info, validated in sorted(
                pairs,
                key=lambda item: item[0].filename,
            ):
                member_display = _archive_display(display_path, info.filename)
                findings.extend(
                    _scan_denied_metadata_values(
                        (info.filename, validated.raw_filename),
                        member_display,
                        denied_terms,
                    )
                )
                try:
                    comment_text = info.comment.decode(
                        "utf-8" if info.flag_bits & 0x800 else "cp437"
                    )
                except UnicodeDecodeError:
                    raise PublicScanError() from None
                findings.extend(
                    _scan_denied_metadata_values(
                        (info.comment, comment_text),
                        _archive_display(member_display, "<comment>"),
                        denied_terms,
                    )
                )
                findings.extend(
                    _scan_denied_metadata(
                        info.extra,
                        _archive_display(member_display, "<extra>"),
                        denied_terms,
                    )
                )
                unsafe = _member_name_is_unsafe(info.filename)
                mode = info.external_attr >> 16
                is_link = stat.S_ISLNK(mode)
                if unsafe:
                    findings.append(
                        _finding("path_escape", member_display, None, denied_terms)
                    )
                if is_link:
                    with archive.open(info) as stream:
                        target_payload = _read_bounded(stream, info.file_size)
                    findings.extend(
                        _scan_denied_metadata(
                            target_payload,
                            _archive_display(member_display, "<link-target>"),
                            denied_terms,
                        )
                    )
                    target = target_payload.decode("utf-8")
                    if not unsafe and target and _link_escapes(
                        info.filename, target, relative_to_member=True
                    ):
                        findings.append(
                            _finding("path_escape", member_display, None, denied_terms)
                        )
                    continue
                if info.is_dir():
                    continue
                with archive.open(info) as stream:
                    member_payload = _read_bounded(stream, info.file_size)
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
        for key, value in sorted(archive.pax_headers.items()):
            findings.extend(
                _scan_denied_metadata(
                    key,
                    _archive_display(display_path, "<pax-key>"),
                    denied_terms,
                )
            )
            findings.extend(
                _scan_denied_metadata(
                    value,
                    _archive_display(display_path, "<pax-value>"),
                    denied_terms,
                )
            )
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            member_display = _archive_display(display_path, member.name)
            findings.extend(
                _scan_denied_metadata(member.name, member_display, denied_terms)
            )
            for field, value in (
                ("uname", member.uname),
                ("gname", member.gname),
            ):
                findings.extend(
                    _scan_denied_metadata(
                        value,
                        _archive_display(member_display, f"<{field}>"),
                        denied_terms,
                    )
                )
            for key, value in sorted(member.pax_headers.items()):
                findings.extend(
                    _scan_denied_metadata(
                        key,
                        _archive_display(member_display, "<pax-key>"),
                        denied_terms,
                    )
                )
                findings.extend(
                    _scan_denied_metadata(
                        value,
                        _archive_display(member_display, "<pax-value>"),
                        denied_terms,
                    )
                )
            unsafe = _member_name_is_unsafe(member.name)
            if unsafe:
                findings.append(
                    _finding("path_escape", member_display, None, denied_terms)
                )
            if member.issym() or member.islnk():
                findings.extend(
                    _scan_denied_metadata(
                        member.linkname,
                        _archive_display(member_display, "<link-target>"),
                        denied_terms,
                    )
                )
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
            findings.extend(
                _scan_text(
                    _read_bounded(stream, member.size),
                    member_display,
                    denied_terms,
                )
            )
    except Exception:
        raise PublicScanError() from None
    return findings


def _has_tar_structure(payload: bytes) -> bool:
    return any(
        payload[offset + 257 : offset + 262] == b"ustar"
        for offset in range(0, len(payload) - 261, 512)
    )


def _gzip_metadata_fields(payload: bytes) -> tuple[tuple[str, bytes], ...]:
    if (
        len(payload) < 18
        or payload[:3] != b"\x1f\x8b\x08"
        or payload[3] & 0xE0
    ):
        raise PublicScanError()
    flags = payload[3]
    cursor = 10
    fields: list[tuple[str, bytes]] = []
    if flags & 0x04:
        if cursor + 2 > len(payload) - 8:
            raise PublicScanError()
        size = int.from_bytes(payload[cursor : cursor + 2], "little")
        cursor += 2
        if cursor + size > len(payload) - 8:
            raise PublicScanError()
        fields.append(("gzip-extra", payload[cursor : cursor + size]))
        cursor += size
    for flag, label in ((0x08, "gzip-filename"), (0x10, "gzip-comment")):
        if not flags & flag:
            continue
        end = payload.find(b"\0", cursor, len(payload) - 8)
        if end < 0:
            raise PublicScanError()
        fields.append((label, payload[cursor:end]))
        cursor = end + 1
    if flags & 0x02:
        cursor += 2
    if cursor > len(payload) - 8:
        raise PublicScanError()
    return tuple(fields)


def _decompress_archive_envelope(
    payload: bytes,
) -> tuple[bytes, tuple[tuple[str, bytes], ...]] | None:
    kind = next(
        (
            name
            for name, signature in COMPRESSION_SIGNATURES
            if payload.startswith(signature)
        ),
        None,
    )
    if kind is None:
        return None
    try:
        if kind == "gzip":
            metadata = _gzip_metadata_fields(payload)
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            expanded = decompressor.decompress(
                payload,
                MAX_DECOMPRESSED_BYTES + 1,
            )
            complete = (
                decompressor.eof
                and not decompressor.unused_data
                and not decompressor.unconsumed_tail
            )
        elif kind == "bzip2":
            metadata = ()
            bzip2 = bz2.BZ2Decompressor()
            expanded = bzip2.decompress(
                payload,
                max_length=MAX_DECOMPRESSED_BYTES + 1,
            )
            complete = bzip2.eof and not bzip2.unused_data
        else:
            metadata = ()
            xz = lzma.LZMADecompressor(
                format=lzma.FORMAT_AUTO,
                memlimit=MAX_XZ_DECODER_MEMORY,
            )
            expanded = xz.decompress(
                payload,
                max_length=MAX_DECOMPRESSED_BYTES + 1,
            )
            complete = xz.eof and not xz.unused_data
    except Exception:
        raise PublicScanError() from None
    if len(expanded) > MAX_DECOMPRESSED_BYTES or not complete:
        raise PublicScanError()
    return expanded, metadata


def _scan_regular_payload(
    payload: bytes,
    display_path: str,
    denied_terms: tuple[str, ...],
) -> list[Finding]:
    if zipfile.is_zipfile(io.BytesIO(payload)):
        try:
            validated_members = validate_zip_framing(
                payload,
                max_member_size=MAX_DECOMPRESSED_BYTES,
            )
        except Exception:
            raise PublicScanError() from None
        return _scan_zip(
            payload,
            display_path,
            denied_terms,
            validated_members,
        )
    if payload.startswith(ZIP_STRUCTURAL_SIGNATURES):
        raise PublicScanError()
    envelope = _decompress_archive_envelope(payload)
    archive_payload = payload if envelope is None else envelope[0]
    envelope_findings: list[Finding] = []
    if envelope is not None:
        for label, value in envelope[1]:
            values: tuple[str | bytes, ...] = (
                (value, value.decode("latin-1"))
                if label in {"gzip-filename", "gzip-comment"}
                else (value,)
            )
            envelope_findings.extend(
                _scan_denied_metadata_values(
                    values,
                    _archive_display(display_path, f"<{label}>"),
                    denied_terms,
                )
            )
    try:
        archive = tarfile.open(fileobj=io.BytesIO(archive_payload), mode="r:")
    except tarfile.ReadError:
        if _has_tar_structure(archive_payload):
            raise PublicScanError() from None
        return envelope_findings + _scan_text(
            archive_payload,
            display_path,
            denied_terms,
        )
    except Exception:
        raise PublicScanError() from None
    with archive:
        try:
            validate_tar_framing(archive_payload)
        except Exception:
            raise PublicScanError() from None
        return envelope_findings + _scan_open_tar(
            archive,
            display_path,
            denied_terms,
        )


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
        findings.extend(_scan_denied_metadata(name, display, denied_terms))
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
    findings = _scan_denied_metadata(path.name, path.name, terms)
    metadata = _current_root(path)
    if stat.S_ISLNK(metadata.st_mode):
        findings.append(_finding("symlink_entry", path.name, None, terms))
        return sorted(findings, key=_sort_key)
    if stat.S_ISDIR(metadata.st_mode):
        descriptor = _open_root(path, metadata, DIRECTORY_FLAGS)
        try:
            findings.extend(_scan_directory(descriptor, "", terms))
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
        findings.extend(
            _scan_regular_payload(b"".join(chunks), path.name, terms)
        )
        return sorted(findings, key=_sort_key)
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


def _write_public_line(
    value: str,
    denied_terms: tuple[str, ...],
    stream: TextIO,
) -> None:
    sanitized = _sanitize_display(value, denied_terms)
    if sanitized != "":
        print(sanitized, file=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--denylist", type=Path)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    denied_terms: tuple[str, ...] = ()
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
        _write_public_line("public scan failed", denied_terms, sys.stderr)
        return 2
    for finding in findings:
        _write_public_line(_render(finding), denied_terms, sys.stdout)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
