# Reviewed experimental publication

The existing `rudderstack-github-actions` GitHub App creates publication PRs.
No new GitHub App or branch-rule bypass is required.
The App needs Contents write and Pull requests write on the experimental publication repositories in `release/allowlist.json`.
The normal Actions token remains Contents read. Production repositories are not on the allowlist.

## Release flow

1. Merge the Release Please PR in the source repository.
2. Record the component version and full source commit SHA.
3. Export and build the standalone package from that source snapshot.
4. Push the generated files to `publication/<package>/<version>`.
5. Open the publication PR through the existing App token.
6. Review and merge the publication PR under the existing branch rules.
7. Press Recover (the central completion workflow) after merge.
8. Verify the exact merge commit against its stored provenance.
9. Create the plain version tag at that verified merge commit.
10. Create the public GitHub Release.
11. Test an anonymous customer upgrade with SwiftPM and an iOS simulator build.

Step 7 is manual. **Merged a bot PR? Press Recover.** Recover has no inputs and scans all packages. The 15-minute schedule was removed on 2026-10-08 because it failed on every run.
Bot commits are authored as `rudderstack-github-actions[bot]` with the App's noreply email; `publish.yml` looks up the bot user id at runtime and the publisher refuses any other identity.
All PR, commit and Release texts and the ticket link come from `release/texts.json`.
The source workflow holds the credentials. Publication repositories need no relay workflow or secrets.
This central workflow replaces the proposed per-repository merge-event relay.

Source component releases are durable release intent. The completion workflow discovers incomplete publication from these releases.
It does not require transient Release Please action outputs, a PR comment, or a new source change.
Completed tag/release pairs are excluded from the recovery queue.
SDK work precedes integration work in the queue. Each integration also checks its required SDK tag before building.
An integration that needs an unpublished SDK reports `awaiting_dependency` and resumes on a later check.
Recover reports and skips a broken item (as `incomplete`) instead of failing the whole queue, and never rebuilds an item whose bot PR is still open (`awaiting_review`).

## Publication boundaries

An open publication PR creates no public version tag or GitHub Release. Publication `main` keeps the previous package.
After the reviewed merge, branch-based customers can see the generated update before its tag exists.
This short interval is inherent in the reviewed PR route. Version-based customers remain on their selected immutable tags.
Source `main` can advance without entering the export. Publication `main` can advance without changing the selected merge commit.
A tag always identifies the verified merge commit, not whichever commit is currently at `main`.

Before merge, the publisher compares the PR's file hashes and complete provenance record with a new deterministic export.
Updating an open PR's hashes together with an unauthorized file change does not bypass this comparison.
After merge (and for an existing tag), the version is verified against its own stored `.publication.json`: every file hash and the package, version and source commit (D25). It is not re-exported, so Recover and re-runs survive exporter changes. The reviewed merge is the gate for the merged content.
It checks PR bot identity, allowlisted destination, source ancestry, and merged commit ancestry.
A closed, unmerged PR, a conflicting version branch, manual drift, or an existing tag conflict stops publication.
The publisher never force-pushes a publication branch or rewrites a version tag.

## States and recovery

| State | Meaning | Recovery |
| --- | --- | --- |
| `awaiting_review` | Valid generated PR exists; no tag is created | Review and merge; completion runs later |
| `awaiting_dependency` | Required SDK tag is unavailable | Complete SDK publication; press Recover again |
| `awaiting_takeover` | Public repository has no `.publication.json` and is not README-only, or takeover found `.github/workflows` | Remove `.github/workflows` by PR, dispatch `mode=takeover`, merge the bot PR, press Recover |
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
- A repository with `.publication.json` publishes normally. A README-only repository (README, maybe LICENSE and `.gitignore`) gets a bootstrap bot PR that replaces it with the export; after merge, Recover tags it.
- Any other repository is `awaiting_takeover`. Other packages continue.
- `mode=takeover` opens one bot PR on `takeover/<key>/<version>` at the existing public tag `<version>`. It removes every non-generated file and adds the export. Before the PR it checks `Sources/` byte-identical to that tag (only a missing `Version.swift` may be added) and `Package.swift` semantically equal with `swift package dump-package` (products, targets, platforms, dependency requirements). The PR body lists the removed files and the allowed differences. No tag or Release is created; after merge the package publishes normally.
- If `.github/workflows` exists, takeover refuses with "Remove .github/workflows by PR first" and the package stays `awaiting_takeover` (D31). The bot never writes or deletes workflow files and needs no Workflows permission.

Every export adds a generated CONTRIBUTING.md, `.github/CODEOWNERS` (`* @rudderlabs/sdk_team`) and a README block linking to the monorepo issue forms (`release/templates/`). All are hashed in provenance; `copiedFiles` records a `transform` per file (`copy`, `vendored-strip-import`, `generated`) for reverse sync.

`anchor-package.yml` (manual: package, version, full `main` SHA) validates the package against the allowlist and package list, the SemVer version against `version.txt` at that commit, and the SHA on `main`, then creates the plain tag `<component>-<version>`. It creates no GitHub Release, so the Recover queue never sees it, and no workflow starts on a tag.

## Existing Sprig trial

The source release `integration-sprig-0.1.1` already records its approved source snapshot.
The new workflow can export that historical snapshot without adding workflow files to the generated package.
Existing immutable tags and provenance are preserved.
The earlier manual Sprig publication PR must not be merged alongside the new bot publication PR for the same version.
After the bot PR exists and its generated tree matches, close the superseded manual PR through the approved experiment execution.

## Validation limits

Local tests use real Git branches, protected-main rejection hooks, PR merge commits, and immutable tags.
Only GitHub PR API responses are modeled in the reviewed-route tests.
The full rehearsal also compiles exported packages and fresh consumers, including iOS builds.
Hosted App Pull requests write access, bot PR creation, required review, scheduled completion, and public customer upgrades need hosted evidence.
Local passing tests do not close these hosted gates or the dependency-monitoring acceptance gates.
