"""Export the explicit demo subset of a SwiftPM target graph."""
import argparse
import json
from pathlib import Path
import re
import shutil

from common import ROOT, anonymous_env, file_hashes, git, inventory, load, run, url, write_json
from dependency_policy import manifest, markers as dependency_markers

SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
PLATFORM = re.compile(r"(iOS|macOS|macCatalyst|tvOS|watchOS|visionOS) ([1-9][0-9]*)(?:\.([0-9]+))?\Z")
TOOLS = re.compile(r"[1-9][0-9]*\.[0-9]+(?:\.[0-9]+)?\Z")
RESOURCE_RULES = ({"process": {}}, {"copy": {}})


def graph(root):
    data = json.loads(run(["swift", "package", "describe", "--type", "json"], cwd=root, env=anonymous_env()))
    return {t["name"]: t for t in data["targets"]}


def platforms(package):
    """Render the package's own `platforms` and `toolsVersion`; the root manifest is never copied."""
    values, tools = package.get("platforms", []), package.get("toolsVersion", "")
    matches = [PLATFORM.fullmatch(value) for value in values]
    if not values or not all(matches) or not TOOLS.fullmatch(tools):
        raise ValueError("Each package needs explicit platforms (e.g. \"iOS 15\") and toolsVersion (e.g. \"5.9\")")
    if len({m[1] for m in matches}) != len(matches):
        raise ValueError("Duplicate platform in package inventory")
    return tools, [f".{m[1]}(.v{m[2]}{'_' + m[3] if m[3] and m[3] != '0' else ''})" for m in matches]


def requirement(value):
    kind, lower, upper = value["kind"], value["lower"], value["upper"]
    forms = {"exact": f'exact: "{lower}"', "upToNextMajor": f'.upToNextMajor(from: "{lower}")',
             "upToNextMinor": f'.upToNextMinor(from: "{lower}")', "range": f'"{lower}"..<"{upper}"'}
    if kind not in forms:
        raise ValueError(f"Unsupported vendor requirement kind: {kind}")
    return forms[kind]


def closure(name, targets, policies):
    result = []
    def visit(current, stack):
        if current in stack:
            raise ValueError("Target dependency cycle")
        if current in result:
            return
        if current != name:
            mode = policies.get(current, {}).get("mode")
            if mode not in ("vendor", "external"):
                raise ValueError(f"Missing or rejected publication policy: {current}")
            if mode == "external":
                result.append(current)
                return
        for dep in targets[current].get("target_dependencies", []):
            visit(dep, stack + [current])
        result.append(current)
    visit(name, [])
    if set(policies) != set(result) - {name}:
        raise ValueError("Publication policies differ from the SwiftPM graph")
    return result


