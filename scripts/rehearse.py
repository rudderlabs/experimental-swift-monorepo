"""Local publication lifecycle on temporary fixture repositories. Git, SwiftPM and Xcode are real; GitHub is modeled.

`python3 scripts/rehearse.py` builds a throwaway monorepo from Tests/Fixtures/demo and one local bare "public"
repository per allowlisted package, then runs bootstrap, takeover, releases, Tag & Release Packages, drift, clean
consumers and a maintenance-line patch.
Nothing reaches GitHub: `gh` is a local model on PATH and every github.com Git URL is rewritten to a local
bare repository or to a path that does not exist.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import parse_qsl

from common import (ROOT, OWNER, RELEASE_BRANCH, SOURCE_NAME, allowlist, anonymous_env, commit, git,
                    inventory, load, run, swift_options, url, write_json)
from anchor import anchor
from maintenance_branch import create as create_maintenance_branch, source_line
import project
import publish
import reviewed_publication
from publication_queue import queue
from dependency_policy import markers as dependency_markers
from release_plan import affected
from reviewed_publication import BOT, WORKFLOWS
import verify_public_customer

FIXTURE = ROOT / 'Tests/Fixtures/demo'
NAMES = allowlist()
SOURCE = f'{OWNER}/{SOURCE_NAME}'
COLLECTIONS = 'https://github.com/apple/swift-collections.git'
BOT_EMAIL = '12345678+rudderstack-github-actions[bot]@users.noreply.github.com'  # modeled App bot user id
FAILURES = (ValueError, RuntimeError, OSError, KeyError)
# Models the branch and tag rulesets: main and release/X.Y.x change only through a reviewed merge (the bot may create
# a release/X.Y.x branch), and tags never move.
HOOK = '''#!/bin/sh
while read old new ref; do
  case "$ref" in
    refs/heads/main) echo "main changes only through a reviewed pull request" >&2; exit 1;;
    refs/heads/release/*) [ "$old" = 0000000000000000000000000000000000000000 ] || {
      echo "release branches change only through a reviewed pull request" >&2; exit 1; };;
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
                         'make_latest': 'false' if '--latest=false' in args else 'default',
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
        elif resource[:1] == ['issues'] and resource[2:] == ['comments']:
            output = []  # the rehearsal never discards a version
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

    def human_change(self, key, title, edit, base=RELEASE_BRANCH):
        """A person's reviewed PR merged on GitHub: a clone, a commit, then a server-side `base` update."""
        with tempfile.TemporaryDirectory(prefix='rehearsal-human-') as temp:
            work = Path(temp) / 'work'
            run(['git', 'clone', '--quiet', '--branch', base, url(key), work])
            edit(work)
            git(work, 'add', '--all')
            if git(work, 'status', '--porcelain'):
                git(work, 'commit', '--quiet', '-m', title)
            sha = git(work, 'rev-parse', 'HEAD')
            number = len(git(self.bare(key), 'for-each-ref', 'refs/merges').splitlines()) + 1
            git(work, 'push', '--quiet', 'origin', f'HEAD:refs/merges/{number}')
        git(self.bare(key), 'update-ref', f'refs/heads/{base}', sha)
        return sha

    def merge(self, key, branch):
        """A reviewer merges the bot PR into its base."""
        state = self.state()
        pr = next(p for p in state['pulls'][f'{OWNER}/{NAMES[key]}'] if p['head']['ref'] == branch)
        check(pr['state'] == 'open' and pr['user']['login'] == BOT, f'{branch} is not an open bot PR')
        author = git(self.bare(key), 'log', '-1', '--format=%an <%ae>', 'refs/heads/' + branch)
        check(author == f'{BOT} <{BOT_EMAIL}>', f'Bot PR commit author differs: {author}')
        title = f'Merge pull request #{pr["number"]} from {branch}'
        sha = self.human_change(key, title, lambda work: git(work, 'merge', '--quiet', '--no-ff', '-m', title,
                                                             'origin/' + branch), pr['base']['ref'])
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

    def release(self, versions, sdk_minimum=None, work=None, branch=RELEASE_BRANCH):
        """A merged Release Please PR on `branch` (checked out in `work`, default the source clone on main): versions,
        constants and changelogs, then component tags and source Releases."""
        work = work or self.source
        packages = inventory(work)
        manifest = load(work / '.release-please-manifest.json')
        for key, version in versions.items():
            package, old = packages[key], manifest[packages[key]['path']]
            if old == version:
                continue
            folder = work / package['path']
            (folder / 'version.txt').write_text(version + '\n')
            constants = folder / 'Sources' / package['target'] / 'Version.swift'
            constants.write_text(constants.read_text().replace(f'current = "{old}"', f'current = "{version}"'))
            with (folder / 'CHANGELOG.md').open('a') as changelog:
                changelog.write(f'\n## {version}\n\nLocal lifecycle rehearsal.\n')
            manifest[package['path']] = version
        if sdk_minimum:
            config = load(work / 'release/packages.json')
            for key in sdk_minimum[1]:
                config['packages'][key]['sdkMinimum'] = sdk_minimum[0]
            write_json(work / 'release/packages.json', config)
            dependency_markers(work)
        write_json(work / '.release-please-manifest.json', manifest)
        sha = commit(work, f'chore: release {branch}')
        git(work, 'push', '--quiet', 'origin', f'HEAD:refs/heads/{branch}')
        git(self.source, 'fetch', '--quiet', 'origin')
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
        # The publish.yml preflight: on main, or on the version's maintenance branch.
        source_line(self.release_source, key, sha, version)
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

    def ios_consumer(self, key, version):
        """The post-publish customer check's generated package (one import, exact version) built with xcodebuild on
        each checked platform the package supports; system Git resolves through the local repositories."""
        package = inventory(self.source)[key]
        folder = self.dir / 'consumers' / f'xcode-{key}-{version}'
        verify_public_customer.write_consumer(folder, package, url(key), version)
        built = verify_public_customer.platforms(package)
        with tempfile.TemporaryDirectory(prefix='rehearsal-xcode-consumer-') as state:
            # A fresh home: the local Swift Collections stand-in must not meet the real tag's recorded fingerprint.
            home = Path(state) / 'home'
            home.mkdir()
            env = {**self.offline_env(), 'HOME': str(home), 'CFFIXED_USER_HOME': str(home)}
            for platform in built:
                verify_public_customer.build(folder, platform, Path(state), env)
        pins = {p['identity']: p['state'] for p in load(folder / 'Package.resolved')['pins']}
        check(pins[NAMES[key]].get('version') == version, f'{key} resolved {pins[NAMES[key]]}')
        return {'package': key, 'version': version, 'platforms': built,
                'pins': {k: v.get('version') for k, v in pins.items()}}

    # Setup.
    def setup(self):
        """Monorepo from the fixture, one bare public repository per allowlisted package, and the GitHub model."""
        write_json(self.state_file, {'remotes': str(self.remotes), 'pulls': {}, 'releases': {}})
        shutil.copytree(FIXTURE, self.source, ignore=shutil.ignore_patterns('.build', '.swiftpm', '__pycache__'))
        for name in ('LICENSE', '.gitignore'):
            shutil.copyfile(ROOT / name, self.source / name)
        # The real config with the fixture packages: Create Maintenance Branch rewrites it.
        config = load(ROOT / 'release-please-config.json')
        config['packages'] = {p['path']: {'component': p['component']} for p in inventory(self.source).values()}
        write_json(self.source / 'release-please-config.json', config)
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
        self.public('swift-sdk', readme_only)
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
    sha = lab.release({'swift-sdk': '0.1.0'})
    readme_main = git(lab.bare('swift-sdk'), 'rev-parse', 'main')
    check(lab.recover() == {'swift-sdk 0.1.0': 'awaiting_review'}, 'SDK bootstrap PR expected')
    pr = lab.pulls('swift-sdk')[0]
    check(pr['head']['ref'] == 'publication/swift-sdk/0.1.0' and 'README-only' in pr['body'], 'bootstrap PR')
    check(git(lab.bare('swift-sdk'), 'rev-parse', 'main') == readme_main and not git(lab.bare('swift-sdk'), 'tag'),
          'an open bot PR changed main or tags')
    check(lab.recover() == {'swift-sdk 0.1.0': 'skipped awaiting_review'}, 'open PR must not be rebuilt')
    check(len(lab.pulls('swift-sdk')) == 1 and lab.pulls('swift-sdk')[0]['head']['sha'] == pr['head']['sha'],
          'Tag & Release Packages rebuilt an open PR')
    merged = lab.merge('swift-sdk', 'publication/swift-sdk/0.1.0')
    check(lab.recover() == {'swift-sdk 0.1.0': 'published'}, 'Tag & Release Packages should tag the merged bootstrap')
    check(git(lab.bare('swift-sdk'), 'rev-parse', '0.1.0^{commit}') == merged, 'tag is not the merge commit')
    check(json.loads(git(lab.bare('swift-sdk'), 'show', '0.1.0:.publication.json'))['sourceCommit'] == sha,
          'provenance source commit')
    release = lab.releases('swift-sdk')
    check(len(release) == 1 and release[0]['name'] == '0.1.0' and release[0]['body'].startswith('# DemoSDK 0.1.0\n\n')
          and release[0]['body'].endswith(f'\n\nSource: monorepo commit https://github.com/{OWNER}/{SOURCE_NAME}'
                                          f'/commit/{sha}\n'), f'Release record: {release}')
    check(lab.pulls('swift-sdk')[0]['title'] == 'chore(release): 0.1.0', 'publish PR title')
    check('README.md' in git(lab.bare('swift-sdk'), 'ls-tree', '--name-only', '0.1.0') and
          'Package.swift' in git(lab.bare('swift-sdk'), 'ls-tree', '--name-only', '0.1.0'), 'bootstrap tree')
    lab.proved('README-only repo got a bootstrap bot PR, no tag while open, Tag & Release Packages did not rebuild the '
               'open PR')
    lab.proved('after the reviewed merge, Tag & Release Packages tagged 0.1.0 at the merge commit and created the Release')


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
    others = lab.refs('swift-sdk', 'firebase')
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
    release = lab.releases('sprig')[-1]
    check(release['name'] == '0.1.2' and release['body'].startswith('# DemoSprig 0.1.2\n\nLocal lifecycle') and
          f'**Full Changelog**: https://github.com/{OWNER}/{NAMES["sprig"]}/compare/0.1.1...0.1.2\n' in
          release['body'] and release['body'].endswith(f'/commit/{sha}\n'), 'Release')
    lab.integration_only = lab.refs('swift-sdk', 'firebase') == others
    lab.proved('sprig 0.1.2: export and build before the bot PR; tag at the merge commit after Tag & Release Packages')


