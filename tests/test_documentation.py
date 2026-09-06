from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from scripts.build_release import build_archive


RELEASE_NOTES = Path("docs/releases/v0.1.0.md")
REPRODUCIBLE_RELEASE_PLAN = Path(
    "docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md"
)
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
EXPECTED_TEST_ACTIONS = [
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
]
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
EXPECTED_RELEASE_COMMAND = '''set -euo pipefail
attempt_root="$(mktemp -d)"
attempt_root="$(cd "$attempt_root" && pwd -P)"
candidate_root="$attempt_root/candidate"
authority_record="$attempt_root/authority.json"
success_receipt="$attempt_root/success.json"
release_commit="$(git rev-parse HEAD)"
python3 -B -m scripts.build_verified_release --commit "$release_commit" --output "$candidate_root" --authority-record "$authority_record"
python3 -B -m scripts.release_candidate record-success --authority-record "$authority_record" --expected-commit "$release_commit" --success-receipt "$success_receipt"
python3 -B -m scripts.release_candidate verify-success --authority-record "$authority_record" --expected-commit "$release_commit" --success-receipt "$success_receipt"
'''
EXPECTED_CI_WORKFLOW = """name: ci

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.12", "3.13", "3.14"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install --upgrade pip build
      - run: python -m unittest discover -s tests -v
        env:
          PYTHONPATH: src:.
      - run: python -m build
      - run: python -m pip install --force-reinstall dist/threadroot-0.1.0-py3-none-any.whl
      - run: threadroot --version
      - run: python scripts/build_release.py --output dist
      - run: python scripts/check_public.py .
      - run: python scripts/check_public.py dist

  release-artifacts:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - run: |
""" + "".join("          " + line + "\n" for line in EXPECTED_RELEASE_COMMAND.splitlines())


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


