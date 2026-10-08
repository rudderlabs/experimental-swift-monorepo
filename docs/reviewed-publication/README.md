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
7. Run the central completion workflow after merge.
8. Verify the exact merge commit against the complete approved export.
9. Create the plain version tag at that verified merge commit.
10. Create the public GitHub Release.
11. Test an anonymous customer upgrade with SwiftPM and an iOS simulator build.

Step 7 is manual: run the completion workflow after merging a publication PR. The 15-minute schedule was removed on 2026-10-08 because it failed on every run.
The source workflow holds the credentials. Publication repositories need no relay workflow or secrets.
This central workflow replaces the proposed per-repository merge-event relay.

Source component releases are durable release intent. The completion workflow discovers incomplete publication from these releases.
It does not require transient Release Please action outputs, a PR comment, or a new source change.
Completed tag/release pairs are excluded from the recovery queue.
SDK work precedes integration work in the queue. Each integration also checks its required SDK tag before building.
An integration that needs an unpublished SDK reports `awaiting_dependency` and resumes on a later check.

## Publication boundaries

An open publication PR creates no public version tag or GitHub Release. Publication `main` keeps the previous package.
After the reviewed merge, branch-based customers can see the generated update before its tag exists.
This short interval is inherent in the reviewed PR route. Version-based customers remain on their selected immutable tags.
Source `main` can advance without entering the export. Publication `main` can advance without changing the selected merge commit.
A tag always identifies the verified merge commit, not whichever commit is currently at `main`.

The publisher compares all generated file hashes and the complete provenance record with a new deterministic export.
Updating a PR's hashes together with an unauthorized file change does not bypass this comparison.
It checks PR bot identity, allowlisted destination, source ancestry, and merged commit ancestry.
A closed, unmerged PR, a conflicting version branch, manual drift, or an existing tag conflict stops publication.
The publisher never force-pushes a publication branch or rewrites a version tag.

## States and recovery

| State | Meaning | Recovery |
| --- | --- | --- |
| `awaiting_review` | Valid generated PR exists; no tag is created | Review and merge; completion runs later |
| `awaiting_dependency` | Required SDK tag is unavailable | Complete SDK publication; run the completion workflow again |
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
