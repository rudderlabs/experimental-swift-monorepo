"""PR CI and developer commands for the packages: matrix, iOS Simulator tests, export check, lint, hints.

`make test`, `make lint` and `make affected` and the ci.yml jobs call this file, so local runs and CI
run the same commands.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from common import ROOT, anonymous_env, git, inventory, run, url
from dependency_policy import manifest
from project import PLATFORM, export
from publish import platform_builds
from release_plan import affected

TYPES = "feat|fix|refactor|perf|style|test|docs|chore|build|ci|revert"
TITLE = re.compile(rf"(?:{TYPES})\((?P<scope>[^)]*)\)!?: ")
PICK_SIMULATOR = ROOT / "scripts/ci/pick-simulator.sh"


def matrix(root=ROOT):
    """Package keys for the `test (<key>)` and `export (<key>)` matrices; `[]` skips both."""
    return list(inventory(root))


def test_targets(data, package):
    """Test targets under the package path (D10); otherwise those that depend on the package target."""
    tests = [t for t in data["targets"] if t["type"] == "test"]
    own = [t["name"] for t in tests
           if (t.get("path") or f"Tests/{t['name']}").startswith(package["path"] + "/")]
    if own:
        return own
    return [t["name"] for t in tests
            if any((d.get("byName") or d.get("target") or [None])[0] == package["target"]
                   for d in t["dependencies"])]


def test_command(data, key, package, simulator):
    targets = test_targets(data, package)
    if not targets:
        raise ValueError(f"{key}: no test target under {package['path']}/Tests or depending on {package['target']}")
    # No failure diagnostics: `simctl diagnose` after a failing test can stall for many minutes.
    return ["xcodebuild", "test", "-quiet", "-collect-test-diagnostics", "never",
            "-scheme", data["name"] + "-Package", "-destination", f"platform=iOS Simulator,id={simulator}",
            *[f"-only-testing:{name}" for name in targets]]


def test(keys=None, root=ROOT):
    """iOS Simulator tests per package (D22), the same command as CI's `test (<key>)` job."""
    packages = inventory(root)
    if not (root / "Package.swift").exists():
        if keys:
            raise ValueError("There is no root Package.swift, so there are no package tests")
        print("No root Package.swift yet: no package tests to run.")
        return
    unknown = sorted(set(keys or []) - set(packages))
    if unknown:
        raise ValueError(f"Unknown package: {', '.join(unknown)} (known: {', '.join(packages) or 'none'})")
    data = manifest(root)
    simulator = run([PICK_SIMULATOR], cwd=root)
    for key in keys or packages:
        command = test_command(data, key, packages[key], simulator)
        print(f"test ({key}): {' '.join(command)}", flush=True)
        if subprocess.run(command, cwd=root).returncode:
            raise SystemExit(f"test ({key}) failed")
        print(f"test ({key}) passed", flush=True)


def manifest_problems(data, package, packages):
    """Problems in an exported manifest (`swift package dump-package` of the export)."""
    problems = []
    expected = []
    for value in package["platforms"]:
        name, major, minor = PLATFORM.fullmatch(value).groups()
        expected.append((name.lower(), f"{major}.{minor or 0}"))
    actual = [(p["platformName"].lower(), p["version"]) for p in data.get("platforms") or []]
    if sorted(actual) != sorted(expected):
        problems.append(f"platforms {actual} differ from the inventory {expected}")
    identities = []
    for dependency in data["dependencies"]:
        if "sourceControl" not in dependency:
            problems.append(f"non-Git package dependency (local path?): {sorted(dependency)}")
            continue
        source = dependency["sourceControl"][0]
        identities.append(source["identity"])
        if not source["location"].get("remote"):
            problems.append(f"{source['identity']} is not a remote URL")
    wanted = sorted({v["identity"] for v in package.get("vendors", [])}
                    | {packages[p["package"]]["repository"].lower()
                       for p in package.get("policies", {}).values() if p.get("mode") == "external"})
    if sorted(identities) != wanted:
        problems.append(f"package dependencies {sorted(identities)} differ from one per vendor/SDK {wanted}")
    return problems


def unpublished_dependencies(package, root=ROOT):
    """External packages whose required tag (sdkMinimum) is not public yet; the build then waits for release."""
    missing = []
    for policy in package.get("policies", {}).values():
        if policy.get("mode") == "external":
            tag = f"refs/tags/{package['sdkMinimum']}"
            if not run(["git", "ls-remote", "--tags", url(policy["package"], root), tag], env=anonymous_env()):
                missing.append(f"{policy['package']} {package['sdkMinimum']}")
    return missing


