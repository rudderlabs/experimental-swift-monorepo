"""Abandon Unpublished Version: discard a version without a public tag, so Release Please releases its number again.

`public`: guards, then the version's publication PRs get the bot's discard marker (an open one is closed; a merged
one is first reverted by a reviewed bot PR, which needs a second run) and its public branches are deleted.
`rollback`: on the version's source line (main or release/<key>-X.Y.x), a bot PR reverts the release commit, the
old release PR gets a commit override that keeps it out of the next changelog, and the monorepo Release and tag
`<component>-X.Y.Z` are deleted last. Every step checks first, so a re-run continues where one stopped.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

from common import ROOT, OWNER, SOURCE_NAME, allowlist, git, inventory, run, text, url
from maintenance_branch import public_base, source_line
from project import SEMVER
from reviewed_publication import (ABANDON, BOT, ROLL_FORWARD, abandon, branch_for, delete_branch, find_pr,
                                  mark_discarded, validate_pr)

MONOREPO = f'{OWNER}/{SOURCE_NAME}'
OVERRIDE = 'BEGIN_COMMIT_OVERRIDE'
FAILURES = (ValueError, RuntimeError, OSError, KeyError)


def discard_branch(key, version):
    return f'discard/{key}/{version}'


def discard_prs(key, version):
    """The bot's monorepo rollback PRs of the version, oldest first."""
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp', f'repos/{MONOREPO}/pulls?state=all'
                            f'&head={OWNER}:{discard_branch(key, version)}&per_page=100']))
    return sorted((p for page in pages for p in page if p['user']['login'] == BOT), key=lambda p: p['number'])


def check(key, version, root=ROOT):
    """The guards, before any change. None when the version is already discarded, else the plan."""
    package = inventory(root)[key]
    component, path = package['component'], package['path']
    tag = f'{component}-{version}'
    if run(['git', 'ls-remote', '--tags', url(key, root), f'refs/tags/{version}']):
        raise ValueError(ROLL_FORWARD.format(version=version))
    prs = discard_prs(key, version)
    try:
        sha = git(root, 'rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}')
    except RuntimeError:
        # The tag is deleted last: without it, an open or merged rollback PR means the run finished.
        if any(p['state'] == 'open' or p['merged_at'] for p in prs):
            return None
        raise ValueError(f'No monorepo tag {tag}; nothing to discard') from None
    # A reused number can be discarded again: only a rollback of this release commit counts.
    prs = [p for p in prs if sha in (p['body'] or '')]
    closed = [p for p in prs if p['state'] == 'closed' and not p['merged_at']]
    if closed:
        raise ValueError(f'Rollback PR #{closed[0]["number"]} was closed without merging; reopen it and run again')
    branch = source_line(root, key, sha, version)
    if not prs:
        released = json.loads(git(root, 'show', f'origin/{branch}:.release-please-manifest.json')).get(path)
        if released != version:
            raise ValueError(f'{version} is not the latest released {key} on {branch} '
                             f'(manifest says {released}); fix forward')
    # The rollback reverts the whole release commit, so it may hold only Release Please's own files.
    config = json.loads(git(root, 'show', f'{sha}:release-please-config.json'))['packages'][path]
    allowed = {'.release-please-manifest.json', f'{path}/CHANGELOG.md', f'{path}/version.txt'}
    allowed |= {f'{path}/{f if isinstance(f, str) else f["path"]}' for f in config.get('extra-files', [])}
    other = sorted(set(git(root, 'diff', '--name-only', f'{sha}^', sha).splitlines()) - allowed)
    if other:
        raise ValueError(f'The release commit of {tag} also changes {", ".join(other)}; fix forward')
    return {'tag': tag, 'sha': sha, 'component': component, 'branch': branch, 'base': public_base(branch, version),
            'rollback': prs[0] if prs else None}


def discard_public(key, version, repo, base, run_url, verify_tree):
    """Mark the version's publication PRs discarded. Returns (status, revert PR) while a revert must merge first."""
    pr = find_pr(key, version)
    if pr:
        validate_pr(pr, key, version, base=base)
        if pr['merged']:
            # Opens the bot revert PR, or reports it; merging it returns the public base to the last release.
            status, revert = abandon(key, version, repo, verify_tree, base)
            if status != 'abandoned':
                return status, revert
        mark_discarded(pr, run_url)
    # After its publication PR: an interrupted run never opens a second revert PR.
    revert = find_pr(key, version, ABANDON)
    if revert and revert['merged']:
        validate_pr(revert, key, version, ABANDON, base)
        mark_discarded(revert, run_url)
    for mode in ('normal', ABANDON):
        delete_branch(repo, branch_for(key, version, mode))
    return None


