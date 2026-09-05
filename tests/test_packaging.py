import json
from pathlib import Path
import re
import tomllib
import unittest

from threadroot import __version__


def load_json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


EXPECTED_PROJECT_URLS = {
    "Homepage": "https://github.com/Will413028/threadroot",
    "Repository": "https://github.com/Will413028/threadroot",
    "Issues": "https://github.com/Will413028/threadroot/issues",
}


EXPECTED_SDIST_ROOTS = [
    ".claude-plugin",
    ".codex-plugin",
    ".dockerignore",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "docs",
    "requirements",
    "scripts",
    "skills",
    "src/threadroot",
    "templates",
    "tests",
    "tools/release",
]


EXPECTED_CLAUDE_MANIFEST = {
    "name": "threadroot",
    "version": "0.1.0",
    "description": "Local-first second-brain workflows for coding agents",
    "author": {
        "name": "Threadroot contributors",
    },
    "license": "Apache-2.0",
    "keywords": [
        "second-brain",
        "agent-skills",
        "local-first",
        "developer-tools",
    ],
}

EXPECTED_CODEX_MANIFEST = {
    "name": "threadroot",
    "version": "0.1.0",
    "description": "Local-first second-brain workflows for coding agents",
    "author": {
        "name": "Threadroot contributors",
    },
    "license": "Apache-2.0",
    "keywords": [
        "second-brain",
        "agent-skills",
        "local-first",
        "developer-tools",
    ],
    "skills": "./skills/",
    "interface": {
        "displayName": "Threadroot",
        "shortDescription": "Local-first second-brain workflows",
        "longDescription": (
            "Set up, query, and maintain a user-owned Markdown vault across "
            "coding-agent sessions."
        ),
        "developerName": "Threadroot contributors",
        "category": "Developer Tools",
        "capabilities": [
            "Interactive",
            "Read",
            "Write",
        ],
        "defaultPrompt": [
            "Set up a user-owned second-brain vault.",
            "Review today's work from my second brain.",
            "Record this work in my second brain.",
        ],
    },
}

EXPECTED_MARKETPLACE_CATALOG = {
    "name": "threadroot",
    "description": "Threadroot local and repository installations",
    "owner": {
        "name": "Threadroot contributors",
    },
    "plugins": [
        {
            "name": "threadroot",
            "description": "Local-first second-brain workflows for coding agents",
            "version": "0.1.0",
            "source": "./",
            "author": {
                "name": "Threadroot contributors",
            },
            "license": "Apache-2.0",
            "keywords": [
                "second-brain",
                "agent-skills",
                "local-first",
                "developer-tools",
            ],
        },
    ],
}


class ManifestTests(unittest.TestCase):
    def test_python_packaging_has_one_hatchling_authority(self) -> None:
        metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            metadata["build-system"],
            {
                "requires": ["hatchling>=1.32,<2"],
                "build-backend": "hatchling.build",
            },
        )
        self.assertEqual(metadata["project"]["license-files"], ["LICENSE"])
        self.assertNotIn("setuptools", metadata.get("tool", {}))
        self.assertFalse(Path("MANIFEST.in").exists())
        self.assertIs(metadata["tool"]["hatch"]["build"]["reproducible"], True)
        self.assertEqual(
            metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"],
            ["src/threadroot"],
        )
        self.assertEqual(
            metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"],
            EXPECTED_SDIST_ROOTS,
        )

    def test_version_matches_python_package_metadata(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
        claude = load_json(".claude-plugin/plugin.json")
        codex = load_json(".codex-plugin/plugin.json")
        marketplace = load_json(".claude-plugin/marketplace.json")
        self.assertEqual(
            {
                __version__,
                project["version"],
                claude["version"],
                codex["version"],
                marketplace["plugins"][0]["version"],
            },
            {"0.1.0"},
        )

    def test_project_urls_match_public_repository(self) -> None:
        project = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )["project"]

        self.assertEqual(project["urls"], EXPECTED_PROJECT_URLS)
        self.assertEqual(project["dependencies"], [])

    def test_claude_manifest_matches_exact_contract(self) -> None:
        self.assertEqual(
            load_json(".claude-plugin/plugin.json"),
            EXPECTED_CLAUDE_MANIFEST,
        )

    def test_codex_manifest_matches_exact_contract(self) -> None:
        self.assertEqual(
            load_json(".codex-plugin/plugin.json"),
            EXPECTED_CODEX_MANIFEST,
        )

    def test_marketplace_catalog_matches_exact_contract(self) -> None:
        self.assertEqual(
            load_json(".claude-plugin/marketplace.json"),
            EXPECTED_MARKETPLACE_CATALOG,
        )

    def test_every_manifest_skill_exists(self) -> None:
        expected = {
            "second-brain-setup",
            "second-brain-doctor",
            "query",
            "recording",
            "morning-review",
            "daily-wrap-up",
            "weekly-review",
            "project-kickoff",
            "decision-log",
        }
        actual = {path.parent.name for path in Path("skills").glob("*/SKILL.md")}
        self.assertEqual(actual, expected)

    def test_manifest_json_is_canonical_and_has_one_trailing_newline(self) -> None:
        for path in (
            Path(".claude-plugin/plugin.json"),
            Path(".claude-plugin/marketplace.json"),
            Path(".codex-plugin/plugin.json"),
        ):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                parsed = json.loads(text)
                self.assertEqual(text, json.dumps(parsed, indent=2) + "\n")

    def test_no_separate_codex_marketplace_exists(self) -> None:
        self.assertFalse(Path(".agents/plugins/marketplace.json").exists())

    def test_shared_skill_bodies_are_provider_neutral(self) -> None:
        for path in sorted(Path("skills").glob("*/SKILL.md")):
            with self.subTest(path=path):
                self.assertNotRegex(
                    path.read_text(encoding="utf-8"),
                    r"\b(?:Claude|Codex)\b",
                )

    def test_host_specific_prose_stays_in_host_or_documentation_paths(self) -> None:
        allowed_roots = {".claude-plugin", ".codex-plugin", "docs", "tests"}
        allowed_files = {Path("AGENTS.md"), Path("README.md")}
        ignored_parts = {".git", ".superpowers", "__pycache__"}
        text_suffixes = {".json", ".md", ".py", ".toml"}

        for path in sorted(Path(".").rglob("*")):
            if (
                not path.is_file()
                or ignored_parts.intersection(path.parts)
                or path.suffix not in text_suffixes
                or path in allowed_files
                or path.parts[0] in allowed_roots
            ):
                continue
            with self.subTest(path=path):
                self.assertNotRegex(
                    path.read_text(encoding="utf-8"),
                    re.compile(r"\b(?:Claude|Codex)\b"),
                )