def export(key, version, destination, root=ROOT):
    if not SEMVER.fullmatch(version):
        raise ValueError("The experiment accepts stable X.Y.Z versions only")
    packages = inventory(root)
    package = packages[key]
    if version != (root / package["path"] / "version.txt").read_text().strip():
        raise ValueError("Requested version differs from version.txt")
    if load(root / ".release-please-manifest.json")[package["path"]] != version:
        raise ValueError("Release Please manifest version differs")
    constants = (root / package["path"] / "Sources" / package["target"] / "Version.swift").read_text()
    if f'current = "{version}"' not in constants:
        raise ValueError("Swift runtime version differs from release intent")
    tools, platform_args = platforms(package)
    data = manifest(root)
    dependency_markers(root, check=True, data=data)
    if git(root, "status", "--porcelain"):
        raise ValueError("Commit the source before exporting an auditable release")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Export destination must be empty")
    targets = graph(root)
    declared_targets = {t["name"]: t for t in data["targets"]}
    target = package["target"]
    policies = package["policies"]
    selected = closure(target, targets, policies)
    destination.mkdir(parents=True, exist_ok=True)
    external, target_deps, copied = [], [], []
    resources = []
    for name in selected:
        mode = policies.get(name, {}).get("mode", "source")
        if mode == "external":
            dependency = policies[name]
            external.append(f'.package(url: "{url(dependency["package"])}", from: "{package["sdkMinimum"]}")')
            target_deps.append(f'.product(name: "{name}", package: "{packages[dependency["package"]]["repository"]}")')
            continue
        entry = targets[name]
        if entry.get("type") != "library" or entry.get("module_type") != "SwiftTarget":
            raise ValueError(f"Unsupported target shape: {name}")
        vendors = entry.get("product_dependencies", [])
        if set(vendors) != set(package.get("vendorProducts", [])) and name == target:
            raise ValueError("External vendor products differ from inventory")
        if name != target and (entry.get("resources") or vendors):
            raise ValueError("Vendored demo targets must contain Swift source only")
        for relative in entry.get("sources", []):
            source = root / entry["path"] / relative
            if source.suffix != ".swift" or not source.resolve().is_relative_to(root.resolve()):
                raise ValueError("Unsupported or escaping source path")
            output = Path("Sources") / target
            if name != target:
                output /= Path("Vendored") / name
            output /= relative
            content = source.read_text()
            for shared in selected:
                if policies.get(shared, {}).get("mode") == "vendor":
                    content = re.sub(rf"^import {re.escape(shared)}\n", "", content, flags=re.M)
            # Shared declarations have module-local visibility. Each integration owns its copy.
            (destination / output).parent.mkdir(parents=True, exist_ok=True)
            (destination / output).write_text(content)
            copied.append({"source": source.relative_to(root).as_posix(), "output": output.as_posix()})
        if name == target:
            # Rules and folder paths come from dump-package; describe expands folders into files.
            rules = {Path(r["path"]).as_posix(): r["rule"] for r in declared_targets[name].get("resources") or []}
            declared = [Path(r).as_posix() for r in package.get("resources", [])]
            if sorted(declared) != sorted(rules):
                raise ValueError("Resources differ from the explicit export inventory")
            base = root / entry["path"]
            for relative in declared:
                if rules[relative] not in RESOURCE_RULES:
                    raise ValueError(f"Unsupported resource rule: {relative}")
                source = base / relative
                if not source.resolve().is_relative_to(base.resolve()):
                    raise ValueError("Unsupported or escaping resource path")
                # A folder resource is copied file by file so provenance lists every output.
                for item in sorted(p for p in source.rglob("*") if p.is_file()) if source.is_dir() else [source]:
                    output = Path("Sources") / target / item.relative_to(base)
                    (destination / output).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, destination / output)
                    copied.append({"source": item.relative_to(root).as_posix(), "output": output.as_posix()})
                resources.append(f'.{next(iter(rules[relative]))}("{relative}")')
    # One package line per vendor identity; its products share that requirement.
    vendors = {}
    for vendor in package.get("vendors", []):
        vendors.setdefault(vendor["identity"], []).append(vendor)
    for identity, products in sorted(vendors.items()):
        external.append(f'.package(url: "{products[0]["url"]}", {requirement(products[0]["requirement"])})')
        target_deps += [f'.product(name: "{v["product"]}", package: "{identity}")' for v in products]
    resource_arg = ", resources: [" + ", ".join(resources) + "]" if resources else ""
    text = f'''// swift-tools-version: {tools}
import PackageDescription
let package = Package(
    name: "{target}",
    platforms: [{", ".join(platform_args)}],
    products: [.library(name: "{target}", targets: ["{target}"])],
    dependencies: [{", ".join(external)}],
    targets: [.target(name: "{target}", dependencies: [{", ".join(target_deps)}]{resource_arg})]
)
'''
    if '.package(path:' in text or "experimental-swift-monorepo" in text:
        raise ValueError("Generated package depends on private source")
    (destination / "Package.swift").write_text(text)
    for name in ("README.md", "CHANGELOG.md"):
        shutil.copyfile(root / package["path"] / name, destination / name)
    shutil.copyfile(root / "LICENSE", destination / "LICENSE")
    (destination / "VERSION").write_text(version + "\n")
    (destination / ".gitignore").write_text(".build/\n.swiftpm/\nPackage.resolved\n.DS_Store\n")
    provenance = {"schemaVersion": 1, "package": key, "version": version,
                  "sourceCommit": git(root, "rev-parse", "HEAD"),
                  "sourceRepository": "rudderlabs/experimental-swift-monorepo",
                  "targetClosure": selected, "policies": policies, "copiedFiles": copied,
                  "fileHashes": file_hashes(destination)}
    write_json(destination / ".publication.json", provenance)
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", choices=list(inventory()))
    parser.add_argument("version")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.package, args.version, args.destination), indent=2))
