# Threadroot v0.1.0 Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Publish Threadroot v0.1.0 as the first verified GitHub Release from the exact reviewed remote main commit.

**Architecture:** Keep product behavior unchanged and make only public metadata, release-note, and regression-test edits on the existing release-readiness branch. Build two byte-compared artifact sets with one pinned disposable toolchain, then install and validate the selected four assets in isolated environments before creating an immutable tag and draft release. Publish only after a separate human gate, and immediately repeat clean-install checks against unauthenticated public downloads.

**Tech Stack:** Python 3.11-3.14, standard-library unittest, setuptools build backend, PyPA build, Claude Code and Codex plugin CLIs, Git, GitHub Actions, GitHub CLI, curl, jq, shasum.

**Spec:** docs/superpowers/specs/2026-09-05-threadroot-v0.1.0-release-readiness-design.md

## Global Constraints

- The release version remains exactly 0.1.0 in the Python package, Claude manifest, Codex manifest, and marketplace catalog.
- Runtime dependencies remain empty; do not change CLI behavior, vault schema, skills, host manifests, or scripts/build_release.py.
- Public documentation is English and names https://github.com/Will413028/threadroot.
- The release has exactly four assets:
  - threadroot-0.1.0-py3-none-any.whl
  - threadroot-0.1.0.tar.gz
  - threadroot-claude-0.1.0.zip
  - threadroot-codex-0.1.0.zip
- Do not publish to PyPI or submit to an OpenAI or Claude plugin directory.
- Do not launch a fresh model run or touch a private vault without separate explicit authorization. Report those gates as unexecuted.
- Do not install missing interpreters or build dependencies from the network without first showing the exact packages and obtaining explicit authorization.
- All vault smoke tests use newly created synthetic temporary roots. Every host config, cache, HOME, and XDG root used by validation is disposable and isolated from normal host state.
- Never print, copy, or commit a maintainer denylist, credential, private path, private fixture, model transcript, or vault content.
- Preserve unrelated work. Stage exact paths only, and never use stash, hard reset, clean, broad staging, verification bypasses, or force-push.
- Push, pull-request creation, merge, tag push, draft creation, and publication are separate external mutations. Stop for explicit authorization at the gates named below.
- The personal GitHub operation account is Will413028. Capture the active account before each account switch and restore it after the bounded operation.
- A published v0.1.0 tag or asset is never deleted, retargeted, overwritten, or silently replaced. A discovered post-publication defect starts a v0.1.1 correction.
- Every Bash fence starts a fresh Bash process with `set -euo pipefail`; execute the whole fence directly, never source it or place it inside an `if`, `!`, or `&&`/`||` condition. Expected failures are guarded inside that process. An unsuccessful guard or pipeline stops before later operations, and EXIT traps restore the GitHub account on failure.
- Tasks 6-8 persist approved PR, merge, and successful CI SHAs outside Git under /private/tmp/threadroot-v010-candidate-20260905. Never replace these values with a newly observed head. Any PR-head drift returns to Task 4 review and Tasks 5-6 verification/CI; any main drift returns to review of the changed commits, Task 7 CI and explicit release-target approval, then Tasks 8-9 verification in newly approved fixed paths. Preserve the previous evidence and do not publish until the full chain is approved again.

## File Map

- Modify README.md: replace the owner placeholder with executable public repository installation commands.
- Modify pyproject.toml: publish canonical homepage, repository, and issue-tracker metadata.
- Modify tests/test_documentation.py: lock the README commands and release-note distribution contract.
- Modify tests/test_packaging.py: lock the Python project URL mapping and empty runtime dependency set.
- Create docs/releases/v0.1.0.md: source-controlled GitHub Release notes.
- Do not modify runtime files, manifests, the release builder, CI, or the nine skill bodies unless a verified failure proves the approved design cannot be completed; stop for a design amendment before such a change.
- Generated build outputs, hashes, extracted bundles, and host state remain outside Git.

---

### Task 1: Replace the repository placeholder with live installation commands

**Files:**

- Modify: tests/test_documentation.py:208-257
- Modify: README.md:74-86

**Interfaces:**

- Consumes: the existing _section(markdown, heading) test helper.
- Produces: one README section named Install from the Git repository with exact clone, Claude marketplace, and Codex marketplace commands.

- [ ] **Step 1: Reconfirm the isolated branch and baseline**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git status --short --branch
git branch --show-current
git fetch --no-tags origin main
git merge-base --is-ancestor origin/main HEAD
PYTHONPATH=src:. python3 -m unittest tests.test_documentation -v
THREADROOT_BASH
~~~

Expected: the branch is release/v0.1.0-readiness, tracked state is clean, origin/main is an ancestor of HEAD, and the documentation tests pass. If origin/main is not an ancestor, stop instead of rewriting the branch.

- [ ] **Step 2: Add the failing README repository-install test**

Add this method to DocumentationTests immediately before test_readme_release_artifacts_match_real_builder_outputs:

~~~python
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
~~~

- [ ] **Step 3: Run the focused test and verify RED**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
if PYTHONPATH=src:. python3 -m unittest tests.test_documentation.DocumentationTests.test_readme_repository_install_uses_live_public_remote -v; then
  exit 1
else
  test "$?" -eq 1
fi
THREADROOT_BASH
~~~

Expected: FAIL with missing section: Install from the Git repository. A pass means the baseline or test is wrong; investigate before editing README.

- [ ] **Step 4: Replace the README section**

Replace README.md lines 74-86 with exactly:

~~~~markdown
## Install from the Git repository

Clone the public repository for the CLI, or add the same repository directly as a host marketplace:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git clone https://github.com/Will413028/threadroot.git
cd threadroot
python -m pip install .
claude plugin marketplace add Will413028/threadroot --scope user
codex plugin marketplace add Will413028/threadroot
THREADROOT_BASH
~~~

Install threadroot@threadroot with the relevant host after adding the repository marketplace.
~~~~

- [ ] **Step 5: Run focused and documentation GREEN**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
PYTHONPATH=src:. python3 -m unittest tests.test_documentation.DocumentationTests.test_readme_repository_install_uses_live_public_remote -v
PYTHONPATH=src:. python3 -m unittest tests.test_documentation -v
python3 scripts/check_public.py README.md tests/test_documentation.py
git diff --check
THREADROOT_BASH
~~~

Expected: all commands exit 0, and no OWNER/threadroot text remains in README.md.

- [ ] **Step 6: Commit the exact files**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git add -- README.md tests/test_documentation.py
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: use live Threadroot repository URLs"
THREADROOT_BASH
~~~

Expected: the staged list contains exactly README.md and tests/test_documentation.py.

---

### Task 2: Add canonical Python project URLs

**Files:**

- Modify: tests/test_packaging.py:14-108
- Modify: pyproject.toml:5-16

**Interfaces:**

- Consumes: Python 3.11+ tomllib and the existing parsed project table.
- Produces: project.urls with exact Homepage, Repository, and Issues keys.

- [ ] **Step 1: Add the failing metadata contract**

Add this constant before EXPECTED_CLAUDE_MANIFEST:

~~~python
EXPECTED_PROJECT_URLS = {
    "Homepage": "https://github.com/Will413028/threadroot",
    "Repository": "https://github.com/Will413028/threadroot",
    "Issues": "https://github.com/Will413028/threadroot/issues",
}
~~~

Add this method immediately after test_version_matches_python_package_metadata:

~~~python
    def test_project_urls_match_public_repository(self) -> None:
        project = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )["project"]

        self.assertEqual(project["urls"], EXPECTED_PROJECT_URLS)
        self.assertEqual(project["dependencies"], [])
~~~

- [ ] **Step 2: Run the focused test and verify RED**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
if PYTHONPATH=src:. python3 -m unittest tests.test_packaging.ManifestTests.test_project_urls_match_public_repository -v; then
  exit 1
else
  test "$?" -eq 1
fi
THREADROOT_BASH
~~~

Expected: ERROR or FAIL because project.urls is absent.

- [ ] **Step 3: Add the exact project URL table**

Insert this block after dependencies = [] and before project.scripts:

