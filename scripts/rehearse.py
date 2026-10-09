"""Local publication lifecycle on temporary fixture repositories. Git, SwiftPM and Xcode are real; GitHub is modeled.

`python3 scripts/rehearse.py` builds a throwaway monorepo from Tests/Fixtures/demo and one local bare "public"
repository per allowlisted package, then runs bootstrap, takeover, releases, Recover, drift and clean consumers.
Nothing reaches GitHub: `gh` is a local model on PATH and every github.com Git URL is rewritten to a local
bare repository or to a path that does not exist.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import parse_qsl

from common import (ROOT, CONSUMER_NAME, OWNER, RELEASE_BRANCH, SOURCE_NAME, allowlist, anonymous_env, commit, git,
                    inventory, load, run, swift_options, text, url, write_json)
from anchor import anchor
import project
import publish
import reviewed_publication
from publication_queue import queue
from dependency_policy import markers as dependency_markers
from release_plan import affected
from reviewed_publication import BOT, WORKFLOWS

FIXTURE = ROOT / 'Tests/Fixtures/demo'
NAMES = allowlist()
SOURCE = f'{OWNER}/{SOURCE_NAME}'
COLLECTIONS = 'https://github.com/apple/swift-collections.git'
BOT_EMAIL = '12345678+rudderstack-github-actions[bot]@users.noreply.github.com'  # modeled App bot user id
FAILURES = (ValueError, RuntimeError, OSError, KeyError)
# Models the branch and tag rulesets: main changes only through a reviewed merge, and tags never move.
HOOK = '''#!/bin/sh
while read old new ref; do
  case "$ref" in
    refs/heads/main) echo "main changes only through a reviewed pull request" >&2; exit 1;;
    refs/tags/*) [ "$old" = 0000000000000000000000000000000000000000 ] || { echo "tags are immutable" >&2; exit 1; };;
  esac
done
'''
# A pre-monorepo Sprig manifest: other formatting and a test target, semantically equal to the export.
LEGACY_SPRIG = '''// swift-tools-version: 5.9
// Hand-written manifest from before the monorepo.
import PackageDescription

let package = Package(
    name: "integration-swift-sprig",
    platforms: [
        .iOS(.v15),
        .macOS(.v12),
    ],
    products: [
        .library(name: "DemoSprig", targets: ["DemoSprig"]),
    ],
    dependencies: [
        .package(url: "https://github.com/rudderlabs/experimental-rudder-sdk-swift.git", .upToNextMajor(from: "0.1.0")),
    ],
    targets: [
        .target(
            name: "DemoSprig",
            dependencies: [.product(name: "DemoSDK", package: "experimental-rudder-sdk-swift")],
            path: "Sources/DemoSprig"
        ),
        .testTarget(name: "DemoSprigTests", dependencies: ["DemoSprig"]),
    ]
)
'''
LEGACY_FILES = {'Tests/DemoSprigTests/DemoSprigTests.swift': 'import XCTest\n',
                'Example/App.swift': 'import DemoSprig\n',
                'LICENSE.md': 'MIT\n', 'README.md': '# Sprig\n', '.swiftlint.yml': 'rules: []\n',
                '.github/CODEOWNERS': '* @someone\n', '.github/workflows/ci.yml': 'on: push\n'}
# Local stand-in for the Swift Collections tag the Firebase fixture pins, so the rehearsal stays offline.
COLLECTIONS_FILES = {
    'Package.swift': '// swift-tools-version: 5.9\nimport PackageDescription\nlet package = Package(\n'
                     '    name: "swift-collections",\n'
                     '    products: [.library(name: "OrderedCollections", targets: ["OrderedCollections"])],\n'
                     '    targets: [.target(name: "OrderedCollections")]\n)\n',
    'Sources/OrderedCollections/OrderedSet.swift':
        'public struct OrderedSet<Element: Hashable>: RandomAccessCollection {\n'
        '    private var elements: [Element] = []\n'
        '    public init<S: Sequence>(_ values: S) where S.Element == Element {\n'
        '        var seen = Set<Element>()\n'
        '        for value in values where seen.insert(value).inserted { elements.append(value) }\n'
        '    }\n'
        '    public var startIndex: Int { elements.startIndex }\n'
        '    public var endIndex: Int { elements.endIndex }\n'
        '    public subscript(index: Int) -> Element { elements[index] }\n'
        '}\n'}
REAL = ('Git repositories, commits, merges, branches and tags; pre-receive hooks for the main and tag rules; export; '
        'swift build and xcodebuild platform builds; dump-package takeover checks; the publication_queue.queue and '
        'publish.publish code paths; fresh SwiftPM consumers')
MODELED = ('gh (repository identity, bot PRs, Releases) as local JSON through a PATH shim; Release Please as version '
           'commits, component tags and source Release records; reviewed merges as a reviewer clone plus a server-side '
           'main update; the App bot user id; Swift Collections as a local stand-in tag 1.1.4')
NOT_MODELED = ('GitHub Actions, App permissions, rulesets, environments, Release Please itself, anonymous public '
               'network access, reverse sync (ingest)')


class RehearsalError(Exception):
    pass


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def github(args):
    """The modeled `gh`: repository identity, bot PRs and Releases kept as local JSON next to the bare repositories."""
    path = Path(os.environ['REHEARSAL_GITHUB']) / 'state.json'
    state = load(path)
    option = lambda name: args[args.index(name) + 1]

    def bare(repository):
        owner, _, name = repository.partition('/')
        folder = Path(state['remotes']) / (name + '.git')
        if owner != OWNER or not folder.is_dir():
            raise ValueError(f'Unknown repository {repository}')
        return folder

    def view(repository, pr):
        if pr['state'] == 'open':
            pr['head']['sha'] = git(bare(repository), 'rev-parse', 'refs/heads/' + pr['head']['ref'])
        return pr

    if args[:2] == ['repo', 'view']:
        bare(args[2])
        output = {'nameWithOwner': args[2], 'visibility': 'PUBLIC', 'isArchived': False}
    elif args[:2] == ['pr', 'create']:
        repository, branch = option('--repo'), option('--head')
        pulls = state['pulls'].setdefault(repository, [])
        if any(p['head']['ref'] == branch for p in pulls):
            raise ValueError('A pull request already exists for ' + branch)
        number = len(pulls) + 1
        reference = {'repo': {'full_name': repository}}
        pulls.append({'number': number, 'html_url': f'local-github://{repository}/pull/{number}', 'state': 'open',
                      'merged': False, 'merge_commit_sha': None, 'user': {'login': BOT}, 'title': option('--title'),
                      'body': Path(option('--body-file')).read_text(), 'base': {'ref': option('--base'), **reference},
                      'head': {'ref': branch, 'sha': git(bare(repository), 'rev-parse', 'refs/heads/' + branch),
                               **reference}})
        output = pulls[-1]['html_url']
    elif args[:2] == ['release', 'create']:
        repository, version = option('--repo'), args[2]
        if '--verify-tag' in args and not git(bare(repository), 'tag', '--list', version):
            raise ValueError('Release tag is not served: ' + version)
        releases = state['releases'].setdefault(repository, [])
        if any(r['tag_name'] == version for r in releases):
            raise ValueError('Release already exists: ' + version)
        releases.append({'tag_name': version, 'name': option('--title'), 'draft': False, 'prerelease': False,
                         'body': Path(option('--notes-file')).read_text(),
                         'html_url': f'local-github://{repository}/releases/tag/{version}'})
        output = releases[-1]['html_url']
    elif args[0] == 'api' and args[-1].startswith('repos/'):
        endpoint, _, query = args[-1].partition('?')
        parts = endpoint.split('/')
        repository, resource = '/'.join(parts[1:3]), parts[3:]
        if resource == ['pulls']:
            head = dict(parse_qsl(query))['head'].split(':', 1)[1]
            output = [view(repository, p) for p in state['pulls'].get(repository, []) if p['head']['ref'] == head]
        elif resource[:1] == ['pulls'] and len(resource) == 2:
            output = view(repository, next(p for p in state['pulls'][repository] if p['number'] == int(resource[1])))
        elif resource == ['releases']:
            output = state['releases'].get(repository, [])
        else:
            raise ValueError('Unmodeled gh api endpoint: ' + args[-1])
        output = [output] if '--slurp' in args else output
    else:
        raise ValueError('Unmodeled gh call: ' + ' '.join(args[:3]))
    write_json(path, state)
    print(output if isinstance(output, str) else json.dumps(output))


class Lab:
    def __init__(self, directory, quick=False):
        self.dir, self.quick = directory, quick
        self.remotes, self.source = directory / 'remotes', directory / 'source'
        self.runner, self.release_source = directory / 'recover-checkout', directory / 'release-source'
        self.state_file = directory / 'github/state.json'
        self.records = {'status': 'running', 'steps': [], 'quick': quick, 'real': REAL, 'notModeled': NOT_MODELED,
                        'modeled': MODELED + ('; xcodebuild platform builds skipped (--quick)' if quick else '')}

    def save(self):
        write_json(self.dir / 'evidence.json', self.records)

    @contextlib.contextmanager
    def step(self, number, title):
        print(f'RUN  step {number}: {title}', flush=True)
        started, entry = time.monotonic(), {'step': number, 'title': title, 'checks': []}
        self.current = entry
        try:
            yield entry
        except Exception as error:
            entry.update(status='failed', error=str(error), seconds=round(time.monotonic() - started, 1))
            self.records['steps'].append(entry)
            self.records['status'] = 'failed'
            self.save()
            raise RehearsalError(f'Step {number} ({title}) failed: {type(error).__name__}: {error}') from error
        entry.update(status='passed', seconds=round(time.monotonic() - started, 1))
        self.records['steps'].append(entry)
        self.save()
        print(f'PASS step {number}: {title} ({entry["seconds"]} s)', flush=True)

    def proved(self, message):
        self.current['checks'].append(message)

    # Environment: everything offline, GitHub modeled, publisher identity only inside publish jobs.
    def rewrites(self):
        return [(f'url.{self.remotes.as_uri()}/.insteadOf', f'https://github.com/{OWNER}/'),
                (f'url.{(self.remotes / "apple").as_uri()}/.insteadOf', 'https://github.com/apple/'),
                ('url.file:///offline-rehearsal/blocked/.insteadOf', 'https://github.com/')]

    def offline_env(self):
        """The anonymous build environment, with github.com rewritten to the local repositories or blocked."""
        env = anonymous_env()
        pairs = [('credential.helper', ''), *self.rewrites()]
        env['GIT_CONFIG_COUNT'] = str(len(pairs))
        for index, (key, value) in enumerate(pairs):
            env[f'GIT_CONFIG_KEY_{index}'], env[f'GIT_CONFIG_VALUE_{index}'] = key, value
        return env

    def mirror(self, package, allowlisted=True):
        """SwiftPM mirrors from the public URLs to the local bare repositories (the manifests keep public URLs)."""
        pairs = [(url(key), self.remotes / (name + '.git')) for key, name in NAMES.items()] if allowlisted else []
        for original, local in [*pairs, (COLLECTIONS, self.remotes / 'apple/swift-collections.git')]:
            run(['swift', 'package', 'config', 'set-mirror', '--original', original, '--mirror', local.as_uri()],
                cwd=package)

    @contextlib.contextmanager
    def environment(self, identity):
        bin_dir = self.dir / 'bin'
        bin_dir.mkdir()
        shim = bin_dir / 'gh'
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" gh "$@"\n')
        shim.chmod(0o755)
        self.developer, self.bot = self.dir / 'developer.gitconfig', self.dir / 'bot.gitconfig'
        self.developer.write_text(f'[user]\n\tname = {identity[0]}\n\temail = {identity[1]}\n')
        self.bot.write_text(f'[user]\n\tname = {BOT}\n\temail = {BOT_EMAIL}\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_CONFIG')
               and k not in ('GH_TOKEN', 'GITHUB_TOKEN', 'ENABLE_EXPERIMENTAL_PUBLICATION')}
        env.update(PATH=f'{bin_dir}{os.pathsep}{os.environ.get("PATH", "")}',
                   REHEARSAL_GITHUB=str(self.state_file.parent), GIT_CONFIG_GLOBAL=str(self.developer),
                   GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0', GIT_CONFIG_COUNT=str(len(self.rewrites())))
        for index, (key, value) in enumerate(self.rewrites()):
            env[f'GIT_CONFIG_KEY_{index}'], env[f'GIT_CONFIG_VALUE_{index}'] = key, value
        real_validate = publish.validate

        def validate(stage, state, mirror_root, package):
            # The reviewed route builds through the same local mirrors that the local-remotes route sets.
            self.mirror(stage, allowlisted=False)
            return real_validate(stage, state, self.remotes, package)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            stack.enter_context(patch.object(publish, 'validate', validate))
            for mod in (publish, project, reviewed_publication):
                stack.enter_context(patch.object(mod, 'anonymous_env', self.offline_env))
            if self.quick:
                stack.enter_context(patch.object(publish, 'platform_builds', lambda *args: None))
            check(shutil.which('gh') == str(shim), 'The modeled gh is not first on PATH')
            yield

    # GitHub model state.
    def state(self):
        return load(self.state_file)

    def releases(self, key):
        return self.state()['releases'].get(f'{OWNER}/{NAMES[key]}', [])

    def pulls(self, key):
        return self.state()['pulls'].get(f'{OWNER}/{NAMES[key]}', [])

    def bare(self, key):
        return self.remotes / (NAMES[key] + '.git')

    def refs(self, *keys):
        return {key: git(self.bare(key), 'for-each-ref', '--format=%(objectname) %(refname)') for key in keys}

    def snapshot(self):
        return {'refs': self.refs(*NAMES), 'source': git(self.remotes / (SOURCE_NAME + '.git'), 'for-each-ref'),
                'github': self.state()}

    # Repositories.
    @staticmethod
    def seed(bare, files, message, tag=None):
        """Push one commit with `files` (and an optional tag) to a new bare repository."""
        with tempfile.TemporaryDirectory(prefix='rehearsal-seed-') as temp:
            work = Path(temp)
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_bytes(content if isinstance(content, bytes) else content.encode())
            git(work, 'init', '--quiet', '--initial-branch=main')
            commit(work, message)
            if tag:
                git(work, 'tag', tag)
            run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', bare])
            git(work, 'push', '--quiet', bare, 'main', '--tags')

    def public(self, key, files, tag=None):
        """A public package repository as it exists before the monorepo publishes to it."""
        self.seed(self.bare(key), files, 'chore: existing public repository', tag)
        hook = self.bare(key) / 'hooks/pre-receive'
        hook.write_text(HOOK)
        hook.chmod(0o755)

    def human_change(self, key, title, edit):
        """A person's reviewed PR merged on GitHub: a clone, a commit, then a server-side main update."""
        with tempfile.TemporaryDirectory(prefix='rehearsal-human-') as temp:
            work = Path(temp) / 'work'
            run(['git', 'clone', '--quiet', url(key), work])
            edit(work)
            git(work, 'add', '--all')
            if git(work, 'status', '--porcelain'):
                git(work, 'commit', '--quiet', '-m', title)
            sha = git(work, 'rev-parse', 'HEAD')
            number = len(git(self.bare(key), 'for-each-ref', 'refs/merges').splitlines()) + 1
            git(work, 'push', '--quiet', 'origin', f'HEAD:refs/merges/{number}')
        git(self.bare(key), 'update-ref', 'refs/heads/main', sha)
        return sha

    def merge(self, key, branch):
        """A reviewer merges the bot PR."""
        state = self.state()
        pr = next(p for p in state['pulls'][f'{OWNER}/{NAMES[key]}'] if p['head']['ref'] == branch)
        check(pr['state'] == 'open' and pr['user']['login'] == BOT, f'{branch} is not an open bot PR')
        author = git(self.bare(key), 'log', '-1', '--format=%an <%ae>', 'refs/heads/' + branch)
        check(author == f'{BOT} <{BOT_EMAIL}>', f'Bot PR commit author differs: {author}')
        title = f'Merge pull request #{pr["number"]} from {branch}'
        sha = self.human_change(key, title, lambda work: git(work, 'merge', '--quiet', '--no-ff', '-m', title,
                                                             'origin/' + branch))
        pr.update(state='closed', merged=True, merge_commit_sha=sha)
        write_json(self.state_file, state)
        return sha

    def change(self, path, old, new, title, expected):
        """A reviewed source PR merged on the monorepo main; the affected packages are checked first."""
        file = self.source / path
        check(old in file.read_text(), f'{path} does not contain {old!r}')
        file.write_text(file.read_text().replace(old, new))
        check(affected([path], self.source) == expected, f'{path} should affect {expected}')
        sha = commit(self.source, title)
        git(self.source, 'push', '--quiet', 'origin', 'main')
        return sha

    def release(self, versions, sdk_minimum=None):
        """A merged Release Please PR: versions, constants and changelogs, then component tags and source Releases."""
        packages = inventory(self.source)
        manifest = load(self.source / '.release-please-manifest.json')
        for key, version in versions.items():
            package, old = packages[key], manifest[packages[key]['path']]
            if old == version:
                continue
            folder = self.source / package['path']
            (folder / 'version.txt').write_text(version + '\n')
            constants = folder / 'Sources' / package['target'] / 'Version.swift'
            constants.write_text(constants.read_text().replace(f'current = "{old}"', f'current = "{version}"'))
            with (folder / 'CHANGELOG.md').open('a') as changelog:
                changelog.write(f'\n## {version}\n\nLocal lifecycle rehearsal.\n')
            manifest[package['path']] = version
        if sdk_minimum:
            config = load(self.source / 'release/packages.json')
            for key in sdk_minimum[1]:
                config['packages'][key]['sdkMinimum'] = sdk_minimum[0]
            write_json(self.source / 'release/packages.json', config)
            dependency_markers(self.source)
        write_json(self.source / '.release-please-manifest.json', manifest)
        sha = commit(self.source, 'chore: release main')
        git(self.source, 'push', '--quiet', 'origin', 'main')
        for key, version in versions.items():
            self.intent(f'{packages[key]["component"]}-{version}', sha)
        return sha

    def intent(self, tag, sha):
        git(self.source, 'tag', tag, sha)
        git(self.source, 'push', '--quiet', 'origin', 'refs/tags/' + tag)
        state = self.state()
        state['releases'].setdefault(SOURCE, []).append(
            {'tag_name': tag, 'name': tag, 'body': 'Release Please intent (modeled)', 'draft': False,
             'prerelease': False,
             'html_url': f'local-github://{SOURCE}/releases/tag/{tag}'})
        write_json(self.state_file, state)

    # Workflows.
    def job(self, key, version, sha, mode='normal'):
        """publish.yml: check out the approved source SHA, then publish as the App bot."""
        git(self.release_source, 'fetch', '--quiet', '--tags', 'origin')
        git(self.release_source, 'checkout', '--quiet', '--detach', sha)
        git(self.release_source, 'merge-base', '--is-ancestor', sha, 'origin/main')
        with patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(self.bot), ENABLE_EXPERIMENTAL_PUBLICATION='true'):
            try:
                result = publish.publish(key, version, root=self.release_source, mode=mode)
            except FAILURES as error:
                result = {'status': 'incomplete', 'package': key, 'version': version, 'error': str(error)}
        self.current.setdefault('jobs', []).append(result)
        return result

    def recover(self):
        """complete-publication.yml: scan every package, then one publish job per pending item, SDK first."""
        git(self.runner, 'fetch', '--quiet', '--tags', 'origin')
        git(self.runner, 'checkout', '--quiet', '--detach', 'origin/main')
        pending, skipped = queue(self.runner)
        results = [self.job(i['package'], i['version'], i['source_sha']) for i in pending]
        statuses = {f'{r["package"]} {r["version"]}': r['status'] for r in results}
        statuses.update({f'{s["package"]} {s["version"]}': 'skipped ' + s['status'] for s in skipped})
        self.current.setdefault('recover', []).append(statuses)
        return statuses

    def consumer(self, key, version):
        """A clean SwiftPM consumer of one package at one version: fresh state, no credentials, local mirrors only."""
        package = inventory(self.source)[key]
        folder = self.dir / 'consumers' / f'{key}-{version}'
        main = folder / 'Sources/Consumer/main.swift'
        main.parent.mkdir(parents=True)
        main.write_text(f'import {package["target"]}\nprint({package["target"]}Version.current)\n')
        (folder / 'Package.swift').write_text(
            '// swift-tools-version: 5.9\nimport PackageDescription\nlet package = Package(\n'
            '    name: "Consumer",\n    platforms: [.iOS(.v15), .macOS(.v12)],\n'
            f'    dependencies: [.package(url: "{url(key)}", exact: "{version}")],\n'
            f'    targets: [.executableTarget(name: "Consumer", dependencies: [.product(name: "{package["target"]}", '
            f'package: "{NAMES[key]}")])]\n)\n')
        self.mirror(folder)
        with tempfile.TemporaryDirectory(prefix='rehearsal-consumer-') as state:
            output = run(['swift', 'run', *swift_options(Path(state)), 'Consumer'], cwd=folder, env=self.offline_env())
        shutil.rmtree(folder / '.swiftpm')
        pins = {p['identity']: p['state'] for p in load(folder / 'Package.resolved')['pins']}
        check(output.splitlines()[-1] == version, f'{key} {version} consumer printed {output.splitlines()[-1:]}')
        check(pins[NAMES[key]].get('version') == version, f'{key} resolved {pins[NAMES[key]]}')
        return {'package': key, 'version': version, 'pins': {k: v.get('version') for k, v in pins.items()}}

    def ios_consumer(self, versions):
        """The sibling consumer template (CLI and iOS Simulator app) at the given versions, through local mirrors."""
        folder = self.dir / 'consumers' / 'ios-template'
        run(['git', 'clone', '--quiet', '--no-local', '--branch', RELEASE_BRANCH, self.template, folder])
        module(folder / 'scripts/dependencies.py', 'consumer_dependencies').render(
            folder, [f'{k}={v}' for k, v in versions.items()])
        self.mirror(folder, allowlisted=False)
        evidence = module(folder / 'scripts/verify.py', 'consumer_verify').verify(folder, self.remotes, True)
        shutil.rmtree(folder / 'DerivedData', ignore_errors=True)
        check(evidence['runtime'].get('iOSSimulatorBuild') == 'passed', 'iOS consumer build did not pass')
        return evidence['runtime']

    # Setup.
    def setup(self):
        """Monorepo from the fixture, one bare public repository per allowlisted package, and the GitHub model."""
        write_json(self.state_file, {'remotes': str(self.remotes), 'pulls': {}, 'releases': {}})
        shutil.copytree(FIXTURE, self.source, ignore=shutil.ignore_patterns('.build', '.swiftpm', '__pycache__'))
        for name in ('LICENSE', '.gitignore'):
            shutil.copyfile(ROOT / name, self.source / name)
        git(self.dir, 'init', '--quiet', '--initial-branch=main', self.source.name)
        commit(self.source, 'chore: import the fixture monorepo')
        run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', self.remotes / (SOURCE_NAME + '.git')])
        git(self.source, 'remote', 'add', 'origin', f'https://github.com/{SOURCE}.git')
        git(self.source, 'push', '--quiet', 'origin', 'main')
        for folder in (self.runner, self.release_source):
            run(['git', 'clone', '--quiet', f'https://github.com/{SOURCE}.git', folder])
        self.seed(self.remotes / 'apple/swift-collections.git', COLLECTIONS_FILES,
                  'test: local stand-in for swift-collections', '1.1.4')
        readme_only = {'README.md': '# Package\n', 'LICENSE': 'MIT\n', '.gitignore': '.build/\n'}
        self.public('sdk', readme_only)
        self.public('firebase', readme_only)
        # Sprig existed before the monorepo: same Sources/ at tag 0.1.1, plus foreign files and workflows.
        with tempfile.TemporaryDirectory(prefix='rehearsal-legacy-') as temp:
            stage = Path(temp) / 'export'
            project.export('sprig', '0.1.1', stage, self.source)
            legacy = {p.relative_to(stage).as_posix(): p.read_bytes()
                      for p in sorted((stage / 'Sources').rglob('*')) if p.is_file()}
        self.public('sprig', {**legacy, **LEGACY_FILES, 'Package.swift': LEGACY_SPRIG}, tag='0.1.1')
        self.records['sourceFixtureCommit'] = git(self.source, 'rev-parse', 'HEAD')
        # Any other github.com URL fails, in the lab and in the anonymous build environment.
        for env in (None, self.offline_env()):
            for address in ('https://github.com/swiftlang/swift.git', f'https://github.com/{OWNER}/unknown.git'):
                try:
                    run(['git', 'ls-remote', address], env=env)
                except RuntimeError:
                    continue
                raise AssertionError(f'{address} is reachable from the rehearsal')


