"""Takeover, bootstrap and awaiting_takeover with real Git and SwiftPM manifests; only the GitHub API is modeled."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import commit, file_hashes, git, run, write_json
from publication_status import summarize
from publish import publish
from reviewed_publication import BOT, WORKFLOWS

EMAIL = '12345678+rudderstack-github-actions[bot]@users.noreply.github.com'  # the id is a test value
REPOSITORY = 'rudderlabs/experimental-integration-swift-sprig'
KIT = 'public enum Kit { public static let name = "kit" }\n'
LEGACY = '''// swift-tools-version: 5.9
// Hand-written legacy manifest: other formatting, a test target and the real SDK URL.
import PackageDescription

let package = Package(
    name: "integration-swift-kit",
    platforms: [
        .iOS(.v15)
    ],
    products: [
        .library(name: "Kit", targets: ["Kit"]),
    ],
    dependencies: [
        .package(url: "https://github.com/rudderlabs/rudder-sdk-swift.git", .upToNextMajor(from: "1.4.0")),
    ],
    targets: [
        .target(
            name: "Kit",
            dependencies: [.product(name: "RudderStackAnalytics", package: "rudder-sdk-swift")],
            path: "Sources/Kit"
        ),
        .testTarget(name: "KitTests", dependencies: ["Kit"]),
    ]
)
'''
GENERATED = '''// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "Kit",
    platforms: [.iOS(.v15)],
    products: [.library(name: "Kit", targets: ["Kit"])],
    dependencies: [.package(url: "https://github.com/rudderlabs/experimental-rudder-sdk-swift.git", from: "1.4.0")],
    targets: [.target(name: "Kit", dependencies: [.product(name: "RudderStackAnalytics", package: "experimental-rudder-sdk-swift")])]
)
'''
FOREIGN = {'Package.swift': LEGACY, 'Sources/Kit/Kit.swift': KIT, 'Tests/KitTests/KitTests.swift': 'import XCTest\n',
           'Example/App.swift': 'import Kit\n', 'LICENSE.md': 'MIT\n', 'README.md': '# Kit\n',
           'Package.resolved': '{}\n', '.github/CODEOWNERS': '* @someone\n',
           '.github/pull_request_template.md': 'Describe\n', '.swiftlint.yml': 'rules: []\n'}


class TakeoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote, self.seed, self.stage = (self.root / n for n in ('remote.git', 'seed', 'stage'))
        self.identity = self.root / 'gitconfig'
        self.identity.write_text(f'[user]\n\tname = {BOT}\n\temail = {EMAIL}\n')
        run(['git', 'init', '--bare', '--initial-branch=main', self.remote])
        run(['git', 'clone', self.remote, self.seed])
        self.pr, self.created = None, []

    def public(self, files, tag=None):
        for path, content in files.items():
            (self.seed / path).parent.mkdir(parents=True, exist_ok=True)
            (self.seed / path).write_text(content)
        sha = commit(self.seed, 'test: public repository before takeover')
        if tag:
            git(self.seed, 'tag', tag)
        git(self.seed, 'push', 'origin', 'main', '--tags')
        # A rejected main push proves that takeover and bootstrap never use that route.
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n'
                        'if [ "$ref" = refs/heads/main ]; then exit 1; fi\ndone\n')
        hook.chmod(0o755)
        return sha

    def export_files(self, version, changes=None):
        files = {'Package.swift': GENERATED, 'Sources/Kit/Kit.swift': KIT,
                 'Sources/Kit/Version.swift': f'enum Version {{ static let current = "{version}" }}\n',
                 'README.md': '# Kit\n\n## Report issues / contribute\n', 'LICENSE': 'MIT\n',
                 'CONTRIBUTING.md': '# Contributing\n', '.github/CODEOWNERS': '* @rudderlabs/sdk_team\n',
                 'VERSION': version + '\n', **(changes or {})}
        shutil.rmtree(self.stage, ignore_errors=True)
        for path, content in files.items():
            (self.stage / path).parent.mkdir(parents=True, exist_ok=True)
            (self.stage / path).write_text(content)
        self.expected = {'package': 'sprig', 'version': version, 'sourceCommit': 'a' * 40,
                         'fileHashes': file_hashes(self.stage)}
        write_json(self.stage / '.publication.json', self.expected)

    def command(self, args, **kwargs):
        if args[:3] == ['gh', 'repo', 'view']:
            return json.dumps({'nameWithOwner': REPOSITORY, 'visibility': 'PUBLIC', 'isArchived': False})
        if args[:3] == ['gh', 'pr', 'create']:
            body = Path(args[args.index('--body-file') + 1]).read_text()
            head = args[args.index('--head') + 1]
            self.created.append({'title': args[args.index('--title') + 1], 'body': body, 'head': head})
            self.pr = {'number': 1, 'html_url': 'https://example.invalid/pr/1', 'state': 'open', 'merged': False,
                       'merge_commit_sha': None, 'user': {'login': BOT},
                       'base': {'ref': 'main', 'repo': {'full_name': REPOSITORY}},
                       'head': {'ref': head, 'sha': git(self.remote, 'rev-parse', 'refs/heads/' + head),
                                'repo': {'full_name': REPOSITORY}}}
            return self.pr['html_url']
        args = [self.remote if str(a).startswith('https://github.com/rudderlabs/') else a for a in args]
        return run(args, **kwargs)

    def publish(self, mode='normal'):
        def export_fixture(key, version, destination, root):
            shutil.copytree(self.stage, destination)
            return self.expected
        with patch.dict(os.environ, ENABLE_EXPERIMENTAL_PUBLICATION='true', GIT_CONFIG_GLOBAL=str(self.identity)), \
             patch('publish.export', side_effect=export_fixture), \
             patch('publish.inventory', return_value={'sprig': {
                 'repository': 'experimental-integration-swift-sprig', 'target': 'Kit'}}), \
             patch('publish.validate'), patch('publish.source_commit', return_value='a' * 40), \
             patch('publish.run', side_effect=self.command), \
             patch('publish.ensure_release', return_value='https://example.invalid/release') as release, \
             patch('publish.find_pr', side_effect=lambda *a: self.pr), \
             patch('reviewed_publication.find_pr', side_effect=lambda *a: self.pr), \
             patch('reviewed_publication.run', side_effect=self.command):
            result = publish('sprig', self.expected['version'], mode=mode)
            self.released = release.called
            return result

    def merge(self, branch):
        work = self.root / 'merge'
        shutil.rmtree(work, ignore_errors=True)
        run(['git', 'clone', self.remote, work])
        git(work, 'config', 'user.name', 'reviewer')
        git(work, 'config', 'user.email', 'reviewer@example.invalid')
        git(work, 'merge', '--no-ff', 'origin/' + branch, '-m', 'Merge reviewed bot PR')
        sha = git(work, 'rev-parse', 'HEAD')
        run(['git', 'push', self.remote, 'HEAD:refs/heads/reviewed-merge'], cwd=work)
        git(self.remote, 'update-ref', 'refs/heads/main', sha)
        self.pr.update(state='closed', merged=True, merge_commit_sha=sha)
        return sha

    def branches(self):
        return git(self.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads').splitlines()

    def test_foreign_repo_waits_for_takeover_without_writes(self):
        main = self.public(FOREIGN, tag='1.0.0')
        self.export_files('1.0.1')
        for _ in range(2):
            result = self.publish()
            self.assertEqual(result['status'], 'awaiting_takeover')
        self.assertEqual(result['sourceCommit'], 'a' * 40)
        with self.assertRaisesRegex(ValueError, 'README-only'):
            self.publish('bootstrap')
        self.assertEqual(self.branches(), ['refs/heads/main'])
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), main)
        self.assertEqual(self.created, [])

    def test_awaiting_takeover_does_not_block_other_packages(self):
        sha = 'a' * 40
        plan = [{'package': 'sdk', 'version': '1.4.1', 'sha': sha}, {'package': 'sprig', 'version': '1.0.1', 'sha': sha}]
        jobs = {'sdk': {'result': 'success', 'outputs': {
                    'status': 'published', 'package': 'sdk', 'version': '1.4.1', 'tag': '1.4.1',
                    'sourceCommit': sha, 'publicationCommit': 'b' * 40}},
                'sprig': {'result': 'success', 'outputs': {
                    'status': 'awaiting_takeover', 'package': 'sprig', 'version': '1.0.1', 'sourceCommit': sha}}}
        result = summarize(plan, jobs)
        self.assertEqual(result['status'], 'awaiting_publication')
        self.assertEqual(result['packages']['sdk']['status'], 'published')
        self.assertEqual(result['packages']['sprig']['status'], 'awaiting_takeover')
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/publish.yml').read_text()
        self.assertIn("'awaiting_dependency', 'awaiting_takeover'):", workflow)

    def test_takeover_refuses_while_workflows_exist(self):
        main = self.public({**FOREIGN, '.github/workflows/ci.yml': 'on: push\n'}, tag='1.0.0')
        self.export_files('1.0.0')
        result = self.publish('takeover')
        self.assertEqual((result['status'], result['reason']), ('awaiting_takeover', WORKFLOWS))
        self.assertEqual(WORKFLOWS, 'Remove .github/workflows by PR first')
        self.assertEqual(self.branches(), ['refs/heads/main'])
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), main)
        self.assertEqual(self.created, [])

    def test_takeover_pr_removes_foreign_files_keeps_sources_and_creates_no_tag(self):
        baseline = self.public(FOREIGN, tag='1.0.0')
        self.export_files('1.0.0')
        result = self.publish('takeover')
        self.assertEqual((result['status'], result['branch'], result['mode']),
                         ('awaiting_review', 'takeover/sprig/1.0.0', 'takeover'))
        head = 'refs/heads/takeover/sprig/1.0.0'
        files = git(self.remote, 'ls-tree', '-r', '--name-only', head).splitlines()
        self.assertEqual(sorted(files), sorted([*self.expected['fileHashes'], '.publication.json']))
        self.assertFalse([f for f in files if f.startswith('.github/workflows')])
        self.assertEqual(git(self.remote, 'rev-parse', f'{head}:Sources/Kit/Kit.swift'),
                         git(self.remote, 'rev-parse', '1.0.0:Sources/Kit/Kit.swift'))
        self.assertEqual(git(self.remote, 'log', '-1', '--format=%an <%ae>', head), f'{BOT} <{EMAIL}>')
        self.assertEqual(self.created[0]['title'], 'chore: take over experimental sprig 1.0.0')
        body = self.created[0]['body']
        for removed in ('Tests/KitTests/KitTests.swift', 'Example/App.swift', 'LICENSE.md', 'Package.resolved',
                        '.github/pull_request_template.md', '.swiftlint.yml'):
            self.assertIn(f'- `{removed}`', body)
        for allowed in ('No `testTarget`', '`LICENSE.md`', 'experimental-rudder-sdk-swift', 'No tag'):
            self.assertIn(allowed, body)
        self.assertEqual(self.publish('takeover')['status'], 'awaiting_review')
        self.assertEqual(len(self.created), 1)
        merged = self.merge('takeover/sprig/1.0.0')
        result = self.publish('takeover')
        self.assertEqual((result['status'], result['takeover'], result['publicationCommit']), ('published', True, merged))
        self.assertFalse(self.released)
        self.assertEqual(git(self.remote, 'tag', '--list'), '1.0.0')
        self.assertEqual(git(self.remote, 'rev-parse', '1.0.0^{commit}'), baseline)
        self.pr = None
        with self.assertRaisesRegex(ValueError, 'already taken over'):
            self.publish('takeover')

    def test_takeover_refuses_when_sources_differ(self):
        self.public(FOREIGN, tag='1.0.0')
        for change, message in [({'Sources/Kit/Kit.swift': KIT + '// changed\n'}, 'Sources/ differ.*Kit/Kit.swift'),
                                ({'Sources/Kit/Extra.swift': 'let x = 1\n'}, 'Sources/ differ.*Kit/Extra.swift'),
                                ({'Package.swift': GENERATED.replace('[.iOS(.v15)]', '[.iOS(.v16)]')},
                                 'differs semantically: platforms'),
                                ({'Package.swift': GENERATED.replace('from: "1.4.0"', 'from: "1.5.0"')},
                                 'differs semantically: dependencies')]:
            with self.subTest(message=message):
                self.export_files('1.0.0', change)
                with self.assertRaisesRegex(ValueError, message):
                    self.publish('takeover')
                self.assertEqual(self.branches(), ['refs/heads/main'])
        self.assertEqual(self.created, [])

    def test_takeover_needs_the_baseline_tag(self):
        self.public(FOREIGN)
        self.export_files('1.0.0')
        with self.assertRaisesRegex(ValueError, 'existing baseline tag 1.0.0'):
            self.publish('takeover')

    def test_readme_only_repo_gets_a_bootstrap_pr_then_recover_tags_it(self):
        self.public({'README.md': '# Kit\n', 'LICENSE': 'MIT\n', '.gitignore': '.build/\n'})
        self.export_files('1.0.0')
        result = self.publish()
        self.assertEqual((result['status'], result['branch'], result['mode']),
                         ('awaiting_review', 'publication/sprig/1.0.0', 'bootstrap'))
        self.assertIn('README-only', self.created[0]['body'])
        self.assertEqual(self.created[0]['title'], 'chore: publish experimental sprig 1.0.0')
        self.assertEqual(git(self.remote, 'tag', '--list'), '')
        merged = self.merge('publication/sprig/1.0.0')
        result = self.publish()
        self.assertEqual((result['status'], result['publicationCommit']), ('published', merged))
        self.assertEqual(git(self.remote, 'rev-parse', '1.0.0'), merged)
        self.assertTrue(self.released)


if __name__ == '__main__':
    unittest.main()
