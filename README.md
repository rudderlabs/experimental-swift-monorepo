# Experimental Swift monorepo publication

Local preparation for [SDK-5388](https://linear.app/rudderstack/issue/SDK-5388), under [SDK-5384](https://linear.app/rudderstack/issue/SDK-5384).
This repository contains representative demo code, not imported production SDK code.
The original one-integration prototype remains at `/Users/denis/git/swift-monorepo-example`.

Dependency-management preparation (2026-09-22): [staged configuration and acceptance procedure](docs/dependency-management/README.md). The YAML template is dormant outside `.github`; dependency authority/release-marker checks are now implemented; hosted graph/updater validation remains pending. See the [acceptance commands and gates](docs/dependency-management/ACCEPTANCE.md). Activate only when the monorepo experiment resumes.

## Branch model

Use `dev` for source changes, Release Please PRs, consumer changes, and generated publication commits.
The organization keeps `main` locked. No workflow in this experiment writes to `main`.
Plain version tags still identify published SwiftPM packages; consumers do not select `dev` directly.
Source and consumer repositories need `dev` as their default branch for the prepared manual workflow entry points.
The publication repositories can keep `main` as default because the publisher explicitly selects `dev`.

## Run the complete local rehearsal

Requirements: macOS, Xcode, Swift 5.9 or later, Python 3.9 or later, and Git.
The iOS app requires an iOS 16 or later simulator. No signing account is needed.
The consumer template must be a sibling checkout named `experimental-swift-example-consumer-app`.
A network connection is needed for the public Swift Collections dependency.

```sh
swift test
python3 scripts/release_plan.py sync-shared --check
python3 scripts/rehearse.py --ios
```

The rehearsal creates a new `.lab/<timestamp>/` folder. It does not reset existing runs.
It uses real local Git commits, bare repositories, tags, SwiftPM resolution, and compiled consumers.
It models GitHub Release records as local JSON. It supplies release versions explicitly.
It does not execute Release Please, GitHub Actions, GitHub App permissions, or GitHub rulesets.
The rehearsal preserves a locked default `main` in each publication remote and proves all releases can use `dev`.
Each consumer has fresh SwiftPM state and no GitHub token or credential helper.
Only the local rehearsal configures public URL mirrors to the bare test repositories.
The generated package manifests retain the planned public URLs.

## Structure

| Path | Role |
| --- | --- |
| `Packages/DemoSDK` | SDK fixture, independent version, resources, privacy manifest |
| `Integrations/Sprig` | First integration fixture |
| `Integrations/Firebase` | Second integration fixture with public Swift Collections dependency |
| `Shared/DemoShared` | Source copied into each generated integration module |
| `release/packages.json` | Fixed publication destinations and dependency policies |
| `scripts/project.py` | Graph inspection and deterministic standalone export |
| `scripts/publish.py` | Build validation, immutable tag publication, drift check, recovery |
| `scripts/release_plan.py` | Affected package selection and reviewed shared-source markers |
| `scripts/rehearse.py` | Developer, maintainer, and customer lifecycle rehearsal |
| `.github/workflows` | Disabled-by-default remote workflow preparation |

## Developer path

1. Change canonical source in this repository.
2. Run `swift test`.
3. If shared source changes, run `python3 scripts/release_plan.py sync-shared`.
4. Include the changed marker files in the same `fix:` or `feat:` commit.
5. Review the affected integration paths in the commit.
6. Let Release Please prepare versions, Swift version constants, and changelogs after remote enablement.

Shared markers contain source hashes under each affected package path.
Release Please sees these path changes in the reviewed feature or fix commit.
CI rejects stale markers. No extra post-processing commit is added to a Release Please branch.
SDK-only work does not modify integration markers.
The SDK minimum requirement is explicit in each integration's inventory entry.
Update that requirement in a coordinated release when an integration needs a new SDK API.

## Maintainer path

Release Please targets `dev` and owns version intent. It creates component tags such as `sdk-0.1.1` in the source repository.
The publisher emits plain tags such as `0.1.1` in the corresponding public package repository.
SDK publication completes before dependent integration jobs start.
An integration-only release skips the SDK job.
Publication jobs use a fixed inventory, an environment-scoped App token, and one concurrency group per package.
A retry must use the original source SHA and version. A newer SHA cannot reuse the same version.
The manual workflow is also the recovery entry point if Release Please outputs are absent on rerun.

See [REMOTE-RUNBOOK.md](REMOTE-RUNBOOK.md) before remote execution.
See [REPOSITORY-REQUEST.md](REPOSITORY-REQUEST.md) for the exact provisioning request.

## Customer path

The independent consumer installs the three public package URLs with exact versions.
The command-line demo asserts runtime versions, normalized events, vendor deduplication, and SDK resource access.
The iOS app displays installed versions and invokes the same products.
Use the consumer's `scripts/dependencies.py --set sprig=0.1.1` to prepare an upgrade.
Review the generated manifests and `Package.resolved` before committing a public consumer upgrade.

## Boundaries still to prove remotely

- Real Release Please PR creation, merge events, and ordered workflow execution.
- Anonymous public clones with no local mirror or source-repository access.
- GitHub App installation scope, missing access, and environment approvals.
- Branch and immutable tag rules, including attempted tag update and deletion.
- Real GitHub Release creation and interruption recovery.
- GitHub concurrency behavior and retained Actions artifacts.
- Archival, credential revocation, and final old-version resolution.

The fixtures cover Swift source, explicit resources, and a source-based external vendor product.
They do not prove the real Firebase/Sprig binaries, the core SDK's complete resources, or all production platforms.
SDK-5385, SDK-5386, and SDK-5387 remain dependent on the remote proof.
