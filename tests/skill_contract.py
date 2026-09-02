from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class SkillDocument:
    name: str
    description: str
    body: str


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
