"""Shared process and Git helpers. No implicit remote writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r"[a-z][a-z0-9-]*\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SOURCE_NAME = "experimental-swift-monorepo"
CONSUMER_NAME = "experimental-swift-example-consumer-app"
OWNER = "rudderlabs"
RELEASE_BRANCH = "main"


def run(args, cwd=ROOT, env=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Command failed: {args[0]} {args[1:3]}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def git(repo, *args):
    return run(["git", "-C", repo, *args])


def commit(repo, message):
    paths = git(repo, "ls-files", "--modified", "--others", "--exclude-standard").splitlines()
    if paths:
        git(repo, "add", "--", *paths)
        git(repo, "diff", "--cached", "--check")
        git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def load(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def allowlist(root=ROOT):
    """Reviewed write targets (package key -> repository under OWNER). Keys without a package are reserved."""
    data = load(root / "release/allowlist.json")
    names = data.get("repositories")
    if data.get("schemaVersion") != 1 or data.get("owner") != OWNER or not isinstance(names, dict):
        raise ValueError("release/allowlist.json needs schemaVersion 1, owner " + OWNER + " and repositories")
    if not all(isinstance(k, str) and KEY.match(k) and isinstance(v, str) and REPOSITORY.match(v)
               for k, v in names.items()) or len(set(names.values())) != len(names):
        raise ValueError("Allowlist keys and repositories must be valid and unique")
    return names


def url(key, root=ROOT):
    return f"https://github.com/{OWNER}/{allowlist(root)[key]}.git"


def inventory(root=ROOT):
    """The only package list, in allowlist order. Every package must be allowlisted with its own repository."""
    packages = load(root / "release/packages.json")["packages"]
    names = allowlist(root)
    for key, package in packages.items():
        if names.get(key) != package.get("repository"):
            raise ValueError(f"Package is not allowlisted with its repository: {key}")
    return {key: packages[key] for key in names if key in packages}


def file_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()
            and not {".git", ".build", ".swiftpm", "__pycache__"}.intersection(p.relative_to(root).parts)
            and p.name != ".publication.json"}


def anonymous_env():
    env = {k: v for k, v in os.environ.items()
           if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GIT_ASKPASS", "SSH_ASKPASS")
           and not k.startswith("GIT_CONFIG")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="1",
               GIT_CONFIG_KEY_0="credential.helper", GIT_CONFIG_VALUE_0="")
    return env


def swift_options(state):
    return ["--cache-path", state / "cache", "--config-path", state / "config",
            "--security-path", state / "security", "--scratch-path", state / "build",
            "--disable-dependency-cache", "--disable-keychain", "--disable-netrc"]


def mirrors(package, mirror_root):
    if mirror_root:
        for key, name in allowlist().items():
            run(["swift", "package", "config", "set-mirror", "--original", url(key),
                 "--mirror", (mirror_root / (name + ".git")).as_uri()], cwd=package)
