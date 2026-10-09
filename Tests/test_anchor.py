"""Anchor tags: validated inputs, a plain tag on a main commit, never a Release or a publication."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from anchor import anchor
from common import ROOT, commit, git, run, write_json

WORKFLOW = ROOT / ".github/workflows/anchor-package.yml"


class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        origin, self.root = base / "origin", base / "source"
        shutil.copytree(ROOT / "Tests/Fixtures/demo/release", origin / "release")
        (origin / "Integrations/Sprig").mkdir(parents=True)
        (origin / "Integrations/Sprig/version.txt").write_text("1.0.0\n")
        git(origin, "init", "--initial-branch=main")
        self.sha = commit(origin, "build(sprig): import integration-swift-sprig 1.0.0")
        git(origin, "checkout", "-b", "side")
        (origin / "side.txt").write_text("not on main\n")
        self.side = commit(origin, "test: side branch")
        git(origin, "checkout", "main")
        run(["git", "clone", origin, self.root])

    def test_valid_input_names_a_plain_component_tag(self):
        self.assertEqual(anchor("sprig", "1.0.0", self.sha, self.root), "integration-sprig-1.0.0")

    def test_invalid_inputs_are_refused(self):
        cases = [("zzz", "1.0.0", self.sha, "not allowlisted"),
                 ("sprig", "1.0", self.sha, "X.Y.Z"), ("sprig", "1.0.0-beta", self.sha, "X.Y.Z"),
                 ("sprig", "1.0.0", self.sha[:12], "40-character"), ("sprig", "1.0.0", "main" + "0" * 36, "40-character"),
                 ("sprig", "1.0.1", self.sha, "version.txt")]
        for key, version, sha, message in cases:
            with self.subTest(message=message, version=version):
                with self.assertRaisesRegex(ValueError, message):
                    anchor(key, version, sha, self.root)
        with self.assertRaises(RuntimeError):
            anchor("sprig", "1.0.0", self.side, self.root)  # not reachable from main

    def test_reserved_allowlist_key_without_a_package_is_refused(self):
        packages = self.root / "release/packages.json"
        write_json(packages, {"schemaVersion": 1, "packages": {}})
        with self.assertRaisesRegex(ValueError, "not allowlisted and listed"):
            anchor("sprig", "1.0.0", self.sha, self.root)

    def test_existing_tag_is_never_moved(self):
        git(self.root, "tag", "integration-sprig-1.0.0", self.sha)
        with self.assertRaisesRegex(ValueError, "already exists"):
            anchor("sprig", "1.0.0", self.sha, self.root)

    def test_workflow_is_manual_and_creates_only_a_plain_tag(self):
        text = WORKFLOW.read_text()
        self.assertIn("on:\n  workflow_dispatch:\n    inputs:\n", text)
        for name in ("package", "version", "sha"):
            self.assertIn(f"      {name}:\n", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn('run: python3 scripts/anchor.py "$PACKAGE" "$VERSION" "$SHA"', text)
        self.assertIn('git/refs" -f ref="refs/tags/$TAG" -f sha="$SHA"', text)
        for forbidden in ("release create", "/releases", "permission-workflows", "push:"):
            self.assertNotIn(forbidden, text)
        # Inputs reach the scripts only through the environment, never inline in a shell line.
        self.assertEqual([l for l in text.splitlines() if l.strip().startswith("run:") and "${{" in l], [])
        # No workflow starts on a tag push, so an anchor never triggers publishing.
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            self.assertNotIn("tags:", path.read_text(), path.name)


if __name__ == "__main__":
    unittest.main()
