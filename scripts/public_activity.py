"""Mirror outside activity on the publication repositories into monorepo issues (one per public item).

Each public issue or PR gets one monorepo issue, found again by a hidden marker in its body. Closed public
items close their mirror; merged PRs keep it open with `sync-back-needed`. Commits on public main after the
latest version tag (other than the publish bot's) get one open `[<key>] Public main has unsynced changes` issue.
Reads public repositories; writes only monorepo issues and labels, and nothing with --dry-run.
"""
import argparse
import json
import os
import re
import urllib.parse
import urllib.request

from common import OWNER, RELEASE_BRANCH, SOURCE_NAME, inventory
from generate_github import labels as package_labels

API = "https://api.github.com"
BOT = "rudderstack-github-actions[bot]"
SYNC = "sync-back-needed"
KINDS = {"issue": ("public-issue", "Issue"), "pr": ("public-pr", "PR")}
LABELS = {"public-issue": ("fbca04", "Issue opened on a publication repository"),
          "public-pr": ("fbca04", "Pull request opened on a publication repository"),
          SYNC: ("d93f0b", "Public change must be synced back into the monorepo")}
MARKER = re.compile(r"<!-- public-activity: (\S+) -->")
# Public items already closed when monitoring started are history; open ones are always mirrored.
SINCE = "2026-10-13T00:00:00Z"
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)\Z")


def request(method, path, body=None):
    """The only network call. Public repositories need no token; one avoids the anonymous rate limit."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body).encode()
    with urllib.request.urlopen(urllib.request.Request(API + path, data, headers, method=method), timeout=30) as r:
        return json.loads(r.read() or "null")


def pages(get, path):
    joiner = "&" if "?" in path else "?"
    result, page = [], 1
    while True:
        batch = get(f"{path}{joiner}per_page=100&page={page}")
        result += batch
        if len(batch) < 100:
            return result
        page += 1


def quiet(text):
    """No @mention from public text may notify anyone."""
    return " ".join(str(text).split()).replace("@", "@​")


def author(commit):
    return (commit.get("author") or {}).get("login") or commit["commit"]["author"]["name"]


def mirrors(get, repo):
    """Monorepo issues carrying a marker, by marker. Every mirror has at least one of the LABELS."""
    found = {}
    for label in LABELS:
        for issue in pages(get, f"/repos/{repo}/issues?state=all&labels={urllib.parse.quote(label)}"):
            marker = MARKER.search(issue.get("body") or "")
            if marker and "pull_request" not in issue:
                found.setdefault(marker[1], {"number": issue["number"], "state": issue["state"],
                                             "body": issue["body"], "labels": {l["name"] for l in issue["labels"]}})
    return found


def unsynced(get, public):
    """(latest version tag, commits on public main after it), or (None, []) before the first tag."""
    tags = [t["name"] for t in pages(get, f"/repos/{public}/tags") if VERSION.match(t["name"])]
    if not tags:
        return None, []
    tag = max(tags, key=lambda name: tuple(map(int, VERSION.match(name).groups())))
    return tag, get(f"/repos/{public}/compare/{tag}...{RELEASE_BRANCH}")["commits"]


def plan_item(key, public, raw, mirror, since=SINCE):
    """Actions that make one public issue or PR's mirror match it."""
    kind = "pr" if "pull_request" in raw else "issue"
    label, noun = KINDS[kind]
    merged = bool((raw.get("pull_request") or {}).get("merged_at"))
    closed = raw["state"] == "closed"
    if mirror is None:
        if closed and (raw.get("closed_at") or "") < since:
            return []
        login = raw["user"]["login"]
        state = "merged" if merged else "closed" if closed else "open"
        body = (f"<!-- public-activity: {public}#{raw['number']} -->\n"
                f"Public {noun.lower()}: {raw['html_url']} ({state})\n"
                f"Author: [{login}](https://github.com/{urllib.parse.quote(login)})\n"
                f"Package: `{key}`\n")
        title = f"[{key}] {noun} #{raw['number']}: {quiet(raw['title'])}"[:250]
        return [{"op": "create", "title": title, "body": body,
                 "labels": [f"pkg:{key}", label] + ([SYNC] if merged else []), "close": closed and not merged}]
    number, is_open = mirror["number"], mirror["state"] == "open"
    if not closed and not is_open:
        return [{"op": "update", "number": number, "comment": "Reopened on the public repo.", "state": "open"}]
    if merged and is_open and SYNC not in mirror["labels"]:
        return [{"op": "update", "number": number, "labels": [SYNC],
                 "comment": "Merged on the public repo — sync back needed."}]
    if closed and not merged and is_open:
        text = "Closed without merging on the public repo." if kind == "pr" else "Closed on the public repo."
        return [{"op": "update", "number": number, "comment": text, "state": "closed"}]
    return []


