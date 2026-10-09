"""Test a customer upgrade from a fresh public consumer without credentials."""
import argparse
import json
from pathlib import Path
import tempfile

from common import ROOT, CONSUMER_NAME, OWNER, allowlist, anonymous_env, git, inventory, load, run, write_json


def verify(key, version, destination, source_root=ROOT):
    with tempfile.TemporaryDirectory(prefix='public-customer-') as temp:
        consumer = Path(temp) / 'consumer'
        env = anonymous_env()
        run(['git', 'clone', '--branch', 'main', '--single-branch',
             f'https://github.com/{OWNER}/{CONSUMER_NAME}.git', consumer], env=env)
        sha = git(consumer, 'rev-parse', 'HEAD')
        selections = [f'{key}={version}']
        minimum = inventory(source_root)[key].get('sdkMinimum')
        sdk = load(consumer / 'dependencies.json')['sdk']['version']
        if minimum and tuple(map(int, sdk.split('.'))) < tuple(map(int, minimum.split('.'))):
            selections.append('sdk=' + minimum)
        run(['python3', 'scripts/dependencies.py', '--set', *selections], cwd=consumer, env=env)
        result = json.loads(run(['python3', 'scripts/verify.py', '--ios'], cwd=consumer, env=env))
        result.update(package=key, version=version, consumerCommit=sha)
        write_json(destination / 'customer-result.json', result)
        (destination / 'Package.resolved').write_bytes((consumer / 'Package.resolved').read_bytes())
        project_lock = consumer / 'PublicationDemo.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved'
        (destination / 'Xcode-Package.resolved').write_bytes(project_lock.read_bytes())
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', choices=list(allowlist()))
    parser.add_argument('version')
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = verify(args.package, args.version, args.destination, args.source_root)
    except (ValueError, RuntimeError, OSError) as error:
        result = {'status': 'failed', 'package': args.package, 'version': args.version, 'error': str(error),
                  'note': 'The public tag may already be served; rerun verification without moving the tag.'}
        write_json(args.destination / 'customer-result.json', result)
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))