def step_1(lab):
    sha = lab.release({'sdk': '0.1.0'})
    readme_main = git(lab.bare('sdk'), 'rev-parse', 'main')
    check(lab.recover() == {'sdk 0.1.0': 'awaiting_review'}, 'SDK bootstrap PR expected')
    pr = lab.pulls('sdk')[0]
    check(pr['head']['ref'] == 'publication/sdk/0.1.0' and 'README-only' in pr['body'], 'bootstrap PR')
    check(git(lab.bare('sdk'), 'rev-parse', 'main') == readme_main and not git(lab.bare('sdk'), 'tag'),
          'an open bot PR changed main or tags')
    check(lab.recover() == {'sdk 0.1.0': 'skipped awaiting_review'}, 'open PR must not be rebuilt')
    check(len(lab.pulls('sdk')) == 1 and lab.pulls('sdk')[0]['head']['sha'] == pr['head']['sha'],
          'Recover rebuilt an open PR')
    merged = lab.merge('sdk', 'publication/sdk/0.1.0')
    check(lab.recover() == {'sdk 0.1.0': 'published'}, 'Recover should tag the merged bootstrap')
    check(git(lab.bare('sdk'), 'rev-parse', '0.1.0^{commit}') == merged, 'tag is not the merge commit')
    check(json.loads(git(lab.bare('sdk'), 'show', '0.1.0:.publication.json'))['sourceCommit'] == sha,
          'provenance source commit')
    check([r['body'] for r in lab.releases('sdk')] == [text('releaseBody', source=sha, publication=merged)],
          'Release record')
    check('README.md' in git(lab.bare('sdk'), 'ls-tree', '--name-only', '0.1.0') and
          'Package.swift' in git(lab.bare('sdk'), 'ls-tree', '--name-only', '0.1.0'), 'bootstrap tree')
    lab.proved('README-only repo got a bootstrap bot PR, no tag while open, Recover did not rebuild the open PR')
    lab.proved('after the reviewed merge, Recover tagged 0.1.0 at the merge commit and created the Release')


