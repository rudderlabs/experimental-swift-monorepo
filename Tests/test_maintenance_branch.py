"""Maintenance lines with real Git: branch creation, line detection and the public release/X.Y.x route (PR API modeled)."""
import fnmatch
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
from common import ROOT, commit, file_hashes, git, load, run, write_json
from maintenance_branch import BRANCH, create, maintenance_config, publication_base, source_line, target
from publication_queue import state
from publish import ensure_release, publish, verify_tree
from reviewed_publication import ABANDON, BOT, Abandoned, abandon, abandon_state, branch_for

FIXTURE = Path(__file__).resolve().parent / 'Fixtures' / 'demo'
BOT_ID_EMAIL = '12345678+rudderstack-github-actions[bot]@users.noreply.github.com'  # the id is a test value
SDK = 'Packages/DemoSDK'
CONFIG = {'release-type': 'simple', 'include-component-in-tag': True, 'separate-pull-requests': True,
          'pull-request-title-pattern': 'chore(release):${component} ${version}',
          'packages': {SDK: {'component': 'swift-sdk', 'extra-files': ['Sources/DemoSDK/Version.swift']},
                       'Integrations/Sprig': {'component': 'integration-sprig'},
                       'Integrations/Firebase': {'component': 'integration-firebase'}}}


