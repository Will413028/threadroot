# Threadroot Reproducible Release Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the nondeterministic Setuptools sdist path with a
backend-native Hatchling build and produce all four Threadroot v0.1.0 release
assets through one pinned, offline artifact-build boundary.

**Architecture:** `pyproject.toml` becomes the only Python packaging authority,
while Hatchling owns deterministic wheel and sdist creation and the existing
host ZIP builder retains its product-specific responsibility. A pinned
`linux/amd64` OCI builder and hash-locked Python toolchain run one checked-in
entry point that exports one Git commit twice, builds two independent artifact
sets, validates them, and promotes the unchanged selected bytes.

**Tech Stack:** Python 3.11-3.14, standard-library `unittest`, Hatchling 1.32.0,
PyPA build 1.6.0, Docker/OCI, GitHub Actions, Git, GitHub CLI, `curl`, `jq`, and
SHA-256.

**Spec:**
`docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md`

**Task 4 amendment:**
`docs/superpowers/plans/2026-09-06-threadroot-artifact-identity-amendment.md`
supersedes the remaining Task 4 implementation checklist after the initial
artifact-orchestrator review exposed a cross-phase identity flaw.

**Execution mode:** Subagent-Driven, as already selected by the user. Execute
one task at a time with fresh implementation and review agents; external
authorization gates remain with the primary agent.

## Global Constraints

- Runtime dependencies remain empty; Hatchling, Docker, and all release tools
  are maintainer-side build dependencies only.
- Supported runtime compatibility remains Python 3.11 through 3.14 on macOS
  and Linux.
- The canonical release platform is exactly `linux/amd64` with Python 3.14.7.
- The canonical base image is
  `python:3.14.7-slim-bookworm@sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9`.
- Canonical build packages are exact and hash-locked. The artifact-build
  container runs with no network and PEP 517 isolation disabled. Provisioning
  ignores ambient pip configuration, uses only `https://pypi.org/simple`, and
  installs the complete lock with `--no-deps` before `pip check`.
- `SOURCE_DATE_EPOCH` is the exact source commit's committer timestamp;
  `TZ=UTC`, `LC_ALL=C.UTF-8`, `LANG=C.UTF-8`, `PYTHONHASHSEED=0`, and umask
  `022` are fixed.
- The public release contains exactly the wheel, sdist, Claude ZIP, and Codex
  ZIP named in the approved spec. Evidence files are never release assets.
- Do not add an sdist canonicalizer, custom Setuptools command, archive
  monkeypatch, clock interception, or post-build archive mutation.
- Do not change runtime CLI behavior, the vault schema, Agent Skills, plugin
  manifests, product version, or release notes except where this plan names an
  exact documentation correction.
- Preserve the failed Setuptools candidates and diagnostic report as evidence;
  never overwrite them with Hatchling output.
- Use synthetic fixtures only. Never copy a private vault, denylist payload,
  host credentials, or private machine-local path/context into Git, build context,
  logs, or artifacts.
- Before every commit or annotated tag, require the repository-local Git
  identity to remain `Will` / `will413028@gmail.com`; never change the
  machine-global identity to proceed.
- Stage exact paths only. One bounded authorization may cover branch push and
  PR creation together. Merge, tag push, draft creation, and publication each
  remain separate explicit external authorization gates.
- Once Task 9 binds the green merge commit, hold a short release freeze on
  `main` through Task 12. Feature-branch development may continue, but no other
  PR or direct push may advance `main` during the tag/draft authorization gap.

## Supersession boundary

This plan replaces Tasks 5 through 12 of
`docs/superpowers/plans/2026-09-05-threadroot-v0.1.0-release-readiness.md`.
Tasks 1 through 4 of that plan remain historical completed work. No command in
the superseded tasks that installs, asserts, or invokes the old Setuptools
release toolchain may be reused.

## File map

| Path | Responsibility |
|---|---|
| `pyproject.toml` | PEP 517 backend, project metadata, exact Hatchling wheel/sdist selection |
| `MANIFEST.in` | Delete; it must not remain as a second packaging authority |
| `.dockerignore` | Restrict canonical image build context to the public release lock |
| `requirements/release.txt` | Exact hash-locked canonical Python build toolchain |
| `tools/release/Dockerfile` | Immutable Python 3.14.7 `linux/amd64` build environment |
| `scripts/release_archives.py` | Safe Python/host archive inspection, source parity, and regular-file-only extraction |
| `scripts/release_artifacts.py` | Build, compare, replay, scan, and promote artifact sets inside the container |
| `scripts/build_verified_release.py` | Sole local/CI entry point; export the commit and enforce the Docker security boundary |
| `tests/test_packaging.py` | Backend, metadata, and explicit file-selection contract |
| `tests/test_documentation.py` | Public docs and exact CI structure |
| `tests/test_release_environment.py` | Image digest, lock, Dockerfile, and no-Setuptools assertions |
| `tests/test_release_archives.py` | Wheel, sdist, host ZIP, path, type, and safe-extraction tests |
| `tests/test_release_artifacts.py` | Artifact validator and promotion unit tests |
| `tests/test_verified_release.py` | Source-export and Docker invocation boundary tests |
| `.github/workflows/ci.yml` | Existing compatibility matrix plus one canonical reproducibility job |
| `docs/testing.md` | Maintainer-facing ordinary and canonical build instructions |
| `docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md` | Approved architectural authority for this plan |
| `docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md` | Executable plan and authorization boundaries |
| `docs/superpowers/plans/2026-09-05-threadroot-v0.1.0-release-readiness.md` | Visible supersession notice only |

## Spec coverage

| Approved requirement | Plan coverage |
|---|---|
| Live repository metadata, release notes, attribution audit | Completed historical Tasks 1-4 in the superseded plan; preserved by Task 0 |
| Hatchling as the sole Python packaging authority | Task 1 |
| Digest-pinned image and complete hash lock | Task 2 |
| Safe archive, membership, metadata, and source-parity checks | Task 3 |
| Two builds, byte comparison, sdist replay, privacy scan, atomic selection | Task 4 |
| One local/CI entry point and offline artifact boundary | Task 5 |
| Eight compatibility jobs plus one canonical artifact job | Task 6 |
| Full local verification and independent review | Task 7 |
| Reviewed PR, exact merge commit, green `main` | Tasks 8-9 |
| Final artifact install, host isolation, and uninstall | Task 10 |
| Immutable tag, verified draft, publication, public redownload | Tasks 11-12 |
| No PyPI/marketplace/model/private-vault expansion; open adoption gate | Global constraints and Task 12 |

---

### Task 0: Record the approved architecture and supersession boundary

**Files:**

- Modify: `docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md`
- Create: `docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md`
- Modify: `docs/superpowers/plans/2026-09-05-threadroot-v0.1.0-release-readiness.md`

**Interfaces:**

- Consumes: the user's approved Hatchling/canonical-builder design.
- Produces: one committed planning baseline that prevents later tasks from
  executing the superseded Setuptools path.

- [ ] **Step 1: Verify the documentation-only planning diff**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_documentation \
  tests.test_public_safety \
  -v
python3 scripts/check_public.py \
  docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md \
  docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md \
  docs/superpowers/plans/2026-09-05-threadroot-v0.1.0-release-readiness.md
git diff --check
```

Expected: PASS, zero public-safety findings, the design status is `Approved`,
and the old plan links to this plan before any stale command.

- [ ] **Step 2: Commit only the approved planning baseline**

```bash
test "$(git config --local --get user.name)" = "Will"
test "$(git config --local --get user.email)" = "will413028@gmail.com"
git add \
  docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md \
  docs/superpowers/plans/2026-09-05-threadroot-reproducible-release-build.md \
  docs/superpowers/plans/2026-09-05-threadroot-v0.1.0-release-readiness.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs: approve reproducible release architecture"
```

---

### Task 1: Migrate the Python packaging authority to Hatchling

**Files:**

- Modify: `tests/test_packaging.py`
- Modify: `tests/test_documentation.py`
- Modify: `pyproject.toml`
- Delete: `MANIFEST.in`

**Interfaces:**

- Consumes: static PEP 621 metadata and the existing `src/threadroot` layout.
- Produces: one Hatchling configuration with an explicit wheel package and
  sdist allowlist; Task 2 extends that allowlist with its new build-environment
  files.

- [ ] **Step 1: Add failing packaging-authority tests**

Add these constants and test to `tests/test_packaging.py`:

```python
EXPECTED_SDIST_ROOTS = [
    ".claude-plugin",
    ".codex-plugin",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "docs",
    "scripts",
    "skills",
    "src/threadroot",
    "templates",
    "tests",
]


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
```

Replace
`DocumentationTests.test_source_manifest_includes_public_policy_documents`
with
`DocumentationTests.test_sdist_configuration_includes_public_policy_documents`,
which reads `tool.hatch.build.targets.sdist.only-include` and requires
`CONTRIBUTING.md` and `SECURITY.md`. Remove the now-unused `shlex` import.

- [ ] **Step 2: Run the focused tests and verify the old backend fails**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_packaging.ManifestTests.test_python_packaging_has_one_hatchling_authority \
  tests.test_documentation.DocumentationTests.test_sdist_configuration_includes_public_policy_documents \
  -v
```

Expected: FAIL because the current backend is `setuptools.build_meta`,
`MANIFEST.in` exists, and no Hatchling target configuration exists.

- [ ] **Step 3: Replace the backend and file-selection configuration**

Make the relevant `pyproject.toml` sections exactly:

```toml
[build-system]
requires = ["hatchling>=1.32,<2"]
build-backend = "hatchling.build"

[project]
name = "threadroot"
version = "0.1.0"
description = "Local-first second-brain workflows for coding agents"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
license-files = ["LICENSE"]
authors = [{ name = "Threadroot contributors" }]
dependencies = []

[tool.hatch.build]
reproducible = true

[tool.hatch.build.targets.wheel]
packages = ["src/threadroot"]

[tool.hatch.build.targets.sdist]
only-include = [
  ".claude-plugin",
  ".codex-plugin",
  "AGENTS.md",
  "CONTRIBUTING.md",
  "LICENSE",
  "README.md",
  "SECURITY.md",
  "docs",
  "scripts",
  "skills",
  "src/threadroot",
  "templates",
  "tests",
]
```

Preserve the approved `[project.urls]` and `[project.scripts]` tables exactly.
Delete the complete `[tool.setuptools]` configuration and delete
`MANIFEST.in`.

- [ ] **Step 4: Run the focused and metadata tests**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_packaging \
  tests.test_documentation.DocumentationTests.test_sdist_configuration_includes_public_policy_documents \
  tests.test_public_safety.PublicSafetyTests.test_runtime_dependency_list_is_empty \
  -v