~~~toml
[project.urls]
Homepage = "https://github.com/Will413028/threadroot"
Repository = "https://github.com/Will413028/threadroot"
Issues = "https://github.com/Will413028/threadroot/issues"
~~~

- [ ] **Step 4: Run focused and packaging GREEN**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
PYTHONPATH=src:. python3 -m unittest tests.test_packaging.ManifestTests.test_project_urls_match_public_repository -v
PYTHONPATH=src:. python3 -m unittest tests.test_packaging -v
python3 scripts/check_public.py pyproject.toml tests/test_packaging.py
git diff --check
THREADROOT_BASH
~~~

Expected: all commands exit 0; versions and manifests remain unchanged.

- [ ] **Step 5: Commit the exact files**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git add -- pyproject.toml tests/test_packaging.py
git diff --cached --name-only
git diff --cached --check
git commit -m "build: add canonical project URLs"
THREADROOT_BASH
~~~

Expected: the staged list contains exactly pyproject.toml and tests/test_packaging.py.

---

### Task 3: Add reviewable v0.1.0 release notes

**Files:**

- Modify: tests/test_documentation.py:13-18 and after the README release-artifact test
- Create: docs/releases/v0.1.0.md

**Interfaces:**

- Consumes: the four approved artifact names and the support, ownership, privacy, installation-layer, and pre-1.0 boundaries from the design.
- Produces: docs/releases/v0.1.0.md, used verbatim as the GitHub Release body.

- [ ] **Step 1: Add the failing release-note contract**

Add these constants above PUBLIC_DOCUMENTS and include RELEASE_NOTES as the final PUBLIC_DOCUMENTS entry:

~~~python
RELEASE_NOTES = Path("docs/releases/v0.1.0.md")
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
~~~

Add this method immediately after test_readme_release_artifacts_match_real_builder_outputs:

~~~python
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
~~~

- [ ] **Step 2: Run the focused test and verify RED**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
if PYTHONPATH=src:. python3 -m unittest tests.test_documentation.DocumentationTests.test_v010_release_notes_match_distribution_contract -v; then
  exit 1
else
  test "$?" -eq 1
fi
THREADROOT_BASH
~~~

Expected: ERROR with FileNotFoundError for docs/releases/v0.1.0.md.

- [ ] **Step 3: Create the exact release notes**

Create docs/releases/v0.1.0.md with:

~~~markdown
# Threadroot v0.1.0

Threadroot v0.1.0 is the first public release of a local-first second-brain toolkit for developers who work with coding agents.

## Install both layers

A complete installation needs both layers:

- threadroot-0.1.0-py3-none-any.whl installs the deterministic CLI.
- threadroot-claude-0.1.0.zip or threadroot-codex-0.1.0.zip installs the nine portable Agent Skills for the selected host.

The source distribution is threadroot-0.1.0.tar.gz. Install the wheel and one host ZIP for the standard complete workflow.

## Supported systems

Threadroot supports Python 3.11 through 3.14 on macOS and Linux.

## Ownership and safety

Threadroot is local-first and has no telemetry. It makes no runtime network requests, keeps user data in a user-owned Markdown and Git vault, and leaves your Markdown and Git vault intact when uninstalled.

## Release boundaries

The public interfaces are pre-1.0 and may evolve through reviewed releases. PyPI and OpenAI universal Plugins Directory installation are not available in this release.

