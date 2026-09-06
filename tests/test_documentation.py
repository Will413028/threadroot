from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
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
EXPECTED_RELEASE_COMMAND = (
    'python3 -m scripts.build_verified_release --commit "$GITHUB_SHA" '
    '--output "$RUNNER_TEMP/threadroot-release"'
)
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
      - run: python3 -m scripts.build_verified_release --commit "$GITHUB_SHA" --output "$RUNNER_TEMP/threadroot-release"
"""


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
    if os.environ.get("FAKE_LS_REMOTE_EMPTY") == "1":
        raise SystemExit(0)
    commit = os.environ.get("FAKE_TAG_COMMIT", os.environ.get("FAKE_RELEASE_COMMIT", "3" * 40))
    print(f"{commit}\\trefs/tags/v0.1.0^{{}}")
elif args and args[0] in {"fetch", "merge-base"}:
    raise SystemExit(int(os.environ.get("FAKE_GIT_READ_EXIT", "0")))
elif args and args[0] in {"tag", "push"}:
    pass
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
    return subprocess.run(
        ["/bin/bash", "-c", sandboxed],
        cwd=Path.cwd(),
        env=run_environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_selected_artifacts(selected: Path, marker: bytes) -> None:
    selected.mkdir(parents=True)
    for name in sorted(EXPECTED_RELEASE_ASSETS):
        (selected / name).write_bytes(marker + b":" + name.encode("utf-8"))


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


def _write_task_10_checksum(path: Path) -> None:
    path.with_suffix(".before").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}\n",
        encoding="utf-8",
    )


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
            [EXPECTED_RELEASE_COMMAND],
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
        canonical_release_step = f"      - run: {EXPECTED_RELEASE_COMMAND}\n"
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

    def test_task_10_cli_smoke_validation_runs_in_a_fresh_shell(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 10, 3, 1)

        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            smoke_root = final_root / "cli-smoke"
            smoke_home = smoke_root / "home"
            smoke_xdg = smoke_root / "xdg"
            smoke_vault = smoke_root / "vault"
            state_root.mkdir()
            smoke_home.mkdir(parents=True)
            smoke_xdg.mkdir()
            (smoke_vault / "daily").mkdir(parents=True)
            (smoke_vault / "daily" / "2042-04-03.md").write_bytes(b"")
            (state_root / "final-root.txt").write_text(
                f"{final_root}\n", encoding="utf-8"
            )
            sentinel = smoke_root / "sentinel.txt"
            sentinel.write_text("unrelated sentinel\n", encoding="utf-8")
            _write_task_10_checksum(sentinel)

            document_names = (
                "init-preview.json",
                "init-apply.json",
                "doctor.json",
                "claim-preview.json",
                "claim-apply.json",
                "claim-repeat.json",
            )
            commands = ("init", "init", "doctor", "claim", "claim", "claim")
            applied = (False, True, False, False, True, False)
            for index, (name, command, was_applied) in enumerate(
                zip(document_names, commands, applied, strict=True)
            ):
                (smoke_root / name).write_text(
                    json.dumps(
                        {
                            "ok": index != 5,
                            "command": command,
                            "applied": was_applied,
                            "vault": str(smoke_vault),
                            "changes": [],
                            "issues": (
                                [] if index != 5 else [{"code": "target.conflict"}]
                            ),
                        }
                    ),
                    encoding="utf-8",
                )

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((smoke_root / "vault-pristine").is_dir())

    def test_task_10_host_validation_runs_in_a_fresh_shell(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 10, 4, 1)

        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            _write_task_10_host_fake(fake_bin, "claude")
            _write_task_10_host_fake(fake_bin, "codex")
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            smoke_root = final_root / "cli-smoke"
            host_root = final_root / "host-smoke"
            state_root.mkdir()
            smoke_root.mkdir(parents=True)
            for name in (
                "claude-bundle",
                "codex-bundle",
                "claude-home",
                "claude-config",
                "claude-cache",
                "codex-home",
                "codex-config",
                "codex-data",
                "codex-cache",
                "codex-state",
                "claude-tmp",
                "codex-tmp",
            ):
                (host_root / name).mkdir(parents=True)
            (state_root / "final-root.txt").write_text(
                f"{final_root}\n", encoding="utf-8"
            )

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                (smoke_root / "claude-version.txt").read_text(encoding="utf-8"),
                "claude 1.0.0\n",
            )
            self.assertEqual(
                (smoke_root / "codex-version.txt").read_text(encoding="utf-8"),
                "codex 1.0.0\n",
            )
            self.assertTrue((host_root / "claude-list-installed.json").is_file())
            self.assertTrue((host_root / "codex-list-installed.json").is_file())

    def test_task_10_uninstall_runs_in_a_fresh_shell(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 10, 5)

        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            _write_task_10_host_fake(fake_bin, "claude")
            _write_task_10_host_fake(fake_bin, "codex")
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            smoke_root = final_root / "cli-smoke"
            smoke_vault = smoke_root / "vault"
            host_root = final_root / "host-smoke"
            state_root.mkdir()
            (state_root / "final-root.txt").write_text(
                f"{final_root}\n", encoding="utf-8"
            )
            wheel_python = final_root / "wheel-smoke-venv" / "bin" / "python"
            wheel_python.parent.mkdir(parents=True)
            _write_executable(
                wheel_python,
                """#!/bin/bash