git diff --check
```

Expected: PASS; runtime dependencies remain `[]`, Hatchling is the only
backend, and no `MANIFEST.in` remains.

- [ ] **Step 5: Commit the backend migration**

```bash
git add pyproject.toml tests/test_packaging.py tests/test_documentation.py
git rm MANIFEST.in
git commit -m "build: migrate distributions to hatchling"
```

---

### Task 2: Define the immutable canonical build environment

**Files:**

- Create: `.dockerignore`
- Create: `requirements/release.txt`
- Create: `tools/release/Dockerfile`
- Create: `tests/test_release_environment.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging.py`

**Interfaces:**

- Consumes: Task 1's Hatchling build configuration.
- Produces: a minimal digest-pinned image and exact package set consumed by
  `scripts/build_verified_release.py`; the release lock and Dockerfile are also
  included in the sdist allowlist.

- [ ] **Step 1: Add failing environment-contract tests**

Create `tests/test_release_environment.py` with tests that require these exact
values:

```python
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
```

Parse each non-option requirement as `normalized-name==version` followed by
exactly its SHA-256 hash. Assert that the complete parsed mapping equals
`EXPECTED_REQUIREMENTS`, every requirement uses `==`, `--only-binary=:all:` is
present, and neither `setuptools` nor `wheel` appears.

Also assert that the Dockerfile:

- starts from `EXPECTED_BASE` and contains no second `FROM`;
- sets `TZ`, `LC_ALL`, `LANG`, `PYTHONHASHSEED`,
  `PYTHONDONTWRITEBYTECODE`, `PIP_DISABLE_PIP_VERSION_CHECK`, and
  `PIP_NO_INPUT` to the approved values;
- sets `PIP_CONFIG_FILE=/dev/null`,
  `PIP_INDEX_URL=https://pypi.org/simple`, empty `PIP_EXTRA_INDEX_URL` and
  `PIP_FIND_LINKS`, and `PIP_NO_CACHE_DIR=1`;
- copies only `requirements/release.txt` from the build context;
- installs with
  `python -m pip install --no-deps --require-hashes --only-binary=:all:`;
  and
- runs `python -m pip check`.

Assert `.dockerignore` contains exactly the three effective patterns `**`,
`!requirements/`, and `!requirements/release.txt` after blank/comment removal.

- [ ] **Step 2: Run the new tests and verify the files are absent**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_release_environment -v
```

Expected: FAIL because the lock, Dockerfile, and `.dockerignore` do not exist.

- [ ] **Step 3: Add the exact release lock**

Create `requirements/release.txt` exactly as follows:

```text
# Canonical Threadroot release-build environment for linux/amd64 Python 3.14.7.
# Upgrade only through a reviewed PR that reruns the complete reproducibility gate.
--only-binary=:all:

build==1.6.0 \
    --hash=sha256:f7aaf1ebbb79178a02ba248bb524f2176b256017e17e8e4bd4289c7b38cc2bad
hatchling==1.32.0 \
    --hash=sha256:0e17c9c3b9aa7c625acc8d0f5b622f107d5049af9ecf5ada4de1aada5be7cdbc
packaging==26.3 \
    --hash=sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c
pathspec==1.1.1 \
    --hash=sha256:a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189
pip==26.2.1 \
    --hash=sha256:71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e
pluggy==1.6.0 \
    --hash=sha256:e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746
pyproject-hooks==1.2.0 \
    --hash=sha256:9e5c6bfa8dcc30091c74b0cf803c81fdd29d94f01992a7707bc97babb1141913
tomlkit==0.15.1 \
    --hash=sha256:177a05aece5a8ca5266fd3c448abb47b8d352f09d477d3ca8332db4d89b24304
trove-classifiers==2026.6.1.19 \
    --hash=sha256:ab4c4ec93cc4a4e7815fa759906e05e6bb3f2fbd92ea0f897288c6a43efd15b3
```

- [ ] **Step 4: Add the minimal Docker build context and image definition**

Create `.dockerignore`:

```dockerignore
**
!requirements/
!requirements/release.txt
```

Create `tools/release/Dockerfile`:

```dockerfile
FROM python:3.14.7-slim-bookworm@sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9

ENV TZ=UTC \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PIP_CONFIG_FILE=/dev/null \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_EXTRA_INDEX_URL="" \
    PIP_FIND_LINKS="" \
    PIP_NO_CACHE_DIR=1

COPY requirements/release.txt /opt/threadroot/release-requirements.txt

RUN python -m pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
      -r /opt/threadroot/release-requirements.txt \
    && python -m pip check