def step_2(lab):
    anchor_sha = git(lab.source, 'rev-parse', 'HEAD')
    git(lab.runner, 'fetch', '--quiet', 'origin')
    tag = anchor('sprig', '0.1.1', anchor_sha, lab.runner)
    check(tag == 'integration-sprig-0.1.1', 'anchor tag name')
    git(lab.source, 'tag', tag, anchor_sha)
    git(lab.source, 'push', '--quiet', 'origin', 'refs/tags/' + tag)
    baseline = git(lab.bare('sprig'), 'rev-parse', '0.1.1^{commit}')
    before = lab.refs('sprig')
    check(lab.job('sprig', '0.1.1', anchor_sha)['status'] == 'awaiting_takeover', 'foreign repo must wait')
    result = lab.job('sprig', '0.1.1', anchor_sha, 'takeover')
    check((result['status'], result.get('reason')) == ('awaiting_takeover', WORKFLOWS), str(result))
    check(lab.refs('sprig') == before and not lab.pulls('sprig'), 'takeover wrote while workflows exist')
    lab.proved('normal mode waits as awaiting_takeover; takeover refuses while .github/workflows exists')
    lab.human_change('sprig', 'ci: remove workflows, releases move to the monorepo',
                     lambda work: git(work, 'rm', '-r', '--quiet', '.github/workflows'))
    result = lab.job('sprig', '0.1.1', anchor_sha, 'takeover')
    check((result['status'], result.get('branch')) == ('awaiting_review', 'takeover/sprig/0.1.1'), str(result))
    head = 'refs/heads/takeover/sprig/0.1.1'
    files = git(lab.bare('sprig'), 'ls-tree', '-r', '--name-only', head).splitlines()
    check(not [f for f in files if f.startswith(('.github/workflows', 'Tests/', 'Example/'))], 'foreign files kept')
    check(git(lab.bare('sprig'), 'rev-parse', f'{head}:Sources') == git(lab.bare('sprig'), 'rev-parse',
                                                                         '0.1.1:Sources'), 'Sources/ differ')
    body = lab.pulls('sprig')[0]['body']
    check(all(f'- `{f}`' in body for f in ('LICENSE.md', 'Tests/DemoSprigTests/DemoSprigTests.swift',
                                             '.swiftlint.yml')), 'removed files missing from the PR body')
    check(git(lab.bare('sprig'), 'tag') == '0.1.1', 'takeover created a tag')
    merged = lab.merge('sprig', 'takeover/sprig/0.1.1')
    result = lab.job('sprig', '0.1.1', anchor_sha, 'takeover')
    check((result['status'], result.get('takeover'), result.get('publicationCommit')) ==
          ('published', True, merged), str(result))
    check(git(lab.bare('sprig'), 'rev-parse', '0.1.1^{commit}') == baseline and not lab.releases('sprig'),
          'takeover moved the tag or created a Release')
    lab.proved('after a person removed .github/workflows, one takeover bot PR removed foreign files, kept '
               'Sources/ byte-identical to tag 0.1.1 and passed the dump-package check')
    lab.proved('after merge, takeover reports published; tag 0.1.1 still points at the old commit; no Release')


