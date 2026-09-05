from __future__ import annotations

from pathlib import Path
import re
import shlex
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from scripts.build_release import build_archive


RELEASE_NOTES = Path("docs/releases/v0.1.0.md")
EXPECTED_RELEASE_ASSETS = {
    "threadroot-0.1.0-py3-none-any.whl",
    "threadroot-0.1.0.tar.gz",
    "threadroot-claude-0.1.0.zip",
    "threadroot-codex-0.1.0.zip",
}

PUBLIC_DOCUMENTS = (
    Path("README.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("docs/testing.md"),
    RELEASE_NOTES,
)
EXPECTED_SKILLS = {
    "daily-wrap-up",
    "decision-log",
    "morning-review",
    "project-kickoff",
    "query",
    "recording",
    "second-brain-doctor",
    "second-brain-setup",
    "weekly-review",
}
EXPECTED_ACTIONS = {
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
}
EXPECTED_CI_COMMANDS = [
    "python -m pip install --upgrade pip build",
    "python -m unittest discover -s tests -v",
    "python -m build",
    "python -m pip install --force-reinstall dist/threadroot-0.1.0-py3-none-any.whl",
    "threadroot --version",
    "python scripts/build_release.py --output dist",
    "python scripts/check_public.py .",
    "python scripts/check_public.py dist",
]


def _section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing section: {heading}")
    return match.group("body")


def _inline_matrix_values(workflow: str, key: str) -> list[str]:
    match = re.search(
        rf"^\s+{re.escape(key)}:\s*\[([^]]+)]\s*$", workflow, re.MULTILINE
    )
    if match is None:
        raise AssertionError(f"missing inline matrix key: {key}")
    return [value.strip().strip('"\'') for value in match.group(1).split(",")]


def _non_overwrite_contract_errors(section: str) -> list[str]:
    errors: list[str] = []
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", " ".join(section.split()))
        if sentence.strip()
    ]
    vault_guarantee = any(
        re.search(
            r"(?i)(?:"
            r"never overwrites?\s+existing vault (?:files|content|data)"
            r"|existing vault (?:files|content|data)[^.]*is never overwritten"
            r")",
            sentence,
        )
        for sentence in sentences
    )
    if not vault_guarantee:
        errors.append("vault_no_overwrite_scope")

    pointer_relation = any(
        re.search(r"`--apply(?:`|\s)", sentence)
        and re.search(r"--set-default`", sentence)
        and re.search(
            r"(?i)atomic(?:ally)? replace\w* the machine-local default-vault pointer"
            r"[^.]*only after the vault operation succeeds",
            sentence,
        )
        for sentence in sentences
    )
    if not pointer_relation:
        errors.append("pointer_gate_and_order")

    pointer_is_vault_neutral = any(
        re.search(
            r"(?i)replac\w*[^.]*does not modify vault content",
            sentence,
        )
        for sentence in sentences
    )
    if not pointer_is_vault_neutral:
        errors.append("pointer_vault_separation")

    for claim in (
        r"\bdoes not overwrite existing files\b",
        r"\bexisting content is never overwritten\b",
    ):
        if re.search(rf"(?i){claim}", section):
            errors.append("unscoped_no_overwrite_claim")
    return sorted(set(errors))


