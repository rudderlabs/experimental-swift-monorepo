"""Shared code stays `package`-level and vendors cleanly into each standalone integration."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import anonymous_env, commit, git, run, swift_options, write_json
from dependency_policy import sync_inventory
from project import export, strip_imports, wide_access
from release_plan import shared_markers

SOURCE = '''// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "Fixture",
    platforms: [.macOS(.v12)],
    targets: [
        .target(name: "TextShared", path: "Shared/TextShared"),
        .target(name: "KitA", dependencies: ["TextShared"], path: "Integrations/A/Sources/KitA"),
        .target(name: "KitB", dependencies: ["TextShared"], path: "Integrations/B/Sources/KitB")
    ]
)
'''
CONSUMER = '''// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "Consumer",
    platforms: [.macOS(.v12)],
    dependencies: [.package(path: "../KitA"), .package(path: "../KitB")],
    targets: [.executableTarget(name: "Consumer", dependencies: [
        .product(name: "KitA", package: "KitA"), .product(name: "KitB", package: "KitB")])]
)
'''


class AccessLevelTests(unittest.TestCase):
    def test_public_and_open_modifiers_are_reported_by_line(self):
        text = ("package enum A {}\npublic enum B {}\nstruct C { public(set) var x = 1 }\n"
                "open class D {}\nclass E: D { override open func f() {} }\n@_spi(X) public func g() {}\n")
        self.assertEqual(wide_access(text), [2, 3, 4, 5, 6])

    def test_comments_strings_and_identifiers_are_ignored(self):
        text = ('// public enum A {}\n/* public /* nested */ open class B {} */\n'
                'let s = "public enum C {}", r = #"open class "D" {}"#\n'
                'let m = """\n    public struct E {}\n    """\n'
                'func open() {}\nlet open = 1\nenum F { case open\n    case closed }\n'
                'let g = x.public\nlet `public` = 2\npackage struct H {}\n')
        self.assertEqual(wide_access(text), [])

    def test_shared_public_symbol_fails_sync_shared(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / "release/packages.json", {"schemaVersion": 1, "packages": {}})
            source = root / "Shared/Text/Text.swift"
            source.parent.mkdir(parents=True)
            source.write_text("import Foundation\n\n// public is fine here\npackage enum A {}\npublic enum B {}\n")
            with self.assertRaisesRegex(ValueError, r"`package` access, not public/open: Shared/Text/Text\.swift:5"):
                shared_markers(root, check=True)
            source.write_text(source.read_text().replace("public enum B", "package enum B"))
            self.assertEqual(shared_markers(root, check=True), [])


class ImportStripTests(unittest.TestCase):
    def test_import_variants_of_vendored_modules_are_removed(self):
        text = ("import Foundation\n@_exported import TextShared\n  @testable import TextShared\r\n"
                "import struct TextShared.Normalizer\n\timport enum TextShared.Mode // why\n"
                "@_spi(Internal) @preconcurrency import TextShared\npackage import Other.Thing\n"
                "import TextSharedExtras\nimport OtherShared\n// import TextShared\nlet x = 1\nimport TextShared")
        self.assertEqual(strip_imports(text, ["TextShared", "Other"]),
                         "import Foundation\nimport TextSharedExtras\nimport OtherShared\n"
                         "// import TextShared\nlet x = 1\n")

    def test_crlf_line_endings_are_kept(self):
        self.assertEqual(strip_imports("import TextShared\r\nimport Foundation\r\nlet x = 1\r\n", ["TextShared"]),
                         "import Foundation\r\nlet x = 1\r\n")


@unittest.skipUnless(os.environ.get("RUN_SWIFT_BUILD_TESTS") == "1", "set RUN_SWIFT_BUILD_TESTS=1 to run swift build")
class VendoredBuildTests(unittest.TestCase):
    """Two exports vendor the same `package` helper; one consumer links both without ambiguity."""

    def test_two_exported_integrations_build_together(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        root = base / "source"
        files = {"Package.swift": SOURCE, "LICENSE": "MIT\n", ".gitignore": ".build/\n",
                 ".gitattributes": "*.swift whitespace=cr-at-eol\n",
                 "Shared/TextShared/Normalizer.swift":
                     "package enum Normalizer {\n    package static func normalize(_ s: String) -> String "
                     "{ s.lowercased() }\n}\n"}
        imports = {"A": "@_exported import TextShared\n", "B": "  import enum TextShared.Normalizer\r\n"}
        for name, line in imports.items():
            path = f"Integrations/{name}"
            files.update({f"{path}/version.txt": "1.0.0\n", f"{path}/README.md": "# Kit\n",
                          f"{path}/CHANGELOG.md": "# Changelog\n",
                          f"{path}/Sources/Kit{name}/Version.swift":
                              f'public enum Kit{name}Version {{ public static let current = "1.0.0" }}\n',
                          f"{path}/Sources/Kit{name}/Kit{name}.swift":
                              f"{line}public enum Kit{name} {{\n    public static func track(_ s: String) -> String "
                              f'{{ Normalizer.normalize(s) + "-{name.lower()}" }}\n}}\n'})
        files = {"source/" + path: content for path, content in files.items()}
        files["Consumer/Package.swift"] = CONSUMER
        files["Consumer/Sources/Consumer/main.swift"] = (
            'import KitA\nimport KitB\nprecondition(KitA.track("X") == "x-a" && KitB.track("Y") == "y-b")\n')
        for path, content in files.items():
            (base / path).parent.mkdir(parents=True, exist_ok=True)
            (base / path).write_bytes(content.encode())
        write_json(root / ".release-please-manifest.json", {"Integrations/A": "1.0.0", "Integrations/B": "1.0.0"})
        write_json(root / "release/packages.json", {"schemaVersion": 1, "packages": {
            key: {"path": f"Integrations/{name}", "target": f"Kit{name}", "repository": repository,
                  "policies": {"TextShared": {"mode": "vendor"}}, "platforms": ["macOS 12"], "toolsVersion": "5.9"}
            for key, name, repository in [("sprig", "A", "experimental-integration-swift-sprig"),
                                          ("firebase", "B", "experimental-integration-swift-firebase")]}})
        sync_inventory(root)
        self.assertEqual(shared_markers(root), ["sprig", "firebase"])
        git(root, "init", "--initial-branch=main")
        commit(root, "test: two integrations vendor one package helper")
        for key, name in [("sprig", "A"), ("firebase", "B")]:
            export(key, "1.0.0", base / f"Kit{name}", root)
            vendored = (base / f"Kit{name}/Sources/Kit{name}/Vendored/TextShared/Normalizer.swift").read_text()
            self.assertIn("package enum Normalizer", vendored)
            self.assertNotIn("TextShared", (base / f"Kit{name}/Sources/Kit{name}/Kit{name}.swift").read_text())
            run(["swift", "build", *swift_options(base / f"state-{name}")], cwd=base / f"Kit{name}", env=anonymous_env())
        run(["swift", "build", *swift_options(base / "state-consumer")], cwd=base / "Consumer", env=anonymous_env())
        run([base / "state-consumer/build/debug/Consumer"])
        # Neither copy leaks past its own package, so the consumer cannot even name the helper.
        main = base / "Consumer/Sources/Consumer/main.swift"
        main.write_text(main.read_text() + 'print(Normalizer.normalize("Z"))\n')
        with self.assertRaisesRegex(RuntimeError, "cannot find 'Normalizer' in scope"):
            run(["swift", "build", *swift_options(base / "state-consumer")], cwd=base / "Consumer", env=anonymous_env())


if __name__ == "__main__":
    unittest.main()
