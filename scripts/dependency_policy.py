"""Validate canonical vendor requirements and reviewed per-package release markers.

This fixture supports exact Git vendor requirements only. Other requirement
shapes fail explicitly; production range/binary coverage is a separate gate.
"""
import argparse
import json

from common import ROOT, inventory, run, write_json


def manifest(root=ROOT):
    return json.loads(run(["swift", "package", "dump-package"], cwd=root))


def requirements(data):
    result = {}
    for dependency in data["dependencies"]:
        sources = dependency.get("sourceControl", [])
        if len(sources) != 1:
            raise ValueError("The fixture supports Git vendor dependencies only")
        source = sources[0]
        exact = source["requirement"].get("exact", [])
        remote = source["location"].get("remote", [])
        if len(exact) != 1 or len(remote) != 1:
            raise ValueError("The fixture supports exact public Git vendor requirements only")
        identity = source["identity"]
        if identity in result:
            raise ValueError("Duplicate canonical vendor identity")
        result[identity] = {"url": remote[0]["urlString"], "version": exact[0]}
    return result


def package_requirements(data, packages):
    canonical = requirements(data)
    targets = {target["name"]: target for target in data["targets"]}
    result = {}
    for key, package in packages.items():
        products = {}
        visited = set()

        def visit(name):
            if name in visited:
                return
            visited.add(name)
            for dependency in targets[name]["dependencies"]:
                if "product" in dependency:
                    product, identity = dependency["product"][:2]
                    if identity not in canonical:
                        raise ValueError("Vendor product has no canonical Git requirement")
                    products[(product, identity)] = {"product": product, "identity": identity,
                                                     **canonical[identity]}
                else:
                    target = dependency.get("target", dependency.get("byName", []))
                    if not target or target[0] not in targets:
                        raise ValueError("Unclassified target dependency")
                    if package.get("policies", {}).get(target[0], {}).get("mode") != "external":
                        visit(target[0])

        visit(package["target"])
        result[key] = {"schemaVersion": 1,
                       "vendors": [products[p] for p in sorted(products)],
                       "sdkMinimum": package.get("sdkMinimum")}
    return result


def check_inventory(expected, packages):
    for key, value in expected.items():
        actual = sorted(packages[key].get("vendors", []), key=lambda v: (v["product"], v["identity"]))
        if actual != value["vendors"]:
            raise ValueError(f"Canonical manifest and export vendor metadata differ: {key}")
        if sorted(packages[key].get("vendorProducts", [])) != sorted(v["product"] for v in actual):
            raise ValueError(f"Vendor product inventory differs: {key}")


def markers(root=ROOT, check=False, data=None):
    packages = inventory(root)
    if not packages:
        return []
    expected = package_requirements(data or manifest(root), packages)
    check_inventory(expected, packages)
    changed = []
    for key, value in expected.items():
        path = root / packages[key]["path"] / "dependency-requirements.json"
        if not path.exists() or json.loads(path.read_text()) != value:
            changed.append(key)
            if not check:
                write_json(path, value)
    if check and changed:
        raise ValueError("Run dependency_policy.py sync and include reviewed release markers: " + ", ".join(changed))
    return changed


def sync_inventory(root=ROOT):
    """Copy canonical requirements into export metadata; never change Package.swift."""
    path = root / "release/packages.json"
    config = json.loads(path.read_text())
    if not inventory(root):
        return []
    data = manifest(root)
    expected = package_requirements(data, inventory(root))
    for key, value in expected.items():
        package = config["packages"][key]
        if value["vendors"] or "vendors" in package:
            package["vendors"] = value["vendors"]
            package["vendorProducts"] = [v["product"] for v in value["vendors"]]
    write_json(path, config)
    return markers(root, data=data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "sync"])
    args = parser.parse_args()
    print(json.dumps(markers(check=True) if args.command == "check" else sync_inventory()))