Report defects through [GitHub Issues](https://github.com/Will413028/threadroot/issues) without attaching private vault content.
~~~

- [ ] **Step 4: Run focused and documentation GREEN**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
PYTHONPATH=src:. python3 -m unittest tests.test_documentation.DocumentationTests.test_v010_release_notes_match_distribution_contract -v
PYTHONPATH=src:. python3 -m unittest tests.test_documentation -v
python3 scripts/check_public.py docs/releases/v0.1.0.md tests/test_documentation.py
git diff --check
THREADROOT_BASH
~~~

Expected: all commands exit 0. The release notes contain exactly the four approved artifact filenames.

- [ ] **Step 5: Commit the exact files**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git add -- docs/releases/v0.1.0.md tests/test_documentation.py
git diff --cached --name-only
git diff --cached --check
git commit -m "docs: add v0.1.0 release notes"
THREADROOT_BASH
~~~

Expected: the staged list contains exactly docs/releases/v0.1.0.md and tests/test_documentation.py.

---

### Task 4: Complete local regression and attribution review

**Files:**

- Inspect only: all tracked public files
- No planned file changes

**Interfaces:**

- Consumes: Tasks 1-3 and the existing public scanner.
- Produces: a clean local readiness result and an attribution conclusion for the PR body.

- [ ] **Step 1: Run every locally installed supported interpreter**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
for threadroot_python in python3.11 python3.12 python3.13 python3.14; do
  command -v "$threadroot_python" >/dev/null || exit 1
  PYTHONPATH=src:. "$threadroot_python" -m unittest discover -s tests -v || exit 1
  "$threadroot_python" -m compileall -q src scripts tests || exit 1
done
THREADROOT_BASH
~~~

Expected: all four interpreters exist and all four 252-test suites and compileall runs pass. Do not install a missing interpreter.

- [ ] **Step 2: Run repository safety and diff checks**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
python3 scripts/check_public.py .
git diff --check origin/main...HEAD
git status --short --branch
git log --oneline --decorate origin/main..HEAD
THREADROOT_BASH
~~~

Expected: the public scan and diff check exit 0, and tracked state is clean.

- [ ] **Step 3: Audit bundled material and dependency metadata**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
python3 -c 'import pathlib,tomllib; project=tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]; assert project["dependencies"] == []'
git ls-files '*.png' '*.jpg' '*.jpeg' '*.gif' '*.webp' '*.pdf' '*.woff' '*.woff2' '*.ttf' '*.otf' '*.wasm' '*.so' '*.dylib' '*.dll'
git grep -nEi 'copyright|license|SPDX|third[- ]party|vend(or|ored)' -- ':!LICENSE' ':!docs/superpowers/**' || test "$?" -eq 1
git ls-files | LC_ALL=C sort
THREADROOT_BASH
~~~

Expected: runtime dependencies are empty, the bundled-binary query is empty, and every remaining attribution-related match is project-owned prose or metadata. Manually inspect the tracked inventory and the host archive roots in scripts/build_release.py. If any copied or bundled third-party material carries a notice obligation, stop and add the required notice through a separately reviewed task; otherwise record “No bundled third-party notice obligation found” and do not create NOTICE.

- [ ] **Step 4: Request a final branch review**

Invoke superpowers:requesting-code-review for origin/main..HEAD. Require the reviewer to check the approved spec, command executability, package metadata, release-note accuracy, private-data boundaries, and absence of runtime or manifest changes.

Expected: no unresolved Critical or Important finding. Apply any valid finding through the relevant task's RED/GREEN loop and exact-path commit, then rerun Steps 1-3.

---

### Task 5: Prove candidate artifact reproducibility with a pinned toolchain

**Files:**

- Generate outside Git: /private/tmp/threadroot-v010-toolchain-20260905
- Generate outside Git: /private/tmp/threadroot-v010-candidate-20260905
- No tracked file changes

**Interfaces:**

- Consumes: the reviewed readiness branch and SOURCE_DATE_EPOCH from its commit timestamp.
- Produces: two byte-identical candidate sets and early proof that packaging metadata and source inclusion are correct.

- [ ] **Step 1: Confirm the build dependency gap without changing the machine**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
if python3.14 -m build --version; then
  printf '%s\n' 'Build is installed; record versions and use the pinned toolchain below.'
else
  test "$?" -eq 1
  printf '%s\n' 'Confirm the error is No module named build before continuing.'
fi
THREADROOT_BASH
~~~

Expected at plan-writing time: nonzero with No module named build. If the command now succeeds, record the installed versions and still use an isolated pinned toolchain below.

- [ ] **Step 2: Obtain explicit authorization for the exact network install**

Present this exact disposable install for approval:

~~~text
Target: /private/tmp/threadroot-v010-toolchain-20260905/venv
Packages: pip==26.2.1, build==1.6.0, setuptools==84.0.0, wheel==0.48.0, packaging==26.3, pyproject-hooks==1.2.0
Purpose: build two candidate sets and the final v0.1.0 artifacts with --no-isolation
Repository changes: none
~~~

Expected: explicit approval before running pip. A refusal blocks local artifact construction but does not authorize changing CI or downloading artifacts from another source.

- [ ] **Step 3: Create and verify the disposable pinned toolchain**

After approval, run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
test ! -e /private/tmp/threadroot-v010-toolchain-20260905
mkdir /private/tmp/threadroot-v010-toolchain-20260905
python3.14 -m venv /private/tmp/threadroot-v010-toolchain-20260905/venv
/private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -m pip install --disable-pip-version-check --no-input pip==26.2.1 build==1.6.0 setuptools==84.0.0 wheel==0.48.0 packaging==26.3 pyproject-hooks==1.2.0
/private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -c 'from importlib.metadata import version; expected={"pip":"26.2.1","build":"1.6.0","setuptools":"84.0.0","wheel":"0.48.0","packaging":"26.3","pyproject-hooks":"1.2.0"}; assert {name:version(name) for name in expected} == expected'
THREADROOT_BASH
~~~

Expected: the exact package-version assertion passes. Do not reuse an existing path or broaden package versions.

- [ ] **Step 4: Build two candidate sets**

Run from the readiness worktree root:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
test ! -e /private/tmp/threadroot-v010-candidate-20260905
mkdir /private/tmp/threadroot-v010-candidate-20260905
mkdir /private/tmp/threadroot-v010-candidate-20260905/a
mkdir /private/tmp/threadroot-v010-candidate-20260905/b
threadroot_candidate_epoch="$(git show -s --format=%ct HEAD)"
for threadroot_candidate_output in /private/tmp/threadroot-v010-candidate-20260905/a /private/tmp/threadroot-v010-candidate-20260905/b; do
  SOURCE_DATE_EPOCH="$threadroot_candidate_epoch" /private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -m build --no-isolation --outdir "$threadroot_candidate_output" .
  /private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python scripts/build_release.py --output "$threadroot_candidate_output"
done
THREADROOT_BASH
~~~

Expected: each directory contains exactly the four approved artifact names.

- [ ] **Step 5: Assert exact membership and byte identity**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
for threadroot_candidate_output in /private/tmp/threadroot-v010-candidate-20260905/a /private/tmp/threadroot-v010-candidate-20260905/b; do
  test -f "$threadroot_candidate_output/threadroot-0.1.0-py3-none-any.whl"
  test -f "$threadroot_candidate_output/threadroot-0.1.0.tar.gz"
  test -f "$threadroot_candidate_output/threadroot-claude-0.1.0.zip"
  test -f "$threadroot_candidate_output/threadroot-codex-0.1.0.zip"
  threadroot_candidate_count="$(find "$threadroot_candidate_output" -maxdepth 1 -type f | wc -l | tr -d ' ')"
  test "$threadroot_candidate_count" -eq 4
done
for threadroot_candidate_asset in threadroot-0.1.0-py3-none-any.whl threadroot-0.1.0.tar.gz threadroot-claude-0.1.0.zip threadroot-codex-0.1.0.zip; do
  cmp "/private/tmp/threadroot-v010-candidate-20260905/a/$threadroot_candidate_asset" "/private/tmp/threadroot-v010-candidate-20260905/b/$threadroot_candidate_asset"
done
THREADROOT_BASH
~~~

Expected: all comparisons exit 0. A mismatch blocks the PR; use superpowers:systematic-debugging and do not weaken the requirement.

- [ ] **Step 6: Inspect candidate metadata and public contents**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
python3 scripts/check_public.py /private/tmp/threadroot-v010-candidate-20260905/a
threadroot_project_url_count="$(unzip -p /private/tmp/threadroot-v010-candidate-20260905/a/threadroot-0.1.0-py3-none-any.whl 'threadroot-0.1.0.dist-info/METADATA' | rg -x 'Project-URL: (Homepage, https://github.com/Will413028/threadroot|Repository, https://github.com/Will413028/threadroot|Issues, https://github.com/Will413028/threadroot/issues)' | wc -l | tr -d ' ')"
test "$threadroot_project_url_count" -eq 3
tar -tzf /private/tmp/threadroot-v010-candidate-20260905/a/threadroot-0.1.0.tar.gz | rg '^threadroot-0.1.0/docs/releases/v0.1.0.md$'
THREADROOT_BASH
~~~

Expected: the scan passes, METADATA prints exactly three matching Project-URL rows including the Issues suffix, and the sdist contains the release notes.

---

### Task 6: Push the readiness branch and open the pull request

**Files:**

- External state: origin/release/v0.1.0-readiness
- External state: one GitHub pull request targeting main
- No new tracked file changes

**Interfaces:**

- Consumes: Tasks 1-5 with a clean branch and no unresolved review findings.
- Produces: a reviewable PR with hosted eight-cell CI and /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt.

- [ ] **Step 1: Present the outbound change and obtain explicit authorization**

Show:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git status --short --branch
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
THREADROOT_BASH
~~~

Summarize the exact commit list, 4x252 local tests, reproducible candidate result, public scan, and attribution conclusion. Ask for permission to push release/v0.1.0-readiness and create a PR. Do not infer this permission from approval of the plan.

- [ ] **Step 2: Switch to the personal account for the bounded push and PR operation**

After approval, run the following in one shell so the trap restores the previous account on failure:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
test "$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')" = "Will413028"
git push --set-upstream origin release/v0.1.0-readiness
threadroot_pr_url="$(gh pr create --repo Will413028/threadroot --base main --head release/v0.1.0-readiness --title 'Release: prepare Threadroot v0.1.0' --body '## Summary

- replace placeholder install commands with the live public repository
- add canonical Python project URLs
- add reviewed v0.1.0 release notes and distribution contracts

## Verification

- Python 3.11, 3.12, 3.13, and 3.14: 252 tests each
- compileall on all four local interpreters
- public safety scan passed
- two candidate four-asset builds are byte-identical
- no bundled third-party notice obligation found

## Boundaries

- no runtime, vault schema, skill, manifest, or dependency changes
- no PyPI or universal plugin-directory publication
- fresh model and private-vault gates remain unexecuted')"
test -n "$threadroot_pr_url"
threadroot_restore_gh_account
trap - EXIT
printf '%s\n' "$threadroot_pr_url"
THREADROOT_BASH
~~~

Expected: push and PR creation succeed, the URL is printed, and the previously active GitHub account is restored. If PR creation reports a partial result, inspect GitHub before retrying.

- [ ] **Step 3: Wait for and inspect every PR check**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_pr_url="$(gh pr view release/v0.1.0-readiness --repo Will413028/threadroot --json url --jq .url)"
test -n "$threadroot_pr_url"
gh pr checks "$threadroot_pr_url" --repo Will413028/threadroot --watch --fail-fast
gh pr checks "$threadroot_pr_url" --repo Will413028/threadroot --json name,bucket,state,link
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: all eight macOS/Linux by Python 3.11-3.14 jobs are in the pass bucket. A pending, skipped, cancelled, or failed cell is not green.

- [ ] **Step 4: Review the remote PR diff**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_pr_url="$(gh pr view release/v0.1.0-readiness --repo Will413028/threadroot --json url --jq .url)"
test -n "$threadroot_pr_url"
gh pr diff "$threadroot_pr_url" --repo Will413028/threadroot
gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json baseRefName,headRefName,headRefOid,isDraft,mergeStateStatus,url
threadroot_reviewed_head="$(git rev-parse HEAD)"
[[ "$threadroot_reviewed_head" =~ ^[0-9a-f]{40}$ ]]
threadroot_tracked_status="$(git status --porcelain --untracked-files=no)"
test -z "$threadroot_tracked_status"
test "$(gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" = "$threadroot_reviewed_head"
gh pr checks "$threadroot_pr_url" --repo Will413028/threadroot --watch --fail-fast
gh pr checks "$threadroot_pr_url" --repo Will413028/threadroot --json name,bucket,state,link > /private/tmp/threadroot-v010-candidate-20260905/approved-pr-checks.json
jq -e 'length == 8 and all(.[]; .bucket == "pass")' /private/tmp/threadroot-v010-candidate-20260905/approved-pr-checks.json >/dev/null
test "$(gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" = "$threadroot_reviewed_head"
test "$(git rev-parse HEAD)" = "$threadroot_reviewed_head"
(set -C; printf '%s\n' "$threadroot_reviewed_head" > /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt)
test -s /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: base main, head release/v0.1.0-readiness, not draft, mergeable state, the remote diff matches the local commits approved in Task 4, all eight checks pass for that unchanged head, and its exact SHA is saved without overwriting prior approval. Any mismatch returns to the review/CI gates. The prior GitHub account is restored.

---

### Task 7: Merge and identify the only permitted release commit

**Files:**

- External state: merge commit on origin/main
- No tracked file changes

**Interfaces:**

- Consumes: the green reviewed PR and saved approved-pr-head.txt from Task 6.
- Produces: /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt, main-ci.json, and main-ci-head-sha.txt, naming the exact PR merge commit and its successful post-merge CI head.

- [ ] **Step 1: Obtain explicit merge authorization**

Present the PR URL, exact head SHA, eight green checks, final review result, and merge method. Ask for permission to merge with a merge commit. Do not enable auto-merge or administrator bypass.

- [ ] **Step 2: Merge only the reviewed head**

After approval, run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_pr_url="$(gh pr view release/v0.1.0-readiness --repo Will413028/threadroot --json url --jq .url)"
test -n "$threadroot_pr_url"
test -s /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt
threadroot_approved_pr_head="$(cat /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt)"
[[ "$threadroot_approved_pr_head" =~ ^[0-9a-f]{40}$ ]]
test "$(gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" = "$threadroot_approved_pr_head"
gh pr checks "$threadroot_pr_url" --repo Will413028/threadroot --json name,bucket | jq -e 'length == 8 and all(.[]; .bucket == "pass")' >/dev/null
gh pr merge "$threadroot_pr_url" --repo Will413028/threadroot --merge --match-head-commit "$threadroot_approved_pr_head"
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: the PR merges without deleting the remote branch or bypassing checks, and the prior GitHub account is restored.

- [ ] **Step 3: Resolve and verify the merge commit**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git fetch --no-tags origin main
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_pr_url="$(gh pr view release/v0.1.0-readiness --repo Will413028/threadroot --json url --jq .url)"
test -n "$threadroot_pr_url"
test -s /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt
threadroot_approved_pr_head="$(cat /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt)"
[[ "$threadroot_approved_pr_head" =~ ^[0-9a-f]{40}$ ]]
test "$(gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json headRefOid --jq .headRefOid)" = "$threadroot_approved_pr_head"
test "$(gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json state --jq .state)" = MERGED
threadroot_pr_merge_commit="$(gh pr view "$threadroot_pr_url" --repo Will413028/threadroot --json mergeCommit --jq .mergeCommit.oid)"
[[ "$threadroot_pr_merge_commit" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse origin/main)" = "$threadroot_pr_merge_commit"
git merge-base --is-ancestor "$threadroot_approved_pr_head" "$threadroot_pr_merge_commit"
git show --no-patch --format='%H %P %s' "$threadroot_pr_merge_commit"
(set -C; printf '%s\n' "$threadroot_pr_merge_commit" > /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt)
test -s /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: origin/main equals the PR merge commit, contains the exact reviewed head, and the prior GitHub account is restored.

- [ ] **Step 4: Wait for post-merge main CI**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git fetch --no-tags origin main
test -s /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt
threadroot_release_commit="$(cat /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt)"
[[ "$threadroot_release_commit" =~ ^[0-9a-f]{40}$ ]]
test "$(git rev-parse origin/main)" = "$threadroot_release_commit"
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_main_run=""
for threadroot_run_attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  threadroot_main_run="$(gh run list --repo Will413028/threadroot --workflow ci.yml --branch main --event push --commit "$threadroot_release_commit" --limit 1 --json databaseId --jq '.[0].databaseId // empty')" || exit 1
  test -n "$threadroot_main_run" && break
  sleep 5
done
test -n "$threadroot_main_run"
gh run watch "$threadroot_main_run" --repo Will413028/threadroot --exit-status
gh run view "$threadroot_main_run" --repo Will413028/threadroot --json headSha,status,conclusion,jobs > /private/tmp/threadroot-v010-candidate-20260905/main-ci.json
jq -e --arg sha "$threadroot_release_commit" '.headSha == $sha and .status == "completed" and .conclusion == "success" and (.jobs | length == 8 and all(.[]; .conclusion == "success"))' /private/tmp/threadroot-v010-candidate-20260905/main-ci.json >/dev/null
threadroot_successful_ci_head="$(jq -r .headSha /private/tmp/threadroot-v010-candidate-20260905/main-ci.json)"
test "$threadroot_successful_ci_head" = "$threadroot_release_commit"
git fetch --no-tags origin main
test "$(git rev-parse origin/main)" = "$threadroot_release_commit"
(set -C; printf '%s\n' "$threadroot_successful_ci_head" > /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt)
test -s /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: headSha equals the saved PR merge SHA, conclusion is success, all eight jobs succeed, current origin/main still equals that SHA, and successful CI evidence is saved outside Git without replacing earlier approval. The prior GitHub account is restored.

- [ ] **Step 5: Verify the release name is unused**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_remote_tags="$(git ls-remote --tags origin 'refs/tags/v0.1.0*')" || exit 1
test -z "$threadroot_remote_tags"
threadroot_existing_release_count="$(gh release list --repo Will413028/threadroot --limit 100 --json tagName --jq '[.[] | select(.tagName == "v0.1.0")] | length')" || exit 1
test "$threadroot_existing_release_count" -eq 0
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: no remote v0.1.0 tag and no GitHub Release exist, and the prior GitHub account is restored. Any existing object is a hard stop for manual audit.

---

### Task 8: Build the final four assets twice from the exact merge commit

**Files:**

- Generate: /private/tmp/threadroot-v010-final-20260905/source-a
- Generate: /private/tmp/threadroot-v010-final-20260905/source-b
- Generate: /private/tmp/threadroot-v010-final-20260905/artifacts-a
- Generate: /private/tmp/threadroot-v010-final-20260905/artifacts-b
- Generate: /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt
- No tracked file changes

**Interfaces:**

- Consumes: the saved approved PR head, exact PR merge SHA, successful main-CI head SHA from Tasks 6-7, and the pinned toolchain from Task 5.
- Produces: the only four files permitted for upload plus their local SHA-256 evidence.

- [ ] **Step 1: Recheck the source and toolchain**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git fetch --no-tags origin main
test -s /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt
test -s /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt
test -s /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt
threadroot_approved_pr_head="$(cat /private/tmp/threadroot-v010-candidate-20260905/approved-pr-head.txt)"
threadroot_release_commit="$(cat /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt)"
threadroot_successful_ci_head="$(cat /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt)"
[[ "$threadroot_approved_pr_head" =~ ^[0-9a-f]{40}$ ]]
[[ "$threadroot_release_commit" =~ ^[0-9a-f]{40}$ ]]
test "$threadroot_release_commit" = "$threadroot_successful_ci_head"
test "$threadroot_release_commit" = "$(git rev-parse origin/main)"
git merge-base --is-ancestor "$threadroot_approved_pr_head" "$threadroot_release_commit"
/private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -c 'from importlib.metadata import version; expected={"pip":"26.2.1","build":"1.6.0","setuptools":"84.0.0","wheel":"0.48.0","packaging":"26.3","pyproject-hooks":"1.2.0"}; assert {name:version(name) for name in expected} == expected'
test ! -e /private/tmp/threadroot-v010-final-20260905
mkdir /private/tmp/threadroot-v010-final-20260905
git worktree add --detach /private/tmp/threadroot-v010-final-20260905/source-a "$threadroot_release_commit"
git worktree add --detach /private/tmp/threadroot-v010-final-20260905/source-b "$threadroot_release_commit"
mkdir /private/tmp/threadroot-v010-final-20260905/artifacts-a
mkdir /private/tmp/threadroot-v010-final-20260905/artifacts-b
THREADROOT_BASH
~~~

Expected: both worktrees are detached at the same exact release commit and all output paths were previously absent.

- [ ] **Step 2: Run the local interpreter matrix against the release commit**

Run from source-a:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
cd /private/tmp/threadroot-v010-final-20260905/source-a
for threadroot_python in python3.11 python3.12 python3.13 python3.14; do
  command -v "$threadroot_python" >/dev/null || exit 1
  PYTHONPATH=src:. "$threadroot_python" -m unittest discover -s tests -v || exit 1
  "$threadroot_python" -m compileall -q src scripts tests || exit 1
done
python3 scripts/check_public.py .
git status --porcelain --untracked-files=no
THREADROOT_BASH
~~~

Expected: four 252-test runs, four compileall runs, and the source public scan pass; tracked status is empty.

- [ ] **Step 3: Build both final sets with the same source epoch**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
test -s /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt
test -s /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt
threadroot_release_commit="$(cat /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt)"
[[ "$threadroot_release_commit" =~ ^[0-9a-f]{40}$ ]]
test "$threadroot_release_commit" = "$(cat /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt)"
git -C /private/tmp/threadroot-v010-final-20260905/source-a fetch --no-tags origin main
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse origin/main)"
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse HEAD)"
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-b rev-parse HEAD)"
threadroot_release_epoch="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a show -s --format=%ct HEAD)"
SOURCE_DATE_EPOCH="$threadroot_release_epoch" /private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -m build --no-isolation --outdir /private/tmp/threadroot-v010-final-20260905/artifacts-a /private/tmp/threadroot-v010-final-20260905/source-a
/private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python /private/tmp/threadroot-v010-final-20260905/source-a/scripts/build_release.py --output /private/tmp/threadroot-v010-final-20260905/artifacts-a
SOURCE_DATE_EPOCH="$threadroot_release_epoch" /private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -m build --no-isolation --outdir /private/tmp/threadroot-v010-final-20260905/artifacts-b /private/tmp/threadroot-v010-final-20260905/source-b
/private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python /private/tmp/threadroot-v010-final-20260905/source-b/scripts/build_release.py --output /private/tmp/threadroot-v010-final-20260905/artifacts-b
THREADROOT_BASH
~~~

