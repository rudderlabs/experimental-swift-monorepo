# Experimental Swift monorepo publication

Local preparation for [SDK-5388](https://linear.app/rudderstack/issue/SDK-5388), under [SDK-5384](https://linear.app/rudderstack/issue/SDK-5384).
This repository contains representative demo code, not imported production SDK code.

**Status (2026-10-08):** the demo packages moved to `Tests/Fixtures/demo/` and are now test data only. The root has no packages until the real SDK, Sprig and Firebase are imported. Releases are paused (`EXPERIMENTAL_RELEASES_ENABLED=false`) and completion is manual (no schedule).
The original one-integration prototype remains at `/Users/denis/git/swift-monorepo-example`.

Dependency-management preparation (2026-09-22): [staged configuration and acceptance procedure](docs/dependency-management/README.md). The YAML template is dormant outside `.github`; dependency authority/release-marker checks are now implemented; hosted graph/updater validation remains pending. See the [acceptance commands and gates](docs/dependency-management/ACCEPTANCE.md). Activate only when the monorepo experiment resumes.

## Getting started

1. Clone this repository.
2. Run `make prepare` once per clone: it checks Xcode 16+, Python 3.9+, SwiftLint and git-filter-repo (with install hints), turns on the repository git hooks (`core.hooksPath`, this clone only) and resolves the vendor packages. It prints `Ready`; re-running it is safe.
3. Open `Package.swift` in Xcode. There is no root `Package.swift` until the first package is imported (P4); until then the repository holds only the release tooling.

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

Requirements: macOS, Xcode, Swift 5.9 or later, Python 3.9 or later, and Git. No network or GitHub access is needed.
`--ios` also builds the consumer template's iOS app; it needs an iOS 16 or later simulator runtime and a sibling checkout named `experimental-swift-example-consumer-app` (or `--consumer-template <path>`). No signing account is needed.

```sh
python3 -m unittest discover -s Tests -p 'test_*.py'
python3 scripts/rehearse.py          # about 4 minutes; --quick skips the xcodebuild platform builds
python3 scripts/rehearse.py --ios    # also the iOS Simulator consumer
```

Each run copies `Tests/Fixtures/demo` into a throwaway monorepo under a new `.lab/<timestamp>/` folder (`.lab/latest.json` points to it; earlier runs are never reset), creates one local bare "public" repository per allowlisted package (SDK and Firebase README-only, Sprig with foreign files, `.github/workflows` and tag `0.1.1`), and runs the real `publication_queue.py` and `publish.py` code paths step by step. Each step stops the run with its name on the first failed check; `evidence.json` records every Tag & Release Packages result, job result and check.

| Step | Proves |
| --- | --- |
| 1 | A README-only repository gets a bootstrap bot PR; Tag & Release Packages never rebuilds the open PR; after merge it tags the merge commit and creates the Release |
| 2 | A foreign repository waits as `awaiting_takeover`; takeover refuses while `.github/workflows` exists, then (after a person removes it) opens one PR with `Sources/` byte-identical to the old tag; no tag moves |
| 3 | An integration release: export, build, bot PR, merge, Tag & Release Packages tags it with matching provenance and Release body |
| 4 | An integration-only release leaves the SDK repository untouched, and an SDK-only release leaves the integrations untouched |
| 5 | An integration that needs an unpublished SDK version waits as `awaiting_dependency`, then continues once the SDK tag exists |
| 6 | A broken source release (off `main`) is reported and skipped while another package completes in the same Tag & Release Packages run |
| 7 | A hand edit in a public repository blocks publication before any branch, PR or tag; after a reviewed revert it publishes |
| 8 | Running Tag & Release Packages again changes no ref, PR or Release |
| 9 | Old tags (SDK, the pre-monorepo Sprig tag, Firebase) resolve and run in clean consumers, one package at a time |

Real: Git commits, merges, branches and tags; pre-receive hooks that reject `main` pushes and tag moves; export; `swift build` and the `xcodebuild` platform builds; the `dump-package` takeover check; fresh SwiftPM consumers with no credentials.
Modeled: `gh` (repository identity, bot PRs, Releases) as local JSON through a `gh` shim on `PATH`; Release Please as version commits, component tags and source Release records; reviewed merges as a reviewer clone plus a server-side `main` update; the App bot user id; Swift Collections as a local stand-in tag. Every `github.com` URL is rewritten to the local bare repositories or to a path that does not exist.
Not covered: GitHub Actions, App permissions, rulesets, environments, Release Please itself, anonymous public access, and reverse sync (ingest is not implemented; step 7 reverts the hand edit instead).
`RUN_SWIFT_BUILD_TESTS=1` runs steps 0 to 3 (`--quick`) in the unit suite.

## Structure

| Path | Role |
| --- | --- |
| `Tests/Fixtures/demo` | Demo SDK, Sprig, Firebase and shared code, used as test data only |
| `release/packages.json` | The only package list: paths, components, targets, platforms and dependency policies |
| `release/allowlist.json` | Reviewed write targets (package key to repository); a key without a package is reserved |
| `release/texts.json` | The only source of Release, bot PR and commit texts (rendered by `scripts/release_notes.py` from each package's CHANGELOG.md) |
| `release/templates` | Generated CONTRIBUTING.md, `.github/CODEOWNERS` and README block added to every export |
| `Makefile` | Developer commands (`make prepare`, `make sync`, `make check`, `make test`, `make affected`, `make lint`, `make new-integration`, `make import-integration`); thin wrappers over `scripts/` |
| `scripts/git-hooks` | `pre-commit` (marker sync for `Package.swift`, `release/` and `Shared/` commits; SwiftLint), `commit-msg` (PR-title rules), `pre-push` (branch name; from a terminal, the tests CI's plan selects since `origin/main`: `make test PKG=<key>` per affected package, `make test-python` for tooling changes, nothing for docs; no fetch, so `git fetch origin` first). Each runs the global hook of the same name first |
| `scripts/ci_plan.py` | PR CI plan and `make affected`: which packages to test and export, and whether the policy job runs |
| `scripts/package_ci.py` | PR CI jobs and `make test`/`make lint`: iOS Simulator tests, export check, lint, scope hint, `ci-ok` |
| `scripts/ci/pick-simulator.sh` | First available iPhone on the newest iOS runtime (no hardcoded device) |
| `scripts/scaffold.py` | `make new-integration`: a new package with its inventory, Release Please and root `Package.swift` entries |
| `scripts/import_package.py` | `make import-integration`: imports a repository at a tag, or at a later non-code-only `REF` (history or snapshot), without a Release Please entry |
| `scripts/dependabot_sync.py` | Releasable title for a Dependabot PR whose markers changed (`dependabot-sync.yml`) |
| `scripts/check_inventory.py` | CI check: package list, allowlist, Release Please entries, generated files and action SHA pins agree |
| `scripts/generate_github.py` | Regenerates issue forms, `labeler.yml` and `labels.json` from the package list (`--check` in CI) |
| `scripts/project.py` | Graph inspection and deterministic standalone export |
| `scripts/publish.py` | Build validation, immutable tag publication, drift check, recovery; `--mode` normal, takeover or bootstrap |
| `scripts/reviewed_publication.py` | Bot PRs, takeover and bootstrap checks, merged-version verification from stored provenance |
| `scripts/release_notes.py` | Release and publish-PR notes from the package CHANGELOG.md section, in the standalone repositories' format |
| `scripts/publication_queue.py` | Tag & Release Packages queue: reports and skips a broken item, never rebuilds an open bot PR |
| `scripts/anchor.py` | Validates an anchor tag request for `anchor-package.yml` |
| `scripts/release_plan.py` | Affected package selection and reviewed shared-source markers |
| `scripts/rehearse.py` | Offline lifecycle rehearsal on temporary fixture repositories (`.lab/<timestamp>/`) |
| `.github/workflows` | PR CI (`ci.yml`, `pr-title.yml`), gated release, reviewed publication, and manual recovery workflows |

## Developer path

1. Change canonical source in this repository on a `<type>/<name>` branch (for example `fix/sprig-empty-traits`).
2. Commit. With `make prepare` done, the pre-commit hook runs the matching sync when the commit stages `Package.swift`, `release/packages.json`, `release/allowlist.json` or `Shared/` and adds the regenerated markers and generated files to the same commit; other commits run no sync. Without the hooks, run `make sync` and include its changes yourself (CI rejects stale markers).
3. Run `make check test` (the CI policy checks, the Python tests and the iOS Simulator package tests; `make test PKG=sprig` runs one package). `make affected` previews which packages the branch changes; `make lint` runs SwiftLint on the changed files.
4. Review the affected integration paths in the commit.
5. Let Release Please prepare versions, Swift version constants, and changelogs after remote enablement.

Commit messages and PR titles: `<type>(<optional scope>)<optional !>: <description>` with types `feat` `fix` `refactor` `perf` `style` `test` `docs` `chore` `build` `ci` `revert`, a description that starts lowercase and has no trailing period, at most 100 characters (`Merge …` and `Revert "…"` are allowed). The `commit-msg` hook and the `pr-title` check apply the same rules. The scope is cosmetic: folders decide what releases, and `scope-hint` only warns when the scope names a package the PR does not touch.

### PR checks

`ci.yml`: `policy` (the `make check` policy checks and the Python tests with `RUN_SWIFT_BUILD_TESTS=1`), `lint` (SwiftLint `--strict` with the root `.swiftlint.yml`; `Tests/`, `Examples/` and manifests are excluded, so the fixtures are not linted), one `test (<key>)` job per package (`xcodebuild test` on the iOS Simulator; a scheme written into the git-ignored `.swiftpm/` for the run holds only that package's test targets, so the job builds only what it tests) and one `export (<key>)` job per package (export, manifest check, generic iOS build). The package jobs are skipped while `release/packages.json` is empty. `ci-ok` needs all of them and fails if any failed or was cancelled; a skipped job passes.
A push to `main` runs every job for every package. A pull request runs only what it affects (`ci_plan.py --base <sha>`, D34; try it locally with `--base origin/main`): a package folder (or the shared code it vendors) tests and exports that package, and also tests every package that depends on it, so an SDK change tests every integration. A `release/packages.json` change is compared entry by entry with the PR base: an added, removed or changed package entry selects that package the same way (tested with its dependents, exported alone), a change outside `packages` (for example `schemaVersion`) or a file missing at the base selects every package, and a reformat or reorder selects none. Shared build inputs (root `Package.swift`/`Package.resolved`, `.swiftlint.yml`, `release/allowlist.json`, `ci.yml`, `scripts/ci/` and the package-job runner `package_ci.py` with the scripts it imports) select every package, while a change to the plan itself (`ci_plan.py`, `release_plan.py`, the git hooks or `Makefile`) runs only `policy`; `LICENSE` and `release/templates/` re-export every package without tests; docs (`*.md`, `docs/`) select none. `policy` runs only when `scripts/`, `release/`, `Tests/`, `.github/`, `Shared/`, `Makefile`, the root manifest or lock file, a `dependency-requirements.json`/`shared-source.json` marker or the Release Please files change. `lint` always runs.
`pr-title.yml`: `pr-title` (`rudderlabs/github-action-check-pr-title`, as in `rudder-sdk-swift`) and the warning-only `scope-hint`.
Required status checks on `main` (an admin sets them): `ci-ok` and `pr-title` only, because the matrix job names change as packages are added.

The root `Package.swift` is the development manifest for every package. Its `// @integrations-products`, `// @integrations-dependencies` and `// @integrations-targets` anchors mark where the commands below add lines (the core SDK sits above them); the first command creates the manifest if it is missing.

- **New integration (Path B):** `make new-integration NAME=Braze [PLATFORMS="iOS 15,tvOS 15"] [SDK_MIN=1.4.1] [VENDOR_URL=… VENDOR_PRODUCTS=… VENDOR_FROM=…]`. The key (`braze`) must already be in `release/allowlist.json` (sdk_team approval). It writes `Integrations/Braze/` (source and test templates, `version.txt`, `CHANGELOG.md`, `README.md`), the inventory entry (platforms default `iOS 15`, `sdkMinimum` default the SDK's current version), the Release Please config entry and the root manifest lines, then runs `make sync`. The version placeholder is `0.0.0` with no manifest entry, so the first release PR is `1.0.0` (no `Release-As`).
- **Import (Path A):** `make import-integration REPO=experimental-integration-swift-sprig TAG=1.0.0 NAME=Sprig MODE=history|snapshot` (`KIND=core` for the SDK, into `Packages/<Name>`). History mode clones with `--no-local`, rewrites the clone under the package folder with `git filter-repo` (old tags become `legacy/<key>/<tag>` and stay out of the monorepo) and starts a merge of the tag with `--allow-unrelated-histories`; snapshot mode copies the files at the tag. Both remove nested `Package.swift`, `Package.resolved`, `.swiftpm/`, `.github/`, root Xcode projects and per-repository license, CODEOWNERS and hook files, move `Example(s)/` to `Examples/<Name>/` (local package references point at the monorepo root), and add the version files, the inventory entry (version from the tag, `sdkMinimum` from the imported `rudder-sdk-swift` requirement) and the root manifest lines. There is no Release Please entry. The result is staged, never committed or pushed; the command prints the commit and the three Path A steps (import PR with a merge commit for history, anchor tag `<component>-<tag>`, `build(<key>): enable releases`). History mode needs `git-filter-repo`. `REF=<branch-or-sha>` (e.g. `REF=main`) imports that commit instead of the tag, at the tag's version: the tag must be an ancestor of `REF`, nothing under `Sources/` or outside the non-code allowlist (`*.md`, `LICENSE*`, `CODEOWNERS`, `.github/`, `docs/`, `.gitignore`) may differ, and a changed `Package.swift` must dump the same products, targets, dependencies, platforms and tools version; otherwise the import fails before the monorepo changes. The differing non-code files are printed and belong in the import PR body.
- `dependabot-sync.yml` runs `make sync` on a Dependabot PR that changes `Package.swift`, pushes the markers with the release bot token (`RELEASE_PRIVATE_KEY` stored as a Dependabot secret) and retitles the PR, for example `fix(firebase): bump firebase-ios-sdk to 13.0.0`.

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
Before any publication write, the publisher builds the exported package with `xcodebuild` for every declared platform (generic device destinations, unsigned, anonymous, temporary caches), plus a host `swift build` when the package declares macOS. PR CI builds only the iOS Simulator. A takeover builds nothing: it republishes the code already public at the existing tag, so it checks identity (byte-identical `Sources/`, same `Package.swift` meaning); the next release runs every build.
Resources keep their `process` or `copy` rule from `swift package dump-package`. Folder resources are copied whole and listed by relative path in the inventory.

## Maintainer path

Release Please targets `main` and owns version intent. It opens one release PR per package, so a package can be released alone, and creates component tags such as `sdk-0.1.1` in the source repository.
Release how-tos (release one package alone, `Release-As`, roll forward a bad version, public activity, sync back an outside PR, discard an unpublished version): [Maintainer how-tos](docs/reviewed-publication/README.md#maintainer-how-tos).
The publisher emits plain tags such as `0.1.1` in the corresponding public package repository.
Dependent integrations wait until their required SDK tag is available. The recovery workflow resumes pending publication.
An integration-only release skips the SDK job.
`release-please.yml` turns the path-based Release Please outputs into a plan (`release_plan.py from-outputs`): a `publish (sdk)` job, then one matrix job with a `publish (<key>)` leg per released integration. No workflow lists package names.
Publication jobs take destinations only from `release/allowlist.json` (every package must be allowlisted with its own repository), use an environment-scoped App token, and run in one concurrency group per package.
Adding a package needs only its `release/packages.json` entry, its allowlist entry, and the regenerated GitHub files; `make new-integration` and `make import-integration` write them.
A retry must use the original source SHA and version. A newer SHA cannot reuse the same version.
The manual workflow is also the recovery entry point if Release Please outputs are absent on rerun.

**Merged a bot PR? Run Tag & Release Packages** (`complete-publication.yml`, Actions → Run workflow, no inputs): every run scans all packages, tags merged versions and creates their Releases. A broken item is reported and skipped; the others still complete. An open bot PR stays `awaiting_review` and is never rebuilt.
Package states: `awaiting_review`, `awaiting_dependency`, `awaiting_takeover`, `published`, `incomplete`.
A public repository without `.publication.json` waits as `awaiting_takeover` (other packages continue) until a person removes `.github/workflows` by PR and dispatches `publish.yml` with `mode=takeover`: one bot PR, no tag, `Sources/` byte-identical to the existing tag and `Package.swift` semantically equal. A README-only repository gets a bootstrap bot PR automatically (`mode=bootstrap` forces it).
`anchor-package.yml` (manual: package, version, main SHA) creates a plain `<component>-<version>` tag and no Release, so nothing is queued or published.
Every export adds a generated CONTRIBUTING.md, `.github/CODEOWNERS` (`* @rudderlabs/sdk_team`) and a README block that welcome issues and pull requests in the public repository (maintainers sync merged ones back); `.publication.json` records a `transform` per file. No workflow file is ever exported.
Bot commits use the App identity `rudderstack-github-actions[bot]`; a merged version is verified against its own stored `.publication.json`, so Tag & Release Packages survives exporter changes.

See [REMOTE-RUNBOOK.md](REMOTE-RUNBOOK.md) before remote execution.
See [REPOSITORY-REQUEST.md](REPOSITORY-REQUEST.md) for the exact provisioning request.

## Customer path

The independent consumer installs the three public package URLs with exact versions.
The macOS command-line demo configures `RudderStackAnalytics` with the Firebase integration (Sprig is iOS only).
The iOS app links all three products. Versions are checked through `Package.resolved` pins, since the SDKs keep version constants internal.
Use the consumer's `scripts/dependencies.py --set sprig=1.0.1 --set sdk=1.2.1` (one `--set` per package) to prepare an upgrade.
Review the generated manifests and `Package.resolved` before committing a public consumer upgrade.
After a publication, `scripts/verify_public_customer.py <package> <version> <evidence-dir>` clones the consumer's `main` anonymously and runs that upgrade with an iOS Simulator build.
Add `--consumer <checkout>` to test an unmerged consumer change locally; packages still resolve from the public URLs.

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
