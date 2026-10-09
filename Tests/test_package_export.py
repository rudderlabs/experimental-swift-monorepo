"""Generated manifests for real package shapes, from a tiny SwiftPM fixture."""
import hashlib
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
from common import ROOT, commit, git, inventory, load, write_json
from dependency_policy import markers, requirement, sync_inventory
from project import TRANSFORMS, export

VENDOR = "https://example.invalid/vendor-sdk.git"
MANIFEST = f'''// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "Fixture",
    platforms: [.iOS(.v15), .macOS(.v12), .tvOS(.v15), .watchOS(.v8)],
    dependencies: [.package(url: "{VENDOR}", from: "4.29.0")],
    targets: [
        .target(name: "Core", path: "Packages/Core/Sources/Core", resources: [.process("Resources")]),
        .target(name: "Kit", dependencies: ["Core", .product(name: "VendorA", package: "vendor-sdk"),
                .product(name: "VendorB", package: "vendor-sdk")], path: "Integrations/Kit/Sources/Kit")
    ]
)
'''


class PackageExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        files = {"Package.swift": MANIFEST, "LICENSE": "MIT\n", ".gitignore": ".build/\n",
                 "Packages/Core/Sources/Core/Resources/PrivacyInfo.xcprivacy": "<plist/>\n",
                 "Packages/Core/Sources/Core/Resources/Nested/config.json": "{}\n"}
        for path, target in [("Packages/Core", "Core"), ("Integrations/Kit", "Kit")]:
            files.update({f"{path}/version.txt": "1.0.0\n", f"{path}/README.md": "# Fixture\n",
                          f"{path}/CHANGELOG.md": "# Changelog\n",
                          f"{path}/Sources/{target}/Version.swift": 'enum Version { static let current = "1.0.0" }\n'})
        for path, content in files.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(content)
        write_json(self.root / ".release-please-manifest.json", {"Packages/Core": "1.0.0", "Integrations/Kit": "1.0.0"})
        write_json(self.root / "release/packages.json", {"schemaVersion": 1, "packages": {
            "sdk": {"path": "Packages/Core", "target": "Core", "repository": "experimental-rudder-sdk-swift",
                    "policies": {}, "resources": ["Resources"], "toolsVersion": "5.9",
                    "platforms": ["iOS 15", "macOS 12", "tvOS 15", "watchOS 8"]},
            "sprig": {"path": "Integrations/Kit", "target": "Kit", "repository": "experimental-integration-swift-sprig",
                      "policies": {"Core": {"mode": "external", "package": "sdk"}}, "sdkMinimum": "1.0.0",
                      "platforms": ["iOS 15"], "toolsVersion": "5.10"}}})
        shutil.copyfile(ROOT / "release/allowlist.json", self.root / "release/allowlist.json")
        sync_inventory(self.root)
        git(self.root, "init", "--initial-branch=main")
        commit(self.root, "test: tiny export fixture")

    def export(self, key):
        output = self.root.parent / ("export-" + key)
        export(key, "1.0.0", output, self.root)
        return output, (output / "Package.swift").read_text()

    def edit(self, change, sync=True):
        path = self.root / "release/packages.json"
        config = load(path)
        change(config["packages"])
        write_json(path, config)
        if sync:
            markers(self.root)
        commit(self.root, "test: change inventory")

    def test_package_platforms_and_tools_version_replace_the_root(self):
        _, text = self.export("sprig")
        self.assertTrue(text.startswith("// swift-tools-version: 5.10\n"))
        self.assertIn("    platforms: [.iOS(.v15)],\n", text)
        _, text = self.export("sdk")
        self.assertIn("platforms: [.iOS(.v15), .macOS(.v12), .tvOS(.v15), .watchOS(.v8)],", text)

    def test_missing_platforms_fail_before_writes(self):
        self.edit(lambda p: p["sprig"].pop("platforms"))
        with self.assertRaisesRegex(ValueError, "explicit platforms"):
            self.export("sprig")
        self.assertFalse((self.root.parent / "export-sprig").exists())

    def test_folder_resource_keeps_process_rule(self):
        output, text = self.export("sdk")
        self.assertIn('resources: [.process("Resources")]', text)
        for name in ["PrivacyInfo.xcprivacy", "Nested/config.json"]:
            source = self.root / "Packages/Core/Sources/Core/Resources" / name
            self.assertEqual((output / "Sources/Core/Resources" / name).read_bytes(), source.read_bytes())
        copied = [f["output"] for f in load(output / ".publication.json")["copiedFiles"]]
        self.assertIn("Sources/Core/Resources/Nested/config.json", copied)

    def test_generated_contributing_codeowners_and_readme_block_are_hashed(self):
        output, _ = self.export("sprig")
        provenance = load(output / ".publication.json")
        issues = "https://github.com/rudderlabs/experimental-swift-monorepo/issues/new/choose"
        self.assertEqual((output / ".github/CODEOWNERS").read_text(), "* @rudderlabs/sdk_team\n")
        self.assertIn(issues, (output / "CONTRIBUTING.md").read_text())
        self.assertIn("`sprig`", (output / "CONTRIBUTING.md").read_text())
        readme = (output / "README.md").read_text()
        self.assertTrue(readme.startswith("# Fixture\n\n## Report issues / contribute\n"))
        self.assertIn(f"[Report an issue or contribute]({issues})", readme)
        for path in ("CONTRIBUTING.md", ".github/CODEOWNERS", "README.md"):
            self.assertEqual(provenance["fileHashes"][path], hashlib.sha256((output / path).read_bytes()).hexdigest())
        self.assertEqual([p for p in provenance["fileHashes"] if p.startswith(".github/")], [".github/CODEOWNERS"])
        self.assertFalse((output / ".github/workflows").exists())

    def test_every_exported_file_has_one_transform(self):
        for key in ("sdk", "sprig"):
            output, _ = self.export(key)
            provenance = load(output / ".publication.json")
            transforms = {f["output"]: f["transform"] for f in provenance["copiedFiles"]}
            self.assertEqual(len(transforms), len(provenance["copiedFiles"]))
            self.assertEqual(set(transforms), set(provenance["fileHashes"]))
            self.assertLessEqual(set(transforms.values()), set(TRANSFORMS))
            for path in ("Package.swift", "README.md", "CONTRIBUTING.md", ".github/CODEOWNERS", "VERSION", ".gitignore"):
                self.assertEqual(transforms[path], "generated")
            for path in ("LICENSE", "CHANGELOG.md"):
                self.assertEqual(transforms[path], "copy")
            sources = [f for f in provenance["copiedFiles"] if f["output"].startswith("Sources/")]
            self.assertTrue(sources and all(f["transform"] == "copy" for f in sources))
            for entry in sources:
                self.assertEqual((output / entry["output"]).read_bytes(), (self.root / entry["source"]).read_bytes())

    def test_resource_inventory_compares_relative_paths(self):
        self.edit(lambda p: p["sdk"].update(resources=["Resources/PrivacyInfo.xcprivacy"]))
        with self.assertRaisesRegex(ValueError, "Resources differ"):
            self.export("sdk")

    def test_from_requirement_round_trips_and_branch_is_rejected(self):
        expected = {"kind": "upToNextMajor", "lower": "4.29.0", "upper": "5.0.0"}
        self.assertEqual([v["requirement"] for v in inventory(self.root)["sprig"]["vendors"]], [expected] * 2)
        self.assertEqual(load(self.root / "Integrations/Kit/dependency-requirements.json")["vendors"][0]["requirement"],
                         expected)
        _, text = self.export("sprig")
        self.assertIn(f'.package(url: "{VENDOR}", .upToNextMajor(from: "4.29.0"))', text)
        path = self.root / "Package.swift"
        path.write_text(path.read_text().replace('from: "4.29.0"', 'branch: "main"'))
        with self.assertRaisesRegex(ValueError, "Unsupported vendor requirement branch for vendor-sdk"):
            sync_inventory(self.root)

    def test_requirement_kinds_follow_parsed_bounds(self):
        bound = lambda lower, upper: {"range": [{"lowerBound": lower, "upperBound": upper}]}
        cases = [({"exact": ["1.2.3"]}, ("exact", "1.2.3", None)),
                 (bound("0.4.0", "1.0.0"), ("upToNextMajor", "0.4.0", "1.0.0")),
                 (bound("1.2.0", "1.3.0"), ("upToNextMinor", "1.2.0", "1.3.0")),
                 (bound("1.0.0", "3.0.0"), ("range", "1.0.0", "3.0.0"))]
        for value, (kind, lower, upper) in cases:
            self.assertEqual(requirement("vendor", value), {"kind": kind, "lower": lower, "upper": upper})

    def test_vendor_products_share_one_package_line(self):
        _, text = self.export("sprig")
        self.assertEqual(text.count(f'.package(url: "{VENDOR}"'), 1)
        for product in ["VendorA", "VendorB"]:
            self.assertIn(f'.product(name: "{product}", package: "vendor-sdk")', text)

    def test_external_policy_without_sdk_minimum_fails_clearly(self):
        self.edit(lambda p: p["sprig"].pop("sdkMinimum"), sync=False)
        with self.assertRaisesRegex(ValueError, "sprig: external policy Core requires sdkMinimum"):
            markers(self.root, check=True)
        with self.assertRaisesRegex(ValueError, "sprig: external policy Core requires sdkMinimum"):
            self.export("sprig")
        self.assertFalse((self.root.parent / "export-sprig").exists())


if __name__ == "__main__":
    unittest.main()
