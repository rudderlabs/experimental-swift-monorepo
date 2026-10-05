# Single main branch release strategy

Owner: SDK team. Decision date: 2026-10-05. Scope: SDK-5388 experiment. Production cutover remains subject to SDK-5386 validation and SDK-5387 approval.

Use one long-lived `main` branch. Short-lived feature and release PR branches remain necessary. Source `main` contains reviewed code awaiting release. Generated repository `main` contains only approved, validated package exports. Existing customer package URLs and immutable version tags remain the release contract.

A normal source merge may update a Release Please PR. It must not change generated package refs. Publication jobs require the package-specific `release_created` output to equal `true`. Merging a release PR approves the included package changes; code not suitable for the next package release remains outside source `main`.

## Release intent and customer publication

Source component tags and GitHub releases are internal release intent. They do not prove a customer package was published. The customer package becomes available to version-based SwiftPM consumers when its plain semantic version tag is served by the package repository. GitHub release metadata follows that tag; an error after tag creation cannot be described as no publication.

The publisher uses the approved source commit SHA, not the latest source `main`. The workflow checks out current tooling separately from the approved source snapshot so older approved commits remain retryable. Publication succeeds only after build validation, served-tag verification, and matching release metadata. Existing version tags never move.

The workflow reports `no_release`, `published`, or `incomplete`. Every requested package must return matching package, version, source SHA, served tag, and publication SHA for batch status `published`. Failed, cancelled, skipped, missing, or mismatched package jobs produce `incomplete`. A partial batch preserves successfully published packages. Inspect actual refs before retrying incomplete jobs; a failed job may already have published a tag.

## Acceptance checks

| ID | Check | Local proof | Required hosted proof |
| --- | --- | --- | --- |
| SB-01 | Source changes remain unpublished while release PR is open | Source commits leave all publication refs unchanged; fresh version/main/develop consumers retain the previous package | Merge an ordinary source fix, leave the real Release Please PR open, compare every publication branch/tag/ref |
| SB-02 | Approved releases select only affected packages | Existing six release scenarios and package-output adapter; explicit release-created gate | Merge the real release PR and verify independent versions, unchanged unrelated tags, and source-to-publication provenance |
| SB-03 | Advancing source main cannot alter an approved release | Commit a later source change, publish a detached approved snapshot, prove newer code is absent | Advance main while the release is waiting on approval; verify the recorded release SHA and exported hashes |
| SB-04 | Failures do not report successful publication | Build failure leaves refs unchanged; after-commit/after-tag recovery records true availability; failed/partial job summaries remain incomplete | Exercise App/rules/build/API failures and retries, verify artifacts and no false success announcement |
| SB-05 | Version and branch consumer behavior remains explicit | Fresh version/main/frozen-develop consumers and old-version reinstall | Verify real public version/main consumers; model frozen develop on a disposable experimental ref only |
| SB-06 | Dependency monitoring distinguishes development from shipped packages | Dependency guards and separate source/consumer evidence | Verify actual graph ingestion on default main in all five repositories; retain gaps instead of reporting zero findings |

Local Git supplies release versions and models GitHub release metadata. It does not execute Release Please or prove hosted permission, environment, alert, or graph behavior. The frozen develop branch is a compatibility fixture; it is not a second active development branch.

## Production migration requirements

Inspect the core SDK and all seven integrations before import: Adjust, AppsFlyer, Braze, CleverTap, Facebook, Firebase, and Sprig. Preserve repository URLs, product names, platform support, resources/binaries, package identities, dependency requirements, historical refs, and plain semantic version tags. Generated production commits must extend existing public history; do not repeat the empty experimental repository bootstrap in production.

The core SDK currently uses custom draft/publish workflows that draft from develop or hotfix branches, publish release branches into main, and back-merge into develop. Replace or disable those release writers at cutover so only the approved monorepo publisher creates package versions. Retain appropriate pre/post-release tests; the shared test rig accepts explicit tags, branches, and commits.

Reconcile both main and develop before selecting import SHAs. Braze main requires vendor 18.2.0 while develop still requires 14.0.0. Several integration develop branches contain manifest CI absent from main. CleverTap currently defaults to develop and also has live-test wiring there. Carry these checks into the monorepo or generated validation route; audit default-branch rules before changing CleverTap's default.

Keep production develop refs unchanged during initial migration. Version consumers retain immutable releases. Main consumers must receive only approved exports. Frozen-develop consumers retain the old snapshot; deleting those branches is a later compatibility decision. Public repository inspection cannot establish every customer's private dependency selection.

The experimental publisher has a fixed experimental destination allowlist. Production use requires a separately reviewed inventory, existing-history bootstrap, graph inputs, and writer permissions. The existing organization PR rule is not bypassed by Contents write. Select an explicitly approved App bypass or reviewed publication update route before activation.

## References

- [Release Please release PR behavior](https://github.com/googleapis/release-please#whats-a-release-pr)
- [Release Please component outputs](https://github.com/googleapis/release-please-action#outputs)
- [SwiftPM dependency requirements](https://docs.swift.org/package-manager/PackageDescription/PackageDescription.html#package-dependency-requirement)
- [Core SDK draft workflow](https://github.com/rudderlabs/rudder-sdk-swift/blob/eb66043ed1bd2da3bc72b7387dbd80b5060de36c/.github/workflows/draft-new-release.yml)
- [Core SDK publication workflow](https://github.com/rudderlabs/rudder-sdk-swift/blob/eb66043ed1bd2da3bc72b7387dbd80b5060de36c/.github/workflows/publish-new-release.yml)
- [Braze released main manifest](https://github.com/rudderlabs/integration-swift-braze/blob/880480351a8409826b259e722b6091688804775d/Package.swift)
- [Braze develop manifest](https://github.com/rudderlabs/integration-swift-braze/blob/71d1364b410986f13e7a9ade04bdc32455098e1d/Package.swift)
