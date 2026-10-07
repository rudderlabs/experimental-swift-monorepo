"""Recover pending publication from durable source component releases."""
import json
import os
from pathlib import Path
import tempfile

from common import ROOT, NAMES, OWNER, SOURCE_NAME, git, load, run, url
from project import SEMVER
from publish import verify_tree

COMPONENTS = {'sdk': 'sdk', 'sprig': 'integration-sprig', 'firebase': 'integration-firebase'}


def queue(root=ROOT):
    pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                           f'repos/{OWNER}/{SOURCE_NAME}/releases?per_page=100']))
    pending = []
    for key in NAMES:
        with tempfile.TemporaryDirectory(prefix='publication-queue-') as temp:
            repo = Path(temp) / 'publication'
            run(['git', 'clone', '--no-checkout', url(key), repo])
            releases = json.loads(run(['gh', 'api', '--paginate', '--slurp',
                                      f'repos/{OWNER}/{NAMES[key]}/releases?per_page=100']))
            public_releases = [r for page in releases for r in page]
            intents = []
            for release in (r for page in pages for r in page):
                prefix = COMPONENTS[key] + '-'
                tag = release['tag_name']
                if release['draft'] or release['prerelease'] or not tag.startswith(prefix):
                    continue
                version = tag.removeprefix(prefix)
                if not SEMVER.fullmatch(version):
                    raise ValueError('Malformed experimental component release')
                sha = git(root, 'rev-parse', f'refs/tags/{tag}^{{commit}}')
                git(root, 'merge-base', '--is-ancestor', sha, 'origin/main')
                intents.append({'package': key, 'version': version, 'source_sha': sha})
            for intent in sorted(intents, key=lambda i: tuple(map(int, i['version'].split('.')))):
                version, sha = intent['version'], intent['source_sha']
                exists = git(repo, 'for-each-ref', '--format=%(refname)', f'refs/tags/{version}')
                if exists:
                    git(repo, 'checkout', '--detach', f'refs/tags/{version}')
                    provenance = verify_tree(repo)
                    if (provenance['sourceCommit'] != sha or provenance['package'] != key
                            or provenance['version'] != version):
                        raise ValueError('Published tag conflicts with source release intent')
                    publication_sha = git(repo, 'rev-parse', 'HEAD')
                    git(repo, 'merge-base', '--is-ancestor', publication_sha, 'origin/main')
                    body = f'Temporary unsupported experiment.\n\nSource: {sha}\nPublication: {publication_sha}\n'
                    matches = [r for r in public_releases if r['tag_name'] == version]
                    if matches:
                        if len(matches) != 1 or matches[0]['draft'] or matches[0]['body'] != body:
                            raise ValueError('Existing public Release metadata conflicts')
                        continue
                pending.append(intent)
    return pending


if __name__ == '__main__':
    plan = queue()
    text = json.dumps({'include': plan}, separators=(',', ':'))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('pending=' + str(bool(plan)).lower() + '\n')
            output.write('matrix=' + text + '\n')
    print(text)
