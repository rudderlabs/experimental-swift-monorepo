"""Publish through reviewed GitHub PRs. Never write the publication main branch."""
import json
import re
import shutil

from common import OWNER, RELEASE_BRANCH, allowlist, commit, git, load, run

BOT = 'rudderstack-github-actions[bot]'


def branch_for(key, version):
    return f'publication/{key}/{version}'


def repository_for(key):
    return f'{OWNER}/{allowlist()[key]}'


def api(endpoint):
    return json.loads(run(['gh', 'api', endpoint]))


def find_pr(key, version):
    branch = branch_for(key, version)
    repository = repository_for(key)
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                           f'repos/{repository}/pulls?state=all&head={OWNER}:{branch}&base=main&per_page=100']))
    prs = [p for page in pages for p in page]
    if len(prs) > 1:
        raise ValueError('Multiple publication PRs match the version')
    return api(f'repos/{repository}/pulls/{prs[0]["number"]}') if prs else None


def validate_pr(pr, key, version):
    repository = repository_for(key)
    if (pr['base']['ref'] != RELEASE_BRANCH
            or pr['base']['repo']['full_name'] != repository
            or pr['head']['ref'] != branch_for(key, version)
            or (pr['head']['repo'] or {}).get('full_name') != repository
            or pr['user']['login'] != BOT):
        raise ValueError('Publication PR identity or destination differs')


def reviewed_commit(key, version, repo, stage, expected, verify_tree):
    """Return pending evidence or the exact verified merge commit to tag."""
    branch = branch_for(key, version)
    pr = find_pr(key, version)
    if pr:
        validate_pr(pr, key, version)
        if pr['state'] == 'closed' and not pr['merged']:
            raise ValueError('Publication PR was closed without merging; review required')
        sha = pr['merge_commit_sha'] if pr['merged'] else pr['head']['sha']
        if not re.fullmatch('[0-9a-f]{40}', sha or ''):
            raise ValueError('Publication PR commit is missing')
        git(repo, 'fetch', '--no-tags', 'origin', sha)
        git(repo, 'checkout', '--detach', sha)
        if verify_tree(repo) != expected:
            raise ValueError('Publication PR differs from the approved export')
        if pr['merged']:
            git(repo, 'merge-base', '--is-ancestor', sha, 'origin/main')
            return sha, pr
        return None, pr

    # A prior branch push can exist after an interrupted PR creation. Reuse it.
    remote_ref = f'refs/remotes/origin/{branch}'
    if git(repo, 'for-each-ref', '--format=%(refname)', remote_ref):
        git(repo, 'checkout', '--detach', remote_ref)
        if verify_tree(repo) != expected:
            raise ValueError('Publication branch conflicts with the approved export')
    else:
        git(repo, 'checkout', '-b', branch, 'origin/main')
        previous = load(repo / '.publication.json')
        if tuple(map(int, previous['version'].split('.'))) >= tuple(map(int, version.split('.'))):
            raise ValueError('New publication version must increase')
        for child in repo.iterdir():
            if child.name == '.git':
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(stage, repo, dirs_exist_ok=True)
        commit(repo, f'chore: sdk-5388 publish experimental {key} {version}')
        git(repo, 'push', 'origin', f'HEAD:refs/heads/{branch}')
    notes = repo.parent / 'publication-pr.md'
    notes.write_text(f'Publish experimental {key} {version} from source commit `{expected["sourceCommit"]}`.\n\n'
                     'The generated package passed an anonymous Swift build. Review the complete export and provenance. '
                     'After merge, the central publication workflow verifies the exact merge commit, creates the immutable '
                     'SwiftPM version tag, and creates the GitHub Release. An open PR does not publish a version.\n\n'
                     '[SDK-5388](https://linear.app/rudderstack/issue/SDK-5388)\n')
    run(['gh', 'pr', 'create', '--repo', repository_for(key), '--base', RELEASE_BRANCH,
         '--head', branch, '--title', f'chore: publish experimental {key} {version}', '--body-file', notes])
    pr = find_pr(key, version)
    if not pr:
        raise ValueError('Created publication PR cannot be verified')
    validate_pr(pr, key, version)
    if pr['head']['sha'] != git(repo, 'rev-parse', 'HEAD'):
        raise ValueError('Created publication PR head differs')
    return None, pr
