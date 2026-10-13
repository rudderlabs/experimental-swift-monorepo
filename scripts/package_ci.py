"""PR CI and developer commands for the packages: iOS Simulator tests, export check, lint, hints, ci-ok.

`make test`, `make lint` and the ci.yml jobs call this file, so local runs and CI run the same commands.
The CI plan (which packages those jobs check) is ci_plan.py. Do not import it here: every script this file imports
selects every package in the plan, so a plan-only change would run every package's tests.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.sax.saxutils import quoteattr

from common import ROOT, anonymous_env, git, inventory, run, url
from dependency_policy import manifest
from project import PLATFORM, export
from publish import platform_builds

TYPES = "feat|fix|refactor|perf|style|test|docs|chore|build|ci|revert"
TITLE = re.compile(rf"(?:{TYPES})\((?P<scope>[^)]*)\)!?: ")
PICK_SIMULATOR = ROOT / "scripts/ci/pick-simulator.sh"
# Per-package test scheme, written for each `test (<key>)` run and removed after it (test_scheme).
SCHEME = "package-ci-{}"


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


def scheme_xml(targets):
    """A scheme whose build and test actions hold only `targets`. `-only-testing` limits what runs, not what builds:
    the package's `-Package` scheme compiles every test target and its vendors (an integration job built Firebase)."""
    def ref(name):
        name = quoteattr(name)
        return (f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier={name} BuildableName={name}'
                f' BlueprintName={name} ReferencedContainer="container:"/>')
    build = "".join(f'<BuildActionEntry buildForTesting="YES" buildForRunning="NO" buildForProfiling="NO"'
                    f' buildForArchiving="NO" buildForAnalyzing="NO">{ref(t)}</BuildActionEntry>' for t in targets)
    tests = "".join(f'<TestableReference skipped="NO">{ref(t)}</TestableReference>' for t in targets)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<Scheme version="1.7">'
            f'<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries>{build}'
            '</BuildActionEntries></BuildAction><TestAction buildConfiguration="Debug" shouldUseLaunchSchemeArgsEnv="YES">'
            f'<Testables>{tests}</Testables></TestAction></Scheme>\n')


@contextlib.contextmanager
def test_scheme(data, key, package, root=ROOT):
    """Writes the package's test scheme into the git-ignored .swiftpm/ for one run, so nothing is committed (D18)."""
    path = root / ".swiftpm/xcode/xcshareddata/xcschemes" / f"{SCHEME.format(key)}.xcscheme"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scheme_xml(test_targets(data, package)))
    try:
        yield path.stem
    finally:
        path.unlink(missing_ok=True)


def test_command(data, key, package, simulator, results):
    targets = test_targets(data, package)
    if not targets:
        raise ValueError(f"{key}: no test target under {package['path']}/Tests or depending on {package['target']}")
    # No failure diagnostics: `simctl diagnose` after a failing test can stall for many minutes.
    # Serial, like the SDK's `swift test --no-parallel` (its async tests hang in parallel); a hung test fails after 2 min.
    return ["xcodebuild", "test", "-quiet", "-collect-test-diagnostics", "never", "-parallel-testing-enabled", "NO",
            "-test-timeouts-enabled", "YES", "-default-test-execution-time-allowance", "120",
            "-scheme", SCHEME.format(key), "-destination", f"platform=iOS Simulator,id={simulator}",
            "-resultBundlePath", str(results), *[f"-only-testing:{name}" for name in targets]]


def failures(results):
    """`<test>: <message>` for each failed test in a result bundle; `-quiet` prints only the test names."""
    try:
        summary = json.loads(run(["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", results]))
    except (RuntimeError, ValueError) as error:
        return [f"(no failure details: {str(error).splitlines()[0]})"]
    return [f"{f.get('testIdentifierString', f.get('testName', '?'))}: {f.get('failureText', '').strip()}"
            for f in summary.get("testFailures", [])]


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
        with tempfile.TemporaryDirectory(prefix=f"test-{key}-") as temp:
            results = Path(temp) / "results.xcresult"
            command = test_command(data, key, packages[key], simulator, results)
            print(f"test ({key}): {' '.join(command)}", flush=True)
            with test_scheme(data, key, packages[key], root):
                failed = subprocess.run(command, cwd=root).returncode
            if failed:
                print(f"test ({key}) failures:", *[f"  {line}" for line in failures(results)], sep="\n", flush=True)
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
    paths = set(git(root, "diff", "--name-only", git(root, "merge-base", base, "HEAD")).splitlines())
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
