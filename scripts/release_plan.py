"""Affected-package discovery and reviewed shared-source release markers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from common import ROOT, git, inventory, load, write_json
from project import SEMVER, wide_access
from dependency_policy import package_requirements, manifest


def shared_access(root=ROOT):
    """Shared code is vendored into several public packages, so it must not widen past `package`."""
    found = [f"{p.relative_to(root).as_posix()}:{line}" for p in sorted((root / "Shared").rglob("*.swift"))
             for line in wide_access(p.read_bytes().decode())]
    if found:
        raise ValueError("Shared code must use `package` access, not public/open: " + ", ".join(found))


def vendored(packages, root=ROOT, data=None):
    """Source directory of each vendored target per package, from the parsed manifest."""
    names = {key: [n for n, p in package["policies"].items() if p["mode"] == "vendor"]
             for key, package in packages.items()}
    if not any(names.values()):
        return names
    targets = {t["name"]: t for t in (data or manifest(root))["targets"]}
    return {key: [Path(targets[n].get("path") or f"Sources/{n}").as_posix() for n in values]
            for key, values in names.items()}


def shared_markers(root=ROOT, check=False):
    shared_access(root)
    packages = inventory(root)
    changed = []
    for key, paths in vendored(packages, root).items():
        if not paths:
            continue
        # Only the vendored targets' files, so an unrelated shared target selects nothing here.
        fingerprints = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(f for path in paths for f in (root / path).rglob("*.swift"))}
        path = root / packages[key]["path"] / "shared-source.json"
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
    data = None
    if {"Package.swift", "release/packages.json"}.intersection(paths):
        data = manifest(root)
        expected = package_requirements(data, packages)
        for key, package in packages.items():
            marker = package["path"] + "/dependency-requirements.json"
            # Require an explicit committed baseline. Missing history is an error.
            before = json.loads(git(root, "show", f"{base_ref}:{marker}"))
            if before != expected[key]:
                dependency_changes.add(key)
    sources = vendored(packages, root, data)
    for key, p in packages.items():
        if any(path.startswith(tuple(d + "/" for d in [p["path"], *sources[key]])) for path in paths) \
                or key in dependency_changes:
            result.append(key)
    return result


def from_outputs(outputs, root=ROOT):
    """Released packages from path-based Release Please outputs, SDK first."""
    result = []
    packages = inventory(root)
    for key in sorted(packages, key=lambda k: k != 'sdk'):
        p = packages[key]
        if str(outputs.get(p['path'] + '--release_created', '')).lower() != 'true':
            continue
        version = outputs[p['path'] + '--version']
        sha = outputs[p['path'] + '--sha']
        if not SEMVER.fullmatch(version) or not re.fullmatch('[0-9a-f]{40}', sha):
            raise ValueError('Invalid Release Please output')
        result.append({'package': key, 'version': version, 'sha': sha})
    return result


def jobs(plan):
    """Workflow outputs: the SDK job input and the integrations matrix."""
    return {'plan': plan, 'sdk': next((p for p in plan if p['package'] == 'sdk'), None),
            'integrations': [p for p in plan if p['package'] != 'sdk']}


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
        result = jobs(from_outputs(json.loads(os.environ['RELEASE_PLEASE_OUTPUTS'])))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                for name, value in result.items():
                    output.write(name + '=' + json.dumps(value, separators=(',', ':')) + '\n')
        print(json.dumps(result))
