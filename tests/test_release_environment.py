import re
from pathlib import Path
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


class ReleaseEnvironmentTests(unittest.TestCase):
    def test_release_lock_is_exact_and_hash_locked(self) -> None:
        path = Path("requirements/release.txt")
        self.assertTrue(path.is_file(), "canonical release lock is missing")
        logical = _logical_requirement_lines(path.read_text(encoding="utf-8"))
        self.assertIn("--only-binary=:all:", logical)
        entries = [line for line in logical if not line.startswith("--")]
        actual: dict[str, tuple[str, str]] = {}
        for entry in entries:
            match = re.fullmatch(
                r"([A-Za-z0-9_.-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})",
                entry,
            )
            self.assertIsNotNone(match, f"invalid pinned requirement: {entry}")
            assert match is not None
            name, version, digest = match.groups()
            normalized = _normalized_name(name)
            self.assertNotIn(normalized, actual)
            actual[normalized] = (version, digest)
        self.assertEqual(actual, EXPECTED_REQUIREMENTS)
        self.assertNotIn("setuptools", actual)
        self.assertNotIn("wheel", actual)

    def test_dockerfile_is_immutable_and_offline_build_definition(self) -> None:
        path = Path("tools/release/Dockerfile")
        self.assertTrue(path.is_file(), "canonical Dockerfile is missing")
        text = path.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertEqual(lines[0], f"FROM {EXPECTED_BASE}")
        self.assertEqual(sum(line.startswith("FROM ") for line in lines), 1)
        for setting in (
            "TZ=UTC",
            "LC_ALL=C.UTF-8",
            "LANG=C.UTF-8",
            "PYTHONHASHSEED=0",
            "PYTHONDONTWRITEBYTECODE=1",
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "PIP_NO_INPUT=1",
            "PIP_CONFIG_FILE=/dev/null",
            "PIP_INDEX_URL=https://pypi.org/simple",
            'PIP_EXTRA_INDEX_URL=""',
            'PIP_FIND_LINKS=""',
            "PIP_NO_CACHE_DIR=1",
        ):
            self.assertIn(setting, text)
        self.assertEqual(
            re.findall(r"^COPY\s+(.+?)\s+/opt/threadroot/release-requirements\.txt$", text, re.MULTILINE),
            ["requirements/release.txt"],
        )
        self.assertIn(
            "python -m pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all:",
            text,
        )
        self.assertIn("python -m pip check", text)

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
