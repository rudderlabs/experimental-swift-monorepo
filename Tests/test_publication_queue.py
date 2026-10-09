"""Recovery comes from source releases, not transient Release Please outputs."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import ROOT
from publication_queue import queue
import json

FIXTURE = Path(__file__).resolve().parent / 'Fixtures' / 'demo'  # inventory and allowlist only; Git is modeled


class PublicationQueueTests(unittest.TestCase):
    def run_queue(self, published=False, wrong_source=False, release_missing=False, open_pr=False,
                  firebase=False):
        sha, pub = 'a' * 40, 'b' * 40
        intents = [{'tag_name': 'integration-sprig-0.1.1', 'draft': False, 'prerelease': False},
                   {'tag_name': 'unrelated-1.0.0', 'draft': False, 'prerelease': False},
                   {'tag_name': 'sdk-0.2.0', 'draft': True, 'prerelease': False}]
        if firebase:
            intents.append({'tag_name': 'integration-firebase-0.1.1', 'draft': False, 'prerelease': False})
        body = f'Temporary unsupported experiment.\n\nSource: {sha}\nPublication: {pub}\n'
        self.clones = []
        def command(args, **kwargs):
            if args[:2] == ['git', 'clone']:
                self.clones.append(args[3])
                return ''
            if 'experimental-swift-monorepo/releases?' in args[-1]:
                return json.dumps([intents])
            return json.dumps([[{'tag_name': '0.1.1', 'draft': False, 'body': body}]]
                              if published and not release_missing and 'sprig/releases?' in args[-1] else [[]])
        def git_command(repo, *args):
            if args[0] == 'rev-parse':
                return sha if repo == FIXTURE else pub
            if args[0] == 'for-each-ref':
                # Only Sprig has a public tag; Firebase is a fresh pending release.
                return 'refs/tags/0.1.1' if published and 'sprig' in str(self.clones[-1]) else ''
            return ''
        def pr(key, version):
            return {'state': 'open'} if open_pr and key == 'sprig' else None
        with patch('publication_queue.run', side_effect=command), \
             patch('publication_queue.git', side_effect=git_command), \
             patch('publication_queue.find_pr', side_effect=pr) as find_pr, \
             patch('publication_queue.verify_tree', return_value={
                 'sourceCommit': 'c' * 40 if wrong_source else sha, 'package': 'sprig', 'version': '0.1.1'}):
            pending, self.skipped = queue(FIXTURE)
            self.find_pr = find_pr.call_args_list
            return pending

    def test_pending_release_is_recovered_without_action_outputs(self):
        self.assertEqual(self.run_queue(), [{'package': 'sprig', 'version': '0.1.1', 'source_sha': 'a' * 40}])
        self.assertEqual(self.skipped, [])

    def test_complete_publication_is_not_repeated(self):
        self.assertEqual(self.run_queue(published=True), [])
        self.assertEqual(self.skipped, [])

    def test_tag_without_release_stays_in_recovery_queue(self):
        self.assertEqual(len(self.run_queue(published=True, release_missing=True)), 1)

    def test_conflicting_public_tag_is_reported_and_skipped(self):
        self.assertEqual(self.run_queue(published=True, wrong_source=True), [])
        self.assertEqual(len(self.skipped), 1)
        self.assertEqual(self.skipped[0]['status'], 'incomplete')
        self.assertIn('conflicts', self.skipped[0]['error'])

    def test_one_broken_item_does_not_stop_the_others(self):
        pending = self.run_queue(published=True, wrong_source=True, firebase=True)
        self.assertEqual(pending, [{'package': 'firebase', 'version': '0.1.1', 'source_sha': 'a' * 40}])
        self.assertEqual([(s['package'], s['status']) for s in self.skipped], [('sprig', 'incomplete')])

    def test_open_bot_pr_is_never_rebuilt(self):
        self.assertEqual(self.run_queue(open_pr=True, firebase=True),
                         [{'package': 'firebase', 'version': '0.1.1', 'source_sha': 'a' * 40}])
        self.assertEqual(self.skipped, [{'package': 'sprig', 'version': '0.1.1', 'source_sha': 'a' * 40,
                                         'status': 'awaiting_review'}])
        self.assertIn(call('sprig', '0.1.1'), self.find_pr)

    def test_release_body_matches_the_publisher(self):
        from common import text
        self.assertEqual(text('releaseBody', source='a' * 40, publication='b' * 40),
                         f'Temporary unsupported experiment.\n\nSource: {"a" * 40}\nPublication: {"b" * 40}\n')
        with tempfile.TemporaryDirectory() as temp:
            from publish import ensure_release
            path = ensure_release('sprig', '0.1.1', 'b' * 40, {'sourceCommit': 'a' * 40}, Path(temp) / 'remotes')
            self.assertEqual(json.loads(Path(path).read_text())['body'],
                             text('releaseBody', source='a' * 40, publication='b' * 40))

    def test_texts_have_one_source(self):
        texts = json.loads((ROOT / 'release/texts.json').read_text())
        self.assertIn('linear.app/rudderstack/issue/SDK-5388', texts['ticket'])
        for name in ('commit', 'takeoverCommit', 'pullRequestTitle', 'takeoverPullRequestTitle', 'pullRequestBody',
                     'bootstrapPullRequestBody', 'takeoverPullRequestBody', 'releaseTitle', 'releaseBody'):
            self.assertIn(name, texts)
        for name in ('pullRequestBody', 'bootstrapPullRequestBody', 'takeoverPullRequestBody'):
            self.assertIn('{ticket}', texts[name])
        for path in ('publish.py', 'reviewed_publication.py', 'publication_queue.py'):
            code = (ROOT / 'scripts' / path).read_text()
            self.assertRegex(code, r'from common import (\([^)]*|[^\n(]*)\btext\b')
            for fragment in ('Temporary unsupported', 'sdk-5388', 'SDK-5388', 'linear.app', 'publish experimental',
                             'Experimental {'):
                self.assertNotIn(fragment, code, path)

    def test_recover_workflow_has_no_inputs_and_scans_all_packages(self):
        workflow = (ROOT / '.github/workflows/complete-publication.yml').read_text()
        self.assertIn('on:\n  workflow_dispatch:\npermissions:', workflow)
        self.assertNotIn('inputs:', workflow)
        self.assertNotIn('schedule:', workflow)
        pending = workflow.split('  pending:\n')[1].split('\n  complete:\n')[0]
        self.assertIn('step-security/harden-runner@', pending)
        self.assertIn('run: python3 scripts/publication_queue.py\n', pending)
        self.assertIn("if: ${{ !cancelled() && needs.pending.outputs.pending == 'true' }}", workflow)
        self.assertIn('Merged a bot PR? Press Recover.', (ROOT / 'README.md').read_text())


if __name__ == '__main__':
    unittest.main()
