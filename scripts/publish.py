"""Validate, publish, and recover immutable standalone package releases."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile

from common import (ROOT, OWNER, RELEASE_BRANCH, SDK, allowlist, anonymous_env, commit, file_hashes, git,
                    inventory, load, mirrors, run, swift_options, text, url, write_json)
from maintenance_branch import line, public_base, semver, source_line
from project import SEMVER, export, platform_builds
import release_notes
from reviewed_publication import MODES, Abandoned, WORKFLOWS, find_pr, layout, reviewed_commit, takeover_check, verify_merged

@contextlib.contextmanager
def publication_lock(mirror_root, name):
    # GitHub uses the equivalent per-package workflow concurrency group.
    if mirror_root is None:
        yield
        return
    lock = mirror_root / (name + ".lock")
    with lock.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("A publication for this repository is already running") from error
        yield


def verify_tree(repo, export_hashes=None):
    """The tree's provenance. Drift is accepted only when `export_hashes()` (the new export's fileHashes) already
    holds every differing file as is: an outside edit that was synced back (scripts/sync_back.py)."""
    provenance = load(repo / ".publication.json")
    published, current = provenance["fileHashes"], file_hashes(repo)
    drift = {p for p in published.keys() | current.keys() if published.get(p) != current.get(p)}
    if drift and not (export_hashes and synced(drift, current, export_hashes)):
        raise ValueError("Publication repository contains manual drift")
    return provenance


def synced(drift, current, export_hashes):
    try:
        expected = export_hashes()
    except (ValueError, RuntimeError):
        return False  # Without an export nothing proves the edit came back; the drift error stands.
    return all(current.get(p) == expected.get(p) for p in drift)


def tag_exists(repo, version):
    return f"refs/tags/{version}" in git(repo, "for-each-ref", "--format=%(refname)", "refs/tags").splitlines()


def versions(repo):
    """Plain X.Y.Z tags of the publication repository (pre-release tags do not count)."""
    return [t for t in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/tags").splitlines()
            if SEMVER.fullmatch(t)]


def base_start(repo, version):
    """A missing public `release/X.Y.x` starts at the tag of the latest X.Y.* version below `version`."""
    older = [t for t in versions(repo) if line(t) == line(version) and semver(t) < semver(version)]
    if not older:
        raise ValueError("No public {}.{}.* tag to start the maintenance base from".format(*line(version)))
    return git(repo, "rev-parse", f"refs/tags/{max(older, key=semver)}^{{commit}}")


def validate(stage, state, mirror_root, package):
    mirrors(stage, mirror_root)
    # The host `swift build` is a macOS build: only for packages that declare macOS (or no platforms at all).
    platforms = [p.split()[0] for p in package.get("platforms", [])]
    output = run(["swift", "build", *swift_options(state)], cwd=stage, env=anonymous_env()) \
        if not platforms or "macOS" in platforms else ""
    platform_builds(stage, package, state)
    # SwiftPM configuration and the resolved file must never enter the publication tree.
    shutil.rmtree(stage / ".swiftpm", ignore_errors=True)
    (stage / "Package.resolved").unlink(missing_ok=True)
    return output


def ensure_release(key, version, sha, mirror_root, render, latest=True):
    """Create the GitHub Release for the served tag, or accept the one that exists.

    An existing Release counts when it is the only one for the tag and not a draft. Its title and notes are
    presentation, not provenance: the tag and its `.publication.json` were verified before this point, people may
    edit notes, the What's Changed section is best effort, and Releases made with earlier texts must still recover.
    `render()` returns the notes; it runs only when a Release is created. `latest=False` keeps a maintenance
    Release below a higher version from becoming "Latest"; otherwise GitHub decides, as before.
    """
    name = allowlist()[key]
    if mirror_root:
        record = mirror_root.parent / "modeled-github-releases" / name / (version + ".json")
        kind = "local-model-not-github"
        if record.exists():
            existing = load(record)
            if (existing.get("tag"), existing.get("commit"), existing.get("kind")) != (version, sha, kind):
                raise ValueError("Modeled release metadata conflicts")
            return str(record)
        write_json(record, {"tag": version, "commit": sha, "title": text("releaseTitle", version=version),
                            "body": render(), "kind": kind})
        return str(record)
    repo = f"{OWNER}/{name}"
    # Listing distinguishes confirmed absence from API, network, and authentication errors.
    records = json.loads(run(["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases"]))
    found = [r for page in records for r in page if r["tag_name"] == version]
    if found:
        if len(found) != 1 or found[0]["draft"]:
            raise ValueError("Existing GitHub Release metadata differs")
        return found[0]["html_url"]
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "release.md"
        path.write_text(render())
        return run(["gh", "release", "create", version, "--repo", repo, "--verify-tag",
                    "--title", text("releaseTitle", version=version), "--notes-file", path,
                    *([] if latest else ["--latest=false"])])


def release_text(repo, key, package, version, sha, provenance, online):
    """Release body from the CHANGELOG.md served at the publication commit."""
    try:
        changelog = git(repo, "show", f"{sha}:CHANGELOG.md")
    except RuntimeError:
        changelog = ""
    tags = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/tags").splitlines()
    return release_notes.release_body(key, package, version, changelog, provenance,
                              previous=release_notes.previous_tag(tags, version), online=online)


def source_commit(root):
    return git(root, "rev-parse", "HEAD")


def waiting(status, key, version, source, **details):
    return {"status": status, "package": key, "version": version, "sourceCommit": source, **details}


def publish(key, version, mirror_root=None, root=ROOT, interrupt=None, mode="normal"):
    # The trusted checkout's allowlist must agree with the source snapshot's inventory and allowlist.
    name = allowlist().get(key)
    if not name or inventory(root).get(key, {}).get("repository") != name:
        raise ValueError("Destination is outside the reviewed allowlist")
    if mode not in MODES:
        raise ValueError("Unknown publication mode")
    if mirror_root:
        if mode != "normal":
            raise ValueError("Takeover and bootstrap use the reviewed GitHub route only")
        mirror_root = mirror_root.resolve()
        remote = mirror_root / (name + ".git")
        if not remote.is_dir() or git(remote, "rev-parse", "--is-bare-repository") != "true":
            raise ValueError("Local publication repository is missing or is not bare")
    else:
        if os.environ.get("ENABLE_EXPERIMENTAL_PUBLICATION") != "true":
            raise ValueError("Remote publication is disabled")
        remote = url(key)
        details = json.loads(run(["gh", "repo", "view", f"{OWNER}/{name}",
                                  "--json", "nameWithOwner,visibility,isArchived"]))
        if details != {"nameWithOwner": f"{OWNER}/{name}", "visibility": "PUBLIC", "isArchived": False}:
            raise ValueError("Experimental repository identity, visibility, or archive state differs")
    with publication_lock(mirror_root, name), tempfile.TemporaryDirectory(prefix=f"publish-{key}-") as temp:
        temp = Path(temp)
        stage, repo = temp / "export", temp / "publication"
        package = inventory(root)[key]
        source = source_commit(root)
        # The source line picks the publication base: main, or release/X.Y.x for a release/<key>-X.Y.x commit.
        base = RELEASE_BRANCH if mirror_root else public_base(source_line(root, key, source, version), version)
        if base != RELEASE_BRANCH and mode != "normal":
            raise ValueError("A maintenance line publishes in mode normal only")

        def prepare(full):
            # Export only when a version is not merged yet; merged versions use stored provenance (D25).
            expected = export(key, version, stage, root)
            if full:
                if mode == "takeover":
                    # The takeover republishes the code already public at the tag: identity, not builds, so a
                    # platform gap in the old package cannot block it. The next release builds every platform.
                    git(repo, "worktree", "add", "--detach", temp / "baseline", f"refs/tags/{version}")
                    takeover_check(temp / "baseline", stage, package["target"])
                else:
                    validate(stage, temp / "validation", mirror_root, package)
            return expected

        run(["git", "clone", "--no-checkout", remote, repo])
        existing = tag_exists(repo, version)
        publication_ref = f"refs/remotes/origin/{base}"
        has_branch = publication_ref in git(
            repo, "for-each-ref", "--format=%(refname)", publication_ref
        ).splitlines()
        # A new maintenance base is pushed only right before its first PR; until then it is checked at the tag.
        start = base_start(repo, version) if not (has_branch or existing) and base != RELEASE_BRANCH else None
        state = None
        if has_branch or start:
            git(repo, "checkout", "-B", base, start or publication_ref)
            state = layout(repo)
            if state == "generated":
                # A separate export: `stage` must stay empty for prepare().
                verify_tree(repo, lambda: export(key, version, temp / "synced-check", root)["fileHashes"])
        if mirror_root is None:
            if not (has_branch or start):
                raise ValueError(f"Reviewed publication requires a seeded {base} branch")
            if base != RELEASE_BRANCH and state != "generated":
                raise ValueError(f"Maintenance base {base} has no provenance")
            if state == "foreign" and mode != "takeover":
                if mode == "bootstrap":
                    raise ValueError("Bootstrap needs a README-only publication repository")
                # Not taken over yet: wait without blocking other packages (D28).
                return waiting("awaiting_takeover", key, version, source,
                               reason="The publication repository is not taken over yet; dispatch mode takeover")
            if mode == "takeover":
                return takeover(key, version, source, repo, stage, prepare, state, existing, package)
        if existing:
            git(repo, "checkout", "--detach", f"refs/tags/{version}")
            try:
                expected = verify_merged(repo, key, version, source, verify_tree)
            except ValueError as error:
                raise ValueError("Existing tag conflicts with source, version, policy, or file hashes") from error
            sha = git(repo, "rev-parse", "HEAD")
            if mirror_root is None:
                git(repo, "merge-base", "--is-ancestor", sha, f"origin/{base}")
        elif mirror_root is None:
            # Dependency readiness is a waiting state, not permission to publish a broken package.
            minimum = package.get("sdkMinimum")
            if minimum and not run(["git", "ls-remote", url(SDK), f"refs/tags/{minimum}"]):
                return waiting("awaiting_dependency", key, version, source, dependency=SDK, minimum=minimum)
            if start:
                # The bot creates the maintenance base once, at the verified tag of the line's latest version.
                git(repo, "push", "origin", f"{start}:refs/heads/{base}")
                git(repo, "fetch", "--no-tags", "origin", f"+refs/heads/{base}:{publication_ref}")
            kind = "bootstrap" if state == "readme-only" else "normal"
            try:
                sha, pr = reviewed_commit(key, version, source, repo, stage, prepare, verify_tree, kind, package,
                                          base)
            except Abandoned:
                return waiting("abandoned", key, version, source)
            if sha is None:
                return waiting("awaiting_review", key, version, source, pullRequest=pr["html_url"],
                               pullRequestNumber=pr["number"], branch=pr["head"]["ref"], mode=kind, base=base)
            expected = load(repo / ".publication.json")
            if interrupt == "after-commit":
                raise InterruptedError("Injected interruption after verified PR merge")
            git(repo, "tag", version, sha)
            git(repo, "push", "origin", f"refs/tags/{version}")
        else:
            expected = prepare(True)
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
                sha = commit(repo, text("commit", version=version))
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
        # A maintenance Release never becomes "Latest" over a higher public version; main keeps GitHub's default.
        latest = base == RELEASE_BRANCH or not any(semver(t) > semver(version) for t in versions(repo))
        release_url = ensure_release(key, version, sha, mirror_root, lambda: release_text(
            repo, key, package, version, sha, expected, online=mirror_root is None), latest)
        return {"status": "published", "package": key, "version": version, "sourceCommit": expected["sourceCommit"],
                "publicationCommit": sha, "tag": version, "release": release_url,
                "reusedTag": existing, "branch": base,
                "transport": "local-git" if mirror_root else "github"}


def takeover(key, version, source, repo, stage, prepare, state, existing, package=None):
    """One reviewed bot PR replaces a foreign repository with the export at its existing tag. No tag is created."""
    if state == "readme-only":
        raise ValueError("A README-only publication repository uses mode bootstrap")
    if state == "generated":
        pr = find_pr(key, version, "takeover")
        if not (pr and pr["merged"]):
            raise ValueError("The publication repository is already taken over; use mode normal")
    elif (repo / ".github/workflows").exists():
        # The release bot has no Workflows permission (D31).
        return waiting("awaiting_takeover", key, version, source, reason=WORKFLOWS)
    if not existing:
        raise ValueError(f"Takeover needs the existing baseline tag {version} in the publication repository")
    sha, pr = reviewed_commit(key, version, source, repo, stage, prepare, verify_tree, "takeover", package)
    if sha is None:
        return waiting("awaiting_review", key, version, source, pullRequest=pr["html_url"],
                       pullRequestNumber=pr["number"], branch=pr["head"]["ref"], mode="takeover")
    # Taken over: the existing tag stays where it is and serves byte-identical Sources/.
    return {"status": "published", "package": key, "version": version, "sourceCommit": source,
            "publicationCommit": sha, "tag": version, "takeover": True, "pullRequest": pr["html_url"],
            "branch": RELEASE_BRANCH, "transport": "github"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", choices=list(allowlist()))
    parser.add_argument("version")
    parser.add_argument("--local-remotes", type=Path)
    parser.add_argument("--interrupt", choices=["after-commit", "after-tag"])
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--mode", choices=MODES, default="normal")
    args = parser.parse_args()
    try:
        result = publish(args.package, args.version, args.local_remotes, root=args.source_root,
                         interrupt=args.interrupt, mode=args.mode)
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
