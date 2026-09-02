from __future__ import annotations

from pathlib import Path
import re
import shlex
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from scripts.build_release import build_archive


PUBLIC_DOCUMENTS = (
    Path("README.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("docs/testing.md"),
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


class DocumentationTests(unittest.TestCase):
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
