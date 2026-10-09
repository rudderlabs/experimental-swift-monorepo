# Experimental Swift monorepo publication

Local preparation for [SDK-5388](https://linear.app/rudderstack/issue/SDK-5388), under [SDK-5384](https://linear.app/rudderstack/issue/SDK-5384).
This repository contains representative demo code, not imported production SDK code.

**Status (2026-10-08):** the demo packages moved to `Tests/Fixtures/demo/` and are now test data only. The root has no packages until the real SDK, Sprig and Firebase are imported. Releases are paused (`EXPERIMENTAL_RELEASES_ENABLED=false`) and completion is manual (no schedule). The `.lab` rehearsal below targets the old demo layout and is rewritten in a later step.
The original one-integration prototype remains at `/Users/denis/git/swift-monorepo-example`.

Dependency-management preparation (2026-09-22): [staged configuration and acceptance procedure](docs/dependency-management/README.md). The YAML template is dormant outside `.github`; dependency authority/release-marker checks are now implemented; hosted graph/updater validation remains pending. See the [acceptance commands and gates](docs/dependency-management/ACCEPTANCE.md). Activate only when the monorepo experiment resumes.

## Branch model

Use `main` for source, Release Please, the independent consumer, and generated publication commits.
Source merges do not publish packages. Only approved releases update generated repositories.
See [release boundaries and acceptance checks](docs/release-boundaries/README.md).
Initial branch creation succeeded. Subsequent source and consumer changes require reviewed PRs.
Publication updates use bot-created PRs under the inherited PR rule. After merge, a central workflow verifies and tags the approved export.
See [reviewed publication and recovery](docs/reviewed-publication/README.md).
Plain version tags identify published SwiftPM packages.
Remote execution is gated by `EXPERIMENTAL_RELEASES_ENABLED`. Hosted permission and publication checks remain required evidence.

## Run the complete local rehearsal

Requirements: macOS, Xcode, Swift 5.9 or later, Python 3.9 or later, and Git.
The iOS app requires an iOS 16 or later simulator. No signing account is needed.
The consumer template must be a sibling checkout named `experimental-swift-example-consumer-app`.
A network connection is needed for the public Swift Collections dependency.

```sh
python3 -m unittest discover -s Tests -p 'test_*.py'
python3 scripts/release_plan.py sync-shared --check
python3 scripts/rehearse.py --ios
```

The rehearsal creates a new `.lab/<timestamp>/` folder. It does not reset existing runs.
It uses real local Git commits, bare repositories, tags, SwiftPM resolution, and compiled consumers.
It models GitHub Release records as local JSON. It supplies release versions explicitly.
It does not execute Release Please, GitHub Actions, GitHub App permissions, or GitHub rulesets.
The rehearsal publishes on default `main`, retains a protected bootstrap fixture, and freezes `develop` for compatibility tests. It checks unpublished source changes and exports a fixed approved SHA after source `main` advances.
Each consumer has fresh SwiftPM state and no GitHub token or credential helper.
Only the local rehearsal configures public URL mirrors to the bare test repositories.
The generated package manifests retain the planned public URLs.

## Structure

| Path | Role |
| --- | --- |
| `Tests/Fixtures/demo` | Demo SDK, Sprig, Firebase and shared code, used as test data only |
| `release/packages.json` | The only package list: paths, components, targets, platforms and dependency policies |
| `release/allowlist.json` | Reviewed write targets (package key to repository); a key without a package is reserved |
| `release/texts.json` | The only source of release, bot PR and commit texts and the ticket link |
| `release/templates` | Generated CONTRIBUTING.md, `.github/CODEOWNERS` and README block added to every export |
| `scripts/check_inventory.py` | CI check: package list, allowlist, Release Please entries, generated files and action SHA pins agree |
| `scripts/generate_github.py` | Regenerates issue forms, `labeler.yml` and `labels.json` from the package list (`--check` in CI) |
| `scripts/project.py` | Graph inspection and deterministic standalone export |
| `scripts/publish.py` | Build validation, immutable tag publication, drift check, recovery; `--mode` normal, takeover or bootstrap |
| `scripts/reviewed_publication.py` | Bot PRs, takeover and bootstrap checks, merged-version verification from stored provenance |
| `scripts/publication_queue.py` | Recover queue: reports and skips a broken item, never rebuilds an open bot PR |
| `scripts/anchor.py` | Validates an anchor tag request for `anchor-package.yml` |
| `scripts/release_plan.py` | Affected package selection and reviewed shared-source markers |
| `scripts/rehearse.py` | Developer, maintainer, and customer lifecycle rehearsal |
| `.github/workflows` | Gated release, reviewed publication, and manual recovery workflows |

## Developer path

1. Change canonical source in this repository.
2. Run the Python tests (`python3 -m unittest discover -s Tests -p 'test_*.py'`).
3. If shared source changes, run `python3 scripts/release_plan.py sync-shared`.
4. Include the changed marker files in the same `fix:` or `feat:` commit.
   After changing `release/packages.json`, run `python3 scripts/generate_github.py` and `python3 scripts/check_inventory.py`.
5. Review the affected integration paths in the commit.
6. Let Release Please prepare versions, Swift version constants, and changelogs after remote enablement.

Shared markers contain source hashes under each affected package path.
Release Please sees these path changes in the reviewed feature or fix commit.
CI rejects stale markers. No extra post-processing commit is added to a Release Please branch.
SDK-only work does not modify integration markers.
Each marker lists only the files of the shared targets that package vendors, so a change to one shared target selects only its vendoring integrations.
Shared code uses Swift's `package` access level, never `public` or `open`. `sync-shared` (and CI's `--check`) rejects a `public`/`open` declaration under `Shared/`, and export rejects it in vendored code.
Export removes imports of vendored modules (including `@_exported`/`@testable` and `import struct Module.Type` forms); each integration then owns a private copy, so two integrations in one app never collide.
`RUN_SWIFT_BUILD_TESTS=1` additionally builds two exported integrations and a consumer of both (offline, about 15 seconds; CI sets it).
The SDK minimum requirement is explicit in each integration's inventory entry.
Update that requirement in a coordinated release when an integration needs a new SDK API.
Export fails if a package has an `external` policy but no `sdkMinimum`.
Each inventory entry also sets its own `platforms` (for example `["iOS 15"]`) and `toolsVersion` (for example `"5.9"`).
The generated manifest uses exactly those, never the root manifest's values.
Before any publication write, the publisher builds the exported package with `xcodebuild` for every declared platform (generic device destinations, unsigned, anonymous, temporary caches). PR CI builds only the iOS Simulator.
Resources keep their `process` or `copy` rule from `swift package dump-package`. Folder resources are copied whole and listed by relative path in the inventory.

