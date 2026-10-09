"""make new-integration / make import-integration on a temporary monorepo (offline)."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_inventory import problems
from common import ROOT, commit, git, inventory, load, write_json
from dependency_policy import manifest, markers
from import_package import MODES, import_package, steps
from scaffold import (ROOT_MANIFEST, insert, product_line, release_please_entry, scaffold, sdk_minimum, sync,
                      target_lines)

COPIED = ["scripts", ".github", "release", "Makefile", "LICENSE", ".gitignore", "release-please-config.json",
          ".release-please-manifest.json"]
SDK = "Packages/RudderStackAnalytics"
VENDOR = "https://github.com/example/vendor-kit.git"
SOURCE_MANIFEST = f"""// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "RudderIntegrationSprig",
    platforms: [.iOS(.v15), .tvOS(.v15)],
    products: [.library(name: "RudderIntegrationSprig", targets: ["RudderIntegrationSprig"])],
    dependencies: [
        .package(url: "{VENDOR}", .upToNextMajor(from: "4.29.0")),
        .package(url: "https://github.com/rudderlabs/rudder-sdk-swift.git", .upToNextMajor(from: "1.2.1"))
    ],
    targets: [
        .target(name: "RudderIntegrationSprig", dependencies: [
            .product(name: "VendorKit", package: "vendor-kit"),
            .product(name: "RudderStackAnalytics", package: "rudder-sdk-swift")]),
        .testTarget(name: "RudderIntegrationSprigTests", dependencies: ["RudderIntegrationSprig"])
    ]
)
"""
PBXPROJ = """// !$*UTF8*$!
{
	objects = {
		A1 /* XCLocalSwiftPackageReference ".." */ = {
			isa = XCLocalSwiftPackageReference;
			relativePath = "..";
		};
	};
}
"""


def write(root, files):
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text)


def make(root, *args):
    return subprocess.run(["make", "-s", "-C", str(root), *args], capture_output=True, text=True)


def monorepo(base):
    """This repository's tooling with an empty-history core SDK package, committed."""
    root = base / "mono"
    root.mkdir()
    for name in COPIED:
        if (ROOT / name).is_dir():
            shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copyfile(ROOT / name, root / name)
    write(root, {f"{SDK}/Sources/RudderStackAnalytics/Analytics.swift": "public enum Analytics {}\n",
                 f"{SDK}/Sources/RudderStackAnalytics/Version.swift":
                     'enum RudderStackAnalyticsVersion { static let current = "1.4.0" }\n',
                 f"{SDK}/version.txt": "1.4.0\n", f"{SDK}/README.md": "# SDK\n", f"{SDK}/CHANGELOG.md": "# Changelog\n"})
    write_json(root / ".release-please-manifest.json", {SDK: "1.4.0"})
    config = load(root / "release/packages.json")
    config["packages"]["sdk"] = {"path": SDK, "target": "RudderStackAnalytics", "component": "sdk",
                                 "repository": "experimental-rudder-sdk-swift", "policies": {},
                                 "platforms": ["iOS 15"], "toolsVersion": "5.9"}
    write_json(root / "release/packages.json", config)
    (root / "Package.swift").write_text(insert(root, {
        "products": product_line("RudderStackAnalytics"),
        "targets": target_lines("RudderStackAnalytics", [], f"{SDK}/Sources/RudderStackAnalytics")}, before=True))
    sync(root)
    git(root, "init", "--quiet", "--initial-branch=main")
    commit(root, "chore: baseline")
    return root


