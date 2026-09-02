from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from tests import skill_contract
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

CORE_COMMANDS = {
    "second-brain-setup": frozenset(
        {
            "threadroot --version",
            "threadroot init --vault <target> --json",
            "threadroot adopt --vault <target> --json",
            "threadroot init --vault <target> --json --apply",
            "threadroot adopt --vault <target> --json --apply",
            "threadroot doctor --vault <target> --json",
        }
    ),
    "second-brain-doctor": frozenset(
        {"threadroot --version", "threadroot doctor --json"}
    ),
    "query": frozenset({"threadroot --version", "threadroot doctor --json"}),
}

SYNTHETIC_SHARED_CONTRACT = """# Shared Contract

<!-- threadroot-contract
drift=stop
secrets=never-read
-->
"""

SYNTHETIC_SKILL = """---
name: synthetic
description: Use when testing a synthetic contract.
---
# Synthetic

<!-- threadroot-contract
extends=../README.md
-->

Run `threadroot --version`.

Threadroot is the product name. The standalone option `--set-default` is not a
command invocation.
"""


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



class EffectiveSkillContractTests(unittest.TestCase):
    def _loader(self):
        loader = getattr(skill_contract, "load_effective_contract", None)
        self.assertIsNotNone(loader, "effective contract validator is required")
        return loader

    def _write_fixture(
        self,
        directory: str,
        *,
        shared: str = SYNTHETIC_SHARED_CONTRACT,
        skill: str = SYNTHETIC_SKILL,
    ) -> Path:
        skills = Path(directory) / "skills"
        skill_directory = skills / "synthetic"
        skill_directory.mkdir(parents=True)
        (skills / "README.md").write_text(shared, encoding="utf-8")
        path = skill_directory / "SKILL.md"
        path.write_text(skill, encoding="utf-8")
        return path

    def test_core_effective_contracts_have_exact_commands_and_safety(self) -> None:
        expected_invariants = {"drift": "stop", "secrets": "never-read"}
        load_effective_contract = self._loader()

        for name, allowed_commands in CORE_COMMANDS.items():
            with self.subTest(name=name):
                contract = load_effective_contract(
                    Path("skills") / name / "SKILL.md",
                    allowed_commands,
                )
                self.assertEqual(allowed_commands, contract.commands)
                self.assertEqual(expected_invariants, dict(contract.invariants))

    def test_positive_synthetic_contract_is_accepted(self) -> None:
        load_effective_contract = self._loader()
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_fixture(directory)

            contract = load_effective_contract(
                path,
                frozenset({"threadroot --version"}),
            )

        self.assertEqual(frozenset({"threadroot --version"}), contract.commands)
        self.assertEqual(
            {"drift": "stop", "secrets": "never-read"},
            dict(contract.invariants),
        )

    def test_valid_multiline_inline_command_is_normalized(self) -> None:
        load_effective_contract = self._loader()
        skill = SYNTHETIC_SKILL.replace(
            "`threadroot --version`",
            "``threadroot\n--version``",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_fixture(directory, skill=skill)

            contract = load_effective_contract(
                path,
                frozenset({"threadroot --version"}),
            )

        self.assertEqual(frozenset({"threadroot --version"}), contract.commands)

    def test_valid_fences_accept_longer_matching_closers(self) -> None:
        load_effective_contract = self._loader()
        fences = {
            "backtick": "   ```sh\nthreadroot --version\n   ````\n",
            "tilde": "   ~~~sh\nthreadroot --version\n   ~~~~\n",
        }

        for name, fence in fences.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = self._write_fixture(
                    directory,
                    skill=SYNTHETIC_SKILL + "\n" + fence,
                )
                contract = load_effective_contract(
                    path,
                    frozenset({"threadroot --version"}),
                )
                self.assertEqual(
                    frozenset({"threadroot --version"}),
                    contract.commands,
                )

    def test_malformed_or_unaccounted_command_syntax_is_rejected(self) -> None:
        load_effective_contract = self._loader()
        mutations = {
            "multiline inline unknown command": (
                SYNTHETIC_SKILL + "\nRun ``threadroot\nmigrate``.\n"
            ),
            "unclosed inline span": (
                SYNTHETIC_SKILL + "\nRun ``threadroot --version.\n"
            ),
            "mismatched inline delimiter": (
                SYNTHETIC_SKILL + "\nRun ``threadroot --version`.\n"
            ),
            "unclosed backtick fence": (
                SYNTHETIC_SKILL + "\n```sh\nthreadroot --version\n"
            ),
            "unclosed tilde fence": (
                SYNTHETIC_SKILL + "\n~~~sh\nthreadroot --version\n"
            ),
            "mixed fence closing character": (
                SYNTHETIC_SKILL + "\n```sh\nthreadroot --version\n~~~\n"
            ),
            "four-space indented code block": (
                SYNTHETIC_SKILL + "\n    threadroot migrate\n"
            ),
            "bare executable command": SYNTHETIC_SKILL + "\nRun `threadroot`.\n",
        }

        for name, skill in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = self._write_fixture(directory, skill=skill)
                with self.assertRaises(AssertionError):
                    load_effective_contract(
                        path,
                        frozenset({"threadroot --version"}),
                    )

    def test_synthetic_contract_mutations_are_rejected(self) -> None:
        load_effective_contract = self._loader()
        mutations = {
            "missing secrets rule": (
                SYNTHETIC_SHARED_CONTRACT.replace("secrets=never-read\n", ""),
                SYNTHETIC_SKILL,
                "secrets=never-read",
            ),
            "inverted drift rule": (
                SYNTHETIC_SHARED_CONTRACT.replace("drift=stop", "drift=continue"),
                SYNTHETIC_SKILL,
                "drift=stop",
            ),
            "extra command": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL + "\nRun `threadroot migrate`.\n",
                "command inventory",
            ),
            "extra fenced command": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL + "\n```sh\nthreadroot migrate\n```\n",
                "command inventory",
            ),
            "extra tilde-fenced command": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL + "\n~~~sh\nthreadroot migrate\n~~~\n",
                "command inventory",
            ),
            "extra indented backtick-fenced command": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL + "\n   ```sh\nthreadroot migrate\n   ```\n",
                "command inventory",
            ),
            "extra indented tilde-fenced command": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL + "\n   ~~~sh\nthreadroot migrate\n   ~~~\n",
                "command inventory",
            ),
            "extra double-backtick command": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL + "\nRun ``threadroot migrate``.\n",
                "command inventory",
            ),
            "allowed command with extra arguments": (
                SYNTHETIC_SHARED_CONTRACT,
                SYNTHETIC_SKILL.replace(
                    "`threadroot --version`",
                    "`threadroot --version --verbose`",
                ),
                "command inventory",
            ),
        }

        for name, (shared, skill, message) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = self._write_fixture(directory, shared=shared, skill=skill)
                with self.assertRaisesRegex(AssertionError, message):
                    load_effective_contract(
                        path,
                        frozenset({"threadroot --version"}),
                    )

    def test_absolute_shared_contract_path_is_rejected(self) -> None:
        load_effective_contract = self._loader()
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_fixture(directory)
            shared_path = (path.parent.parent / "README.md").resolve()
            path.write_text(
                SYNTHETIC_SKILL.replace(
                    "extends=../README.md",
                    f"extends={shared_path}",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(AssertionError, "relative"):
                load_effective_contract(
                    path,
                    frozenset({"threadroot --version"}),
                )

    def test_shared_contract_resolution_remains_fail_closed(self) -> None:
        load_effective_contract = self._loader()
        invalid_shared_contracts = {
            "outside traversal": "../../README.md",
            "cycle": "../README.md",
            "duplicate key": "../README.md",
        }

        for name, extends in invalid_shared_contracts.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                shared = SYNTHETIC_SHARED_CONTRACT
                if name == "cycle":
                    shared = shared.replace(
                        "drift=stop",
                        "extends=other.md\ndrift=stop",
                    )
                elif name == "duplicate key":
                    shared = shared.replace("drift=stop", "drift=stop\ndrift=stop")
                skill = SYNTHETIC_SKILL.replace("../README.md", extends)
                path = self._write_fixture(directory, shared=shared, skill=skill)

                with self.assertRaises(AssertionError):
                    load_effective_contract(
                        path,
                        frozenset({"threadroot --version"}),
                    )

        with tempfile.TemporaryDirectory() as directory:
            path = self._write_fixture(directory)
            outside = Path(directory) / "outside.md"
            outside.write_text(SYNTHETIC_SHARED_CONTRACT, encoding="utf-8")
            linked = path.parent.parent / "linked.md"
            linked.symlink_to(outside)
            path.write_text(
                SYNTHETIC_SKILL.replace("../README.md", "../linked.md"),
                encoding="utf-8",
            )

            with self.assertRaises(AssertionError):
                load_effective_contract(
                    path,
                    frozenset({"threadroot --version"}),
                )


if __name__ == "__main__":
    unittest.main()
