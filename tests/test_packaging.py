import json
from pathlib import Path
import re
import tomllib
import unittest

from threadroot import __version__


def load_json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ManifestTests(unittest.TestCase):
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

    def test_native_manifests_share_public_metadata(self) -> None:
        claude = load_json(".claude-plugin/plugin.json")
        codex = load_json(".codex-plugin/plugin.json")
        common_keys = {
            "name",
            "version",
            "description",
            "author",
            "license",
            "keywords",
        }
        self.assertEqual(set(claude), common_keys)
        self.assertEqual(set(codex), common_keys | {"skills", "interface"})
        for key in common_keys:
            self.assertEqual(claude[key], codex[key])
        self.assertEqual(codex["skills"], "./skills/")

    def test_codex_manifest_has_complete_interface_metadata(self) -> None:
        interface = load_json(".codex-plugin/plugin.json")["interface"]
        self.assertEqual(
            set(interface),
            {
                "displayName",
                "shortDescription",
                "longDescription",
                "developerName",
                "category",
                "capabilities",
                "defaultPrompt",
            },
        )
        self.assertEqual(interface["displayName"], "Threadroot")
        self.assertEqual(interface["developerName"], "Threadroot contributors")
        self.assertEqual(interface["category"], "Developer Tools")
        self.assertEqual(interface["capabilities"], ["Interactive", "Read", "Write"])
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(interface["defaultPrompt"])
        self.assertTrue(all(prompt.strip() for prompt in interface["defaultPrompt"]))
        self.assertTrue(all(len(prompt) <= 128 for prompt in interface["defaultPrompt"]))

    def test_marketplace_points_to_the_repository_plugin(self) -> None:
        marketplace = load_json(".claude-plugin/marketplace.json")
        self.assertEqual(marketplace["name"], "threadroot")
        self.assertEqual(len(marketplace["plugins"]), 1)
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "threadroot")
        self.assertEqual(plugin["version"], "0.1.0")
        self.assertEqual(plugin["source"], "./")
        claude = load_json(".claude-plugin/plugin.json")
        common_keys = {
            "name",
            "version",
            "description",
            "author",
            "license",
            "keywords",
        }
        self.assertEqual(set(plugin), common_keys | {"source"})
        self.assertEqual({key: plugin[key] for key in common_keys}, claude)

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