class DocumentationTests(unittest.TestCase):
    def test_non_overwrite_contract_distinguishes_vault_from_default_pointer(self) -> None:
        sections = {
            "README Safety": _section(
                Path("README.md").read_text(encoding="utf-8"), "Safety"
            ),
            "SECURITY Non-overwriting writes": _section(
                Path("SECURITY.md").read_text(encoding="utf-8"),
                "Non-overwriting writes",
            ),
        }
        for name, section in sections.items():
            with self.subTest(section=name):
                self.assertEqual(_non_overwrite_contract_errors(section), [])

    def test_non_overwrite_contract_rejects_relational_mutations(self) -> None:
        sections = {
            "README Safety": _section(
                Path("README.md").read_text(encoding="utf-8"), "Safety"
            ),
            "SECURITY Non-overwriting writes": _section(
                Path("SECURITY.md").read_text(encoding="utf-8"),
                "Non-overwriting writes",
            ),
        }
        mutations = {
            "pointer before vault success": (
                "only after the vault operation succeeds",
                "before the vault operation succeeds",
                "pointer_gate_and_order",
            ),
            "pointer replacement modifies vault": (
                "does not modify vault content",
                "does modify vault content",
                "pointer_vault_separation",
            ),
            "apply gate omitted": (
                "--apply --set-default",
                "--set-default",
                "pointer_gate_and_order",
            ),
        }

        for section_name, section in sections.items():
            for mutation_name, (correct, incorrect, expected_error) in mutations.items():
                with self.subTest(section=section_name, mutation=mutation_name):
                    self.assertIn(correct, section)
                    mutated = section.replace(correct, incorrect)
                    self.assertNotEqual(mutated, section)
                    self.assertIn(
                        expected_error,
                        _non_overwrite_contract_errors(mutated),
                    )

    def test_design_goal_scopes_non_overwrite_to_vault_data(self) -> None:
        design = Path(
            "docs/superpowers/specs/2026-09-02-threadroot-v0-design.md"
        ).read_text(encoding="utf-8")
        goals = _section(design, "Goals")
        write_contracts = [
            bullet
            for bullet in re.findall(r"^- (.+)$", goals, re.MULTILINE)
            if "deterministic" in bullet
            and "write" in bullet
            and "non-overwriting" in bullet
        ]

        self.assertEqual(len(write_contracts), 1)
        self.assertRegex(
            write_contracts[0],
            r"(?i)\bevery deterministic vault-data write\b",
        )

    def test_public_document_links_resolve_and_fences_are_balanced(self) -> None:
        for source in PUBLIC_DOCUMENTS:
            with self.subTest(document=source.as_posix()):
                self.assertTrue(source.is_file(), f"missing public document: {source}")
                markdown = source.read_text(encoding="utf-8")
                fences = re.findall(r"^```[A-Za-z0-9_-]*\s*$", markdown, re.MULTILINE)
                self.assertEqual(len(fences) % 2, 0)
                for target in re.findall(r"\[[^]]+]\(([^)]+)\)", markdown):
                    parsed = urlsplit(target)
                    if parsed.scheme or not parsed.path:
                        continue
                    resolved = source.parent / parsed.path
                    self.assertTrue(
                        resolved.is_file(),
                        f"{source}: unresolved repository-relative link {target!r}",
                    )

    def test_readme_skill_inventory_matches_shipped_skills(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        inventory = re.findall(
            r"^- `([^`]+)`(?:\s|$)", _section(readme, "Skills"), re.MULTILINE
        )

        self.assertEqual(len(inventory), len(set(inventory)), "duplicate README skill")
        self.assertEqual(set(inventory), EXPECTED_SKILLS)
        self.assertEqual(
            EXPECTED_SKILLS,
            {path.parent.name for path in Path("skills").glob("*/SKILL.md")},
        )

    def test_readme_repository_install_uses_live_public_remote(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        section = _section(readme, "Install from the Git repository")
        commands = (
            "git clone https://github.com/Will413028/threadroot.git",
            "cd threadroot",
            "python -m pip install .",
            "claude plugin marketplace add Will413028/threadroot --scope user",
            "codex plugin marketplace add Will413028/threadroot",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertRegex(section, rf"(?m)^{re.escape(command)}$")
        self.assertNotIn("OWNER/threadroot", readme)

    def test_readme_release_artifacts_match_real_builder_outputs(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        with TemporaryDirectory() as directory:
            expected_archives = {
                build_archive(host, Path(directory)).name
                for host in ("claude", "codex")
            }

        documented_archives = set(
            re.findall(
                r"\bthreadroot-(?:claude|codex)-[0-9][A-Za-z0-9.-]*\.zip\b",
                readme,
            )
        )
        self.assertEqual(documented_archives, expected_archives)

        versions = {
            name.removeprefix(f"threadroot-{host}-").removesuffix(".zip")
            for host in ("claude", "codex")
            for name in expected_archives
            if name.startswith(f"threadroot-{host}-")
        }
        self.assertEqual(len(versions), 1)
        version = versions.pop()
        self.assertEqual(
            set(
                re.findall(
                    r"\bthreadroot-[0-9][A-Za-z0-9.-]*-py3-none-any\.whl\b",
                    readme,
                )
            ),
            {f"threadroot-{version}-py3-none-any.whl"},
        )

        markdown_targets = re.findall(r"\[[^]]+]\(([^)]+)\)", readme)
        self.assertFalse(any("OWNER/threadroot" in target for target in markdown_targets))

    def test_v010_release_notes_match_distribution_contract(self) -> None:
        notes = RELEASE_NOTES.read_text(encoding="utf-8")
        documented_assets = set(
            re.findall(
                r"\bthreadroot-(?:"
                r"[0-9]+\.[0-9]+\.[0-9]+-py3-none-any\.whl|"
                r"[0-9]+\.[0-9]+\.[0-9]+\.tar\.gz|"
                r"(?:claude|codex)-[0-9]+\.[0-9]+\.[0-9]+\.zip"
                r")\b",
                notes,
            )
        )
        required_statements = (
            "first public release",
            "A complete installation needs both layers",
            "deterministic CLI",
            "nine portable Agent Skills",
            "Python 3.11 through 3.14 on macOS and Linux",
            "local-first and has no telemetry",
            "leaves your Markdown and Git vault intact when uninstalled",
            "public interfaces are pre-1.0",
            "PyPI and OpenAI universal Plugins Directory installation are not available",
        )

        self.assertEqual(documented_assets, EXPECTED_RELEASE_ASSETS)
        for statement in required_statements:
            with self.subTest(statement=statement):
                self.assertIn(statement, notes)
        self.assertNotIn("OWNER/threadroot", notes)

    def test_source_manifest_includes_public_policy_documents(self) -> None:
        direct_includes: set[str] = set()
        for line in Path("MANIFEST.in").read_text(encoding="utf-8").splitlines():
            fields = shlex.split(line, comments=True)
            if len(fields) == 2 and fields[0] == "include":
                direct_includes.add(fields[1])

        self.assertTrue({"CONTRIBUTING.md", "SECURITY.md"} <= direct_includes)

    def test_ci_has_exact_matrix_pins_and_validation_commands(self) -> None:
        workflow_path = Path(".github/workflows/ci.yml")
        self.assertTrue(workflow_path.is_file(), "missing CI workflow")
        workflow = workflow_path.read_text(encoding="utf-8")
        actions = re.findall(r"^\s+- uses:\s*(\S+)", workflow, re.MULTILINE)

        self.assertEqual(set(actions), EXPECTED_ACTIONS)
        self.assertEqual(len(actions), len(EXPECTED_ACTIONS))
        for action in actions:
            with self.subTest(action=action):
                self.assertRegex(action, r"@[0-9a-f]{40}$")

        self.assertEqual(
            _inline_matrix_values(workflow, "os"),
            ["ubuntu-latest", "macos-latest"],
        )
        self.assertEqual(
            _inline_matrix_values(workflow, "python"),
            ["3.11", "3.12", "3.13", "3.14"],
        )
        self.assertIn("fail-fast: false", workflow)
        self.assertIn("contents: read", workflow)
        self.assertEqual(
            re.findall(r"^\s+- run:\s*(.+)$", workflow, re.MULTILINE),
            EXPECTED_CI_COMMANDS,
        )
        self.assertRegex(workflow, r"(?m)^\s+PYTHONPATH:\s*src:\.\s*$")


if __name__ == "__main__":
    unittest.main()