def step_4(lab):
    check(lab.integration_only, 'the sprig release changed SDK or Firebase refs')
    others = lab.refs('sprig', 'firebase')
    lab.change('Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift', 'public static func hasPrivacyManifest',
               '/// Reports whether the privacy manifest ships.\n    public static func hasPrivacyManifest',
               'fix(swift-sdk): document the privacy manifest check', ['swift-sdk'])
    lab.release({'swift-sdk': '0.1.1'})
    check(lab.recover() == {'swift-sdk 0.1.1': 'awaiting_review'}, 'SDK PR expected')
    lab.merge('swift-sdk', 'publication/swift-sdk/0.1.1')
    check(lab.recover() == {'swift-sdk 0.1.1': 'published'}, 'SDK should publish')
    check(lab.refs('sprig', 'firebase') == others, 'the SDK release changed integration refs')
    lab.proved('sprig 0.1.2 left SDK and Firebase refs unchanged; SDK 0.1.1 left Sprig and Firebase unchanged')


def step_5(lab):
    lab.change('Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift', 'public enum DemoSDK {',
               'public enum DemoSDK {\n    public static let apiLevel = 2', 'feat(swift-sdk): add an API level',
               ['swift-sdk'])
    lab.release({'swift-sdk': '0.2.0', 'firebase': '0.1.0'}, sdk_minimum=('0.2.0', ['firebase']))
    status = lab.recover()
    check(status == {'swift-sdk 0.2.0': 'awaiting_review', 'firebase 0.1.0': 'awaiting_dependency'}, str(status))
    check(not lab.pulls('firebase') and not git(lab.bare('firebase'), 'tag'), 'firebase wrote while waiting')
    lab.merge('swift-sdk', 'publication/swift-sdk/0.2.0')
    status = lab.recover()
    check(status == {'swift-sdk 0.2.0': 'published', 'firebase 0.1.0': 'awaiting_review'}, str(status))
    check(lab.pulls('firebase')[0]['head']['ref'] == 'publication/firebase/0.1.0', 'firebase bootstrap PR')
    manifest = git(lab.bare('firebase'), 'show', 'publication/firebase/0.1.0:Package.swift')
    check('from: "0.2.0"' in manifest and 'exact: "1.1.4"' in manifest, 'firebase requirements')
    lab.merge('firebase', 'publication/firebase/0.1.0')
    lab.proved('firebase 0.1.0 (sdkMinimum 0.2.0) was awaiting_dependency while the SDK 0.2.0 PR was open')
    lab.proved('the same Tag & Release Packages run that tagged SDK 0.2.0 then built Firebase and opened its bootstrap '
               'PR; merged here, tagged in step 6')


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
               'completed in the same Tag & Release Packages run')


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
    # The edit is to the generated README, which sync back cannot copy; a person reverts it by a reviewed PR.
    lab.human_change('sprig', 'revert: hand edit on the public repository',
                     lambda work: git(work, 'checkout', 'HEAD~1', '--', 'README.md'))
    check(lab.recover() == {'sprig 0.1.3': 'awaiting_review', 'sprig 0.1.9': 'skipped incomplete'},
          'sprig PR expected after the revert')
    lab.merge('sprig', 'publication/sprig/0.1.3')
    check(lab.recover() == {'sprig 0.1.3': 'published', 'sprig 0.1.9': 'skipped incomplete'}, 'sprig 0.1.3')
    lab.proved('after the edit was reverted by a reviewed PR, Tag & Release Packages published sprig 0.1.3')