def step_3(lab):
    others = lab.refs('sdk', 'firebase')
    lab.change('Integrations/Sprig/Sources/DemoSprig/DemoSprig.swift', '"unnamed event"', '"unnamed sprig event"',
               'fix(sprig): name empty sprig events', ['sprig'])
    sha = lab.release({'sprig': '0.1.2'})
    check(lab.recover() == {'sprig 0.1.2': 'awaiting_review'}, 'sprig PR expected')
    check(git(lab.bare('sprig'), 'tag') == '0.1.1', 'tag before merge')
    merged = lab.merge('sprig', 'publication/sprig/0.1.2')
    check(lab.recover() == {'sprig 0.1.2': 'published'}, 'sprig should publish')
    check(git(lab.bare('sprig'), 'rev-parse', '0.1.2^{commit}') == merged, 'tag is not the merge commit')
    generated = git(lab.bare('sprig'), 'show', '0.1.2:Sources/DemoSprig/DemoSprig.swift')
    check('unnamed sprig event' in generated and 'import DemoShared' not in generated, 'exported source')
    check(json.loads(git(lab.bare('sprig'), 'show', '0.1.2:.publication.json'))['sourceCommit'] == sha,
          'provenance')
    check(lab.releases('sprig')[-1]['body'] == text('releaseBody', source=sha, publication=merged), 'Release')
    lab.integration_only = lab.refs('sdk', 'firebase') == others
    lab.proved('sprig 0.1.2: export and build before the bot PR; tag at the merge commit after Recover')


