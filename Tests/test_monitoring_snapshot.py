"""Collector contract tests; fixtures are not live vulnerability evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from monitoring_snapshot import alert_records, collect


def alert(number=1, state="open"):
    return {"number": number, "state": state, "html_url": "https://example.invalid/alert",
            "dependency": {"manifest_path": "Package.resolved", "package": {"name": "vendor"}},
            "security_advisory": {"ghsa_id": "fixture-only"}}


class MonitoringSnapshotTests(unittest.TestCase):
    def fixture_reader(self, graph_failure=False, move_branch=False):
        observations = 0
        def reader(endpoint, paginate=False):
            nonlocal observations
            if "dependabot/alerts" in endpoint:
                return [[]]
            if "dependency-graph" in endpoint:
                if graph_failure:
                    raise RuntimeError("Missing graph access")
                return {"sbom": {"packages": []}}
            if "/commits/" in endpoint:
                observations += 1
                return {"sha": ("b" if move_branch and observations > 1 else "a") * 40}
            return {"id": 10, "full_name": "rudderlabs/experimental-swift-monorepo", "default_branch": "dev"}
        return reader

    def test_same_advisory_and_alert_number_keep_repository_identity(self):
        first = alert_records({"id": 10, "full_name": "source"}, [[alert()]])
        second = alert_records({"id": 20, "full_name": "publication"}, [[alert()]])
        self.assertEqual(first[0]["identity"], [10, 1])
        self.assertEqual(second[0]["identity"], [20, 1])
        self.assertEqual(first, alert_records({"id": 10, "full_name": "source"}, [[alert()]]))

    def test_every_native_state_and_no_patch_findings_are_retained(self):
        states = ["open", "fixed", "dismissed", "auto_dismissed"]
        records = alert_records({"id": 10, "full_name": "source"},
                                [[alert(n, state) for n, state in enumerate(states)]])
        self.assertEqual([r["state"] for r in records], states)
        self.assertTrue(all(r["vulnerability"] is None for r in records))

    def test_duplicate_pagination_is_a_collection_error(self):
        with self.assertRaisesRegex(ValueError, "Repeated alert"):
            alert_records({"id": 10, "full_name": "source"}, [[alert()], [alert()]])

    def test_failed_alert_read_is_not_an_empty_success(self):
        scope = {"mode": "fixture", "repositories": [{"name": "rudderlabs/experimental-swift-monorepo"}]}
        def reader(endpoint, paginate=False):
            if "dependabot/alerts" in endpoint:
                raise RuntimeError("Missing alert access")
            if "dependency-graph" in endpoint:
                return {"sbom": {"packages": []}}
            if "/commits/" in endpoint:
                return {"sha": "a" * 40}
            return {"id": 10, "full_name": scope["repositories"][0]["name"], "default_branch": "dev"}
        result = collect(scope, reader)
        self.assertFalse(result["complete"])
        self.assertEqual(result["repositories"][0]["alertsStatus"], "failed")
        self.assertNotIn("alerts", result["repositories"][0])
        self.assertEqual(result["repositories"][0]["graphStatus"], "collected")

    def test_zero_alerts_are_a_successful_read_with_graph_kept_for_review(self):
        scope = {"mode": "fixture", "repositories": [{"name": "rudderlabs/experimental-swift-monorepo"}]}
        result = collect(scope, self.fixture_reader())
        self.assertTrue(result["complete"])
        self.assertEqual(result["repositories"][0]["alerts"], [])
        self.assertEqual(result["repositories"][0]["graph"], {"sbom": {"packages": []}})
        self.assertNotIn("coveragePassed", result)

    def test_graph_failure_preserves_successful_alert_read(self):
        scope = {"mode": "fixture", "repositories": [{"name": "rudderlabs/experimental-swift-monorepo"}]}
        result = collect(scope, self.fixture_reader(graph_failure=True))
        self.assertFalse(result["complete"])
        self.assertEqual(result["repositories"][0]["alertsStatus"], "collected")
        self.assertNotIn("graph", result["repositories"][0])

    def test_moving_default_branch_keeps_observations_but_marks_incomplete(self):
        scope = {"mode": "fixture", "repositories": [{"name": "rudderlabs/experimental-swift-monorepo"}]}
        result = collect(scope, self.fixture_reader(move_branch=True))
        self.assertFalse(result["complete"])
        self.assertIn("Default branch changed", result["repositories"][0]["errors"][0])

    def test_production_scope_is_rejected_before_any_read(self):
        scope = {"mode": "fixture", "repositories": [{"name": "rudderlabs/rudder-sdk-swift"}]}
        with self.assertRaisesRegex(ValueError, "approved experimental repositories"):
            collect(scope, lambda *args, **kwargs: self.fail("Unexpected remote read"))


if __name__ == "__main__":
    unittest.main()
