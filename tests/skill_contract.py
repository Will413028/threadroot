from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class SkillDocument:
    name: str
    description: str
    body: str


@dataclass(frozen=True)
class EffectiveSkillContract:
    commands: frozenset[str]
    invariants: tuple[tuple[str, str], ...]


def load_skill(name: str) -> SkillDocument:
    path = Path("skills") / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"{path} must have one YAML frontmatter block")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"invalid frontmatter line in {path}: {line}")
        key = key.strip()
        if key in fields:
            raise AssertionError(f"duplicate frontmatter key in {path}: {key}")
        fields[key] = value.strip().strip('"')

    if set(fields) != {"name", "description"}:
        raise AssertionError(f"{path} frontmatter keys must be name and description")
    if not fields["name"] or not fields["description"]:
        raise AssertionError(f"{path} frontmatter values must not be empty")
    return SkillDocument(fields["name"], fields["description"], match.group(2))


def _contract_fields(path: Path, text: str) -> dict[str, str]:
    matches = re.findall(
        r"<!-- threadroot-contract\n(.*?)\n-->",
        text,
        re.DOTALL,
    )
    if len(matches) != 1:
        raise AssertionError(f"{path} must have one threadroot contract block")

    fields: dict[str, str] = {}
    for line in matches[0].splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not key or not value:
            raise AssertionError(f"invalid contract line in {path}: {line}")
        if key not in {"extends", "drift", "secrets"}:
            raise AssertionError(f"unknown contract key in {path}: {key}")
        if key in fields:
            raise AssertionError(f"duplicate contract key in {path}: {key}")
        fields[key] = value
    return fields


def _threadroot_commands(text: str) -> frozenset[str]:
    commands: set[str] = set()
    accounted_offsets: set[int] = set()
    lexical_invocation = re.compile(r"(?<![\w-])threadroot(?![\w-])")

    lines = text.splitlines(keepends=True)
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)

    fenced_ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        opener = re.fullmatch(r" {0,3}(?P<fence>`{3,}|~{3,}).*", line)
        if opener is None:
            index += 1
            continue

        fence = opener.group("fence")
        closer = re.compile(
            rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$"
        )
        closing_index = index + 1
        while closing_index < len(lines):
            closing_line = lines[closing_index].rstrip("\r\n")
            if closer.fullmatch(closing_line) is not None:
                break
            closing_index += 1

        if closing_index == len(lines):
            remaining = text[line_offsets[index] :]
            if lexical_invocation.search(remaining) is not None:
                raise AssertionError("unclosed fence contains threadroot command syntax")
            index += 1
            continue

        fenced_ranges.append(
            (
                line_offsets[index],
                line_offsets[closing_index] + len(lines[closing_index]),
            )
        )
        for body_index in range(index + 1, closing_index):
            body_line = lines[body_index].rstrip("\r\n")
            code = body_line.strip()
            if code == "threadroot" or code.startswith("threadroot "):
                commands.add(code)
                accounted_offsets.add(
                    line_offsets[body_index] + body_line.index("threadroot")
                )
        index = closing_index + 1

    segment_start = 0
    segments: list[tuple[int, int]] = []
    for fence_start, fence_end in fenced_ranges:
        segments.append((segment_start, fence_start))
        segment_start = fence_end
    segments.append((segment_start, len(text)))

    inline_pattern = re.compile(
        r"(?<!`)(?P<fence>`+)(?!`)(?P<code>.*?)(?<!`)(?P=fence)(?!`)",
        re.DOTALL,
    )
    for start, end in segments:
        segment = text[start:end]
        for match in inline_pattern.finditer(segment):
            raw_code = match.group("code")
            code = re.sub(r"\r\n?|\n", " ", raw_code)
            if code.startswith(" ") and code.endswith(" ") and code.strip(" "):
                code = code[1:-1]
            if code == "threadroot" or code.startswith("threadroot "):
                commands.add(code)
                invocation = lexical_invocation.search(raw_code)
                if invocation is not None:
                    accounted_offsets.add(
                        start + match.start("code") + invocation.start()
                    )

    lexical_offsets = {match.start() for match in lexical_invocation.finditer(text)}
    unaccounted = lexical_offsets - accounted_offsets
    if unaccounted:
        raise AssertionError("unaccounted threadroot command syntax")

    return frozenset(commands)


def load_effective_contract(
    path: Path,
    allowed_commands: frozenset[str],
) -> EffectiveSkillContract:
    path = path.resolve()
    text = path.read_text(encoding="utf-8")
    local = _contract_fields(path, text)
    extends = local.pop("extends", None)
    if extends is None:
        raise AssertionError(f"{path} contract must extend a shared contract")
    extends_path = Path(extends)
    if extends_path.is_absolute():
        raise AssertionError(f"{path} shared contract path must be relative")

    skills_root = path.parent.parent.resolve()
    shared_path = (path.parent / extends_path).resolve()
    try:
        shared_path.relative_to(skills_root)
    except ValueError:
        raise AssertionError(f"{path} shared contract escapes skills root") from None

    shared = _contract_fields(
        shared_path,
        shared_path.read_text(encoding="utf-8"),
    )
    if "extends" in shared:
        raise AssertionError(f"{shared_path} must not extend another contract")

    invariants = shared | local
    required = {"drift": "stop", "secrets": "never-read"}
    for key, value in required.items():
        if invariants.get(key) != value:
            raise AssertionError(
                f"{path} effective contract requires {key}={value}"
            )

    commands = _threadroot_commands(text)
    if commands != allowed_commands:
        raise AssertionError(
            f"{path} command inventory must be exact; "
            f"extra={sorted(commands - allowed_commands)}, "
            f"missing={sorted(allowed_commands - commands)}"
        )

    return EffectiveSkillContract(
        commands=commands,
        invariants=tuple(sorted(invariants.items())),
    )
