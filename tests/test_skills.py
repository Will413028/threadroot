from __future__ import annotations

from pathlib import Path
import re
import unittest

from tests.skill_contract import load_skill


TEMPLATES = {
    "daily.md": """# {{date}}

## Focus

## Work Log

## Decisions

## Follow-up
""",
    "project.md": """# {{project_name}}

## Current Status

## Pending

## Recent Activity

## Lessons Learned

## Key Decisions
""",
    "decision.md": """# {{decision_title}}

## Context

## Options Considered

## Decision

## Rationale

## Expected Outcome

## Followup

## Review Notes

## Related
""",
    "weekly-review.md": """# Weekly Review {{iso_week}}

## Outcomes

## Decisions

## Carry Forward

## Lessons
""",
}


class PhaseASkillContractTests(unittest.TestCase):
    def test_setup_shared_contract_link_resolves(self) -> None:
        skill_path = Path("skills/second-brain-setup/SKILL.md")
        skill = load_skill("second-brain-setup")
        links = re.findall(r"\[[^]]+\]\(([^)]+)\)", skill.body)

        self.assertIn("../README.md", links)
        self.assertTrue((skill_path.parent / "../README.md").resolve().is_file())

    def test_setup_frontmatter_and_required_sections(self) -> None:
        skill = load_skill("second-brain-setup")

        self.assertEqual("second-brain-setup", skill.name)
        self.assertTrue(skill.description.startswith("Use when "))
        self.assertNotRegex(skill.description, r"threadroot\s+(?:init|adopt|doctor)")
        self.assertEqual(
            ["Inputs", "Procedure", "Safety", "Output"],
            re.findall(r"^## (.+)$", skill.body, re.MULTILINE),
        )

    def test_setup_exposes_safe_cli_command_shapes(self) -> None:
        skill = load_skill("second-brain-setup")
        commands = set(re.findall(r"`(threadroot [^`\n]+)`", skill.body))

        self.assertTrue(
            {
                "threadroot --version",
                "threadroot init --vault <target> --json",
                "threadroot adopt --vault <target> --json",
                "threadroot init --vault <target> --json --apply",
                "threadroot adopt --vault <target> --json --apply",
                "threadroot doctor --vault <target> --json",
            }.issubset(commands)
        )
        self.assertRegex(skill.body, r"(?is)drift.{0,100}\bstop\b|\bstop\b.{0,100}drift")

    def test_public_skill_markdown_has_no_private_or_provider_specific_content(self) -> None:
        skill_paths = sorted(Path("skills").rglob("*.md"))
        self.assertTrue(skill_paths)

        forbidden = {
            "provider name": re.compile(r"\b(?:Claude|Codex)\b"),
            "absolute home path": re.compile(
                r"(?:/(?:Users|home)/[^\s`]+|[A-Za-z]:\\\\Users\\\\[^\s`]+|~/)"
            ),
            "secret assignment": re.compile(
                r"(?im)\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*="
            ),
        }
        for path in skill_paths:
            text = path.read_text(encoding="utf-8")
            for label, pattern in forbidden.items():
                with self.subTest(path=path, invariant=label):
                    self.assertNotRegex(text, pattern)

    def test_public_vault_templates_are_exact(self) -> None:
        for name, expected in TEMPLATES.items():
            with self.subTest(name=name):
                self.assertEqual(
                    expected,
                    (Path("templates/vault") / name).read_text(encoding="utf-8"),
                )

    def test_config_template_matches_runtime(self) -> None:
        from threadroot.config import config_text

        self.assertEqual(
            Path("templates/vault/config.json").read_text(encoding="utf-8"),
            config_text(),
        )


class DoctorSkillContractTests(unittest.TestCase):
    def test_doctor_frontmatter_sections_and_shared_contract(self) -> None:
        skill_path = Path("skills/second-brain-doctor/SKILL.md")
        skill = load_skill("second-brain-doctor")

        self.assertEqual("second-brain-doctor", skill.name)
        self.assertTrue(skill.description.startswith("Use when "))
        self.assertNotRegex(skill.description, r"threadroot\s+doctor")
        self.assertEqual(
            ["Inputs", "Procedure", "Safety", "Output"],
            re.findall(r"^## (.+)$", skill.body, re.MULTILINE),
        )
        links = re.findall(r"\[[^]]+\]\(([^)]+)\)", skill.body)
        self.assertIn("../README.md", links)
        self.assertTrue((skill_path.parent / "../README.md").resolve().is_file())

    def test_doctor_exposes_only_read_only_cli_commands(self) -> None:
        skill = load_skill("second-brain-doctor")
        commands = set(re.findall(r"`(threadroot [^`\n]+)`", skill.body))

        self.assertEqual(
            {"threadroot --version", "threadroot doctor --json"},
            commands,
        )


class QuerySkillContractTests(unittest.TestCase):
    def test_query_frontmatter_sections_and_shared_contract(self) -> None:
        skill_path = Path("skills/query/SKILL.md")
        skill = load_skill("query")

        self.assertEqual("query", skill.name)
        self.assertTrue(skill.description.startswith("Use when "))
        self.assertNotRegex(skill.description, r"threadroot\s+doctor")
        self.assertEqual(
            ["Inputs", "Procedure", "Safety", "Output"],
            re.findall(r"^## (.+)$", skill.body, re.MULTILINE),
        )
        links = re.findall(r"\[[^]]+\]\(([^)]+)\)", skill.body)
        self.assertIn("../README.md", links)
        self.assertTrue((skill_path.parent / "../README.md").resolve().is_file())

    def test_query_exposes_only_read_only_cli_commands(self) -> None:
        skill = load_skill("query")
        commands = set(re.findall(r"`(threadroot [^`\n]+)`", skill.body))

        self.assertEqual(
            {"threadroot --version", "threadroot doctor --json"},
            commands,
        )


if __name__ == "__main__":
    unittest.main()
