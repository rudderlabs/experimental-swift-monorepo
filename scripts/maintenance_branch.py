"""Maintenance lines: patch an older X.Y line of one package while main moves on.

The monorepo branch `release/<key>-X.Y.x` starts at the tag `<component>-X.Y.Z` of the line's latest patch. Its
Release Please config keeps only that package and always bumps the patch. The public base is `release/X.Y.x`.
"""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

from common import ROOT, RELEASE_BRANCH, commit, git, inventory
from project import SEMVER

BRANCH = re.compile(r'release/([a-z][a-z0-9-]*)-(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.x\Z')
FAILURES = (ValueError, RuntimeError, OSError, KeyError)


def line(version):
    return tuple(map(int, version.split('.')[:2]))


def semver(version):
    return tuple(map(int, version.split('.')))


def branch_name(key, version):
    return 'release/{}-{}.{}.x'.format(key, *line(version))


def public_base(source_branch, version):
    """The publication repository branch for a version: main, or `release/X.Y.x` for a maintenance line."""
    return RELEASE_BRANCH if source_branch == RELEASE_BRANCH else 'release/{}.{}.x'.format(*line(version))


def ancestor(root, sha, ref):
    try:
        git(root, 'merge-base', '--is-ancestor', sha, ref)
        return True
    except RuntimeError:
        return False


def source_line(root, key, sha, version):
    """`main` when the source commit is on origin/main, else its `release/<key>-X.Y.x` branch; refuse otherwise."""
    if ancestor(root, sha, f'origin/{RELEASE_BRANCH}'):
        return RELEASE_BRANCH
    branch = branch_name(key, version)
    if git(root, 'for-each-ref', '--format=%(refname)', f'refs/remotes/origin/{branch}') \
            and ancestor(root, sha, f'origin/{branch}'):
        return branch
    raise ValueError(f'Source commit is on neither {RELEASE_BRANCH} nor {branch}')


def publication_base(root, key, version):
    """The public base of a released version, from where its monorepo tag lives."""
    tag = f'{inventory(root)[key]["component"]}-{version}'
    return public_base(source_line(root, key, git(root, 'rev-parse', f'refs/tags/{tag}^{{commit}}'), version), version)


def target(ref, branch=''):
    """The Release Please target: the pushed branch, or `branch` when dispatched on main."""
    if branch and ref != RELEASE_BRANCH:
        raise ValueError(f'Dispatch with a branch input on {RELEASE_BRANCH} only')
    name = branch or ref
    if name != RELEASE_BRANCH:
        match = BRANCH.fullmatch(name)
        if not match or match[1] not in inventory():
            raise ValueError(f'Not {RELEASE_BRANCH} or a maintenance branch release/<key>-X.Y.x: {name}')
    return name


def maintenance_config(config, path):
    """Only the package at `path`, and a patch bump whatever the commit type (a feat cannot open X.Y+1.0)."""
    if path not in config.get('packages', {}):
        raise ValueError(f'release-please-config.json has no package {path}')
    return {**config, 'packages': {path: {**config['packages'][path], 'versioning': 'always-bump-patch'}}}


def create(key, version, root=ROOT, dry_run=False):
    """Push `release/<key>-X.Y.x` (the tag commit plus one config commit). Returns the plan."""
    packages = inventory(root)
    if key not in packages or not SEMVER.fullmatch(version):
        raise ValueError('Unknown package or version is not X.Y.Z')
    package = packages[key]
    tag, branch = f'{package["component"]}-{version}', branch_name(key, version)
    try:
        sha = git(root, 'rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}')
    except RuntimeError:
        raise ValueError(f'Monorepo tag {tag} is missing') from None
    prefix = re.compile(re.escape(package['component']) + r'-(.+)\Z')
    versions = [m[1] for t in git(root, 'tag', '--list').split() if (m := prefix.match(t)) and SEMVER.fullmatch(m[1])]
    latest = max((v for v in versions if line(v) == line(version)), key=semver)
    if latest != version:
        raise ValueError(f'{version} is not the latest {".".join(map(str, line(version)))} patch; use {latest}')
    main = json.loads(git(root, 'show', f'origin/{RELEASE_BRANCH}:.release-please-manifest.json'))[package['path']]
    if line(main) <= line(version):
        raise ValueError(f'{RELEASE_BRANCH} is still on {main}; release the fix from {RELEASE_BRANCH}')
    if git(root, 'ls-remote', '--heads', 'origin', f'refs/heads/{branch}'):
        raise ValueError(f'Branch {branch} already exists')
    config = maintenance_config(json.loads(git(root, 'show', f'{sha}:release-please-config.json')), package['path'])
    message = 'chore({}): start {}.{}.x maintenance line'.format(key, *line(version))
    plan = {'branch': branch, 'tag': tag, 'from': sha, 'message': message, 'dryRun': dry_run}
    if dry_run:
        return plan
    with tempfile.TemporaryDirectory(prefix='maintenance-') as temp:
        work = Path(temp) / 'branch'
        git(root, 'worktree', 'add', '--quiet', '--detach', work, sha)
        try:
            (work / 'release-please-config.json').write_text(json.dumps(config, indent=2) + '\n')
            plan['commit'] = commit(work, message)
            # A new ref only: an existing branch of that name rejects the push.
            git(work, 'push', '--quiet', 'origin', f'HEAD:refs/heads/{branch}')
        finally:
            git(root, 'worktree', 'remove', '--force', work)
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('create', help='create release/<key>-X.Y.x from the monorepo tag <component>-X.Y.Z')
    start.add_argument('package')
    start.add_argument('version', help='the existing release to branch from (latest patch of its X.Y line)')
    start.add_argument('--dry-run', action='store_true')
    resolve = commands.add_parser('target', help='validate the Release Please target branch')
    resolve.add_argument('--ref', required=True)
    resolve.add_argument('--branch', default='')
    args = parser.parse_args()
    try:
        result = create(args.package, args.version, dry_run=args.dry_run) if args.command == 'create' \
            else {'branch': target(args.ref, args.branch)}
    except FAILURES as error:
        raise SystemExit(f'::error::{error}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('branch=' + result['branch'] + '\n')
    print(json.dumps(result, indent=2))
