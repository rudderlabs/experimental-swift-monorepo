"""Recovery comes from source releases, not transient Release Please outputs."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import ROOT
from publication_queue import queue
from reviewed_publication import BOT
import json

FIXTURE = Path(__file__).resolve().parent / 'Fixtures' / 'demo'  # inventory and allowlist only; Git is modeled


class PublicationQueueTests(unittest.TestCase):
    def run_queue(self, published=False, wrong_source=False, release_missing=False, open_pr=False,
                  firebase=False, body=None, draft=False, prs=None, later=False, lines=None):
        sha, pub = 'a' * 40, 'b' * 40
        intents = [{'tag_name': 'integration-sprig-0.1.1', 'draft': False, 'prerelease': False},
                   {'tag_name': 'unrelated-1.0.0', 'draft': False, 'prerelease': False},
                   {'tag_name': 'sdk-0.2.0', 'draft': True, 'prerelease': False}]
        # `lines`: version -> source line (main, release/<key>-X.Y.x, or an error for neither).
        intents += [{'tag_name': f'integration-sprig-{v}', 'draft': False, 'prerelease': False}
                    for v in lines or {} if v != '0.1.1']
        def line(root, key, sha, version):
            value = (lines or {}).get(version, 'main')
            if isinstance(value, Exception):
                raise value
            return value
        if later:
            intents.append({'tag_name': 'integration-sprig-0.1.2', 'draft': False, 'prerelease': False})
        if firebase:
            intents.append({'tag_name': 'integration-firebase-0.1.1', 'draft': False, 'prerelease': False})
        # Releases 1.4.1, 1.0.1 and 1.1.3 were created with these earlier texts.
        body = body or f'Temporary unsupported experiment.\n\nSource: {sha}\nPublication: {pub}\n'
        self.clones = []
        def command(args, **kwargs):
            if args[:2] == ['git', 'clone']:
                self.clones.append(args[3])
                return ''
            if 'experimental-swift-monorepo/releases?' in args[-1]:
                return json.dumps([intents])
            return json.dumps([[{'tag_name': '0.1.1', 'draft': draft, 'body': body}]]
                              if published and not release_missing and 'sprig/releases?' in args[-1] else [[]])
        def git_command(repo, *args):
            if args[0] == 'rev-parse':
                return sha if repo == FIXTURE else pub
            if args[0] == 'for-each-ref':
                # Only Sprig has a public tag; Firebase is a fresh pending release.
                return 'refs/tags/0.1.1' if published and 'sprig' in str(self.clones[-1]) else ''
            return ''
        def pr(key, version, mode='normal'):
            if prs is not None:
                return prs.get((key, version, mode))
            return {'state': 'open'} if open_pr and key == 'sprig' else None
        with patch('publication_queue.run', side_effect=command), \
             patch('publication_queue.git', side_effect=git_command), \
             patch('publication_queue.source_line', side_effect=line), \
             patch('publication_queue.find_pr', side_effect=pr) as find_pr, \
             patch('reviewed_publication.find_pr', side_effect=pr), \
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

    def bot_pr(self, version, state='closed', merged=False, labels=(), prefix='publication', base='main'):
        repository = {'full_name': 'rudderlabs/experimental-integration-swift-sprig'}
        return {'state': state, 'merged': merged, 'labels': [{'name': n} for n in labels],
                'user': {'login': BOT}, 'base': {'ref': base, 'repo': repository},
                'head': {'ref': f'{prefix}/sprig/{version}', 'repo': repository}}

    def test_main_and_maintenance_versions_queue_together_each_on_its_base(self):
        lines = {'0.1.1': 'main', '0.2.0': 'main', '0.1.2': 'release/sprig-0.1.x', '0.1.3': 'release/sprig-0.1.x',
                 '0.1.9': ValueError('Source commit is on neither main nor release/sprig-0.1.x')}
        # 0.1.2 was discarded on the public release/0.1.x: found only when its PR is checked against that base.
        prs = {('sprig', '0.1.2', 'normal'): self.bot_pr('0.1.2', labels=['abandon'], base='release/0.1.x'),
               ('sprig', '0.1.3', 'normal'): self.bot_pr('0.1.3', state='open', base='release/0.1.x')}
        pending = self.run_queue(prs=prs, lines=lines)
        self.assertEqual([i['version'] for i in pending], ['0.1.1', '0.2.0'])
        self.assertEqual(pending[1], {'package': 'sprig', 'version': '0.2.0', 'source_sha': 'a' * 40})
        self.assertEqual({s['version']: s['status'] for s in self.skipped},
                         {'0.1.9': 'incomplete', '0.1.2': 'abandoned', '0.1.3': 'awaiting_review'})
        self.assertIn('neither main nor release/sprig-0.1.x', self.skipped[0]['error'])
        # A pending maintenance version is queued like any other, in version order with the main line.
        del prs[('sprig', '0.1.3', 'normal')]
        self.assertEqual([i['version'] for i in self.run_queue(prs=prs, lines=lines)], ['0.1.1', '0.1.3', '0.2.0'])
        # Checked against main instead, the maintenance PR is a broken item, not an abandoned version.
        lines['0.1.2'] = 'main'
        self.run_queue(prs=prs, lines=lines)
        self.assertEqual({s['version']: s['status'] for s in self.skipped}, {'0.1.9': 'incomplete', '0.1.2': 'incomplete'})

    def test_abandoned_version_is_reported_and_a_later_version_proceeds(self):
        later = {'package': 'sprig', 'version': '0.1.2', 'source_sha': 'a' * 40}
        merged = self.bot_pr('0.1.1', merged=True)
        for name, prs in (('closed with label', {('sprig', '0.1.1', 'normal'): self.bot_pr('0.1.1', labels=['abandon'])}),
                          ('merged then reverted', {('sprig', '0.1.1', 'normal'): merged,
                                                    ('sprig', '0.1.1', 'abandon'): self.bot_pr(
                                                        '0.1.1', merged=True, prefix='abandon')})):
            with self.subTest(name):
                self.assertEqual(self.run_queue(prs=prs, later=True), [later])
                self.assertEqual(self.skipped, [{'package': 'sprig', 'version': '0.1.1', 'source_sha': 'a' * 40,
                                                 'status': 'abandoned'}])

    def test_unlabeled_close_or_pending_revert_is_never_abandoned(self):
        closed = {('sprig', '0.1.1', 'normal'): self.bot_pr('0.1.1', labels=['wontfix'])}
        # Still pending: Tag & Release Packages stops on it with the review-required error.
        self.assertEqual(len(self.run_queue(prs=closed)), 1)
        reverting = {('sprig', '0.1.1', 'normal'): self.bot_pr('0.1.1', merged=True),
                     ('sprig', '0.1.1', 'abandon'): self.bot_pr('0.1.1', state='open', prefix='abandon')}
        self.assertEqual(self.run_queue(prs=reverting), [])
        self.assertEqual([s['status'] for s in self.skipped], ['abandoning'])

    def test_modeled_release_is_written_once_and_kept(self):
        from common import text
        from publish import ensure_release
        with tempfile.TemporaryDirectory() as temp:
            remotes = Path(temp) / 'remotes'
            path = ensure_release('sprig', '0.1.1', 'b' * 40, remotes, lambda: 'Notes\n')
            self.assertEqual(json.loads(Path(path).read_text())['body'], 'Notes\n')
            self.assertEqual(json.loads(Path(path).read_text())['title'], text('releaseTitle', version='0.1.1'))
            # A later run with other notes keeps the record; another commit for the tag is a conflict.
            ensure_release('sprig', '0.1.1', 'b' * 40, remotes, lambda: self.fail('rendered again'))
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                ensure_release('sprig', '0.1.1', 'c' * 40, remotes, lambda: '')

    def test_existing_release_with_earlier_texts_is_accepted(self):
        from publish import ensure_release
        old = {'tag_name': '1.0.1', 'draft': False, 'name': 'Experimental 1.0.1', 'html_url': 'https://x/1.0.1',
               'body': f'Temporary unsupported experiment.\n\nSource: {"a" * 40}\nPublication: {"b" * 40}\n'}
        for releases, error in (([old], None), ([{**old, 'draft': True}], 'differs'), ([old, old], 'differs')):
            with patch('publish.run', return_value=json.dumps([releases])) as command:
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        ensure_release('sprig', '1.0.1', 'b' * 40, None, lambda: self.fail('rendered'))
                else:
                    self.assertEqual(ensure_release('sprig', '1.0.1', 'b' * 40, None,
                                                    lambda: self.fail('rendered')), 'https://x/1.0.1')
                self.assertEqual(command.call_count, 1)

    def test_release_with_earlier_texts_counts_as_complete_but_a_draft_conflicts(self):
        self.assertEqual(self.run_queue(published=True, body='# New format\n'), [])
        self.assertEqual(self.skipped, [])
        self.assertEqual(self.run_queue(published=True, draft=True), [])
        self.assertEqual([(s['package'], s['status']) for s in self.skipped], [('sprig', 'incomplete')])

    def test_texts_have_one_source(self):
        texts = json.loads((ROOT / 'release/texts.json').read_text())
        for name in ('commit', 'takeoverCommit', 'pullRequestTitle', 'takeoverPullRequestTitle', 'pullRequestBody',
                     'bootstrapPullRequestBody', 'takeoverPullRequestBody', 'releaseTitle', 'notesHeading',
                     'whatsChanged', 'pullRequestLine', 'fullChangelog', 'releaseFooter'):
            self.assertIn(name, texts)
        self.assertEqual(texts['commit'], 'chore(release): {version}')
        self.assertEqual(texts['pullRequestTitle'], 'chore(release): {version}')
        self.assertEqual(texts['releaseTitle'], '{version}')
        for name, value in texts.items():
            for fragment in ('sdk-5388', 'SDK-5388', 'linear.app', '{ticket}'):
                self.assertNotIn(fragment, str(value), name)
        for name in ('commit', 'takeoverCommit', 'pullRequestTitle', 'takeoverPullRequestTitle', 'releaseTitle',
                     'notesHeading'):
            self.assertNotIn('xperimental', texts[name], name)
        for name in ('pullRequestBody', 'bootstrapPullRequestBody'):
            self.assertIn('{notes}', texts[name])
            self.assertIn('Built for: {platforms}', texts[name])
            self.assertNotIn('anonymous Swift build', texts[name])
        for path in ('publish.py', 'reviewed_publication.py', 'release_notes.py'):
            code = (ROOT / 'scripts' / path).read_text()
            self.assertRegex(code, r'from common import (\([^)]*|[^\n(]*)\btext\b')
            for fragment in ('Temporary unsupported', 'sdk-5388', 'SDK-5388', 'linear.app', 'publish experimental',
                             'Experimental {', "## What's Changed", '**Full Changelog**'):
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
        self.assertIn('Merged a bot PR? Run Tag & Release Packages', (ROOT / 'README.md').read_text())


if __name__ == '__main__':
    unittest.main()
