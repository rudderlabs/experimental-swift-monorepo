"""Failed, skipped, or mismatched publication must not report customer success."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publication_status import summarize
from release_plan import from_outputs


class PublicationStatusTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.plan = [{'package': 'sprig', 'version': '0.1.1', 'sha': self.sha}]
        self.jobs = {'sprig': {'result': 'success', 'outputs': {
            'status': 'published', 'package': 'sprig', 'version': '0.1.1', 'tag': '0.1.1',
            'sourceCommit': self.sha, 'publicationCommit': 'b' * 40}}}

    def test_pending_release_outputs_do_not_publish(self):
        self.assertEqual(from_outputs({'Integrations/Sprig--release_created': 'false',
                                       'Integrations/Sprig--version': '0.1.1'}), [])
        self.assertEqual(summarize([], self.jobs)['status'], 'no_release')

    def test_verified_publication_reports_success(self):
        self.assertEqual(summarize(self.plan, self.jobs)['status'], 'published')

    def test_failed_cancelled_skipped_or_missing_job_is_incomplete(self):
        for result in ['failure', 'cancelled', 'skipped', 'missing']:
            with self.subTest(result=result):
                self.jobs['sprig']['result'] = result
                self.assertEqual(summarize(self.plan, self.jobs)['status'], 'incomplete')
        self.assertEqual(summarize(self.plan, {})['status'], 'incomplete')

    def test_wrong_source_tag_or_commit_is_incomplete(self):
        for field, value in [('sourceCommit', 'c' * 40), ('tag', '0.1.0'),
                             ('publicationCommit', 'main'), ('status', 'pending')]:
            with self.subTest(field=field):
                old = self.jobs['sprig']['outputs'][field]
                self.jobs['sprig']['outputs'][field] = value
                self.assertEqual(summarize(self.plan, self.jobs)['status'], 'incomplete')
                self.jobs['sprig']['outputs'][field] = old

    def test_partial_batch_keeps_verified_package_and_reports_incomplete(self):
        self.plan.insert(0, {'package': 'sdk', 'version': '0.1.1', 'sha': self.sha})
        self.jobs['sdk'] = {'result': 'failure'}
        result = summarize(self.plan, self.jobs)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['packages']['sprig']['status'], 'published')
        self.assertEqual(result['packages']['sdk']['status'], 'incomplete')

    def test_waiting_states_are_not_customer_success(self):
        for state in ('awaiting_review', 'awaiting_dependency'):
            self.jobs['sprig']['outputs']['status'] = state
            result = summarize(self.plan, self.jobs)
            self.assertEqual(result['status'], 'awaiting_publication')
            self.assertEqual(result['packages']['sprig']['status'], state)
            self.assertIsNone(result['packages']['sprig']['publicationCommit'])

    def test_waiting_wrong_source_is_incomplete(self):
        self.jobs['sprig']['outputs'].update(status='awaiting_review', sourceCommit='c' * 40)
        self.assertEqual(summarize(self.plan, self.jobs)['status'], 'incomplete')
