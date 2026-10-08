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
from common import ROOT, commit, git, inventory, load, run, write_json
from dependency_policy import markers, sync_inventory
from project import export
from release_plan import affected, shared_markers


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
        self.assertEqual(inventory(self.root)["firebase"]["vendors"][0]["requirement"],
                         {"kind": "exact", "lower": "1.1.5", "upper": None})

    def test_missing_reviewed_marker_blocks_publication(self):
        self.update_vendor()
        config = json.loads((self.root / "release/packages.json").read_text())
        config["packages"]["firebase"]["vendors"][0]["requirement"]["lower"] = "1.1.5"
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

    def test_export_vendors_package_level_shared_code_and_rejects_public(self):
        (self.root / ".gitignore").write_text(".build/\n.swiftpm/\n")
        (self.root / "LICENSE").write_text("MIT\n")
        commit(self.root, "test: exportable fixture")
        output = self.root.parent / "export"
        export("firebase", "0.1.0", output, self.root)
        sources = output / "Sources/DemoFirebase"
        self.assertIn("package enum DemoNormalizer", (sources / "Vendored/DemoShared/DemoNormalizer.swift").read_text())
        self.assertEqual((sources / "DemoFirebase.swift").read_text().splitlines()[:2],
                         ["import DemoSDK", "import OrderedCollections"])
        shared = self.root / "Shared/DemoShared/DemoNormalizer.swift"
        shared.write_text(shared.read_text().replace("package enum", "public enum"))
        commit(self.root, "test: widen shared access")
        with self.assertRaisesRegex(ValueError, "package access, not public/open: DemoNormalizer.swift"):
            export("firebase", "0.1.0", self.root.parent / "export-public", self.root)

    def test_fixture_shared_markers_are_current(self):
        self.assertEqual(shared_markers(self.root, check=True), [])

    def test_shared_change_selects_only_integrations_vendoring_that_target(self):
        other = self.root / "Shared/DemoFormat/DemoFormat.swift"
        other.parent.mkdir(parents=True)
        other.write_text('package enum DemoFormat {\n    package static let separator = " "\n}\n')
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace(
            '.target(name: "DemoShared", path: "Shared/DemoShared"),',
            '.target(name: "DemoShared", path: "Shared/DemoShared"),\n'
            '        .target(name: "DemoFormat", path: "Shared/DemoFormat"),').replace(
            '["DemoSDK", "DemoShared",\n', '["DemoSDK", "DemoShared", "DemoFormat",\n'))
        self.assertIn('"DemoShared", "DemoFormat",', path.read_text())
        config = load(self.root / "release/packages.json")
        config["packages"]["firebase"]["policies"]["DemoFormat"] = {"mode": "vendor"}
        write_json(self.root / "release/packages.json", config)
        self.assertEqual(shared_markers(self.root), ["firebase"])
        self.assertEqual(list(load(self.root / "Integrations/Sprig/shared-source.json")),
                         ["Shared/DemoShared/DemoNormalizer.swift"])
        self.assertEqual(sorted(load(self.root / "Integrations/Firebase/shared-source.json")),
                         ["Shared/DemoFormat/DemoFormat.swift", "Shared/DemoShared/DemoNormalizer.swift"])
        other.write_text(other.read_text().replace('" "', '"-"'))
        self.assertEqual(affected(["Shared/DemoFormat/DemoFormat.swift"], self.root), ["firebase"])
        with self.assertRaisesRegex(ValueError, "sync-shared .*: firebase$"):
            shared_markers(self.root, check=True)
        self.assertEqual(shared_markers(self.root), ["firebase"])
        self.assertEqual(affected(["Shared/DemoShared/DemoNormalizer.swift"], self.root), ["sprig", "firebase"])
        self.assertEqual(affected(["Shared/README.md"], self.root), [])

    def test_unsupported_revision_fails_explicitly(self):
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace('exact: "1.1.4"', 'revision: "' + "a" * 40 + '"'))
        with self.assertRaisesRegex(ValueError, "Unsupported vendor requirement revision for swift-collections"):
            sync_inventory(self.root)

    def test_documented_cli_accepts_base_option_before_changed_paths(self):
        self.update_vendor()
        output = run([sys.executable, self.root / "scripts/release_plan.py", "affected",
                      "--base-ref", "HEAD", "Package.swift"], cwd=self.root)
        self.assertEqual(json.loads(output), ["firebase"])


if __name__ == "__main__":
    unittest.main()
