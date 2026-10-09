"""Publish through reviewed GitHub PRs. Never write the publication main branch."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from common import OWNER, RELEASE_BRANCH, allowlist, anonymous_env, commit, git, load, run, swift_options, text

BOT = 'rudderstack-github-actions[bot]'
BOT_EMAIL = re.compile(r'[1-9][0-9]*\+' + re.escape(BOT) + r'@users\.noreply\.github\.com\Z')
MODES = ('normal', 'takeover', 'bootstrap')
README_ONLY = re.compile(r'(?:README|LICENSE)[^/]*\Z|\.gitignore\Z', re.I)
WORKFLOWS = 'Remove .github/workflows by PR first'


def branch_for(key, version, mode='normal'):
    return f'{"takeover" if mode == "takeover" else "publication"}/{key}/{version}'


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


def find_pr(key, version, mode='normal'):
    branch = branch_for(key, version, mode)
    repository = repository_for(key)
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                           f'repos/{repository}/pulls?state=all&head={OWNER}:{branch}&base=main&per_page=100']))
    prs = [p for page in pages for p in page]
    if len(prs) > 1:
        raise ValueError('Multiple publication PRs match the version')
    return api(f'repos/{repository}/pulls/{prs[0]["number"]}') if prs else None


def validate_pr(pr, key, version, mode='normal'):
    repository = repository_for(key)
    if (pr['base']['ref'] != RELEASE_BRANCH
            or pr['base']['repo']['full_name'] != repository
            or pr['head']['ref'] != branch_for(key, version, mode)
            or (pr['head']['repo'] or {}).get('full_name') != repository
            or pr['user']['login'] != BOT):
        raise ValueError('Publication PR identity or destination differs')


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


def reviewed_commit(key, version, source, repo, stage, prepare, verify_tree, mode='normal'):
    """Return pending evidence or the exact verified merge commit. `prepare(full)` exports into `stage`."""
    branch = branch_for(key, version, mode)
    pr = find_pr(key, version, mode)
    if pr:
        validate_pr(pr, key, version, mode)
        if pr['state'] == 'closed' and not pr['merged']:
            raise ValueError('Publication PR was closed without merging; review required')
        sha = pr['merge_commit_sha'] if pr['merged'] else pr['head']['sha']
        if not re.fullmatch('[0-9a-f]{40}', sha or ''):
            raise ValueError('Publication PR commit is missing')
        git(repo, 'fetch', '--no-tags', 'origin', sha)
        git(repo, 'checkout', '--detach', sha)
        if pr['merged']:
            verify_merged(repo, key, version, source, verify_tree)
            git(repo, 'merge-base', '--is-ancestor', sha, 'origin/main')
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
        git(repo, 'checkout', '-b', branch, 'origin/main')
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
        commit(repo, text('takeoverCommit' if mode == 'takeover' else 'commit', package=key, version=version))
        git(repo, 'push', 'origin', f'HEAD:refs/heads/{branch}')
    removed = git(repo, 'diff', '--name-only', '--diff-filter=D', 'origin/main', 'HEAD').splitlines()
    notes = repo.parent / 'publication-pr.md'
    notes.write_text(text({'takeover': 'takeoverPullRequestBody', 'bootstrap': 'bootstrapPullRequestBody'}
                          .get(mode, 'pullRequestBody'), package=key, version=version, source=source,
                          removed=text('removedFiles', files='\n'.join(f'- `{f}`' for f in removed)) if removed else ''))
    title = text('takeoverPullRequestTitle' if mode == 'takeover' else 'pullRequestTitle', package=key, version=version)
    run(['gh', 'pr', 'create', '--repo', repository_for(key), '--base', RELEASE_BRANCH,
         '--head', branch, '--title', title, '--body-file', notes])
    pr = find_pr(key, version, mode)
    if not pr:
        raise ValueError('Created publication PR cannot be verified')
    validate_pr(pr, key, version, mode)
    if pr['head']['sha'] != git(repo, 'rev-parse', 'HEAD'):
        raise ValueError('Created publication PR head differs')
    return None, pr
