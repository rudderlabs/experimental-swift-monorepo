"""PR CI plan and helpers: matrix, simulator choice, test targets, export manifest check, scope hint, ci-ok."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT
from package_ci import failed_needs, main, manifest_problems, matrix, scheme, scope_warnings, test_command, test_targets

FIXTURE = ROOT / "Tests/Fixtures/demo"
PICK = ROOT / "scripts/ci/pick-simulator.sh"
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()


def device(name, udid, available=True):
    return {"name": name, "udid": udid, "isAvailable": available, "state": "Shutdown"}


def runtime(platform, version):
    return f"com.apple.CoreSimulator.SimRuntime.{platform}-{version}"


class SimulatorTests(unittest.TestCase):
    def pick(self, devices):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "devices.json"
            path.write_text(json.dumps({"devices": devices}))
            return subprocess.run([PICK, path], capture_output=True, text=True)

    def test_first_iphone_on_the_newest_ios_runtime_with_an_iphone(self):
        result = self.pick({
            runtime("iOS", "9-3"): [device("iPhone 6s", "OLD")],
            runtime("iOS", "18-0"): [device("iPad Air", "IPAD"), device("iPhone 16", "A"), device("iPhone 16 Pro", "B")],
            runtime("iOS", "18-2"): [device("iPad Pro", "IPAD2"), device("iPhone 16", "GONE", available=False)],
            runtime("iOS", "17-5"): [device("iPhone 15", "C")],
            runtime("tvOS", "27-0"): [device("Apple TV", "TV")],
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "A")

    def test_numeric_versions_and_patch_runtimes(self):
        result = self.pick({runtime("iOS", "9-3"): [device("iPhone 6s", "OLD")],
                            runtime("iOS", "26-0"): [device("iPhone 17", "NEW")],
                            runtime("iOS", "26-0-1"): [device("iPhone Air", "PATCH")]})
        self.assertEqual(result.stdout.strip(), "PATCH")

    def test_no_iphone_fails_with_a_hint(self):
        result = self.pick({runtime("iOS", "18-0"): [device("iPad Air", "IPAD")], runtime("watchOS", "11-0"): []})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No available iPhone simulator", result.stderr)


class MatrixTests(unittest.TestCase):
    def test_empty_inventory_gives_an_empty_matrix_and_skips_the_package_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(FIXTURE / "release", root / "release")
            (root / "release/packages.json").write_text('{"schemaVersion": 1, "packages": {}}\n')
            # `[]` is exactly what the workflow compares against.
            self.assertEqual(json.dumps(matrix(root), separators=(",", ":")), "[]")
        for job in ("test", "export"):
            block = WORKFLOW.split(f"\n  {job}:\n", 1)[1].split("\n\n  ", 1)[0]
            self.assertIn("needs: packages\n", block)
            self.assertIn("if: needs.packages.outputs.packages != '[]'", block)
            self.assertIn("package: ${{ fromJSON(needs.packages.outputs.packages) }}", block)
            self.assertIn(f"name: {job} (${{{{ matrix.package }}}})", block)

    def test_fixture_inventory_gives_one_job_per_package_in_allowlist_order(self):
        self.assertEqual(matrix(FIXTURE), ["sdk", "sprig", "firebase"])

    def test_ci_ok_needs_every_job_and_always_runs(self):
        block = WORKFLOW.split("\n  ci-ok:\n", 1)[1]
        self.assertIn("if: always()", block)
        self.assertIn("needs: [packages, policy, lint, test, export]", block)
        jobs = [line[2:-1] for line in WORKFLOW.split("\njobs:\n", 1)[1].splitlines()
                if line.startswith("  ") and not line.startswith("   ") and line.endswith(":")]
        self.assertEqual(sorted(jobs), sorted(["packages", "policy", "lint", "test", "export", "ci-ok"]))

    def test_ci_ok_passes_skipped_and_fails_failed_or_cancelled(self):
        self.assertEqual(failed_needs({"policy": {"result": "success"}, "test": {"result": "skipped"}}), [])
        self.assertEqual(failed_needs({"policy": {"result": "failure"}, "lint": {"result": "success"},
                                       "test": {"result": "cancelled"}}), ["policy", "test"])
        needs = {"packages": {"result": "success"}, "export": {"result": "failure"}}
        os.environ["NEEDS"] = json.dumps(needs)
        self.addCleanup(os.environ.pop, "NEEDS")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["ci-ok"]), 1)
        self.assertIn("::error::Required jobs did not pass: export", output.getvalue())
        os.environ["NEEDS"] = json.dumps({"packages": {"result": "success"}, "test": {"result": "skipped"}})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["ci-ok"]), 0)


DEMO = {"name": "SwiftPublicationExperiment", "targets": [
    {"name": "DemoSDK", "type": "regular", "path": "Packages/DemoSDK/Sources/DemoSDK", "dependencies": []},
    {"name": "DemoSprig", "type": "regular", "path": "Integrations/Sprig/Sources/DemoSprig",
     "dependencies": [{"byName": ["DemoSDK", None]}]},
    {"name": "DemoTests", "type": "test", "path": None,
     "dependencies": [{"byName": ["DemoSDK", None]}, {"byName": ["DemoSprig", None]}]},
    {"name": "RudderIntegrationKitTests", "type": "test", "path": "Integrations/Kit/Tests/RudderIntegrationKitTests",
     "dependencies": [{"target": ["RudderIntegrationKit", None]}, {"byName": ["DemoSDK", None]}]},
]}


class TestTargetTests(unittest.TestCase):
    def test_tests_under_the_package_path_win(self):
        self.assertEqual(test_targets(DEMO, {"path": "Integrations/Kit", "target": "RudderIntegrationKit"}),
                         ["RudderIntegrationKitTests"])

    def test_otherwise_tests_that_depend_on_the_package_target(self):
        self.assertEqual(test_targets(DEMO, {"path": "Packages/DemoSDK", "target": "DemoSDK"}),
                         ["DemoTests", "RudderIntegrationKitTests"])
        self.assertEqual(test_targets(DEMO, {"path": "Integrations/Sprig", "target": "DemoSprig"}), ["DemoTests"])

    def test_command_uses_the_package_scheme_and_the_picked_simulator(self):
        command = test_command(DEMO, "sprig", {"path": "Integrations/Sprig", "target": "DemoSprig"}, "UDID-1")
        self.assertEqual(command, ["xcodebuild", "test", "-quiet", "-collect-test-diagnostics", "never", "-parallel-testing-enabled", "NO",
                                   "-test-timeouts-enabled", "YES", "-default-test-execution-time-allowance", "120", "-scheme", "SwiftPublicationExperiment-Package",
                                   "-destination", "platform=iOS Simulator,id=UDID-1", "-only-testing:DemoTests"])
        with self.assertRaisesRegex(ValueError, "no test target"):
            test_command(DEMO, "x", {"path": "Integrations/X", "target": "X"}, "UDID-1")

    def test_scheme_matches_what_xcode_generates(self):
        # One product (only the SDK imported): Xcode names the scheme after the package, with no -Package suffix.
        self.assertEqual(scheme("SwiftPublicationExperiment", ["SwiftPublicationExperiment"]), "SwiftPublicationExperiment")
        self.assertEqual(scheme("SwiftPublicationExperiment", ["DemoSDK", "SwiftPublicationExperiment-Package"]),
                         "SwiftPublicationExperiment-Package")
        command = test_command(DEMO, "sprig", {"path": "Integrations/Sprig", "target": "DemoSprig"}, "UDID-1",
                               ["SwiftPublicationExperiment"])
        self.assertIn("SwiftPublicationExperiment", command)
        with self.assertRaisesRegex(ValueError, "No Xcode scheme"):
            scheme("SwiftPublicationExperiment", ["Other"])


def dump(platforms, dependencies):
    return {"platforms": [{"platformName": n, "version": v, "options": []} for n, v in platforms],
            "dependencies": dependencies}


def remote(identity, location="https://github.com/example/{}.git"):
    return {"sourceControl": [{"identity": identity, "location": {"remote": [{"urlString": location.format(identity)}]},
                               "requirement": {"exact": ["1.0.0"]}}]}


class ExportManifestTests(unittest.TestCase):
    packages = {"sdk": {"repository": "experimental-rudder-sdk-swift"}}
    kit = {"platforms": ["iOS 15", "tvOS 15.4"], "policies": {"Core": {"mode": "external", "package": "sdk"}},
           "vendors": [{"identity": "vendor-kit", "product": "A"}, {"identity": "vendor-kit", "product": "B"}]}

    def test_matching_manifest_has_no_problems(self):
        data = dump([("ios", "15.0"), ("tvos", "15.4")],
                    [remote("experimental-rudder-sdk-swift"), remote("vendor-kit")])
        self.assertEqual(manifest_problems(data, self.kit, self.packages), [])

    def test_local_path_platforms_and_duplicate_vendor_lines_are_reported(self):
        data = dump([("ios", "16.0")], [remote("experimental-rudder-sdk-swift"), remote("vendor-kit"),
                                        remote("vendor-kit"), {"fileSystem": [{"identity": "core", "path": "/x"}]}])
        problems = "\n".join(manifest_problems(data, self.kit, self.packages))
        self.assertIn("platforms", problems)
        self.assertIn("non-Git package dependency", problems)
        self.assertIn("one per vendor/SDK", problems)


class ScopeHintTests(unittest.TestCase):
    packages = {"sdk": {"path": "Packages/RudderStackAnalytics"}, "sprig": {"path": "Integrations/Sprig"}}

    def test_scope_naming_an_untouched_package_warns(self):
        warnings = scope_warnings("fix(sprig): skip empty traits", ["Packages/RudderStackAnalytics/Sources/A.swift"],
                                  self.packages)
        self.assertEqual(len(warnings), 1)
        self.assertIn("(sprig)", warnings[0])
        self.assertIn("Integrations/Sprig/", warnings[0])

    def test_touched_unknown_missing_or_invalid_scopes_do_not_warn(self):
        paths = ["Integrations/Sprig/Sources/RudderIntegrationSprig/Sprig.swift"]
        for title in ["fix(sprig): skip empty traits", "feat(sprig)!: drop iOS 14", "ci(release): pin actions",
                      "fix: no scope", "Fix(sdk): not a valid title", "chore(deps): bump"]:
            self.assertEqual(scope_warnings(title, paths, self.packages), [], title)
        # A prefix of the folder name is not the folder.
        self.assertEqual(len(scope_warnings("fix(sprig): x", ["Integrations/SprigLegacy/A.swift"], self.packages)), 1)

    def test_several_scopes_are_checked_one_by_one(self):
        warnings = scope_warnings("feat(sdk,sprig): coordinated", ["Integrations/Sprig/README.md"], self.packages)
        self.assertEqual([w.split(")")[0] for w in warnings], ["The PR title scope (sdk"])

    def test_cli_never_fails(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["scope-hint", "--title", "fix(sdk): x", "--base", "0" * 40, "--head", "1" * 40]), 0)
        self.assertIn("::warning title=PR title scope::scope check skipped", output.getvalue())


if __name__ == "__main__":
    unittest.main()
