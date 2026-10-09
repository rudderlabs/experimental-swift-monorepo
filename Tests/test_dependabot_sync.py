"""Dependabot PRs that change release markers get a releasable title; the workflow runs only repo scripts."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT
from dependabot_sync import changed_packages, retitle

PACKAGES = {"sdk": {"path": "Packages/RudderStackAnalytics"}, "firebase": {"path": "Integrations/Firebase"},
            "sprig": {"path": "Integrations/Sprig"}}
WORKFLOW = ROOT / ".github/workflows/dependabot-sync.yml"


class RetitleTests(unittest.TestCase):
    def test_changed_markers_select_their_packages(self):
        paths = ["release/packages.json", "Integrations/Sprig/dependency-requirements.json",
                 "Integrations/Firebase/dependency-requirements.json", "Integrations/Firebase/README.md",
                 "Packages/RudderStackAnalytics/shared-source.json"]
        self.assertEqual(changed_packages(paths, PACKAGES), ["firebase", "sprig"])
        self.assertEqual(changed_packages(["Package.resolved"], PACKAGES), [])

    def test_dependabot_titles_become_releasable_fixes(self):
        for title, keys, expected in [
                ("build(deps): bump firebase-ios-sdk from 12.5.0 to 13.0.0", ["firebase"],
                 "fix(firebase): bump firebase-ios-sdk to 13.0.0"),
                ("Bump firebase-ios-sdk from 12.5.0 to 13.0.0 in /", ["firebase"],
                 "fix(firebase): bump firebase-ios-sdk to 13.0.0"),
                ("chore(deps)!: bump the swift group across 1 directory with 2 updates", ["firebase", "sprig"],
                 "fix(firebase,sprig): bump the swift group across 1 directory with 2 updates"),
                ("Bump X\nfrom 1 to 2.", ["sprig"], "fix(sprig): bump X to 2"),
                ("Update the vendor.", ["sprig"], "fix(sprig): update the vendor")]:
            with self.subTest(title=title):
                self.assertEqual(retitle(title, keys), expected)

    def test_no_marker_change_keeps_the_title_and_long_titles_drop_the_scope(self):
        self.assertIsNone(retitle("build(deps): bump firebase-ios-sdk from 12.5.0 to 13.0.0", []))
        title = retitle("Bump " + "a" * 80 + " from 1.0.0 to 2.0.0", ["firebase", "sprig"])
        self.assertEqual(title, "fix: bump " + "a" * 80 + " to 2.0.0")
        self.assertLessEqual(len(retitle("Bump " + "a" * 200, ["sprig"])), 100)


class WorkflowTests(unittest.TestCase):
    def test_runs_only_for_dependabot_manifest_changes_and_repo_scripts(self):
        text = WORKFLOW.read_text()
        self.assertIn("    paths: [Package.swift]\n", text)
        self.assertIn("if: github.event.pull_request.user.login == 'dependabot[bot]'\n", text)
        self.assertNotIn("if: github.actor", text)  # spoofable (zizmor bot-conditions)
        self.assertIn("private-key: ${{ secrets.RELEASE_PRIVATE_KEY }}", text)
        self.assertIn("client-id: ${{ vars.RELEASE_APP_CLIENT_ID }}", text)
        self.assertIn("step-security/harden-runner@", text)
        # Untrusted PR text reaches scripts only through the environment.
        self.assertEqual(text.count("github.event.pull_request.title"), 1)
        self.assertIn("PR_TITLE: ${{ github.event.pull_request.title }}", text)
        self.assertEqual([line for line in text.splitlines() if "${{" in line and ("run:" in line or "git " in line)],
                         [])
        runs = re.findall(r"^\s+run: (.+)$", text, re.M)
        self.assertEqual(runs[:2], ["make sync", "python3 scripts/dependabot_sync.py"])
        # Only actions already pinned elsewhere in the repository.
        pins = lambda path: set(re.findall(r"uses: ([\w./-]+@[0-9a-f]{40})", path.read_text()))
        others = set().union(*(pins(p) for p in (ROOT / ".github/workflows").glob("*.yml") if p != WORKFLOW))
        self.assertTrue(pins(WORKFLOW) <= others)
        try:
            import yaml
        except ImportError:
            return
        data = yaml.safe_load(text)
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertEqual(list(data[True]), ["pull_request"])


if __name__ == "__main__":
    unittest.main()