def step_8(lab):
    before = lab.snapshot()
    for _ in range(2):
        check(lab.recover() == {'sprig 0.1.9': 'skipped incomplete'}, 'nothing should be pending')
    check(lab.snapshot() == before, 'Tag & Release Packages changed refs, PRs or Releases')
    tags = {key: git(lab.bare(key), 'tag', '--sort=v:refname').split() for key in NAMES}
    check(tags == {'swift-sdk': ['0.1.0', '0.1.1', '0.2.0'], 'sprig': ['0.1.1', '0.1.2', '0.1.3'],
                   'firebase': ['0.1.0']}, str(tags))
    lab.records['publicTags'] = tags
    lab.proved('two more Tag & Release Packages runs changed no ref, PR or Release; only the broken item is reported')


def step_9(lab):
    consumers = [lab.consumer(key, version) for key, version in
                 (('swift-sdk', '0.1.0'), ('sprig', '0.1.1'), ('firebase', '0.1.0'))]
    lab.records['consumers'] = consumers
    lab.proved('one package at a time, fresh SwiftPM state, offline mirrors: SDK 0.1.0, the pre-monorepo '
               'Sprig 0.1.1 tag and Firebase 0.1.0 resolve and run')
    if lab.ios:
        # Firebase 0.1.0 needs SDK 0.2.0; each check resolves on its own, like the post-publish customer check.
        lab.records['iosConsumer'] = [lab.ios_consumer(key, version) for key, version in
                                      (('swift-sdk', '0.2.0'), ('sprig', '0.1.1'), ('firebase', '0.1.0'))]
        lab.proved('the customer check package builds with xcodebuild on each supported platform (iOS Simulator, '
                   'macOS): SDK 0.2.0, Sprig 0.1.1, Firebase 0.1.0')