def export_check(key, root=ROOT):
    """Export to a temporary folder, check the generated manifest, then build it for iOS (generic device)."""
    packages = inventory(root)
    package = packages[key]
    version = (root / package["path"] / "version.txt").read_text().strip()
    with tempfile.TemporaryDirectory(prefix=f"export-{key}-") as temp:
        stage = Path(temp) / "export"
        export(key, version, stage, root, preview=True)
        data = json.loads(run(["swift", "package", "dump-package"], cwd=stage, env=anonymous_env()))
        problems = manifest_problems(data, package, packages)
        if problems:
            raise ValueError(f"export ({key}) manifest:\n" + "\n".join(problems))
        print(f"export ({key}) {version}: manifest has the inventory platforms and one package per vendor")
        ios = [p for p in package["platforms"] if p.split()[0] == "iOS"]
        if not ios:
            raise ValueError(f"{key}: PR CI builds iOS only (D22), but the package declares no iOS platform")
        waiting = unpublished_dependencies(package, root)
        if waiting:
            print(f"::warning::export ({key}): skipped the iOS build until {', '.join(waiting)} is published")
            return
        platform_builds(stage, {"target": package["target"], "platforms": ios}, Path(temp) / "state")
        print(f"export ({key}): generic iOS build passed")


def base_commit(base, root=ROOT):
    return git(root, "merge-base", base, "HEAD")


def changed(base, root=ROOT):
    """Paths this branch changes since it left `base` (committed only)."""
    return git(root, "diff", "--name-only", base_commit(base, root), "HEAD").splitlines()


def lint(paths=None, root=ROOT, strict=False, reporter=None):
    """SwiftLint with the root .swiftlint.yml; `paths=None` lints the repository. Nothing to lint is a pass."""
    if paths is not None and not paths:
        print("No changed Swift files to lint.")
        return 0
    command = ["swiftlint", "lint", "--quiet", *(["--strict"] if strict else []),
               *(["--reporter", reporter] if reporter else []),
               *(["--force-exclude", *paths] if paths else [])]
    try:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    except FileNotFoundError:
        raise SystemExit("SwiftLint is not installed: brew install swiftlint")
    if result.returncode and "No lintable files found" in result.stdout + result.stderr:
        print("No Swift files to lint (all excluded by .swiftlint.yml).")
        return 0
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if not result.returncode:
        print(f"SwiftLint passed ({len(paths)} changed files)." if paths else "SwiftLint passed.")
    return result.returncode


def changed_swift(base, root=ROOT):
    """Changed, uncommitted and untracked .swift files that still exist."""
    paths = set(git(root, "diff", "--name-only", base_commit(base, root)).splitlines())
    paths |= set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(p for p in paths if p.endswith(".swift") and (root / p).is_file())


def scope_warnings(title, paths, packages):
    """D16: the title scope is cosmetic; warn (never fail) when it names a package the PR does not touch."""
    match = TITLE.match(title)
    if not match:
        return []
    warnings = []
    for scope in (s.strip() for s in match["scope"].split(",")):
        if scope in packages and not any(p.startswith(packages[scope]["path"] + "/") for p in paths):
            warnings.append(f"The PR title scope ({scope}) names package {scope}, but the PR changes nothing under "
                            f"{packages[scope]['path']}/. Folders decide what releases; fix the scope or drop it.")
    return warnings


def failed_needs(needs):
    """ci-ok: every needed job must succeed or be skipped (empty matrix); failed or cancelled fails."""
    return sorted(name for name, value in needs.items() if value.get("result") not in ("success", "skipped"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("matrix", help="package keys as JSON")
    command = commands.add_parser("test", help="iOS Simulator tests")
    command.add_argument("--package", action="append")
    commands.add_parser("export-check", help="export, manifest check and iOS build").add_argument(
        "--package", required=True)
    command = commands.add_parser("affected", help="packages this branch changes since BASE")
    command.add_argument("--base", default="origin/main")
    command = commands.add_parser("lint", help="SwiftLint on changed files, or --all")
    command.add_argument("--base", default="origin/main")
    command.add_argument("--all", action="store_true")
    command.add_argument("--strict", action="store_true")
    command.add_argument("--reporter")
    command = commands.add_parser("scope-hint", help="warning-only PR title scope check")
    command.add_argument("--title", required=True)
    command.add_argument("--base", required=True)
    command.add_argument("--head", required=True)
    commands.add_parser("ci-ok", help="fail unless every job in $NEEDS succeeded or was skipped")
    args = parser.parse_args(argv)
    if args.command == "matrix":
        print(json.dumps(matrix(), separators=(",", ":")))
    elif args.command == "test":
        test(args.package)
    elif args.command == "export-check":
        export_check(args.package)
    elif args.command == "affected":
        print(json.dumps(affected(changed(args.base), base_ref=base_commit(args.base))))
    elif args.command == "lint":
        return lint(None if args.all else changed_swift(args.base), strict=args.strict, reporter=args.reporter)
    elif args.command == "scope-hint":
        try:
            paths = git(ROOT, "diff", "--name-only", f"{args.base}...{args.head}").splitlines()
            for warning in scope_warnings(args.title, paths, inventory()):
                print("::warning title=PR title scope::" + warning)
        except Exception as error:  # Warning only (D16): never fail the PR on this hint.
            print(f"::warning title=PR title scope::scope check skipped: {error}")
    elif args.command == "ci-ok":
        needs = json.loads(os.environ["NEEDS"])
        for name, value in sorted(needs.items()):
            print(f"{name}: {value.get('result')}")
        failed = failed_needs(needs)
        if failed:
            print("::error::Required jobs did not pass: " + ", ".join(failed))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
