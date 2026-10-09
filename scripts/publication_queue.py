"""Recover pending publication from durable source component releases."""
import json
import os
from pathlib import Path
import tempfile

from common import ROOT, OWNER, SOURCE_NAME, git, inventory, run, text, url
from project import SEMVER
from publish import verify_tree
from reviewed_publication import find_pr

FAILURES = (ValueError, RuntimeError, OSError, KeyError)


def state(repo, key, version, sha, public_releases):
    """None when the version is complete, otherwise its pending state."""
    if git(repo, 'for-each-ref', '--format=%(refname)', f'refs/tags/{version}'):
        git(repo, 'checkout', '--detach', f'refs/tags/{version}')
        provenance = verify_tree(repo)
        if provenance['sourceCommit'] != sha or provenance['package'] != key or provenance['version'] != version:
            raise ValueError('Published tag conflicts with source release intent')
        publication_sha = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'merge-base', '--is-ancestor', publication_sha, 'origin/main')
        body = text('releaseBody', source=sha, publication=publication_sha)
        matches = [r for r in public_releases if r['tag_name'] == version]
        if matches:
            if len(matches) != 1 or matches[0]['draft'] or matches[0]['body'] != body:
                raise ValueError('Existing public Release metadata conflicts')
            return None
        return 'pending'
    # An open bot PR waits for review; Recover never rebuilds it.
    pr = find_pr(key, version)
    return 'awaiting_review' if pr and pr['state'] == 'open' else 'pending'


def queue(root=ROOT):
    """Pending intents and skipped items. One broken item is reported and never stops the others."""
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                           f'repos/{OWNER}/{SOURCE_NAME}/releases?per_page=100']))
    pending, skipped = [], []
    packages = inventory(root)
    # SDK work precedes integration work.
    for key in sorted(packages, key=lambda k: k != 'sdk'):
        prefix = packages[key]['component'] + '-'
        intents = []
        for release in (r for page in pages for r in page):
            tag = release['tag_name']
            if release['draft'] or release['prerelease'] or not tag.startswith(prefix):
                continue
            version = tag.removeprefix(prefix)
            try:
                if not SEMVER.fullmatch(version):
                    raise ValueError('Malformed experimental component release')
                sha = git(root, 'rev-parse', f'refs/tags/{tag}^{{commit}}')
                git(root, 'merge-base', '--is-ancestor', sha, 'origin/main')
                intents.append({'package': key, 'version': version, 'source_sha': sha})
            except FAILURES as error:
                skipped.append({'package': key, 'version': version, 'status': 'incomplete', 'error': str(error)})
        if not intents:
            continue
        with tempfile.TemporaryDirectory(prefix='publication-queue-') as temp:
            repo = Path(temp) / 'publication'
            try:
                run(['git', 'clone', '--no-checkout', url(key, root), repo])
                releases = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                                          f'repos/{OWNER}/{packages[key]["repository"]}/releases?per_page=100']))
            except FAILURES as error:
                skipped += [{**i, 'status': 'incomplete', 'error': str(error)} for i in intents]
                continue
            public_releases = [r for page in releases for r in page]
            for intent in sorted(intents, key=lambda i: tuple(map(int, i['version'].split('.')))):
                try:
                    status = state(repo, key, intent['version'], intent['source_sha'], public_releases)
                except FAILURES as error:
                    skipped.append({**intent, 'status': 'incomplete', 'error': str(error)})
                    continue
                if status == 'pending':
                    pending.append(intent)
                elif status:
                    skipped.append({**intent, 'status': status})
    return pending, skipped


if __name__ == '__main__':
    plan, skipped = queue()
    text_plan = json.dumps({'include': plan}, separators=(',', ':'))
    broken = [s for s in skipped if s['status'] == 'incomplete']
    for item in skipped:
        level = 'error' if item in broken else 'notice'
        detail = ' '.join(item.get('error', '').split())
        print(f"::{level}::{item['package']} {item['version']}: {item['status']} {detail}".rstrip())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('pending=' + str(bool(plan)).lower() + '\n')
            output.write('matrix=' + text_plan + '\n')
            output.write('broken=' + str(bool(broken)).lower() + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('Recover queue\n\n```json\n' + json.dumps({'pending': plan, 'skipped': skipped}, indent=2)
                          + '\n```\n')
    print(text_plan)
