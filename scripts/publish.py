"""Validate, publish, and recover immutable standalone package releases."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile

from common import (ROOT, NAMES, OWNER, RELEASE_BRANCH, anonymous_env, commit, file_hashes, git,
                    inventory, load, mirrors, run, swift_options, url, write_json)
from project import export
from reviewed_publication import reviewed_commit


@contextlib.contextmanager
def publication_lock(mirror_root, key):
    # GitHub uses the equivalent per-package workflow concurrency group.
    if mirror_root is None:
        yield
        return
    lock = mirror_root / (NAMES[key] + ".lock")
    with lock.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("A publication for this repository is already running") from error
        yield


def verify_tree(repo):
    provenance = load(repo / ".publication.json")
    if provenance["fileHashes"] != file_hashes(repo):
        raise ValueError("Publication repository contains manual drift")
    return provenance


def tag_exists(repo, version):
    return f"refs/tags/{version}" in git(repo, "for-each-ref", "--format=%(refname)", "refs/tags").splitlines()


def validate(stage, state, mirror_root):
    mirrors(stage, mirror_root)
    output = run(["swift", "build", *swift_options(state)], cwd=stage, env=anonymous_env())
    # SwiftPM configuration and the resolved file must never enter the publication tree.
    shutil.rmtree(stage / ".swiftpm", ignore_errors=True)
    (stage / "Package.resolved").unlink(missing_ok=True)
    return output


def ensure_release(key, version, sha, provenance, mirror_root):
    body = f"Temporary unsupported experiment.\n\nSource: {provenance['sourceCommit']}\nPublication: {sha}\n"
    if mirror_root:
        record = mirror_root.parent / "modeled-github-releases" / NAMES[key] / (version + ".json")
        value = {"tag": version, "commit": sha, "body": body, "kind": "local-model-not-github"}
        if record.exists() and load(record) != value:
            raise ValueError("Modeled release metadata conflicts")
        write_json(record, value)
        return str(record)
    repo = f"{OWNER}/{NAMES[key]}"
    # Listing distinguishes confirmed absence from API, network, and authentication errors.
    records = json.loads(run(["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases"]))
    found = [r for page in records for r in page if r["tag_name"] == version]
    if found:
        if len(found) != 1 or found[0]["body"] != body or found[0]["draft"]:
            raise ValueError("Existing GitHub Release metadata differs")
        return found[0]["html_url"]
    with tempfile.TemporaryDirectory() as temp:
        notes = Path(temp) / "release.md"
        notes.write_text(body)
        return run(["gh", "release", "create", version, "--repo", repo, "--verify-tag",
                    "--title", f"Experimental {version}", "--notes-file", notes])


def publish(key, version, mirror_root=None, root=ROOT, interrupt=None):
    if key not in NAMES or inventory(root)[key]["repository"] != NAMES[key]:
        raise ValueError("Destination is outside the fixed experimental inventory")
    if mirror_root:
        mirror_root = mirror_root.resolve()
        remote = mirror_root / (NAMES[key] + ".git")
        if not remote.is_dir() or git(remote, "rev-parse", "--is-bare-repository") != "true":
            raise ValueError("Local publication repository is missing or is not bare")
    else:
        if os.environ.get("ENABLE_EXPERIMENTAL_PUBLICATION") != "true":
            raise ValueError("Remote publication is disabled")
        remote = url(key)
        details = json.loads(run(["gh", "repo", "view", f"{OWNER}/{NAMES[key]}",
                                  "--json", "nameWithOwner,visibility,isArchived"]))
        if details != {"nameWithOwner": f"{OWNER}/{NAMES[key]}", "visibility": "PUBLIC", "isArchived": False}:
            raise ValueError("Experimental repository identity, visibility, or archive state differs")
    with publication_lock(mirror_root, key), tempfile.TemporaryDirectory(prefix=f"publish-{key}-") as temp:
        temp = Path(temp)
        stage, repo = temp / "export", temp / "publication"
        expected = export(key, version, stage, root)
        run(["git", "clone", "--no-checkout", remote, repo])
        existing = tag_exists(repo, version)
        publication_ref = f"refs/remotes/origin/{RELEASE_BRANCH}"
        has_branch = publication_ref in git(
            repo, "for-each-ref", "--format=%(refname)", publication_ref
        ).splitlines()
        if has_branch:
            git(repo, "checkout", "-B", RELEASE_BRANCH, publication_ref)
            verify_tree(repo)
        if existing:
            git(repo, "checkout", "--detach", f"refs/tags/{version}")
            if verify_tree(repo) != expected:
                raise ValueError("Existing tag conflicts with source, version, policy, or file hashes")
            sha = git(repo, "rev-parse", "HEAD")
            if mirror_root is None:
                git(repo, "merge-base", "--is-ancestor", sha, "origin/main")
            validate(stage, temp / "validation", mirror_root)
        elif mirror_root is None:
            if not has_branch:
                raise ValueError("Reviewed publication requires a seeded main branch")
            # Dependency readiness is a waiting state, not permission to publish a broken package.
            minimum = inventory(root)[key].get("sdkMinimum")
            if minimum and not run(["git", "ls-remote", url("sdk"), f"refs/tags/{minimum}"]):
                return {"status": "awaiting_dependency", "package": key, "version": version,
                        "sourceCommit": expected["sourceCommit"], "dependency": "sdk", "minimum": minimum}
            validate(stage, temp / "validation", mirror_root)
            sha, pr = reviewed_commit(key, version, repo, stage, expected, verify_tree)
            if sha is None:
                return {"status": "awaiting_review", "package": key, "version": version,
                        "sourceCommit": expected["sourceCommit"], "pullRequest": pr["html_url"],
                        "pullRequestNumber": pr["number"], "branch": pr["head"]["ref"]}
            if interrupt == "after-commit":
                raise InterruptedError("Injected interruption after verified PR merge")
            git(repo, "tag", version, sha)
            git(repo, "push", "origin", f"refs/tags/{version}")
        else:
            validate(stage, temp / "validation", mirror_root)
            if has_branch and load(repo / ".publication.json") == expected:
                # Recover after the generated publication commit was pushed without its tag.
                sha = git(repo, "rev-parse", "HEAD")
            else:
                if has_branch:
                    previous = load(repo / ".publication.json")
                    if tuple(map(int, previous["version"].split("."))) >= tuple(map(int, version.split("."))):
                        raise ValueError("New publication version must increase")
                    for child in repo.iterdir():
                        if child.name != ".git":
                            if child.is_dir() and not child.is_symlink():
                                shutil.rmtree(child)
                            else:
                                child.unlink()
                else:
                    # Bootstrap the publication branch without checking out or inheriting a locked default branch.
                    git(repo, "symbolic-ref", "HEAD", f"refs/heads/{RELEASE_BRANCH}")
                shutil.copytree(stage, repo, dirs_exist_ok=True)
                sha = commit(repo, f"chore: sdk-5388 publish experimental {key} {version}")
                git(repo, "push", "origin", f"HEAD:refs/heads/{RELEASE_BRANCH}")
            if interrupt == "after-commit":
                raise InterruptedError("Injected interruption after publication push")
            git(repo, "tag", version)
            git(repo, "push", "origin", f"refs/tags/{version}")
        # Confirm the served tag, not only the success of the push command.
        served = run(["git", "ls-remote", remote, f"refs/tags/{version}"])
        if served.split()[0] != sha:
            raise ValueError("Served publication tag differs from validated commit")
        if interrupt == "after-tag":
            raise InterruptedError("Injected interruption after tag push")
        release_url = ensure_release(key, version, sha, expected, mirror_root)
        return {"status": "published", "package": key, "version": version, "sourceCommit": expected["sourceCommit"],
                "publicationCommit": sha, "tag": version, "release": release_url,
                "reusedTag": existing, "branch": RELEASE_BRANCH,
                "transport": "local-git" if mirror_root else "github"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", choices=list(NAMES))
    parser.add_argument("version")
    parser.add_argument("--local-remotes", type=Path)
    parser.add_argument("--interrupt", choices=["after-commit", "after-tag"])
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--result-file", type=Path)
    args = parser.parse_args()
    try:
        result = publish(args.package, args.version, args.local_remotes, root=args.source_root, interrupt=args.interrupt)
    except (ValueError, RuntimeError, OSError, InterruptedError) as error:
        result = {"status": "incomplete", "package": args.package, "version": args.version,
                  "error": str(error),
                  "note": "A public tag may already exist; inspect refs and retry with the original source SHA."}
        if args.result_file:
            write_json(args.result_file, result)
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    if args.result_file:
        write_json(args.result_file, result)
    print(json.dumps(result, indent=2))
