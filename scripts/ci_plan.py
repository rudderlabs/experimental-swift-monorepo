"""CI plan (D34): which packages to test and export, and whether the policy job runs, as JSON.

ci.yml's `packages` job, the pre-push hook and `make affected` call this file. It is separate from package_ci.py (the
package jobs) so that a change to the plan alone runs only the Python tests. package_ci.py must not import it.
"""
import argparse
import ast
import json
import os
import sys

from common import ROOT, git, inventory
from release_plan import affected

# A trailing slash matches a folder. The scripts the package-job runner (package_ci.py) imports also count as BUILD.
# release/packages.json is not BUILD: changed_entries() selects the packages whose entry changed.
RUNNER = "package_ci"
INVENTORY = "release/packages.json"
BUILD = ("Package.swift", "Package.resolved", ".swiftlint.yml", "release/allowlist.json", ".github/workflows/ci.yml",
         "scripts/ci/")
EXPORT = ("LICENSE", "release/templates/")
POLICY = ("scripts/", "release/", "Tests/", ".github/", "Shared/", "Makefile", "Package.swift", "Package.resolved",
          ".release-please-manifest.json", "release-please-config.json")
POLICY_FILES = ("dependency-requirements.json", "shared-source.json")


def matches(path, patterns):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in patterns)


def imported(root=ROOT):
    """scripts/ modules the package-job runner imports, directly or not: each changes how every package is checked."""
    found, pending = set(), [RUNNER]
    while pending:
        path = f"scripts/{pending.pop()}.py"
        if path in found or not (root / path).is_file():
            continue
        found.add(path)
        for node in ast.walk(ast.parse((root / path).read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                pending.append(node.module)
            elif isinstance(node, ast.Import):
                pending += [alias.name for alias in node.names]
    return found


def dependents(keys, packages):
    """`keys` plus every package that depends on one of them, directly or not (inventory policies, D18)."""
    result = set(keys)
    while True:
        more = {k for k, p in packages.items() if k not in result
                and any(v.get("package") in result for v in p.get("policies", {}).values())}
        if not more:
            return result
        result |= more


def changed_entries(root=ROOT, base_ref="HEAD"):
    """Keys whose release/packages.json entry was added, removed or changed since `base_ref` (parsed JSON, so
    whitespace and key order do not count); `None` (every package) when a field outside `packages` changed or the
    file is missing or unreadable at `base_ref`."""
    try:
        before = json.loads(git(root, "show", f"{base_ref}:{INVENTORY}"))
        old = before.pop("packages")
    except (RuntimeError, ValueError, KeyError, AttributeError):
        return None
    after = json.loads(git(root, "show", f"HEAD:{INVENTORY}"))  # committed, like the changed paths
    new = after.pop("packages")
    if before != after:
        return None
    return {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}


def ci_plan(paths, root=ROOT, base_ref="HEAD", with_dependents=True):
    """Packages to test and export and whether the policy job runs; `paths=None` checks everything.

    Shared build inputs select every package, LICENSE and release templates every export, docs nothing. Other paths
    select their package (release_plan.affected), and tests also cover the packages that depend on it unless
    `with_dependents` is false (the pre-push hook). A release/packages.json change selects the packages whose entry
    changed (changed_entries), the same way.
    """
    packages = inventory(root)
    every = list(packages)
    if paths is None:
        return {"test": every, "export": every, "policy": True}
    policy = any(matches(p, POLICY) or p.rsplit("/", 1)[-1] in POLICY_FILES for p in paths)
    build = imported()
    entries = changed_entries(root, base_ref) if INVENTORY in paths else set()
    if entries is None or any(matches(p, BUILD) or p in build for p in paths):
        return {"test": every, "export": every, "policy": policy}
    code = [p for p in paths if p != INVENTORY and not matches(p, EXPORT) and not p.endswith(".md")
            and not p.startswith("docs/")]
    direct = (affected(code, root, base_ref) if code else []) + [k for k in every if k in entries]
    test = dependents(direct, packages) if with_dependents else set(direct)
    export = every if any(matches(p, EXPORT) for p in paths) else direct
    return {"test": [k for k in every if k in test], "export": [k for k in every if k in export], "policy": policy}


def base_commit(base, root=ROOT):
    return git(root, "merge-base", base, "HEAD")


def changed(base, root=ROOT):
    """Paths this branch changes since it left `base` (committed only)."""
    return git(root, "diff", "--name-only", base_commit(base, root), "HEAD").splitlines()


def push_plan(before, root=ROOT):
    """Push plan: what changed since `before` (the branch's previous commit), or everything when `before` is unknown:
    all zeros (a new branch), empty, or missing from the checkout (a force push)."""
    try:
        base = base_commit(before, root)
    except RuntimeError:
        return ci_plan(None, root)
    return ci_plan(changed(base, root), root, base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="PR base: check what this branch changes since it left BASE")
    group.add_argument("--before", help="push: check what changed since BEFORE, or everything when it is unknown")
    group.add_argument("--all", action="store_true", help="check everything")
    parser.add_argument("--affected", action="store_true",
                        help="with --base: print only the packages the branch changes (make affected)")
    parser.add_argument("--no-dependents", action="store_true",
                        help="with --base: test the changed packages but not their dependents (pre-push hook)")
    args = parser.parse_args(argv)
    if args.no_dependents and args.base is None:
        parser.error("--no-dependents needs --base")
    if args.affected:
        if args.base is None:
            parser.error("--affected needs --base")
        print(json.dumps(affected(changed(args.base), base_ref=base_commit(args.base))))
        return 0
    if args.all:
        plan = ci_plan(None)
    elif args.before is not None:
        plan = push_plan(args.before)
    else:
        plan = ci_plan(changed(args.base), base_ref=base_commit(args.base),
                       with_dependents=not args.no_dependents)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for name, value in plan.items():
                output.write(f"{name}={json.dumps(value, separators=(',', ':'))}\n")
    print(json.dumps(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