class ManifestAnchorTests(unittest.TestCase):
    def test_lines_go_to_the_end_of_each_block_and_the_core_sdk_above_the_anchors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(insert(root, {}), ROOT_MANIFEST)
            (root / "Package.swift").write_text(ROOT_MANIFEST.replace(
                "        // @integrations-products\n",
                '        // @integrations-products\n        .library(name: "A", targets: ["A"]) // first\n'))
            text = insert(root, {"products": product_line("B"),
                                 "dependencies": [f'.package(url: "{VENDOR}", from: "1.0.0"),']}, ["macOS 12"])
            self.assertIn('    platforms: [.iOS(.v15), .macOS(.v12)],\n', text)
            self.assertIn('        // @integrations-products\n'
                          '        .library(name: "A", targets: ["A"]), // first\n'
                          '        .library(name: "B", targets: ["B"]),\n    ],', text)
            self.assertIn(f'        // @integrations-dependencies\n        .package(url: "{VENDOR}", from: "1.0.0"),\n', text)
            (root / "Package.swift").write_text(text)
            core = insert(root, {"products": product_line("Core"),
                                 "dependencies": [f'.package(url: "{VENDOR}", exact: "2.0.0"),']}, before=True)
            self.assertIn('        .library(name: "Core", targets: ["Core"]),\n        // @integrations-products\n', core)
            self.assertEqual(core.count("vendor-kit"), 1, "an existing vendor keeps its canonical requirement")
            with self.assertRaisesRegex(ValueError, "already declares B"):
                insert(root, {"products": product_line("B")})


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = monorepo(Path(self.temp.name))

    def test_new_integration_passes_every_check_without_workflow_edits(self):
        root = self.root
        workflows = {p.name: p.read_text() for p in (root / ".github/workflows").iterdir()}
        result = make(root, "new-integration", "NAME=Firebase", "PLATFORMS=iOS 15,tvOS 15",
                      f"VENDOR_URL={VENDOR}", "VENDOR_PRODUCTS=VendorKit", "VENDOR_FROM=2.0.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        path, target = root / "Integrations/Firebase", "RudderIntegrationFirebase"
        vendor = {"identity": "vendor-kit", "product": "VendorKit", "url": VENDOR,
                  "requirement": {"kind": "upToNextMajor", "lower": "2.0.0", "upper": "3.0.0"}}
        self.assertEqual(inventory(root)["firebase"], {
            "path": "Integrations/Firebase", "target": target, "component": "integration-firebase",
            "repository": "experimental-integration-swift-firebase", "platforms": ["iOS 15", "tvOS 15"],
            "toolsVersion": "5.9", "sdkMinimum": "1.4.0", "vendors": [vendor], "vendorProducts": ["VendorKit"],
            "policies": {"RudderStackAnalytics": {"mode": "external", "package": "sdk"}}})
        self.assertEqual(load(root / "release-please-config.json")["packages"],
                         {"Integrations/Firebase": release_please_entry("integration-firebase", target)})
        self.assertEqual(load(root / ".release-please-manifest.json"), {SDK: "1.4.0"})
        self.assertEqual((path / "version.txt").read_text(), "0.0.0\n")
        self.assertIn('    static let current = "0.0.0" // x-release-please-version\n',
                      (path / f"Sources/{target}/Version.swift").read_text())
        for relative in (f"Sources/{target}/FirebaseIntegration.swift",
                         f"Tests/{target}Tests/FirebaseIntegrationTests.swift", "README.md", "CHANGELOG.md"):
            self.assertTrue((path / relative).is_file(), relative)
        self.assertEqual(load(path / "dependency-requirements.json"),
                         {"schemaVersion": 2, "sdkMinimum": "1.4.0", "vendors": [vendor]})
        data = manifest(root)
        self.assertEqual({t["name"]: t.get("path") for t in data["targets"]}, {
            "RudderStackAnalytics": f"{SDK}/Sources/RudderStackAnalytics",
            target: f"Integrations/Firebase/Sources/{target}",
            f"{target}Tests": f"Integrations/Firebase/Tests/{target}Tests"})
        self.assertEqual([p["platformName"] for p in data["platforms"]], ["ios", "tvos"])
        self.assertIn("pkg:firebase", [label["name"] for label in load(root / ".github/labels.json")])
        self.assertIn('"firebase"', (root / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text())
        checked = make(root, "check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual({p.name: p.read_text() for p in (root / ".github/workflows").iterdir()}, workflows)
        commit(root, "feat(firebase): add Firebase integration")
        self.assertEqual(make(root, "sync").returncode, 0)
        self.assertEqual(git(root, "status", "--porcelain"), "")

    def test_package_missing_from_the_allowlist_fails_before_any_change(self):
        with self.assertRaisesRegex(ValueError, r"^add braze to release/allowlist.json first \(sdk_team approval\)$"):
            scaffold("Braze", self.root)
        result = make(self.root, "new-integration", "NAME=Braze")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("add braze to release/allowlist.json first (sdk_team approval)", result.stderr)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_sdk_minimum_defaults_to_the_current_sdk_version(self):
        packages = inventory(self.root)
        self.assertEqual(sdk_minimum(self.root, packages), "1.4.0")
        write_json(self.root / ".release-please-manifest.json", {})
        self.assertEqual(sdk_minimum(self.root, packages), "1.4.1")


@unittest.skipUnless(shutil.which("git-filter-repo"), "history import needs git-filter-repo")
class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory()
        source = cls.source = Path(cls.base.name) / "experimental-integration-swift-sprig"
        source.mkdir()
        git(source, "init", "--quiet", "--initial-branch=main")
        write(source, {"README.md": "# Sprig\n", "Package.swift": SOURCE_MANIFEST})
        commit(source, "feat: first release")
        git(source, "tag", "0.9.0")
        write(source, {"Sources/RudderIntegrationSprig/SprigIntegration.swift": "public enum Sprig {}\n",
                       "Tests/RudderIntegrationSprigTests/SprigTests.swift": "import XCTest\n",
                       "Example/Example.xcodeproj/project.pbxproj": PBXPROJ, "Example/App.swift": "// app\n",
                       "Package.resolved": "{}\n", ".swiftpm/xcode/package.xcworkspace/contents.xcworkspacedata": "x\n",
                       ".github/workflows/ci.yml": "on: push\n", "LICENSE.md": "MIT\n", "CODEOWNERS": "* @someone\n"})
        cls.tagged = commit(source, "fix: second release")
        git(source, "tag", "-a", "1.0.0", "-m", "1.0.0")
        write(source, {"Sources/RudderIntegrationSprig/Unreleased.swift": "// after the tag\n"})
        commit(source, "fix: unreleased")
        # Branches after (or beside) the tag: non-code only, a manifest change, and one not descending from the tag.
        git(source, "checkout", "--quiet", "-b", "relicense", "1.0.0")
        write(source, {"README.md": "# Sprig\n\nMIT licensed.\n", "LICENSE.md": "MIT, new holder\n",
                       "CODEOWNERS": "* @rudderlabs/sdk_team\n",
                       "Package.swift": SOURCE_MANIFEST + "// formatting only\n"})
        cls.relicensed = commit(source, "chore: relicense under MIT")
        git(source, "checkout", "--quiet", "-b", "platforms", "1.0.0")
        write(source, {"Package.swift": SOURCE_MANIFEST.replace(", .tvOS(.v15)", ""), "README.md": "# Sprig!\n"})
        commit(source, "chore: drop tvOS")
        git(source, "checkout", "--quiet", "-b", "beside", "0.9.0")
        write(source, {"README.md": "# Sprig beside\n"})
        cls.beside = commit(source, "docs: beside the tag")
        git(source, "checkout", "--quiet", "main")

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = monorepo(Path(self.temp.name))
        self.head = git(self.root, "rev-parse", "HEAD")

    def assert_imported(self, output, title="build(sprig): import experimental-integration-swift-sprig 1.0.0"):
        root, path = self.root, self.root / "Integrations/Sprig"
        self.assertEqual(git(root, "rev-parse", "HEAD"), self.head, "nothing is committed")
        self.assertEqual(git(root, "diff", "--name-only"), "", "everything is staged")
        self.assertEqual(git(root, "tag", "--list"), "")
        self.assertTrue((path / "Sources/RudderIntegrationSprig/SprigIntegration.swift").is_file())
        self.assertFalse((path / "Sources/RudderIntegrationSprig/Unreleased.swift").exists())
        for name in ("Package.swift", "Package.resolved", ".swiftpm", ".github", "LICENSE.md", "CODEOWNERS", "Example"):
            self.assertFalse((path / name).exists(), name)
        self.assertEqual(git(root, "ls-files", "Integrations/Sprig/Package.swift"), "")
        self.assertIn('relativePath = "../..";',
                      (root / "Examples/Sprig/Example.xcodeproj/project.pbxproj").read_text())
        self.assertEqual((path / "version.txt").read_text(), "1.0.0\n")
        self.assertIn('static let current = "1.0.0" // x-release-please-version',
                      (path / "Sources/RudderIntegrationSprig/Version.swift").read_text())
        self.assertIn("experimental-integration-swift-sprig/releases", (path / "CHANGELOG.md").read_text())
        entry = inventory(root)["sprig"]
        self.assertEqual({k: entry[k] for k in ("component", "platforms", "toolsVersion", "sdkMinimum", "policies",
                                                "vendorProducts")},
                         {"component": "integration-sprig", "platforms": ["iOS 15", "tvOS 15"], "toolsVersion": "5.9",
                          "sdkMinimum": "1.2.1", "vendorProducts": ["VendorKit"],
                          "policies": {"RudderStackAnalytics": {"mode": "external", "package": "sdk"}}})
        package = (root / "Package.swift").read_text()
        self.assertIn(f'.package(url: "{VENDOR}", .upToNextMajor(from: "4.29.0")),', package)
        self.assertIn('dependencies: [.product(name: "VendorKit", package: "vendor-kit"), "RudderStackAnalytics"],',
                      package)
        self.assertNotIn("rudder-sdk-swift", package)
        self.assertEqual(load(root / "release-please-config.json")["packages"], {}, "no Release Please entry")
        self.assertEqual(load(root / ".release-please-manifest.json"), {SDK: "1.4.0"})
        self.assertEqual(problems(root), [])
        self.assertEqual(markers(root, check=True), [])
        for text in (title, "1. Open the import PR", "2. Run Actions > Anchor package (package=sprig, version=1.0.0",
                     "plain tag integration-sprig-1.0.0", '3. Open "build(sprig): enable releases"',
                     '"Integrations/Sprig": "1.0.0"'):
            self.assertIn(text, output)

    def test_snapshot_import_copies_the_tagged_files(self):
        result = make(self.root, "import-integration", f"REPO={self.source}", "TAG=1.0.0", "NAME=Sprig",
                      "MODE=snapshot")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".git/MERGE_HEAD").exists())
        self.assert_imported(result.stdout)
        self.assertIn("squash-merge it", result.stdout)

    def test_history_import_rewrites_history_under_the_folder_with_legacy_tags(self):
        result = import_package(str(self.source), "1.0.0", "Sprig", "history", self.root)
        root = self.root
        self.assertEqual(result["sha"], self.tagged)
        self.assertNotEqual(result["imported"], self.tagged)
        self.assertEqual(result["legacyTags"], ["legacy/sprig/0.9.0", "legacy/sprig/1.0.0"])
        self.assertEqual(git(root, "rev-parse", "MERGE_HEAD"), result["imported"])
        self.assertEqual(git(root, "rev-list", "--count", "MERGE_HEAD"), "2", "commits after the tag stay out")
        files = git(root, "ls-tree", "-r", "--name-only", "MERGE_HEAD").splitlines()
        self.assertIn("Integrations/Sprig/Package.swift", files)
        self.assertTrue(all(f.startswith("Integrations/Sprig/") for f in files))
        self.assert_imported(steps(result))
        self.assertIn("merge commit", steps(result))
        git(root, "commit", "--quiet", "-m", "build(sprig): import experimental-integration-swift-sprig 1.0.0")
        self.assertEqual(git(root, "rev-parse", "HEAD^2"), result["imported"])
        self.assertEqual(git(root, "tag", "--list"), "")

    def assert_unchanged(self):
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.head)
        self.assertFalse((self.root / ".git/MERGE_HEAD").exists())

    def test_history_import_of_a_non_code_ref_keeps_the_tag_version(self):
        result = import_package(str(self.source), "1.0.0", "Sprig", "history", self.root, ref="relicense")
        root, output = self.root, steps(result)
        self.assertEqual((result["ref"], result["sha"], result["tagSha"]), ("relicense", self.relicensed, self.tagged))
        self.assertEqual(result["nonCode"], ["CODEOWNERS", "LICENSE.md", "Package.swift", "README.md"])
        self.assertEqual(result["legacyTags"], ["legacy/sprig/0.9.0", "legacy/sprig/1.0.0"])
        self.assertEqual(git(root, "rev-list", "--count", "MERGE_HEAD"), "3", "the relicense commit comes along")
        self.assertIn("MIT licensed.", (root / "Integrations/Sprig/README.md").read_text())
        self.assert_imported(output, "build(sprig): import experimental-integration-swift-sprig relicense "
                                     f"({self.relicensed[:12]}) at version 1.0.0")
        self.assertIn(f"relicense ({self.relicensed}) at version 1.0.0", output)
        self.assertIn("Non-code files that differ between 1.0.0 and relicense: CODEOWNERS, LICENSE.md, Package.swift, "
                      "README.md", output)

    def test_snapshot_import_of_a_non_code_sha_keeps_the_tag_version(self):
        result = make(self.root, "import-integration", f"REPO={self.source}", "TAG=1.0.0", "NAME=Sprig",
                      "MODE=snapshot", f"REF={self.relicensed}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".git/MERGE_HEAD").exists())
        self.assertIn("MIT licensed.", (self.root / "Integrations/Sprig/README.md").read_text())
        sha = self.relicensed
        self.assert_imported(result.stdout, f"import experimental-integration-swift-sprig {sha} ({sha[:12]}) at "
                                            "version 1.0.0")
        self.assertIn("Non-code files that differ between 1.0.0 and", result.stdout)

    def test_ref_with_code_or_manifest_changes_or_off_the_tag_fails_without_changes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, r"main \([0-9a-f]{40}\) changes code since 1\.0\.0.*: "
                                                        r"Sources/RudderIntegrationSprig/Unreleased\.swift$"):
                    import_package(str(self.source), "1.0.0", "Sprig", mode, self.root, ref="main")
                self.assert_unchanged()
        with self.assertRaisesRegex(ValueError, r"changes code since 1\.0\.0.*: Package\.swift \(products, targets, "
                                                r"dependencies, platforms, toolsVersion\)$"):
            import_package(str(self.source), "1.0.0", "Sprig", "history", self.root, ref="platforms")
        self.assert_unchanged()
        with self.assertRaisesRegex(ValueError, f"Tag 1.0.0 is not an ancestor of beside \\({self.beside}\\)"):
            import_package(str(self.source), "1.0.0", "Sprig", "snapshot", self.root, ref="beside")
        with self.assertRaisesRegex(ValueError, "Ref nowhere not found"):
            import_package(str(self.source), "1.0.0", "Sprig", "history", self.root, ref="nowhere")
        result = make(self.root, "import-integration", f"REPO={self.source}", "TAG=1.0.0", "NAME=Sprig",
                      "MODE=history", "REF=main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Sources/RudderIntegrationSprig/Unreleased.swift", result.stderr)
        self.assert_unchanged()

    def test_import_refuses_unknown_keys_and_tags_without_changes(self):
        with self.assertRaisesRegex(ValueError, "add braze to release/allowlist.json first"):
            import_package(str(self.source), "1.0.0", "Braze", "snapshot", self.root)
        with self.assertRaisesRegex(ValueError, "Tag 2.0.0 not found"):
            import_package(str(self.source), "2.0.0", "Sprig", "history", self.root)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.head)


if __name__ == "__main__":
    unittest.main()
