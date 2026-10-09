"""Real Git merge and tree verification, with only the GitHub PR API modeled."""
import copy
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import commit, file_hashes, git, run, write_json
from publish import verify_tree
from reviewed_publication import BOT, reviewed_commit

BOT_ID_EMAIL = '12345678+rudderstack-github-actions[bot]@users.noreply.github.com'  # the id is a test value


class ReviewedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote, self.repo, self.stage = (self.root / n for n in ('remote.git', 'repo', 'stage'))
        run(['git', 'init', '--bare', '--initial-branch=main', self.remote])
        run(['git', 'clone', self.remote, self.repo])
        git(self.repo, 'config', 'user.name', BOT)
        git(self.repo, 'config', 'user.email', BOT_ID_EMAIL)
        (self.repo / 'VERSION').write_text('0.1.0\n')
        write_json(self.repo / '.publication.json', {'version': '0.1.0', 'fileHashes': file_hashes(self.repo)})
        commit(self.repo, 'test: baseline')
        git(self.repo, 'push', 'origin', 'main')
        self.stage.mkdir()
        (self.stage / 'VERSION').write_text('0.1.1\n')
        self.expected = {'package': 'sprig', 'version': '0.1.1', 'sourceCommit': 'a' * 40,
                         'fileHashes': file_hashes(self.stage)}
        write_json(self.stage / '.publication.json', self.expected)
        self.pr = None
        # A rejected main push proves that PR preparation never uses that route.
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n'
                        'if [ "$ref" = refs/heads/main ]; then exit 1; fi\ndone\n')
        hook.chmod(0o755)
        self.original_main = git(self.remote, 'rev-parse', 'main')

    def identity(self):
        # The workflow sets this global identity after looking up the App bot's user id.
        path = self.root / 'gitconfig'
        path.write_text(f'[user]\n\tname = {BOT}\n\temail = {BOT_ID_EMAIL}\n')
        return path

    def create(self, args, **kwargs):
        self.assertEqual(args[:3], ['gh', 'pr', 'create'])
        self.pr = {'number': 1, 'html_url': 'https://example.invalid/pr/1', 'state': 'open', 'merged': False,
                   'merge_commit_sha': None, 'user': {'login': BOT},
                   'base': {'ref': 'main', 'repo': {'full_name': 'rudderlabs/experimental-integration-swift-sprig'}},
                   'head': {'ref': 'publication/sprig/0.1.1', 'sha': git(self.repo, 'rev-parse', 'HEAD'),
                            'repo': {'full_name': 'rudderlabs/experimental-integration-swift-sprig'}}}
        return self.pr['html_url']

    def prepare(self):
        with patch('reviewed_publication.find_pr', side_effect=lambda *a: self.pr), \
             patch('reviewed_publication.run', side_effect=self.create):
            return reviewed_commit('sprig', '0.1.1', 'a' * 40, self.repo, self.stage, lambda full: self.expected,
                                   verify_tree)

    def merge(self):
        # Model a server-authorized, reviewed merge. Ordinary publisher main pushes remain blocked.
        git(self.repo, 'checkout', 'main')
        git(self.repo, 'merge', '--no-ff', 'publication/sprig/0.1.1', '-m', 'Merge approved publication')
        sha = git(self.repo, 'rev-parse', 'HEAD')
        run(['git', 'push', self.remote, 'HEAD:refs/heads/reviewed-merge'], cwd=self.repo)
        git(self.remote, 'update-ref', 'refs/heads/main', sha)
        git(self.repo, 'fetch', 'origin', 'main')
        self.pr.update(state='closed', merged=True, merge_commit_sha=sha)
        return sha

    def test_open_pr_and_retry_leave_main_and_tags_unchanged(self):
        self.assertIsNone(self.prepare()[0])
        head = self.pr['head']['sha']
        self.assertIsNone(self.prepare()[0])
        self.assertEqual(self.pr['head']['sha'], head)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), self.original_main)
        self.assertEqual(git(self.remote, 'tag', '--list'), '')

    def test_merged_pr_uses_exact_merge_even_after_main_advances(self):
        self.prepare()
        merged = self.merge()
        (self.repo / 'VERSION').write_text('0.1.2\n')
        write_json(self.repo / '.publication.json', {'version': '0.1.2', 'fileHashes': file_hashes(self.repo)})
        later = commit(self.repo, 'test: later publication')
        git(self.repo, 'push', 'origin', 'HEAD:refs/heads/later')
        git(self.remote, 'update-ref', 'refs/heads/main', later)
        git(self.repo, 'fetch', 'origin', 'main')
        self.assertEqual(self.prepare()[0], merged)
        self.assertNotEqual(merged, later)

    def test_bot_commit_author_matches_pr_author(self):
        self.prepare()
        head = git(self.remote, 'log', '-1', '--format=%an <%ae>|%cn <%ce>', 'refs/heads/publication/sprig/0.1.1')
        self.assertEqual(head, f'{BOT} <{BOT_ID_EMAIL}>|{BOT} <{BOT_ID_EMAIL}>')
        self.assertEqual(head.split(' <')[0], self.pr['user']['login'])

    def test_workflow_configures_the_app_bot_identity_at_runtime(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/publish.yml').read_text()
        self.assertIn('''id="$(gh api '/users/rudderstack-github-actions%5Bbot%5D' --jq .id)"''', workflow)
        self.assertIn(f'git config --global user.name "{BOT}"', workflow)
        self.assertIn('git config --global user.email "${id}+rudderstack-github-actions[bot]@users.noreply.github.com"',
                      workflow)
        self.assertNotIn('41898282', workflow)
        self.assertNotIn('permission-workflows', workflow)

    def test_other_commit_identity_is_refused_before_push(self):
        git(self.repo, 'config', 'user.name', 'github-actions[bot]')
        with self.assertRaisesRegex(ValueError, 'rudderstack-github-actions'):
            self.prepare()
        git(self.repo, 'config', 'user.name', BOT)
        git(self.repo, 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        with self.assertRaisesRegex(ValueError, 'rudderstack-github-actions'):
            self.prepare()
        self.assertEqual(git(self.remote, 'for-each-ref', 'refs/heads/publication'), '')
        self.assertIsNone(self.pr)

    def test_merged_version_is_verified_from_its_stored_record_after_exporter_changes(self):
        self.prepare()
        merged = self.merge()
        def export_changed(full):
            raise AssertionError('A newer exporter would differ; a merged version is never re-exported')
        with patch('reviewed_publication.find_pr', side_effect=lambda *a: self.pr):
            self.assertEqual(reviewed_commit('sprig', '0.1.1', 'a' * 40, self.repo, self.stage, export_changed,
                                             verify_tree)[0], merged)
            # The stored record still binds the merge to its release identity and to its own file hashes.
            with self.assertRaisesRegex(ValueError, 'differs from the approved release'):
                reviewed_commit('sprig', '0.1.1', 'c' * 40, self.repo, self.stage, export_changed, verify_tree)

    def test_changed_pr_cannot_be_tagged_even_with_updated_hashes(self):
        self.prepare()
        (self.repo / 'VERSION').write_text('tampered\n')
        changed = copy.deepcopy(self.expected)
        changed['fileHashes'] = file_hashes(self.repo)
        write_json(self.repo / '.publication.json', changed)
        sha = commit(self.repo, 'test: malicious change')
        git(self.repo, 'push', 'origin', 'HEAD:refs/heads/publication/sprig/0.1.1')
        self.pr['head']['sha'] = sha
        with self.assertRaisesRegex(ValueError, 'differs from the approved export'):
            self.prepare()
        self.assertEqual(git(self.remote, 'tag', '--list'), '')

    def test_closed_unmerged_pr_stops(self):
        self.prepare()
        self.pr.update(state='closed')
        with self.assertRaisesRegex(ValueError, 'closed without merging'):
            self.prepare()

    def test_wrong_bot_or_destination_stops(self):
        self.prepare()
        original = copy.deepcopy(self.pr)
        for change in ('bot', 'destination'):
            self.pr = copy.deepcopy(original)
            if change == 'bot':
                self.pr['user']['login'] = 'untrusted-user'
            else:
                self.pr['base']['repo']['full_name'] = 'rudderlabs/production'
            with self.assertRaisesRegex(ValueError, 'identity or destination'):
                self.prepare()

    def test_merge_commit_outside_main_stops(self):
        self.prepare()
        self.pr.update(state='closed', merged=True, merge_commit_sha=self.pr['head']['sha'])
        with self.assertRaises(RuntimeError):
            self.prepare()

    def test_reuses_branch_after_interrupted_pr_creation(self):
        self.prepare()
        head = git(self.repo, 'rev-parse', 'HEAD')
        self.pr = None
        git(self.repo, 'fetch', 'origin')
        self.assertIsNone(self.prepare()[0])
        self.assertEqual(self.pr['head']['sha'], head)

    def test_remote_publisher_waits_then_tags_merge_and_recovers_after_tag(self):
        from publish import publish
        def export_fixture(key, version, destination, root):
            shutil.copytree(self.stage, destination)
            return self.expected
        def remote_command(args, **kwargs):
            if args[:3] == ['gh', 'repo', 'view']:
                return __import__('json').dumps({'nameWithOwner': 'rudderlabs/experimental-integration-swift-sprig',
                                               'visibility': 'PUBLIC', 'isArchived': False})
            args = [self.remote if str(a).startswith('https://github.com/rudderlabs/') else a for a in args]
            return run(args, **kwargs)
        def create_pr(args, **kwargs):
            self.create(args, **kwargs)
            self.pr['head']['sha'] = git(self.remote, 'rev-parse', 'refs/heads/publication/sprig/0.1.1')
            return self.pr['html_url']
        with patch.dict(os.environ, ENABLE_EXPERIMENTAL_PUBLICATION='true'), \
             patch('publish.export', side_effect=export_fixture), \
             patch('publish.inventory', return_value={'sprig': {'repository': 'experimental-integration-swift-sprig'}}), \
             patch('publish.validate'), patch('publish.run', side_effect=remote_command), \
             patch('publish.source_commit', return_value='a' * 40), \
             patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(self.identity())), \
             patch('publish.ensure_release', return_value='https://example.invalid/release') as release, \
             patch('reviewed_publication.find_pr', side_effect=lambda *a: self.pr), \
             patch('reviewed_publication.run', side_effect=create_pr):
            with patch('publish.inventory', return_value={'sprig': {
                    'repository': 'experimental-integration-swift-sprig', 'sdkMinimum': '9.0.0'}}):
                self.assertEqual(publish('sprig', '0.1.1')['status'], 'awaiting_dependency')
                self.assertIsNone(self.pr)
            self.assertEqual(publish('sprig', '0.1.1')['status'], 'awaiting_review')
            self.assertEqual(publish('sprig', '0.1.1')['status'], 'awaiting_review')
            self.assertEqual(git(self.remote, 'rev-parse', 'main'), self.original_main)
            self.assertEqual(git(self.remote, 'tag', '--list'), '')
            release.assert_not_called()
            git(self.repo, 'fetch', 'origin')
            git(self.repo, 'checkout', '-b', 'publication/sprig/0.1.1', 'origin/publication/sprig/0.1.1')
            merged = self.merge()
            with self.assertRaises(InterruptedError):
                publish('sprig', '0.1.1', interrupt='after-tag')
            self.assertEqual(git(self.remote, 'rev-parse', '0.1.1'), merged)
            release.assert_not_called()
            result = publish('sprig', '0.1.1')
            self.assertEqual(result['status'], 'published')
            self.assertTrue(result['reusedTag'])
            self.assertEqual(result['publicationCommit'], merged)
            self.assertEqual(git(self.remote, 'rev-parse', 'main'), merged)
            release.assert_called_once()
            # A re-run after an exporter change verifies the tag from its stored record (D25).
            with patch('publish.export', side_effect=AssertionError('never re-exported')):
                self.assertEqual(publish('sprig', '0.1.1')['publicationCommit'], merged)
