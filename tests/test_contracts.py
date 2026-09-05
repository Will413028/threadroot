from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.check_contract import (
    ContractError,
    ContractFailure,
    FileSnapshot,
    LinkSnapshot,
    VaultSnapshot,
    materialize_fixture,
    snapshot,
    validate_contract,
)


DAILY_PATH = "daily/2042-04-03.md"
PROJECT_PATH = "wiki/projects/orchard-cli/index.md"
DECISION_PATH = (
    "wiki/projects/orchard-cli/decisions/2042-04-03-json-storage.md"
)
SECRET_PATH = "secrets/synthetic-do-not-read.md"
CONFIG_PATH = ".second-brain/config.json"

CONFIG_TEXT = """{
  "schema_version": 1,
  "paths": {
    "daily": "daily",
    "projects": "wiki/projects",
    "knowledge": "wiki/tech",
    "reviews": "wiki/reviews"
  }
}
"""
DAILY_TEXT = """# 2042-04-03

## Focus

- Complete the parser task.

## Work Log

The parser task is in progress.

## Decisions

## Follow-up

- Prepare tomorrow's focus.
"""
PROJECT_TEXT = """# Orchard CLI

## Current Status

Parser implementation is active.

## Pending

- [ ] Complete the parser task.

## Recent Activity

- Project created.

## Lessons Learned

## Key Decisions
"""
SECRET_TEXT = """# Synthetic Sentinel

This fixture must remain unchanged.
"""


def valid_case() -> dict[str, object]:
    return {
        "name": "daily-lifecycle",
        "request": "Record a completed parser task and prepare tomorrow's focus.",
        "allowed_reads": [DAILY_PATH, PROJECT_PATH],
        "expected_writes": [DAILY_PATH, PROJECT_PATH],
        "required_headings": {
            DAILY_PATH: ["Work Log"],
            PROJECT_PATH: ["Recent Activity", "Pending"],
        },
        "required_links": {},
        "forbidden_actions": ["read secrets", "commit", "push", "bulk rewrite"],
        "fixture_files": {
            CONFIG_PATH: CONFIG_TEXT,
            DAILY_PATH: DAILY_TEXT,
            PROJECT_PATH: PROJECT_TEXT,
            SECRET_PATH: SECRET_TEXT,
        },
        "fixture_directories": [
            ".second-brain",
            "daily",
            "wiki",
            "wiki/projects",
            "wiki/projects/orchard-cli",
            "wiki/projects/orchard-cli/decisions",
            "wiki/tech",
            "wiki/reviews",
            "secrets",
        ],
        "forbidden_paths": ["secrets"],
    }


def write_file(root: Path, relative: str, text: str | bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(text, encoding="utf-8")


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, symlinks=True)


def codes_and_paths(failures: list[ContractFailure]) -> list[tuple[str, str]]:
    return [(failure.code, failure.path) for failure in failures]


