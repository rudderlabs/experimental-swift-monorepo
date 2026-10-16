"""Abandon Unpublished Version, monorepo side, with real Git: guards and the rollback (GitHub API modeled)."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
    os.environ.pop(name, None)  # every git call below stays inside its temporary repository
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import ROOT, commit, git, run, write_json
from discard_version import check, rollback
from reviewed_publication import BOT

FIXTURE = Path(__file__).resolve().parent / 'Fixtures' / 'demo'
PATH = 'Integrations/Firebase'
VERSION_SWIFT = f'{PATH}/Sources/RudderIntegrationFirebase/Version.swift'
RELEASE_FILES = ['.release-please-manifest.json', f'{PATH}/CHANGELOG.md', f'{PATH}/version.txt', VERSION_SWIFT]
RUN = 'https://github.com/rudderlabs/experimental-swift-monorepo/actions/runs/1'


class DiscardVersionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin, self.mono, self.public = self.root / 'origin.git', self.root / 'mono', self.root / 'public.git'
        for bare in (self.origin, self.public):
            run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', bare])
        run(['git', 'clone', '--quiet', self.origin, self.mono])
        git(self.mono, 'config', 'user.name', BOT)
        git(self.mono, 'config', 'user.email', '12345678+rudderstack-github-actions[bot]@users.noreply.github.com')
        shutil.copytree(FIXTURE / 'release', self.mono / 'release')
        write_json(self.mono / 'release-please-config.json', {'packages': {PATH: {
            'component': 'integration-firebase',
            'extra-files': [{'type': 'generic', 'path': 'Sources/RudderIntegrationFirebase/Version.swift'}]}}})
        (self.mono / PATH / 'Sources/RudderIntegrationFirebase').mkdir(parents=True)
        (self.mono / PATH / 'Code.swift').write_text('let code = 1\n')
        self.release('1.1.5')
        (self.mono / PATH / 'Code.swift').write_text('let code = 2\n')
        self.fix = commit(self.mono, 'fix(firebase): change the code')
        self.sha = self.release('1.1.6')
        git(self.mono, 'push', '--quiet', 'origin', 'main', '--tags')
        git(self.mono, 'fetch', '--quiet', 'origin')
        self.discards, self.releases, self.calls = [], ['integration-firebase-1.1.5', 'integration-firebase-1.1.6'], []
        self.release_pr = {'number': 47, 'merge_commit_sha': self.sha, 'body': 'Release notes\n'}

    def release(self, version, branch='main'):
        write_json(self.mono / '.release-please-manifest.json', {PATH: version})
        (self.mono / PATH / 'version.txt').write_text(version + '\n')
        (self.mono / VERSION_SWIFT).write_text(f'let version = "{version}"\n')
        changelog = self.mono / PATH / 'CHANGELOG.md'
        changelog.write_text(f'## {version}\n' + (changelog.read_text() if changelog.exists() else ''))
        sha = commit(self.mono, f'chore(release): integration-firebase {version}')
        git(self.mono, 'tag', f'integration-firebase-{version}')
        return sha

    def gh(self, args, **kwargs):
        # The GitHub API: rollback PRs, the release PR, and the monorepo Releases.
        args = [str(a) for a in args]
        if args[0] == 'git':
            return run(args, **kwargs)
        self.calls.append(args[1:3])
        if args[1:3] == ['pr', 'create']:
            self.discards.append({'number': 60 + len(self.discards), 'state': 'open', 'merged_at': None,
                                  'user': {'login': BOT}, 'body': args[args.index('--body') + 1],
                                  'title': args[args.index('--title') + 1], 'head': args[args.index('--head') + 1],
                                  'base': args[args.index('--base') + 1]})
            return 'https://example.invalid/pull/60'
        if args[1:3] == ['release', 'delete']:
            self.assertEqual(args[3:], [self.releases[-1], '--repo', 'rudderlabs/experimental-swift-monorepo',
                                        '--cleanup-tag', '--yes'])
            git(self.origin, 'tag', '-d', self.releases.pop())
            return ''
        if args[1:3] == ['api', '-X']:
            self.assertEqual(args[3:5], ['PATCH', 'repos/rudderlabs/experimental-swift-monorepo/pulls/47'])
            self.release_pr['body'] = args[6].removeprefix('body=')
            return '{}'
        if args[-1].endswith(f'/commits/{self.sha}/pulls'):
            return json.dumps([self.release_pr, {'number': 46, 'merge_commit_sha': self.fix, 'body': ''}])
        if '/releases?' in args[-1]:
            return json.dumps([[{'tag_name': t} for t in self.releases]])
        raise AssertionError(f'Unmodeled gh call: {args}')

    def github(self, function, *args):
        with patch('discard_version.url', return_value=str(self.public)), \
             patch('discard_version.run', side_effect=self.gh), \
             patch('discard_version.discard_prs', side_effect=lambda key, version: list(self.discards)):
            return function(*args)

    def check(self, version='1.1.6'):
        return self.github(check, 'firebase', version, self.mono)

    def rollback(self, plan):
        return self.github(rollback, 'firebase', '1.1.6', plan, self.mono, RUN)

    def show(self, ref, path):
        return git(self.origin, 'show', f'{ref}:{path}')

    def test_rollback_restores_the_release_files_and_keeps_the_code(self):
        plan = self.check()
        self.assertEqual((plan['branch'], plan['base'], plan['sha'], plan['rollback']),
                         ('main', 'main', self.sha, None))
        self.assertEqual(self.rollback(plan), 60)
        branch = 'refs/heads/discard/firebase/1.1.6'
        self.assertEqual(git(self.origin, 'rev-parse', f'{branch}^'), self.sha)
        self.assertEqual(git(self.origin, 'diff', '--name-only', self.fix, branch), '')
        self.assertEqual(self.show(branch, '.release-please-manifest.json'), json.dumps({PATH: '1.1.5'}, indent=2))
        self.assertEqual(self.show(branch, f'{PATH}/Code.swift'), 'let code = 2')
        self.assertEqual(git(self.origin, 'log', '-1', '--format=%s%n%b', branch),
                         f'revert(firebase): discard unpublished integration-firebase 1.1.6\nThis reverts commit {self.sha}.')
        [pr] = self.discards
        self.assertEqual((pr['title'], pr['head'], pr['base']),
                         ('revert(firebase): discard unpublished integration-firebase 1.1.6',
                          'discard/firebase/1.1.6', 'main'))
        self.assertIn(self.sha, pr['body'])
        self.assertIn(RUN, pr['body'])
        self.assertEqual(self.release_pr['body'], 'Release notes\n\nBEGIN_COMMIT_OVERRIDE\n'
                         'revert(firebase): discarded release integration-firebase 1.1.6\nEND_COMMIT_OVERRIDE\n')
        # The Release and tag go last; main and the earlier tag stay.
        self.assertEqual(self.calls[-1], ['release', 'delete'])
        self.assertLess(self.calls.index(['pr', 'create']), self.calls.index(['api', '-X']))
        self.assertEqual(git(self.origin, 'tag', '--list'), 'integration-firebase-1.1.5')
        self.assertEqual(git(self.origin, 'rev-parse', 'main'), self.sha)

    def test_rerun_continues_once_and_then_reports_already_discarded(self):
        plan = self.check()
        self.rollback(plan)
        # Interrupted before the tag deletion: the run continues without a second PR or override.
        self.releases.append('integration-firebase-1.1.6')
        git(self.origin, 'tag', 'integration-firebase-1.1.6', self.sha)
        # The rollback PR merged meanwhile: the manifest no longer says 1.1.6, which is fine with a rollback PR.
        git(self.origin, 'update-ref', 'refs/heads/main', 'refs/heads/discard/firebase/1.1.6')
        git(self.mono, 'fetch', '--quiet', 'origin')
        self.discards[0].update(state='closed', merged_at='2026-10-15T00:00:00Z')
        plan = self.check()
        self.assertEqual(plan['rollback']['number'], 60)
        self.assertEqual(self.rollback(plan), 60)
        self.assertEqual(len(self.discards), 1)
        self.assertEqual(self.release_pr['body'].count('BEGIN_COMMIT_OVERRIDE'), 1)
        self.assertEqual(git(self.origin, 'tag', '--list', 'integration-firebase-1.1.6'), '')
        # A fresh checkout has no tag: already discarded, nothing to do.
        git(self.mono, 'tag', '-d', 'integration-firebase-1.1.6')
        self.assertIsNone(self.check())

    def test_refusals_before_any_change(self):
        with self.assertRaisesRegex(ValueError, 'No monorepo tag integration-firebase-1.1.9; nothing to discard'):
            self.check('1.1.9')
        with self.assertRaisesRegex(ValueError, r'1.1.5 is not the latest released firebase on main '
                                                r'\(manifest says 1.1.6\); fix forward'):
            self.check('1.1.5')
        self.discards.append({'number': 60, 'state': 'closed', 'merged_at': None, 'user': {'login': BOT},
                              'body': f'reverts {self.sha}'})
        with self.assertRaisesRegex(ValueError, 'Rollback PR #60 was closed without merging'):
            self.check()
        self.discards.clear()
        # A release commit with other changes is never reverted as a whole.
        write_json(self.mono / '.release-please-manifest.json', {PATH: '1.1.7'})
        (self.mono / PATH / 'Code.swift').write_text('let code = 3\n')
        commit(self.mono, 'chore(release): integration-firebase 1.1.7')
        git(self.mono, 'tag', 'integration-firebase-1.1.7')
        git(self.mono, 'push', '--quiet', 'origin', 'main')
        git(self.mono, 'fetch', '--quiet', 'origin')
        with self.assertRaisesRegex(ValueError, f'also changes {PATH}/Code.swift; fix forward'):
            self.check('1.1.7')
        # A public tag is never discarded.
        run(['git', 'clone', '--quiet', self.origin, self.root / 'public'])
        git(self.root / 'public', 'tag', '1.1.6')
        git(self.root / 'public', 'push', '--quiet', self.public, 'refs/tags/1.1.6')
        with self.assertRaisesRegex(ValueError, 'already public .* roll forward'):
            self.check()
        self.assertEqual(self.calls, [])
        self.assertEqual(git(self.origin, 'for-each-ref', 'refs/heads/discard'), '')

    def test_maintenance_line_rolls_back_on_its_branch(self):
        git(self.mono, 'checkout', '--quiet', '-b', 'line', 'integration-firebase-1.1.5')
        (self.mono / PATH / 'Code.swift').write_text('let code = 4\n')
        commit(self.mono, 'fix(firebase): patch the 1.1 line')
        sha = self.release('1.1.7')
        git(self.mono, 'push', '--quiet', 'origin', 'HEAD:refs/heads/release/firebase-1.1.x', '--tags')
        git(self.mono, 'fetch', '--quiet', 'origin')
        plan = self.github(check, 'firebase', '1.1.7', self.mono)
        self.assertEqual((plan['branch'], plan['base']), ('release/firebase-1.1.x', 'release/1.1.x'))
        self.sha, self.release_pr['merge_commit_sha'] = sha, sha
        self.releases.append('integration-firebase-1.1.7')
        self.github(rollback, 'firebase', '1.1.7', plan, self.mono, RUN)
        self.assertEqual(self.discards[0]['base'], 'release/firebase-1.1.x')
        self.assertEqual(git(self.origin, 'rev-parse', 'discard/firebase/1.1.7^'), sha)
        self.assertEqual(self.show('discard/firebase/1.1.7', f'{PATH}/version.txt'), '1.1.5')
        self.assertEqual(git(self.origin, 'tag', '--list', 'integration-firebase-1.1.7'), '')

    def test_workflow_runs_the_monorepo_side_only_after_the_public_side(self):
        workflow = (ROOT / '.github/workflows/abandon-publication.yml').read_text()
        rollback_job = workflow.split('\n  rollback:\n')[1]
        self.assertIn("    if: needs.public.outputs.proceed == 'true'\n", rollback_job)
        self.assertIn('discard_version.py rollback', rollback_job)
        self.assertNotIn('discard_version.py rollback', workflow.split('\n  rollback:\n')[0])


if __name__ == '__main__':
    unittest.main()
