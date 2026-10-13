"""Test a customer upgrade from a fresh public consumer without credentials."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from common import ROOT, CONSUMER_NAME, OWNER, allowlist, anonymous_env, git, inventory, load, run, write_json


def dependency_args(key, version, consumer_sdk, minimum=None):
    """Arguments for the consumer's dependencies.py: one --set per package (it appends repeated flags)."""
    selections = [f'{key}={version}']
    if key != 'sdk' and minimum and tuple(map(int, consumer_sdk.split('.'))) < tuple(map(int, minimum.split('.'))):
        selections.append('sdk=' + minimum)
    return [arg for selection in selections for arg in ('--set', selection)]


def verify(key, version, destination, source_root=ROOT, consumer_source=None):
    with tempfile.TemporaryDirectory(prefix='public-customer-') as temp:
        consumer = Path(temp) / 'consumer'
        env = anonymous_env()
        if consumer_source:
            # A local consumer checkout (for example an unmerged consumer change); packages still resolve publicly.
            shutil.copytree(consumer_source, consumer,
                            ignore=shutil.ignore_patterns('.git', '.build', '.swiftpm', 'DerivedData', '__pycache__'))
            sha = git(consumer_source, 'rev-parse', 'HEAD')
        else:
            run(['git', 'clone', '--branch', 'main', '--single-branch',
                 f'https://github.com/{OWNER}/{CONSUMER_NAME}.git', consumer], env=env)
            sha = git(consumer, 'rev-parse', 'HEAD')
        minimum = inventory(source_root)[key].get('sdkMinimum')
        sdk = load(consumer / 'dependencies.json')['sdk']['version']
        run(['python3', 'scripts/dependencies.py', *dependency_args(key, version, sdk, minimum)], cwd=consumer, env=env)
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
    parser.add_argument('--consumer', type=Path, help='local consumer checkout instead of a fresh clone of its main')
    args = parser.parse_args()
    try:
        result = verify(args.package, args.version, args.destination, args.source_root, args.consumer)
    except (ValueError, RuntimeError, OSError) as error:
        result = {'status': 'failed', 'package': args.package, 'version': args.version, 'error': str(error),
                  'note': 'The public tag may already be served; rerun verification without moving the tag.'}
        write_json(args.destination / 'customer-result.json', result)
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))
