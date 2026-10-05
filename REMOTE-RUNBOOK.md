# Remote experiment runbook

Status: prepared, not executed. Complete repository approval before these remote steps.
The local rehearsal evidence does not close SDK-5388.

The remote proof also includes the [staged dependency-management procedure](docs/dependency-management/README.md). Run its local dependency checks and review package-local release markers before the updater trial. Use the [acceptance commands and hosted gates](docs/dependency-management/ACCEPTANCE.md). Its source/consumer graph checks and failure cases are required evidence; publication success alone is insufficient.

## Seed and preflight

1. Complete [REPOSITORY-REQUEST.md](REPOSITORY-REQUEST.md).
2. Review the prepared source and consumer histories and file lists.
3. Push the source and consumer `main` branches to their approved repositories.
4. Seed publication `main` from the approved source export; preserve immutable tags.
5. Do not push `.lab` histories, local rehearsal tags, local mirror files, or locks produced by local-mirror rehearsals. Review/regenerate public-URL source and consumer lockfiles for the dependency-graph test; follow the staged procedure.
6. Verify `main` is the default branch in all five repositories.
7. Confirm both origins and record the source and consumer `main` seed SHAs.
8. Create the protected environment, permit `main` runs, and configure the scoped App installation.
9. Confirm the Actions job can read only the intended credentials and repositories.
10. Set source variable `EXPERIMENTAL_RELEASES_ENABLED=true` after preflight and review.

Source and consumer have no GitHub `origin` configured locally. This prevents an accidental push to an unapproved destination.
Generated sibling repositories are local review snapshots. Remote publication must run the exporter against the selected source SHA.
A generated snapshot from a different source SHA is not a valid retry candidate.

## Branch model

All five repositories use default `main`. Release Please targets `main`.
The source and consumer require reviewed PRs after initial creation.
Generated publication updates also inherit the PR requirement. The publisher needs an explicitly approved App bypass or a reviewed update route. Contents write alone is insufficient. Keep release activation disabled until this is resolved.
Dispatch manual runs using `--ref main` and permit `main` in the release environment policy.
The local rehearsal protects a separate bootstrap branch. It does not prove hosted App bypass or ruleset behavior.

## Baseline manual release

1. Record the full reviewed source `main` SHA whose manifest versions are all `0.1.0`.
2. Dispatch `publish.yml` for `sdk`, version `0.1.0`, and that SHA.
3. Review and approve the environment job.
4. Verify the public SDK tag and GitHub Release.
5. Dispatch `publish.yml` for `sprig`, version `0.1.0`, and the same SHA.
6. Dispatch `publish.yml` for `firebase`, version `0.1.0`, and the same SHA.
7. Set consumer variable `EXPERIMENTAL_PACKAGES_AVAILABLE=true`.
8. Dispatch the consumer workflow.
9. Inspect the resolved public URLs, runtime versions, and iOS simulator build.
10. Save the consumer lockfiles and workflow evidence.

The publisher validates against public dependency URLs without the publication token in the SwiftPM process.
The consumer workflow has no credentials for the internal source monorepo.

## Establish the Release Please baseline

The initial scaffold is a hidden `chore` commit. It does not request a feature release.
Before the first post-baseline change, record the baseline source SHA reachable from `main` as `bootstrap-sha` in `release-please-config.json`.
Create matching source component baseline tags and GitHub Releases at the baseline SHA:
`sdk-0.1.0`, `integration-sprig-0.1.0`, and `integration-firebase-0.1.0`.
These source tags differ from the plain public package tags. Do not copy publication tags into source.
Review this baseline setup before enabling normal Release Please changes.

## Lifecycle validation

| Change | Expected publication | Consumer check |
| --- | --- | --- |
| Sprig fix | Sprig only | Select new Sprig version; keep SDK and Firebase exact versions |
| SDK fix | SDK only | Select new SDK version; keep integration versions |
| Shared-source fix with updated markers | Sprig and Firebase | Install both generated copies; check no module collision |
| Coordinated API change and raised `sdkMinimum` | SDK first, then integrations | Select compatible versions of all three packages |
| Reinstall baseline | No new publication | Fresh consumer still resolves every `0.1.0` tag |

Use actual `fix:`/`feat:` commits, review the Release Please PR, and merge only the intended package version changes.
Confirm Swift version constants, `version.txt`, and manifest versions agree before publication.
The configured `extra-files` paths are relative to each package path.
CI checks shared fingerprints before merge. A shared-source fix must include both marker files in the same reviewed fix commit.
Use the consumer dependency generator to prepare and review the upgrade. No automatic cross-repository consumer write is configured.

## Recovery validation

Use disposable refs for destructive failure tests. Preserve protected branches and immutable tags.

1. Test a missing publication repository and a token without access.
2. Test an unclassified or rejected local dependency.
3. Test a wrong version and an unavailable required SDK version.
4. Test an existing tag with different source or content.
5. Interrupt after the generated publication commit is pushed.
6. Retry with the original version and source SHA.
7. Confirm the publication commit is reused and the missing tag is added.
8. Interrupt after the public tag is pushed.
9. Retry with the original version and source SHA.
10. Confirm the tag is reused and only the missing GitHub Release is created.
11. Start two publication jobs for the same package.
12. Verify their concurrency group prevents overlapping writes.
13. Inject manual drift in a disposable test and confirm publication stops.
14. Attempt an update and deletion of a disposable tag under the configured ruleset.
15. Confirm the publisher App cannot address production repositories.

A workflow rerun may have no new Release Please outputs. Use the manual publisher with the original SHA and version to repair publication.
Never move an existing version tag. Keep drift failures for inspection; repair through a reviewed incident decision.
The three repositories are not one transaction. A completed SDK release can remain available if an integration later fails.
The repair path publishes the remaining integration from the same approved source.

## Evidence and teardown

Include dependency graph exports, actual default branches, effective rules, updater evidence, and vendor-only export/release/consumer checks from the staged procedure. Record any missing coverage explicitly. Do not close the dependency-management acceptance gate from build results alone.

Record repository URLs, source and publication SHAs, Release Please PRs, source tags, public tags, GitHub Releases, workflow runs,
consumer lockfiles, runtime output, iOS build output, failure/retry results, App scope, and repository rules.
Complete a final fresh baseline and latest-version consumer check.
Disable release workflows. Archive all public experiment repositories and preserve the evidence.
Remove the experiment from the App installation. Remove the protected environment and test credentials.
Archive or delete the internal source only after review. Do not reuse experiment names for production.

## Tool references

- [Release Please outputs](https://github.com/googleapis/release-please-action#outputs)
- [Release Please file updates](https://github.com/googleapis/release-please/blob/main/docs/customizing.md#updating-arbitrary-files)
- [GitHub App token action](https://github.com/actions/create-github-app-token)
- [Swift Collections fixture dependency](https://github.com/apple/swift-collections/tree/1.1.4)