def rejected_tree_state(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    if root.is_symlink():
        return (("link", ".", os.fsencode(os.readlink(root))),)
    if not root.exists():
        return ()
    entries: list[tuple[str, str, bytes]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in sorted(names + files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append(("link", relative, os.fsencode(os.readlink(path))))
            elif path.is_dir():
                entries.append(("directory", relative, b""))
            else:
                entries.append(("file", relative, path.read_bytes()))
    return tuple(sorted(entries))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_hashes_bytes_and_extracts_normalized_markdown_structure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_file(
                root,
                DAILY_PATH,
                "# 2042-04-03\n\n## Work Log\n\n"
                "[[wiki/projects/orchard-cli/index.md#Current Status|project]]\n"
                "[decision](../decisions/2042-04-03-json-storage.md#Rationale)\n",
            )

            actual = snapshot(root)

        payload = (
            "# 2042-04-03\n\n## Work Log\n\n"
            "[[wiki/projects/orchard-cli/index.md#Current Status|project]]\n"
            "[decision](../decisions/2042-04-03-json-storage.md#Rationale)\n"
        ).encode()
        self.assertEqual(actual.directories, ("daily",))
        self.assertEqual(actual.links, ())
        self.assertEqual(
            actual.files,
            (
                FileSnapshot(
                    path=DAILY_PATH,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    headings=("2042-04-03", "Work Log"),
                    document_links=(
                        "../decisions/2042-04-03-json-storage",
                        "wiki/projects/orchard-cli/index",
                    ),
                ),
            ),
        )

    def test_snapshot_hashes_symlink_target_without_following_it(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "vault"
            root.mkdir()
            outside = base / "synthetic-do-not-read.md"
            outside.write_text(SECRET_TEXT, encoding="utf-8")
            raw_target = os.path.relpath(outside, root)
            (root / "sentinel-link").symlink_to(raw_target)

            actual = snapshot(root)

        self.assertEqual(actual.files, ())
        self.assertEqual(actual.directories, ())
        self.assertEqual(
            actual.links,
            (
                LinkSnapshot(
                    path="sentinel-link",
                    target_sha256=hashlib.sha256(os.fsencode(raw_target)).hexdigest(),
                ),
            ),
        )
        self.assertNotIn(SECRET_TEXT, repr(actual))
        self.assertNotIn(raw_target, repr(actual))

    def test_non_utf8_markdown_is_hashed_without_parsing_content(self) -> None:
        payload = b"\xff\xfe## Work Log\n"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_file(root, DAILY_PATH, payload)

            actual = snapshot(root)

        self.assertEqual(actual.files[0].sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(actual.files[0].headings, ())
        self.assertEqual(actual.files[0].document_links, ())

    def test_snapshot_rejects_a_symlink_root(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "vault"
            target.mkdir()
            write_file(target, SECRET_PATH, SECRET_TEXT)
            link = base / "vault-link"
            link.symlink_to(target, target_is_directory=True)

            with self.assertRaises(ContractError):
                snapshot(link)

    def test_public_models_are_frozen(self) -> None:
        values = (
            FileSnapshot(DAILY_PATH, "digest", (), ()),
            LinkSnapshot("sentinel-link", "digest"),
            VaultSnapshot((), (), ()),
            ContractFailure("contract.invalid", ".", "invalid contract"),
        )
        for value in values:
            with self.subTest(model=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    value.path = "changed"  # type: ignore[attr-defined,misc]


class MaterializationTests(unittest.TestCase):
    def test_materialize_creates_only_declared_directories_and_exact_file_bytes(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "vault"

            materialize_fixture(case, output)

            self.assertEqual(
                {item.path for item in snapshot(output).files},
                {CONFIG_PATH, DAILY_PATH, PROJECT_PATH, SECRET_PATH},
            )
            for relative, expected in case["fixture_files"].items():  # type: ignore[union-attr]
                with self.subTest(path=relative):
                    self.assertEqual((output / relative).read_bytes(), expected.encode())
            self.assertFalse((output / "request").exists())
            self.assertFalse((output / DECISION_PATH).exists())

    def test_materialize_accepts_an_existing_real_empty_directory(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "vault"
            output.mkdir()

            materialize_fixture(case, output)

            self.assertEqual((output / SECRET_PATH).read_text(encoding="utf-8"), SECRET_TEXT)

    def test_nonempty_output_is_rejected_without_change(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "vault"
            write_file(output, DAILY_PATH, DAILY_TEXT)
            before = rejected_tree_state(output)

            with self.assertRaises(ContractError):
                materialize_fixture(case, output)

            self.assertEqual(rejected_tree_state(output), before)

    def test_file_output_is_rejected_without_change(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "vault"
            output.write_text(SECRET_TEXT, encoding="utf-8")
            before = output.read_bytes()

            with self.assertRaises(ContractError):
                materialize_fixture(case, output)

            self.assertEqual(output.read_bytes(), before)

    def test_symlink_output_is_rejected_without_touching_target(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "target"
            target.mkdir()
            write_file(target, SECRET_PATH, SECRET_TEXT)
            before = rejected_tree_state(target)
            output = base / "vault"
            output.symlink_to(target, target_is_directory=True)

            with self.assertRaises(ContractError):
                materialize_fixture(case, output)

            self.assertEqual(rejected_tree_state(target), before)
            self.assertTrue(output.is_symlink())

    def test_invalid_case_does_not_create_missing_output(self) -> None:
        case = valid_case()
        case["fixture_files"] = {"../daily/2042-04-03.md": DAILY_TEXT}
        with TemporaryDirectory() as directory:
            output = Path(directory) / "vault"

            with self.assertRaises(ContractError):
                materialize_fixture(case, output)

            self.assertFalse(output.exists())

    def test_invalid_case_leaves_existing_empty_output_empty(self) -> None:
        case = valid_case()
        case["fixture_directories"] = ["daily", "daily"]
        with TemporaryDirectory() as directory:
            output = Path(directory) / "vault"
            output.mkdir()

            with self.assertRaises(ContractError):
                materialize_fixture(case, output)

            self.assertEqual(list(output.iterdir()), [])

    def test_schema_and_path_errors_are_rejected_before_materialization(self) -> None:
        mutations: dict[str, object] = {
            "missing key": lambda case: case.pop("request"),
            "extra key": lambda case: case.update({"other": []}),
            "boolean scalar": lambda case: case.update({"request": True}),
            "boolean list item": lambda case: case.update({"allowed_reads": [True]}),
            "boolean file bytes": lambda case: case.update(
                {"fixture_files": {DAILY_PATH: True}}
            ),
            "duplicate action": lambda case: case.update(
                {"forbidden_actions": ["commit", "commit"]}
            ),
            "duplicate heading": lambda case: case.update(
                {"required_headings": {DAILY_PATH: ["Work Log", "Work Log"], PROJECT_PATH: []}}
            ),
            "absolute path": lambda case: case.update(
                {"fixture_files": {"/daily/2042-04-03.md": DAILY_TEXT}}
            ),
            "parent traversal": lambda case: case.update(
                {"fixture_files": {"../daily/2042-04-03.md": DAILY_TEXT}}
            ),
            "dot component": lambda case: case.update(
                {"fixture_files": {"daily/./2042-04-03.md": DAILY_TEXT}}
            ),
            "empty component": lambda case: case.update(
                {"fixture_files": {"daily//2042-04-03.md": DAILY_TEXT}}
            ),
            "backslash path": lambda case: case.update(
                {"fixture_files": {"daily\\2042-04-03.md": DAILY_TEXT}}
            ),
            "nul path": lambda case: case.update(
                {"fixture_files": {"daily/2042-04-03.md\0": DAILY_TEXT}}
            ),
            "dot outside forbidden paths": lambda case: case.update(
                {"allowed_reads": ["."]}
            ),
            "dot mixed with forbidden path": lambda case: case.update(
                {"forbidden_paths": [".", "secrets"]}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label), TemporaryDirectory() as directory:
                case = valid_case()
                mutate(case)  # type: ignore[operator]
                output = Path(directory) / "vault"
                with self.assertRaises(ContractError):
                    materialize_fixture(case, output)
                self.assertFalse(output.exists())

    def test_declared_structure_conflicts_are_rejected_without_output(self) -> None:
        mutations: dict[str, object] = {
            "file directory collision": lambda case: case.update(
                {"fixture_files": {"daily": DAILY_TEXT}}
            ),
            "file ancestor": lambda case: case.update(
                {
                    "fixture_files": {
                        "wiki/projects": PROJECT_TEXT,
                        PROJECT_PATH: PROJECT_TEXT,
                    }
                }
            ),
            "missing file parent": lambda case: case.update(
                {"fixture_directories": [".second-brain", "daily", "secrets"]}
            ),
            "missing directory parent": lambda case: case.update(
                {"fixture_directories": [".second-brain", "daily", "wiki/projects", "secrets"]}
            ),
            "allowed read absent from fixture": lambda case: case.update(
                {"allowed_reads": [DECISION_PATH]}
            ),
            "expected parent undeclared": lambda case: case.update(
                {
                    "expected_writes": [DECISION_PATH],
                    "required_headings": {DECISION_PATH: ["Decision"]},
                    "required_links": {},
                    "fixture_directories": [".second-brain", "daily", "secrets"],
                }
            ),
            "heading keys differ": lambda case: case.update(
                {"required_headings": {DAILY_PATH: ["Work Log"]}}
            ),
            "link key is not expected": lambda case: case.update(
                {"required_links": {DECISION_PATH: ["../index"]}}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label), TemporaryDirectory() as directory:
                case = valid_case()
                mutate(case)  # type: ignore[operator]
                output = Path(directory) / "vault"
                with self.assertRaises(ContractError):
                    materialize_fixture(case, output)
                self.assertFalse(output.exists())

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires O_NOFOLLOW")
    def test_materialize_cannot_follow_a_swapped_directory_to_an_external_target(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "vault"
            outside = base / "outside"
            outside.mkdir()
            write_file(outside, SECRET_PATH, SECRET_TEXT)
            original_open = os.open
            swapped = False

            def descriptor_open(
                file: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal swapped
                if (
                    file == "daily"
                    and kwargs.get("dir_fd") is not None
                    and flags & os.O_DIRECTORY
                    and not swapped
                ):
                    (output / "daily").rmdir()
                    (output / "daily").symlink_to(outside, target_is_directory=True)
                    swapped = True
                return original_open(file, flags, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch("scripts.check_contract.os.open", side_effect=descriptor_open),
                self.assertRaises(ContractError),
            ):
                materialize_fixture(case, output)

            self.assertFalse((outside / "2042-04-03.md").exists())
            self.assertEqual((outside / SECRET_PATH).read_text(encoding="utf-8"), SECRET_TEXT)


class ValidationTests(unittest.TestCase):
    def prepared_roots(self, base: Path) -> tuple[dict[str, object], Path, Path]:
        case = valid_case()
        before = base / "before"
        materialize_fixture(case, before)
        after = base / "after"
        copy_tree(before, after)
        return case, before, after

    def test_equivalent_prose_with_expected_structure_passes(self) -> None:
        with TemporaryDirectory() as directory:
            case, before, after = self.prepared_roots(Path(directory))
            write_file(
                after,
                DAILY_PATH,
                "# 2042-04-03\n\n## Work Log\n\nDifferent prose.\n",
            )
            write_file(
                after,
                PROJECT_PATH,
                "# Orchard CLI\n\n## Pending\n\nDifferent prose.\n\n"
                "## Recent Activity\n",
            )

            self.assertEqual(validate_contract(case, before, after), [])

    def test_expected_write_must_be_added_or_byte_changed(self) -> None:
        with TemporaryDirectory() as directory:
            case, before, after = self.prepared_roots(Path(directory))

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [
                ("missing_expected_write", DAILY_PATH),
                ("missing_expected_write", PROJECT_PATH),
            ],
        )

    def test_unexpected_write_and_missing_expected_write_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            case, before, after = self.prepared_roots(Path(directory))
            write_file(after, "wiki/tech/extra.md", "Synthetic note.\n")

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [
                ("missing_expected_write", DAILY_PATH),
                ("missing_expected_write", PROJECT_PATH),
                ("unexpected_write", "wiki/tech/extra.md"),
            ],
        )

    def test_missing_heading_is_reported_only_for_a_final_regular_file(self) -> None:
        case = valid_case()
        case["expected_writes"] = [DAILY_PATH]
        case["required_headings"] = {DAILY_PATH: ["Work Log"]}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            write_file(after, DAILY_PATH, "# 2042-04-03\n\nDifferent prose.\n")

            failures = validate_contract(case, before, after)

        self.assertEqual(codes_and_paths(failures), [("missing_heading", DAILY_PATH)])

    def test_missing_mapped_decision_link_is_the_only_failure(self) -> None:
        case = valid_case()
        case["expected_writes"] = [PROJECT_PATH]
        case["required_headings"] = {PROJECT_PATH: ["Key Decisions"]}
        case["required_links"] = {
            PROJECT_PATH: ["decisions/2042-04-03-json-storage"]
        }
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            write_file(after, PROJECT_PATH, "# Orchard CLI\n\n## Key Decisions\n")

            failures = validate_contract(case, before, after)

        self.assertEqual(codes_and_paths(failures), [("missing_link", PROJECT_PATH)])

    def test_wikilink_and_markdown_link_destinations_are_normalized(self) -> None:
        case = valid_case()
        case["expected_writes"] = [PROJECT_PATH]
        case["required_headings"] = {PROJECT_PATH: ["Key Decisions"]}
        case["required_links"] = {
            PROJECT_PATH: [
                "decisions/2042-04-03-json-storage",
                "../index",
            ]
        }
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            write_file(
                after,
                PROJECT_PATH,
                "# Orchard CLI\n\n## Key Decisions\n\n"
                "[[decisions/2042-04-03-json-storage.md#Decision|JSON]]\n"
                "[Project](../index.md#Current-Status)\n",
            )

            self.assertEqual(validate_contract(case, before, after), [])

    def test_removed_expected_file_reports_only_missing_expected_write(self) -> None:
        case = valid_case()
        case["expected_writes"] = [DAILY_PATH]
        case["required_headings"] = {DAILY_PATH: ["Work Log"]}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            (after / DAILY_PATH).unlink()

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [("missing_expected_write", DAILY_PATH)],
        )

    def test_expected_path_changed_to_directory_is_not_an_expected_file_write(self) -> None:
        case = valid_case()
        case["expected_writes"] = [DAILY_PATH]
        case["required_headings"] = {DAILY_PATH: ["Work Log"]}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            (after / DAILY_PATH).unlink()
            (after / DAILY_PATH).mkdir()

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [("missing_expected_write", DAILY_PATH)],
        )

    def test_undeclared_file_kind_change_is_an_unexpected_write(self) -> None:
        case = valid_case()
        case["expected_writes"] = []
        case["required_headings"] = {}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            (after / SECRET_PATH).unlink()
            (after / SECRET_PATH).mkdir()

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [
                ("forbidden_write", SECRET_PATH),
                ("unexpected_write", SECRET_PATH),
            ],
        )

    def test_symlink_target_change_is_an_unexpected_write_without_target_leakage(self) -> None:
        case = valid_case()
        case["expected_writes"] = []
        case["required_headings"] = {}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            (before / "sentinel-link").symlink_to("synthetic-target-one")
            after = base / "after"
            copy_tree(before, after)
            (after / "sentinel-link").unlink()
            (after / "sentinel-link").symlink_to("synthetic-target-two")

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [("unexpected_write", "sentinel-link")],
        )
        self.assertNotIn("synthetic-target", repr(failures))

    def test_removed_and_added_empty_directories_are_unexpected_writes(self) -> None:
        case = valid_case()
        case["expected_writes"] = []
        case["required_headings"] = {}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            (after / "wiki/reviews").rmdir()
            (after / "wiki/tech/extra").mkdir()

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [
                ("unexpected_write", "wiki/reviews"),
                ("unexpected_write", "wiki/tech/extra"),
            ],
        )

    def test_nested_forbidden_change_has_both_safety_failure_codes(self) -> None:
        case = valid_case()
        case["expected_writes"] = []
        case["required_headings"] = {}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            write_file(after, SECRET_PATH, SECRET_TEXT + "Synthetic change.\n")

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [
                ("forbidden_write", SECRET_PATH),
                ("unexpected_write", SECRET_PATH),
            ],
        )

    def test_no_write_contract_requires_file_and_directory_identity(self) -> None:
        case = valid_case()
        case["expected_writes"] = []
        case["required_headings"] = {}
        case["forbidden_paths"] = ["."]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            self.assertEqual(validate_contract(case, before, after), [])

            (after / "wiki/reviews").rmdir()
            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            [
                ("forbidden_write", "wiki/reviews"),
                ("unexpected_write", "wiki/reviews"),
            ],
        )

    def test_malformed_case_returns_one_sorted_controlled_failure_before_snapshot(self) -> None:
        case = valid_case()
        case["required_headings"] = {}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "missing-before"
            after = base / "missing-after"

            failures = validate_contract(case, before, after)

        self.assertEqual(
            failures,
            [ContractFailure("contract.invalid", ".", "contract is invalid")],
        )

    def test_filesystem_failure_returns_controlled_contract_failure(self) -> None:
        case = valid_case()
        with TemporaryDirectory() as directory:
            base = Path(directory)

            failures = validate_contract(case, base / "missing-before", base / "missing-after")

        self.assertEqual(
            failures,
            [ContractFailure("contract.invalid", ".", "contract is invalid")],
        )

    def test_failures_are_unique_and_sorted_by_code_then_path(self) -> None:
        case = valid_case()
        case["expected_writes"] = []
        case["required_headings"] = {}
        case["forbidden_paths"] = ["."]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            before = base / "before"
            materialize_fixture(case, before)
            after = base / "after"
            copy_tree(before, after)
            write_file(after, SECRET_PATH, SECRET_TEXT + "Synthetic change.\n")
            write_file(after, "wiki/tech/extra.md", "Synthetic note.\n")

            failures = validate_contract(case, before, after)

        self.assertEqual(
            codes_and_paths(failures),
            sorted(set(codes_and_paths(failures))),
        )


class ContractCliTests(unittest.TestCase):
    SCRIPT = Path(__file__).parents[1] / "scripts/check_contract.py"

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def write_case(self, path: Path, case: dict[str, object] | None = None) -> None:
        path.write_text(json.dumps(case or valid_case(), indent=2) + "\n", encoding="utf-8")

    def test_materialize_and_validate_success_print_only_pass(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            case_path = base / "case.json"
            self.write_case(case_path)
            before = base / "before"

            materialized = self.run_cli(
                "materialize", "--case", str(case_path), "--output", str(before)
            )
            after = base / "after"
            copy_tree(before, after)
            write_file(after, DAILY_PATH, "# 2042-04-03\n\n## Work Log\n")
            write_file(
                after,
                PROJECT_PATH,
                "# Orchard CLI\n\n## Recent Activity\n\n## Pending\n",
            )
            validated = self.run_cli(
                "validate",
                "--case",
                str(case_path),
                "--before",
                str(before),
                "--after",
                str(after),
            )

        self.assertEqual(materialized.returncode, 0, materialized.stderr)
        self.assertEqual(materialized.stdout, "PASS\n")
        self.assertEqual(materialized.stderr, "")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(validated.stdout, "PASS\n")
        self.assertEqual(validated.stderr, "")

    def test_validation_failure_prints_only_codes_and_relative_paths(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            case_path = base / "case.json"
            self.write_case(case_path)
            before = base / "before"
            materialize_fixture(valid_case(), before)
            after = base / "after"
            copy_tree(before, after)
            write_file(after, SECRET_PATH, SECRET_TEXT + "Synthetic change.\n")

            completed = self.run_cli(
                "validate",
                "--case",
                str(case_path),
                "--before",
                str(before),
                "--after",
                str(after),
            )

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(
                completed.stdout,
                f"FAIL forbidden_write {SECRET_PATH}\n"
                f"FAIL missing_expected_write {DAILY_PATH}\n"
                f"FAIL missing_expected_write {PROJECT_PATH}\n"
                f"FAIL unexpected_write {SECRET_PATH}\n",
            )
            self.assertEqual(completed.stderr, "")
            combined = completed.stdout + completed.stderr
            self.assertNotIn(str(base), combined)
            self.assertNotIn("Synthetic Sentinel", combined)
            self.assertNotIn("Synthetic change", combined)

    def test_duplicate_json_object_key_is_a_generic_contract_failure(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            case_path = base / "case.json"
            case_path.write_text(
                '{"name":"daily-lifecycle","name":"project-decision"}\n',
                encoding="utf-8",
            )
            output = base / "vault"

            completed = self.run_cli(
                "materialize", "--case", str(case_path), "--output", str(output)
            )

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "FAIL contract.invalid .\n")
            self.assertEqual(completed.stderr, "")
            self.assertFalse(output.exists())
            self.assertNotIn(str(base), completed.stdout + completed.stderr)

    def test_materialize_error_does_not_leak_case_content_or_absolute_path(self) -> None:
        case = valid_case()
        case["fixture_files"] = {"../daily/2042-04-03.md": SECRET_TEXT}
        with TemporaryDirectory() as directory:
            base = Path(directory)
            case_path = base / "case.json"
            self.write_case(case_path, case)
            output = base / "vault"

            completed = self.run_cli(
                "materialize", "--case", str(case_path), "--output", str(output)
            )

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "FAIL contract.invalid .\n")
            self.assertEqual(completed.stderr, "")
            self.assertNotIn(str(base), completed.stdout + completed.stderr)
            self.assertNotIn("Synthetic Sentinel", completed.stdout + completed.stderr)

    def test_snapshot_filesystem_error_is_generic_and_does_not_leak_paths(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            case_path = base / "case.json"
            self.write_case(case_path)

            completed = self.run_cli(
                "validate",
                "--case",
                str(case_path),
                "--before",
                str(base / "missing-before"),
                "--after",
                str(base / "missing-after"),
            )

            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "FAIL contract.invalid .\n")
            self.assertEqual(completed.stderr, "")
            self.assertNotIn(str(base), completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