WORKDIR /workspace
```

Replace the sdist `only-include` list and `EXPECTED_SDIST_ROOTS` with this exact
final sequence:

```python
[
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
```

- [ ] **Step 5: Run static environment and packaging tests**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_environment \
  tests.test_packaging \
  tests.test_documentation \
  -v
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Provision and inspect the pinned image only after network authorization**

This step may pull the exact base image and download only hash-approved wheels.
If the current execution has no explicit network authorization, stop before the
command and request it.

Run:

```bash
docker build \
  --platform linux/amd64 \
  --pull \
  --file tools/release/Dockerfile \
  --tag threadroot-release-builder:plan-check \
  .
docker run --rm --platform linux/amd64 --network none \
  threadroot-release-builder:plan-check \
  python -c 'from importlib.metadata import distributions; from packaging.utils import canonicalize_name; expected={"build":"1.6.0","hatchling":"1.32.0","packaging":"26.3","pathspec":"1.1.1","pip":"26.2.1","pluggy":"1.6.0","pyproject-hooks":"1.2.0","tomlkit":"0.15.1","trove-classifiers":"2026.6.1.19"}; actual={canonicalize_name(item.metadata["Name"]): item.version for item in distributions()}; assert actual == expected'
```

Expected: image build succeeds only with matching hashes; the no-network
inspection exits zero and prints nothing.

- [ ] **Step 7: Commit the canonical environment**

```bash
git add .dockerignore requirements/release.txt tools/release/Dockerfile \
  pyproject.toml tests/test_packaging.py tests/test_release_environment.py
git commit -m "build: pin canonical release environment"
```

---

### Task 3: Add safe archive validation and extraction

**Files:**

- Create: `scripts/release_archives.py`
- Create: `tests/test_release_archives.py`

**Interfaces:**

- Consumes: one wheel, sdist, or host ZIP plus the corresponding exported
  source tree.
- Produces: validators that return only after exact membership, metadata,
  source parity, and safe member types pass; and a regular-file-only extractor
  used by Task 4.

- [ ] **Step 1: Write failing path and member-type tests**

Create `tests/test_release_archives.py` with this first test:

```python
def test_validate_archive_name_rejects_unsafe_forms(self) -> None:
    invalid = ("", "/absolute", "../escape", "safe/../../escape", "dir\\file")
    for name in invalid:
        with self.subTest(name=name), self.assertRaisesRegex(
            ReleaseArchiveError, "unsafe archive path"
        ):
            validate_archive_name(name)
```

Add table-driven tar and ZIP fixtures that start with one regular
`safe/file.txt` member. Mutate one property per subtest to create a duplicate,
symlink, hard link, character/block device, FIFO, unsupported mode, or unsafe
path. Require a stable `ReleaseArchiveError.code` and assert no extraction file
was created. Cover an absolute path, `..`, backslash, interior empty component, NUL,
duplicate normalized name, leading/trailing archive data, symlinked destination
parent, and nonempty destination; an already-existing empty destination is
rejected too.

- [ ] **Step 2: Run the tests and verify the module is absent**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_release_archives -v
```

Expected: FAIL because `scripts.release_archives` does not exist.

- [ ] **Step 3: Implement common path, duplicate, type, and extraction rules**

Create `scripts/release_archives.py` with:

```python
class ReleaseArchiveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
```

Expose these exact functions:

- `validate_archive_name(name: str) -> PurePosixPath`
- `extract_regular_tar(artifact: Path, destination: Path,
  expected_global_comment: str | None = None) -> None`
- `extract_regular_zip(artifact: Path, destination: Path) -> None`

Both extractors require a missing destination below a real nonsymlink parent,
reject every
duplicate, link, special type, absolute/parent/backslash name, and write only
validated directories and regular files using descriptor-relative operations.
One trailing slash is permitted only for a directory member; interior empty
components and a trailing slash on a file are invalid.
Never use `extractall`, `shutil.unpack_archive`, or follow an archive-provided
link. Accept input permission bits only from `0644`, `0664`, `0755`, and
`0775`; preserve only executable versus non-executable intent as output `0755`
or `0644`, and set output directories to `0755`. For ZIP files, treat external
file-type bits of zero as a regular file because Hatchling uses that form for
generated dist-info; accept `S_IFREG` too and reject every other non-directory
type. Validate the complete member table before opening
the destination, create parents with `dir_fd`, reopen every parent with
`O_DIRECTORY | O_NOFOLLOW`, create files with `O_CREAT | O_EXCL | O_NOFOLLOW`,
write into a private sibling staging directory, and atomically rename that
complete directory to the requested destination. On failure, remove only the
staging directory created by the current call. Tar PAX data must be empty when
`expected_global_comment` is `None`; otherwise require the sole global and
inherited member mapping to equal `{"comment": expected_global_comment}`. Reject every
path, link, or other PAX override.

- [ ] **Step 4: Add and implement the wheel contract**

Add `test_wheel_requires_exact_source_metadata_entry_point_license_and_record`.
Build a valid synthetic ZIP with the Python source files plus exactly
`METADATA`, `WHEEL`, `entry_points.txt`, `licenses/LICENSE`, and `RECORD` below
`threadroot-0.1.0.dist-info/`. In separate subtests remove each required file,
add an undeclared package file, change one source byte, add `Requires-Dist`, or
change one Project-URL/entry point. Require failure for every mutation and PASS
for the unchanged fixture.

Implement
`validate_wheel(artifact: Path, source: Path, version: str, epoch: int) -> None`.
It must require:

- every regular file recursively below `src/threadroot` at the corresponding
  `threadroot/` path, with identical bytes;
- the five named dist-info metadata files and no extra payload path;
- `Metadata-Version: 2.5`, `Name: threadroot`, `Version: 0.1.0`, the approved
  summary and author, `License-Expression: Apache-2.0`, sole
  `License-File: LICENSE`, `Requires-Python: >=3.11`,
  `Description-Content-Type: text/markdown`, exactly the three approved
  Project-URL rows, no `Requires-Dist`, and a description body equal to
  `README.md`; and
- `threadroot = threadroot.cli:main` as the sole console entry point;
- `Wheel-Version: 1.0`, `Generator: hatchling 1.32.0`,
  `Root-Is-Purelib: true`, and sole tag `py3-none-any`; and
- unique regular-file members in the exact order of sorted package paths,
  followed by `METADATA`, `WHEEL`, `entry_points.txt`, `licenses/LICENSE`, and
  `RECORD`; the UTC DOS timestamp derived from `max(epoch, 315532800)` with
  two-second resolution; Unix create system, DEFLATE compression, normalized
  `0644`/`0755` permission bits, file-type bits of either `S_IFREG` for source
  entries or zero for Hatchling-generated dist-info entries, zero local and
  central general-purpose flags, correct CRC/size,
  and no archive/member comments, extra fields, bytes before the first local
  header, or bytes after the ZIP end record; and a valid
  `RECORD` row for every member, including URL-safe SHA-256 and size for every
  file except the self-row, whose hash and size are empty.

- [ ] **Step 5: Add and implement the sdist contract**

Add `test_sdist_requires_exact_allowlisted_source_and_generated_metadata`.
Generate a PAX-format `.tar.gz` whose regular files all share the sole top-level
prefix `threadroot-0.1.0/`. Mutate the valid fixture with one extra file,
missing source file, changed source byte, second top level, directory entry,
link, special member, wrong gzip/tar timestamp, wrong owner/mode, archive
trailing data, `MANIFEST.in`, `setup.cfg`, and
`src/threadroot.egg-info/PKG-INFO`. Require each mutation to fail.

Implement
`validate_sdist(artifact: Path, source: Path, version: str, epoch: int) -> None`.
Parse the exact `only-include` sequence from `pyproject.toml`, walk only those
source paths without following links, and add `.gitignore`, `pyproject.toml`,
and generated `PKG-INFO` to the expected regular files. Require a gzip header
with DEFLATE method, zero flags, `mtime == epoch`, XFL `2`, OS `255`, and no
original filename/comment/extra field. Require
unique regular-file tar members only, the exact top-level prefix, exact file
membership after stripping that prefix, `uid == gid == 0`, empty owner/group
names, `mtime == epoch`, normalized `0644`/`0755` modes, no global or per-member
PAX values, and no unconsumed bytes after the gzip stream. Compare every
non-generated payload byte for byte with the export. Parse `PKG-INFO` and
require the same name, version, Python,
dependency, license, and Project-URL contract as wheel `METADATA`.

- [ ] **Step 6: Add and implement both host ZIP contracts**

Add one valid synthetic fixture per host and mutate native manifest selection,
timestamp, UTF-8 flag, create-system value, file mode, extra/comment fields,
ordering, and source byte. Require each mutation to fail.

Implement
`validate_host_zip(artifact: Path, source: Path, host: str) -> None` by reusing
the exact `HOST_MANIFESTS`, `COMMON_ROOTS`, and `MARKETPLACE` selections from
`scripts/build_release.py`. Require the existing canonical ZIP metadata and
byte parity contract: sorted unique regular files, 1980 timestamp, Unix create
system, exactly the UTF-8 local and central flag, `0644` mode, DEFLATE
compression, empty
archive/member comments and extras, exact CRC/size, and no bytes outside the
ZIP structure. Do not duplicate workflow content or introduce another host
package builder.

- [ ] **Step 7: Run focused tests and commit archive validation**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_archives \
  tests.test_release \
  tests.test_public_safety \
  -v
python3 -m compileall -q scripts/release_archives.py
git diff --check
```

Expected: PASS.

Commit:

```bash
git add scripts/release_archives.py tests/test_release_archives.py
git commit -m "build: validate release archive contracts"
```

---

### Task 4: Build, compare, replay, scan, and promote artifact sets

> **Execution amendment (approved 2026-09-06):** Do not continue this section
> as a standalone two-file task. Complete the approved artifact-identity
> amendment plan named above, then mark this task complete and resume at Task
> 5. The requirements below remain binding product context; the amendment plan
> is the executable checklist and expands the implementation scope to the Task
> 3 archive core and tests.

**Files:**

- Create: `scripts/release_artifacts.py`
- Create: `tests/test_release_artifacts.py`

**Interfaces:**

- Consumes: two read-only source exports, Task 3's archive validators, the
  fixed environment, and `scripts/build_release.py` from each export.
- Produces:
  `build_and_verify(source_a: Path, source_b: Path, output: Path, commit: str,
  epoch: int, denylist: Path | None = None) -> dict[str, str]`.

- [ ] **Step 1: Add failing exact-set and byte-comparison tests**

Create `tests/test_release_artifacts.py` with:

```python
def test_artifact_set_requires_exact_four_names(self) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for name in expected_asset_names("0.1.0")[:-1]:
            (root / name).write_bytes(b"synthetic")
        with self.assertRaisesRegex(
            ReleaseArtifactError, "release output membership mismatch"
        ):
            ArtifactSet.load(root, "0.1.0")

def test_compare_sets_rejects_one_changed_byte(self) -> None:
    with TemporaryDirectory() as left_dir, TemporaryDirectory() as right_dir:
        for root in (Path(left_dir), Path(right_dir)):
            for name in expected_asset_names("0.1.0"):
                (root / name).write_bytes(name.encode("utf-8"))
        (Path(right_dir) / "threadroot-0.1.0.tar.gz").write_bytes(b"changed")
        with self.assertRaisesRegex(
            ReleaseArtifactError, "artifact bytes differ: threadroot-0.1.0.tar.gz"
        ):
            compare_artifact_sets(
                ArtifactSet.load(Path(left_dir), "0.1.0"),
                ArtifactSet.load(Path(right_dir), "0.1.0"),
            )
```

- [ ] **Step 2: Run the new tests and verify the module is absent**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_release_artifacts -v
```

Expected: FAIL because `scripts.release_artifacts` does not exist.

- [ ] **Step 3: Implement the data model, output gate, and environment gate**

Create `scripts/release_artifacts.py` with:

```python
class ReleaseArtifactError(RuntimeError):
    """Release artifact validation or promotion failed."""


@dataclass(frozen=True)
class ArtifactSet:
    root: Path
    wheel: Path
    sdist: Path
    claude: Path
    codex: Path

    @classmethod
    def load(cls, root: Path, version: str) -> "ArtifactSet":
        root = Path(root)
        names = expected_asset_names(version)
        entries = list(root.iterdir()) if root.is_dir() and not root.is_symlink() else []
        if (
            sorted(path.name for path in entries) != sorted(names)
            or any(path.is_symlink() or not path.is_file() for path in entries)
        ):
            raise ReleaseArtifactError(
                "release output membership mismatch"
            )
        return cls(
            root=root,
            wheel=root / names[0],
            sdist=root / names[1],
            claude=root / names[2],
            codex=root / names[3],
        )
```

The method body above is implemented in this step; do not leave a stub. Add:

```python
def expected_asset_names(version: str) -> tuple[str, str, str, str]:
    return (
        f"threadroot-{version}-py3-none-any.whl",
        f"threadroot-{version}.tar.gz",
        f"threadroot-claude-{version}.zip",
        f"threadroot-codex-{version}.zip",
    )
```

Implement
`compare_artifact_sets(left: ArtifactSet, right: ArtifactSet) -> dict[str, str]`
to return the selected filename-to-SHA-256 mapping only after every byte pair
matches. Implement
`build_and_verify(source_a: Path, source_b: Path, output: Path, commit: str,
epoch: int, denylist: Path | None = None) -> dict[str, str]` as the sole inner
orchestrator and return the same mapping only after atomic promotion.

Require `THREADROOT_CANONICAL_BUILD=1`, Linux x86_64, Python 3.14.7, the
complete installed distribution name/version mapping to equal Task 2's lock
with no extra package, every fixed environment value, a matching
non-negative epoch, a lowercase 40-hex commit, two distinct real nonsymlink
source roots, and a missing or empty nonsymlink output. Call `os.umask(0o022)`
before output creation. Add focused tests that mutate each environment/input
condition and require failure before a candidate directory exists.

- [ ] **Step 4: Implement one-source building and pair comparison**

For each source, invoke these as two distinct commands so the initial wheel is
built directly from the Git export rather than implicitly from the sdist:

```text
python -m build --sdist --no-isolation --outdir CANDIDATE SOURCE
python -m build --wheel --no-isolation --outdir CANDIDATE SOURCE
python SOURCE/scripts/build_release.py --output CANDIDATE
```

Use `sys.executable`, absolute paths, argv lists, `check=True`, and
`shell=False`. Give each candidate distinct empty `TMPDIR`, `HOME`, and
`XDG_CACHE_HOME` directories below `evidence/work/a/` or `evidence/work/b/`.
Pass only those three paths plus `PATH` from the immutable image and these exact
values: `THREADROOT_CANONICAL_BUILD=1`, `SOURCE_DATE_EPOCH=str(epoch)`, `TZ=UTC`,
`LC_ALL=C.UTF-8`, `LANG=C.UTF-8`, `PYTHONHASHSEED=0`,
`PYTHONDONTWRITEBYTECODE=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1`, and
`PIP_NO_INPUT=1`, `PIP_CONFIG_FILE=/dev/null`,
`PIP_INDEX_URL=https://pypi.org/simple`, empty `PIP_EXTRA_INDEX_URL` and
`PIP_FIND_LINKS`, and `PIP_NO_CACHE_DIR=1`. Do not share a build directory or
cache. Require exact
four-file membership and no subdirectory. Compare each pair with
`filecmp.cmp(left_path, right_path, shallow=False)` and stream SHA-256. Add a
test whose mocked second build changes one sdist byte and require that
`selected/` is absent.

- [ ] **Step 5: Apply Task 3 validators and replay the sdist**

Validate both wheel/sdist/host ZIP sets against their own source export,
passing the exact epoch to the Python archive validators. Safely extract
candidate A's sdist with `extract_regular_tar`, run
`python -m build --wheel --no-isolation` against the extracted top level, and
require the replay directory contains only the approved wheel and that its bytes
equal candidate A's wheel. Add a test with a changed replay wheel and require a
stable failure before promotion.

- [ ] **Step 6: Scan, record evidence, and promote only after success**

Safely unpack candidate A's four artifacts beneath `evidence/unpacked/`. Run
candidate A's `scripts/check_public.py` against both exports, every packed
artifact, and every unpacked root. Pass a mounted denylist only by its fixed
container path and never log its bytes.

Write four sorted `DIGEST + two spaces + FILENAME` rows to
`evidence/SHA256SUMS` and canonical newline-terminated `evidence/build.json`
by serializing this exact data model with sorted keys and compact separators:

```python
evidence = {
    "schema": 1,
    "commit": commit,
    "source_date_epoch": epoch,
    "platform": "linux/amd64",
    "python": "3.14.7",
    "base_image": (
        "python:3.14.7-slim-bookworm@"
        "sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9"
    ),
    "builder_definition_sha256": hashlib.sha256(
        dockerfile_bytes + b"\0" + lockfile_bytes
    ).hexdigest(),
    "packages": parsed_release_lock_versions,
    "artifacts": [
        {
            "name": name,
            "sha256": selected_hashes[name],
            "size": candidate_a_paths[name].stat().st_size,
        }
        for name in expected_asset_names(version)
    ],
}
payload = json.dumps(
    evidence,
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
) + "\n"
```

`parsed_release_lock_versions` is the complete sorted name-to-version mapping
read from `requirements/release.txt`; no path, username, hostname, image ID,
clock time, or denylist datum is recorded. Then copy candidate A's four files
into a new
`selected.pending/`, recheck their hashes and sizes, and atomically rename that
complete directory to `selected/`. `selected/` must not exist before every gate
and evidence write succeeds. Add a success test that asserts this exact layout,
a simulated copy/write failure test that leaves only `selected.pending/`, and a
scanner-failure test that asserts both promotion directories are absent.

- [ ] **Step 7: Run focused tests and commit artifact orchestration**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_release_artifacts \
  tests.test_release_archives \
  tests.test_release \
  tests.test_public_safety \
  -v
python3 -m compileall -q scripts/release_artifacts.py
git diff --check
```

Expected: PASS.

Commit:

```bash
git add scripts/release_artifacts.py tests/test_release_artifacts.py
git commit -m "build: verify reproducible release artifacts"
```

---

### Task 5: Add the single local and CI release entry point

**Files:**

- Create: `scripts/build_verified_release.py`
- Create: `tests/test_verified_release.py`

**Interfaces:**

- Consumes: a clean Git repository, one exact 40-character commit, Docker, and
  Task 4's `build_and_verify`.
- Produces: `source-a/`, `source-b/`, and `build/` beneath one new or empty
  absolute output root. `build/` contains `candidate-a/`, `candidate-b/`,
  `evidence/`, and the atomically promoted `selected/`.
- Exposes:
  `canonical_image_tag(dockerfile: Path, lockfile: Path) -> str`,
  `docker_run_argv(image: str, source_a: Path, source_b: Path, output: Path,
  commit: str, epoch: int, uid: int, gid: int, denylist: Path | None) ->
  list[str]`, and `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Add failing outer-boundary tests**

Create `tests/test_verified_release.py` and cover:

```python
def test_image_tag_depends_on_dockerfile_and_lock_bytes(self) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dockerfile = root / "Dockerfile"
        lock = root / "release.txt"
        dockerfile.write_bytes(b"FROM pinned\n")
        lock.write_bytes(b"build==1.6.0\n")
        first = canonical_image_tag(dockerfile, lock)
        lock.write_bytes(b"build==1.6.1\n")
        second = canonical_image_tag(dockerfile, lock)
    self.assertRegex(first, r"^threadroot-release-builder:[0-9a-f]{64}$")
    self.assertNotEqual(first, second)

def test_docker_run_is_offline_read_only_and_unprivileged(self) -> None:
    argv = docker_run_argv(
        image="threadroot-release-builder:" + "0" * 64,
        source_a=Path("/outside/source-a"),
        source_b=Path("/outside/source-b"),
        output=Path("/outside/build"),
        commit="a" * 40,
        epoch=123,
        uid=501,
        gid=20,
        denylist=None,
    )
    self.assertEqual(argv[argv.index("--network") + 1], "none")
    self.assertIn("--read-only", argv)
    self.assertEqual(argv.count("--cap-drop"), 1)
    self.assertIn("ALL", argv)
    self.assertIn("no-new-privileges", argv)
    self.assertNotIn("--privileged", argv)
```

The artifact-identity amendment makes this outer boundary authoritative. Add
`test_docker_run_exactly_establishes_artifact_identity_perimeter`, parse every
`--mount` value, and assert the complete list is exactly:

```python
[
    "type=bind,src=/outside/source-a,dst=/source-a,readonly",
    "type=bind,src=/outside/source-b,dst=/source-b,readonly",
    "type=bind,src=/outside/build,dst=/release-output",
]
```

When a denylist is supplied, the sole additional mount must end with
`dst=/run/threadroot/denylist,readonly`. Assert there is one writable mount,
its destination is `/release-output`, no Docker socket or extra host path is
present, and the argv contains exactly one each of `--read-only`,
`--network none`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, `--user UID:GID`, and the fixed inside
arguments `--source-a /source-a --source-b /source-b --output
/release-output`. Independently delete or alter each security option in a
table-driven validator fixture and require rejection before the inner entry
point can run.

Add separate tests named
`test_requires_full_commit_and_absolute_output_outside_repository`,
`test_rejects_docker_mount_delimiters_and_control_characters`,
`test_rejects_dirty_tracked_or_untracked_repository_state`,
`test_rejects_nonempty_output_and_symlink_output`,
`test_exports_exact_commit_twice_without_links_or_unsafe_names`,
`test_runner_files_must_match_the_selected_commit`,
`test_docker_build_uses_exact_platform_dockerfile_and_export_context`,
`test_optional_denylist_is_mounted_read_only_without_entering_argv_logs`, and
`test_inside_mode_requires_container_sentinel_and_calls_build_and_verify`.
The inside-mode test must also reject any source or output value other than
exactly `/source-a`, `/source-b`, and `/release-output` before importing or
calling Task 4.
For every rejection test, assert both the stable exception message and that no
Docker run occurred. For the denylist test, assert only the fixed container path
appears after `--denylist`; the host basename and bytes must be absent from
captured stdout/stderr. Simulate a Docker failure that echoes every host mount
path and require the public error to replace them with fixed labels.

Mock `subprocess.run` and inspect complete argv lists; never make unit tests
depend on a Docker daemon or network.

- [ ] **Step 2: Run the tests and verify the entry point is absent**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest tests.test_verified_release -v
```

Expected: FAIL because `scripts.build_verified_release` does not exist.

- [ ] **Step 3: Implement validated source export**

Create `scripts/build_verified_release.py` with public usage:

```text
python3 -m scripts.build_verified_release \
  --commit COMMIT_SHA \
  --output ABSOLUTE_OUTPUT_PATH \
  [--denylist ABSOLUTE_DENYLIST_PATH]
```

Define `VerifiedReleaseError(RuntimeError)` for every stable validation
failure. CLI errors print only its public message to stderr and return `1`;
they never print a traceback, subprocess environment, denylist bytes, or
credentials.

The outer path must:

1. Resolve the repository from the module location.
2. Require a clean `git status --porcelain=v1 --untracked-files=all`.
3. Resolve the supplied commit to itself and confirm it is a commit object.
4. Require the current bytes of `.dockerignore`, `requirements/release.txt`,
   `tools/release/Dockerfile`, `pyproject.toml`,
   `scripts/build_verified_release.py`, `scripts/release_archives.py`,
   `scripts/release_artifacts.py`, `scripts/build_release.py`, and
   `scripts/check_public.py` to equal those at the supplied commit before using
   any current-tree runner code.
5. Require the output root to be absolute, outside the repository, not a
   symlink, and missing or empty before creating `source-a`, `source-b`, and
   `build`. Reject a comma, NUL, newline, carriage return, or other control
   character in any host path inserted into a Docker `--mount` value; apply
   the same rule to the optional denylist path.
6. Run `git archive --format=tar COMMIT_SHA` twice and safely materialize only
   regular files and directories into the two distinct roots. Reject archive
   links, special members, unsafe paths, duplicates, and mode values other than
   Git's regular `0664`/`0775` or directory `0775` after masking file type;
   normalize the materialized trees to regular `0644`/`0755` and directory
   `0755`. Require the Git archive's sole global PAX field to be `comment` with
   the exact 40-character commit, and pass that commit as
   `expected_global_comment` during extraction.
7. Derive the epoch only from `git show -s --format=%ct COMMIT_SHA` and require a
   non-negative decimal integer.

Do not use `shutil.unpack_archive`, unrestricted `tarfile.extractall`, shell
pipelines, worktrees, or the caller's untracked files.

- [ ] **Step 4: Implement the Docker provisioning and offline run boundary**

Compute `digest = sha256(dockerfile_bytes + b"\0" + lockfile_bytes).hexdigest()`
and the local image tag as
`f"threadroot-release-builder:{digest}"`. Run Docker build with this exact
shape:

```text
docker build --platform linux/amd64 --pull \
  --file SOURCE_A/tools/release/Dockerfile \
  --tag COMPUTED_TAG SOURCE_A
```

Then run the artifact phase with argv-equivalent options:

```text
docker run --rm --platform linux/amd64 --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=512m --user UID:GID \
  --workdir /source-a \
  --env THREADROOT_CANONICAL_BUILD=1 \
  --env SOURCE_DATE_EPOCH=EPOCH \
  --env TZ=UTC --env LC_ALL=C.UTF-8 --env LANG=C.UTF-8 \
  --env PYTHONHASHSEED=0 --env PYTHONDONTWRITEBYTECODE=1 \
  --env HOME=/tmp \
  --mount type=bind,src=SOURCE_A,dst=/source-a,readonly \
  --mount type=bind,src=SOURCE_B,dst=/source-b,readonly \
  --mount type=bind,src=OUTPUT_BUILD,dst=/release-output \
  COMPUTED_TAG python -m scripts.build_verified_release --inside \
  --source-a /source-a --source-b /source-b \
  --output /release-output --commit COMMIT --epoch EPOCH
```

On platforms with no `os.getuid`/`os.getgid`, fail as unsupported; Windows is
not in scope. When `--denylist` is present, validate it without reading or
printing its bytes, add one read-only bind at `/run/threadroot/denylist`, and
pass only that fixed container path after `--denylist`.

Capture Docker stdout/stderr. On success, forward only sanitized output; on
failure, replace the repository, source, output, and denylist host paths with
`[repository]`, `[source-a]`, `[source-b]`, `[output]`, and `[denylist]` before
raising `VerifiedReleaseError`. Never print `repr(argv)`, the subprocess
environment, or an unsanitized `CalledProcessError`.

Inside mode must reject calls without `THREADROOT_CANONICAL_BUILD=1`, reject
noncanonical absolute source/output paths, import Task 4's
`build_and_verify`, and return nonzero without cleanup on any exception. Docker
provisioning may use network; the artifact phase cannot.

- [ ] **Step 5: Run outer-boundary tests**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_verified_release \
  tests.test_release_artifacts \
  -v
python3 -m compileall -q \
  scripts/build_verified_release.py \
  scripts/release_artifacts.py
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit the entry point**

```bash
git add scripts/build_verified_release.py tests/test_verified_release.py
git commit -m "build: add verified release entry point"
```

---

### Task 6: Make reproducibility a permanent CI and documentation gate

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_documentation.py`
- Modify: `docs/testing.md`

**Interfaces:**

- Consumes: Task 5's sole entry point.
- Produces: eight compatibility jobs plus one separate canonical artifact job,
  and maintainer instructions that invoke the same entry point.

- [ ] **Step 1: Add failing CI/documentation assertions**

Refactor the existing workflow test to inspect the `test` and
`release-artifacts` job bodies separately. Preserve exact compatibility matrix
and commands. Require `release-artifacts` to:

- use `ubuntu-24.04`;
- set `timeout-minutes: 30`;
- contain one full-SHA-pinned `actions/checkout` step;
- run exactly
  `python3 -m scripts.build_verified_release --commit "$GITHUB_SHA" --output "$RUNNER_TEMP/threadroot-release"`;
- contain no artifact upload, release, tag, credential, or write permission;
  and
- leave top-level permissions at `contents: read`.

Add a documentation assertion that `docs/testing.md` contains the canonical
command, names the network-enabled provisioning phase, and states that the
artifact phase is `--network none`.

Add
`test_superseded_release_plan_points_to_reproducible_plan_before_first_task`.
It must require the new plan link and the words `Tasks 5-12` and `must not be
executed` to occur before the old plan's first `### Task` heading.

- [ ] **Step 2: Run the assertions and verify the job/docs are missing**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_documentation.DocumentationTests.test_ci_has_exact_matrix_pins_and_validation_commands \
  tests.test_documentation.DocumentationTests.test_canonical_release_build_is_documented \
  tests.test_documentation.DocumentationTests.test_superseded_release_plan_points_to_reproducible_plan_before_first_task \
  -v
```

Expected: FAIL because `release-artifacts` and the canonical instructions are
absent.

- [ ] **Step 3: Add the dedicated CI job**

Append this job to `.github/workflows/ci.yml`, using the same existing pinned
checkout SHA:

```yaml
  release-artifacts:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - run: python3 -m scripts.build_verified_release --commit "$GITHUB_SHA" --output "$RUNNER_TEMP/threadroot-release"
```

Do not upload CI artifacts or grant write, id-token, attestations, packages, or
actions permissions. The existing eight-cell `test` matrix remains unchanged.

- [ ] **Step 4: Replace the stale build instructions**

In `docs/testing.md`:

- identify Hatchling as the PEP 517 backend and retain ordinary
  `python -m build` for compatibility inspection;
- remove the Setuptools `>=69` offline-toolchain paragraph;
- document that canonical provisioning may pull the digest-pinned image and
  hash-approved wheels, while the artifact container runs with
  `--network none`;
- show this exact maintainer sequence:

```bash
threadroot_release_output="$(mktemp -d)"
python3 -m scripts.build_verified_release \
  --commit "$(git rev-parse HEAD)" \
  --output "$threadroot_release_output"
find "$threadroot_release_output/build/selected" -maxdepth 1 -type f -print | sort
```

- state that the output root must be outside the repository and missing or
  empty, and that failures preserve candidate/evidence directories; and
- state that Docker is not an end-user or runtime requirement.

Confirm Task 0's old-plan supersession test remains green; do not rewrite its
completed Tasks 1-4 or historical failure evidence.

- [ ] **Step 5: Run documentation, workflow, and public checks**

Run:

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_documentation \
  tests.test_packaging \
  tests.test_release_environment \
  -v
python3 scripts/check_public.py \
  .github/workflows/ci.yml \
  docs/testing.md
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit the continuous gate**

```bash
git add .github/workflows/ci.yml tests/test_documentation.py docs/testing.md
git commit -m "ci: enforce reproducible release builds"
```

---

### Task 7: Prove the complete implementation before outbound review

**Files:**

- Verify: all tracked files changed by Tasks 0-6
- Generate outside Git: one fresh canonical candidate/evidence root
- No expected tracked changes unless review finds a defect

**Interfaces:**

- Consumes: Tasks 0-6 as committed, clean branch state.
- Produces: local four-version, canonical-build, privacy, and independent review
  evidence for the exact branch head.

- [ ] **Step 1: Run every supported local interpreter**

Run from the repository root:

```bash
for threadroot_python in python3.11 python3.12 python3.13 python3.14; do
  PYTHONPATH=src:. "$threadroot_python" -m unittest discover -s tests -v
  "$threadroot_python" -m compileall -q src scripts tests
done
```

Expected: all four suites and all four compile passes exit zero.

- [ ] **Step 2: Run the canonical builder against the exact clean HEAD**

This step provisions the pinned image and therefore requires current explicit
network authorization. The nested artifact phase remains offline.

Run:

```bash
test "$(git branch --show-current)" = "release/v0.1.0-readiness"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
threadroot_candidate_root="$(mktemp -d /private/tmp/threadroot-hatchling-candidate-20260905-XXXXXX)"
python3 -m scripts.build_verified_release \
  --commit "$(git rev-parse HEAD)" \
  --output "$threadroot_candidate_root"
find "$threadroot_candidate_root/build/selected" -maxdepth 1 -type f -print | sort
sed -n '1,4p' "$threadroot_candidate_root/build/evidence/SHA256SUMS"
```

Expected: exactly four selected artifact paths and four sorted checksum lines;
candidate A/B, archive checks, scans, and sdist replay all pass inside the
offline container. Preserve and report the root path; do not delete or replace
the earlier Setuptools candidate directories. If the build fails, preserve the
path and use a new candidate root for the next complete attempt rather than
editing or reusing partial output.

- [ ] **Step 3: Run repository-wide safety checks**

Run:

```bash
python3 scripts/check_public.py .
git diff --check origin/main...HEAD
git status --short --branch
git log --oneline origin/main..HEAD
```

If an untracked maintainer denylist is currently bound, rerun the scanner using
that path without printing the variable or file. Expected: no finding, clean
tracked state, and only the reviewed release-readiness commits.

- [ ] **Step 4: Request two-stage code review**

Use `superpowers:requesting-code-review` against the exact
`origin/main...HEAD` diff. First require spec compliance; then require code
quality/security review. The reviewers must inspect at minimum:

- backend/file membership and absence of dormant Setuptools behavior;
- Docker build-context minimization and exact digest/hash pins;
- archive extraction and member-type/path safety;
- subprocess argv, no-network container boundary, permissions, and mounts;
- failure atomicity: no `selected/` before all gates pass;
- source-to-sdist and sdist-to-wheel parity; and
- privacy of evidence and denylist handling.

Fix every Important or higher finding with a focused test-first commit, then
repeat Steps 1-3 and both reviews against the new head. Do not waive a finding
to reach the release deadline.

Only after both reviews pass the unchanged head, bind the final candidate root
once:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
test ! -e "$threadroot_state_root"
install -d -m 700 "$threadroot_state_root"
test "$(jq -r .commit \
  "$threadroot_candidate_root/build/evidence/build.json")" \
  = "$(git rev-parse HEAD)"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/candidate-root.txt" \
  "$threadroot_candidate_root"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/reviewed-head.txt" \
  "$(git rev-parse HEAD)"
```

Require `candidate-root.txt` to name the most recent successful candidate and
`reviewed-head.txt` to equal its `build/evidence/build.json` commit. Never
rewrite these bindings.

---

### Task 8: Push the reviewed branch and open the replacement PR

**Files:**

- External state: `origin/release/v0.1.0-readiness`
- External state: one PR targeting `main`
- No tracked changes

**Interfaces:**

- Consumes: Task 7's clean reviewed head and preserved candidate evidence.
- Produces: one remote PR whose eight compatibility jobs and one
  `release-artifacts` job pass for the exact approved head.

- [ ] **Step 1: Present the exact outbound diff and request authorization**

Run and summarize:

```bash
git status --short --branch
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
```

Ask for explicit authorization to push this branch and create or update its PR.
Do not infer it from spec approval or earlier PR authorization.

- [ ] **Step 2: Push and create the PR under the personal account**

After authorization, create
`/private/tmp/threadroot-v010-pr-body-20260905.md` with exactly:

```markdown
## Summary

- migrate Python distributions from Setuptools to Hatchling without changing runtime dependencies
- pin the canonical linux/amd64 Python 3.14.7 builder by image digest and package hashes
- build two independent copies of all four release assets, compare bytes, replay the sdist, and scan packed and unpacked content
- keep the Python 3.11-3.14 macOS/Linux compatibility matrix separate from the canonical release-artifact job

## Boundaries

- no runtime CLI, vault schema, Agent Skill, plugin manifest, or product-version change
- no PyPI upload, marketplace submission, telemetry, model run, or private-vault content

## Verification

- eight compatibility jobs plus one canonical release-artifacts job
- local four-interpreter unit/compile suite
- byte-identical wheel, sdist, Claude ZIP, and Codex ZIP pairs
- offline sdist-to-wheel replay and zero public-safety findings
```

Then run the exact account and push boundary below. The EXIT trap must remain
installed until the account is restored:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_candidate_root="$(tr -d '\n' < "$threadroot_state_root/candidate-root.txt")"
threadroot_reviewed_head="$(tr -d '\n' < "$threadroot_state_root/reviewed-head.txt")"
test -d "$threadroot_candidate_root/build/selected"
test "$(git rev-parse HEAD)" = "$threadroot_reviewed_head"
threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT

gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
test "$(git remote get-url origin)" \
  = "https://github.com/Will413028/threadroot.git"
test "$(git branch --show-current)" = "release/v0.1.0-readiness"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git push --set-upstream origin \
  HEAD:refs/heads/release/v0.1.0-readiness

threadroot_pr_url="$(gh pr list \
  --repo Will413028/threadroot \
  --base main \
  --head release/v0.1.0-readiness \
  --state open \
  --json url \
  --jq '.[0].url // empty')"
if test -z "$threadroot_pr_url"; then
  threadroot_pr_url="$(gh pr create \
    --repo Will413028/threadroot \
    --base main \
    --head release/v0.1.0-readiness \
    --title "Release: prepare Threadroot v0.1.0" \
    --body-file /private/tmp/threadroot-v010-pr-body-20260905.md)"
else
  gh pr edit "$threadroot_pr_url" \
    --repo Will413028/threadroot \
    --title "Release: prepare Threadroot v0.1.0" \
    --body-file /private/tmp/threadroot-v010-pr-body-20260905.md
fi

python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/pr-url.txt" \
  "$threadroot_pr_url"

threadroot_restore_account
trap - EXIT
```

Do not call `gh auth setup-git`, change Git configuration, push another ref, or
force-update the branch.

- [ ] **Step 3: Verify the exact PR head and all nine checks**

Run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_candidate_root="$(tr -d '\n' < "$threadroot_state_root/candidate-root.txt")"
threadroot_pr_url="$(tr -d '\n' < "$threadroot_state_root/pr-url.txt")"
threadroot_approved_head="$(git rev-parse HEAD)"
test "$(gh pr view "$threadroot_pr_url" \
  --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" \
  = "$threadroot_approved_head"
gh pr checks "$threadroot_pr_url" \
  --repo Will413028/threadroot --watch --fail-fast
gh pr checks "$threadroot_pr_url" \
  --repo Will413028/threadroot \
  --json name,bucket,state,link \
  > "$threadroot_candidate_root/pr-checks.json"
jq -e '
  all(.[]; .bucket == "pass") and
  ([.[] | select(.name == "release-artifacts")] | length == 1) and
  ([.[] | select(.name | startswith("test ("))] | length == 8)
' "$threadroot_candidate_root/pr-checks.json"
gh pr diff "$threadroot_pr_url" \
  --repo Will413028/threadroot \
  > "$threadroot_candidate_root/pr.diff"
test "$(gh pr view "$threadroot_pr_url" \
  --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" \
  = "$threadroot_approved_head"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/approved-pr-head.txt" \
  "$threadroot_approved_head"
```

The exact matrix name formatting must first be confirmed from the returned
JSON; if GitHub adds a repository-level check, require the nine expected
workflow jobs and all additional required checks to pass instead of deleting a
valid external check to satisfy the count. Any new commit invalidates the
approval and returns to Task 7.

---

### Task 9: Merge, bind the release commit, and build final bytes

**Files:**

- External state: one merge commit on `origin/main`
- Generate outside Git: final canonical build root and CI evidence
- No tracked changes

**Interfaces:**

- Consumes: Task 8's exact green PR head and separate explicit merge authority.
- Produces: the only permitted release commit and the final selected four
  artifacts built from it.

- [ ] **Step 1: Request and perform an exact-head merge**

Present the PR URL, head SHA, nine green checks, review results, and merge-commit
method. Re-read the values from the preserved state and require the head still
matches before asking. After explicit authorization, run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_pr_url="$(tr -d '\n' < "$threadroot_state_root/pr-url.txt")"
threadroot_approved_head="$(tr -d '\n' < "$threadroot_state_root/approved-pr-head.txt")"
test "$(gh pr view "$threadroot_pr_url" \
  --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" \
  = "$threadroot_approved_head"

threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
test "$(gh pr view "$threadroot_pr_url" \
  --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" \
  = "$threadroot_approved_head"
gh pr merge "$threadroot_pr_url" \
  --repo Will413028/threadroot \
  --merge \
  --match-head-commit "$threadroot_approved_head"
threadroot_restore_account
trap - EXIT
```

Do not enable auto-merge, delete the branch, use administrator bypass, or
accept a different head.

- [ ] **Step 2: Bind remote main and post-merge CI**

Fetch `origin/main` without tags, bind the merge commit, and save it with a
no-clobber write:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_pr_url="$(tr -d '\n' < "$threadroot_state_root/pr-url.txt")"
threadroot_approved_head="$(tr -d '\n' < "$threadroot_state_root/approved-pr-head.txt")"
git fetch --no-tags origin \
  refs/heads/main:refs/remotes/origin/main
threadroot_release_commit="$(gh pr view "$threadroot_pr_url" \
  --repo Will413028/threadroot \
  --json mergeCommit,state \
  --jq 'select(.state == "MERGED") | .mergeCommit.oid')"
test "$(git rev-parse refs/remotes/origin/main)" \
  = "$threadroot_release_commit"
git merge-base --is-ancestor \
  "$threadroot_approved_head" "$threadroot_release_commit"
gh run list \
  --repo Will413028/threadroot \
  --workflow ci.yml \
  --branch main \
  --commit "$threadroot_release_commit" \
  --event push \
  --limit 20 \
  --json databaseId,headSha,status,conclusion \
  > "$threadroot_state_root/main-runs.json"
threadroot_run_id="$(jq -r --arg sha "$threadroot_release_commit" \
  '[.[] | select(.headSha == $sha)][0].databaseId // empty' \
  "$threadroot_state_root/main-runs.json")"
test -n "$threadroot_run_id"
gh run watch "$threadroot_run_id" \
  --repo Will413028/threadroot --exit-status
gh run view "$threadroot_run_id" \
  --repo Will413028/threadroot \
  --json headSha,status,conclusion,jobs \
  > "$threadroot_state_root/main-ci.json"
jq -e --arg sha "$threadroot_release_commit" '
  .headSha == $sha and
  .status == "completed" and
  .conclusion == "success" and
  (.jobs | length == 9) and
  ([.jobs[] | select(.name == "release-artifacts")] | length == 1) and
  ([.jobs[] | select(.name | startswith("test ("))] | length == 8) and
  all(.jobs[]; .conclusion == "success")
' "$threadroot_state_root/main-ci.json"
git fetch --no-tags origin \
  refs/heads/main:refs/remotes/origin/main
test "$(git rev-parse refs/remotes/origin/main)" \
  = "$threadroot_release_commit"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/release-commit.txt" \
  "$threadroot_release_commit"
```

If the exact push run is not visible yet, wait and repeat only the read-only
`gh run list` query. If `main` moves, restart final verification against the new
commit rather than releasing the stale tree. Once `release-commit.txt` is
written, announce the `main` release freeze; do not begin unrelated merge or
push work until Task 12 completes or the release is abandoned.

- [ ] **Step 3: Confirm the release namespace is unused**

Under the personal GitHub account, run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
if git show-ref --verify --quiet refs/tags/v0.1.0; then
  false
fi
test -z "$(git ls-remote --tags origin \
  'refs/tags/v0.1.0' 'refs/tags/v0.1.0^{}')"
if gh api --include \
  repos/Will413028/threadroot/releases/tags/v0.1.0 \
  > "$threadroot_state_root/release-namespace-probe.txt" 2>&1; then
  false
fi
rg -q 'HTTP 404| 404 ' \
  "$threadroot_state_root/release-namespace-probe.txt"
threadroot_restore_account
trap - EXIT
```

Inspect the `gh api` failure and require a genuine not-found result;
an authentication, permission, rate-limit, or network failure is not evidence
that the namespace is unused. Any existing local/remote tag or release is a
hard stop for manual audit.

- [ ] **Step 4: Build final artifacts through the canonical entry point**

This step provisions the immutable image and requires current explicit network
authorization. After authorization, create and preserve a fresh root with:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
test "$(git rev-parse refs/remotes/origin/main)" \
  = "$threadroot_release_commit"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
threadroot_final_root="$(mktemp -d /private/tmp/threadroot-v010-final-20260905-XXXXXX)"
python3 -m scripts.build_verified_release \
  --commit "$threadroot_release_commit" \
  --output "$threadroot_final_root"
find "$threadroot_final_root/build/selected" -maxdepth 1 -type f -print | sort
test "$(find "$threadroot_final_root/build/selected" \
  -maxdepth 1 -type f | wc -l | tr -d ' ')" = "4"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/final-root.txt" \
  "$threadroot_final_root"
```

The runner-file parity check binds the locally executed wrapper to the same
bytes at the merge commit. Require exact four-file selected membership and save
the final root, release commit, `build.json`, and `SHA256SUMS` paths outside Git
without overwriting previous evidence.

---

### Task 10: Validate final install and host behavior in disposable roots

**Files:**

- Generate outside Git: disposable wheel, vault, Claude, and Codex roots
- No tracked changes

**Interfaces:**

- Consumes: Task 9's selected final artifacts.
- Produces: clean install, CLI, host package, uninstall, and no-vault-write
  evidence for those exact bytes.

- [ ] **Step 1: Recheck hashes and scanner output**

Run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
threadroot_selected="$threadroot_final_root/build/selected"
test -d "$threadroot_selected"
(
  cd "$threadroot_selected"
  shasum -a 256 \
    threadroot-0.1.0-py3-none-any.whl \
    threadroot-0.1.0.tar.gz \
    threadroot-claude-0.1.0.zip \
    threadroot-codex-0.1.0.zip | LC_ALL=C sort
) > "$threadroot_state_root/final-recomputed.SHA256SUMS"
cmp "$threadroot_state_root/final-recomputed.SHA256SUMS" \
  "$threadroot_final_root/build/evidence/SHA256SUMS"
jq -e --arg commit "$threadroot_release_commit" '
  .schema == 1 and
  .commit == $commit and
  .platform == "linux/amd64" and
  .python == "3.14.7" and
  .base_image == "python:3.14.7-slim-bookworm@sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9" and
  (.builder_definition_sha256 | test("^[0-9a-f]{64}$")) and
  (.artifacts | length == 4)
' "$threadroot_final_root/build/evidence/build.json"
python3 scripts/check_public.py \
  "$threadroot_final_root/source-a" \
  "$threadroot_final_root/source-b" \
  "$threadroot_selected" \
  "$threadroot_final_root/build/evidence/unpacked"
```

If the private denylist is available, rerun the last command with
`--denylist` and its already-approved absolute path without printing it.
Require zero findings.

- [ ] **Step 2: Install the selected wheel offline**

Create a fresh virtual environment and run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
python3 -m venv "$threadroot_final_root/wheel-smoke-venv"
"$threadroot_final_root/wheel-smoke-venv/bin/python" -m pip install \
  --no-index --no-deps --no-cache-dir --force-reinstall \
  "$threadroot_final_root/build/selected/threadroot-0.1.0-py3-none-any.whl"
"$threadroot_final_root/wheel-smoke-venv/bin/python" -m pip check
"$threadroot_final_root/wheel-smoke-venv/bin/threadroot" --version
"$threadroot_final_root/wheel-smoke-venv/bin/python" -c \
  'from importlib.metadata import requires, version; assert version("threadroot") == "0.1.0"; assert requires("threadroot") in (None, [])'
```

Expected version: exactly `threadroot 0.1.0` according to the existing CLI
contract.

- [ ] **Step 3: Run synthetic CLI smoke without touching normal state**

Run every CLI call with explicit disposable `HOME` and XDG roots:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_smoke_root="$threadroot_final_root/cli-smoke"
threadroot_smoke_home="$threadroot_smoke_root/home"
threadroot_smoke_xdg="$threadroot_smoke_root/xdg"
threadroot_smoke_vault="$threadroot_smoke_root/vault"
install -d -m 700 "$threadroot_smoke_home" "$threadroot_smoke_xdg"
printf 'unrelated sentinel\n' > "$threadroot_smoke_root/sentinel.txt"
shasum -a 256 "$threadroot_smoke_root/sentinel.txt" \
  > "$threadroot_smoke_root/sentinel.before"

HOME="$threadroot_smoke_home" XDG_CONFIG_HOME="$threadroot_smoke_xdg" \
  "$threadroot_final_root/wheel-smoke-venv/bin/threadroot" \
  init --vault "$threadroot_smoke_vault" --json \
  > "$threadroot_smoke_root/init-preview.json"
test ! -e "$threadroot_smoke_vault"
HOME="$threadroot_smoke_home" XDG_CONFIG_HOME="$threadroot_smoke_xdg" \
  "$threadroot_final_root/wheel-smoke-venv/bin/threadroot" \
  init --vault "$threadroot_smoke_vault" --json --apply \
  > "$threadroot_smoke_root/init-apply.json"
HOME="$threadroot_smoke_home" XDG_CONFIG_HOME="$threadroot_smoke_xdg" \
  "$threadroot_final_root/wheel-smoke-venv/bin/threadroot" \
  doctor --vault "$threadroot_smoke_vault" --json \
  > "$threadroot_smoke_root/doctor.json"
HOME="$threadroot_smoke_home" XDG_CONFIG_HOME="$threadroot_smoke_xdg" \
  "$threadroot_final_root/wheel-smoke-venv/bin/threadroot" \
  claim --vault "$threadroot_smoke_vault" \
  --path daily/2042-04-03.md --json \
  > "$threadroot_smoke_root/claim-preview.json"
test ! -e "$threadroot_smoke_vault/daily/2042-04-03.md"
HOME="$threadroot_smoke_home" XDG_CONFIG_HOME="$threadroot_smoke_xdg" \
  "$threadroot_final_root/wheel-smoke-venv/bin/threadroot" \
  claim --vault "$threadroot_smoke_vault" \
  --path daily/2042-04-03.md --json --apply \
  > "$threadroot_smoke_root/claim-apply.json"
test -f "$threadroot_smoke_vault/daily/2042-04-03.md"
test ! -s "$threadroot_smoke_vault/daily/2042-04-03.md"
if HOME="$threadroot_smoke_home" XDG_CONFIG_HOME="$threadroot_smoke_xdg" \
  "$threadroot_final_root/wheel-smoke-venv/bin/threadroot" \
  claim --vault "$threadroot_smoke_vault" \
  --path daily/2042-04-03.md --json --apply \
  > "$threadroot_smoke_root/claim-repeat.json"; then
  threadroot_repeat_code="0"
else
  threadroot_repeat_code="$?"
fi
test "$threadroot_repeat_code" = "5"
```

The repeat command is the only expected nonzero command; capture it without
aborting the surrounding verification shell. Validate all six JSON files with:

```bash
python3 - \
  "$threadroot_smoke_root/init-preview.json" \
  "$threadroot_smoke_root/init-apply.json" \
  "$threadroot_smoke_root/doctor.json" \
  "$threadroot_smoke_root/claim-preview.json" \
  "$threadroot_smoke_root/claim-apply.json" \
  "$threadroot_smoke_root/claim-repeat.json" <<'PY'
import json
from pathlib import Path
import sys

documents = [json.loads(Path(name).read_text(encoding="utf-8")) for name in sys.argv[1:]]
required = {"ok", "command", "applied", "vault", "changes", "issues"}
assert all(set(document) == required for document in documents)
assert [(item["command"], item["ok"], item["applied"]) for item in documents] == [
    ("init", True, False),
    ("init", True, True),
    ("doctor", True, False),
    ("claim", True, False),
    ("claim", True, True),
    ("claim", False, False),
]
assert all(not item["issues"] for item in documents[:5])
assert documents[5]["issues"][0]["code"] == "target.conflict"
PY
shasum -a 256 "$threadroot_smoke_root/sentinel.txt" \
  > "$threadroot_smoke_root/sentinel.after"
cmp "$threadroot_smoke_root/sentinel.before" \
  "$threadroot_smoke_root/sentinel.after"
test ! -e "$threadroot_smoke_home/.config/threadroot/default-vault"
test -z "$(find "$threadroot_smoke_home" -mindepth 1 -print -quit)"
test -z "$(find "$threadroot_smoke_xdg" -mindepth 1 -print -quit)"
cp -R "$threadroot_smoke_vault" "$threadroot_smoke_root/vault-pristine"
```

Require no normal host path in command arguments or JSON output. The copied
vault snapshot is the uninstall baseline; it is never an uninstall target.

- [ ] **Step 4: Validate both host packages in disposable config roots**

First require both native CLIs to be present and record only their version
strings. Create fresh bundles with Threadroot's safe extractor, not
`zipfile -e` or a host runtime extractor:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_selected="$threadroot_final_root/build/selected"
threadroot_smoke_root="$threadroot_final_root/cli-smoke"
command -v claude >/dev/null
command -v codex >/dev/null
threadroot_host_root="$threadroot_final_root/host-smoke"
threadroot_claude_bundle="$threadroot_host_root/claude-bundle"
threadroot_codex_bundle="$threadroot_host_root/codex-bundle"
threadroot_claude_home="$threadroot_host_root/claude-home"
threadroot_claude_config="$threadroot_host_root/claude-config"
threadroot_claude_cache="$threadroot_host_root/claude-cache"
threadroot_codex_home="$threadroot_host_root/codex-home"
threadroot_codex_config="$threadroot_host_root/codex-config"
threadroot_codex_data="$threadroot_host_root/codex-data"
threadroot_codex_cache="$threadroot_host_root/codex-cache"
threadroot_codex_state="$threadroot_host_root/codex-state"
threadroot_claude_tmp="$threadroot_host_root/claude-tmp"
threadroot_codex_tmp="$threadroot_host_root/codex-tmp"
install -d -m 700 \
  "$threadroot_host_root" \
  "$threadroot_claude_home" \
  "$threadroot_claude_config" \
  "$threadroot_claude_cache" \
  "$threadroot_codex_home" \
  "$threadroot_codex_config" \
  "$threadroot_codex_data" \
  "$threadroot_codex_cache" \
  "$threadroot_codex_state" \
  "$threadroot_claude_tmp" \
  "$threadroot_codex_tmp"
python3 - \
  "$threadroot_selected/threadroot-claude-0.1.0.zip" \
  "$threadroot_claude_bundle" \
  "$threadroot_selected/threadroot-codex-0.1.0.zip" \
  "$threadroot_codex_bundle" <<'PY'
from pathlib import Path
import sys

from scripts.release_archives import extract_regular_zip

extract_regular_zip(Path(sys.argv[1]), Path(sys.argv[2]))
extract_regular_zip(Path(sys.argv[3]), Path(sys.argv[4]))
PY
cp -R "$threadroot_claude_bundle" \
  "$threadroot_host_root/claude-bundle-pristine"
cp -R "$threadroot_codex_bundle" \
  "$threadroot_host_root/codex-bundle-pristine"
```

Run `claude plugin validate --strict .` from the Claude bundle. Then run local
marketplace add/install/list under `env -i`, passing only the current `PATH`,
`HOME`, `TMPDIR`, `CLAUDE_CONFIG_DIR`,
`CLAUDE_CODE_PLUGIN_CACHE_DIR`, `LC_ALL=C.UTF-8`, and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. Run the corresponding Codex
marketplace add/install/list under `env -i`, passing only `PATH`, `HOME`,
`TMPDIR`, `CODEX_HOME`, every XDG root above, and `LC_ALL=C.UTF-8`. Use these
native command forms exactly:

```bash
threadroot_claude() {
  env -i \
    PATH="$PATH" \
    HOME="$threadroot_claude_home" \
    TMPDIR="$threadroot_claude_tmp" \
    CLAUDE_CONFIG_DIR="$threadroot_claude_config" \
    CLAUDE_CODE_PLUGIN_CACHE_DIR="$threadroot_claude_cache" \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    LC_ALL=C.UTF-8 \
    claude "$@"
}
threadroot_codex() {
  env -i \
    PATH="$PATH" \
    HOME="$threadroot_codex_home" \
    TMPDIR="$threadroot_codex_tmp" \
    CODEX_HOME="$threadroot_codex_config" \
    XDG_CONFIG_HOME="$threadroot_codex_config" \
    XDG_DATA_HOME="$threadroot_codex_data" \
    XDG_CACHE_HOME="$threadroot_codex_cache" \
    XDG_STATE_HOME="$threadroot_codex_state" \
    LC_ALL=C.UTF-8 \
    codex "$@"
}
threadroot_claude --version \
  > "$threadroot_smoke_root/claude-version.txt"
threadroot_codex --version \
  > "$threadroot_smoke_root/codex-version.txt"
(
  cd "$threadroot_claude_bundle"
  threadroot_claude plugin validate --strict .
)
threadroot_claude plugin marketplace add \
  "$threadroot_claude_bundle" --scope user
threadroot_claude plugin install threadroot@threadroot --scope user
threadroot_claude plugin list --json \
  > "$threadroot_host_root/claude-list-installed.json"
threadroot_codex plugin marketplace add \
  "$threadroot_codex_bundle" --json
threadroot_codex plugin add threadroot@threadroot --json
threadroot_codex plugin list --json \
  > "$threadroot_host_root/codex-list-installed.json"
```

Require each list result to report the installed
`threadroot@threadroot` package. Do not launch a model. Compare
`final-recomputed.SHA256SUMS`, `vault-pristine`, and the sentinel before and
after. All expected host writes must remain below `host-smoke/`; any normal
host-state drift is a failure. If either installed host/version cannot
guarantee offline disposable operation, mark that native gate unexecuted and
keep publication blocked rather than weakening isolation.

- [ ] **Step 5: Verify disposable uninstall preserves user data**

Uninstall `threadroot` only from the fresh wheel virtual environment and remove
only the disposable host registrations created in Step 4 through these native
forms under the identical isolated environments:

If this step runs in a new shell, reload `threadroot_final_root`,
`threadroot_smoke_root`, and every `threadroot_host_*` path from Step 4 and
redeclare the exact `threadroot_claude` and `threadroot_codex` functions before
running:

```bash
"$threadroot_final_root/wheel-smoke-venv/bin/python" \
  -m pip uninstall -y threadroot
threadroot_claude plugin remove threadroot@threadroot --scope user
threadroot_claude plugin marketplace remove threadroot --scope user
threadroot_codex plugin remove threadroot@threadroot --json
threadroot_codex plugin marketplace remove threadroot --json
threadroot_claude plugin list --json \
  > "$threadroot_host_root/claude-list-removed.json"
threadroot_codex plugin list --json \
  > "$threadroot_host_root/codex-list-removed.json"
if "$threadroot_final_root/wheel-smoke-venv/bin/python" \
  -c 'import threadroot'; then
  false
fi
if test -e "$threadroot_final_root/wheel-smoke-venv/bin/threadroot"; then
  false
fi
diff -qr "$threadroot_smoke_root/vault-pristine" \
  "$threadroot_smoke_vault"
diff -qr "$threadroot_host_root/claude-bundle-pristine" \
  "$threadroot_claude_bundle"
diff -qr "$threadroot_host_root/codex-bundle-pristine" \
  "$threadroot_codex_bundle"
shasum -a 256 "$threadroot_smoke_root/sentinel.txt" \
  > "$threadroot_smoke_root/sentinel.after-uninstall"
cmp "$threadroot_smoke_root/sentinel.before" \
  "$threadroot_smoke_root/sentinel.after-uninstall"
```

Require the wheel import and executable to be absent and the two native list
commands to contain no installed Threadroot entry. Run `diff -qr` from
`vault-pristine` to the synthetic vault and compare the sentinel and selected
artifact checksums again. Do not delete the evidence root or use a vault as an
uninstall target.

Fresh model runs and another private-vault dogfood cycle remain outside this
task and require separate authorization; report them as unexecuted for the new
artifacts unless separately approved.

---

### Task 11: Create the immutable tag and verified draft release

**Files:**

- External state: annotated `v0.1.0` tag
- External state: draft GitHub Release with four assets
- Generate outside Git: downloaded draft verification copies

**Interfaces:**

- Consumes: exact release commit, nine green main checks, Task 10 evidence, and
  separate explicit tag authorization followed by separate draft
  authorization.
- Produces: an unpublished draft whose metadata and downloaded bytes match the
  selected set.

- [ ] **Step 1: Present the irreversible boundary and request tag authorization**

Present the exact commit, four filenames/hashes, main CI result, final gates,
release-note path, and confirmation that no tag/release currently exists. Ask
only for explicit authorization to create and push the annotated tag. Do not
infer draft or publication authorization from tag authorization. Reconfirm
that the Task 9 `main` release freeze is still in force.

- [ ] **Step 2: Create and push only the annotated release tag**

After authorization, run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
git fetch --no-tags origin \
  refs/heads/main:refs/remotes/origin/main
test "$(git config --local --get user.name)" = "Will"
test "$(git config --local --get user.email)" = "will413028@gmail.com"
test "$(git rev-parse refs/remotes/origin/main)" \
  = "$threadroot_release_commit"
if git show-ref --verify --quiet refs/tags/v0.1.0; then
  false
fi
test -z "$(git ls-remote --tags origin \
  'refs/tags/v0.1.0' 'refs/tags/v0.1.0^{}')"
git tag --annotate v0.1.0 "$threadroot_release_commit" \
  --message "Threadroot v0.1.0"
test "$(git rev-parse 'refs/tags/v0.1.0^{}')" \
  = "$threadroot_release_commit"

threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
test "$(git remote get-url origin)" \
  = "https://github.com/Will413028/threadroot.git"
git push origin refs/tags/v0.1.0:refs/tags/v0.1.0
threadroot_remote_peeled="$(git ls-remote --tags origin \
  'refs/tags/v0.1.0^{}' | awk '{print $1}')"
test "$threadroot_remote_peeled" = "$threadroot_release_commit"
threadroot_restore_account
trap - EXIT
```

Never force or retarget the tag. A partial failure leaves the local or remote
tag visible for manual audit; do not delete it automatically.

- [ ] **Step 3: Revalidate and request separate draft authorization**

Re-fetch `main`, recheck the peeled local and remote tag, final checksums, and
release-note blob against the saved release commit. Present that evidence and
ask only for authorization to create the unpublished draft. After
authorization, run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_selected="$threadroot_final_root/build/selected"
git fetch --no-tags origin \
  refs/heads/main:refs/remotes/origin/main
test "$(git rev-parse refs/remotes/origin/main)" \
  = "$threadroot_release_commit"
test "$(git rev-parse 'refs/tags/v0.1.0^{}')" \
  = "$threadroot_release_commit"
test "$(git hash-object docs/releases/v0.1.0.md)" \
  = "$(git rev-parse "$threadroot_release_commit:docs/releases/v0.1.0.md")"
cmp "$threadroot_state_root/final-recomputed.SHA256SUMS" \
  "$threadroot_final_root/build/evidence/SHA256SUMS"

threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
threadroot_draft_url="$(gh release create v0.1.0 \
  --repo Will413028/threadroot \
  --title "Threadroot v0.1.0" \
  --draft \
  --verify-tag \
  --notes-file docs/releases/v0.1.0.md \
  "$threadroot_selected/threadroot-0.1.0-py3-none-any.whl" \
  "$threadroot_selected/threadroot-0.1.0.tar.gz" \
  "$threadroot_selected/threadroot-claude-0.1.0.zip" \
  "$threadroot_selected/threadroot-codex-0.1.0.zip")"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/draft-url.txt" \
  "$threadroot_draft_url"
threadroot_restore_account
trap - EXIT
```

Do not use `--latest`, `--prerelease`, generated notes, wildcards, or
`--clobber`. Draft authorization is not publication authorization.

- [ ] **Step 4: Download and verify the unpublished draft**

Switch to `Will413028` with the same restore trap, then run:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
threadroot_selected="$threadroot_final_root/build/selected"
threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
test "$(git rev-parse 'refs/tags/v0.1.0^{}')" \
  = "$threadroot_release_commit"
test "$(git ls-remote --tags origin \
  'refs/tags/v0.1.0^{}' | awk '{print $1}')" \
  = "$threadroot_release_commit"
threadroot_draft_download="$(mktemp -d /private/tmp/threadroot-v010-draft-download-20260905-XXXXXX)"
gh release view v0.1.0 \
  --repo Will413028/threadroot \
  --json assets,body,isDraft,isPrerelease,name,tagName,url \
  > "$threadroot_state_root/draft-before.json"
python3 -c 'from pathlib import Path; import json,sys; data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); Path(sys.argv[2]).write_text(data["body"], encoding="utf-8")' \
  "$threadroot_state_root/draft-before.json" \
  "$threadroot_state_root/draft-body.md"
cmp "$threadroot_state_root/draft-body.md" docs/releases/v0.1.0.md
jq -e '
  .tagName == "v0.1.0" and
  .name == "Threadroot v0.1.0" and
  .isDraft == true and
  .isPrerelease == false and
  ([.assets[].name] | sort) == [
    "threadroot-0.1.0-py3-none-any.whl",
    "threadroot-0.1.0.tar.gz",
    "threadroot-claude-0.1.0.zip",
    "threadroot-codex-0.1.0.zip"
  ]
' "$threadroot_state_root/draft-before.json"
python3 - \
  "$threadroot_state_root/draft-before.json" \
  "$threadroot_selected" <<'PY'
import json
from pathlib import Path
import sys

release = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
selected = Path(sys.argv[2])
actual = {item["name"]: item["size"] for item in release["assets"]}
expected = {path.name: path.stat().st_size for path in selected.iterdir()}
assert actual == expected
PY
for threadroot_asset in \
  threadroot-0.1.0-py3-none-any.whl \
  threadroot-0.1.0.tar.gz \
  threadroot-claude-0.1.0.zip \
  threadroot-codex-0.1.0.zip; do
  gh release download v0.1.0 \
    --repo Will413028/threadroot \
    --pattern "$threadroot_asset" \
    --dir "$threadroot_draft_download"
  cmp "$threadroot_selected/$threadroot_asset" \
    "$threadroot_draft_download/$threadroot_asset"
done
gh release view v0.1.0 \
  --repo Will413028/threadroot \
  --json assets,body,isDraft,isPrerelease,name,tagName,url \
  > "$threadroot_state_root/draft-after.json"
jq -S '{assets: ([.assets[] | {name, size}] | sort_by(.name)), body, isDraft, isPrerelease, name, tagName, url}' \
  "$threadroot_state_root/draft-before.json" \
  > "$threadroot_state_root/draft-before-contract.json"
jq -S '{assets: ([.assets[] | {name, size}] | sort_by(.name)), body, isDraft, isPrerelease, name, tagName, url}' \
  "$threadroot_state_root/draft-after.json" \
  > "$threadroot_state_root/draft-after-contract.json"
cmp "$threadroot_state_root/draft-before-contract.json" \
  "$threadroot_state_root/draft-after-contract.json"
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/draft-download-root.txt" \
  "$threadroot_draft_download"
threadroot_restore_account
trap - EXIT
```

Also require every API-reported size to equal its selected local file and the
local/remote peeled tag to equal the saved commit. Leave the draft unpublished
on any mismatch.

---

### Task 12: Publish exact bytes and close release readiness

**Files:**

- External state: public GitHub Release `v0.1.0`
- Generate outside Git: unauthenticated public downloads and final evidence
- No tracked changes

**Interfaces:**

- Consumes: Task 11's unchanged verified draft and separate explicit publish
  authorization.
- Produces: public release plus immediate unauthenticated verification and an
  open telemetry-free adoption gate.

- [ ] **Step 1: Request final publication authorization**

Present the draft URL, exact target, body, four names/hashes, draft-download
verification, and current `origin/main`. Ask separately for permission to
publish it as the repository's latest release. If main moved or any draft byte
changed, stop. Because the immutable tag now exists, never retarget it; a moved
`main` requires an explicit release-version/design decision rather than an
automatic return to Task 9.

- [ ] **Step 2: Publish without rebuilding or replacing anything**

After authorization, revalidate remote main, the peeled tag, draft metadata,
downloaded hashes, and final source commit, then publish with one mutation:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_draft_download="$(tr -d '\n' < "$threadroot_state_root/draft-download-root.txt")"
threadroot_selected="$threadroot_final_root/build/selected"
git fetch --no-tags origin \
  refs/heads/main:refs/remotes/origin/main
test "$(git rev-parse refs/remotes/origin/main)" \
  = "$threadroot_release_commit"
test "$(git rev-parse 'refs/tags/v0.1.0^{}')" \
  = "$threadroot_release_commit"
test "$(git ls-remote --tags origin \
  'refs/tags/v0.1.0^{}' | awk '{print $1}')" \
  = "$threadroot_release_commit"
for threadroot_asset in \
  threadroot-0.1.0-py3-none-any.whl \
  threadroot-0.1.0.tar.gz \
  threadroot-claude-0.1.0.zip \
  threadroot-codex-0.1.0.zip; do
  cmp "$threadroot_selected/$threadroot_asset" \
    "$threadroot_draft_download/$threadroot_asset"
done

threadroot_previous_account="$(gh api user --jq .login)"
threadroot_restore_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_account"
}
trap threadroot_restore_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh api user --jq .login)" = "Will413028"
gh release view v0.1.0 \
  --repo Will413028/threadroot \
  --json assets,body,isDraft,isPrerelease,name,tagName,url \
  > "$threadroot_state_root/draft-prepublish.json"
jq -S '{assets: ([.assets[] | {name, size}] | sort_by(.name)), body, isDraft, isPrerelease, name, tagName, url}' \
  "$threadroot_state_root/draft-prepublish.json" \
  > "$threadroot_state_root/draft-prepublish-contract.json"
cmp "$threadroot_state_root/draft-after-contract.json" \
  "$threadroot_state_root/draft-prepublish-contract.json"
gh release edit v0.1.0 \
  --repo Will413028/threadroot \
  --draft=false \
  --latest
threadroot_restore_account
trap - EXIT
```

Do not upload, rebuild, replace, or retarget during this step.

- [ ] **Step 3: Verify unauthenticated public downloads**

Use only unauthenticated `curl` calls with user configuration disabled:

```bash
threadroot_state_root="/private/tmp/threadroot-v010-release-state-20260905"
threadroot_release_commit="$(tr -d '\n' < "$threadroot_state_root/release-commit.txt")"
threadroot_final_root="$(tr -d '\n' < "$threadroot_state_root/final-root.txt")"
threadroot_selected="$threadroot_final_root/build/selected"
threadroot_public_download="$(mktemp -d /private/tmp/threadroot-v010-public-download-20260905-XXXXXX)"
curl --disable --fail --silent --show-error --location \
  --header 'Accept: application/vnd.github+json' \
  --header 'X-GitHub-Api-Version: 2022-11-28' \
  https://api.github.com/repos/Will413028/threadroot/releases/tags/v0.1.0 \
  --output "$threadroot_public_download/release.json"
jq -e '
  .tag_name == "v0.1.0" and
  .name == "Threadroot v0.1.0" and
  .draft == false and
  .prerelease == false and
  ([.assets[].name] | sort) == [
    "threadroot-0.1.0-py3-none-any.whl",
    "threadroot-0.1.0.tar.gz",
    "threadroot-claude-0.1.0.zip",
    "threadroot-codex-0.1.0.zip"
  ]
' "$threadroot_public_download/release.json"
python3 - \
  "$threadroot_public_download/release.json" \
  docs/releases/v0.1.0.md \
  "$threadroot_selected" <<'PY'
import json
from pathlib import Path
import sys

release = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
notes = Path(sys.argv[2]).read_text(encoding="utf-8")
selected = Path(sys.argv[3])
assert release["body"] == notes
actual = {item["name"]: item["size"] for item in release["assets"]}
expected = {path.name: path.stat().st_size for path in selected.iterdir()}
assert actual == expected
PY
for threadroot_asset in \
  threadroot-0.1.0-py3-none-any.whl \
  threadroot-0.1.0.tar.gz \
  threadroot-claude-0.1.0.zip \
  threadroot-codex-0.1.0.zip; do
  threadroot_asset_url="$(jq -r --arg name "$threadroot_asset" \
    '.assets[] | select(.name == $name) | .browser_download_url' \
    "$threadroot_public_download/release.json")"
  case "$threadroot_asset_url" in
    https://github.com/Will413028/threadroot/releases/download/v0.1.0/*) ;;
    *) false ;;
  esac
  curl --disable --fail --silent --show-error --location \
    "$threadroot_asset_url" \
    --output "$threadroot_public_download/$threadroot_asset"
  cmp "$threadroot_selected/$threadroot_asset" \
    "$threadroot_public_download/$threadroot_asset"
done
python3 scripts/check_public.py "$threadroot_public_download"
python3 - \
  "$threadroot_public_download" \
  "$threadroot_final_root/source-a" \
  "$threadroot_final_root/build/evidence/build.json" <<'PY'
import json
from pathlib import Path
import sys

from scripts.release_archives import (
    validate_host_zip,
    validate_sdist,
    validate_wheel,
)

artifacts = Path(sys.argv[1])
source = Path(sys.argv[2])
evidence = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
epoch = evidence["source_date_epoch"]
validate_wheel(
    artifacts / "threadroot-0.1.0-py3-none-any.whl",
    source,
    "0.1.0",
    epoch,
)
validate_sdist(
    artifacts / "threadroot-0.1.0.tar.gz",
    source,
    "0.1.0",
    epoch,
)
validate_host_zip(
    artifacts / "threadroot-claude-0.1.0.zip",
    source,
    "claude",
)
validate_host_zip(
    artifacts / "threadroot-codex-0.1.0.zip",
    source,
    "codex",
)
PY
```

Install the public wheel with
`--no-index --no-deps --no-cache-dir` in a new virtual environment and rerun
the exact version, `init`, `doctor`, `claim`, host add/install/list/remove, and
uninstall assertions from Task 10 in new disposable roots. No model call or
normal host configuration is permitted. Byte identity with `selected/`
transfers the already-passed canonical sdist-to-wheel replay proof; do not
rebuild or mutate a release asset after publication.

Finally fetch the public JSON again without authentication and require the same
tag, title, body, four names/sizes, `draft == false`, and
`prerelease == false`. Require the local and remote peeled tag to remain the
saved release commit. Only after every post-publication gate passes, bind the
successful public evidence root with:

```bash
python3 -c 'from pathlib import Path; import sys; stream=Path(sys.argv[1]).open("x", encoding="utf-8"); stream.write(sys.argv[2] + "\n"); stream.close()' \
  "$threadroot_state_root/public-download-root.txt" \
  "$threadroot_public_download"
```

- [ ] **Step 4: Report completion and the still-open adoption gate**

Report the release URL, exact commit, four hashes, nine-job CI result, canonical
environment identity, and every executed/unexecuted gate. State explicitly
that no PyPI upload, plugin-directory submission, release automation,
attestation, fresh model run, telemetry, or unapproved private-vault operation
occurred. Preserve the branch, worktree, candidates, and evidence; cleanup is a
separate exact-target authorization. The three-to-five-developer adoption gate
from the approved spec remains open after publication.

## Completion criteria

- Hatchling is the only Python build backend and `MANIFEST.in` is absent.
- The build environment is digest-pinned, hash-locked, auditable, and offline
  during artifact creation.
- Local/CI use one entry point and CI has eight compatibility jobs plus one
  canonical reproducibility job.
- Two independent exports of the exact release commit produce byte-identical
  wheel, sdist, Claude ZIP, and Codex ZIP files.
- The selected sdist reproduces the selected wheel offline, and archive,
  membership, install, host isolation, privacy, and uninstall gates pass.
- Only the selected, unchanged four files are attached to the immutable
  `v0.1.0` release.
- The annotated tag peels to the saved green merge commit, unauthenticated
  redownloads match every selected byte, and the `main` release freeze is then
  lifted.
- No PyPI upload, marketplace submission, model run, or unapproved
  private-vault operation occurs.
- No superseded Setuptools release command is used after this plan is approved.
