"""Validate an anchor: a plain `<component>-<version>` tag on a `main` commit, never a GitHub Release (D21)."""
import argparse
import os
import re

from common import ROOT, allowlist, git, inventory
from project import SEMVER


def anchor(key, version, sha, root=ROOT):
    """Return the tag to create, or raise. Only the allowlist and package list of `main` decide."""
    package = inventory(root).get(key)
    if key not in allowlist(root) or not package:
        raise ValueError(f"Package is not allowlisted and listed in release/packages.json: {key}")
    if not SEMVER.fullmatch(version):
        raise ValueError("Version must be X.Y.Z")
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise ValueError("SHA must be a full 40-character commit SHA")
    git(root, "merge-base", "--is-ancestor", sha, "origin/main")
    if git(root, "show", f"{sha}:{package['path']}/version.txt") != version:
        raise ValueError("version.txt at that commit differs from the anchor version")
    tag = f"{package['component']}-{version}"
    if git(root, "tag", "--list", tag):
        raise ValueError(f"Tag already exists: {tag}")
    return tag


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("version")
    parser.add_argument("sha")
    args = parser.parse_args()
    tag = anchor(args.package, args.version, args.sha)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write("tag=" + tag + "\n")
    print(tag)
