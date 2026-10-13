"""PR CI plan and helpers: CI plan, matrix, simulator choice, test targets, export manifest check, scope hint, ci-ok."""
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
from unittest.mock import patch
from xml.etree import ElementTree

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT, commit, git, write_json
from package_ci import (changed, ci_plan, failed_needs, failures, main, manifest_problems, matrix, scope_warnings, test_command,
                        test_scheme, test_targets)

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
            self.assertIn(f"if: needs.packages.outputs.{job} != '[]'", block)
            self.assertIn(f"package: ${{{{ fromJSON(needs.packages.outputs.{job}) }}}}", block)
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


class CiPlanTests(unittest.TestCase):
    """D34: a PR checks what it affects; push to main checks everything."""
    every = ["sdk", "sprig", "firebase"]
    sprig = "Integrations/Sprig/Sources/DemoSprig/DemoSprig.swift"

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        shutil.copytree(FIXTURE, cls.root, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".build", ".swiftpm"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def plan(self, *paths):
        return ci_plan(list(paths), self.root)

    def test_package_change_selects_only_that_package(self):
        self.assertEqual(self.plan(self.sprig), {"test": ["sprig"], "export": ["sprig"], "policy": False})

    def test_sdk_change_also_tests_its_dependents_but_exports_only_the_sdk(self):
        # Exported integrations build against the published SDK tag, so only their tests see the local SDK.
        self.assertEqual(self.plan("Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift"),
                         {"test": self.every, "export": ["sdk"], "policy": False})

    def test_dependents_come_from_the_inventory_so_a_new_integration_needs_no_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(self.root / "release", root / "release")
            data = json.loads((root / "release/packages.json").read_text())
            data["packages"]["kit"] = {"path": "Integrations/Kit", "target": "Kit", "repository": "kit",
                                       "policies": {"DemoSprig": {"mode": "external", "package": "sprig"}}}
            for package in data["packages"].values():
                package["policies"] = {k: v for k, v in package["policies"].items() if v["mode"] == "external"}
            write_json(root / "release/packages.json", data)
            allowlist = json.loads((root / "release/allowlist.json").read_text())
            allowlist["repositories"]["kit"] = "kit"
            write_json(root / "release/allowlist.json", allowlist)
            # write_json sorts the allowlist, so the plan lists keys alphabetically here.
            self.assertEqual(ci_plan(["Packages/DemoSDK/A.swift"], root)["test"], ["firebase", "kit", "sdk", "sprig"])
            self.assertEqual(ci_plan(["Integrations/Sprig/A.swift"], root)["test"], ["kit", "sprig"])
            self.assertEqual(ci_plan(["Integrations/Kit/A.swift"], root)["test"], ["kit"])

    def test_vendored_shared_source_selects_the_packages_that_vendor_it(self):
        self.assertEqual(self.plan("Shared/DemoShared/DemoNormalizer.swift"),
                         {"test": ["sprig", "firebase"], "export": ["sprig", "firebase"], "policy": True})

    def test_shared_build_inputs_select_every_package(self):
        for path in ["Package.swift", "Package.resolved", ".swiftlint.yml", "release/allowlist.json",
                     ".github/workflows/ci.yml", "scripts/ci/pick-simulator.sh", "scripts/package_ci.py",
                     "scripts/project.py", "scripts/common.py"]:
            plan = self.plan(path, self.sprig)
            self.assertEqual((plan["test"], plan["export"]), (self.every, self.every), path)
        self.assertEqual(self.plan(".swiftlint.yml")["policy"], False)

    def test_docs_select_nothing(self):
        self.assertEqual(self.plan("README.md", "docs/release-boundaries/README.md", "Integrations/Sprig/README.md"),
                         {"test": [], "export": [], "policy": False})

    def test_license_and_release_templates_export_everything_without_tests(self):
        self.assertEqual(self.plan("LICENSE"), {"test": [], "export": self.every, "policy": False})
        self.assertEqual(self.plan("release/templates/README-block.md", self.sprig),
                         {"test": ["sprig"], "export": self.every, "policy": True})

    def test_policy_runs_only_for_tooling_and_policy_inputs(self):
        for path in ["scripts/dependabot_sync.py", "release/texts.json", "Tests/test_anchor.py", ".github/labeler.yml",
                     "Makefile", "Package.swift", "Package.resolved", ".release-please-manifest.json",
                     "release-please-config.json", "Integrations/Sprig/dependency-requirements.json",
                     "Integrations/Sprig/shared-source.json", "Shared/DemoShared/DemoNormalizer.swift"]:
            self.assertTrue(self.plan(path)["policy"], path)
        for path in [self.sprig, "README.md", "LICENSE", "Examples/Sprig/ContentView.swift", ".gitignore"]:
            self.assertFalse(self.plan(path)["policy"], path)
        # A tooling script package_ci.py does not import changes no package job.
        self.assertEqual(self.plan("scripts/dependabot_sync.py"), {"test": [], "export": [], "policy": True})

    def test_push_to_main_checks_everything(self):
        self.assertEqual(ci_plan(None, self.root), {"test": self.every, "export": self.every, "policy": True})
        block = WORKFLOW.split("\n  packages:\n", 1)[1].split("\n  policy:\n", 1)[0]
        self.assertIn("ci-plan --all", block)
        self.assertIn('ci-plan --base "$BASE"', block)
        self.assertIn("BASE: ${{ github.event.pull_request.base.sha }}", block)
        self.assertIn("if: needs.packages.outputs.policy == 'true'", WORKFLOW.split("\n  policy:\n", 1)[1])

    def test_changed_paths_come_from_the_branch_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(self.root, root, dirs_exist_ok=True)
            git(root, "init", "--initial-branch=main")
            base = commit(root, "test: baseline")
            git(root, "switch", "-c", "feature")
            (root / self.sprig).write_text((root / self.sprig).read_text() + "// change\n")
            commit(root, "fix(sprig): change")
            self.assertEqual(changed(base, root), [self.sprig])
            self.assertEqual(ci_plan(changed(base, root), root, base),
                             {"test": ["sprig"], "export": ["sprig"], "policy": False})



class InventoryPlanTests(unittest.TestCase):
    """A release/packages.json change selects only the packages whose entry changed (real git history)."""
    every = ["firebase", "sdk", "sprig"]  # write_json sorts the allowlist, so plans list keys alphabetically here.
    inventory = "release/packages.json"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".build", ".swiftpm"))
        # A new package is allowlisted (sdk_team approval) before its entry lands, so the base already lists it.
        allowlist = json.loads((self.root / "release/allowlist.json").read_text())
        allowlist["repositories"]["kit"] = "kit"
        write_json(self.root / "release/allowlist.json", allowlist)
        git(self.root, "init", "--initial-branch=main")
        self.base = commit(self.root, "test: baseline")
        git(self.root, "switch", "-c", "feature")

    def change(self, edit=None, text=None, also=()):
        """Commit an inventory edit (`edit(data)`) or new file text and return the PR plan."""
        path = self.root / self.inventory
        if edit:
            data = json.loads(path.read_text())
            edit(data)
            write_json(path, data)
        if text is not None:
            path.write_text(text)
        commit(self.root, "test: inventory change")
        paths = changed(self.base, self.root)
        self.assertEqual(paths, sorted([self.inventory, *also]))
        return ci_plan(paths, self.root, self.base)

    def test_integration_entry_change_selects_only_that_integration(self):
        plan = self.change(lambda d: d["packages"]["firebase"]["platforms"].remove("macOS 12"))
        self.assertEqual(plan, {"test": ["firebase"], "export": ["firebase"], "policy": True})

    def test_sdk_entry_change_tests_its_dependents_but_exports_only_the_sdk(self):
        plan = self.change(lambda d: d["packages"]["sdk"]["platforms"].append("tvOS 15"))
        self.assertEqual(plan, {"test": self.every, "export": ["sdk"], "policy": True})

    def test_added_entry_selects_the_new_package(self):
        entry = {"path": "Integrations/Kit", "target": "Kit", "repository": "kit", "policies": {}}
        plan = self.change(lambda d: d["packages"].update(kit=entry))
        self.assertEqual(plan, {"test": ["kit"], "export": ["kit"], "policy": True})

    def test_removed_entry_tests_the_remaining_dependents_only(self):
        # A removed package has no job left; packages that still depend on it would be tested.
        plan = self.change(lambda d: d["packages"].pop("sprig"))
        self.assertEqual(plan, {"test": [], "export": [], "policy": True})

    def test_field_outside_packages_selects_every_package(self):
        plan = self.change(lambda d: d.update(schemaVersion=2))
        self.assertEqual(plan, {"test": self.every, "export": self.every, "policy": True})

    def test_reformat_or_reorder_selects_no_package_but_policy_still_runs(self):
        # Policy checks own the file's format, so a reformat-only change still runs them.
        data = json.loads((self.root / self.inventory).read_text())
        data["packages"] = dict(reversed(list(data["packages"].items())))
        plan = self.change(text=json.dumps(data, indent=4))
        self.assertEqual(plan, {"test": [], "export": [], "policy": True})

    def test_file_missing_at_base_selects_every_package(self):
        git(self.root, "switch", "main")
        git(self.root, "rm", "-q", "--cached", self.inventory)
        git(self.root, "commit", "-q", "-m", "test: no inventory")
        self.base = git(self.root, "rev-parse", "HEAD")
        git(self.root, "switch", "-C", "feature")
        plan = self.change(lambda d: d["packages"]["firebase"]["platforms"].remove("macOS 12"))
        self.assertEqual(plan, {"test": self.every, "export": self.every, "policy": True})

    def test_entry_change_with_a_package_change_selects_both(self):
        path = self.root / CiPlanTests.sprig
        path.write_text(path.read_text() + "// change\n")
        plan = self.change(lambda d: d["packages"]["firebase"]["platforms"].remove("macOS 12"),
                           also=[CiPlanTests.sprig])
        self.assertEqual(plan, {"test": ["firebase", "sprig"], "export": ["firebase", "sprig"], "policy": True})


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

    def test_command_uses_the_package_test_scheme_and_the_picked_simulator(self):
        command = test_command(DEMO, "sprig", {"path": "Integrations/Sprig", "target": "DemoSprig"}, "UDID-1", "/tmp/r.xcresult")
        self.assertEqual(command, ["xcodebuild", "test", "-quiet", "-collect-test-diagnostics", "never", "-parallel-testing-enabled", "NO",
                                   "-test-timeouts-enabled", "YES", "-default-test-execution-time-allowance", "120", "-scheme", "package-ci-sprig",
                                   "-destination", "platform=iOS Simulator,id=UDID-1", "-resultBundlePath", "/tmp/r.xcresult",
                                   "-only-testing:DemoTests"])
        with self.assertRaisesRegex(ValueError, "no test target"):
            test_command(DEMO, "x", {"path": "Integrations/X", "target": "X"}, "UDID-1", "/tmp/r.xcresult")

    def test_failures_print_each_failed_test_with_its_message(self):
        summary = {"testFailures": [{"testIdentifierString": "AnalyticsTests/testTrack()",
                                     "failureText": "Expectation failed: count == 1\n"}]}
        with patch("package_ci.run", return_value=json.dumps(summary)):
            self.assertEqual(failures("r.xcresult"), ["AnalyticsTests/testTrack(): Expectation failed: count == 1"])
        with patch("package_ci.run", side_effect=RuntimeError("Command failed: xcrun ['xcresulttool']\nno bundle")):
            self.assertEqual(failures("r.xcresult"), ["(no failure details: Command failed: xcrun ['xcresulttool'])"])

    def test_scheme_builds_and_tests_only_the_package_test_targets_and_is_removed_after_the_run(self):
        # `-only-testing` limits what runs, not what builds: the scheme must hold only this package's test targets.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / ".swiftpm/xcode/xcshareddata/xcschemes"
            with test_scheme(DEMO, "sdk", {"path": "Packages/DemoSDK", "target": "DemoSDK"}, root) as name:
                self.assertEqual(name, "package-ci-sdk")
                scheme = ElementTree.parse(folder / "package-ci-sdk.xcscheme").getroot()
                built, tested = ([e.find("BuildableReference").get("BlueprintName") for e in scheme.iter(tag)]
                                 for tag in ("BuildActionEntry", "TestableReference"))
                self.assertEqual(built, ["DemoTests", "RudderIntegrationKitTests"])
                self.assertEqual(tested, ["DemoTests", "RudderIntegrationKitTests"])
                self.assertEqual({e.get("buildForTesting") for e in scheme.iter("BuildActionEntry")}, {"YES"})
                self.assertEqual({e.get("buildForRunning") for e in scheme.iter("BuildActionEntry")}, {"NO"})
            self.assertEqual(list(folder.iterdir()), [])
            with self.assertRaises(RuntimeError):
                with test_scheme(DEMO, "sprig", {"path": "Integrations/Sprig", "target": "DemoSprig"}, root):
                    raise RuntimeError("xcodebuild interrupted")
            self.assertEqual(list(folder.iterdir()), [])

    def test_swiftpm_folder_is_git_ignored(self):
        self.assertIn(".swiftpm/", (ROOT / ".gitignore").read_text().splitlines())


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