def step_10(lab):
    sdk = lab.bare('swift-sdk')
    public_main, others = git(sdk, 'rev-parse', 'main'), lab.refs('sprig', 'firebase')
    git(lab.runner, 'fetch', '--quiet', '--tags', 'origin')
    for key, version, message in (('swift-sdk', '0.1.0', 'not the latest 0.1 patch; use 0.1.1'),
                                  ('sprig', '0.1.9', 'main is still on 0.1.3')):
        try:
            create_maintenance_branch(key, version, lab.runner)
        except ValueError as error:
            check(message in str(error), str(error))
            continue
        raise AssertionError(f'{key} {version} maintenance branch was not refused')
    # Create Maintenance Branch (as the App bot): main is on SDK 0.2.0, customers are on 0.1.x.
    with patch.dict(os.environ, GIT_CONFIG_GLOBAL=str(lab.bot)):
        plan = create_maintenance_branch('swift-sdk', '0.1.1', lab.runner)
    branch = 'release/swift-sdk-0.1.x'
    check(plan['branch'] == branch and plan['from'] == git(lab.source, 'rev-parse', 'swift-sdk-0.1.1^{commit}'), str(plan))
    with tempfile.TemporaryDirectory(prefix='rehearsal-maintenance-') as temp:
        work = Path(temp) / 'work'
        run(['git', 'clone', '--quiet', '--branch', branch, f'https://github.com/{SOURCE}.git', work])
        config = load(work / 'release-please-config.json')
        check(config['packages'] == {'Packages/DemoSDK': {'component': 'swift-sdk', 'versioning': 'always-bump-patch'}},
              str(config['packages']))
        # A reviewed fix PR targeting the maintenance branch, then its Release Please PR (a patch, as configured).
        demo = work / 'Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift'
        check('apiLevel' not in demo.read_text(), 'the 0.2.0 feature reached the 0.1.x line')
        demo.write_text(demo.read_text().replace('public static func hasPrivacyManifest',
                                                 '/// Patched on the 0.1.x line.\n    public static func hasPrivacyManifest'))
        commit(work, 'fix(swift-sdk): patch the 0.1.x line')
        git(work, 'push', '--quiet', 'origin', f'HEAD:refs/heads/{branch}')
        sha = lab.release({'swift-sdk': '0.1.2'}, work=work, branch=branch)
    status = lab.recover()
    check(status == {'swift-sdk 0.1.2': 'awaiting_review', 'sprig 0.1.9': 'skipped incomplete'}, str(status))
    pr = next(p for p in lab.pulls('swift-sdk') if p['head']['ref'] == 'publication/swift-sdk/0.1.2')
    check(pr['base']['ref'] == 'release/0.1.x', f'publish PR base {pr["base"]["ref"]}')
    check(git(sdk, 'rev-parse', 'release/0.1.x') == git(sdk, 'rev-parse', '0.1.1^{commit}'),
          'public release/0.1.x does not start at tag 0.1.1')
    check(git(sdk, 'rev-parse', 'publication/swift-sdk/0.1.2^') == git(sdk, 'rev-parse', 'release/0.1.x'), 'PR parent')
    merged = lab.merge('swift-sdk', 'publication/swift-sdk/0.1.2')
    status = lab.recover()
    check(status == {'swift-sdk 0.1.2': 'published', 'sprig 0.1.9': 'skipped incomplete'}, str(status))
    check(git(sdk, 'rev-parse', '0.1.2^{commit}') == merged == git(sdk, 'rev-parse', 'release/0.1.x'),
          'tag is not the merge commit on release/0.1.x')
    check(json.loads(git(sdk, 'show', '0.1.2:.publication.json'))['sourceCommit'] == sha, 'provenance')
    check('apiLevel' not in git(sdk, 'show', '0.1.2:Sources/DemoSDK/DemoSDK.swift'), '0.2.0 code in 0.1.2')
    check(git(sdk, 'rev-parse', 'main') == public_main and lab.refs('sprig', 'firebase') == others,
          'the maintenance release changed public main or other packages')
    release = lab.releases('swift-sdk')[-1]
    check((release['tag_name'], release['make_latest']) == ('0.1.2', 'false'), str(release))
    check(lab.recover() == {'sprig 0.1.9': 'skipped incomplete'}, 'Tag & Release Packages is not idempotent')
    lab.records['maintenanceConsumer'] = lab.consumer('swift-sdk', '0.1.2')
    lab.proved('Create Maintenance Branch refused a non-latest patch and a line main has not left; it cut '
               'release/swift-sdk-0.1.x from tag swift-sdk-0.1.1 with an SDK-only, always-bump-patch config')
    lab.proved('SDK 0.1.2 (fix on release/swift-sdk-0.1.x, without the 0.2.0 feature): the bot created public '
               'release/0.1.x at tag 0.1.1, the publish PR targeted it, and Tag & Release Packages tagged its merge '
               'commit; public main and the other packages did not change; the Release is not "Latest"')


