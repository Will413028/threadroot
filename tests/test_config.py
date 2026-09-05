import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from threadroot.config import DEFAULT_CONFIG, config_text, load_config
from threadroot.results import ExitCode, ThreadrootError


class ConfigTests(unittest.TestCase):
    def write_marker(self, root: Path, document: str) -> Path:
        marker = root / ".second-brain" / "config.json"
        marker.parent.mkdir()
        marker.write_text(document, encoding="utf-8")
        return marker

    def test_default_config_round_trips_and_matches_template(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_marker(root, config_text())
            template = Path("templates/vault/config.json")
            self.assertEqual(load_config(root), DEFAULT_CONFIG)
            self.assertEqual(config_text(), template.read_text(encoding="utf-8"))

    def test_unknown_version_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            document = json.loads(config_text())
            document["schema_version"] = 2
            self.write_marker(root, json.dumps(document))
            with self.assertRaises(ThreadrootError) as raised:
                load_config(root)
            self.assertEqual(raised.exception.exit_code, ExitCode.CONFIG)
            self.assertEqual(raised.exception.code, "config.unsupported_version")

    def test_malformed_duplicate_or_wrong_schema_is_invalid(self) -> None:
        documents = (
            "{",
            '{"schema_version": 1, "schema_version": 1, "paths": {}}',
            '{"schema_version": true, "paths": {}}',
            '{"schema_version": 1, "paths": {}, "extra": true}',
            '{"schema_version": 1, "paths": {"daily": "daily", "projects": "wiki/projects", "knowledge": "wiki/tech", "reviews": "wiki/reviews", "daily": "other"}}',
            '{"schema_version": 1, "paths": {"daily": "", "projects": "wiki/projects", "knowledge": "wiki/tech", "reviews": "wiki/reviews"}}',
        )
        for document in documents:
            with self.subTest(document=document), TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_marker(root, document)
                with self.assertRaises(ThreadrootError) as raised:
                    load_config(root)
                self.assertEqual(raised.exception.exit_code, ExitCode.CONFIG)
                self.assertEqual(raised.exception.code, "config.invalid")

    def test_absolute_configured_path_is_unsafe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            document = json.loads(config_text())
            document["paths"]["daily"] = "/tmp/outside"
            self.write_marker(root, json.dumps(document))
            with self.assertRaises(ThreadrootError) as raised:
                load_config(root)
            self.assertEqual(raised.exception.exit_code, ExitCode.UNSAFE_PATH)
    def test_configured_directory_symlink_that_escapes_is_unsafe(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "vault"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (root / "daily").symlink_to(outside, target_is_directory=True)
            self.write_marker(root, config_text())
            with self.assertRaises(ThreadrootError) as raised:
                load_config(root)
            self.assertEqual(raised.exception.exit_code, ExitCode.UNSAFE_PATH)

    def test_marker_symlink_that_escapes_is_rejected_without_reading_target(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "vault"
            root.mkdir()
            outside = base / "outside.json"
            outside.write_text("{", encoding="utf-8")
            marker = root / ".second-brain" / "config.json"
            marker.parent.mkdir()
            marker.symlink_to(outside)
            with self.assertRaises(ThreadrootError) as raised:
                load_config(root)
            self.assertEqual(raised.exception.exit_code, ExitCode.UNSAFE_PATH)