def step_4(lab):
    check(lab.integration_only, 'the sprig release changed SDK or Firebase refs')
    others = lab.refs('sprig', 'firebase')
    lab.change('Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift', 'public static func hasPrivacyManifest',
               '/// Reports whether the privacy manifest ships.\n    public static func hasPrivacyManifest',
               'fix(sdk): document the privacy manifest check', ['sdk'])
    lab.release({'sdk': '0.1.1'})
    check(lab.recover() == {'sdk 0.1.1': 'awaiting_review'}, 'SDK PR expected')
    lab.merge('sdk', 'publication/sdk/0.1.1')
    check(lab.recover() == {'sdk 0.1.1': 'published'}, 'SDK should publish')
    check(lab.refs('sprig', 'firebase') == others, 'the SDK release changed integration refs')
    lab.proved('sprig 0.1.2 left SDK and Firebase refs unchanged; SDK 0.1.1 left Sprig and Firebase unchanged')


def step_5(lab):
    lab.change('Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift', 'public enum DemoSDK {',
               'public enum DemoSDK {\n    public static let apiLevel = 2', 'feat(sdk): add an API level',
               ['sdk'])
    lab.release({'sdk': '0.2.0', 'firebase': '0.1.0'}, sdk_minimum=('0.2.0', ['firebase']))
    status = lab.recover()
    check(status == {'sdk 0.2.0': 'awaiting_review', 'firebase 0.1.0': 'awaiting_dependency'}, str(status))
    check(not lab.pulls('firebase') and not git(lab.bare('firebase'), 'tag'), 'firebase wrote while waiting')
    lab.merge('sdk', 'publication/sdk/0.2.0')
    status = lab.recover()
    check(status == {'sdk 0.2.0': 'published', 'firebase 0.1.0': 'awaiting_review'}, str(status))
    check(lab.pulls('firebase')[0]['head']['ref'] == 'publication/firebase/0.1.0', 'firebase bootstrap PR')
    manifest = git(lab.bare('firebase'), 'show', 'publication/firebase/0.1.0:Package.swift')
    check('from: "0.2.0"' in manifest and 'exact: "1.1.4"' in manifest, 'firebase requirements')
    lab.merge('firebase', 'publication/firebase/0.1.0')
    lab.proved('firebase 0.1.0 (sdkMinimum 0.2.0) was awaiting_dependency while the SDK 0.2.0 PR was open')
    lab.proved('the same Recover that tagged SDK 0.2.0 then built Firebase and opened its bootstrap PR; '
               'merged here, tagged in step 6')


