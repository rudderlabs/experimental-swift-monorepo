"""The repository git hooks (scripts/git-hooks), run as git runs them."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings and global hooks
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT, git

HOOKS = ROOT / "scripts/git-hooks"
FIXTURE = ROOT / "Tests/Fixtures/demo"


def hook(name, *args, stdin="", env=None, cwd=None):
    return subprocess.run([HOOKS / name, *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, cwd=cwd)


class CommitMessageTests(unittest.TestCase):
    def check(self, message):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "COMMIT_EDITMSG"
            path.write_text(message)
            return hook("commit-msg", path, cwd=temp)

    def test_valid_messages(self):
        for message in ["feat: add session timeout", "fix(sprig): skip empty traits when identifying users",
                        "feat(sdk)!: remove the deprecated flush API", "refactor!: rename the queue",
                        "chore(release-please): v1.3.0", "perf(sdk,sprig): batch writes",
                        "docs: explain make prepare\n\nLonger body. With Capitals.\n",
                        "# editor comment\n\nci: pin actions\n", "build(firebase): import 1.1.2",
                        "test: cover iOS 15", "fix: handle iOS crash", "style: " + "a" * 93,
                        "Merge branch 'main' into feat/x", 'Revert "fix(sprig): skip empty traits"']:
            result = self.check(message)
            self.assertEqual(result.returncode, 0, f"{message!r}: {result.stdout}{result.stderr}")

    def test_invalid_messages_fail_with_the_reason_and_an_example(self):
        cases = {"Add session timeout": "Invalid commit message format",
                 "feature: add timeout": "Invalid commit message format",
                 "Fix: add timeout": "Invalid commit message format",
                 "fix(Sprig): add timeout": "Invalid commit message format",
                 "fix(): add timeout": "Invalid commit message format",
                 "fix:add timeout": "Invalid commit message format",
                 "fix: Add timeout": "must not start with a capital letter",
                 "fix: add timeout.": "must not end with a period",
                 "fix:  add timeout": "exactly one space",
                 "style: " + "a" * 94: "the maximum is 100",
                 "Revert fix": "Invalid commit message format"}
        for message, reason in cases.items():
            result = self.check(message)
            self.assertEqual(result.returncode, 1, message)
            self.assertIn(reason, result.stdout, message)
            self.assertIn("fix(sprig): skip empty traits when identifying users", result.stdout)
        result = self.check("# only a comment\n\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot be empty", result.stderr)


class BranchNameTests(unittest.TestCase):
    def push(self, branch, env=None):
        line = f"refs/heads/{branch} {'1' * 40} refs/heads/{branch} {'0' * 40}\n"
        # stdout is a pipe, as in a GUI client, so the hook skips `make test`.
        return hook("pre-push", "origin", "https://example.invalid/repo.git", stdin=line, env=env)

    def test_valid_branch_names(self):
        for branch in ["feat/sdk-5388-developer-setup", "fix/sprig-empty-traits", "ci/developer-setup",
                       "perf/x", "style/x", "test/x", "docs/x", "chore/x", "build/x", "refactor/x", "revert/x",
                       "hotfix/1.4.1", "release/1.5.0", "main"]:
            result = self.push(branch)
            self.assertEqual(result.returncode, 0, f"{branch}: {result.stdout}")
            self.assertIn("Skipping tests", result.stdout)

    def test_invalid_branch_names(self):
        for branch in ["my-branch", "feature/x", "Feat/x", "fix/", "fix/a/b", "develop", "fix/a@b"]:
            result = self.push(branch)
            self.assertEqual(result.returncode, 1, branch)
            self.assertIn("Invalid branch name", result.stdout)
            self.assertIn("feat/sdk-5388-developer-setup", result.stdout)

    def test_tags_and_deletes_are_not_branch_checked(self):
        result = hook("pre-push", "origin", "x", stdin=f"refs/tags/1.0.0 {'1' * 40} refs/tags/1.0.0 {'0' * 40}\n"
                                                       f"(delete) {'0' * 40} refs/heads/old {'1' * 40}\n")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_global_hook_runs_first_and_does_not_hide_the_refs(self):
        with tempfile.TemporaryDirectory() as temp:
            hooks = Path(temp) / "global-hooks"
            hooks.mkdir()
            (hooks / "pre-push").write_text("#!/bin/bash\ncat > /dev/null\necho global-pre-push-ran\n")
            (hooks / "pre-push").chmod(0o755)
            config = Path(temp) / "gitconfig"
            config.write_text(f"[core]\n\thooksPath = {hooks}\n")
            result = self.push("bad-name", env={"GIT_CONFIG_GLOBAL": str(config)})
            self.assertIn("global-pre-push-ran", result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid branch name: 'bad-name'", result.stdout)
            (hooks / "pre-push").write_text("#!/bin/bash\necho blocked by gitleaks\nexit 3\n")
            result = self.push("fix/x", env={"GIT_CONFIG_GLOBAL": str(config)})
            self.assertEqual(result.returncode, 3)
            self.assertNotIn("Running pre-push checks", result.stdout)


class PreCommitTests(unittest.TestCase):
    """A fixture monorepo with the hooks on: markers follow Package.swift into the same commit."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "mono"
        shutil.copytree(FIXTURE, self.root, ignore=shutil.ignore_patterns(".build", ".swiftpm"))
        for name in ["scripts", "Makefile", ".swiftlint.yml", "LICENSE", ".gitignore"]:
            if (ROOT / name).is_dir():
                shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copyfile(ROOT / name, self.root / name)
        shutil.copytree(ROOT / ".github", self.root / ".github")
        subprocess.run([sys.executable, "scripts/generate_github.py"], cwd=self.root, check=True,
                       capture_output=True)
        git(self.root, "init", "--quiet", "--initial-branch=main")
        git(self.root, "add", "-A")
        git(self.root, "commit", "--quiet", "--no-verify", "-m", "chore: baseline")
        git(self.root, "config", "--local", "core.hooksPath", "scripts/git-hooks")

    def commit(self, message, *paths):
        git(self.root, "add", "--", *paths)
        return subprocess.run(["git", "commit", "-m", message], cwd=self.root, capture_output=True, text=True)

    def committed(self):
        return sorted(git(self.root, "show", "--name-only", "--format=", "HEAD").splitlines())

    def test_vendor_requirement_change_adds_its_markers_to_the_same_commit(self):
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace('exact: "1.1.4"', 'exact: "1.1.5"'))
        result = self.commit("fix(firebase): bump swift-collections to 1.1.5", "Package.swift")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.committed(), ["Integrations/Firebase/dependency-requirements.json", "Package.swift",
                                            "release/packages.json"])
        self.assertIn('"lower": "1.1.5"', (self.root / "Integrations/Firebase/dependency-requirements.json").read_text())
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        check = subprocess.run([sys.executable, "scripts/dependency_policy.py", "check"], cwd=self.root,
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_shared_change_adds_shared_markers(self):
        path = self.root / "Shared/DemoShared/DemoNormalizer.swift"
        path.write_text(path.read_text() + "\n// shared change\n")
        result = self.commit("fix: normalize shared names", "Shared/DemoShared/DemoNormalizer.swift")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.committed(), ["Integrations/Firebase/shared-source.json",
                                            "Integrations/Sprig/shared-source.json",
                                            "Shared/DemoShared/DemoNormalizer.swift"])

    def test_source_only_commit_runs_no_sync(self):
        path = self.root / "Tests/DemoTests/DemoTests.swift"
        path.write_text(path.read_text() + "\n// source change\n")
        result = self.commit("test: note", "Tests/DemoTests/DemoTests.swift")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.committed(), ["Tests/DemoTests/DemoTests.swift"])
        self.assertNotIn("Syncing", result.stdout + result.stderr)

    def test_bad_message_is_rejected(self):
        (self.root / "README.md").write_text("# Demo\n")
        result = self.commit("Update readme", "README.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid commit message format", result.stdout + result.stderr)
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "chore: baseline")


if __name__ == "__main__":
    unittest.main()