Expected: both builds exit 0 without network access.

- [ ] **Step 4: Assert exact membership and byte identity**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
for threadroot_final_output in /private/tmp/threadroot-v010-final-20260905/artifacts-a /private/tmp/threadroot-v010-final-20260905/artifacts-b; do
  test -f "$threadroot_final_output/threadroot-0.1.0-py3-none-any.whl"
  test -f "$threadroot_final_output/threadroot-0.1.0.tar.gz"
  test -f "$threadroot_final_output/threadroot-claude-0.1.0.zip"
  test -f "$threadroot_final_output/threadroot-codex-0.1.0.zip"
  threadroot_final_count="$(find "$threadroot_final_output" -maxdepth 1 -type f | wc -l | tr -d ' ')"
  test "$threadroot_final_count" -eq 4
done
for threadroot_final_asset in threadroot-0.1.0-py3-none-any.whl threadroot-0.1.0.tar.gz threadroot-claude-0.1.0.zip threadroot-codex-0.1.0.zip; do
  cmp "/private/tmp/threadroot-v010-final-20260905/artifacts-a/$threadroot_final_asset" "/private/tmp/threadroot-v010-final-20260905/artifacts-b/$threadroot_final_asset"
done
(cd /private/tmp/threadroot-v010-final-20260905/artifacts-a && shasum -a 256 threadroot-0.1.0-py3-none-any.whl threadroot-0.1.0.tar.gz threadroot-claude-0.1.0.zip threadroot-codex-0.1.0.zip) > /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt
THREADROOT_BASH
~~~