class SourceLineTests(unittest.TestCase):
    """The monorepo side: release/<key>-X.Y.x from a tag, and which line a source commit belongs to."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.origin, self.mono = self.root / 'origin.git', self.root / 'mono'
        run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', self.origin])
        run(['git', 'clone', '--quiet', self.origin, self.mono])
        git(self.mono, 'config', 'user.name', 'Developer')
        git(self.mono, 'config', 'user.email', 'developer@example.invalid')
        shutil.copytree(FIXTURE / 'release', self.mono / 'release')
        write_json(self.mono / 'release-please-config.json', CONFIG)
        self.tags = {}
        for tag, versions in (('swift-sdk-1.4.0', ('1.4.0', '1.0.0')), ('integration-sprig-1.0.0', ('1.4.0', '1.0.0')),
                              ('swift-sdk-1.4.1', ('1.4.1', '1.0.0')), ('swift-sdk-1.5.0', ('1.5.0', '1.0.0'))):
            write_json(self.mono / '.release-please-manifest.json', {SDK: versions[0], 'Integrations/Sprig': versions[1]})
            (self.mono / 'notes.txt').write_text(tag + '\n')
            self.tags[tag] = commit(self.mono, f'chore: release {tag}')
            git(self.mono, 'tag', tag)
        git(self.mono, 'push', '--quiet', 'origin', 'main', '--tags')

    def test_dry_run_validates_and_writes_nothing(self):
        plan = create('swift-sdk', '1.4.1', self.mono, dry_run=True)
        self.assertEqual((plan['branch'], plan['tag'], plan['from']), ('release/swift-sdk-1.4.x', 'swift-sdk-1.4.1',
                                                                      self.tags['swift-sdk-1.4.1']))
        self.assertEqual(plan['message'], 'chore(swift-sdk): start 1.4.x maintenance line')
        self.assertEqual(git(self.origin, 'for-each-ref', 'refs/heads/release'), '')

    def test_branch_starts_at_the_tag_with_a_single_package_patch_only_config(self):
        plan = create('swift-sdk', '1.4.1', self.mono)
        head = git(self.origin, 'rev-parse', 'refs/heads/release/swift-sdk-1.4.x')
        self.assertEqual(head, plan['commit'])
        self.assertEqual(git(self.origin, 'rev-parse', 'release/swift-sdk-1.4.x^'), self.tags['swift-sdk-1.4.1'])
        self.assertEqual(git(self.origin, 'log', '-1', '--format=%s|%an', head),
                         'chore(swift-sdk): start 1.4.x maintenance line|Developer')
        self.assertEqual(git(self.origin, 'diff', '--name-only', 'swift-sdk-1.4.1', head), 'release-please-config.json')
        config = json.loads(git(self.origin, 'show', f'{head}:release-please-config.json'))
        self.assertEqual(config['packages'], {SDK: {**CONFIG['packages'][SDK], 'versioning': 'always-bump-patch'}})
        self.assertEqual({k: v for k, v in config.items() if k != 'packages'},
                         {k: v for k, v in CONFIG.items() if k != 'packages'})
        # The temporary worktree is gone; main and tags are untouched.
        self.assertEqual(len(git(self.mono, 'worktree', 'list').splitlines()), 1)
        self.assertEqual(git(self.origin, 'rev-parse', 'main'), self.tags['swift-sdk-1.5.0'])
        with self.assertRaisesRegex(ValueError, 'release/swift-sdk-1.4.x already exists'):
            create('swift-sdk', '1.4.1', self.mono)

    def test_refusals(self):
        for args, message in ((('swift-sdk', '1.4.0'), r'1.4.0 is not the latest 1.4 patch; use 1.4.1'),
                              (('swift-sdk', '1.3.0'), 'Monorepo tag swift-sdk-1.3.0 is missing'),
                              (('sprig', '1.0.0'), 'main is still on 1.0.0'),
                              (('unknown', '1.0.0'), 'Unknown package'), (('swift-sdk', '1.4'), 'not X.Y.Z')):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, message):
                create(*args, self.mono)
        self.assertEqual(git(self.origin, 'for-each-ref', 'refs/heads/release'), '')
        with self.assertRaisesRegex(ValueError, 'no package Integrations/Other'):
            maintenance_config(CONFIG, 'Integrations/Other')

    def maintenance_commit(self):
        create('swift-sdk', '1.4.1', self.mono)
        git(self.mono, 'fetch', '--quiet', 'origin')
        git(self.mono, 'checkout', '--quiet', '-b', 'fix', 'origin/release/swift-sdk-1.4.x')
        (self.mono / 'fix.txt').write_text('fix\n')
        sha = commit(self.mono, 'fix(swift-sdk): patch the 1.4 line')
        git(self.mono, 'push', '--quiet', 'origin', 'HEAD:refs/heads/release/swift-sdk-1.4.x')
        git(self.mono, 'fetch', '--quiet', 'origin')
        return sha

    def test_line_is_main_or_the_matching_maintenance_branch_else_refused(self):
        fix = self.maintenance_commit()
        self.assertEqual(source_line(self.mono, 'swift-sdk', self.tags['swift-sdk-1.4.1'], '1.4.1'), 'main')
        self.assertEqual(source_line(self.mono, 'swift-sdk', fix, '1.4.2'), 'release/swift-sdk-1.4.x')
        for key, version in (('swift-sdk', '1.5.1'), ('sprig', '1.4.2')):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'neither main nor release/'):
                source_line(self.mono, key, fix, version)
        git(self.mono, 'checkout', '--quiet', '-b', 'side', 'main')
        (self.mono / 'side.txt').write_text('side\n')
        side = commit(self.mono, 'test: unreviewed side branch')
        with self.assertRaisesRegex(ValueError, 'neither main nor release/swift-sdk-1.5.x'):
            source_line(self.mono, 'swift-sdk', side, '1.5.1')
        # Abandon finds the public base from the version's monorepo tag.
        git(self.mono, 'tag', 'swift-sdk-1.4.2', fix)
        self.assertEqual(publication_base(self.mono, 'swift-sdk', '1.4.2'), 'release/1.4.x')
        self.assertEqual(publication_base(self.mono, 'swift-sdk', '1.4.1'), 'main')

    def test_release_please_target_branch(self):
        self.assertEqual(target('main'), 'main')
        self.assertEqual(target('release/swift-sdk-1.4.x'), 'release/swift-sdk-1.4.x')
        for ref in ('release/unknown-1.0.x', 'feat/x', 'release/swift-sdk-1.4', 'release/swift-sdk-01.4.x'):
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, 'Not main'):
                target(ref)
        # The push filter of release-please.yml and the pre-push hook both accept every maintenance branch.
        hook = (ROOT / 'scripts/git-hooks/pre-push').read_text()
        self.assertIn('|hotfix|release)\\/[a-zA-Z0-9._-]+$', hook)
        for name in ('release/swift-sdk-1.4.x', 'release/sprig-10.0.x', 'release/integration-x-0.1.x'):
            self.assertTrue(BRANCH.fullmatch(name) and fnmatch.fnmatch(name, 'release/*-*.*.x'), name)


class PublicMaintenanceTests(unittest.TestCase):
    """The public side: release/X.Y.x from the line's latest tag, a PR to it, and the tag on its merge commit."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote, self.repo, self.stage = (self.root / n for n in ('remote.git', 'repo', 'stage'))
        run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', self.remote])
        run(['git', 'clone', '--quiet', self.remote, self.repo])
        git(self.repo, 'config', 'user.name', BOT)
        git(self.repo, 'config', 'user.email', BOT_ID_EMAIL)
        self.commits = {}
        for version in ('1.4.0', '1.4.1', '1.5.0'):
            self.commits[version] = self.record(version)
            git(self.repo, 'tag', version)
        git(self.repo, 'tag', '1.4.9-beta.1')  # a pre-release tag is never a line's latest version
        git(self.repo, 'push', '--quiet', 'origin', 'main', '--tags')
        # Models the rulesets: main and release/* change only by a reviewed merge; the bot may create a branch.
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do case "$ref" in\n'
                        '  refs/heads/main) exit 1;;\n'
                        '  refs/heads/release/*) [ "$old" = 0000000000000000000000000000000000000000 ] || exit 1;;\n'
                        'esac; done\n')
        hook.chmod(0o755)
        self.identity = self.root / 'gitconfig'
        self.identity.write_text(f'[user]\n\tname = {BOT}\n\temail = {BOT_ID_EMAIL}\n')
        self.export('1.4.2')
        self.prs = {}

    def record(self, version, folder=None):
        folder = folder or self.repo
        (folder / 'VERSION').write_text(version + '\n')
        (folder / '.publication.json').unlink(missing_ok=True)
        write_json(folder / '.publication.json', {'package': 'swift-sdk', 'version': version, 'sourceCommit': 'a' * 40,
                                                  'fileHashes': file_hashes(folder)})
        return commit(folder, f'chore(release): {version}') if folder == self.repo else None

    def export(self, version):
        shutil.rmtree(self.stage, ignore_errors=True)
        self.stage.mkdir()
        self.record(version, self.stage)
        self.expected = load(self.stage / '.publication.json')

    def create(self, args, **kwargs):
        if args[:3] != ['gh', 'pr', 'create']:
            return run(args, **kwargs)
        head, base = args[args.index('--head') + 1], args[args.index('--base') + 1]
        repository = {'full_name': 'rudderlabs/experimental-rudder-sdk-swift'}
        self.prs[head] = {'number': len(self.prs) + 1, 'html_url': f'https://example.invalid/pr/{head}',
                          'state': 'open', 'merged': False, 'merge_commit_sha': None, 'user': {'login': BOT},
                          'labels': [], 'base': {'ref': base, 'repo': repository},
                          'head': {'ref': head, 'sha': git(self.remote, 'rev-parse', 'refs/heads/' + head),
                                   'repo': repository}}
        return self.prs[head]['html_url']

    def find(self, key, version, mode='normal'):
        return self.prs.get(branch_for(key, version, mode))

    def command(self, args, **kwargs):
        if args[:3] == ['gh', 'repo', 'view']:
            return json.dumps({'nameWithOwner': 'rudderlabs/experimental-rudder-sdk-swift', 'visibility': 'PUBLIC',
                               'isArchived': False})
        return run([self.remote if str(a).startswith('https://github.com/rudderlabs/') else a for a in args], **kwargs)

    def publish(self, version='1.4.2', line='release/swift-sdk-1.4.x', package=None):
        def export_fixture(key, version, destination, root):
            shutil.copytree(self.stage, destination)
            return self.expected
        with patch.dict(os.environ, ENABLE_EXPERIMENTAL_PUBLICATION='true', GIT_CONFIG_GLOBAL=str(self.identity)), \
             patch('publish.export', side_effect=export_fixture), \
             patch('publish.inventory', return_value={'swift-sdk': {'repository': 'experimental-rudder-sdk-swift',
                                                              **(package or {})}}), \
             patch('publish.validate'), patch('publish.source_commit', return_value='a' * 40), \
             patch('publish.source_line', return_value=line), patch('publish.run', side_effect=self.command), \
             patch('publish.ensure_release', return_value='https://example.invalid/release') as release, \
             patch('reviewed_publication.find_pr', side_effect=self.find), \
             patch('reviewed_publication.run', side_effect=self.create):
            result = publish('swift-sdk', version)
            self.release = release
            return result

    def merge(self, head, base):
        """A reviewer merges the PR into `base` (server side, past the ruleset hook)."""
        work = self.root / 'merge'
        shutil.rmtree(work, ignore_errors=True)
        run(['git', 'clone', '--quiet', '--branch', base, self.remote, work])
        git(work, 'config', 'user.name', 'Reviewer')
        git(work, 'config', 'user.email', 'reviewer@example.invalid')
        git(work, 'merge', '--quiet', '--no-ff', 'origin/' + head, '-m', 'Merge reviewed bot PR')
        sha = git(work, 'rev-parse', 'HEAD')
        run(['git', 'push', '--quiet', self.remote, f'HEAD:refs/merges/{head}'], cwd=work)
        git(self.remote, 'update-ref', 'refs/heads/' + base, sha)
        self.prs[head].update(state='closed', merged=True, merge_commit_sha=sha)
        return sha

    def test_maintenance_version_is_published_on_release_branch_and_never_latest(self):
        main = git(self.remote, 'rev-parse', 'main')
        result = self.publish()
        self.assertEqual((result['status'], result['base']), ('awaiting_review', 'release/1.4.x'))
        # The bot created release/1.4.x at the latest 1.4.* tag (1.4.1, not the pre-release), and the PR targets it.
        self.assertEqual(git(self.remote, 'rev-parse', 'release/1.4.x'), self.commits['1.4.1'])
        pr = self.prs['publication/swift-sdk/1.4.2']
        self.assertEqual(pr['base']['ref'], 'release/1.4.x')
        self.assertEqual(git(self.remote, 'rev-parse', 'publication/swift-sdk/1.4.2^'), self.commits['1.4.1'])
        self.assertEqual(self.publish()['status'], 'awaiting_review')  # a re-run reuses the branch and the PR
        self.assertEqual(len(self.prs), 1)
        self.assertEqual(git(self.remote, 'tag', '--list', '1.4.2'), '')
        merged = self.merge('publication/swift-sdk/1.4.2', 'release/1.4.x')
        result = self.publish()
        self.assertEqual((result['status'], result['branch'], result['publicationCommit']),
                         ('published', 'release/1.4.x', merged))
        self.assertEqual(git(self.remote, 'rev-parse', '1.4.2^{commit}'), merged)
        with self.assertRaises(RuntimeError):
            git(self.remote, 'merge-base', '--is-ancestor', merged, 'main')
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), main)
        self.assertIs(self.release.call_args.args[5], False)  # 1.5.0 is public: 1.4.2 is not "Latest"
        # Tag & Release checks the tag against the version's own base.
        git(self.repo, 'fetch', '--quiet', '--tags', 'origin')
        releases = [{'tag_name': '1.4.2', 'draft': False}]
        with patch('publication_queue.find_pr', side_effect=self.find):
            self.assertIsNone(state(self.repo, 'swift-sdk', '1.4.2', 'a' * 40, releases, 'release/1.4.x'))
            with self.assertRaises(RuntimeError):
                state(self.repo, 'swift-sdk', '1.4.2', 'a' * 40, releases)

    def test_highest_maintenance_version_keeps_github_default(self):
        git(self.remote, 'update-ref', '-d', 'refs/tags/1.5.0')
        self.publish()
        self.merge('publication/swift-sdk/1.4.2', 'release/1.4.x')
        self.assertEqual(self.publish()['status'], 'published')
        self.assertIs(self.release.call_args.args[5], True)

    def test_line_without_a_public_tag_or_provenance_is_refused_without_writes(self):
        self.export('1.3.5')
        with self.assertRaisesRegex(ValueError, r'No public 1\.3\.\* tag'):
            self.publish('1.3.5', 'release/swift-sdk-1.3.x')
        self.assertEqual(git(self.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads'), 'refs/heads/main')
        self.assertEqual(self.prs, {})

    def test_integration_waits_for_its_sdk_minimum_before_any_write(self):
        result = self.publish(package={'sdkMinimum': '9.0.0'})
        self.assertEqual((result['status'], result['minimum']), ('awaiting_dependency', '9.0.0'))
        self.assertEqual(git(self.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads'), 'refs/heads/main')
        self.assertEqual(self.prs, {})

    def abandon(self):
        clone = self.root / 'abandon'
        shutil.rmtree(clone, ignore_errors=True)
        run(['git', 'clone', '--quiet', '--no-checkout', self.remote, clone])
        git(clone, 'config', 'user.name', BOT)
        git(clone, 'config', 'user.email', BOT_ID_EMAIL)
        with patch('reviewed_publication.find_pr', side_effect=self.find), \
             patch('reviewed_publication.run', side_effect=self.create):
            return abandon('swift-sdk', '1.4.2', clone, verify_tree, 'release/1.4.x')

    def test_merged_maintenance_version_is_abandoned_on_its_base(self):
        self.publish()
        merged = self.merge('publication/swift-sdk/1.4.2', 'release/1.4.x')
        status, revert = self.abandon()
        self.assertEqual((status, revert['base']['ref'], revert['head']['ref']),
                         ('awaiting_review', 'release/1.4.x', 'abandon/swift-sdk/1.4.2'))
        self.assertEqual(git(self.remote, 'rev-parse', 'abandon/swift-sdk/1.4.2^'), merged)
        self.assertEqual(git(self.remote, 'rev-parse', 'release/1.4.x'), merged)  # changes only by review
        self.assertEqual(json.loads(git(self.remote, 'show', 'abandon/swift-sdk/1.4.2:.publication.json'))['version'],
                         '1.4.1')
        self.merge('abandon/swift-sdk/1.4.2', 'release/1.4.x')
        with patch('reviewed_publication.find_pr', side_effect=self.find):
            self.assertEqual(abandon_state('swift-sdk', '1.4.2', self.prs['publication/swift-sdk/1.4.2'], 'release/1.4.x'),
                             'abandoned')
            # The same PR checked against main is not this version's publication: refused, never abandoned.
            with self.assertRaisesRegex(ValueError, 'identity or destination'):
                abandon_state('swift-sdk', '1.4.2', self.prs['publication/swift-sdk/1.4.2'])
        self.assertEqual(self.publish()['status'], 'abandoned')
        self.assertEqual(git(self.remote, 'tag', '--list', '1.4.2'), '')

    def test_release_is_created_with_latest_false(self):
        commands = []
        def gh(args, **kwargs):
            commands.append([str(a) for a in args])
            return '[[]]' if args[:2] == ['gh', 'api'] else 'https://example.invalid/release'
        with patch('publish.run', side_effect=gh):
            ensure_release('swift-sdk', '1.4.2', 'b' * 40, None, lambda: 'Notes\n', False)
            ensure_release('swift-sdk', '1.5.1', 'b' * 40, None, lambda: 'Notes\n')
        self.assertEqual(commands[1][-1], '--latest=false')
        self.assertNotIn('--latest=false', commands[3])


class WorkflowTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / '.github/workflows' / name).read_text()

    def test_release_please_runs_on_main_and_maintenance_branches(self):
        text = self.read('release-please.yml')
        self.assertIn("    branches: [main, 'release/*-*.*.x']\n", text)
        self.assertIn('          target-branch: ${{ steps.target.outputs.branch }}\n', text)
        self.assertIn('run: python3 scripts/maintenance_branch.py target --ref "$GITHUB_REF_NAME"\n', text)
        self.assertIn('  group: experimental-release-please-${{ github.ref_name }}\n', text)
        self.assertNotIn('inputs.branch', text)  # a manual run releases the branch picked in "Use workflow from"
        self.assertNotIn('target-branch: main', text)

    def test_pr_checks_run_on_main_and_maintenance_branches(self):
        # `ci-ok` and `pr-title` are the required checks on both (PR #48 into release/sdk-1.4.x got none).
        ci, title = self.read('ci.yml'), self.read('pr-title.yml')
        self.assertIn("  pull_request:\n    branches: [main, 'release/*-*.*.x']\n", ci)
        self.assertIn("  push:\n    branches: [main, 'release/*-*.*.x']\n", ci)
        self.assertIn("  pull_request:\n    branches: [main, 'release/*-*.*.x']\n", title)
        self.assertIn('BASE: ${{ github.event.pull_request.base.sha }}', ci)  # the PR base, whichever branch
        for text in (ci, title):
            self.assertNotIn('refs/heads/main', text)
            self.assertNotIn("github.base_ref == 'main'", text)

    def test_create_maintenance_branch_is_manual_on_main_and_validates_first(self):
        text = self.read('create-maintenance-branch.yml')
        self.assertIn('name: Create Maintenance Branch\n', text)
        self.assertIn('on:\n  workflow_dispatch:\n    inputs:\n', text)
        for name in ('package', 'version'):
            self.assertIn(f'      {name}:\n', text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertLess(text.index('--dry-run'), text.index('create-github-app-token'))
        self.assertIn('fetch-depth: 0', text)
        for forbidden in ('permission-workflows', 'permission-pull-requests', 'git push', 'release create'):
            self.assertNotIn(forbidden, text)
        self.assertEqual([l for l in text.splitlines() if l.strip().startswith('run:') and '${{' in l], [])

    def test_publication_workflows_follow_the_source_line(self):
        publish_yml = self.read('publish.yml')
        self.assertIn('from maintenance_branch import source_line', publish_yml)
        self.assertNotIn("'origin/main'", publish_yml)
        self.assertIn("(github.event_name == 'push' && startsWith(github.ref, 'refs/heads/release/'))", publish_yml)
        self.assertIn('fetch-depth: 0', self.read('abandon-publication.yml'))
        self.assertIn('fetch-depth: 0', self.read('complete-publication.yml'))


if __name__ == '__main__':
    unittest.main()
