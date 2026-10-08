"""Fail on any mismatch between the package list, the allowlist, Release Please and generated files.

Every package must be allowlisted with its own repository. An allowlist key without a package is
reserved: it is reviewed in advance (for an import) but nothing publishes to it until the package exists.
"""
import json
import re

from common import ROOT, allowlist, load
from generate_github import stale

FIELDS = ("path", "target", "component", "repository")
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^\s'\"#]+)", re.M)
PINNED = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}\Z")


def unpinned(root=ROOT):
    """Every action reference is a full commit SHA; local reusable workflows are exempt."""
    return [f"{path.relative_to(root).as_posix()}: {ref}"
            for path in sorted((root / ".github/workflows").glob("*.y*ml"))
            for ref in USES.findall(path.read_text())
            if not ref.startswith("./") and not PINNED.match(ref)]


def problems(root=ROOT):
    try:
        names = allowlist(root)
    except (ValueError, KeyError, OSError) as error:
        return [str(error)]
    packages = load(root / "release/packages.json")["packages"]
    errors = []
    for key, package in packages.items():
        missing = [f for f in FIELDS if not package.get(f)]
        if missing:
            errors.append(f"{key}: missing {', '.join(missing)}")
        if names.get(key) != package.get("repository"):
            errors.append(f"{key}: repository {package.get('repository')!r} differs from allowlist {names.get(key)!r}")
    for field in ("path", "component"):
        values = [p.get(field) for p in packages.values()]
        errors += [f"Duplicate {field}: {v}" for v in sorted({v for v in values if values.count(v) > 1})]
    # A package may exist before its Release Please entry (the import adds it later), never the reverse.
    by_path = {p.get("path"): p for p in packages.values()}
    for path, entry in sorted(load(root / "release-please-config.json").get("packages", {}).items()):
        if path not in by_path or entry.get("component") != by_path[path].get("component"):
            errors.append(f"Release Please package {path} has no package with component {entry.get('component')!r}")
    if not errors:
        errors += [f"Stale generated file (run python3 scripts/generate_github.py): {p}" for p in stale(root)]
    errors += [f"Action not pinned to a 40-character commit SHA: {ref}" for ref in unpinned(root)]
    return errors


if __name__ == "__main__":
    found = problems()
    if found:
        raise SystemExit("Inventory check failed:\n" + "\n".join(found))
    packages = load(ROOT / "release/packages.json")["packages"]
    print(json.dumps({"packages": list(packages), "reserved": sorted(set(allowlist()) - set(packages))}))
