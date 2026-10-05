"""Export the explicit demo subset of a SwiftPM target graph."""
import argparse
import json
from pathlib import Path
import re
import shutil

from common import ROOT, file_hashes, git, inventory, load, run, url, write_json
from dependency_policy import markers as dependency_markers

SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


def graph(root):
    data = json.loads(run(["swift", "package", "describe", "--type", "json"], cwd=root))
    return {t["name"]: t for t in data["targets"]}


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
    dependency_markers(root, check=True)
    if git(root, "status", "--porcelain"):
        raise ValueError("Commit the source before exporting an auditable release")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Export destination must be empty")
    targets = graph(root)
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
            declared = package.get("resources", [])
            actual = sorted(Path(r["path"]).name for r in entry.get("resources", []))
            if sorted(Path(r).name for r in declared) != actual:
                raise ValueError("Resources differ from the explicit export inventory")
            for relative in declared:
                source = root / entry["path"] / relative
                output = Path("Sources") / target / relative
                (destination / output).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination / output)
                resources.append(f'.copy("{relative}")')
                copied.append({"source": source.relative_to(root).as_posix(), "output": output.as_posix()})
    for vendor in package.get("vendors", []):
        external.append(f'.package(url: "{vendor["url"]}", exact: "{vendor["version"]}")')
        target_deps.append(f'.product(name: "{vendor["product"]}", package: "{vendor["identity"]}")')
    resource_arg = ", resources: [" + ", ".join(resources) + "]" if resources else ""
    manifest = f'''// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "{target}",
    platforms: [.iOS(.v15), .macOS(.v12)],
    products: [.library(name: "{target}", targets: ["{target}"])],
    dependencies: [{", ".join(external)}],
    targets: [.target(name: "{target}", dependencies: [{", ".join(target_deps)}]{resource_arg})]
)
'''
    if '.package(path:' in manifest or "experimental-swift-monorepo" in manifest:
        raise ValueError("Generated package depends on private source")
    (destination / "Package.swift").write_text(manifest)
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
