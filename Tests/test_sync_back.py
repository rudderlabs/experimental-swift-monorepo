"""Sync back on real local Git repositories; only GitHub (clone URL, PR list and create) is modeled."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as commit.gpgsign
os.environ.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",
                  GIT_CONFIG_KEY_1="maintenance.auto", GIT_CONFIG_VALUE_1="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import commit, file_hashes, git, run, write_json
from publish import verify_tree
from reviewed_publication import BOT
import sync_back

BOT_ID_EMAIL = "12345678+rudderstack-github-actions[bot]@users.noreply.github.com"  # the id is a test value
ADA, BOB = ("Ada Outside", "ada@example.com"), ("Bob Outside", "bob@example.com")
SOURCE = "Integrations/Sprig/Sources/RudderIntegrationSprig/"


class SyncBackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote, self.public = self.root / "public.git", self.root / "public"
        run(["git", "init", "--quiet", "--bare", "--initial-branch=main", self.remote])
        run(["git", "clone", "--quiet", self.remote, self.public])
        files = {"Sources/A.swift": "let a = 1\nlet b = 2\nlet c = 3\n", "Sources/Vendored/V.swift": "let v = 1\n",
                 "README.md": "# Sprig\n"}
        for path, content in files.items():
            (self.public / path).parent.mkdir(parents=True, exist_ok=True)
            (self.public / path).write_text(content)
        write_json(self.public / ".publication.json", {
            "package": "sprig", "version": "1.0.0", "fileHashes": file_hashes(self.public),
            "copiedFiles": [{"output": "Sources/A.swift", "source": SOURCE + "A.swift", "transform": "copy"},
                            {"output": "Sources/Vendored/V.swift", "source": "Shared/V.swift",
                             "transform": "vendored-strip-import"},
                            {"output": "README.md", "source": "Integrations/Sprig/README.md", "transform": "generated"}]})
        self.publication = self.change((BOT, BOT_ID_EMAIL), "chore(release): 1.0.0", {})
        # The monorepo source equals the published file.
        self.mono = self.root / "monorepo"
        (self.mono / SOURCE).mkdir(parents=True)
        (self.mono / SOURCE / "A.swift").write_text(files["Sources/A.swift"])
        shutil.copy(ROOT / "release-please-config.json", self.mono)

    def change(self, author, subject, files):
        git(self.public, "config", "user.name", author[0])
        git(self.public, "config", "user.email", author[1])
        for path, content in files.items():
            (self.public / path).parent.mkdir(parents=True, exist_ok=True)
            (self.public / path).write_text(content)
        sha = commit(self.public, subject)
        git(self.public, "push", "--quiet", "origin", "main")
        return sha

    def sync(self, dry_run=True, found=None, gh=None, root=None):
        def fake_run(args, **kwargs):
            if args[:2] == ["gh", "pr"]:
                self.assertIsNotNone(gh, "no PR may be created")
                gh.append(args)
                return "https://example.invalid/pull/9"
            return run(args, **kwargs)
        with patch("sync_back.clone", side_effect=lambda key, dest: run(["git", "clone", "--quiet", "--no-checkout",
                                                                         self.remote, dest])), \
             patch("sync_back.existing", return_value=found), patch("sync_back.run", side_effect=fake_run), \
             patch("sync_back.ROOT", root or self.mono):
            return sync_back.sync_back("sprig", dry_run)

    def test_nothing_after_the_publication(self):
        self.assertIn("Nothing to sync for sprig", self.sync())

    def test_bot_commits_are_not_outside_changes(self):
        self.change((BOT, BOT_ID_EMAIL), "chore: bot housekeeping", {"Sources/A.swift": "let a = 9\n"})
        self.assertIn("no outside commits", self.sync())

    def test_copy_applies_and_others_need_a_person(self):
        self.change(ADA, "fix: correct b (#5)", {"Sources/A.swift": "let a = 1\nlet b = 20\nlet c = 3\n",
                                                 "Sources/Vendored/V.swift": "let v = 2\n", "README.md": "# Hi\n",
                                                 "Sources/New.swift": "let n = 1\n"})
        repo = self.root / "check"
        run(["git", "clone", "--quiet", "--no-checkout", self.remote, repo])
        commits = sync_back.outside_commits(repo, sync_back.last_publication(repo))
        provenance = sync_back.load(self.public / ".publication.json")
        writes, people, applied = sync_back.plan(repo, provenance, self.publication,
                                                 sync_back.changed_paths(repo, commits), self.mono)
        self.assertEqual(writes, {SOURCE + "A.swift": b"let a = 1\nlet b = 20\nlet c = 3\n"})
        self.assertEqual(applied, [("Sources/A.swift", SOURCE + "A.swift", "copied")])
        self.assertEqual([p for p, _ in people], ["README.md", "Sources/New.swift", "Sources/Vendored/V.swift"])
        output = self.sync()
        self.assertIn("branch chore/sync-back-sprig-", output)
        self.assertIn("PR title: fix(sprig): sync back public changes", output)
        self.assertIn("## Needs a person", output)
        self.assertIn("/pull/5)", output)

    def test_monorepo_edits_merge_three_way_or_need_a_person(self):
        self.change(ADA, "fix: correct a", {"Sources/A.swift": "let a = 10\nlet b = 2\nlet c = 3\n"})
        (self.mono / SOURCE / "A.swift").write_text("let a = 1\nlet b = 2\nlet c = 30\n")
        self.assertIn("(merged 3-way)", self.sync())
        (self.mono / SOURCE / "A.swift").write_text("let a = 11\nlet b = 2\nlet c = 3\n")
        output = self.sync()
        self.assertIn("conflicts with monorepo changes", output)
        self.assertIn("- nothing", output)

    def test_already_synced_source_is_not_rewritten(self):
        self.change(ADA, "fix: correct a", {"Sources/A.swift": "let a = 10\n"})
        (self.mono / SOURCE / "A.swift").write_text("let a = 10\n")
        self.assertIn("already has every public change", self.sync())

    def test_existing_branch_or_pr_does_nothing(self):
        self.change(ADA, "fix: correct a", {"Sources/A.swift": "let a = 10\n"})
        self.assertEqual(self.sync(dry_run=False, found="https://example.invalid/pull/3"),
                         "Already synced or in review: https://example.invalid/pull/3")

    def test_commit_has_one_trailer_per_outside_author_and_opens_a_pr(self):
        self.change(ADA, "feat: add d", {"Sources/A.swift": "let a = 1\nlet b = 2\nlet c = 3\nlet d = 4\n"})
        self.change(BOB, "docs: typo", {"README.md": "# Sprig.\n"})
        self.change(ADA, "fix: e", {"Sources/A.swift": "let a = 1\nlet b = 2\nlet c = 3\nlet d = 5\n"})
        mono_remote = self.root / "mono.git"
        run(["git", "init", "--quiet", "--bare", "--initial-branch=main", mono_remote])
        run(["git", "clone", "--quiet", mono_remote, self.root / "mono-clone"])
        clone = self.root / "mono-clone"
        shutil.copytree(self.mono, clone, dirs_exist_ok=True)
        git(clone, "config", "user.name", BOT)
        git(clone, "config", "user.email", BOT_ID_EMAIL)
        commit(clone, "chore: seed")
        git(clone, "push", "--quiet", "origin", "main")
        gh = []
        self.assertEqual(self.sync(dry_run=False, gh=gh, root=clone), "https://example.invalid/pull/9")
        branch = gh[0][gh[0].index("--head") + 1]
        self.assertTrue(branch.startswith("chore/sync-back-sprig-"))
        self.assertEqual(gh[0][gh[0].index("--title") + 1], "feat(sprig): sync back public changes")
        message = git(mono_remote, "log", "-1", "--format=%B", branch)
        self.assertEqual([l for l in message.splitlines() if l.startswith("Co-authored-by:")],
                         ["Co-authored-by: Ada Outside <ada@example.com>",
                          "Co-authored-by: Bob Outside <bob@example.com>"])
        self.assertEqual(git(mono_remote, "show", f"{branch}:{SOURCE}A.swift"),
                         "let a = 1\nlet b = 2\nlet c = 3\nlet d = 5")
        self.assertEqual(git(clone, "worktree", "list").count("\n"), 0, "the temporary worktree is removed")

    def test_commit_type(self):
        allowed = {"feat", "fix", "chore", "docs", "perf"}
        one = lambda s: [{"subject": s}]
        self.assertEqual(sync_back.commit_type(one("perf(x): faster"), allowed), "perf")
        self.assertEqual(sync_back.commit_type(one("Update README"), allowed), "chore")
        self.assertEqual(sync_back.commit_type(one("docs: x") + one("fix: y"), allowed), "fix")
        self.assertEqual(sync_back.commit_type(one("docs: x") + one("perf: y"), allowed), "chore")


class SyncedDriftTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        (self.repo / "A.swift").write_text("let a = 1\n")
        (self.repo / "B.swift").write_text("let b = 1\n")
        write_json(self.repo / ".publication.json", {"fileHashes": file_hashes(self.repo)})
        (self.repo / "A.swift").write_text("let a = 2\n")  # the outside edit
        self.edited = file_hashes(self.repo)

    def test_rejects_drift_without_an_export(self):
        with self.assertRaisesRegex(ValueError, "manual drift"):
            verify_tree(self.repo)

    def test_accepts_drift_the_export_already_has(self):
        new_export = {**self.edited, "B.swift": "changed by the release", "VERSION": "new"}
        self.assertIn("fileHashes", verify_tree(self.repo, lambda: new_export))

    def test_rejects_unsynced_drift(self):
        for export in ({**self.edited, "A.swift": "other"}, {"B.swift": self.edited["B.swift"]}):
            with self.assertRaisesRegex(ValueError, "manual drift"):
                verify_tree(self.repo, lambda: export)
        (self.repo / "Extra.swift").write_text("let x = 1\n")
        with self.assertRaisesRegex(ValueError, "manual drift"):
            verify_tree(self.repo, lambda: self.edited)

    def test_failed_export_keeps_the_drift_error(self):
        def broken():
            raise ValueError("Requested version differs from version.txt")
        with self.assertRaisesRegex(ValueError, "manual drift"):
            verify_tree(self.repo, broken)


if __name__ == "__main__":
    unittest.main()