def step_6(lab):
    with tempfile.TemporaryDirectory(prefix='rehearsal-side-') as temp:
        side = Path(temp) / 'work'
        run(['git', 'clone', '--quiet', f'https://github.com/{SOURCE}.git', side])
        (side / 'Integrations/Sprig/version.txt').write_text('0.1.9\n')
        broken = commit(side, 'test: unreviewed side-branch release')
        git(side, 'push', '--quiet', 'origin', 'HEAD:refs/heads/side')
    git(lab.source, 'fetch', '--quiet', 'origin')
    lab.intent('integration-sprig-0.1.9', broken)
    before = lab.refs('sprig')
    status = lab.recover()
    check(status == {'firebase 0.1.0': 'published', 'sprig 0.1.9': 'skipped incomplete'}, str(status))
    check(lab.refs('sprig') == before, 'the broken item changed refs')
    check(git(lab.bare('firebase'), 'rev-parse', '0.1.0^{commit}') ==
          git(lab.bare('firebase'), 'rev-parse', 'main'), 'firebase tag')
    lab.proved('a source release off main was reported incomplete and skipped; Firebase 0.1.0 still '
               'completed in the same Recover')


def step_7(lab):
    lab.human_change('sprig', 'docs: hand edit on the public repository',
                     lambda work: (work / 'README.md').write_text((work / 'README.md').read_text() + 'Edited.\n'))
    lab.change('Integrations/Sprig/Sources/DemoSprig/DemoSprig.swift', '"unnamed sprig event"', '"unnamed event"',
               'fix(sprig): restore the empty event name', ['sprig'])
    lab.release({'sprig': '0.1.3'})
    before = lab.refs('sprig')
    status = lab.recover()
    check(status == {'sprig 0.1.3': 'incomplete', 'sprig 0.1.9': 'skipped incomplete'}, str(status))
    check('manual drift' in lab.current['jobs'][-1]['error'], lab.current['jobs'][-1]['error'])
    check(lab.refs('sprig') == before and len(lab.pulls('sprig')) == 2, 'drift run wrote refs or a PR')
    lab.proved('a hand edit on sprig main stopped sprig 0.1.3 before any branch, PR or tag')
    # Ingest (reverse sync) is not implemented yet: a person reverts the edit by a reviewed PR instead.
    lab.human_change('sprig', 'revert: hand edit on the public repository',
                     lambda work: git(work, 'checkout', 'HEAD~1', '--', 'README.md'))
    check(lab.recover() == {'sprig 0.1.3': 'awaiting_review', 'sprig 0.1.9': 'skipped incomplete'},
          'sprig PR expected after the revert')
    lab.merge('sprig', 'publication/sprig/0.1.3')
    check(lab.recover() == {'sprig 0.1.3': 'published', 'sprig 0.1.9': 'skipped incomplete'}, 'sprig 0.1.3')
    lab.proved('after the edit was reverted by a reviewed PR, Recover published sprig 0.1.3')


