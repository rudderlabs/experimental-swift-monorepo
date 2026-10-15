"""Publish through reviewed GitHub PRs. Never write a publication base branch (main or release/X.Y.x)."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from common import OWNER, RELEASE_BRANCH, allowlist, anonymous_env, commit, git, load, run, swift_options, text
import release_notes

BOT = 'rudderstack-github-actions[bot]'
BOT_EMAIL = re.compile(r'[1-9][0-9]*\+' + re.escape(BOT) + r'@users\.noreply\.github\.com\Z')
MODES = ('normal', 'takeover', 'bootstrap')
README_ONLY = re.compile(r'(?:README|LICENSE)[^/]*\Z|\.gitignore\Z', re.I)
WORKFLOWS = 'Remove .github/workflows by PR first'
ABANDON = 'abandon'  # the revert PR branch prefix
DISCARDED = '<!-- discarded -->'  # the bot's comment marker: a discarded version's PR is history
ROLL_FORWARD = '{version} is already public and is never discarded; roll forward with a new release instead'


class Abandoned(ValueError):
    """The version was discarded before its tag; nothing is published for it."""


def branch_for(key, version, mode='normal'):
    prefix = mode if mode in ('takeover', ABANDON) else 'publication'
    return f'{prefix}/{key}/{version}'


def repository_for(key):
    return f'{OWNER}/{allowlist()[key]}'


def api(endpoint):
    return json.loads(run(['gh', 'api', endpoint]))


def layout(repo):
    """`generated` (has provenance), `readme-only` (README, maybe LICENSE and .gitignore) or `foreign`."""
    if (repo / '.publication.json').exists():
        return 'generated'
    files = git(repo, 'ls-files').splitlines()
    readme = any(f.upper().startswith('README') for f in files)
    return 'readme-only' if readme and all(README_ONLY.match(f) for f in files) else 'foreign'


def find_prs(key, version, mode='normal'):
    """Every PR of the version branch, discarded ones included, oldest first."""
    branch = branch_for(key, version, mode)
    repository = repository_for(key)
    # Any base: validate_pr checks the base.
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                           f'repos/{repository}/pulls?state=all&head={OWNER}:{branch}&per_page=100']))
    return [api(f'repos/{repository}/pulls/{n}') for n in sorted(p['number'] for page in pages for p in page)]


def find_pr(key, version, mode='normal'):
    """The version's live PR or None. A discarded PR is history: a reused version number opens a new one."""
    prs = [p for p in find_prs(key, version, mode) if not discarded(p)]
    if len(prs) > 1:
        raise ValueError('Multiple publication PRs match the version')
    return prs[0] if prs else None


def marked(pr):
    """The bot commented the discard marker on its own PR."""
    if pr['user']['login'] != BOT:
        return False
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                           f'repos/{pr["base"]["repo"]["full_name"]}/issues/{pr["number"]}/comments?per_page=100']))
    return any(c['user']['login'] == BOT and DISCARDED in (c['body'] or '') for page in pages for c in page)


def discarded(pr):
    return pr['state'] == 'closed' and marked(pr)


def mark_discarded(pr, run_url):
    """Comment the marker once, then close the PR if it is open."""
    repository, number = pr['base']['repo']['full_name'], str(pr['number'])
    if not marked(pr):
        run(['gh', 'pr', 'comment', number, '--repo', repository, '--body', text('discardedComment', run=run_url)])
    if pr['state'] == 'open':
        run(['gh', 'pr', 'close', number, '--repo', repository])


def delete_branch(repo, branch):
    """Delete a public PR branch: reviewed_commit and abandon reuse a pushed branch of the same name."""
    if git(repo, 'ls-remote', '--heads', 'origin', f'refs/heads/{branch}'):
        git(repo, 'push', 'origin', f':refs/heads/{branch}')


def validate_pr(pr, key, version, mode='normal', base=RELEASE_BRANCH):
    repository = repository_for(key)
    if (pr['base']['ref'] != base
            or pr['base']['repo']['full_name'] != repository
            or pr['head']['ref'] != branch_for(key, version, mode)
            or (pr['head']['repo'] or {}).get('full_name') != repository
            or pr['user']['login'] != BOT):
        raise ValueError('Publication PR identity or destination differs')


def abandon_state(key, version, pr, base=RELEASE_BRANCH):
    """Derived from GitHub only: `abandoned`, `abandoning` (revert PR open) or None (publishable).

    A closed unmerged PR is abandoned only with the bot's discard marker (a person's close still needs review);
    a merged one once its bot revert PR is merged.
    """
    if not pr or pr['state'] != 'closed':
        return None
    validate_pr(pr, key, version, base=base)
    if not pr['merged']:
        return 'abandoned' if discarded(pr) else None
    revert = find_pr(key, version, ABANDON)
    if not revert:
        return None
    validate_pr(revert, key, version, ABANDON, base)
    # A revert PR closed without merging cancels the request.
    return 'abandoned' if revert['merged'] else 'abandoning' if revert['state'] == 'open' else None


