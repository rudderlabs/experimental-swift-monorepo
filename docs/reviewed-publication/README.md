# Reviewed experimental publication

The existing `rudderstack-github-actions` GitHub App creates publication PRs.
No new GitHub App or branch-rule bypass is required.
The App needs Contents write and Pull requests write on the experimental publication repositories in `release/allowlist.json`.
The normal Actions token remains Contents read. Production repositories are not on the allowlist.

## Release flow

1. Merge the package's Release Please PR in the source repository (one PR per package, see [Release one package alone](#release-one-package-alone)).
2. Record the component version and full source commit SHA.
3. Export and build the standalone package from that source snapshot.
4. Push the generated files to `publication/<package>/<version>`.
5. Open the publication PR through the existing App token.
6. Review and merge the publication PR under the existing branch rules.
7. Run Tag & Release Packages (`complete-publication.yml`, the central completion workflow) after merge.
8. Verify the exact merge commit against its stored provenance.
9. Create the plain version tag at that verified merge commit.
10. Create the public GitHub Release.
11. Test an anonymous customer upgrade with SwiftPM and an iOS simulator build.

Step 7 is manual. **Merged a bot PR? Run Tag & Release Packages.** It has no inputs and scans all packages. The 15-minute schedule was removed on 2026-10-08 because it failed on every run.
Bot commits are authored as `rudderstack-github-actions[bot]` with the App's noreply email; `publish.yml` looks up the bot user id at runtime and the publisher refuses any other identity.
All PR, commit and Release texts come from `release/texts.json` and follow the standalone repositories: commit and PR title `chore(release): <version>`, Release title `<version>`. The Release body is `# <title> <version>` (`title` in `release/packages.json`, default the target), the package's CHANGELOG.md section for the version as `## Features`/`## Bug Fixes`/... with full monorepo PR links, `## What's Changed` (PR title and author from the GitHub API; best effort, omitted on any API error), `**Full Changelog**` against the previous version tag, and a `Source: monorepo commit` footer. The publish PR body repeats the heading and sections, then lists the built platforms.
An existing Release only has to be the single non-draft Release for its tag: the tag and its `.publication.json` carry the provenance, so Releases created with earlier texts (or edited by hand) still complete.
The source workflow holds the credentials. Publication repositories need no relay workflow or secrets.
This central workflow replaces the proposed per-repository merge-event relay.

Source component releases are durable release intent. The completion workflow discovers incomplete publication from these releases.
It does not require transient Release Please action outputs, a PR comment, or a new source change.
Completed tag/release pairs are excluded from the recovery queue.
SDK work precedes integration work in the queue. Each integration also checks its required SDK tag before building.
An integration that needs an unpublished SDK reports `awaiting_dependency` and resumes on a later check.
The completion workflow reports and skips a broken item (as `incomplete`) instead of failing the whole queue, and never rebuilds an item whose bot PR is still open (`awaiting_review`).

## Publication boundaries

An open publication PR creates no public version tag or GitHub Release. Publication `main` keeps the previous package.
After the reviewed merge, branch-based customers can see the generated update before its tag exists.
This short interval is inherent in the reviewed PR route. Version-based customers remain on their selected immutable tags.
Source `main` can advance without entering the export. Publication `main` can advance without changing the selected merge commit.
A tag always identifies the verified merge commit, not whichever commit is currently at `main`.

Before merge, the publisher compares the PR's file hashes and complete provenance record with a new deterministic export.
Updating an open PR's hashes together with an unauthorized file change does not bypass this comparison.
After merge (and for an existing tag), the version is verified against its own stored `.publication.json`: every file hash and the package, version and source commit (D25). It is not re-exported, so completion runs and re-runs survive exporter changes. The reviewed merge is the gate for the merged content.
It checks PR bot identity, allowlisted destination, source ancestry, and merged commit ancestry.
A closed, unmerged PR, a conflicting version branch, manual drift, or an existing tag conflict stops publication.
The publisher never force-pushes a publication branch or rewrites a version tag.

## States and recovery

| State | Meaning | Recovery |
| --- | --- | --- |
| `awaiting_review` | Valid generated PR exists; no tag is created | Review and merge; completion runs later |
| `awaiting_dependency` | Required SDK tag is unavailable | Complete SDK publication; run Tag & Release Packages again |
| `awaiting_takeover` | Public repository has no `.publication.json` and is not README-only, or takeover found `.github/workflows` | Remove `.github/workflows` by PR, dispatch `mode=takeover`, merge the bot PR, run Tag & Release Packages |
| `published` | Served version tag and public Release are verified | No further publication write |
| `incomplete` | Build, verification, API, or publication failed | Inspect evidence; retry the original source SHA and version |

The batch status is `awaiting_publication` when packages are waiting. Waiting does not count as customer success.
An interruption after branch push reuses the matching branch. An interruption after PR creation reuses the matching PR.
An interruption after merge tags the verified merge commit. An interruption after tagging repairs only the missing Release.
A failed customer build fails the workflow, while publication evidence records any already served tag.
Rerun that failed publisher job or dispatch `publish.yml` with the original source SHA and version to repeat customer verification.
Do not move a public tag to repair a customer failure.

The anonymous customer check clones the public consumer on `main` into a disposable directory.
It selects the newly published package version and raises the SDK selection only when the declared minimum requires that change.
It records the consumer commit, runtime versions, public lockfiles, and iOS build result.
It does not push a consumer upgrade commit. A persistent example-app upgrade remains a separate reviewed PR.

## Takeover, bootstrap and anchors

`publish.yml` takes `mode`: `normal` (default), `takeover` or `bootstrap`.
- A repository with `.publication.json` publishes normally. A README-only repository (README, maybe LICENSE and `.gitignore`) gets a bootstrap bot PR that replaces it with the export; after merge, Tag & Release Packages tags it.
- Any other repository is `awaiting_takeover`. Other packages continue.
- `mode=takeover` opens one bot PR on `takeover/<key>/<version>` at the existing public tag `<version>`. It removes every non-generated file and adds the export. Before the PR it checks `Sources/` byte-identical to that tag (only a missing `Version.swift` may be added) and `Package.swift` semantically equal with `swift package dump-package` (products, targets, platforms, dependency requirements). The PR body lists the removed files and the allowed differences. No tag or Release is created; after merge the package publishes normally.
- If `.github/workflows` exists, takeover refuses with "Remove .github/workflows by PR first" and the package stays `awaiting_takeover` (D31). The bot never writes or deletes workflow files and needs no Workflows permission.

Every export adds a generated CONTRIBUTING.md, `.github/CODEOWNERS` (`* @rudderlabs/sdk_team`) and a README block (`release/templates/`) that welcome issues and pull requests in the public repository; maintainers carry merged public PRs back to this monorepo ([Sync back an outside PR](#sync-back-an-outside-pr)). All are hashed in provenance; `copiedFiles` records a `transform` per file (`copy`, `vendored-strip-import`, `generated`) for reverse sync.

`anchor-package.yml` (manual: package, version, full `main` SHA) validates the package against the allowlist and package list, the SemVer version against `version.txt` at that commit, and the SHA on `main`, then creates the plain tag `<component>-<version>`. It creates no GitHub Release, so the completion queue never sees it, and no workflow starts on a tag.

## Maintainer how-tos

### Release one package alone

Release Please opens one release PR per package (`"separate-pull-requests": true` in `release-please-config.json`), for example `chore(release): sdk 1.4.2` on branch `release-please--branches--main--components--sdk` and `chore(release): integration-sprig 1.0.2` on `release-please--branches--main--components--integration-sprig`. The title comes from `pull-request-title-pattern`, matching rudder-sdk-swift's `chore(release): …` style. Each PR holds only its package's version files, CHANGELOG and manifest line.
Merge only the PR of the package you want to release; the others stay open and are rebuilt on the next push to `main`. `release-please.yml` then plans only the merged package: merging only the Sprig PR runs one `publish (sprig)` leg and skips `publish (sdk)`. Merging the SDK PR releases only the SDK; merge each integration's own PR when it should follow.
An integration whose `sdkMinimum` needs an unreleased SDK waits as `awaiting_dependency` until the SDK is published, so merge the SDK PR first in a coordinated release.

### Override the next version with Release-As

Release Please normally picks the next version from the commit types (`fix` a patch, `feat` a minor, `!` a major). To choose it yourself, end the squash commit message on `main` with the footer:

```text
fix(sprig): send the session id on identify