Expected: exact four-file membership, byte identity across the two sets, and one four-line checksum file outside Git.

- [ ] **Step 5: Scan the complete selected asset set**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
cd /private/tmp/threadroot-v010-final-20260905/source-a
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/artifacts-a
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0-py3-none-any.whl
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0.tar.gz
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-claude-0.1.0.zip
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-codex-0.1.0.zip
THREADROOT_BASH
~~~

If Task 4 found an available untracked maintainer denylist, rerun the checkout and artifact scans with its recorded resolved path through --denylist, without printing that path or its contents in public logs.

Expected: every scan exits 0.

- [ ] **Step 6: Ensure remote main did not move during verification**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
git -C /private/tmp/threadroot-v010-final-20260905/source-a fetch --no-tags origin main
threadroot_current_main="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse origin/main)"
threadroot_release_commit="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse HEAD)"
test "$threadroot_current_main" = "$threadroot_release_commit"
THREADROOT_BASH
~~~

Expected: equality. If main moved, stop and return to the review, CI, and release-target approval gates before repeating Tasks 8-9 in newly approved fixed paths. Never silently adopt the newer main SHA or overwrite the earlier evidence.

---

### Task 9: Validate install, sdist, host packages, and uninstall in disposable roots

**Files:**

- Generate only below: /private/tmp/threadroot-v010-final-20260905
- No tracked file changes

**Interfaces:**

- Consumes: artifacts-a from Task 8.
- Produces: pre-publication clean-room evidence for all four assets without a model run.

- [ ] **Step 1: Rebuild the wheel from the selected sdist**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
cd /private/tmp/threadroot-v010-final-20260905/source-a
mkdir /private/tmp/threadroot-v010-final-20260905/sdist-source
mkdir /private/tmp/threadroot-v010-final-20260905/sdist-wheel
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0.tar.gz
tar -xzf /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0.tar.gz -C /private/tmp/threadroot-v010-final-20260905/sdist-source
test -d /private/tmp/threadroot-v010-final-20260905/sdist-source/threadroot-0.1.0
threadroot_sdist_epoch="$(git show -s --format=%ct HEAD)"
SOURCE_DATE_EPOCH="$threadroot_sdist_epoch" /private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -m build --wheel --no-isolation --outdir /private/tmp/threadroot-v010-final-20260905/sdist-wheel /private/tmp/threadroot-v010-final-20260905/sdist-source/threadroot-0.1.0
cmp /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0-py3-none-any.whl /private/tmp/threadroot-v010-final-20260905/sdist-wheel/threadroot-0.1.0-py3-none-any.whl
THREADROOT_BASH
~~~

Expected: the sdist is safe to extract, builds without network access, and reproduces the selected wheel byte-for-byte.

- [ ] **Step 2: Install the wheel and exercise init, doctor, and claim**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
mkdir /private/tmp/threadroot-v010-final-20260905/wheel-smoke
python3.14 -m venv /private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/python -m pip install --no-index --no-deps --force-reinstall /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0-py3-none-any.whl
test "$(/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot --version)" = "threadroot 0.1.0"
test ! -e /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot init --vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault --json >/dev/null
test ! -e /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot init --vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault --json --apply >/dev/null
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot doctor --vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault --json >/dev/null
test ! -e /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault/daily/2042-04-03.md
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot claim --path daily/2042-04-03.md --vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault --json >/dev/null
test ! -e /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault/daily/2042-04-03.md
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot claim --path daily/2042-04-03.md --vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault --json --apply >/dev/null
test -f /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault/daily/2042-04-03.md
test ! -s /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault/daily/2042-04-03.md
if /private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/threadroot claim --path daily/2042-04-03.md --vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault --json --apply >/dev/null; then
  exit 1
else
  test "$?" -eq 5
fi
cp -R /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault-before-uninstall
/private/tmp/threadroot-v010-final-20260905/wheel-smoke/venv/bin/python -m pip uninstall -y threadroot >/dev/null
diff -rq /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault-before-uninstall /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault
THREADROOT_BASH
~~~