def rollback(key, version, plan, root=ROOT, run_url=''):
    """The monorepo side. Returns the rollback PR number."""
    tag, sha, branch, component = plan['tag'], plan['sha'], plan['branch'], plan['component']
    pr = plan['rollback']
    if not pr:
        head = discard_branch(key, version)
        message = text('discardCommit', key=key, component=component, version=version, sha=sha)
        with tempfile.TemporaryDirectory(prefix='discard-') as temp:
            work = Path(temp) / 'line'
            git(root, 'worktree', 'add', '--quiet', '--detach', work, f'origin/{branch}')
            try:
                # Squash merges have one parent; a merge commit reverts against its first parent.
                parents = git(root, 'rev-list', '--parents', '-n', '1', sha).split()[1:]
                git(work, 'revert', '--no-commit', *(['-m', '1'] if len(parents) > 1 else []), sha)
                git(work, 'commit', '--quiet', '-m', message)
                # No PR reverts this commit yet: the branch is an interrupted push or an earlier discard's.
                git(work, 'push', '--quiet', 'origin', f'+HEAD:refs/heads/{head}')
            finally:
                git(root, 'worktree', 'remove', '--force', work)
        run(['gh', 'pr', 'create', '--repo', MONOREPO, '--base', branch, '--head', head,
             '--title', message.splitlines()[0],
             '--body', text('discardPullRequestBody', component=component, version=version, sha=sha, run=run_url)])
        pr = next((p for p in discard_prs(key, version) if sha in (p['body'] or '')), None)
        if not pr:
            raise ValueError('Created rollback PR cannot be verified')
    # Release Please reads the old release commit through this override: the next changelog skips it.
    release = [p for p in json.loads(run(['gh', 'api', f'repos/{MONOREPO}/commits/{sha}/pulls']))
               if p.get('merge_commit_sha') == sha]
    if len(release) != 1:
        raise ValueError(f'No single release PR merged as {sha}')
    body = release[0]['body'] or ''
    if OVERRIDE not in body:
        # Its `autorelease: tagged` label stays: a pending label would make Release Please recreate the Release.
        override = text('discardOverride', key=key, component=component, version=version)
        run(['gh', 'api', '-X', 'PATCH', f'repos/{MONOREPO}/pulls/{release[0]["number"]}',
             '-f', f'body={body.rstrip()}\n\n{override}\n'])
    # Last, so a re-run still finds the tag for the steps above.
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp', f'repos/{MONOREPO}/releases?per_page=100']))
    if any(r['tag_name'] == tag for page in pages for r in page):
        run(['gh', 'release', 'delete', tag, '--repo', MONOREPO, '--cleanup-tag', '--yes'])
    elif git(root, 'ls-remote', '--tags', 'origin', f'refs/tags/{tag}'):
        git(root, 'push', '--quiet', 'origin', f':refs/tags/{tag}')
    return pr['number']


if __name__ == '__main__':
    from publish import verify_tree
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('step', choices=('public', 'rollback'))
    parser.add_argument('package', choices=list(allowlist()))
    parser.add_argument('version')
    args = parser.parse_args()
    if not SEMVER.fullmatch(args.version):
        raise SystemExit('::error::Version must be X.Y.Z')
    env = os.environ
    run_url = f'{env.get("GITHUB_SERVER_URL")}/{env.get("GITHUB_REPOSITORY")}/actions/runs/{env.get("GITHUB_RUN_ID")}'
    outputs, name = {'proceed': 'false'}, f'{args.package} {args.version}'
    try:
        plan = check(args.package, args.version)
        if plan is None:
            print(f'::notice::{name} is already discarded; nothing to do.')
        elif args.step == 'public':
            with tempfile.TemporaryDirectory(prefix='discard-') as temp:
                clone = Path(temp) / 'publication'
                run(['git', 'clone', '--quiet', '--no-checkout', url(args.package), clone])
                waiting = discard_public(args.package, args.version, clone, plan['base'], run_url, verify_tree)
            if waiting:
                print(f'::notice::{name} is {waiting[0]}: merge revert PR #{waiting[1]["number"]} '
                      f'({waiting[1]["html_url"]}), then run this workflow again.')
            else:
                outputs = {'proceed': 'true', 'branch': plan['branch']}
        else:
            number = rollback(args.package, args.version, plan, run_url=run_url)
            print(f'::notice::{name} discarded; merge rollback PR #{number} next.')
    except FAILURES as error:
        raise SystemExit(f'::error::{error}')
    if env.get('GITHUB_OUTPUT'):
        with open(env['GITHUB_OUTPUT'], 'a') as output:
            output.writelines(f'{k}={v}\n' for k, v in outputs.items())