set -euo pipefail
if test "$*" = "-m pip uninstall -y threadroot"; then
  exit 0
fi
if test "$*" = "-c import threadroot"; then
  exit 1
fi
exit 97
""",
            )
            (smoke_vault / "daily").mkdir(parents=True)
            (smoke_vault / "daily" / "2042-04-03.md").write_bytes(b"")
            (smoke_root / "vault-pristine" / "daily").mkdir(parents=True)
            (smoke_root / "vault-pristine" / "daily" / "2042-04-03.md").write_bytes(
                b""
            )
            sentinel = smoke_root / "sentinel.txt"
            sentinel.write_text("unrelated sentinel\n", encoding="utf-8")
            _write_task_10_checksum(sentinel)
            for name in ("claude-bundle", "codex-bundle"):
                bundle = host_root / name
                pristine = host_root / f"{name}-pristine"
                bundle.mkdir(parents=True)
                pristine.mkdir()
                (bundle / "manifest.txt").write_text("same\n", encoding="utf-8")
                (pristine / "manifest.txt").write_text(
                    "same\n", encoding="utf-8"
                )
            for name in (
                "claude-home",
                "claude-config",
                "claude-cache",
                "codex-home",
                "codex-config",
                "codex-data",
                "codex-cache",
                "codex-state",
                "claude-tmp",
                "codex-tmp",
            ):
                (host_root / name).mkdir(parents=True)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((host_root / "claude-list-removed.json").is_file())
            self.assertTrue((host_root / "codex-list-removed.json").is_file())
            self.assertTrue((smoke_root / "sentinel.after-uninstall").is_file())

    def test_task_7_binding_rejects_candidate_commit_without_writing_authority(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 7, 4)
        reviewed_head = "1" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            candidate_root = directory / "candidate"
            evidence = candidate_root / "build" / "evidence"
            evidence.mkdir(parents=True)
            (evidence / "build.json").write_text(
                json.dumps({"commit": "2" * 40}),
                encoding="utf-8",
            )
            candidate_record = (
                directory / f"threadroot-v010-candidate-{reviewed_head}.txt"
            )
            candidate_record.write_text(f"{candidate_root}\n", encoding="utf-8")

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
            )

            state_root = directory / "threadroot-v010-release-state-20260905"
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertFalse(
                state_root.exists(),
                "a rejected candidate must not create the authority directory",
            )

    def test_task_7_binding_reloads_successful_candidate_in_new_shell(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 7, 4)
        reviewed_head = "1" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            candidate_root = directory / "candidate"
            selected = candidate_root / "build" / "selected"
            _write_selected_artifacts(selected, b"approved")
            _write_sha256sums(
                candidate_root / "build" / "evidence" / "SHA256SUMS",
                selected,
            )
            (candidate_root / "build" / "evidence" / "build.json").write_text(
                json.dumps({"commit": reviewed_head}),
                encoding="utf-8",
            )
            candidate_record = (
                directory / f"threadroot-v010-candidate-{reviewed_head}.txt"
            )
            candidate_record.write_text(f"{candidate_root}\n", encoding="utf-8")

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
            )

            state_root = directory / "threadroot-v010-release-state-20260905"
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                (state_root / "candidate-root.txt").read_text(encoding="utf-8"),
                f"{candidate_root}\n",
            )
            self.assertEqual(
                (state_root / "reviewed-head.txt").read_text(encoding="utf-8"),
                f"{reviewed_head}\n",
            )

    def test_task_8_pr_approval_rejects_local_head_drift_without_authority_write(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 8, 3)
        reviewed_head = "1" * 40
        changed_head = "2" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            candidate_root = directory / "candidate"
            evidence = candidate_root / "build" / "evidence"
            evidence.mkdir(parents=True)
            (evidence / "build.json").write_text(
                json.dumps({"commit": reviewed_head}),
                encoding="utf-8",
            )
            state_root.mkdir()
            (state_root / "candidate-root.txt").write_text(
                f"{candidate_root}\n", encoding="utf-8"
            )
            (state_root / "reviewed-head.txt").write_text(
                f"{reviewed_head}\n", encoding="utf-8"
            )
            (state_root / "pr-url.txt").write_text(
                "https://example.invalid/pr/1\n", encoding="utf-8"
            )

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=changed_head,
                FAKE_PR_HEAD=changed_head,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertFalse(
                (state_root / "approved-pr-head.txt").exists(),
                "local HEAD drift must not become approved authority",
            )

    def test_task_9_merge_rejects_pr_authority_not_bound_to_reviewed_head(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 9, 1)
        reviewed_head = "1" * 40
        unreviewed_head = "2" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            state_root.mkdir()
            (state_root / "reviewed-head.txt").write_text(
                f"{reviewed_head}\n", encoding="utf-8"
            )
            (state_root / "approved-pr-head.txt").write_text(
                f"{unreviewed_head}\n", encoding="utf-8"
            )
            (state_root / "pr-url.txt").write_text(
                "https://example.invalid/pr/1\n", encoding="utf-8"
            )

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_PR_HEAD=unreviewed_head,
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertNotIn("gh pr merge", calls)

    def test_task_11_draft_upload_rehashes_current_selected_assets(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 11, 3)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            canonical = final_root / "build" / "evidence" / "SHA256SUMS"
            _write_selected_artifacts(selected, b"approved")
            _write_sha256sums(canonical, selected)
            state_root.mkdir()
            _write_sha256sums(state_root / "final-recomputed.SHA256SUMS", selected)
            (state_root / "reviewed-head.txt").write_text(
                f"{reviewed_head}\n", encoding="utf-8"
            )
            (state_root / "approved-pr-head.txt").write_text(
                f"{reviewed_head}\n", encoding="utf-8"
            )
            (state_root / "release-commit.txt").write_text(
                f"{release_commit}\n", encoding="utf-8"
            )
            (state_root / "final-root.txt").write_text(
                f"{final_root}\n", encoding="utf-8"
            )
            (selected / "threadroot-codex-0.1.0.zip").write_bytes(b"drifted")

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_RELEASE_COMMIT=release_commit,
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertNotIn("gh release create", calls)
            self.assertFalse((state_root / "draft-url.txt").exists())

    def test_task_11_tag_probe_failures_skip_tag_and_push_mutators(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 11, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        scenarios = {
            "local probe error": {
                "FAKE_SHOW_REF_EXIT": "2",
                "FAKE_LS_REMOTE_EMPTY": "1",
            },
            "remote probe error": {"FAKE_LS_REMOTE_EXIT": "42"},
        }
        for scenario, failure_environment in scenarios.items():
            with self.subTest(scenario=scenario), TemporaryDirectory() as directory_name:
                directory = Path(directory_name)
                fake_bin, call_log = _fake_release_commands(directory)
                state_root = directory / "threadroot-v010-release-state-20260905"
                state_root.mkdir()
                for name, value in (
                    ("reviewed-head.txt", reviewed_head),
                    ("approved-pr-head.txt", reviewed_head),
                    ("release-commit.txt", release_commit),
                ):
                    (state_root / name).write_text(
                        f"{value}\n", encoding="utf-8"
                    )

                result = _run_release_plan_block(
                    block,
                    directory,
                    fake_bin,
                    call_log,
                    FAKE_GIT_HEAD=reviewed_head,
                    FAKE_RELEASE_COMMIT=release_commit,
                    **failure_environment,
                )

                calls = (
                    call_log.read_text(encoding="utf-8")
                    if call_log.exists()
                    else ""
                )
                self.assertNotEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                self.assertNotIn("unsupported fake", result.stderr)
                self.assertNotIn("git tag --annotate", calls)
                self.assertNotIn("git push", calls)

    def test_task_12_publish_precondition_failure_skips_mutator(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            draft_download = directory / "draft-download"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(draft_download, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
                ("draft-download-root.txt", str(draft_download)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            release_json = _write_release_contract(state_root, selected)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_RELEASE_COMMIT=release_commit,
                FAKE_REMOTE_MAIN="9" * 40,
                FAKE_RELEASE_JSON=str(release_json),
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertNotIn("gh release edit", calls)
            self.assertFalse((state_root / "publish-download-root.txt").exists())

    def test_task_12_publish_rehashes_current_selected_assets(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            draft_download = directory / "draft-download"
            _write_selected_artifacts(selected, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            _write_selected_artifacts(draft_download, b"approved")
            drifted_asset = "threadroot-codex-0.1.0.zip"
            (selected / drifted_asset).write_bytes(b"matching drift")
            (draft_download / drifted_asset).write_bytes(b"matching drift")
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
                ("draft-download-root.txt", str(draft_download)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            release_json = _write_release_contract(state_root, selected)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_RELEASE_COMMIT=release_commit,
                FAKE_RELEASE_JSON=str(release_json),
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertNotIn("gh release edit", calls)
            self.assertFalse((state_root / "publish-download-root.txt").exists())

    def test_task_12_publish_rejects_same_size_current_draft_byte_drift(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            prior_download = directory / "draft-download"
            current_draft = directory / "current-draft"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(prior_download, b"approved")
            _write_selected_artifacts(current_draft, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            drifted_asset = current_draft / "threadroot-codex-0.1.0.zip"
            original = drifted_asset.read_bytes()
            drifted_asset.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            self.assertEqual(
                drifted_asset.stat().st_size,
                (selected / drifted_asset.name).stat().st_size,
            )
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
                ("draft-download-root.txt", str(prior_download)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            release_json = _write_release_contract(state_root, selected)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
                FAKE_RELEASE_COMMIT=release_commit,
                FAKE_RELEASE_JSON=str(release_json),
                FAKE_DRAFT_ASSET_ROOT=str(current_draft),
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            downloads = [
                call
                for call in calls.splitlines()
                if call.startswith("gh release download ")
            ]
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertEqual(len(downloads), 4)
            self.assertNotIn("gh release edit", calls)
            self.assertFalse((state_root / "publish-download-root.txt").exists())

    def test_task_12_publish_redownloads_current_draft_before_mutation(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            prior_download = directory / "draft-download"
            current_draft = directory / "current-draft"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(prior_download, b"approved")
            _write_selected_artifacts(current_draft, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
                ("draft-download-root.txt", str(prior_download)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            release_json = _write_release_contract(state_root, selected)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
                FAKE_RELEASE_COMMIT=release_commit,
                FAKE_RELEASE_JSON=str(release_json),
                FAKE_DRAFT_ASSET_ROOT=str(current_draft),
            )

            calls = call_log.read_text(encoding="utf-8").splitlines()
            downloads = [
                call for call in calls if call.startswith("gh release download ")
            ]
            edits = [call for call in calls if call.startswith("gh release edit ")]
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertEqual(len(downloads), 4)
            self.assertEqual(len(edits), 1)
            self.assertLess(calls.index(downloads[-1]), calls.index(edits[0]))
            publication_root = Path(
                (state_root / "publish-download-root.txt")
                .read_text(encoding="utf-8")
                .strip()
            )
            self.assertTrue(publication_root.is_dir())
            for name in EXPECTED_RELEASE_ASSETS:
                self.assertEqual(
                    (publication_root / name).read_bytes(),
                    (selected / name).read_bytes(),
                )

    def test_task_12_publish_download_failure_skips_mutator_and_binding(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            prior_download = directory / "draft-download"
            current_draft = directory / "current-draft"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(prior_download, b"approved")
            _write_selected_artifacts(current_draft, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
                ("draft-download-root.txt", str(prior_download)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            release_json = _write_release_contract(state_root, selected)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
                FAKE_RELEASE_COMMIT=release_commit,
                FAKE_RELEASE_JSON=str(release_json),
                FAKE_DRAFT_ASSET_ROOT=str(current_draft),
                FAKE_RELEASE_DOWNLOAD_EXIT="42",
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("synthetic release download failure", result.stderr)
            self.assertIn("gh release download", calls)
            self.assertNotIn("gh release edit", calls)
            self.assertFalse((state_root / "publish-download-root.txt").exists())

    def test_task_12_publish_refuses_to_overwrite_existing_binding(self) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 2)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            prior_download = directory / "draft-download"
            current_draft = directory / "current-draft"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(prior_download, b"approved")
            _write_selected_artifacts(current_draft, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
                ("draft-download-root.txt", str(prior_download)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            binding = state_root / "publish-download-root.txt"
            binding.write_text("existing authority\n", encoding="utf-8")
            release_json = _write_release_contract(state_root, selected)

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
                FAKE_RELEASE_COMMIT=release_commit,
                FAKE_RELEASE_JSON=str(release_json),
                FAKE_DRAFT_ASSET_ROOT=str(current_draft),
            )

            calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("gh release download", calls)
            self.assertNotIn("gh release edit", calls)
            self.assertEqual(binding.read_text(encoding="utf-8"), "existing authority\n")

    def test_task_12_public_binding_reloads_successful_candidate_in_new_shell(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 3, 1)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            public_download = directory / "public-download"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(public_download, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            _write_public_release(public_download / "release.json", selected)
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            candidate_record = (
                directory
                / f"threadroot-v010-public-candidate-{release_commit}.txt"
            )
            candidate_record.write_text(f"{public_download}\n", encoding="utf-8")

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
                FAKE_RELEASE_COMMIT=release_commit,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                (state_root / "public-download-root.txt").read_text(
                    encoding="utf-8"
                ),
                f"{public_download}\n",
            )

    def test_task_12_public_binding_rejects_invalid_metadata_without_authority(
        self,
    ) -> None:
        plan = REPRODUCIBLE_RELEASE_PLAN.read_text(encoding="utf-8")
        block = _release_plan_bash_block(plan, 12, 3, 1)
        reviewed_head = "1" * 40
        release_commit = "3" * 40
        with TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            fake_bin, call_log = _fake_release_commands(directory)
            state_root = directory / "threadroot-v010-release-state-20260905"
            final_root = directory / "final"
            selected = final_root / "build" / "selected"
            public_download = directory / "public-download"
            _write_selected_artifacts(selected, b"approved")
            _write_selected_artifacts(public_download, b"approved")
            _write_sha256sums(
                final_root / "build" / "evidence" / "SHA256SUMS", selected
            )
            (public_download / "release.json").write_text(
                json.dumps({"tag_name": "v0.1.0"}),
                encoding="utf-8",
            )
            state_root.mkdir()
            for name, value in (
                ("reviewed-head.txt", reviewed_head),
                ("approved-pr-head.txt", reviewed_head),
                ("release-commit.txt", release_commit),
                ("final-root.txt", str(final_root)),
            ):
                (state_root / name).write_text(f"{value}\n", encoding="utf-8")
            candidate_record = (
                directory
                / f"threadroot-v010-public-candidate-{release_commit}.txt"
            )
            candidate_record.write_text(f"{public_download}\n", encoding="utf-8")

            result = _run_release_plan_block(
                block,
                directory,
                fake_bin,
                call_log,
                FAKE_GIT_HEAD=reviewed_head,
                FAKE_RELEASE_COMMIT=release_commit,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unsupported fake", result.stderr)
            self.assertFalse((state_root / "public-download-root.txt").exists())

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
        expected_commands = "\n".join(
            (
                'threadroot_release_output="$(mktemp -d)"',
                "python3 -m scripts.build_verified_release \\",
                '  --commit "$(git rev-parse HEAD)" \\',
                '  --output "$threadroot_release_output"',
                'find "$threadroot_release_output/build/selected" '
                "-maxdepth 1 -type f -print | sort",
            )
        )

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


if __name__ == "__main__":
    unittest.main()