Expected: preview is pure, apply succeeds, doctor is read-only, claim creates one empty file, repeat claim exits 5, and uninstall leaves the synthetic vault unchanged.

- [ ] **Step 3: Extract and fingerprint both host packages**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-bundle
python3 -m zipfile -e /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-claude-0.1.0.zip /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle
python3 -m zipfile -e /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-codex-0.1.0.zip /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-bundle
threadroot_claude_symlinks="$(find /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle -type l -print -quit)"
threadroot_codex_symlinks="$(find /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-bundle -type l -print -quit)"
test -z "$threadroot_claude_symlinks"
test -z "$threadroot_codex_symlinks"
(cd /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-before.sha256
(cd /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-bundle && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-before.sha256
test -s /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-before.sha256
test -s /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-before.sha256
THREADROOT_BASH
~~~

Expected: extraction succeeds, neither bundle contains symlinks, and both fingerprints are nonempty.

- [ ] **Step 4: Validate and install the Claude package in isolated state**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache claude plugin validate --strict /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache claude plugin marketplace add /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache claude plugin install threadroot@threadroot --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache claude plugin list --json | jq -e '.. | strings | select(. == "threadroot@threadroot")' >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache claude plugin remove threadroot@threadroot --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/host-smoke/claude-cache claude plugin marketplace remove threadroot --scope user
THREADROOT_BASH
~~~

Expected: validate, add, install, list, remove, and marketplace removal all exit 0 without a model launch.

- [ ] **Step 5: Validate and install the Codex package in isolated state**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-home
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/user-home
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-config
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-data
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-cache
mkdir /private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-state
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/codex-home codex plugin marketplace add /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-bundle --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/codex-home codex plugin add threadroot@threadroot --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/codex-home codex plugin list --json | jq -e '.. | strings | select(. == "threadroot@threadroot")' >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/codex-home codex plugin remove threadroot@threadroot --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/host-smoke/codex-home codex plugin marketplace remove threadroot --json >/dev/null
THREADROOT_BASH
~~~

Expected: add, install, list, remove, and marketplace removal all exit 0 without reading normal Codex configuration or launching a model.

- [ ] **Step 6: Prove host validation did not mutate either bundle**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
(cd /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-bundle && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-after.sha256
(cd /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-bundle && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-after.sha256
cmp /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-before.sha256 /private/tmp/threadroot-v010-final-20260905/host-smoke/claude-after.sha256
cmp /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-before.sha256 /private/tmp/threadroot-v010-final-20260905/host-smoke/codex-after.sha256
diff -rq /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault-before-uninstall /private/tmp/threadroot-v010-final-20260905/wheel-smoke/vault
THREADROOT_BASH
~~~

Expected: both bundle trees and the synthetic vault are unchanged by host installation and removal.

---

### Task 10: Create the v0.1.0 tag and draft release

**Files:**

- External state: annotated tag v0.1.0
- External state: draft GitHub Release v0.1.0 with four assets
- No tracked file changes

**Interfaces:**

- Consumes: the exact release commit, artifacts-a, verified-sha256.txt, and all pre-publication gates.
- Produces: one unpublished draft for human inspection.

- [ ] **Step 1: Present the release candidate and obtain explicit authorization**

Present:

- Exact release commit SHA and post-merge CI URL.
- Four artifact names, byte sizes, and SHA-256 hashes.
- Local Python matrix, reproducibility, public scan, wheel, sdist, host install/remove, attribution, and reviewer results.
- Fresh model run and private dogfood explicitly marked unexecuted.
- Exact mutations: create and push annotated tag v0.1.0, then create an unpublished draft release with four assets.

Ask for explicit approval. Do not create a local or remote tag before approval.

- [ ] **Step 2: Revalidate commit, tag absence, and release absence**

After approval, run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_release_commit="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse HEAD)"
git -C /private/tmp/threadroot-v010-final-20260905/source-a fetch --no-tags origin main
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse origin/main)"
threadroot_remote_tags="$(git ls-remote --tags origin 'refs/tags/v0.1.0*')" || exit 1
test -z "$threadroot_remote_tags"
threadroot_existing_release_count="$(gh release list --repo Will413028/threadroot --limit 100 --json tagName --jq '[.[] | select(.tagName == "v0.1.0")] | length')" || exit 1
test "$threadroot_existing_release_count" -eq 0
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: exact main equality, no tag, no release, and restoration of the prior GitHub account. Any mismatch stops before mutation.

- [ ] **Step 3: Create and push the annotated tag without force**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_release_commit="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse HEAD)"
if git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse --verify --quiet refs/tags/v0.1.0 >/dev/null; then
  test "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-list -n 1 v0.1.0)" = "$threadroot_release_commit"
else
  git -C /private/tmp/threadroot-v010-final-20260905/source-a tag -a v0.1.0 "$threadroot_release_commit" -m "Threadroot v0.1.0"
fi
test "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-list -n 1 v0.1.0)" = "$threadroot_release_commit"
git -C /private/tmp/threadroot-v010-final-20260905/source-a push origin refs/tags/v0.1.0:refs/tags/v0.1.0
git -C /private/tmp/threadroot-v010-final-20260905/source-a fetch --tags origin
test "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-list -n 1 v0.1.0)" = "$threadroot_release_commit"
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: one normal tag push succeeds and the prior GitHub account is restored. Never add --force.

- [ ] **Step 4: Create the draft with explicit assets**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
threadroot_release_commit="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse HEAD)"
gh release create v0.1.0 \
  /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0-py3-none-any.whl \
  /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-0.1.0.tar.gz \
  /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-claude-0.1.0.zip \
  /private/tmp/threadroot-v010-final-20260905/artifacts-a/threadroot-codex-0.1.0.zip \
  --repo Will413028/threadroot \
  --verify-tag \
  --target "$threadroot_release_commit" \
  --draft \
  --title "Threadroot v0.1.0" \
  --notes-file /private/tmp/threadroot-v010-final-20260905/source-a/docs/releases/v0.1.0.md
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: the release exists only as a draft and the prior GitHub account is restored. If any upload fails, leave it unpublished and inspect the draft before any retry.

- [ ] **Step 5: Verify the complete draft**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
gh release view v0.1.0 --repo Will413028/threadroot --json tagName,name,isDraft,isPrerelease,targetCommitish,body,assets,url > /private/tmp/threadroot-v010-final-20260905/draft-release.json
test -s /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt
threadroot_release_commit="$(cat /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt)"
[[ "$threadroot_release_commit" =~ ^[0-9a-f]{40}$ ]]
jq -e --arg sha "$threadroot_release_commit" '.tagName == "v0.1.0" and .name == "Threadroot v0.1.0" and .isDraft == true and .isPrerelease == false and .targetCommitish == $sha' /private/tmp/threadroot-v010-final-20260905/draft-release.json >/dev/null
jq -e '[.assets[].name] | sort == ["threadroot-0.1.0-py3-none-any.whl","threadroot-0.1.0.tar.gz","threadroot-claude-0.1.0.zip","threadroot-codex-0.1.0.zip"]' /private/tmp/threadroot-v010-final-20260905/draft-release.json >/dev/null
for threadroot_draft_asset in threadroot-0.1.0-py3-none-any.whl threadroot-0.1.0.tar.gz threadroot-claude-0.1.0.zip threadroot-codex-0.1.0.zip; do
  threadroot_local_size="$(wc -c < "/private/tmp/threadroot-v010-final-20260905/artifacts-a/$threadroot_draft_asset" | tr -d ' ')"
  threadroot_remote_size="$(jq -r --arg name "$threadroot_draft_asset" '.assets[] | select(.name == $name) | .size' /private/tmp/threadroot-v010-final-20260905/draft-release.json)"
  test "$threadroot_local_size" = "$threadroot_remote_size"
done
jq -j .body /private/tmp/threadroot-v010-final-20260905/draft-release.json > /private/tmp/threadroot-v010-final-20260905/draft-body.md
cmp /private/tmp/threadroot-v010-final-20260905/source-a/docs/releases/v0.1.0.md /private/tmp/threadroot-v010-final-20260905/draft-body.md
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: draft metadata, body, asset set, and every byte size match the reviewed local candidate; the prior GitHub account is restored. Report the draft URL and do not publish.

---

### Task 11: Publish and verify unauthenticated public downloads

**Files:**

- External state: public immutable-process GitHub Release v0.1.0
- Generate: /private/tmp/threadroot-v010-final-20260905/public-download
- No tracked file changes

**Interfaces:**

- Consumes: the inspected draft and exact unchanged remote main/tag.
- Produces: a public release whose downloaded bytes and clean behavior match the verified local assets.

- [ ] **Step 1: Obtain separate publication authorization**

Present the draft URL, exact tag target, body, four names and sizes, and all pre-publication evidence. Ask explicitly for permission to change draft v0.1.0 to public. Plan approval, tag approval, or draft approval is not publication approval.

- [ ] **Step 2: Revalidate the complete draft and publish exactly once**

After approval, run this entire block in one process. The publication command is the final mutation after every revalidation guard; do not run it separately or reuse earlier draft metadata.

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
test -s /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt
test -s /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt
threadroot_release_commit="$(cat /private/tmp/threadroot-v010-candidate-20260905/pr-merge-sha.txt)"
[[ "$threadroot_release_commit" =~ ^[0-9a-f]{40}$ ]]
test "$threadroot_release_commit" = "$(cat /private/tmp/threadroot-v010-candidate-20260905/main-ci-head-sha.txt)"
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse HEAD)"
git -C /private/tmp/threadroot-v010-final-20260905/source-a fetch --no-tags origin main
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse origin/main)"
threadroot_remote_peeled_tag="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a ls-remote --exit-code --tags origin 'refs/tags/v0.1.0^{}')"
test "$threadroot_remote_peeled_tag" = "$(printf '%s\t%s' "$threadroot_release_commit" 'refs/tags/v0.1.0^{}')"
test -s /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt
test "$(wc -l < /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt | tr -d ' ')" -eq 4
(cd /private/tmp/threadroot-v010-final-20260905/artifacts-a && shasum -a 256 -c /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt)
gh release view v0.1.0 --repo Will413028/threadroot --json tagName,name,isDraft,isPrerelease,targetCommitish,body,assets,url > /private/tmp/threadroot-v010-final-20260905/prepublish-draft.json
jq -e --arg sha "$threadroot_release_commit" '.tagName == "v0.1.0" and .name == "Threadroot v0.1.0" and .isDraft == true and .isPrerelease == false and .targetCommitish == $sha and ([.assets[].name] | sort == ["threadroot-0.1.0-py3-none-any.whl","threadroot-0.1.0.tar.gz","threadroot-claude-0.1.0.zip","threadroot-codex-0.1.0.zip"])' /private/tmp/threadroot-v010-final-20260905/prepublish-draft.json >/dev/null
jq -j .body /private/tmp/threadroot-v010-final-20260905/prepublish-draft.json > /private/tmp/threadroot-v010-final-20260905/prepublish-body.md
cmp /private/tmp/threadroot-v010-final-20260905/source-a/docs/releases/v0.1.0.md /private/tmp/threadroot-v010-final-20260905/prepublish-body.md
mkdir /private/tmp/threadroot-v010-final-20260905/prepublish-download
for threadroot_draft_asset in threadroot-0.1.0-py3-none-any.whl threadroot-0.1.0.tar.gz threadroot-claude-0.1.0.zip threadroot-codex-0.1.0.zip; do
  threadroot_local_size="$(wc -c < "/private/tmp/threadroot-v010-final-20260905/artifacts-a/$threadroot_draft_asset" | tr -d ' ')"
  threadroot_remote_size="$(jq -r --arg name "$threadroot_draft_asset" '.assets[] | select(.name == $name) | .size' /private/tmp/threadroot-v010-final-20260905/prepublish-draft.json)"
  test "$threadroot_local_size" = "$threadroot_remote_size"
  gh release download v0.1.0 --repo Will413028/threadroot --pattern "$threadroot_draft_asset" --dir /private/tmp/threadroot-v010-final-20260905/prepublish-download
  cmp "/private/tmp/threadroot-v010-final-20260905/artifacts-a/$threadroot_draft_asset" "/private/tmp/threadroot-v010-final-20260905/prepublish-download/$threadroot_draft_asset"
done
(cd /private/tmp/threadroot-v010-final-20260905/prepublish-download && shasum -a 256 -c /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt)
# Re-read the full contract and asset identities; download counters are not contract fields.
gh release view v0.1.0 --repo Will413028/threadroot --json tagName,name,isDraft,isPrerelease,targetCommitish,body,assets,url > /private/tmp/threadroot-v010-final-20260905/prepublish-draft-after.json
jq -S '{tagName,name,isDraft,isPrerelease,targetCommitish,body,assets: ([.assets[] | {id,name,size,digest}] | sort_by(.name))}' /private/tmp/threadroot-v010-final-20260905/prepublish-draft.json > /private/tmp/threadroot-v010-final-20260905/prepublish-draft-before.sorted.json
jq -S '{tagName,name,isDraft,isPrerelease,targetCommitish,body,assets: ([.assets[] | {id,name,size,digest}] | sort_by(.name))}' /private/tmp/threadroot-v010-final-20260905/prepublish-draft-after.json > /private/tmp/threadroot-v010-final-20260905/prepublish-draft-after.sorted.json
cmp /private/tmp/threadroot-v010-final-20260905/prepublish-draft-before.sorted.json /private/tmp/threadroot-v010-final-20260905/prepublish-draft-after.sorted.json
threadroot_remote_peeled_tag="$(git -C /private/tmp/threadroot-v010-final-20260905/source-a ls-remote --exit-code --tags origin 'refs/tags/v0.1.0^{}')"
test "$threadroot_remote_peeled_tag" = "$(printf '%s\t%s' "$threadroot_release_commit" 'refs/tags/v0.1.0^{}')"
git -C /private/tmp/threadroot-v010-final-20260905/source-a fetch --no-tags origin main
test "$threadroot_release_commit" = "$(git -C /private/tmp/threadroot-v010-final-20260905/source-a rev-parse origin/main)"
gh release edit v0.1.0 --repo Will413028/threadroot --draft=false --latest
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: current main and the remote annotated tag's peeled commit equal the approved release commit; every draft field, exact body byte, asset name, size, and authenticated downloaded hash matches. Only then is the draft published, and the prior GitHub account is restored. Any failed check stops before publication; preserve the draft and evidence for inspection. A main mismatch returns to review/CI/verification gates.

- [ ] **Step 3: Confirm publication**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
gh release view v0.1.0 --repo Will413028/threadroot --json isDraft,isPrerelease,tagName,name,url --jq '{isDraft,isPrerelease,tagName,name,url}'
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: isDraft false, isPrerelease false, tagName v0.1.0, name Threadroot v0.1.0, and restoration of the prior GitHub account.

- [ ] **Step 4: Confirm public API visibility and download without GitHub credentials**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
mkdir /private/tmp/threadroot-v010-final-20260905/public-download
curl -fsS https://api.github.com/repos/Will413028/threadroot/releases/tags/v0.1.0 > /private/tmp/threadroot-v010-final-20260905/public-release.json
jq -e '.draft == false and .prerelease == false and .tag_name == "v0.1.0" and ([.assets[].name] | sort == ["threadroot-0.1.0-py3-none-any.whl","threadroot-0.1.0.tar.gz","threadroot-claude-0.1.0.zip","threadroot-codex-0.1.0.zip"])' /private/tmp/threadroot-v010-final-20260905/public-release.json >/dev/null
for threadroot_public_asset in threadroot-0.1.0-py3-none-any.whl threadroot-0.1.0.tar.gz threadroot-claude-0.1.0.zip threadroot-codex-0.1.0.zip; do
  curl --fail --location --proto '=https' --tlsv1.2 --output "/private/tmp/threadroot-v010-final-20260905/public-download/$threadroot_public_asset" "https://github.com/Will413028/threadroot/releases/download/v0.1.0/$threadroot_public_asset"
done
(cd /private/tmp/threadroot-v010-final-20260905/public-download && shasum -a 256 -c /private/tmp/threadroot-v010-final-20260905/verified-sha256.txt)
THREADROOT_BASH
~~~

Expected: the unauthenticated API is public, exactly four assets are listed, all downloads succeed, and all four hashes match.

- [ ] **Step 5: Repeat public wheel and sdist smoke checks**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
cd /private/tmp/threadroot-v010-final-20260905/source-a
python3 scripts/check_public.py /private/tmp/threadroot-v010-final-20260905/public-download
mkdir /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke
python3.14 -m venv /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/venv
/private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/venv/bin/python -m pip install --no-index --no-deps --force-reinstall /private/tmp/threadroot-v010-final-20260905/public-download/threadroot-0.1.0-py3-none-any.whl
test "$(/private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/venv/bin/threadroot --version)" = "threadroot 0.1.0"
/private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/venv/bin/threadroot init --vault /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/vault --apply --json >/dev/null
/private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/venv/bin/threadroot doctor --vault /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/vault --json >/dev/null
/private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/venv/bin/threadroot claim --path daily/2042-04-03.md --vault /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/vault --apply --json >/dev/null
test -f /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/vault/daily/2042-04-03.md
test ! -s /private/tmp/threadroot-v010-final-20260905/public-wheel-smoke/vault/daily/2042-04-03.md
mkdir /private/tmp/threadroot-v010-final-20260905/public-sdist-source
mkdir /private/tmp/threadroot-v010-final-20260905/public-sdist-wheel
tar -xzf /private/tmp/threadroot-v010-final-20260905/public-download/threadroot-0.1.0.tar.gz -C /private/tmp/threadroot-v010-final-20260905/public-sdist-source
threadroot_sdist_epoch="$(git show -s --format=%ct HEAD)"
SOURCE_DATE_EPOCH="$threadroot_sdist_epoch" /private/tmp/threadroot-v010-toolchain-20260905/venv/bin/python -m build --wheel --no-isolation --outdir /private/tmp/threadroot-v010-final-20260905/public-sdist-wheel /private/tmp/threadroot-v010-final-20260905/public-sdist-source/threadroot-0.1.0
cmp /private/tmp/threadroot-v010-final-20260905/public-download/threadroot-0.1.0-py3-none-any.whl /private/tmp/threadroot-v010-final-20260905/public-sdist-wheel/threadroot-0.1.0-py3-none-any.whl
THREADROOT_BASH
~~~

Expected: public scan passes, wheel commands succeed on a fresh synthetic vault, and the public sdist reproduces the public wheel.

- [ ] **Step 6: Repeat public host-package validation and installation**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-bundle
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-bundle
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-home
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/user-home
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-config
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-data
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-cache
mkdir /private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-state
python3 -m zipfile -e /private/tmp/threadroot-v010-final-20260905/public-download/threadroot-claude-0.1.0.zip /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-bundle
python3 -m zipfile -e /private/tmp/threadroot-v010-final-20260905/public-download/threadroot-codex-0.1.0.zip /private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-bundle
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache claude plugin validate --strict /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-bundle --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache claude plugin marketplace add /private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-bundle --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache claude plugin install threadroot@threadroot --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache claude plugin list --json | jq -e '.. | strings | select(. == "threadroot@threadroot")' >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache claude plugin remove threadroot@threadroot --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-xdg-state CLAUDE_CONFIG_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-config CLAUDE_CODE_PLUGIN_CACHE_DIR=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/claude-cache claude plugin marketplace remove threadroot --scope user
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-home codex plugin marketplace add /private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-bundle --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-home codex plugin add threadroot@threadroot --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-home codex plugin list --json | jq -e '.. | strings | select(. == "threadroot@threadroot")' >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-home codex plugin remove threadroot@threadroot --json >/dev/null
HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/user-home XDG_CONFIG_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-config XDG_DATA_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-data XDG_CACHE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-cache XDG_STATE_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/xdg-state CODEX_HOME=/private/tmp/threadroot-v010-final-20260905/public-host-smoke/codex-home codex plugin marketplace remove threadroot --json >/dev/null
THREADROOT_BASH
~~~

Expected: both downloaded host packages validate, install, list, and remove in disposable state without launching a model.

- [ ] **Step 7: Apply immutable failure handling**

If any post-public check fails:

1. Do not delete or retarget v0.1.0.
2. Do not replace an asset with gh release upload --clobber.
3. Preserve the synthetic evidence, report the exact failed gate, and open a separately approved v0.1.1 correction plan.

If every check passes, report the public release URL, exact commit, four SHA-256 values, and the complete gate table.

---

### Task 12: Close release readiness and open the adoption gate

**Files:**

- No public repository changes
- Keep the merged branch and temporary evidence until the user approves cleanup

**Interfaces:**

- Consumes: a public v0.1.0 release with successful public-download verification.
- Produces: an explicit release-complete handoff and a still-open telemetry-free adoption checkpoint.

- [ ] **Step 1: Verify no out-of-scope distribution occurred**

Run:

~~~bash
bash <<'THREADROOT_BASH'
set -euo pipefail
threadroot_previous_gh_account="$(gh auth status --json hosts --jq '.hosts["github.com"][] | select(.active == true) | .login')"
test -n "$threadroot_previous_gh_account"
threadroot_restore_gh_account() {
  gh auth switch --hostname github.com --user "$threadroot_previous_gh_account" >/dev/null
}
trap threadroot_restore_gh_account EXIT
gh auth switch --hostname github.com --user Will413028
gh release view v0.1.0 --repo Will413028/threadroot --json url,tagName,isDraft,isPrerelease
git ls-remote origin refs/tags/v0.1.0 'refs/tags/v0.1.0^{}'
threadroot_restore_gh_account
trap - EXIT
THREADROOT_BASH
~~~

Expected: the public release remains non-draft at v0.1.0 and the prior GitHub account is restored. Confirm from the operation log that no PyPI upload, OpenAI directory submission, Claude directory submission, model run, private vault run, telemetry addition, or normal host-state installation occurred.

- [ ] **Step 2: Report the post-release adoption gate**

Hand off these exact open conditions:

- Recruit three to five external developers.
- At least three install both layers and complete setup or adoption, doctor, and one real workflow on a vault they control.
- At least two voluntarily report a second successful use at least fourteen days later.
- Keep unresolved overwrite, unsafe-path, privacy, uninstall, and host-state isolation incidents at zero.
- Collect only opt-in feedback or public issues; do not add telemetry or infer retention from stars, downloads, clones, or install counts.
- Do not begin universal plugin-directory work until this evidence exists and the local-filesystem submission boundary is reevaluated.

- [ ] **Step 3: Preserve or clean generated state only with explicit direction**

Report these generated locations without printing their contents:

- /private/tmp/threadroot-v010-toolchain-20260905
- /private/tmp/threadroot-v010-candidate-20260905
- /private/tmp/threadroot-v010-final-20260905
- the release/v0.1.0-readiness worktree and branch

Do not delete temporary evidence, remove worktrees, or delete the branch as part of release publication. Cleanup is a separate explicit, exact-target action.

---

## Completion Criteria

This plan is complete only when:

- README commands and pyproject project URLs point to Will413028/threadroot and their focused tests pass.
- Source-controlled release notes describe both install layers, all four assets, supported systems, ownership, privacy, pre-1.0 status, and distribution limits.
- Local Python 3.11-3.14 tests and compileall pass, hosted PR and post-merge CI are green, and attribution has no unresolved obligation.
- Two final builds from the exact main merge commit produce byte-identical four-asset sets.
- Wheel, sdist, Claude package, Codex package, uninstall, public scan, and normal-host isolation checks pass before publication.
- The v0.1.0 tag targets the exact verified commit and the reviewed draft contains exactly the four verified assets.
- The public unauthenticated downloads match the verified hashes and pass the repeated clean-room checks.
- No model/private-vault evidence is inferred, and no PyPI or universal directory submission occurs.
- The adoption gate remains explicitly open after the release.