def step_8(lab):
    before = lab.snapshot()
    for _ in range(2):
        check(lab.recover() == {'sprig 0.1.9': 'skipped incomplete'}, 'nothing should be pending')
    check(lab.snapshot() == before, 'Recover changed refs, PRs or Releases')
    tags = {key: git(lab.bare(key), 'tag', '--sort=v:refname').split() for key in NAMES}
    check(tags == {'sdk': ['0.1.0', '0.1.1', '0.2.0'], 'sprig': ['0.1.1', '0.1.2', '0.1.3'],
                   'firebase': ['0.1.0']}, str(tags))
    lab.records['publicTags'] = tags
    lab.proved('two more Recover runs changed no ref, PR or Release; only the broken item is reported')


def step_9(lab):
    consumers = [lab.consumer(key, version) for key, version in
                 (('sdk', '0.1.0'), ('sprig', '0.1.1'), ('firebase', '0.1.0'))]
    lab.records['consumers'] = consumers
    lab.proved('one package at a time, fresh SwiftPM state, offline mirrors: SDK 0.1.0, the pre-monorepo '
               'Sprig 0.1.1 tag and Firebase 0.1.0 resolve and run')
    if lab.ios:
        # Firebase 0.1.0 needs SDK 0.2.0, so the all-in-one app takes the oldest set that resolves together.
        lab.records['iosConsumer'] = lab.ios_consumer({'sdk': '0.2.0', 'sprig': '0.1.1', 'firebase': '0.1.0'})
        lab.proved('consumer template CLI and iOS Simulator app build with SDK 0.2.0, Sprig 0.1.1, Firebase 0.1.0')


