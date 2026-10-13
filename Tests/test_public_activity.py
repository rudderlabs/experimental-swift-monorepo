"""Public issues and PRs get exactly one monorepo issue; the workflow writes only monorepo issues."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT
import public_activity
from public_activity import BOT, main, plan

REPO = "rudderlabs/experimental-swift-monorepo"
PUBLIC = "rudderlabs/experimental-integration-swift-sprig"
PACKAGES = {"sprig": {"repository": "experimental-integration-swift-sprig", "path": "Integrations/Sprig"}}
WORKFLOW = ROOT / ".github/workflows/public-activity.yml"
LATER = "2026-12-01T00:00:00Z"


def public(number, title="Crash on launch", login="someone", state="open", pr=False, merged=False,
           closed_at=None):
    item = {"number": number, "title": title, "state": state, "user": {"login": login},
            "html_url": f"https://github.com/{PUBLIC}/issues/{number}", "closed_at": closed_at}
    if pr:
        item["pull_request"] = {"merged_at": LATER if merged else None}
    return item


def mirror(number, marker, state="open", labels=("pkg:sprig", "public-issue"), body=None):
    return {"number": number, "state": state, "body": body or f"<!-- public-activity: {marker} -->\nx",
            "labels": [{"name": l} for l in labels]}


def commit(sha, login, message="fix: something"):
    return {"sha": sha * 40, "html_url": f"https://github.com/{PUBLIC}/commit/{sha}", "author": {"login": login},
            "commit": {"message": message + "\n\nbody", "author": {"name": login}}}


class Fake:
    """GitHub reads by path; writes are recorded (and give new issues number 100)."""
    def __init__(self, items=(), mirrors=(), commits=(), tags=("1.0.1", "1.0.0"), labels=()):
        self.items, self.mirrors, self.commits = list(items), list(mirrors), list(commits)
        self.tags, self.labels, self.writes = list(tags), list(labels), []

    def get(self, path):
        path, query = path.split("?", 1) if "?" in path else (path, "")
        if "page=2" in query:
            return []
        if path == f"/repos/{REPO}/issues":
            label = re.search(r"labels=([^&]+)", query)[1].replace("%3A", ":")
            return [m for m in self.mirrors if label in {l["name"] for l in m["labels"]}]
        if path == f"/repos/{REPO}/labels":
            return [{"name": n} for n in self.labels]
        if path == f"/repos/{PUBLIC}/issues":
            return self.items
        if path == f"/repos/{PUBLIC}/tags":
            return [{"name": t} for t in self.tags]
        if path == f"/repos/{PUBLIC}/compare/1.0.1...main":
            return {"ahead_by": len(self.commits), "commits": self.commits}
        raise AssertionError("unexpected read " + path)

    def write(self, method, path, body):
        self.writes.append((method, path, body))
        return {"number": 100}

    def run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            original = public_activity.inventory
            public_activity.inventory = lambda: PACKAGES
            try:
                main(list(argv), self.get, self.write)
            finally:
                public_activity.inventory = original
        return out.getvalue()


class PlanTests(unittest.TestCase):
    def test_new_public_issue_opens_one_labelled_monorepo_issue(self):
        fake = Fake(items=[public(12, "Crash @here")], labels=["pkg:sprig", "public-issue"])
        fake.run()
        self.assertEqual(len(fake.writes), 1)
        method, path, body = fake.writes[0]
        self.assertEqual((method, path), ("POST", f"/repos/{REPO}/issues"))
        self.assertEqual(body["title"], "[sprig] Issue #12: Crash @​here")
        self.assertEqual(body["labels"], ["pkg:sprig", "public-issue"])
        self.assertIn(f"<!-- public-activity: {PUBLIC}#12 -->", body["body"])
        self.assertIn(f"https://github.com/{PUBLIC}/issues/12", body["body"])
        self.assertIn("[someone](https://github.com/someone)", body["body"])

    def test_missing_labels_are_created_first(self):
        fake = Fake(items=[public(13, pr=True)])
        fake.run()
        self.assertEqual([(m, p, b.get("name")) for m, p, b in fake.writes[:2]],
                         [("POST", f"/repos/{REPO}/labels", "pkg:sprig"), ("POST", f"/repos/{REPO}/labels", "public-pr")])
        self.assertEqual(fake.writes[2][2]["title"], "[sprig] PR #13: Crash on launch")

    def test_existing_marker_creates_no_duplicate(self):
        fake = Fake(items=[public(12)], mirrors=[mirror(7, f"{PUBLIC}#12")])
        self.assertEqual(fake.run(), "No public activity to mirror.\n")
        self.assertEqual(fake.writes, [])

    def test_closed_public_issue_closes_its_mirror(self):
        fake = Fake(items=[public(12, state="closed", closed_at=LATER)], mirrors=[mirror(7, f"{PUBLIC}#12")])
        fake.run()
        self.assertEqual(fake.writes, [("POST", f"/repos/{REPO}/issues/7/comments", {"body": "Closed on the public repo."}),
                                       ("PATCH", f"/repos/{REPO}/issues/7", {"state": "closed"})])
        fake = Fake(items=[public(12, state="closed", closed_at=LATER)],
                    mirrors=[mirror(7, f"{PUBLIC}#12", state="closed")])
        fake.run()
        self.assertEqual(fake.writes, [])

    def test_closed_unmerged_pr_closes_its_mirror(self):
        fake = Fake(items=[public(13, pr=True, state="closed", closed_at=LATER)],
                    mirrors=[mirror(8, f"{PUBLIC}#13", labels=["public-pr"])])
        fake.run()
        self.assertEqual([w[2] for w in fake.writes],
                         [{"body": "Closed without merging on the public repo."}, {"state": "closed"}])

    def test_merged_pr_stays_open_with_sync_back_needed(self):
        fake = Fake(items=[public(13, pr=True, merged=True, state="closed", closed_at=LATER)],
                    mirrors=[mirror(8, f"{PUBLIC}#13", labels=["pkg:sprig", "public-pr"])], labels=["sync-back-needed"])
        fake.run()
        self.assertEqual(fake.writes, [
            ("POST", f"/repos/{REPO}/issues/8/comments", {"body": "Merged on the public repo — sync back needed."}),
            ("POST", f"/repos/{REPO}/issues/8/labels", {"labels": ["sync-back-needed"]})])
        # Already flagged: nothing more.
        fake = Fake(items=[public(13, pr=True, merged=True, state="closed", closed_at=LATER)],
                    mirrors=[mirror(8, f"{PUBLIC}#13", labels=["public-pr", "sync-back-needed"])])
        fake.run()
        self.assertEqual(fake.writes, [])

    def test_items_closed_before_monitoring_are_history(self):
        merged = public(13, pr=True, merged=True, state="closed", closed_at="2026-10-01T00:00:00Z")
        fake = Fake(items=[merged], labels=["pkg:sprig", "public-pr", "sync-back-needed"])
        fake.run()
        self.assertEqual(fake.writes, [])
        fake.run("--since", "2026-09-01T00:00:00Z")
        self.assertEqual(fake.writes[0][2]["labels"], ["pkg:sprig", "public-pr", "sync-back-needed"])
        # A newly seen closed issue is opened and closed at once.
        fake = Fake(items=[public(12, state="closed", closed_at=LATER)], labels=["pkg:sprig", "public-issue"])
        fake.run()
        self.assertEqual([(m, p) for m, p, _ in fake.writes],
                         [("POST", f"/repos/{REPO}/issues"), ("PATCH", f"/repos/{REPO}/issues/100")])

    def test_reopened_public_item_reopens_its_mirror(self):
        fake = Fake(items=[public(12)], mirrors=[mirror(7, f"{PUBLIC}#12", state="closed")])
        fake.run()
        self.assertEqual(fake.writes[-1], ("PATCH", f"/repos/{REPO}/issues/7", {"state": "open"}))

    def test_publish_bot_prs_are_ignored(self):
        fake = Fake(items=[public(4, login=BOT, pr=True, merged=True, state="closed", closed_at=LATER),
                           public(5, login=BOT, pr=True)])
        self.assertEqual(fake.run(), "No public activity to mirror.\n")
        self.assertEqual(fake.writes, [])


class UnsyncedTests(unittest.TestCase):
    def test_human_commits_after_the_latest_tag_open_one_issue(self):
        fake = Fake(commits=[commit("a", "outsider", "fix: ping @team"), commit("b", BOT)],
                    labels=["pkg:sprig", "sync-back-needed"], tags=["1.0.0", "0.9.9", "1.0.1", "latest"])
        fake.run()
        self.assertEqual(len(fake.writes), 1)
        body = fake.writes[0][2]
        self.assertEqual(body["title"], "[sprig] Public main has unsynced changes")
        self.assertEqual(body["labels"], ["pkg:sprig", "sync-back-needed"])
        self.assertIn(f"<!-- public-activity: {PUBLIC}:unsynced -->", body["body"])
        self.assertIn("fix: ping @​team (outsider)", body["body"])
        self.assertNotIn("b" * 7, body["body"])
        # The same commits again: no change.
        open_ = mirror(9, f"{PUBLIC}:unsynced", labels=["sync-back-needed"], body=body["body"])
        fake = Fake(commits=[commit("a", "outsider", "fix: ping @team")], mirrors=[open_])
        fake.run()
        self.assertEqual(fake.writes, [])

    def test_issue_closes_when_only_bot_commits_remain(self):
        open_ = mirror(9, f"{PUBLIC}:unsynced", labels=["sync-back-needed"])
        for commits in ([], [commit("b", BOT)]):
            fake = Fake(commits=commits, mirrors=[open_])
            fake.run()
            self.assertEqual([w[2] for w in fake.writes],
                             [{"body": "Public main has no unsynced changes after 1.0.1 any more."}, {"state": "closed"}])

    def test_no_tag_means_no_unsynced_report(self):
        fake = Fake(tags=[])
        self.assertEqual(fake.run(), "No public activity to mirror.\n")


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_and_writes_nothing(self):
        fake = Fake(items=[public(12), public(13, pr=True, merged=True, state="closed", closed_at=LATER)],
                    mirrors=[mirror(8, f"{PUBLIC}#13", labels=["public-pr"])], commits=[commit("a", "outsider")])
        out = fake.run("--dry-run")
        self.assertEqual(fake.writes, [])
        self.assertIn("[dry-run] create label pkg:sprig", out)
        self.assertIn("[dry-run] open issue '[sprig] Issue #12: Crash on launch'", out)
        self.assertIn("[dry-run] update #8: comment='Merged on the public repo — sync back needed.'", out)
        self.assertIn("[dry-run] open issue '[sprig] Public main has unsynced changes'", out)
        self.assertEqual(len(plan(fake.get, REPO, PACKAGES)), out.count("[dry-run]"))


class WorkflowTests(unittest.TestCase):
    def test_daily_and_manual_with_the_built_in_token(self):
        text = WORKFLOW.read_text()
        self.assertIn("name: Public Activity\n", text)
        self.assertIn("- cron: '30 3 * * *'", text)
        self.assertIn("  workflow_dispatch:\n", text)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", text)
        self.assertIn("run: python3 scripts/public_activity.py\n", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("secrets.", text)
        pins = lambda path: set(re.findall(r"uses: ([\w./-]+@[0-9a-f]{40})", path.read_text()))
        others = set().union(*(pins(p) for p in (ROOT / ".github/workflows").glob("*.yml") if p != WORKFLOW))
        self.assertTrue(pins(WORKFLOW) and pins(WORKFLOW) <= others)
        try:
            import yaml
        except ImportError:
            return
        data = yaml.safe_load(text)
        self.assertEqual(data["permissions"], {"issues": "write", "contents": "read"})
        self.assertEqual(set(data[True]), {"schedule", "workflow_dispatch"})


if __name__ == "__main__":
    unittest.main()
