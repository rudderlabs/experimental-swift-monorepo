"""Create a new integration (Path B) and the shared root-manifest helpers used by the import command.

`make new-integration NAME=<Name>` writes the folder, source and test templates, version files, the
package list entry and the Release Please config entry, inserts root Package.swift lines at the
`// @integrations-*` anchors, then runs the `make sync` steps. It never commits or pushes.
"""
import argparse
import json
from pathlib import Path
import re

from common import ROOT, allowlist, inventory, load, write_json
from dependency_policy import sync_inventory
from generate_github import write as write_generated
from project import PLATFORM, SEMVER
from release_plan import shared_markers

NAME = re.compile(r"[A-Z][A-Za-z0-9]*\Z")
SECTIONS = ("products", "dependencies", "targets")
# A new package has no release: Release Please replaces this placeholder with 1.0.0 in its first release PR.
PLACEHOLDER = "0.0.0"
DEFAULT_SDK_MINIMUM = "1.4.1"
TOOLS_VERSION = "5.9"
ROOT_MANIFEST = """// swift-tools-version: 5.9
import PackageDescription

// Development manifest for every package in this repository. Release exports generate their own manifests.
// make new-integration / make import-integration add lines at the end of each `// @integrations-*` block;
// the core SDK sits above the anchors.
let package = Package(
    name: "SwiftPublicationExperiment",
    platforms: [.iOS(.v15)],
    products: [
        // @integrations-products
    ],
    dependencies: [
        // @integrations-dependencies
    ],
    targets: [
        // @integrations-targets
    ]
)
"""
PACKAGE_URL = re.compile(r'\.package\(\s*url:\s*"([^"]+)"')
ROOT_PLATFORMS = re.compile(r"^(\s*platforms:\s*\[)([^\]\n]*)(\],?)$", re.M)
ROOT_PLATFORM = re.compile(r"\.(iOS|macOS|macCatalyst|tvOS|watchOS|visionOS)\(\.v([0-9]+)(?:_([0-9]+))?\)")


def q(value):
    # JSON strings are valid Swift string literals for these names and paths.
    return json.dumps(value)