STEPS = [
    ('bootstrap a README-only public repository', step_1),
    ('take over a foreign public repository', step_2),
    ('release an integration: export, build, bot PR, merge, Recover tags it', step_3),
    ('an integration-only release leaves the SDK untouched, and vice versa', step_4),
    ('an integration waits for its SDK tag, then continues', step_5),
    ('a broken item is skipped while the others complete', step_6),
    ('drift in a public repository blocks publishing', step_7),
    ('Recover is idempotent', step_8),
    ('old tags still resolve for clean consumers', step_9),
]


def rehearse(ios=False, consumer_template=None, base=None, quick=False, through=len(STEPS)):
    """Run steps 0..`through` in a new `<base>/<timestamp>/` folder (default `.lab`); earlier runs are never touched."""
    base = Path(base or ROOT / '.lab').resolve()
    directory = base / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True)
    write_json(base / 'latest.json', {'path': str(directory)})
    if ios:
        consumer_template = Path(consumer_template or ROOT.parent / CONSUMER_NAME)
        if not (consumer_template / 'scripts/verify.py').exists():
            raise RehearsalError(f'--ios needs the consumer template checkout at {consumer_template}')
    # The configured Git identity authors developer and reviewer commits; the modeled App bot authors publication.
    ident = git(ROOT, 'var', 'GIT_AUTHOR_IDENT')
    identity = (ident.split(' <')[0], ident.split(' <')[1].split('>')[0])
    lab = Lab(directory, quick)
    lab.ios, lab.template = ios, consumer_template
    lab.records.update(through=through, tool=ROOT.as_posix(), toolCommit=git(ROOT, 'rev-parse', 'HEAD'),
                       swift=run(['swift', '--version']).splitlines()[0],
                       xcode=' '.join(run(['xcodebuild', '-version']).split()))
    started = time.monotonic()
    with lab.environment(identity):
        with lab.step(0, 'set up the fixture monorepo and local public repositories'):
            lab.setup()
            lab.proved('sdk and firebase public repositories are README-only; sprig has foreign files, '
                       '.github/workflows and tag 0.1.1')

        for number, (title, action) in enumerate(STEPS[:through], 1):
            with lab.step(number, title):
                action(lab)
    lab.records.update(status='passed', seconds=round(time.monotonic() - started, 1))
    lab.save()
    print(json.dumps({'status': 'passed', 'seconds': lab.records['seconds'],
                      'evidence': str(directory / 'evidence.json')}, indent=2), flush=True)
    return directory


if __name__ == '__main__':
    if sys.argv[1:2] == ['gh']:
        try:
            github(sys.argv[2:])
        except Exception as error:
            print(f'modeled gh: {error}', file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--ios', action='store_true', help='also build the sibling consumer template for iOS Simulator')
    parser.add_argument('--consumer-template', type=Path)
    parser.add_argument('--quick', action='store_true', help='skip the xcodebuild platform builds in the publisher')
    parser.add_argument('--through', type=int, choices=range(len(STEPS) + 1), default=len(STEPS),
                        help='stop after this step')
    args = parser.parse_args()
    try:
        rehearse(args.ios, args.consumer_template, quick=args.quick, through=args.through)
    except RehearsalError as error:
        raise SystemExit(f'Rehearsal failed: {error}')
