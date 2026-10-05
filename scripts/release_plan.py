"""Affected-package discovery and reviewed shared-source release markers."""
import argparse
import hashlib
import json
import os

from common import ROOT, git, inventory, load, write_json
from project import SEMVER
from dependency_policy import package_requirements, manifest


def shared_markers(root=ROOT, check=False):
    files = sorted((root / "Shared").rglob("*.swift"))
    fingerprints = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    changed = []
    for key, package in inventory(root).items():
        if not any(p["mode"] == "vendor" for p in package["policies"].values()):
            continue
        path = root / package["path"] / "shared-source.json"
        if not path.exists() or load(path) != fingerprints:
            changed.append(key)
            if not check:
                write_json(path, fingerprints)
    if check and changed:
        raise ValueError("Run release_plan.py sync-shared and include the markers in the shared-change fix/feat commit: " + ", ".join(changed))
    return changed


def affected(paths, root=ROOT, base_ref="HEAD"):
    result = []
    packages = inventory(root)
    dependency_changes = set()
    if {"Package.swift", "release/packages.json"}.intersection(paths):
        expected = package_requirements(manifest(root), packages)
        for key, package in packages.items():
            marker = package["path"] + "/dependency-requirements.json"
            # Require an explicit committed baseline. Missing history is an error.
            before = json.loads(git(root, "show", f"{base_ref}:{marker}"))
            if before != expected[key]:
                dependency_changes.add(key)
    for key, p in packages.items():
        if any(path.startswith(p["path"] + "/") or
               (path.startswith("Shared/") and any(d["mode"] == "vendor" for d in p["policies"].values()))
               for path in paths) or key in dependency_changes:
            result.append(key)
    return result


def from_outputs(outputs, root=ROOT):
    result = []
    for key, p in inventory(root).items():
        if str(outputs.get(p['path'] + '--release_created', '')).lower() != 'true':
            continue
        version = outputs[p['path'] + '--version']
        sha = outputs[p['path'] + '--sha']
        if not SEMVER.fullmatch(version) or not __import__('re').fullmatch('[0-9a-f]{40}', sha):
            raise ValueError('Invalid Release Please output')
        result.append({'package': key, 'version': version, 'sha': sha})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['sync-shared', 'affected', 'from-outputs'])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--base-ref', default='HEAD')
    parser.add_argument('paths', nargs='*')
    args = parser.parse_intermixed_args()
    if args.command == 'sync-shared':
        print(json.dumps(shared_markers(check=args.check)))
    elif args.command == 'affected':
        print(json.dumps(affected(args.paths, base_ref=args.base_ref)))
    else:
        print(json.dumps(from_outputs(json.loads(os.environ['RELEASE_PLEASE_OUTPUTS']))))
