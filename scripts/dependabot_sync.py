"""After `make sync` on a Dependabot PR: which release markers changed, and the releasable PR title (D27).

A canonical requirement change in Package.swift changes the markers of the packages that use the
vendor. Those packages must release, so the squash title becomes `fix(<keys>): bump <dep> to <version>`.
"""
import json
import os
import re

from common import ROOT, git, inventory

MARKER = "dependency-requirements.json"
PREFIX = re.compile(r"[a-z]+(?:\([^)]*\))?!?:\s*")
BUMP = re.compile(r"bump (\S+) from \S+ to (\S+)", re.I)
LIMIT = 100


def changed_packages(paths, packages):
    return sorted(key for key, p in packages.items() if f"{p['path']}/{MARKER}" in paths)


def retitle(title, keys):
    """The releasable title for the packages whose markers changed, or None when none did."""
    if not keys:
        return None
    text = PREFIX.sub("", " ".join(title.split()), count=1)  # one line, safe for GITHUB_OUTPUT
    bump = BUMP.match(text)
    description = (f"bump {bump[1]} to {bump[2]}" if bump else text[:1].lower() + text[1:]).rstrip(".")
    scoped = f"fix({','.join(keys)}): {description}"
    return scoped if len(scoped) <= LIMIT else f"fix: {description}"[:LIMIT]


def changed_paths(root=ROOT):
    return (git(root, "diff", "--name-only", "HEAD").splitlines()
            + git(root, "ls-files", "--others", "--exclude-standard").splitlines())


if __name__ == "__main__":
    paths = changed_paths()
    keys = changed_packages(paths, inventory())
    result = {"dirty": bool(paths), "packages": keys, "title": retitle(os.environ["PR_TITLE"], keys) or ""}
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"dirty={str(result['dirty']).lower()}\ntitle={result['title']}\n")
    print(json.dumps(result))