def plan_unsynced(key, public, tag, commits, mirror):
    """One open issue per package while public main has non-bot commits after the latest tag."""
    human = [c for c in commits if author(c) != BOT]
    if not human:
        if mirror and mirror["state"] == "open":
            return [{"op": "update", "number": mirror["number"], "state": "closed",
                     "comment": f"Public main has no unsynced changes after {tag} any more."}]
        return []
    lines = [f"- [`{c['sha'][:7]}`]({c['html_url']}) {quiet(c['commit']['message'].splitlines()[0])} "
             f"({quiet(author(c))})" for c in human]
    body = (f"<!-- public-activity: {public}:unsynced -->\n"
            f"https://github.com/{public}/compare/{tag}...{RELEASE_BRANCH} has {len(human)} commit(s) "
            f"after `{tag}` that are not from the publish bot. Sync them back into the monorepo.\n\n"
            + "\n".join(lines) + "\n")
    if mirror is None:
        return [{"op": "create", "title": f"[{key}] Public main has unsynced changes", "body": body,
                 "labels": [f"pkg:{key}", SYNC], "close": False}]
    if mirror["state"] != "open":
        return [{"op": "update", "number": mirror["number"], "body": body, "state": "open",
                 "comment": "New unsynced commits on public main."}]
    return [{"op": "update", "number": mirror["number"], "body": body}] if mirror["body"] != body else []


def plan(get, repo, packages, since=SINCE):
    found = mirrors(get, repo)
    actions = []
    for key, package in packages.items():
        public = f"{OWNER}/{package['repository']}"
        for raw in pages(get, f"/repos/{public}/issues?state=all"):
            if raw["user"]["login"] != BOT:
                actions += plan_item(key, public, raw, found.get(f"{public}#{raw['number']}"), since)
        tag, commits = unsynced(get, public)
        if tag:
            actions += plan_unsynced(key, public, tag, commits, found.get(f"{public}:unsynced"))
    wanted = sorted({l for a in actions for l in a.get("labels", [])})
    have = {l["name"] for l in pages(get, f"/repos/{repo}/labels")} if wanted else set()
    known = {l["name"]: (l["color"], l["description"]) for l in package_labels(packages)} | LABELS
    return [{"op": "label", "name": name, "color": known[name][0], "description": known[name][1]}
            for name in wanted if name not in have] + actions


def describe(action):
    if action["op"] == "label":
        return f"create label {action['name']}"
    if action["op"] == "create":
        return f"open issue {action['title']!r} {action['labels']}" + (", then close it" if action["close"] else "")
    parts = [f"{k}={action[k]!r}" for k in ("comment", "labels", "state") if k in action]
    return f"update #{action['number']}: " + ", ".join(parts + (["body"] if "body" in action else []))


def apply(write, repo, actions):
    for action in actions:
        if action["op"] == "label":
            write("POST", f"/repos/{repo}/labels", {k: action[k] for k in ("name", "color", "description")})
            continue
        if action["op"] == "create":
            number = write("POST", f"/repos/{repo}/issues", {k: action[k] for k in ("title", "body", "labels")})["number"]
            action = {"number": number, **({"state": "closed"} if action["close"] else {})}
        issue = f"/repos/{repo}/issues/{action['number']}"
        if "comment" in action:
            write("POST", issue + "/comments", {"body": action["comment"]})
        if "labels" in action:
            write("POST", issue + "/labels", {"labels": action["labels"]})
        patch = {k: action[k] for k in ("state", "body") if k in action}
        if patch:
            write("PATCH", issue, patch)


def main(argv=None, get=lambda path: request("GET", path), write=request):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the actions without writing")
    parser.add_argument("--since", default=SINCE, help="also mirror public items closed after this ISO time")
    args = parser.parse_args(argv)
    repo = os.environ.get("GITHUB_REPOSITORY") or f"{OWNER}/{SOURCE_NAME}"
    actions = plan(get, repo, inventory(), args.since)
    for action in actions:
        print(("[dry-run] " if args.dry_run else "") + describe(action))
    if not actions:
        print("No public activity to mirror.")
    if not args.dry_run:
        apply(write, repo, actions)


if __name__ == "__main__":
    main()
