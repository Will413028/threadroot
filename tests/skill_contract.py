from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


CONTRACT_KEYS = {
    "extends",
    "drift",
    "secrets",
    "confirmation-order",
    "confirmation-cadence",
    "local-adapter",
    "write-gate",
    "decision-gate",
    "draft-gate",
    "followup-routing",
    "project-backlink",
    "supersession",
}


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
        if key not in CONTRACT_KEYS:
            raise AssertionError(f"unknown contract key in {path}: {key}")
        if key in fields:
            raise AssertionError(f"duplicate contract key in {path}: {key}")
        fields[key] = value
    return fields


def _threadroot_commands(text: str) -> frozenset[str]:
    marker = "threadroot-commands"
    matches = list(
        re.finditer(
            r"<!-- threadroot-commands\n(?P<commands>.*?)\n-->",
            text,
            re.DOTALL,
        )
    )
    if text.count(marker) != 1 or len(matches) != 1:
        raise AssertionError("skill must have exactly one closed command inventory")

    match = matches[0]
    lines = match.group("commands").split("\n")
    if any(not line or line != line.strip() for line in lines):
        raise AssertionError("command inventory entries must be non-empty and exact")
    if any(
        line != "threadroot" and not line.startswith("threadroot ")
        for line in lines
    ):
        raise AssertionError("command inventory entries must be Threadroot commands")
    if len(lines) != len(set(lines)):
        raise AssertionError("command inventory entries must be unique")

    outside_inventory = text[: match.start()] + text[match.end() :]
    lowercase_command = re.compile(
        r"(?<![\w-])(?:threadroot|_+threadroot_+)(?![\w-])"
    )
    if lowercase_command.search(outside_inventory):
        raise AssertionError("lowercase threadroot token outside command inventory")

    return frozenset(lines)


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
