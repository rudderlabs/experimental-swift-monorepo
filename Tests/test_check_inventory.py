"""One package list and one reviewed allowlist drive checks, workflows and generated GitHub files."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_inventory import problems, unpinned
from common import ROOT, allowlist, inventory, load, write_json
from generate_github import OTHER, generate, stale, write
from publication_status import collect, summarize
from release_plan import from_outputs, jobs

FIXTURE = ROOT / "Tests" / "Fixtures" / "demo"
SHA = "a" * 40


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        shutil.copytree(FIXTURE / "release", self.root / "release")
        shutil.copyfile(ROOT / "release-please-config.json", self.root / "release-please-config.json")
        write(self.root)

    def edit(self, name, change):
        path = self.root / "release" / name
        data = load(path)
        change(data)
        write_json(path, data)

    def add_zzz(self):
        self.edit("packages.json", lambda d: d["packages"].update(zzz={
            "path": "Integrations/Zzz", "target": "Zzz", "component": "integration-zzz",
            "repository": "experimental-integration-swift-zzz"}))
        self.edit("allowlist.json", lambda d: d["repositories"].update(zzz="experimental-integration-swift-zzz"))

    def test_root_passes_with_empty_inventory_and_reserved_allowlist_keys(self):
        self.assertEqual(problems(ROOT), [])
        self.assertEqual(inventory(ROOT), {})
        self.assertEqual(set(allowlist(ROOT)), {"sdk", "sprig", "firebase"})
        form = (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text()
        self.assertIn(f"        - {json.dumps(OTHER)}\n    validations:", form)
        self.assertEqual((ROOT / ".github/CODEOWNERS").read_text(), "* @rudderlabs/sdk_team\n")

    def test_fixture_passes(self):
        self.assertEqual(problems(self.root), [])

    def test_repository_differing_from_allowlist_fails(self):
        self.edit("packages.json", lambda d: d["packages"]["sprig"].update(repository="rudder-integration-sprig"))
        self.assertTrue(any(p.startswith("sprig: repository") for p in problems(self.root)))
        with self.assertRaisesRegex(ValueError, "not allowlisted with its repository: sprig"):
            inventory(self.root)

    def test_new_package_needs_only_inventory_and_allowlist_entries(self):
        self.add_zzz()
        self.assertEqual(stale(self.root), [".github/ISSUE_TEMPLATE/bug_report.yml",
                                            ".github/ISSUE_TEMPLATE/feature_request.yml",
                                            ".github/labeler.yml", ".github/labels.json"])
        write(self.root)
        self.assertEqual(problems(self.root), [])
        outputs = {}
        for path, version in [("Integrations/Zzz", "1.0.0"), ("Packages/DemoSDK", "0.2.0")]:
            outputs.update({path + "--release_created": "true", path + "--version": version, path + "--sha": SHA})
        plan = jobs(from_outputs(outputs, self.root))
        self.assertEqual(plan["sdk"], {"package": "sdk", "version": "0.2.0", "sha": SHA})
        self.assertEqual(plan["integrations"], [{"package": "zzz", "version": "1.0.0", "sha": SHA}])
        self.assertIn('"zzz"', (self.root / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text())
        self.assertIn('"Integrations/Zzz/**"', (self.root / ".github/labeler.yml").read_text())
        self.assertIn("pkg:zzz", [label["name"] for label in load(self.root / ".github/labels.json")])
        self.edit("allowlist.json", lambda d: d["repositories"].pop("zzz"))
        self.assertIn("zzz: repository 'experimental-integration-swift-zzz' differs from allowlist None",
                      problems(self.root))
        with self.assertRaisesRegex(ValueError, "zzz"):
            from_outputs(outputs, self.root)

    def test_stale_generated_file_fails(self):
        labels = self.root / ".github/labels.json"
        labels.write_text(labels.read_text().replace("pkg:sprig", "pkg:old"))
        (self.root / ".github/ISSUE_TEMPLATE/config.yml").unlink()
        self.assertEqual(problems(self.root), [
            "Stale generated file (run python3 scripts/generate_github.py): .github/ISSUE_TEMPLATE/config.yml",
            "Stale generated file (run python3 scripts/generate_github.py): .github/labels.json"])
        write(self.root)
        self.assertEqual(problems(self.root), [])

    def test_empty_inventory_generates_only_the_fallback_option(self):
        self.edit("packages.json", lambda d: d["packages"].clear())
        files = generate(self.root)
        self.assertIn(f"      options:\n        - {json.dumps(OTHER)}\n", files[".github/ISSUE_TEMPLATE/bug_report.yml"])
        self.assertEqual([l["name"] for l in json.loads(files[".github/labels.json"])], ["pkg:tooling", "from-public-repo"])

    def test_duplicate_component_or_path_fails(self):
        self.edit("packages.json", lambda d: d["packages"]["firebase"].update(
            component="integration-sprig", path="Integrations/Sprig"))
        self.assertEqual(problems(self.root), ["Duplicate path: Integrations/Sprig",
                                               "Duplicate component: integration-sprig"])

    def test_invalid_allowlist_fails(self):
        for change in (lambda d: d.update(owner="someone-else"),
                       lambda d: d["repositories"].update(zzz=d["repositories"]["sdk"]),
                       lambda d: d["repositories"].update({"Bad Key": "repo"})):
            with self.subTest():
                original = load(self.root / "release/allowlist.json")
                self.edit("allowlist.json", change)
                self.assertEqual(len(problems(self.root)), 1)
                write_json(self.root / "release/allowlist.json", original)

    def test_release_please_entries_need_a_matching_package(self):
        config = self.root / "release-please-config.json"
        data = load(config)
        data["packages"] = {"Integrations/Sprig": {"component": "integration-sprig"}}
        write_json(config, data)
        self.assertEqual(problems(self.root), [])
        for entry in ({"Integrations/Sprig": {"component": "sprig"}}, {"Integrations/Gone": {"component": "gone"}}):
            data["packages"] = entry
            write_json(config, data)
            self.assertEqual(len(problems(self.root)), 1)

    def test_actions_must_be_pinned_to_full_commit_shas(self):
        workflow = self.root / ".github/workflows/x.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("jobs:\n  a:\n    uses: ./.github/workflows/publish.yml\n  b:\n    steps:\n"
                            f"      - uses: actions/checkout@{SHA} # v4\n"
                            "      - uses: actions/checkout@v4\n"
                            f"      - name: x\n        uses: 'actions/cache@{SHA[:39]}'\n")
        self.assertEqual(unpinned(self.root), [".github/workflows/x.yml: actions/checkout@v4",
                                               f".github/workflows/x.yml: actions/cache@{SHA[:39]}"])
        self.assertEqual(len(problems(self.root)), 2)
        self.assertEqual(unpinned(ROOT), [])


class ReleaseConfigTests(unittest.TestCase):
    def test_changelog_sections_match_the_sdk_release_types(self):
        sections = {s["type"]: s["hidden"] for s in load(ROOT / "release-please-config.json")["changelog-sections"]}
        self.assertEqual(sections, {**dict.fromkeys(["feat", "fix", "perf", "refactor", "chore"], False),
                                    **dict.fromkeys(["docs", "test", "ci", "style", "build", "revert"], True)})

    def test_release_workflow_is_data_driven(self):
        release = (ROOT / ".github/workflows/release-please.yml").read_text()
        publish = (ROOT / ".github/workflows/publish.yml").read_text()
        for text in (release, publish):
            self.assertNotIn("sprig", text)
            self.assertNotIn("firebase", text)
        self.assertEqual(release.count("vars.EXPERIMENTAL_RELEASES_ENABLED == 'true'"), 1)
        for line in ["    name: publish (sdk)\n", "    name: publish (${{ matrix.package }})\n",
                     "        include: ${{ fromJSON(needs.intent.outputs.integrations) }}\n",
                     "    needs: [intent, sdk]\n", "    needs: [intent, sdk, integrations]\n",
                     "        run: python3 scripts/release_plan.py from-outputs\n"]:
            self.assertIn(line, release)
        self.assertIn("(needs.sdk.result == 'success' || needs.sdk.result == 'skipped')", release)
        self.assertIn("      group: experimental-publication-${{ inputs.package }}\n", publish)
        self.assertNotIn("type: choice", publish)
        self.assertIn("from common import allowlist, inventory", publish)
        try:
            import yaml
        except ImportError:
            return
        jobs_ = yaml.safe_load(release)["jobs"]
        self.assertEqual(jobs_["integrations"]["uses"], "./.github/workflows/publish.yml")
        self.assertEqual(jobs_["sdk"]["with"]["package"], "sdk")
        self.assertEqual(yaml.safe_load(publish)[True]["workflow_dispatch"]["inputs"]["package"]["type"], "string")


class PublicationStatusArtifactTests(unittest.TestCase):
    def test_each_matrix_leg_reports_through_its_own_artifact(self):
        plan = [{"package": "sdk", "version": "1.0.0", "sha": SHA}, {"package": "zzz", "version": "1.0.1", "sha": SHA},
                {"package": "late", "version": "1.0.0", "sha": SHA}]
        published = {"status": "published", "package": "sdk", "version": "1.0.0", "tag": "1.0.0",
                     "sourceCommit": SHA, "publicationCommit": "b" * 40}
        with tempfile.TemporaryDirectory() as temp:
            for name, result, job in [("publication-sdk-1.0.0", published, "success"),
                                      ("publication-zzz-1.0.1", {**published, "package": "zzz", "version": "1.0.1",
                                                                 "tag": "1.0.1"}, "failure")]:
                write_json(Path(temp) / name / "publication-result.json", result)
                write_json(Path(temp) / name / "publication-job.json", {"result": job})
            found = collect(plan, lambda name: Path(temp) / name if (Path(temp) / name).exists() else None)
        result = summarize(plan, found)
        self.assertEqual({k: v["status"] for k, v in result["packages"].items()},
                         {"sdk": "published", "zzz": "incomplete", "late": "incomplete"})
        self.assertEqual(result["packages"]["late"]["jobResult"], "missing")
        self.assertEqual(result["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
