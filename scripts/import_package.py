"""Import an existing package repository at a tag (Path A, step A2). Never commits or pushes.

History mode clones the repository, rewrites it under the package folder with `git filter-repo`
immediately (old tags become `legacy/<key>/<tag>`), and starts a merge of that tag with
`--allow-unrelated-histories`. Snapshot mode copies the files at the tag. Both remove nested
package and per-repository files, move the example app to `Examples/<Name>/`, add the root
Package.swift lines and the package list entry, run the `make sync` steps and stage the result.
There is deliberately no Release Please entry: it follows the anchor tag (D21).
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from common import OWNER, ROOT, git, inventory, run
from dependency_policy import manifest, requirements
from project import SEMVER, TOOLS, requirement
from scaffold import (NAME, add_package, allowlisted, identity, insert, product_line, q, release_please_entry,
                      sync, target_lines, version_swift)

MODES = ("history", "snapshot")
KINDS = ("integration", "core")
# Nested package, Xcode project and per-repository files (globs at the package root); the monorepo owns these once.
REMOVE = ("Package.swift", "Package@swift-*.swift", "Package.resolved", ".swiftpm", ".github", "LICENSE", "LICENSE.md",
          "CODEOWNERS", "sonar-project.properties", "*.xcodeproj", "*.xcworkspace", "scripts/git-hooks")
EXAMPLES = ("Example", "Examples")
SDK_IDENTITIES = ("rudder-sdk-swift",)
PLATFORM_NAMES = {"ios": "iOS", "macos": "macOS", "maccatalyst": "macCatalyst", "tvos": "tvOS",
                  "watchos": "watchOS", "visionos": "visionOS"}
LOCAL_PACKAGE = re.compile(r'(isa = XCLocalSwiftPackageReference;\s*relativePath = )("?)([^";\n]*)\2;')
LOCAL_COMMENT = re.compile(r'(XCLocalSwiftPackageReference ")([^"]*)(")')


def source(repo):
    """A local path or URL as given; a bare name is a repository under OWNER."""
    return repo if "/" in repo or ":" in repo else f"https://github.com/{OWNER}/{repo}.git"


def platform(value):
    """`{"platformName": "ios", "version": "15.0"}` -> `iOS 15`."""
    major, minor = (value["version"].split(".") + ["0"])[:2]
    return f"{PLATFORM_NAMES[value['platformName']]} {major if minor == '0' else major + '.' + minor}"


def tools_version(value):
    """`5.9.0` -> `5.9`."""
    return value[:-2] if value.count(".") == 2 and value.endswith(".0") else value


def rule(resource):
    kind = next(iter(resource["rule"]))
    if kind not in ("process", "copy") or resource["rule"][kind]:
        raise ValueError(f"Unsupported resource rule for {resource['path']}: use process or copy")
    return f".{kind}({q(resource['path'])})"


def describe(data, key, dest, sdk_target, sdk_repository):
    """Root manifest lines and the package list entry from the imported package's own manifest."""
    libraries = [p for p in data["products"] if "library" in p["type"]]
    if len(libraries) != 1 or len(libraries[0]["targets"]) != 1:
        raise ValueError("The imported package needs exactly one library product with one target")
    target = libraries[0]["targets"][0]
    targets = {t["name"]: t for t in data["targets"]}
    extra = [n for n, t in targets.items() if t["type"] != "test" and n != target]
    if extra or targets[target]["type"] != "regular":
        raise ValueError("Only one regular target (plus test targets) can be imported: " + ", ".join(extra))
    vendors = requirements(data)
    sdk = [i for i, v in vendors.items() if i in SDK_IDENTITIES or identity(v["url"]) == sdk_repository.lower()]
    minimum = None
    if key != "sdk":
        if len(sdk) != 1:
            raise ValueError("The imported integration has no rudder-sdk-swift requirement")
        minimum = vendors.pop(sdk[0])["requirement"]["lower"]

    def dependencies(entry):
        result = []
        for dependency in entry["dependencies"]:
            if "product" in dependency:
                product, package = dependency["product"][:2]
                result.append(q(sdk_target) if package in sdk else f".product(name: {q(product)}, package: {q(package)})")
            else:
                name = (dependency.get("target") or dependency.get("byName"))[0]
                if name != target:
                    raise ValueError(f"Unsupported dependency {name} of {entry['name']}")
                result.append(q(name))
        return result

    lines = {"products": product_line(target),
             "dependencies": [f".package(url: {q(v['url'])}, {requirement(v['requirement'])}),"
                              for _, v in sorted(vendors.items())],
             "targets": []}
    for name in [target] + sorted(n for n, t in targets.items() if t["type"] == "test"):
        entry = targets[name]
        test = entry["type"] == "test"
        relative = entry.get("path") or f"{'Tests' if test else 'Sources'}/{name}"
        if not test and relative != f"Sources/{target}":
            raise ValueError(f"The imported target must live in Sources/{target}")
        lines["targets"] += target_lines(name, dependencies(entry), f"{dest}/{relative}", test=test,
                                         resources=[rule(r) for r in entry.get("resources") or []],
                                         exclude=entry.get("exclude") or [])
    platforms = [platform(p) for p in data["platforms"]]
    tools = tools_version(data["toolsVersion"]["_version"])
    if not platforms or not TOOLS.fullmatch(tools):
        raise ValueError("The imported manifest needs explicit platforms and a tools version")
    entry = {"path": dest, "target": target, "component": "sdk" if key == "sdk" else f"integration-{key}",
             "platforms": platforms, "toolsVersion": tools,
             "policies": {} if key == "sdk" else {sdk_target: {"mode": "external", "package": "sdk"}}}
    if minimum:
        entry["sdkMinimum"] = minimum
    resources = [r["path"] for r in targets[target].get("resources") or []]
    if resources:
        entry["resources"] = resources
    return lines, entry