STEPS = [
    ('bootstrap a README-only public repository', step_1),
    ('take over a foreign public repository', step_2),
    ('release an integration: export, build, bot PR, merge, Tag & Release Packages tags it', step_3),
    ('an integration-only release leaves the SDK untouched, and vice versa', step_4),
    ('an integration waits for its SDK tag, then continues', step_5),
    ('a broken item is skipped while the others complete', step_6),
    ('drift in a public repository blocks publishing', step_7),
    ('Tag & Release Packages is idempotent', step_8),
    ('old tags still resolve for clean consumers', step_9),
    ('patch an older version line while main is ahead', step_10),
]


def rehearse(ios=False, base=None, quick=False, through=len(STEPS)):
    """Run steps 0..`through` in a new `<base>/<timestamp>/` folder (default `.lab`); earlier runs are never touched."""
    base = Path(base or ROOT / '.lab').resolve()
    directory = base / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True)
    write_json(base / 'latest.json', {'path': str(directory)})
    # The configured Git identity authors developer and reviewer commits; the modeled App bot authors publication.
    ident = git(ROOT, 'var', 'GIT_AUTHOR_IDENT')
    identity = (ident.split(' <')[0], ident.split(' <')[1].split('>')[0])
    lab = Lab(directory, quick)
    lab.ios = ios
    lab.records.update(through=through, tool=ROOT.as_posix(), toolCommit=git(ROOT, 'rev-parse', 'HEAD'),
                       swift=run(['swift', '--version']).splitlines()[0],
                       xcode=' '.join(run(['xcodebuild', '-version']).split()))
    started = time.monotonic()
    with lab.environment(identity):
        with lab.step(0, 'set up the fixture monorepo and local public repositories'):
            lab.setup()
            lab.proved('swift-sdk and firebase public repositories are README-only; sprig has foreign files, '
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
    parser.add_argument('--ios', action='store_true', help='also run the customer check package with xcodebuild (iOS Simulator, macOS)')
    parser.add_argument('--quick', action='store_true', help='skip the xcodebuild platform builds in the publisher')
    parser.add_argument('--through', type=int, choices=range(len(STEPS) + 1), default=len(STEPS),
                        help='stop after this step')
    args = parser.parse_args()
    try:
        rehearse(args.ios, quick=args.quick, through=args.through)
    except RehearsalError as error:
        raise SystemExit(f'Rehearsal failed: {error}')