def check_identity(repo):
    """Bot commits carry the App's identity, so the commit author matches the PR author."""
    if (git(repo, 'config', 'user.name') != BOT
            or not BOT_EMAIL.fullmatch(git(repo, 'config', 'user.email'))):
        raise ValueError(f'Publication commits need the {BOT} identity')


def verify_merged(repo, key, version, source, verify_tree):
    """A merged version is checked against its own stored provenance, never a re-export (D25)."""
    provenance = verify_tree(repo)
    if (provenance.get('package'), provenance.get('version'), provenance.get('sourceCommit')) != (key, version, source):
        raise ValueError('Merged publication differs from the approved release')
    return provenance


def tree(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob('*')) if p.is_file()}


def manifest_summary(path):
    """Consumer-visible shape; formatting, test targets and the experimental SDK URL do not count."""
    # SwiftPM state stays outside the tree, so nothing enters the publication PR.
    with tempfile.TemporaryDirectory(prefix='dump-package-') as state:
        data = json.loads(run(['swift', 'package', *swift_options(Path(state)), 'dump-package'],
                              cwd=path, env=anonymous_env()))
    def location(spec):
        remote = (spec.get('location') or {}).get('remote') or [spec.get('path', '')]
        value = remote[0]['urlString'] if isinstance(remote[0], dict) else str(remote[0])
        return re.sub(r'github\.com/rudderlabs/experimental-', 'github.com/rudderlabs/', value.lower()).removesuffix('.git')
    names = lambda deps: sorted(next(iter(d.values()))[0] for d in deps)
    return {'products': sorted([p['name'], p['type'], sorted(p['targets'])] for p in data['products']),
            'targets': sorted([t['name'], t['type'], names(t['dependencies']),
                               sorted([r['path'], r['rule']] for r in t.get('resources') or [])]
                              for t in data['targets'] if t['type'] != 'test'),
            'platforms': sorted([p['platformName'], p['version']] for p in data['platforms']),
            'dependencies': sorted([location(s), s.get('requirement')]
                                   for d in data['dependencies'] for specs in d.values() for s in specs)}


def takeover_check(baseline, stage, target):
    """Sources/ byte-identical to the baseline tag (only a missing Version.swift may be added); Package.swift semantic."""
    old = tree(baseline / 'Sources') if (baseline / 'Sources').is_dir() else {}
    new = tree(stage / 'Sources')
    added = set(new) - set(old) - {f'{target}/Version.swift'}
    changed = sorted(added | {p for p in old if new.get(p) != old[p]})
    if changed:
        raise ValueError('Takeover Sources/ differ from the baseline tag: ' + ', '.join(changed[:20]))
    before, after = manifest_summary(baseline), manifest_summary(stage)
    differences = [k for k in after if before[k] != after[k]]
    if differences:
        raise ValueError('Takeover Package.swift differs semantically: ' + ', '.join(differences))


def reviewed_commit(key, version, source, repo, stage, prepare, verify_tree, mode='normal', package=None,
                    base=RELEASE_BRANCH):
    """Return pending evidence or the exact verified merge commit. `prepare(full)` exports into `stage`.

    `package` (the inventory entry) supplies the display title and platforms of the PR text. `base` is the
    publication branch the PR targets: main, or `release/X.Y.x` for a maintenance line.
    """
    branch = branch_for(key, version, mode)
    pr = find_pr(key, version, mode)
    if pr:
        validate_pr(pr, key, version, mode, base)
        # Before the merged path: a reverted merge is still an ancestor of the base and must never be tagged.
        status = abandon_state(key, version, pr, base) if mode != 'takeover' else None
        if status:
            raise Abandoned(f'{version} is {status}; it is never tagged')
        if pr['state'] == 'closed' and not pr['merged']:
            raise ValueError('Publication PR was closed without merging; review required '
                             '(run Abandon Unpublished Version to discard the version)')
        sha = pr['merge_commit_sha'] if pr['merged'] else pr['head']['sha']
        if not re.fullmatch('[0-9a-f]{40}', sha or ''):
            raise ValueError('Publication PR commit is missing')
        git(repo, 'fetch', '--no-tags', 'origin', sha)
        git(repo, 'checkout', '--detach', sha)
        if pr['merged']:
            verify_merged(repo, key, version, source, verify_tree)
            git(repo, 'merge-base', '--is-ancestor', sha, f'origin/{base}')
            return sha, pr
        # An open PR still equals the export. Its build passed before the PR was opened.
        if verify_tree(repo) != prepare(False):
            raise ValueError('Publication PR differs from the approved export')
        return None, pr

    # A prior branch push can exist after an interrupted PR creation. Reuse it.
    remote_ref = f'refs/remotes/origin/{branch}'
    if git(repo, 'for-each-ref', '--format=%(refname)', remote_ref):
        git(repo, 'checkout', '--detach', remote_ref)
        if verify_tree(repo) != prepare(False):
            raise ValueError('Publication branch conflicts with the approved export')
    else:
        check_identity(repo)
        prepare(True)
        git(repo, 'checkout', '-b', branch, f'origin/{base}')
        if (repo / '.publication.json').exists():
            previous = load(repo / '.publication.json')
            if tuple(map(int, previous['version'].split('.'))) >= tuple(map(int, version.split('.'))):
                raise ValueError('New publication version must increase')
        elif mode == 'normal':
            raise ValueError('Publication main has no provenance; use takeover or bootstrap')
        # Every non-generated file goes; the bot never writes .github/workflows (D31).
        for child in repo.iterdir():
            if child.name == '.git':
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(stage, repo, dirs_exist_ok=True)
        commit(repo, text('takeoverCommit' if mode == 'takeover' else 'commit', version=version))
        git(repo, 'push', 'origin', f'HEAD:refs/heads/{branch}')
    removed = git(repo, 'diff', '--name-only', '--diff-filter=D', f'origin/{base}', 'HEAD').splitlines()
    notes = repo.parent / 'publication-pr.md'
    changelog = (repo / 'CHANGELOG.md').read_text() if (repo / 'CHANGELOG.md').is_file() else ''
    notes.write_text(text({'takeover': 'takeoverPullRequestBody', 'bootstrap': 'bootstrapPullRequestBody'}
                          .get(mode, 'pullRequestBody'), version=version, source=source,
                          title=release_notes.display_name(key, package),
                          notes=release_notes.notes(key, package, version, changelog),
                          platforms=', '.join((package or {}).get('platforms', [])) or 'the package defaults',
                          removed=text('removedFiles', files='\n'.join(f'- `{f}`' for f in removed)) if removed else ''))
    title = text('takeoverPullRequestTitle' if mode == 'takeover' else 'pullRequestTitle', version=version)
    run(['gh', 'pr', 'create', '--repo', repository_for(key), '--base', base,
         '--head', branch, '--title', title, '--body-file', notes])
    pr = find_pr(key, version, mode)
    if not pr:
        raise ValueError('Created publication PR cannot be verified')
    validate_pr(pr, key, version, mode, base)
    if pr['head']['sha'] != git(repo, 'rev-parse', 'HEAD'):
        raise ValueError('Created publication PR head differs')
    return None, pr