def relink_examples(root, examples, previous, old, names):
    """Point each example's local Swift package reference at the monorepo root instead of the old package root.

    Some examples reach the package through its checkout folder (`../../../../rudder-sdk-swift`), so a sibling
    folder named like the repository also counts as the old package root.
    """
    roots = {old} | {old.parent / name for name in names}
    changed = []
    for project in sorted(examples.rglob("project.pbxproj")):
        base = project.parent.parent
        before = previous / base.relative_to(examples)

        def replace(match):
            value = match[2] if match.re is LOCAL_COMMENT else match[3]
            if Path(os.path.normpath(before / value)) not in roots:
                return match[0]
            new = os.path.relpath(root, base)
            if match.re is LOCAL_COMMENT:
                return match[1] + new + match[3]
            return f"{match[1]}{q(new)};"

        text = project.read_text()
        updated = LOCAL_COMMENT.sub(replace, LOCAL_PACKAGE.sub(replace, text))
        if updated != text:
            project.write_text(updated)
            changed.append(project.relative_to(root).as_posix())
    return changed


def prepare(clone, tag, dest, key, mode):
    """Check out the tag in the clone (rewritten under the package folder in history mode); return the legacy tags."""
    if mode == "snapshot":
        git(clone, "checkout", "--quiet", "--detach", f"refs/tags/{tag}")
        return []
    # Rewrite the fresh clone before anything else touches it.
    git(clone, "filter-repo", "--quiet", "--to-subdirectory-filter", dest, "--tag-rename", f":legacy/{key}/")
    git(clone, "branch", f"import/{key}", f"legacy/{key}/{tag}")
    git(clone, "checkout", "--quiet", f"import/{key}")
    return git(clone, "tag", "--list").splitlines()


def place(root, clone, dest, key, mode):
    """Bring the checked-out files into the monorepo: a merge in progress (history) or plain files (snapshot)."""
    if mode == "history":
        git(root, "fetch", "--quiet", "--no-tags", clone, f"refs/heads/import/{key}")
        git(root, "merge", "--quiet", "--no-ff", "--no-commit", "--allow-unrelated-histories", "FETCH_HEAD")
        return git(root, "rev-parse", "MERGE_HEAD")
    for relative in git(clone, "ls-files", "-z").split("\0"):
        if relative:
            target = root / dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(clone / relative, target, follow_symlinks=False)
    return git(clone, "rev-parse", "HEAD")


