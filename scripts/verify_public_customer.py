"""Test a customer install of a published version without credentials: a throwaway SwiftPM package
depends on the public tag and builds with xcodebuild on each checked platform the package supports."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from common import ROOT, OWNER, allowlist, anonymous_env, inventory, run, write_json

CHECKED_PLATFORMS = ('iOS', 'macOS')
DESTINATIONS = {'iOS': 'generic/platform=iOS Simulator', 'macOS': 'generic/platform=macOS'}
VERSION = re.compile(r'(\d+)(?:\.(\d+))?\Z')


def minimums(package):
    """Checked platform -> minimum version string (e.g. 'iOS' -> '15') from the package's `platforms`."""
    found = dict(value.split(' ', 1) for value in package.get('platforms', []))
    return {name: found[name] for name in CHECKED_PLATFORMS if name in found}


def platforms(package):
    return list(minimums(package))


def write_consumer(folder, package, url, version):
    folder = Path(folder)
    identity = url.removesuffix('.git').rsplit('/', 1)[-1].lower()
    supported = []
    for name, minimum in minimums(package).items():
        match = VERSION.fullmatch(minimum)
        if not match:
            raise ValueError(f'Unsupported platform version: {name} {minimum}')
        supported.append(f'.{name}(.v{match[1]}{"_" + match[2] if match[2] and match[2] != "0" else ""})')
    if not supported:
        raise ValueError(f'{package["target"]} supports none of {", ".join(CHECKED_PLATFORMS)}')
    (folder / 'Sources/Consumer').mkdir(parents=True, exist_ok=True)
    (folder / 'Package.swift').write_text(f'''// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Consumer",
    platforms: [{", ".join(supported)}],
    products: [.library(name: "Consumer", targets: ["Consumer"])],
    dependencies: [.package(url: "{url}", exact: "{version}")],
    targets: [.target(name: "Consumer", dependencies: [.product(name: "{package["target"]}", package: "{identity}")])]
)
''')
    (folder / 'Sources/Consumer/Consumer.swift').write_text(f'import {package["target"]}\n')


def build(folder, platform, state, env):
    # Isolated package state: nothing comes from this machine's caches or credentials.
    output = run(['xcodebuild', 'build', '-scheme', 'Consumer', '-destination', DESTINATIONS[platform],
                  '-derivedDataPath', state / 'derived', '-clonedSourcePackagesDirPath', state / 'packages',
                  '-packageCachePath', state / 'cache', '-disablePackageRepositoryCache',
                  '-packageFingerprintPolicy', 'strict', '-scmProvider', 'system', 'CODE_SIGNING_ALLOWED=NO'],
                 cwd=folder, env=env)
    if '** BUILD SUCCEEDED **' not in output:
        raise RuntimeError(f'Customer build for {platform} did not succeed\n{output[-4000:]}')


def verify(key, version, destination, source_root=ROOT):
    package = inventory(source_root)[key]
    url = f'https://github.com/{OWNER}/{package["repository"]}.git'
    identity = package['repository'].lower()
    with tempfile.TemporaryDirectory(prefix='public-customer-') as temp:
        folder, state, env = Path(temp) / 'consumer', Path(temp) / 'state', anonymous_env()
        write_consumer(folder, package, url, version)
        built = []
        for platform in platforms(package):
            build(folder, platform, state, env)
            built.append(platform)
        lock = folder / 'Package.resolved'
        pins = {pin['identity']: pin['state'].get('version') for pin in json.loads(lock.read_text())['pins']}
        if pins.get(identity) != version:
            raise ValueError(f'{identity} resolved to {pins.get(identity)}, expected {version}')
        result = {'status': 'passed', 'package': key, 'version': version, 'platforms': built,
                  'transport': 'anonymous-public-git', 'resolved': pins}
        write_json(destination / 'customer-result.json', result)
        (destination / 'Package.resolved').write_bytes(lock.read_bytes())
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
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        result = {'status': 'failed', 'package': args.package, 'version': args.version, 'error': str(error),
                  'note': 'The public tag may already be served; rerun verification without moving the tag.'}
        write_json(args.destination / 'customer-result.json', result)
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))
