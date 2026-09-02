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
    commands = set(re.findall(r"(?<!`)`(threadroot [^`\n]+)`(?!`)", text))
    fenced_blocks = re.findall(
        r"^```[^\n]*\n(.*?)^```[ \t]*$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    for block in fenced_blocks:
        commands.update(
            line.strip()
            for line in block.splitlines()
            if line.strip().startswith("threadroot ")
        )
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

    skills_root = path.parent.parent.resolve()
    shared_path = (path.parent / extends).resolve()
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