def abandon(key, version, repo, verify_tree, base=RELEASE_BRANCH):
    """Discard a merged, untagged version: a bot revert PR returns `base` to the last published record.

    `repo` is a clone of the publication repository; `base` is the version's publication branch (main or
    `release/X.Y.x`). Returns (status, PR). A tagged version is refused.
    """
    if git(repo, 'for-each-ref', '--format=%(refname)', f'refs/tags/{version}'):
        raise ValueError(ROLL_FORWARD.format(version=version))
    pr = find_pr(key, version)
    if not pr:
        raise ValueError('No publication PR for this version; nothing to abandon')
    status = abandon_state(key, version, pr, base)
    if status:
        return status, find_pr(key, version, ABANDON) or pr
    if not pr['merged']:
        raise ValueError('Publication PR is not merged; nothing to revert')
    branch = branch_for(key, version, ABANDON)
    if find_pr(key, version, ABANDON):
        raise ValueError(f'Abandon PR was closed without merging; delete branch {branch} to request it again')
    remote_ref = f'refs/remotes/origin/{branch}'
    pushed = bool(git(repo, 'for-each-ref', '--format=%(refname)', remote_ref))
    if pushed:
        # A prior push can exist after an interrupted PR creation. Reuse it.
        git(repo, 'checkout', '--detach', remote_ref)
    else:
        check_identity(repo)
        sha = pr['merge_commit_sha']
        if not re.fullmatch('[0-9a-f]{40}', sha or ''):
            raise ValueError('Publication PR commit is missing')
        git(repo, 'fetch', '--no-tags', 'origin', sha)
        git(repo, 'merge-base', '--is-ancestor', sha, f'origin/{base}')
        git(repo, 'checkout', '-b', branch, f'origin/{base}')
        # Squash and rebase merges have one parent; a merge commit reverts against its first parent.
        parents = git(repo, 'rev-list', '--parents', '-n', '1', sha).split()[1:]
        git(repo, 'revert', '--no-edit', *(['-m', '1'] if len(parents) > 1 else []), sha)
    # The base returns to an earlier verified record, so the next version's drift check and base stay correct.
    if (repo / '.publication.json').exists():
        previous = verify_tree(repo)
        if tuple(map(int, previous['version'].split('.'))) >= tuple(map(int, version.split('.'))):
            raise ValueError('Revert does not restore an earlier publication')
    if not pushed:
        git(repo, 'push', 'origin', f'HEAD:refs/heads/{branch}')
    # The title and body are the revert commit's own message.
    run(['gh', 'pr', 'create', '--repo', repository_for(key), '--base', base, '--head', branch,
         '--title', git(repo, 'log', '-1', '--format=%s'), '--body', git(repo, 'log', '-1', '--format=%b')])
    revert = find_pr(key, version, ABANDON)
    if not revert:
        raise ValueError('Created abandon PR cannot be verified')
    validate_pr(revert, key, version, ABANDON, base)
    if revert['head']['sha'] != git(repo, 'rev-parse', 'HEAD'):
        raise ValueError('Created abandon PR head differs')
    return 'awaiting_review', revert