def _yaml_mapping_body(document: str, key: str, indent: int) -> str:
    spaces = " " * indent
    match = re.search(
        rf"^{spaces}{re.escape(key)}:\s*$\n"
        rf"(?P<body>.*?)(?=^{spaces}[A-Za-z0-9_-]+:\s*(?:#.*)?$|\Z)",
        document,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing YAML mapping: {key}")
    return match.group("body")


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


def _release_plan_task(plan: str, task_number: int) -> str:
    match = re.search(
        rf"^### Task {task_number}:[^\n]*$\n"
        rf"(?P<body>.*?)(?=^### Task {task_number + 1}:|^## Completion criteria|\Z)",
        plan,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing Task {task_number}")
    return match.group("body")


def _release_plan_step(plan: str, task_number: int, step_number: int) -> str:
    task = _release_plan_task(plan, task_number)
    match = re.search(
        rf"^- \[ \] \*\*Step {step_number}:[^\n]*\*\*$\n"
        r"(?P<body>.*?)(?=^- \[ \] \*\*Step \d+:|\Z)",
        task,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing Task {task_number} Step {step_number}")
    return match.group("body")


def _release_plan_bash_block(
    plan: str,
    task_number: int,
    step_number: int,
    block_number: int = 0,
) -> str:
    blocks = re.findall(
        r"^```bash\s*$\n(.*?)^```\s*$",
        _release_plan_step(plan, task_number, step_number),
        re.MULTILINE | re.DOTALL,
    )
    try:
        return blocks[block_number]
    except IndexError as error:
        raise AssertionError(
            f"missing Task {task_number} Step {step_number} Bash block "
            f"{block_number + 1}"
        ) from error


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _fake_release_commands(directory: Path) -> tuple[Path, Path]:
    fake_bin = directory / "fake-bin"
    fake_bin.mkdir()
    call_log = directory / "calls.log"
    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env python3
import os
from pathlib import Path
import shlex
import sys

args = sys.argv[1:]
with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write("git " + shlex.join(args) + "\\n")

if args[:2] == ["rev-parse", "HEAD"]:
    print(os.environ.get("FAKE_GIT_HEAD", "1" * 40))
elif args[:2] == ["branch", "--show-current"]:
    print(os.environ.get("FAKE_GIT_BRANCH", "release/v0.1.0-readiness"))
elif args and args[0] == "status":
    print(os.environ.get("FAKE_GIT_STATUS", ""))
    raise SystemExit(int(os.environ.get("FAKE_GIT_STATUS_EXIT", "0")))
elif args[:2] == ["rev-parse", "refs/remotes/origin/main"]:
    print(os.environ.get("FAKE_REMOTE_MAIN", os.environ.get("FAKE_RELEASE_COMMIT", "3" * 40)))
elif args[:2] == ["rev-parse", "refs/tags/v0.1.0^{}"]:
    print(os.environ.get("FAKE_TAG_COMMIT", os.environ.get("FAKE_RELEASE_COMMIT", "3" * 40)))
elif args and args[0] == "rev-parse" and ":docs/releases/v0.1.0.md" in args[-1]:
    print(os.environ.get("FAKE_NOTES_BLOB", "4" * 40))
elif args and args[0] == "hash-object":
    print(os.environ.get("FAKE_NOTES_BLOB", "4" * 40))
elif args[:3] == ["config", "--local", "--get"]:
    if args[-1] == "user.name":
        print("Will")
    elif args[-1] == "user.email":
        print("will413028@gmail.com")
    else:
        raise SystemExit(96)
elif args[:2] == ["remote", "get-url"]:
    print("https://github.com/Will413028/threadroot.git")
elif args and args[0] == "show-ref":
    raise SystemExit(int(os.environ.get("FAKE_SHOW_REF_EXIT", "1")))
elif args and args[0] == "ls-remote":
    if os.environ.get("FAKE_LS_REMOTE_EXIT"):
        raise SystemExit(int(os.environ["FAKE_LS_REMOTE_EXIT"]))
    if os.environ.get("FAKE_LS_REMOTE_EMPTY") == "1" and not Path(os.environ["THREADROOT_TEST_CALL_LOG"] + ".tag-pushed").exists():
        raise SystemExit(0)
    commit = os.environ.get("FAKE_TAG_COMMIT", os.environ.get("FAKE_RELEASE_COMMIT", "3" * 40))
    print(f"{commit}\\trefs/tags/v0.1.0^{{}}")
elif args and args[0] in {"fetch", "merge-base"}:
    raise SystemExit(int(os.environ.get("FAKE_GIT_READ_EXIT", "0")))
elif args and args[0] in {"tag", "push"}:
    if args[0] == "push" and any("refs/tags/" in arg for arg in args):
        Path(os.environ["THREADROOT_TEST_CALL_LOG"] + ".tag-pushed").touch()
else:
    print(f"unsupported fake git command: {shlex.join(args)}", file=sys.stderr)
    raise SystemExit(97)
""",
    )
    _write_executable(
        fake_bin / "gh",
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

args = sys.argv[1:]
with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write("gh " + shlex.join(args) + "\\n")

if args[:2] == ["api", "user"]:
    print("Will413028")
elif args[:2] == ["auth", "switch"]:
    pass
elif args[:2] == ["pr", "view"]:
    print(os.environ.get("FAKE_PR_HEAD", os.environ.get("FAKE_GIT_HEAD", "1" * 40)))
elif args[:2] == ["pr", "checks"]:
    if "--json" in args:
        checks = [
            {"name": "release-artifacts", "bucket": "pass", "state": "SUCCESS", "link": "https://example.invalid/release"},
            *[
                {"name": f"test ({number})", "bucket": "pass", "state": "SUCCESS", "link": f"https://example.invalid/{number}"}
                for number in range(1, 9)
            ],
        ]
        print(json.dumps(checks))
elif args[:2] == ["pr", "diff"]:
    print("synthetic diff")
elif args[:2] == ["pr", "list"]:
    print(os.environ.get("FAKE_EXISTING_PR", ""))
elif args[:2] == ["pr", "create"]:
    print("https://example.invalid/pr/1")
elif args[:2] == ["pr", "edit"]:
    pass
elif args[:2] == ["pr", "merge"]:
    print("merged")
elif args[:2] == ["release", "create"]:
    print("https://example.invalid/draft")
elif args[:2] == ["release", "view"]:
    release_json = os.environ.get("FAKE_RELEASE_JSON")
    print(Path(release_json).read_text(encoding="utf-8") if release_json else "{}")
elif args[:2] == ["release", "download"]:
    if os.environ.get("FAKE_RELEASE_DOWNLOAD_EXIT"):
        print("synthetic release download failure", file=sys.stderr)
        raise SystemExit(int(os.environ["FAKE_RELEASE_DOWNLOAD_EXIT"]))
    pattern = args[args.index("--pattern") + 1]
    destination = Path(args[args.index("--dir") + 1])
    source = Path(os.environ["FAKE_DRAFT_ASSET_ROOT"]) / pattern
    shutil.copyfile(source, destination / pattern)
elif args[:2] == ["release", "edit"]:
    print("published")
else:
    print(f"unsupported fake gh command: {shlex.join(args)}", file=sys.stderr)
    raise SystemExit(98)
""",
    )
    return fake_bin, call_log


def _run_release_plan_block(
    block: str,
    directory: Path,
    fake_bin: Path,
    call_log: Path,
    repository: Path | None = None,
    **environment: str,
) -> subprocess.CompletedProcess[str]:
    sandboxed = block.replace(
        "/private/tmp/threadroot-v010-",
        f"{directory.as_posix()}/threadroot-v010-",
    )
    run_environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("threadroot_")
    }
    run_environment.update(environment)
    run_environment["PATH"] = f"{fake_bin}{os.pathsep}{run_environment['PATH']}"
    run_environment["THREADROOT_TEST_CALL_LOG"] = str(call_log)
    run_environment["PYTHONPATH"] = str(Path.cwd().resolve()) + os.pathsep + str(Path.cwd().resolve() / "src")
    return subprocess.run(
        ["/bin/bash", "-c", sandboxed],
        cwd=repository or Path.cwd(),
        env=run_environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_sha256sums(destination: Path, selected: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(
            f"{hashlib.sha256((selected / name).read_bytes()).hexdigest()}  {name}\n"
            for name in sorted(EXPECTED_RELEASE_ASSETS)
        ),
        encoding="utf-8",
    )


def _write_release_contract(destination: Path, selected: Path) -> Path:
    release = {
        "assets": [
            {"name": name, "size": (selected / name).stat().st_size}
            for name in sorted(EXPECTED_RELEASE_ASSETS)
        ],
        "body": "synthetic release body",
        "isDraft": True,
        "isPrerelease": False,
        "name": "Threadroot v0.1.0",
        "tagName": "v0.1.0",
        "url": "https://example.invalid/draft",
    }
    release_json = destination / "release.json"
    release_json.write_text(json.dumps(release), encoding="utf-8")
    contract = {
        "assets": release["assets"],
        "body": release["body"],
        "isDraft": release["isDraft"],
        "isPrerelease": release["isPrerelease"],
        "name": release["name"],
        "tagName": release["tagName"],
        "url": release["url"],
    }
    (destination / "draft-after-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return release_json


def _write_public_release(destination: Path, selected: Path) -> None:
    release = {
        "assets": [
            {
                "browser_download_url": (
                    "https://github.com/Will413028/threadroot/releases/download/"
                    f"v0.1.0/{name}"
                ),
                "name": name,
                "size": (selected / name).stat().st_size,
            }
            for name in sorted(EXPECTED_RELEASE_ASSETS)
        ],
        "body": RELEASE_NOTES.read_text(encoding="utf-8"),
        "draft": False,
        "name": "Threadroot v0.1.0",
        "prerelease": False,
        "tag_name": "v0.1.0",
    }
    destination.write_text(json.dumps(release), encoding="utf-8")


def _write_task_10_host_fake(fake_bin: Path, command: str) -> None:
    _write_executable(
        fake_bin / command,
        f"""#!/bin/bash
set -euo pipefail
if test "$*" = "--version"; then
  printf '%s 1.0.0\\n' {command!r}
elif test "$*" = "plugin list --json"; then
  printf '%s\\n' '{{"plugins":["threadroot@threadroot"]}}'
fi
""",
    )


class DocumentationTests(unittest.TestCase):
    def _assert_canonical_success_arm(self, command: str) -> None:
        for failure, expected in (("build", ["build"]),
                                  ("record-success", ["build", "record-success"]),
                                  ("verify-success", ["build", "record-success", "verify-success"]),
                                  ("", ["build", "record-success", "verify-success"])):
            with self.subTest(failure=failure), TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                fake_bin, call_log = _fake_release_commands(root)
                (root / "alias").symlink_to(root, target_is_directory=True)
                _write_executable(fake_bin / "mktemp", f"#!{sys.executable}\n" + '''
import os
from pathlib import Path
import sys
assert sys.argv[1:] == ["-d"]
root = Path(os.environ["THREADROOT_TEST_TEMP_ROOT"])
(root / "attempt").mkdir()
print(root / "alias/attempt")
''')
                # Absolute interpreter avoids recursive PATH lookup by the fake git.
                _write_executable(fake_bin / "git", f"#!{sys.executable}\nprint('{'1' * 40}')\n")
                _write_executable(fake_bin / "python3", f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import sys
args = sys.argv[1:]
assert args[:2] == ["-B", "-m"], args
assert args[2] in {"scripts.build_verified_release", "scripts.release_candidate"}
phase = "build" if args[2] == "scripts.build_verified_release" else args[3]
options = args[3:] if phase == "build" else args[4:]
values = dict(zip(options[::2], options[1::2]))
expected = {"--commit", "--output", "--authority-record"} if phase == "build" else {
    "--authority-record", "--expected-commit", "--success-receipt"}
assert set(values) == expected and len(options) == len(expected) * 2, args
assert values.get("--commit", values.get("--expected-commit")) == "1" * 40
record = Path(values["--authority-record"])
assert record.is_absolute() and record.parent == record.parent.resolve(strict=True)
candidate = record.parent / "candidate"
receipt = record.parent / "success.json"
if phase == "build":
    assert Path(values["--output"]) == candidate
    assert not any(path.exists() for path in (candidate, record, receipt))
    candidate.mkdir()
    record.write_text("synthetic diagnostic authority")
else:
    assert Path(values["--success-receipt"]) == receipt
    assert candidate.is_dir() and record.is_file()
    if phase == "record-success":
        assert not receipt.exists()
    else:
        assert receipt.is_file()
with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a") as stream:
    stream.write(phase + "\\n")
if os.environ["FAIL_PHASE"] == phase:
    raise SystemExit(23)
if phase == "record-success":
    receipt.write_text("synthetic receipt")
''')
                result = _run_release_plan_block(command, root, fake_bin, call_log,
                    FAIL_PHASE=failure, THREADROOT_TEST_TEMP_ROOT=str(root))
                self.assertEqual(result.returncode, 23 if failure else 0, result.stderr)
                self.assertEqual(call_log.read_text().splitlines(), expected)
                self.assertEqual((root / "attempt/success.json").exists(),
                                 failure in ("", "verify-success"))

    def test_ci_canonical_build_records_and_verifies_success(self):
        workflow = Path(".github/workflows/ci.yml").read_text()
        release = _yaml_mapping_body(_yaml_mapping_body(workflow, "jobs", 0), "release-artifacts", 2)
        command = textwrap.dedent(release.split("      - run: |\n", 1)[1])
        self.assertEqual(command, EXPECTED_RELEASE_COMMAND)
        self._assert_canonical_success_arm(command)

    def test_testing_guide_canonical_build_records_and_verifies_success(self):
        section = _section(Path("docs/testing.md").read_text(), "Canonical release build")
        command = re.findall(r"^```bash\s*$\n(.*?)^```\s*$", section, re.MULTILINE | re.DOTALL)[0]
        self.assertEqual(command, EXPECTED_RELEASE_COMMAND)
        self._assert_canonical_success_arm(command)

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
                r"\bthreadroot-[A-Za-z0-9_.+-]+\.(?:whl|tar\.gz|zip)\b",
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

    def test_sdist_configuration_includes_public_policy_documents(self) -> None:
        metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("hatch", metadata.get("tool", {}))
        included_roots = metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]

        self.assertTrue({"CONTRIBUTING.md", "SECURITY.md"} <= set(included_roots))

    def test_ci_has_exact_matrix_pins_and_validation_commands(self) -> None:
        workflow_path = Path(".github/workflows/ci.yml")
        self.assertTrue(workflow_path.is_file(), "missing CI workflow")
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertEqual(workflow, EXPECTED_CI_WORKFLOW)
        jobs = _yaml_mapping_body(workflow, "jobs", 0)
        self.assertEqual(
            re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs, re.MULTILINE),
            ["test", "release-artifacts"],
        )
        test_job = _yaml_mapping_body(jobs, "test", 2)
        release_job = _yaml_mapping_body(jobs, "release-artifacts", 2)
        test_actions = re.findall(
            r"^\s+- uses:\s*(\S+)", test_job, re.MULTILINE
        )
        release_actions = re.findall(
            r"^\s+- uses:\s*(\S+)", release_job, re.MULTILINE
        )

        self.assertEqual(test_actions, EXPECTED_TEST_ACTIONS)
        for action in test_actions:
            with self.subTest(action=action):
                self.assertRegex(action, r"@[0-9a-f]{40}$")

        matrix_os = _inline_matrix_values(test_job, "os")
        matrix_python = _inline_matrix_values(test_job, "python")
        self.assertEqual(matrix_os, ["ubuntu-latest", "macos-latest"])
        self.assertEqual(matrix_python, ["3.11", "3.12", "3.13", "3.14"])
        self.assertEqual(len(matrix_os) * len(matrix_python), 8)
        self.assertRegex(test_job, r"(?m)^      fail-fast:\s*false\s*$")
        self.assertRegex(
            test_job,
            r"(?m)^    runs-on:\s*\$\{\{\s*matrix\.os\s*\}\}\s*$",
        )
        self.assertRegex(
            test_job,
            r"(?m)^          python-version:\s*\$\{\{\s*matrix\.python\s*\}\}\s*$",
        )
        self.assertEqual(
            re.findall(r"^\s+- run:\s*(.+)$", test_job, re.MULTILINE),
            EXPECTED_CI_COMMANDS,
        )
        self.assertRegex(test_job, r"(?m)^\s+PYTHONPATH:\s*src:\.\s*$")

        self.assertEqual(
            release_actions,
            ["actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"],
        )
        self.assertRegex(release_actions[0], r"@[0-9a-f]{40}$")
        self.assertEqual(
            re.findall(r"^\s+- run:\s*(.+)$", release_job, re.MULTILINE),
            ["|"],
        )
        self.assertEqual(
            re.findall(
                r"^    (runs-on|timeout-minutes):\s*(.+?)\s*$",
                release_job,
                re.MULTILINE,
            ),
            [("runs-on", "ubuntu-24.04"), ("timeout-minutes", "30")],
        )
        self.assertEqual(
            re.findall(r"^    ([A-Za-z0-9_-]+):", release_job, re.MULTILINE),
            ["runs-on", "timeout-minutes", "steps"],
        )
        self.assertEqual(
            re.findall(r"^      - ([A-Za-z0-9_-]+):", release_job, re.MULTILINE),
            ["uses", "run"],
        )
        self.assertEqual(
            re.findall(r"^        ([A-Za-z0-9_-]+):", release_job, re.MULTILINE),
            [],
        )
        self.assertNotRegex(release_job, r"(?m)^    permissions:")

        permissions = _yaml_mapping_body(workflow, "permissions", 0)
        self.assertEqual(
            re.findall(
                r"^  ([A-Za-z0-9_-]+):\s*(\S+)\s*$", permissions, re.MULTILINE
            ),
            [("contents", "read")],
        )

    def test_ci_contract_rejects_hidden_yaml_mutations(self) -> None:
        workflow_path = Path(".github/workflows/ci.yml")
        workflow = workflow_path.read_text(encoding="utf-8")
        canonical_release_step = "      - run: |\n" + "".join(
            "          " + line + "\n" for line in EXPECTED_RELEASE_COMMAND.splitlines())
        canonical_permissions = "permissions:\n  contents: read\n\njobs:\n"
        mutations = {
            "quoted release permissions": workflow.replace(
                "    timeout-minutes: 30\n",
                '    timeout-minutes: 30\n    "permissions": write-all\n',
                1,
            ),
            "quoted upload step": workflow.replace(
                canonical_release_step,
                canonical_release_step
                + '      - "uses": actions/upload-artifact@v4\n',
                1,
            ),
            "quoted multiline run step": workflow.replace(
                canonical_release_step,
                canonical_release_step
                + '      - "run": |\n          echo hidden command\n',
                1,
            ),
            "fully quoted publish job": workflow
            + '  "publish":\n'
            + '    "runs-on": "ubuntu-24.04"\n'
            + '    "steps":\n'
            + '      - "run": "echo publish"\n',
            "duplicate quoted top-level permissions": workflow.replace(
                canonical_permissions,
                canonical_permissions.replace(
                    "\njobs:\n", '\n"permissions": write-all\n\njobs:\n'
                ),
                1,
            ),
        }
        original_read_text = Path.read_text

        for name, mutated_workflow in mutations.items():
            with self.subTest(mutation=name):
                self.assertNotEqual(mutated_workflow, workflow)

                def controlled_read_text(path: Path, *args: object, **kwargs: object) -> str:
                    if path == workflow_path:
                        return mutated_workflow
                    return original_read_text(path, *args, **kwargs)

                with patch.object(Path, "read_text", new=controlled_read_text):
                    with self.assertRaises(AssertionError):
                        self.test_ci_has_exact_matrix_pins_and_validation_commands()

    def test_tasks_7_through_12_bash_blocks_have_locked_counts_and_syntax(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")

        expected_counts = {7: 4, 8: 3, 9: 4, 10: 7, 11: 3, 12: 3}

        for task_number, expected_count in expected_counts.items():
            blocks = re.findall(
                r"^```bash\s*$\n(.*?)^```\s*$",
                _release_plan_task(plan, task_number),
                re.MULTILINE | re.DOTALL,
            )
            self.assertEqual(
                len(blocks),
                expected_count,
                f"Task {task_number} Bash block count changed",
            )
            for block_number, block in enumerate(blocks, start=1):
                with self.subTest(task=task_number, block=block_number):
                    self.assertEqual(block.splitlines()[0], "set -euo pipefail")

                    syntax = subprocess.run(
                        ["/bin/bash", "-n"],
                        input=block,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(
                        syntax.returncode,
                        0,
                        syntax.stdout + syntax.stderr,
                    )


    def test_task_7_local_matrix_command_uses_src_layout(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        task = re.search(
            r"^### Task 7:[^\n]*$\n(?P<body>.*?)(?=^### Task 8:|\Z)",
            plan,
            re.MULTILINE | re.DOTALL,
        )
        if task is None:
            self.fail("missing Task 7")
        step = re.search(
            r"^- \[ \] \*\*Step 1:[^\n]*$\n(?P<body>.*?)(?=^- \[ \] \*\*Step 2:)",
            task.group("body"),
            re.MULTILINE | re.DOTALL,
        )
        if step is None:
            self.fail("missing Task 7 Step 1")

        self.assertEqual(
            re.findall(
                r"^```bash\s*$\n(.*?)^```\s*$",
                step.group("body"),
                re.MULTILINE | re.DOTALL,
            ),
            [
                "set -euo pipefail\n"
                "for threadroot_python in python3.11 python3.12 python3.13 python3.14; do\n"
                '  PYTHONPATH=src:. "$threadroot_python" -m unittest discover '
                "-s tests -v\n"
                '  "$threadroot_python" -m compileall -q src scripts tests\n'
                "done\n"
            ],
        )

    def test_canonical_release_build_is_documented(self) -> None:
        testing = Path("docs/testing.md").read_text(encoding="utf-8")
        section = _section(testing, "Canonical release build")
        expected_commands = EXPECTED_RELEASE_COMMAND.rstrip("\n")

        self.assertEqual(
            re.findall(
                r"^```bash\s*$\n(.*?)^```\s*$",
                section,
                re.MULTILINE | re.DOTALL,
            ),
            [expected_commands + "\n"],
        )
        for statement in (
            "Hatchling is the PEP 517 build backend.",
            "Keep `python -m build` as the ordinary compatibility-inspection command.",
            "The canonical builder's provisioning phase is network-enabled and may pull the digest-pinned image and hash-approved wheels.",
            "The artifact container then runs with exact `--network none`.",
            "The output root must be outside the repository and must be missing or empty.",
            "Failures retain the candidate/evidence directories for inspection.",
            "Docker is not an end-user or runtime requirement.",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, section)
        self.assertNotRegex(testing, r"(?i)setuptools\s+`?>=69`?")

    def test_superseded_release_plan_points_to_reproducible_plan_before_first_task(
        self,
    ) -> None:
        old_plan = Path(
            "docs/superpowers/plans/2026-09-05-threadroot-v0.1.0-release-readiness.md"
        ).read_text(encoding="utf-8")
        first_task = re.search(r"^### Task\b", old_plan, re.MULTILINE)
        self.assertIsNotNone(first_task, "superseded plan has no task heading")
        prefix = old_plan[: first_task.start()]

        self.assertRegex(
            prefix,
            r"\[[^]]+]\(2026-09-05-threadroot-reproducible-release-build\.md\)",
        )
        self.assertIn("Tasks 5-12", prefix)
        self.assertIn("must not be executed", prefix)


class ReleaseAuthorityFlowTests(unittest.TestCase):
    """Execute published shell blocks with real Git and paired authority."""

    def setUp(self):
        from tests import test_release_candidate as fixtures
        from scripts.release_candidate import record_successful_attempt

        self.fixture = fixtures.CandidateAuthorityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        selected = self.fixture.candidate / "build/selected"
        for host in ("claude", "codex"):
            archive = build_archive(host, selected)
            for group in ("candidate-a", "candidate-b"):
                shutil.copyfile(archive, self.fixture.candidate / "build" / group / archive.name)
        evidence = self.fixture.candidate / "build/evidence"
        (evidence / "unpacked").mkdir()
        build_path = evidence / "build.json"
        build = json.loads(build_path.read_bytes())
        build["artifacts"] = [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "size": path.stat().st_size} for path in sorted(selected.iterdir())]
        build_path.write_text(json.dumps(build))
        _write_sha256sums(evidence / "SHA256SUMS", selected)
        self.fixture._prepare()
        self.fixture._bind()
        self.directory = self.fixture.root
        self.repository = self.fixture.repository
        self.candidate = self.fixture.candidate
        self.commit = self.fixture.commit
        self.receipt = self.directory / "success.json"
        with self.fixture._in_repository():
            record_successful_attempt(self.fixture.record, self.commit, self.receipt)
        self.fixture._git("branch", "-m", "release/v0.1.0-readiness")
        notes = self.repository / "docs/releases/v0.1.0.md"
        notes.parent.mkdir(parents=True)
        notes.write_bytes(RELEASE_NOTES.read_bytes())
        self.fake_bin, self.call_log = _fake_release_commands(self.directory)
        fake_git = self.fake_bin / "git"
        original = fake_git.read_text()
        original = original.replace(
            'if args[:2] == ["rev-parse", "HEAD"]:',
            'if args and (args[0] in {"archive", "show", "ls-tree", "cat-file"} or args[:2] == ["rev-parse", "--show-toplevel"]):\n'
            '    os.execv(os.environ["THREADROOT_REAL_GIT"], ["git", *args])\n'
            'elif args[:2] == ["rev-parse", "HEAD"]:',
        )
        _write_executable(fake_git, original)
        _write_executable(self.fake_bin / "python3", f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import shlex
import shutil
import sys

args = sys.argv[1:]
if args[:3] == ["-B", "-m", "scripts.release_candidate"]:
    with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a") as stream:
        stream.write("release_candidate " + shlex.join(args[3:]) + "\n")
    if args[3] == "verify-success":
        counter = Path(os.environ["THREADROOT_TEST_CALL_LOG"] + ".verify-count")
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        if str(count) == os.environ.get("THREADROOT_DRIFT_AT_VERIFY"):
            Path(os.environ["THREADROOT_DRIFT_MEMBER"]).write_bytes(b"drift\n")
elif "scripts.build_verified_release" in args:
    with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a") as stream:
        stream.write("builder " + shlex.join(args) + "\n")
    if os.environ.get("THREADROOT_BUILDER_FAIL") == "1":
        raise SystemExit(19)
    import json
    import subprocess
    from scripts.release_candidate import _canonical_json, bind_candidate
    output = Path(args[args.index("--output") + 1])
    record = Path(args[args.index("--authority-record") + 1])
    commit = args[args.index("--commit") + 1]
    assert not output.exists() and not record.exists()
    shutil.copytree(os.environ["THREADROOT_FIXTURE_CANDIDATE"], output,
                    ignore=shutil.ignore_patterns("candidate-integrity.json"))
    build_path = output / "build/evidence/build.json"
    build = json.loads(build_path.read_bytes())
    build["commit"] = commit
    build["source_date_epoch"] = int(subprocess.run(
        ["git", "show", "-s", "--format=%ct", commit],
        check=True, capture_output=True, text=True).stdout)
    build_path.write_bytes(_canonical_json(build))
    bind_candidate(output, commit, record)
    raise SystemExit(0)
elif args[:3] == ["-B", "-m", "venv"]:
    root = Path(args[3])
    root.mkdir()
    (root / "bin").mkdir()
    for command, template in (("python", "THREADROOT_FAKE_WHEEL_PYTHON"),
                              ("threadroot", "THREADROOT_FAKE_WHEEL_CLI")):
        shutil.copyfile(os.environ[template], root / "bin" / command)
        (root / "bin" / command).chmod(0o755)
    with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a") as stream:
        stream.write("install venv " + str(root) + "\n")
    raise SystemExit(0)
elif args[:2] == ["-B", "scripts/check_public.py"]:
    args[1] = str(Path(os.environ["THREADROOT_WORKTREE"]) / args[1])
os.execv(os.environ["THREADROOT_REAL_PYTHON"], [os.environ["THREADROOT_REAL_PYTHON"], *args])
''')
        self.state = self.directory / "threadroot-v010-release-state-20260905"
        self.environment = {
            "FAKE_GIT_HEAD": self.commit,
            "FAKE_RELEASE_COMMIT": self.commit,
            "THREADROOT_REAL_GIT": shutil.which("git"),
            "THREADROOT_REAL_PYTHON": sys.executable,
            "THREADROOT_WORKTREE": str(Path.cwd()),
            "THREADROOT_FIXTURE_CANDIDATE": str(self.candidate),
            "THREADROOT_DRIFT_MEMBER": str(self.candidate / "source-b/README.md"),
            "threadroot_reviewed_head": self.commit,
            "threadroot_candidate_record": str(self.fixture.record),
            "threadroot_candidate_receipt": str(self.receipt),
        }
        wheel_python = self.directory / "wheel-python"
        _write_executable(wheel_python, f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import sys
args = sys.argv[1:]
with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a") as stream:
    stream.write("wheel-python " + " ".join(args) + "\n")
if args == ["-m", "pip", "uninstall", "-y", "threadroot"]:
    Path(sys.argv[0]).with_name("threadroot").unlink()
elif args == ["-c", "import threadroot"]:
    raise SystemExit(1)
elif args[:3] == ["-m", "pip", "install"]:
    assert "--no-index" in args and "--no-deps" in args
    if os.environ.get("THREADROOT_TOOL_DRIFT") == "1":
        Path(os.environ["THREADROOT_DRIFT_MEMBER"]).write_bytes(b"installer drift")
elif args != ["-m", "pip", "check"] and args[:1] != ["-c"]:
    raise SystemExit(97)
''')
        wheel_cli = self.directory / "wheel-cli"
        _write_executable(wheel_cli, f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import sys
with Path(os.environ["THREADROOT_TEST_CALL_LOG"]).open("a") as stream:
    stream.write("threadroot " + " ".join(sys.argv[1:]) + "\n")
os.execv(os.environ["THREADROOT_REAL_PYTHON"],
         [os.environ["THREADROOT_REAL_PYTHON"], "-B", "-m", "threadroot", *sys.argv[1:]])
''')
        self.environment.update(THREADROOT_FAKE_WHEEL_PYTHON=str(wheel_python),
                                THREADROOT_FAKE_WHEEL_CLI=str(wheel_cli))
        for host in ("claude", "codex"):
            _write_task_10_host_fake(self.fake_bin, host)
            host_file = self.fake_bin / host
            source = host_file.read_text().replace(
                "set -euo pipefail\n", "set -euo pipefail\n" +
                f"printf '%s\\n' \"{host} $*\" >> {str(self.call_log)!r}\n")
            _write_executable(host_file, source)
        self.plan = REPRODUCIBLE_RELEASE_PLAN.read_text()

    def run_block(self, task, step, block=0, **environment):
        return _run_release_plan_block(
            _release_plan_bash_block(self.plan, task, step, block),
            self.directory, self.fake_bin, self.call_log, repository=self.repository,
            **(self.environment | environment),
        )

    def calls(self):
        return self.call_log.read_text() if self.call_log.exists() else ""

    def bind_state(self):
        result = self.run_block(7, 4)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, value in (("pr-url.txt", "https://example.invalid/pr/1"),
                            ("approved-pr-head.txt", self.commit),
                            ("release-commit.txt", self.commit),
                            ("final-root.txt", str(self.candidate))):
            (self.state / name).write_text(value + "\n")
        for source, name in ((self.fixture.record, "final-authority.json"),
                             (self.receipt, "final-success.json")):
            destination = self.state / name
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o400)
        self.call_log.write_text("")
        Path(str(self.call_log) + ".verify-count").write_text("0")

    def test_task_8_pr_evidence_remains_outside_candidate(self):
        from scripts.release_candidate import verify_successful_attempt
        self.bind_state()
        (self.state / "approved-pr-head.txt").unlink()
        result = self.run_block(8, 3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "pr-checks.json").is_file())
        self.assertTrue((self.state / "pr.diff").is_file())
        self.assertFalse((self.candidate / "pr-checks.json").exists())
        self.assertFalse((self.candidate / "pr.diff").exists())
        with self.fixture._in_repository():
            self.assertEqual(verify_successful_attempt(self.receipt, self.fixture.record, self.commit), self.candidate)

    def test_task_9_source_drift_immediately_before_merge_stops_mutator(self):
        self.bind_state()
        result = self.run_block(9, 1, THREADROOT_DRIFT_AT_VERIFY="2")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("gh pr merge ", self.calls())
        self.assertEqual(self.calls().count("release_candidate verify-success"), 2)

    def test_task_9_final_build_records_new_state_local_pair(self):
        self.bind_state()
        self.fixture._git("commit", "--allow-empty", "--no-gpg-sign", "-qm", "synthetic merged commit")
        release_commit = self.fixture._git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(release_commit, self.commit)
        (self.state / "release-commit.txt").write_text(release_commit + "\n")
        for name in ("final-authority.json", "final-success.json", "final-root.txt"):
            (self.state / name).unlink()
        result = self.run_block(9, 4, FAKE_RELEASE_COMMIT=release_commit)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "final-authority.json").is_file())
        self.assertTrue((self.state / "final-success.json").is_file())
        authority = json.loads((self.state / "final-authority.json").read_bytes())
        self.assertEqual(authority["commit"], release_commit)
        root = authority["candidate_root"]
        self.assertEqual((self.state / "final-root.txt").read_text(), root + "\n")

    def test_task_10_raw_record_cannot_begin_install(self):
        self.bind_state()
        (self.state / "final-success.json").unlink()
        result = self.run_block(10, 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release_candidate verify-success", self.calls())
        self.assertFalse((self.candidate / "wheel-smoke-venv").exists())

    def test_task_9_failed_final_builder_cannot_record_success_or_bind_root(self):
        self.bind_state()
        for name in ("final-authority.json", "final-success.json", "final-root.txt"):
            (self.state / name).unlink()
        result = self.run_block(9, 4, THREADROOT_BUILDER_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("builder ", self.calls())
        self.assertNotIn("release_candidate record-success", self.calls())
        self.assertFalse((self.state / "final-success.json").exists())
        self.assertFalse((self.state / "final-root.txt").exists())

    def test_task_11_drift_before_draft_upload_stops_mutator(self):
        self.bind_state()
        result = self.run_block(11, 3, THREADROOT_DRIFT_AT_VERIFY="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("gh release create ", self.calls())
        self.assertEqual(self.calls().count("release_candidate verify-success"), 2)

    def prepare_draft(self):
        selected = self.candidate / "build/selected"
        download = self.directory / "draft-download"
        shutil.copytree(selected, download)
        (self.state / "draft-download-root.txt").write_text(str(download) + "\n")
        release_json = _write_release_contract(self.state, selected)
        return {"FAKE_RELEASE_JSON": str(release_json),
                "FAKE_DRAFT_ASSET_ROOT": str(download)}

    def test_task_12_drift_before_publish_stops_mutator(self):
        self.bind_state()
        result = self.run_block(12, 2, **self.prepare_draft(), THREADROOT_DRIFT_AT_VERIFY="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("gh release edit ", self.calls())
        self.assertEqual(self.calls().count("release_candidate verify-success"), 2)

    def test_task_10_complete_validation_uses_one_external_root_and_preserves_candidate(self):
        from scripts.release_candidate import verify_successful_attempt
        self.bind_state()
        for step, block in ((1, 0), (2, 0), (3, 0), (3, 1), (4, 0), (4, 1), (5, 0)):
            with self.subTest(step=step, block=block):
                result = self.run_block(10, step, block)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        validation = Path((self.state / "validation-root.txt").read_text().strip())
        self.assertEqual(validation.stat().st_mode & 0o777, 0o700)
        self.assertFalse(validation.is_relative_to(self.candidate))
        self.assertFalse(validation.is_relative_to(self.repository))
        for relative in ("wheel-smoke-venv", "cli-smoke", "host-smoke/claude-smoke", "host-smoke/codex-smoke"):
            self.assertTrue((validation / relative).is_dir())
        self.assertEqual(len(list(self.directory.glob("threadroot-v010-validation-*"))), 1)
        with self.fixture._in_repository():
            self.assertEqual(verify_successful_attempt(self.receipt, self.fixture.record, self.commit), self.candidate)

    def test_task_8_push_and_pr_create_have_separate_fresh_verification(self):
        self.bind_state()
        (self.state / "pr-url.txt").unlink()
        result = self.run_block(8, 2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls().splitlines()
        pushes = [i for i, line in enumerate(calls) if line.startswith("git push ")]
        creates = [i for i, line in enumerate(calls) if line.startswith("gh pr create ")]
        checks = [i for i, line in enumerate(calls) if line.startswith("release_candidate verify-success ")]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(len(creates), 1)
        self.assertTrue(checks[1] < pushes[0] < checks[2] < creates[0])

    def test_task_8_drift_at_each_outbound_boundary_prevents_its_mutator(self):
        for count, mutator, existing in ((2, "git push ", ""), (3, "gh pr create ", ""),
                                         (3, "gh pr edit ", "https://example.invalid/pr/1")):
            with self.subTest(mutator=mutator):
                case = ReleaseAuthorityFlowTests()
                case.setUp()
                try:
                    case.bind_state()
                    (case.state / "pr-url.txt").unlink()
                    result = case.run_block(8, 2, THREADROOT_DRIFT_AT_VERIFY=str(count), FAKE_EXISTING_PR=existing)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(mutator, case.calls())
                    self.assertEqual(case.calls().count("release_candidate verify-success"), count)
                finally:
                    case.doCleanups()

    def prepare_validation(self, wheel=True):
        validation = self.directory / "validation"
        validation.mkdir(mode=0o700)
        (self.state / "validation-root.txt").write_text(str(validation) + "\n")
        (validation / "cli-smoke").mkdir()
        for host in ("claude", "codex"):
            for child in ("bundle", "home", "config", "cache", "data", "state", "tmp"):
                (validation / "host-smoke" / f"{host}-smoke" / child).mkdir(parents=True)
        if wheel:
            binaries = validation / "wheel-smoke-venv/bin"
            binaries.mkdir(parents=True)
            for command, template in (("python", "THREADROOT_FAKE_WHEEL_PYTHON"),
                                      ("threadroot", "THREADROOT_FAKE_WHEEL_CLI")):
                shutil.copyfile(self.environment[template], binaries / command)
                (binaries / command).chmod(0o755)
        return validation

    def test_task_10_drift_at_every_install_and_uninstall_boundary_stops_that_effect(self):
        cases = (
            (2, 0, 2, "install venv", ""),
            (2, 0, 3, "wheel-python -m pip install", ""),
            (3, 0, 3, "threadroot init", "--apply"),
            (3, 0, 6, "threadroot claim", "--apply"),
            (3, 0, 7, "threadroot claim", "--apply"),
            (4, 1, 2, "claude plugin marketplace add", ""),
            (4, 1, 3, "claude plugin install", ""),
            (4, 1, 4, "codex plugin marketplace add", ""),
            (4, 1, 5, "codex plugin add", ""),
            (5, 0, 2, "wheel-python -m pip uninstall", ""),
            (5, 0, 3, "claude plugin remove", ""),
            (5, 0, 4, "claude plugin marketplace remove", ""),
            (5, 0, 5, "codex plugin remove", ""),
            (5, 0, 6, "codex plugin marketplace remove", ""),
        )
        for index, (step, block, count, mutator, qualifier) in enumerate(cases):
            with self.subTest(step=step, count=count, mutator=mutator):
                case = ReleaseAuthorityFlowTests()
                case.setUp()
                try:
                    case.bind_state()
                    case.prepare_validation(wheel=step != 2)
                    result = case.run_block(10, step, block, THREADROOT_DRIFT_AT_VERIFY=str(count))
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    effects = [line for line in case.calls().splitlines()
                               if line.startswith(mutator) and qualifier in line]
                    self.assertEqual(len(effects), 1 if (step, count) == (3, 7) else 0,
                                     case.calls())
                    block_effects = {item[3:5] for item in cases if item[:2] == (step, block)}
                    actual_preceding = [effect for line in case.calls().splitlines()
                                        for effect in block_effects
                                        if line.startswith(effect[0]) and effect[1] in line]
                    expected_preceding = [item[3:5] for item in cases[:index]
                                          if item[:2] == (step, block)]
                    self.assertEqual(actual_preceding, expected_preceding, case.calls())
                    self.assertEqual(case.calls().count("release_candidate verify-success"), count,
                                     result.stdout + result.stderr)
                finally:
                    case.doCleanups()

    def test_task_11_tag_and_push_have_separate_drift_gates(self):
        for count, mutator in ((2, "git tag --annotate"), (3, "git push ")):
            with self.subTest(mutator=mutator):
                case = ReleaseAuthorityFlowTests()
                case.setUp()
                try:
                    case.bind_state()
                    result = case.run_block(11, 2, FAKE_LS_REMOTE_EMPTY="1",
                                           THREADROOT_DRIFT_AT_VERIFY=str(count))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(mutator, case.calls())
                    self.assertEqual(case.calls().count("release_candidate verify-success"), count)
                finally:
                    case.doCleanups()

    def test_task_11_positive_tag_and_draft_keep_valid_authority(self):
        self.bind_state()
        for step in (2, 3):
            result = self.run_block(11, step, FAKE_LS_REMOTE_EMPTY="1")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("git tag --annotate", self.calls())
        self.assertIn("git push origin refs/tags/v0.1.0:refs/tags/v0.1.0", self.calls())
        self.assertIn("gh release create ", self.calls())

    def test_task_12_positive_publish_downloads_fresh_bytes_before_mutation(self):
        self.bind_state()
        result = self.run_block(12, 2, **self.prepare_draft())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls().splitlines()
        downloads = [i for i, line in enumerate(calls) if line.startswith("gh release download ")]
        publishes = [i for i, line in enumerate(calls) if line.startswith("gh release edit ")]
        self.assertEqual(len(downloads), 4)
        self.assertEqual(len(publishes), 1)
        self.assertLess(downloads[-1], publishes[0])
        bound = Path((self.state / "publish-download-root.txt").read_text().strip())
        self.assertNotEqual(bound, self.directory / "draft-download")
        for name in EXPECTED_RELEASE_ASSETS:
            self.assertEqual((bound / name).read_bytes(), (self.candidate / "build/selected" / name).read_bytes())

    def test_task_7_reviewers_require_successful_entry_and_exit(self):
        review = re.search(r"^```sh\n(.*?)^```", _release_plan_step(self.plan, 7, 4), re.M | re.S).group(1)
        for reviewer in ("spec", "quality"):
            result = _run_release_plan_block(review, self.directory, self.fake_bin, self.call_log,
                                             repository=self.repository, **self.environment)
            self.assertEqual(result.returncode, 0, reviewer + result.stderr)
        self.assertEqual(self.calls().count("release_candidate verify-success"), 4)
        result = _run_release_plan_block(review, self.directory, self.fake_bin, self.call_log,
                                        repository=self.repository,
                                        **(self.environment | {"THREADROOT_DRIFT_AT_VERIFY": "6"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls().count("release_candidate verify-success"), 6)

    def test_task_7_raw_record_cannot_enter_review(self):
        review = re.search(r"^```sh\n(.*?)^```", _release_plan_step(self.plan, 7, 4), re.M | re.S).group(1)
        self.receipt.unlink()
        result = _run_release_plan_block(review, self.directory, self.fake_bin, self.call_log,
                                        repository=self.repository, **self.environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls().count("release_candidate verify-success"), 1)

    def test_task_7_binding_rejects_head_other_than_reviewed_commit(self):
        result = self.run_block(7, 4, FAKE_GIT_HEAD="9" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.state.exists())

    def test_task_8_approval_rejects_local_head_drift(self):
        self.bind_state()
        (self.state / "approved-pr-head.txt").unlink()
        result = self.run_block(8, 3, FAKE_GIT_HEAD="9" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "approved-pr-head.txt").exists())
        self.assertIn("release_candidate verify-success", self.calls())

    def test_task_8_post_check_drift_prevents_approved_head_binding(self):
        self.bind_state()
        (self.state / "approved-pr-head.txt").unlink()
        result = self.run_block(8, 3, THREADROOT_DRIFT_AT_VERIFY="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "approved-pr-head.txt").exists())
        self.assertTrue((self.state / "pr.diff").is_file())

    def test_task_10_installer_candidate_write_invalidates_block_exit(self):
        self.bind_state()
        self.prepare_validation(wheel=False)
        result = self.run_block(10, 2, THREADROOT_TOOL_DRIFT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wheel-python -m pip install", self.calls())
        self.assertEqual(self.calls().count("release_candidate verify-success"), 4)

    def test_task_9_merge_rejects_approval_not_bound_to_reviewed_head(self):
        self.bind_state()
        (self.state / "approved-pr-head.txt").write_text("9" * 40 + "\n")
        result = self.run_block(9, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("gh pr merge ", self.calls())
        self.assertIn("release_candidate verify-success", self.calls())

    def test_task_11_tag_probe_errors_cannot_authorize_tag_or_push(self):
        self.bind_state()
        for environment in ({"FAKE_SHOW_REF_EXIT": "2", "FAKE_LS_REMOTE_EMPTY": "1"},
                            {"FAKE_LS_REMOTE_EXIT": "42"}):
            result = self.run_block(11, 2, **environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("git tag --annotate", self.calls())
            self.assertNotIn("git push ", self.calls())
            self.assertNotIn("unsupported fake", result.stderr)

    def test_task_11_selected_artifact_drift_cannot_authorize_upload(self):
        self.bind_state()
        (self.candidate / "build/selected/threadroot-codex-0.1.0.zip").write_bytes(b"drift")
        result = self.run_block(11, 3)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("gh release create ", self.calls())
        self.assertFalse((self.state / "draft-url.txt").exists())

    def test_task_12_prior_guards_remain_discriminating_with_valid_authority(self):
        scenarios = ("main-drift", "selected-and-old-download-drift", "current-draft-same-size-drift",
                     "download-failure", "existing-binding", "metadata-drift")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                case = ReleaseAuthorityFlowTests()
                case.setUp()
                try:
                    case.bind_state()
                    environment = case.prepare_draft()
                    current = case.directory / "current-draft"
                    shutil.copytree(case.directory / "draft-download", current)
                    environment["FAKE_DRAFT_ASSET_ROOT"] = str(current)
                    binding = case.state / "publish-download-root.txt"
                    if scenario == "main-drift":
                        environment["FAKE_REMOTE_MAIN"] = "9" * 40
                    elif scenario == "selected-and-old-download-drift":
                        for root in (case.candidate / "build/selected", case.directory / "draft-download"):
                            (root / "threadroot-codex-0.1.0.zip").write_bytes(b"same drift")
                    elif scenario == "current-draft-same-size-drift":
                        member = current / "threadroot-codex-0.1.0.zip"
                        payload = member.read_bytes()
                        member.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
                    elif scenario == "download-failure":
                        environment["FAKE_RELEASE_DOWNLOAD_EXIT"] = "42"
                    elif scenario == "existing-binding":
                        binding.write_text("existing authority\n")
                    else:
                        metadata = Path(environment["FAKE_RELEASE_JSON"])
                        data = json.loads(metadata.read_text())
                        data["name"] = "changed draft"
                        metadata.write_text(json.dumps(data))
                    result = case.run_block(12, 2, **environment)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn("gh release edit ", case.calls())
                    self.assertNotIn("unsupported fake", result.stderr)
                    self.assertIn("release_candidate verify-success", case.calls())
                    if scenario == "existing-binding":
                        self.assertEqual(binding.read_text(), "existing authority\n")
                        self.assertNotIn("gh release download ", case.calls())
                    else:
                        self.assertFalse(binding.exists())
                    if scenario in ("current-draft-same-size-drift", "metadata-drift"):
                        self.assertEqual(case.calls().count("gh release download "), 4)
                finally:
                    case.doCleanups()

    def test_task_12_public_binding_checks_metadata_with_valid_final_pair(self):
        for valid in (True, False):
            with self.subTest(valid=valid):
                case = ReleaseAuthorityFlowTests()
                case.setUp()
                try:
                    case.bind_state()
                    selected = case.candidate / "build/selected"
                    public = case.directory / "public-download"
                    shutil.copytree(selected, public)
                    _write_public_release(public / "release.json", selected)
                    if not valid:
                        (public / "release.json").write_text('{"tag_name":"v0.1.0"}')
                    record = case.directory / f"threadroot-v010-public-candidate-{case.commit}.txt"
                    record.write_text(str(public) + "\n")
                    result = case.run_block(12, 3, 1)
                    binding = case.state / "public-download-root.txt"
                    if valid:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(binding.read_text(), str(public) + "\n")
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(binding.exists())
                    self.assertIn("release_candidate verify-success", case.calls())
                finally:
                    case.doCleanups()

    def test_task_7_binding_copies_the_verified_pair_and_exact_bindings(self):
        result = self.run_block(7, 4)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for source, name in ((self.fixture.record, "candidate-authority.json"),
                             (self.receipt, "candidate-success.json")):
            destination = self.state / name
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o400)
        self.assertEqual((self.state / "candidate-root.txt").read_text(), f"{self.candidate}\n")
        self.assertEqual((self.state / "reviewed-head.txt").read_text(), f"{self.commit}\n")
        self.assertGreaterEqual(self.calls().count("release_candidate verify-success"), 2)

    def test_task_7_raw_record_and_post_review_drift_cannot_create_state(self):
        for failure in ("missing-receipt", "source-drift"):
            with self.subTest(failure=failure):
                if failure == "missing-receipt":
                    self.receipt.rename(self.directory / "held-success.json")
                else:
                    (self.directory / "held-success.json").rename(self.receipt)
                    (self.candidate / "source-a/README.md").write_bytes(b"drift\n")
                result = self.run_block(7, 4)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.state.exists())
                self.assertIn("release_candidate verify-success", self.calls())

    def test_task_7_builder_failure_never_records_success(self):
        result = self.run_block(7, 2, THREADROOT_BUILDER_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("builder ", self.calls())
        self.assertNotIn("release_candidate record-success", self.calls())

    def test_task_7_successful_builder_creates_pair_in_success_arm(self):
        result = self.run_block(7, 2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = dict(line.split(": ", 1) for line in result.stdout.splitlines()
                       if line.startswith(("Authority: ", "Receipt: ")))
        record, receipt = Path(summary["Authority"]), Path(summary["Receipt"])
        self.assertEqual(record.name, "authority.json")
        self.assertEqual(receipt.name, "success.json")
        self.assertEqual(record.parent, receipt.parent)
        self.assertTrue(record.parent.name.startswith(f"threadroot-v010-candidate-{self.commit}-"))
        self.assertTrue(record.is_file() and receipt.is_file())
        calls = self.calls()
        self.assertLess(calls.index("builder "), calls.index("release_candidate record-success"))
        self.assertLess(calls.index("release_candidate record-success"),
                        calls.index("release_candidate verify-success"))


if __name__ == "__main__":
    unittest.main()