## Maintainer path

Release Please targets `main` and owns version intent. It creates component tags such as `sdk-0.1.1` in the source repository.
The publisher emits plain tags such as `0.1.1` in the corresponding public package repository.
Dependent integrations wait until their required SDK tag is available. The recovery workflow resumes pending publication.
An integration-only release skips the SDK job.
`release-please.yml` turns the path-based Release Please outputs into a plan (`release_plan.py from-outputs`): a `publish (sdk)` job, then one matrix job with a `publish (<key>)` leg per released integration. No workflow lists package names.
Publication jobs take destinations only from `release/allowlist.json` (every package must be allowlisted with its own repository), use an environment-scoped App token, and run in one concurrency group per package.
Adding a package needs only its `release/packages.json` entry, its allowlist entry, and the regenerated GitHub files.
A retry must use the original source SHA and version. A newer SHA cannot reuse the same version.
The manual workflow is also the recovery entry point if Release Please outputs are absent on rerun.

**Merged a bot PR? Press Recover.** Recover is `complete-publication.yml` (Actions → Run workflow, no inputs): every run scans all packages, tags merged versions and creates their Releases. A broken item is reported and skipped; the others still complete. An open bot PR stays `awaiting_review` and is never rebuilt.
Package states: `awaiting_review`, `awaiting_dependency`, `awaiting_takeover`, `published`, `incomplete`.
A public repository without `.publication.json` waits as `awaiting_takeover` (other packages continue) until a person removes `.github/workflows` by PR and dispatches `publish.yml` with `mode=takeover`: one bot PR, no tag, `Sources/` byte-identical to the existing tag and `Package.swift` semantically equal. A README-only repository gets a bootstrap bot PR automatically (`mode=bootstrap` forces it).
`anchor-package.yml` (manual: package, version, main SHA) creates a plain `<component>-<version>` tag and no Release, so nothing is queued or published.
Every export adds a generated CONTRIBUTING.md, `.github/CODEOWNERS` (`* @rudderlabs/sdk_team`) and a README block linking to monorepo issues; `.publication.json` records a `transform` per file. No workflow file is ever exported.
Bot commits use the App identity `rudderstack-github-actions[bot]`; a merged version is verified against its own stored `.publication.json`, so Recover survives exporter changes.

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

The fixtures cover Swift source, explicit file and folder resources, per-package platforms, and source-based external vendor products.
They do not prove the real Firebase/Sprig binaries, the core SDK's complete resources, or all production platforms.
SDK-5385, SDK-5386, and SDK-5387 remain dependent on the remote proof.