def import_package(repo, tag, name, mode, root=ROOT, kind="integration"):
    if mode not in MODES or kind not in KINDS:
        raise ValueError(f"MODE must be one of {MODES} and KIND one of {KINDS}")
    if not SEMVER.fullmatch(tag) or not NAME.fullmatch(name):
        raise ValueError("TAG must be X.Y.Z and NAME PascalCase")
    key = "sdk" if kind == "core" else name.lower()
    dest = f"Packages/{name}" if kind == "core" else f"Integrations/{name}"
    repository = allowlisted(root, key)
    packages = inventory(root)
    if key in packages or (root / dest).exists() or (root / "Examples" / name).exists():
        raise ValueError(f"{key} already exists")
    if kind == "integration" and "sdk" not in packages:
        raise ValueError("release/packages.json has no sdk package; import the core SDK first (KIND=core)")
    sdk_target = packages["sdk"]["target"] if "sdk" in packages else name
    if git(root, "status", "--porcelain"):
        raise ValueError("Start the import from a clean working tree")
    with tempfile.TemporaryDirectory() as temp:
        clone = Path(temp) / "source"
        run(["git", "clone", "--quiet", "--no-local", "--", source(repo), clone])
        tags = git(clone, "tag", "--list", tag).splitlines()
        if tags != [tag]:
            raise ValueError(f"Tag {tag} not found in {repo}")
        original = git(clone, "rev-parse", f"refs/tags/{tag}^{{commit}}")
        legacy = prepare(clone, tag, dest, key, mode)
        checkout = clone / dest if mode == "history" else clone
        # Everything that can fail runs before the monorepo changes.
        lines, entry = describe(manifest(checkout), key, dest, sdk_target, repository)
        version = Path("Sources") / entry["target"] / "Version.swift"
        if (checkout / version).exists() and f'current = "{tag}"' not in (checkout / version).read_text():
            raise ValueError(f"{version} exists without current = \"{tag}\"")
        if all((checkout / e).is_dir() for e in EXAMPLES):
            raise ValueError("Both Example/ and Examples/ exist; merge them by hand")
        root_manifest = insert(root, lines, entry["platforms"], before=kind == "core")
        imported = place(root, clone, dest, key, mode)
    package = root / dest
    removed = []
    for path in sorted({p for pattern in REMOVE for p in package.glob(pattern)}):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(path.relative_to(package).as_posix())
    examples = [e for e in EXAMPLES if (package / e).is_dir()]
    relinked = []
    if examples:
        moved = root / "Examples" / name
        moved.parent.mkdir(exist_ok=True)
        shutil.move(str(package / examples[0]), str(moved))
        names = {repository, repository.removeprefix("experimental-"), Path(source(repo)).name.removesuffix(".git")}
        relinked = relink_examples(root, moved, package / examples[0], package, names)
    if not (package / version).exists():
        (package / version).write_text(version_swift(entry["target"], tag))
    (package / "version.txt").write_text(tag + "\n")
    releases = f"https://github.com/{OWNER}/{repository}/releases"
    for file, text in (("CHANGELOG.md", f"# Changelog\n\nReleases up to {tag} are listed at {releases}.\n"),
                       ("README.md", f"# {entry['target']}\n\nImported from {repository} {tag}.\n")):
        if not (package / file).exists():
            (package / file).write_text(text)
    (root / "Package.swift").write_text(root_manifest)
    add_package(root, key, {**entry, "repository": repository})
    synced = sync(root)
    git(root, "add", "--all")
    return {"package": key, "mode": mode, "source": source(repo), "tag": tag, "sha": original, "imported": imported,
            "path": dest, "component": entry["component"], "target": entry["target"], "repository": repository,
            "sdkMinimum": entry.get("sdkMinimum"), "removed": removed,
            "examples": f"Examples/{name}" if examples else None, "relinked": relinked,
            "legacyTags": legacy, "sync": synced}


def steps(result):
    """What the developer does next (Path A)."""
    key, tag, component, path = result["package"], result["tag"], result["component"], result["path"]
    title = f"build({key}): import {Path(result['source']).name.removesuffix('.git')} {tag}"
    merge = ("merge it with a merge commit (temporary admin exception; squash loses the history)"
             if result["mode"] == "history" else "squash-merge it")
    entry = json.dumps({path: release_please_entry(component, result["target"])})
    return "\n".join([
        f"Imported {result['source']} {tag} ({result['sha']}) into {path}, staged; nothing was committed or pushed.",
        f"Review `git status`, then commit: git commit -m \"{title}\" -m \"Source: {result['source']} {tag} "
        f"({result['sha']}), {result['mode']} import\"",
        "",
        "Path A, next steps:",
        f"1. Open the import PR \"{title}\" and {merge}. Record the merge SHA.",
        f"2. Run Actions > Anchor package (package={key}, version={tag}, sha=<merge SHA>) to create the plain tag "
        f"{component}-{tag} on the merge commit (no Release).",
        f"3. Open \"build({key}): enable releases\": add {entry} to release-please-config.json and "
        f"\"{path}\": \"{tag}\" to .release-please-manifest.json; the dry run must show no {key} release; squash-merge.",
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import a package repository at a tag (Path A)")
    parser.add_argument("repo", help="repository name under rudderlabs, URL or local path")
    parser.add_argument("tag")
    parser.add_argument("name")
    parser.add_argument("--mode", choices=MODES, default="history")
    parser.add_argument("--kind", choices=KINDS, default="integration")
    args = parser.parse_args()
    print(steps(import_package(args.repo, args.tag, args.name, args.mode, kind=args.kind)))
