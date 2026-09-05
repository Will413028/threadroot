import re
from pathlib import Path
import shlex
import unittest


EXPECTED_BASE = (
    "python:3.14.7-slim-bookworm@"
    "sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9"
)
EXPECTED_REQUIREMENTS = {
    "build": ("1.6.0", "f7aaf1ebbb79178a02ba248bb524f2176b256017e17e8e4bd4289c7b38cc2bad"),
    "hatchling": ("1.32.0", "0e17c9c3b9aa7c625acc8d0f5b622f107d5049af9ecf5ada4de1aada5be7cdbc"),
    "packaging": ("26.3", "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c"),
    "pathspec": ("1.1.1", "a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189"),
    "pip": ("26.2.1", "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e"),
    "pluggy": ("1.6.0", "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746"),
    "pyproject-hooks": ("1.2.0", "9e5c6bfa8dcc30091c74b0cf803c81fdd29d94f01992a7707bc97babb1141913"),
    "tomlkit": ("0.15.1", "177a05aece5a8ca5266fd3c448abb47b8d352f09d477d3ca8332db4d89b24304"),
    "trove-classifiers": ("2026.6.1.19", "ab4c4ec93cc4a4e7815fa759906e05e6bb3f2fbd92ea0f897288c6a43efd15b3"),
}


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _logical_requirement_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    logical: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line or line.startswith("#"):
            continue
        if line == "--only-binary=:all:":
            logical.append(line)
            continue
        if not line.endswith("\\") or index >= len(lines):
            logical.append(line)
            continue
        logical.append(f"{line[:-1].rstrip()} {lines[index]}")
        index += 1
    return logical


def _assert_release_lock_text(text: str) -> dict[str, tuple[str, str]]:
    logical = _logical_requirement_lines(text)
    options = [line for line in logical if line.startswith("--")]
    assert options == ["--only-binary=:all:"]
    entries = [line for line in logical if not line.startswith("--")]
    actual: dict[str, tuple[str, str]] = {}
    for entry in entries:
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})",
            entry,
        )
        assert match is not None, f"invalid pinned requirement: {entry}"
        name, version, digest = match.groups()
        normalized = _normalized_name(name)
        assert normalized not in actual
        actual[normalized] = (version, digest)
    assert actual == EXPECTED_REQUIREMENTS
    assert "setuptools" not in actual
    assert "wheel" not in actual
    return actual


EXPECTED_ENVIRONMENT = {
    "TZ": "UTC",
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "PIP_CONFIG_FILE": "/dev/null",
    "PIP_INDEX_URL": "https://pypi.org/simple",
    "PIP_EXTRA_INDEX_URL": "",
    "PIP_FIND_LINKS": "",
    "PIP_NO_CACHE_DIR": "1",
}


def _logical_docker_instructions(text: str) -> list[tuple[str, str]]:
    instructions: list[tuple[str, str]] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line and not pending:
            continue
        if not pending and line.startswith("#"):
            continue
        combined = f"{pending}{line}" if pending else line
        if combined.endswith("\\"):
            pending = f"{combined[:-1].rstrip()} "
            continue
        pending = ""
        match = re.fullmatch(r"([A-Za-z]+)\s+(.*)", combined)
        assert match is not None, f"invalid Docker instruction: {combined}"
        instructions.append((match.group(1).upper(), match.group(2).strip()))
    assert not pending, "unterminated Docker instruction"
    return instructions


def _assert_dockerfile_contract(text: str) -> None:
    instructions = _logical_docker_instructions(text)
    assert instructions[0] == ("FROM", EXPECTED_BASE)
    assert [rest for keyword, rest in instructions if keyword == "FROM"] == [EXPECTED_BASE]

    envs = [rest for keyword, rest in instructions if keyword == "ENV"]
    assert len(envs) == 1
    env_tokens = shlex.split(envs[0])
    assert len(env_tokens) == len(EXPECTED_ENVIRONMENT)
    actual_environment: dict[str, str] = {}
    for token in env_tokens:
        name, separator, value = token.partition("=")
        assert separator and name and name not in actual_environment
        actual_environment[name] = value
    assert actual_environment == EXPECTED_ENVIRONMENT

    copies = [rest for keyword, rest in instructions if keyword == "COPY"]
    assert copies == ["requirements/release.txt /opt/threadroot/release-requirements.txt"]

    runs = [rest for keyword, rest in instructions if keyword == "RUN"]
    assert len(runs) == 1
    assert shlex.split(runs[0]) == [
        "python",
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        "-r",
        "/opt/threadroot/release-requirements.txt",
        "&&",
        "python",
        "-m",
        "pip",
        "check",
    ]
    assert [rest for keyword, rest in instructions if keyword == "WORKDIR"] == ["/workspace"]
    assert {keyword for keyword, _ in instructions} <= {"FROM", "ENV", "COPY", "RUN", "WORKDIR"}


class ReleaseEnvironmentTests(unittest.TestCase):
    def test_release_lock_rejects_unapproved_requirement_option(self) -> None:
        text = """--only-binary=:all:
--requirement extra-release.txt
build==1.6.0 --hash=sha256:f7aaf1ebbb79178a02ba248bb524f2176b256017e17e8e4bd4289c7b38cc2bad
"""
        with self.assertRaises(AssertionError):
            _assert_release_lock_text(text)

    def test_dockerfile_rejects_second_lowercase_from(self) -> None:
        text = Path("tools/release/Dockerfile").read_text(encoding="utf-8")
        with self.assertRaises(AssertionError):
            _assert_dockerfile_contract(text + "\nfrom scratch\n")

    def test_dockerfile_rejects_environment_override(self) -> None:
        text = Path("tools/release/Dockerfile").read_text(encoding="utf-8")
        with self.assertRaises(AssertionError):
            _assert_dockerfile_contract(text.replace("WORKDIR /workspace", "ENV TZ=BAD\nWORKDIR /workspace"))

    def test_dockerfile_rejects_extra_copy_instruction(self) -> None:
        text = Path("tools/release/Dockerfile").read_text(encoding="utf-8")
        with self.assertRaises(AssertionError):
            _assert_dockerfile_contract(text.replace("WORKDIR /workspace", "COPY extra.txt /tmp/extra.txt\nWORKDIR /workspace"))

    def test_dockerfile_rejects_comment_only_install_and_check(self) -> None:
        text = Path("tools/release/Dockerfile").read_text(encoding="utf-8")
        mutated = text.replace("RUN python -m pip install", "# RUN python -m pip install")
        with self.assertRaises(AssertionError):
            _assert_dockerfile_contract(mutated)

    def test_release_lock_is_exact_and_hash_locked(self) -> None:
        path = Path("requirements/release.txt")
        self.assertTrue(path.is_file(), "canonical release lock is missing")
        _assert_release_lock_text(path.read_text(encoding="utf-8"))

    def test_dockerfile_is_immutable_and_offline_build_definition(self) -> None:
        path = Path("tools/release/Dockerfile")
        self.assertTrue(path.is_file(), "canonical Dockerfile is missing")
        text = path.read_text(encoding="utf-8")
        _assert_dockerfile_contract(text)

    def test_dockerignore_exposes_only_release_lock(self) -> None:
        path = Path(".dockerignore")
        self.assertTrue(path.is_file(), "canonical Docker context policy is missing")
        effective = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(effective, ["**", "!requirements/", "!requirements/release.txt"])


if __name__ == "__main__":
    unittest.main()
