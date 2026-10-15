"""CI plan (ci_plan.py, D34): what a PR or push tests and exports, and whether the policy job runs."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT, commit, git, write_json
from ci_plan import changed, ci_plan, imported, main, push_plan

FIXTURE = ROOT / "Tests/Fixtures/demo"
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()


class CiPlanTests(unittest.TestCase):
    """D34: a PR or push checks what it affects."""
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

    def test_pre_push_tests_only_the_changed_packages(self):
        # The pre-push hook leaves the dependents to CI; shared build inputs still select every package.
        sdk = "Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift"
        self.assertEqual(ci_plan([sdk], self.root, with_dependents=False),
                         {"test": ["sdk"], "export": ["sdk"], "policy": False})
        self.assertEqual(ci_plan(["Package.swift", sdk], self.root, with_dependents=False)["test"], self.every)

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
                     "scripts/project.py", "scripts/common.py", "scripts/dependency_policy.py"]:
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

    def test_plan_only_changes_run_only_the_python_tests(self):
        # The plan, the path-to-package rules, the git hooks and the Makefile do not change how a package job runs.
        for path in ["scripts/ci_plan.py", "scripts/release_plan.py", "scripts/git-hooks/pre-push", "Makefile",
                     "Tests/test_ci_plan.py"]:
            self.assertEqual(self.plan(path), {"test": [], "export": [], "policy": True}, path)
        self.assertEqual(self.plan("scripts/ci_plan.py", "scripts/git-hooks/pre-push", "Makefile", self.sprig),
                         {"test": ["sprig"], "export": ["sprig"], "policy": True})

    def test_build_scripts_are_what_the_package_job_runner_imports(self):
        build = imported()
        self.assertIn("scripts/package_ci.py", build)
        self.assertIn("scripts/project.py", build)  # export check builds the exported package with project.py
        self.assertNotIn("scripts/ci_plan.py", build)
        # The release flow is not a package build input: a release-script change runs only the Python tests.
        for path in ["scripts/publish.py", "scripts/reviewed_publication.py", "scripts/publication_queue.py",
                     "scripts/maintenance_branch.py", "scripts/release_notes.py", "scripts/sync_back.py"]:
            self.assertNotIn(path, build)
            self.assertEqual(self.plan(path), {"test": [], "export": [], "policy": True}, path)
        # If package_ci.py imported ci_plan.py, every plan change would select every package again.
        tree = ast.parse((ROOT / "scripts/package_ci.py").read_text())
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn("ci_plan", modules)

    def test_workflow_plans_a_pr_from_its_base_and_a_push_from_its_previous_commit(self):
        self.assertEqual(ci_plan(None, self.root), {"test": self.every, "export": self.every, "policy": True})
        block = WORKFLOW.split("\n  packages:\n", 1)[1].split("\n  policy:\n", 1)[0]
        self.assertIn('python3 scripts/ci_plan.py --base "$BASE"', block)
        self.assertIn("BASE: ${{ github.event.pull_request.base.sha }}", block)
        self.assertIn('python3 scripts/ci_plan.py --before "$BEFORE"', block)
        self.assertIn("BEFORE: ${{ github.event.before }}", block)
        self.assertIn("fetch-depth: 0", block)
        self.assertIn("if: needs.packages.outputs.policy == 'true'", WORKFLOW.split("\n  policy:\n", 1)[1])

    def test_cli_prints_the_plan_and_the_affected_packages(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}  # the policy job sets it
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--all"]), 0)
        self.assertEqual(set(json.loads(output.getvalue())), {"test", "export", "policy"})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--all", "--affected"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--before", "HEAD", "--affected"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--all", "--no-dependents"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([])

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

    def test_push_checks_what_changed_since_the_previous_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(self.root, root, dirs_exist_ok=True)
            git(root, "init", "--initial-branch=main")
            first = commit(root, "test: baseline")
            sdk = root / "Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift"
            sdk.write_text(sdk.read_text() + "// change\n")
            before = commit(root, "fix(sdk): change")
            (root / self.sprig).write_text((root / self.sprig).read_text() + "// change\n")
            commit(root, "chore(release): sprig")
            # Only the pushed commits count: the earlier SDK change does not select its dependents again.
            self.assertEqual(push_plan(before, root), {"test": ["sprig"], "export": ["sprig"], "policy": False})
            self.assertEqual(push_plan(first, root), {"test": self.every, "export": ["sdk", "sprig"], "policy": False})

    def test_push_with_an_unknown_previous_commit_checks_everything(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(self.root, root, dirs_exist_ok=True)
            git(root, "init", "--initial-branch=main")
            commit(root, "test: baseline")
            everything = {"test": self.every, "export": self.every, "policy": True}
            # A new branch (all zeros), no value, and a force-pushed-over commit the checkout lacks.
            for before in ["0" * 40, "", "1234567890abcdef1234567890abcdef12345678"]:
                self.assertEqual(push_plan(before, root), everything, repr(before))



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


if __name__ == "__main__":
    unittest.main()
