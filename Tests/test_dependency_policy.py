"""Release regressions against real Swift manifest parsing and Git baselines."""
import os
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT, commit, git, inventory, run, write_json
from dependency_policy import markers, sync_inventory
from project import export
from release_plan import affected


FIXTURE = ROOT / "Tests" / "Fixtures" / "demo"  # demo packages are test data only


class DependencyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        for name in ["Package.swift", "release", "Packages", "Integrations", "Shared",
                     ".release-please-manifest.json", "scripts"]:
            path = (ROOT if name == "scripts" else FIXTURE) / name
            if path.is_dir():
                shutil.copytree(path, self.root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copyfile(path, self.root / name)
        markers(self.root)
        git(self.root, "init", "--initial-branch=dev")
        commit(self.root, "test: baseline dependency requirements")

    def update_vendor(self):
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace('exact: "1.1.4"', 'exact: "1.1.5"'))

    def test_manifest_only_update_blocks_export_before_writes(self):
        self.update_vendor()
        output = self.root.parent / "export"
        with self.assertRaisesRegex(ValueError, "Canonical manifest.*differ"):
            export("firebase", "0.1.0", output, self.root)
        self.assertFalse(output.exists())

    def test_vendor_update_selects_only_firebase_and_sync_is_repeatable(self):
        self.update_vendor()
        self.assertEqual(affected(["Package.swift"], self.root), ["firebase"])
        self.assertEqual(sync_inventory(self.root), ["firebase"])
        self.assertEqual(sync_inventory(self.root), [])
        self.assertEqual(markers(self.root, check=True), [])
        self.assertEqual(inventory(self.root)["firebase"]["vendors"][0]["version"], "1.1.5")

    def test_missing_reviewed_marker_blocks_publication(self):
        self.update_vendor()
        config = json.loads((self.root / "release/packages.json").read_text())
        config["packages"]["firebase"]["vendors"][0]["version"] = "1.1.5"
        write_json(self.root / "release/packages.json", config)
        with self.assertRaisesRegex(ValueError, "reviewed release markers: firebase"):
            markers(self.root, check=True)

    def test_lock_only_refresh_does_not_select_a_release(self):
        self.assertEqual(affected(["Package.resolved"], self.root), [])
        self.assertEqual(markers(self.root, check=True), [])

    def test_sdk_minimum_change_selects_its_integration(self):
        config = json.loads((self.root / "release/packages.json").read_text())
        config["packages"]["sprig"]["sdkMinimum"] = "0.1.1"
        write_json(self.root / "release/packages.json", config)
        self.assertEqual(affected(["release/packages.json"], self.root), ["sprig"])
        self.assertEqual(markers(self.root), ["sprig"])

    def test_committed_update_uses_explicit_previous_baseline(self):
        self.update_vendor()
        sync_inventory(self.root)
        commit(self.root, "fix: update firebase dependency and marker")
        self.assertEqual(affected(["Package.swift"], self.root, "HEAD~1"), ["firebase"])

    def test_shared_vendor_selects_both_integrations(self):
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace(
            '.target(name: "DemoSprig", dependencies: ["DemoSDK", "DemoShared"],',
            '.target(name: "DemoSprig", dependencies: ["DemoSDK", "DemoShared", '
            '.product(name: "OrderedCollections", package: "swift-collections")],'))
        self.assertEqual(sync_inventory(self.root), ["sprig"])
        commit(self.root, "test: both integrations consume the same vendor")
        self.update_vendor()
        self.assertEqual(affected(["Package.swift"], self.root), ["sprig", "firebase"])
        self.assertEqual(sync_inventory(self.root), ["sprig", "firebase"])

    def test_unsupported_range_fails_explicitly(self):
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace('exact: "1.1.4"', 'from: "1.1.4"'))
        with self.assertRaisesRegex(ValueError, "exact public Git"):
            sync_inventory(self.root)

    def test_documented_cli_accepts_base_option_before_changed_paths(self):
        self.update_vendor()
        output = run([sys.executable, self.root / "scripts/release_plan.py", "affected",
                      "--base-ref", "HEAD", "Package.swift"], cwd=self.root)
        self.assertEqual(json.loads(output), ["firebase"])


if __name__ == "__main__":
    unittest.main()