Release-As: 1.5.0
```

Put the footer in the commit message box of the squash-merge dialog (the extended description), as its last paragraph, and check it is there before you confirm. Release Please reads it from the commit body on `main`, not from the PR description.
The footer applies to every package whose folder the commit changes, and each of those packages' release PRs proposes that version. A commit that changes no file at all (an empty commit) applies to every package; a commit that changes only files outside the package folders (for example `docs/` or `scripts/`) applies to none.
To target one package, make the commit change only files under that package's folder (for example `Integrations/Sprig/`). The commit needs a type with a visible CHANGELOG section (`feat`, `fix`, `perf`, `refactor`, `chore`): Release Please skips a package whose notes would be empty, so a `docs:` or `test:` commit opens no release PR.
The alternative is a temporary `"release-as": "1.5.0"` inside that package's entry under `packages` in `release-please-config.json`. It works in manifest mode and targets exactly one package, but it still needs a releasable commit in that folder, and it keeps forcing that version until it is removed: remove it in a follow-up PR right after the release PR merges. Prefer the footer.

### Roll forward a bad published version

Never delete or move a public tag: the tag ruleset makes version tags immutable, and SwiftPM customers may already have resolved it. Publish a fixed version instead.

1. In this monorepo, undo the bad change with a `fix:` commit that changes only the affected package's folder, for example `fix(sprig): revert the session id change from 1.0.2`. Do not merge GitHub's `Revert "…"` title as-is: `revert` is a hidden type here and opens no release PR.
2. Merge the package's release PR (a patch, for example `1.0.3`), review and merge the publication PR, then run Tag & Release Packages.
3. Mark the bad version in the public repository's GitHub Release. Keep it a published (non-draft) Release, because completion expects one non-draft Release per tag. Prepend the warning to the existing notes:

```sh
REPO=rudderlabs/experimental-integration-swift-sprig BAD=1.0.2 GOOD=1.0.3
gh release view "$BAD" --repo "$REPO" --json body --jq .body > notes.md
{ printf '> ⚠️ Withdrawn — use %s\n\n' "$GOOD"; cat notes.md; } > withdrawn.md
gh release edit "$BAD" --repo "$REPO" --notes-file withdrawn.md
```

Customers on `from: "1.0.2"` get `1.0.3` with their next package update; customers pinned to `exact: "1.0.2"` must change the pin.

### Public activity notifications

The **Public Activity** workflow runs daily at 09:00 IST (03:30 UTC) and can be started at any time with Actions → Public Activity → Run workflow. It looks at the public package repositories and opens an issue in this monorepo for new outside activity, labelled `pkg:<key>` for the package and `public-issue` (a public issue), `public-pr` (a public pull request) or `sync-back-needed` (a merged public change that this monorepo does not have yet). Triage those issues like any other: answer on the public repository, and close the monorepo issue when done.

### Sync back an outside PR

After a public pull request is merged, bring the change into this monorepo, the source of truth; until then the public repository differs from its last export and the next publication stops on the drift check. Run Actions → **Sync Back Public Changes** → Run workflow with input `package` (the package key, for example `sprig`). It opens a monorepo PR with the public changes that credits the outside author. Generated and vendored files (CONTRIBUTING.md, the README block, `Package.swift`, vendored shared code) cannot be copied back as-is: the PR flags them, and a person makes the matching change in the real source (`release/templates/`, `release/packages.json`, `Shared/`). Review it like any change; it ships with the package's next release.

### Discard an unpublished version

- Before the publication PR is merged: add the label `abandon` to the public publish PR and close it (`gh pr edit <number> --repo <repo> --add-label abandon`, then `gh pr close <number> --repo <repo>`). No tag or Release exists for that version.
- After the publication PR is merged but before the tag exists: run Actions → **Abandon Unpublished Version** with `package` and `version`. It opens a bot revert PR on the public repository; review and merge it, and public `main` is back to the last published version.
- Either way, Tag & Release Packages reports the version as `abandoned` and never tags it. The monorepo tag stays; the next Release Please version publishes normally and skips that number.
- Closing a publication PR without the `abandon` label still stops Tag & Release on purpose (review required).
- Once a version is tagged, customers may have it: roll forward instead (see above).
- Each public repository needs the `abandon` label once: `gh label create abandon --repo <repo> --description "Discard this unpublished version"`.

## Existing Sprig trial

The source release `integration-sprig-0.1.1` already records its approved source snapshot.
The new workflow can export that historical snapshot without adding workflow files to the generated package.
Existing immutable tags and provenance are preserved.
The earlier manual Sprig publication PR must not be merged alongside the new bot publication PR for the same version.
After the bot PR exists and its generated tree matches, close the superseded manual PR through the approved experiment execution.

## Validation limits

Local tests use real Git branches, protected-main rejection hooks, PR merge commits, and immutable tags.
Only GitHub PR API responses are modeled in the reviewed-route tests.
The rehearsal (`python3 scripts/rehearse.py`) runs bootstrap, takeover, releases, Tag & Release Packages, drift and clean consumers on fixture repositories with the same modeled PR API; `--ios` adds the iOS consumer build.
Hosted App Pull requests write access, bot PR creation, required review, scheduled completion, and public customer upgrades need hosted evidence.
Local passing tests do not close these hosted gates or the dependency-monitoring acceptance gates.