def identity(location):
    """SwiftPM's identity for a Git URL: the last path component, lowercased, without `.git`."""
    name = location.rstrip("/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".git") else name


def target_lines(name, dependencies, path, test=False, resources=(), exclude=()):
    call = ".testTarget(" if test else ".target("
    parts = [f"name: {q(name)}", f"dependencies: [{', '.join(dependencies)}]", f"path: {q(path)}"]
    if exclude:
        parts.append(f"exclude: [{', '.join(q(e) for e in exclude)}]")
    if resources:
        parts.append(f"resources: [{', '.join(resources)}]")
    pad = " " * len(call)
    return [call + parts[0] + ","] + [pad + p + "," for p in parts[1:-1]] + [pad + parts[-1] + "),"]


def product_line(target):
    return [f".library(name: {q(target)}, targets: [{q(target)}]),"]


def root_manifest(root=ROOT):
    """The root manifest text; a repository without one starts from the anchored template."""
    path = root / "Package.swift"
    return path.read_text() if path.exists() else ROOT_MANIFEST


def code_part(line):
    """The line without a trailing `//` comment; a `//` inside a URL string is kept."""
    code = line.rstrip()
    comment = code.find("//", code.rfind('"') + 1)
    return code[:comment].rstrip() if comment >= 0 else code


def platform_key(name, major, minor):
    return name, int(major), int(minor or 0)


def merge_platforms(text, platforms):
    """Raise the root `platforms:` to cover a new package (the root needs the highest minimum per platform)."""
    match = ROOT_PLATFORMS.search(text)
    if not match:
        raise ValueError("Package.swift needs a one-line `platforms: [...]` list")
    current = {m[1]: platform_key(*m.groups()) for m in ROOT_PLATFORM.finditer(match[2])}
    for value in platforms:
        found = PLATFORM.fullmatch(value)
        if not found:
            raise ValueError(f"Invalid platform {value!r} (e.g. \"iOS 15\")")
        new = platform_key(*found.groups())
        if new[0] not in current or new[1:] > current[new[0]][1:]:
            current[new[0]] = new
    order = ["iOS", "macOS", "macCatalyst", "tvOS", "watchOS", "visionOS"]
    rendered = [f".{n}(.v{major}{'_' + str(minor) if minor else ''})"
                for n, major, minor in sorted(current.values(), key=lambda p: order.index(p[0]))]
    return text[:match.start(2)] + ", ".join(rendered) + text[match.end(2):]


def insert(root, lines, platforms=(), before=False):
    """Root Package.swift text with lines added at the end of each `// @integrations-<section>` block,
    or just above the anchors (core SDK). A vendor package the root already has keeps its requirement."""
    text = merge_platforms(root_manifest(root), platforms)
    existing = {identity(u) for u in PACKAGE_URL.findall(text)}
    lines = {**lines, "dependencies": [line for line in lines.get("dependencies", [])
                                       if identity(PACKAGE_URL.search(line)[1]) not in existing]}
    for name in re.findall(r'name: "([^"]+)"', "\n".join(lines.get("products", []) + lines.get("targets", []))):
        if re.search(rf'\.(?:library|target|testTarget)\(\s*name:\s*"{re.escape(name)}"', text):
            raise ValueError(f"Package.swift already declares {name}")
    rows = text.split("\n")
    for section in SECTIONS:
        new = lines.get(section)
        if not new:
            continue
        marker = f"// @integrations-{section}"
        found = [i for i, row in enumerate(rows) if row.strip() == marker]
        if len(found) != 1:
            raise ValueError(f"Package.swift needs exactly one `{marker}` anchor line")
        anchor = found[0]
        indent = rows[anchor][:len(rows[anchor]) - len(rows[anchor].lstrip())]
        at = anchor if before else next((i for i in range(anchor + 1, len(rows))
                                         if rows[i].strip().startswith("]")), None)
        if at is None:
            raise ValueError(f"No closing `]` after `{marker}` in Package.swift")
        previous = max((i for i in range(at) if rows[i].strip() and not rows[i].strip().startswith("//")),
                       default=None)
        # The element above the new lines needs a separating comma.
        code = code_part(rows[previous]) if previous is not None else ""
        if code and not code.endswith((",", "[", "(")):
            rows[previous] = code + "," + rows[previous].rstrip()[len(code):]
        rows[at:at] = [indent + row for row in new]
    return "\n".join(rows)


def add_package(root, key, entry):
    path = root / "release/packages.json"
    config = load(path)
    if key in config["packages"] or any(p.get("path") == entry["path"] for p in config["packages"].values()):
        raise ValueError(f"release/packages.json already has {key} or {entry['path']}")
    config["packages"][key] = entry
    write_json(path, config)


def release_please_entry(component, target):
    return {"component": component, "package-name": target,
            "extra-files": [{"type": "generic", "path": f"Sources/{target}/Version.swift"}]}


def add_release_please(root, path, component, target):
    """Path B only. Release Please creates the manifest entry with the first release (1.0.0)."""
    config_path = root / "release-please-config.json"
    config = load(config_path)
    config.setdefault("packages", {})[path] = release_please_entry(component, target)
    # Keep the reviewed key order of this file.
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def sync(root=ROOT):
    """The `make sync` steps: vendor metadata and markers, shared-source markers, generated GitHub files."""
    return {"dependencies": sync_inventory(root), "shared": shared_markers(root),
            "generated": write_generated(root)}


def allowlisted(root, key):
    names = allowlist(root)
    if key not in names:
        raise ValueError(f"add {key} to release/allowlist.json first (sdk_team approval)")
    return names[key]


def sdk_minimum(root, packages):
    """The SDK's current release from the Release Please manifest, or the default before it has one."""
    return load(root / ".release-please-manifest.json").get(packages["sdk"]["path"], DEFAULT_SDK_MINIMUM)


def version_swift(target, version):
    return ("// Managed by Release Please. Do not edit by hand.\n"
            f"enum {target}Version {{\n"
            f'    static let current = "{version}" // x-release-please-version\n'
            "}\n")


def templates(name, target, sdk_target):
    return {
        f"Sources/{target}/{name}Integration.swift": f"""import Foundation
import {sdk_target}

/// {name} device-mode integration. Initialize the vendor SDK in `create(destinationConfig:)`.
public class {name}Integration: IntegrationPlugin, StandardIntegration {{
    public var pluginType: PluginType = .terminal
    public var analytics: Analytics?
    // Must equal the destination name in the RudderStack dashboard.
    public var key: String = "{name}"
    private var destination: Any?

    public init() {{}}

    public func create(destinationConfig: [String: Any]) throws {{
        // Read the destination settings and create the vendor SDK instance here.
    }}

    public func getDestinationInstance() -> Any? {{
        return destination
    }}
}}
""",
        f"Sources/{target}/Version.swift": version_swift(target, PLACEHOLDER),
        f"Tests/{target}Tests/{name}IntegrationTests.swift": f"""import Testing
import {sdk_target}
@testable import {target}

@Suite("{target} Tests")
struct {name}IntegrationTests {{
    @Test("uses the dashboard destination name")
    func destinationKey() {{
        #expect({name}Integration().key == "{name}")
    }}
}}
""",
        "version.txt": PLACEHOLDER + "\n",
        "CHANGELOG.md": "# Changelog\n",
        "README.md": f"# {target}\n\nRudderStack Swift SDK device-mode integration for {name}.\n"
                     "Source of truth: the monorepo. Do not edit generated publication repositories.\n",
    }


def scaffold(name, root=ROOT, platforms=("iOS 15",), minimum=None, vendor_url=None, vendor_products=(),
             vendor_from=None):
    if not NAME.fullmatch(name):
        raise ValueError("NAME must be PascalCase, e.g. Braze")
    key, target, path = name.lower(), f"RudderIntegration{name}", f"Integrations/{name}"
    repository = allowlisted(root, key)
    packages = inventory(root)
    if "sdk" not in packages:
        raise ValueError("release/packages.json has no sdk package; import the core SDK first")
    if key in packages or (root / path).exists() or any(p["path"] == path for p in packages.values()):
        raise ValueError(f"{key} already exists")
    minimum = minimum or sdk_minimum(root, packages)
    if not SEMVER.fullmatch(minimum) or (vendor_from and not SEMVER.fullmatch(vendor_from)):
        raise ValueError("Versions must be X.Y.Z")
    if bool(vendor_url) != bool(vendor_products) or bool(vendor_url) != bool(vendor_from):
        raise ValueError("Give VENDOR_URL, VENDOR_PRODUCTS and VENDOR_FROM together")
    sdk_target = packages["sdk"]["target"]
    dependencies = [q(sdk_target)] + [f".product(name: {q(p)}, package: {q(identity(vendor_url))})"
                                      for p in vendor_products]
    lines = {"products": product_line(target),
             "dependencies": [f".package(url: {q(vendor_url)}, from: {q(vendor_from)}),"] if vendor_url else [],
             "targets": target_lines(target, dependencies, f"{path}/Sources/{target}")
             + target_lines(f"{target}Tests", [q(target)], f"{path}/Tests/{target}Tests", test=True)}
    text = insert(root, lines, platforms)
    (root / "Package.swift").write_text(text)
    for relative, text in templates(name, target, sdk_target).items():
        (root / path / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / path / relative).write_text(text)
    add_package(root, key, {"path": path, "target": target, "component": f"integration-{key}",
                            "repository": repository, "platforms": list(platforms), "toolsVersion": TOOLS_VERSION,
                            "policies": {sdk_target: {"mode": "external", "package": "sdk"}},
                            "sdkMinimum": minimum})
    add_release_please(root, path, f"integration-{key}", target)
    return {"package": key, "path": path, "target": target, "sdkMinimum": minimum, "sync": sync(root)}


def items(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Integrations/<Name> with its inventory and Release Please entries")
    parser.add_argument("name")
    parser.add_argument("--platforms", default="iOS 15", help='comma-separated, e.g. "iOS 15,tvOS 15"')
    parser.add_argument("--sdk-minimum", help="lowest core SDK version (default: the SDK's current version)")
    parser.add_argument("--vendor-url")
    parser.add_argument("--vendor-products", help="comma-separated vendor products")
    parser.add_argument("--vendor-from", help="vendor version, used as from: (up to next major)")
    args = parser.parse_args()
    result = scaffold(args.name, platforms=items(args.platforms), minimum=args.sdk_minimum,
                      vendor_url=args.vendor_url, vendor_products=items(args.vendor_products),
                      vendor_from=args.vendor_from)
    print(json.dumps(result, indent=2))
    print(f"Next: implement {result['path']}, run `make check test`, and open "
          f"`feat({result['package']}): add {args.name} integration` (it releases 1.0.0).")
