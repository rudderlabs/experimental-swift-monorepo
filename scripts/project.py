"""Export the explicit demo subset of a SwiftPM target graph."""
import argparse
import json
from pathlib import Path
import re
import shutil

from common import ROOT, OWNER, SOURCE_NAME, anonymous_env, file_hashes, git, inventory, load, run, url, write_json
from dependency_policy import manifest, markers as dependency_markers

SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
PLATFORM = re.compile(r"(iOS|macOS|macCatalyst|tvOS|watchOS|visionOS) ([1-9][0-9]*)(?:\.([0-9]+))?\Z")
TOOLS = re.compile(r"[1-9][0-9]*\.[0-9]+(?:\.[0-9]+)?\Z")
RESOURCE_RULES = ({"process": {}}, {"copy": {}})
LEXEME = re.compile(r'//[^\n]*|/\*|(#*)("""|")')
BLOCK = re.compile(r"/\*|\*/")
# `open` is contextual, so it counts only before another modifier or a declaration keyword.
WIDE_ACCESS = re.compile(r"(?<![\w`.])(?:public\b|open(?:\s*\(set\))?(?=\s+(?:@|(?:class|func|var|let|subscript|"
                         r"static|final|override|required|convenience|dynamic|lazy|weak|unowned|nonisolated|"
                         r"public|open|package|internal)\b)))")
IMPORT_KIND = r"(?:(?:typealias|struct|class|enum|protocol|let|var|func)[ \t]+)?"
TRANSFORMS = ("copy", "vendored-strip-import", "generated")


def code_only(text):
    """Blank comments and string literals, keeping line numbers."""
    parts, i = [], 0
    while match := LEXEME.search(text, i):
        parts.append(text[i:match.start()])
        if match[0] == "/*":
            depth, end = 1, match.end()
            while depth and (inner := BLOCK.search(text, end)):
                depth, end = depth + (1 if inner[0] == "/*" else -1), inner.end()
            end = len(text) if depth else end
        elif match[0].startswith("//"):
            end = match.end()
        else:
            hashes, quote = match[1], match[2]
            close = re.compile(rf"(?:\\{hashes}[\s\S]|[\s\S])*?{quote}{hashes}").match(text, match.end())
            end = close.end() if close else len(text)
        parts.append(re.sub(r"[^\n]", " ", text[match.start():end]))
        i = end
    return "".join(parts) + text[i:]


def wide_access(text):
    """Line numbers of `public`/`open` modifiers outside comments and strings."""
    code = code_only(text)
    return [code.count("\n", 0, m.start()) + 1 for m in WIDE_ACCESS.finditer(code)]


def strip_imports(content, modules):
    """Drop imports of vendored modules, whatever their attributes, kind, or line ending."""
    for module in modules:
        content = re.sub(rf"^[ \t]*(?:@\w+(?:\([^)\r\n]*\))?[ \t]+)*(?:(?:public|package|internal)[ \t]+)?"
                         rf"import[ \t]+{IMPORT_KIND}{re.escape(module)}(?:\.[\w.]+)?[ \t]*(?://[^\r\n]*)?"
                         r"(?:\r?\n|\Z)", "", content, flags=re.M)
    return content


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


def template(name, key):
    """Generated publication files come from release/templates in the trusted checkout, like the exporter."""
    return (ROOT / "release/templates" / name).read_text().format(
        package=key, owner=OWNER, source=SOURCE_NAME,
        issues=f"https://github.com/{OWNER}/{SOURCE_NAME}/issues/new/choose")


def export(key, version, destination, root=ROOT, preview=False):
    """Export one package. `preview` (PR CI) allows a package that has no Release Please entry yet."""
    if not SEMVER.fullmatch(version):
        raise ValueError("The experiment accepts stable X.Y.Z versions only")
    packages = inventory(root)
    package = packages[key]
    if version != (root / package["path"] / "version.txt").read_text().strip():
        raise ValueError("Requested version differs from version.txt")
    if not preview and load(root / ".release-please-manifest.json").get(package["path"]) != version:
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
            external.append(f'.package(url: "{url(dependency["package"], root)}", from: "{package["sdkMinimum"]}")')
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
            original = source.read_bytes().decode()
            if name != target and wide_access(original):
                raise ValueError(f"Vendored code must use package access, not public/open: {relative}")
            content = strip_imports(original, [n for n in selected if policies.get(n, {}).get("mode") == "vendor"])
            # Shared declarations use `package` access. Each integration owns its copy.
            (destination / output).parent.mkdir(parents=True, exist_ok=True)
            (destination / output).write_bytes(content.encode())
            # Reverse sync copies a `copy` file back as is; vendored or stripped files need the transform undone.
            transform = "copy" if name == target and content == original else "vendored-strip-import"
            copied.append({"source": source.relative_to(root).as_posix(), "output": output.as_posix(),
                           "transform": transform})
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
                    copied.append({"source": item.relative_to(root).as_posix(), "output": output.as_posix(),
                                   "transform": "copy"})
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
    readme = root / package["path"] / "README.md"
    (destination / "README.md").write_text(readme.read_text().rstrip("\n") + "\n" + template("README-block.md", key))
    for source, name in ((root / package["path"] / "CHANGELOG.md", "CHANGELOG.md"), (root / "LICENSE", "LICENSE")):
        shutil.copyfile(source, destination / name)
        copied.append({"source": source.relative_to(root).as_posix(), "output": name, "transform": "copy"})
    (destination / "VERSION").write_text(version + "\n")
    (destination / ".gitignore").write_text(".build/\n.swiftpm/\nPackage.resolved\n.DS_Store\n")
    # CODEOWNERS keeps "Require review from Code Owners" working after takeover. It is not a workflow file.
    (destination / "CONTRIBUTING.md").write_text(template("CONTRIBUTING.md", key))
    (destination / ".github").mkdir()
    (destination / ".github/CODEOWNERS").write_text(template("CODEOWNERS", key))
    copied.append({"source": readme.relative_to(root).as_posix(), "output": "README.md", "transform": "generated"})
    listed = {c["output"] for c in copied}
    copied += [{"source": None, "output": path, "transform": "generated"}
               for path in sorted(file_hashes(destination)) if path not in listed]
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
