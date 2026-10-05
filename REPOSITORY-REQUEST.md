# Repository creation request — SDK-5388

Prepared: 2026-09-06. Status: creation request draft; visibility recorded in SDK-5388; repositories created; remote controls pending. Owner: SDK team.

Create the following repositories in `rudderlabs` for the [experimental SwiftPM publication proof](https://linear.app/rudderstack/issue/SDK-5388).
All five repositories have been created as Public, with default `main`.
The initial source push succeeded. Use `main` for CI, Release Please, and generated publications.
Source and consumer updates require reviewed PRs. Repeated publication updates require an explicitly approved publisher App bypass or a reviewed update route; Contents write does not bypass the inherited rule.
The local source, consumer, and generated package preparation already exists under `/Users/denis/git/swift-monorepo-spm-lab`.

| Repository | Visibility | Purpose | After review |
| --- | --- | --- | --- |
| `experimental-swift-monorepo` | Internal | Canonical demo source, independent release intent, exporter, publisher | Archive or delete after evidence review |
| `experimental-rudder-sdk-swift` | Public | Generated SDK fixture and plain semantic version tags | Archive |
| `experimental-integration-swift-sprig` | Public | Generated first integration | Archive |
| `experimental-integration-swift-firebase` | Public | Generated second integration with public vendor dependency | Archive |
| `experimental-swift-example-consumer-app` | Public | Independent SwiftPM and iOS consumer | Archive |

Internal visibility for the experimental source monorepo replaces the earlier Private proposal.
This is a temporary choice while validating the setup. The architecture also supports a public source monorepo.
The production source monorepo is expected to be Public, with existing public SDK and integration publication repositories retained.
No Private repository is requested for this experiment.

All public repositories must state that the packages are temporary and unsupported.
Do not add these packages to a Swift registry or the Swift Package Index.

## Access and repository controls

1. Give the SDK team access to review and maintain the source and consumer repositories.
2. Enable GitHub Actions and macOS runners for the experiment.
3. Create a dedicated GitHub App with access to the source and three publication repositories only.
4. Grant source tokens `Metadata: read`, `Contents: write`, and `Pull requests: write`.
5. Grant publication tokens only `Metadata: read` and `Contents: write`.
6. Store `RELEASE_APP_CLIENT_ID` as a source repository variable.
7. Store `RELEASE_PRIVATE_KEY` in the `experimental-spm-release` environment.
8. Require a reviewer for initial jobs that use this environment, and permit jobs from `main`.
9. Apply review and CI requirements to source `main` after its initial seed, while allowing reviewed PR merges.
10. Allow the publisher App to create and update publication `main`; verify the approved publisher route under inherited protection.
11. Protect full semantic version tags against update and deletion.
12. Disable Issues and Discussions in the three generated publication repositories.
13. Keep `EXPERIMENTAL_RELEASES_ENABLED` unset until remote preflight passes.
14. Keep consumer `EXPERIMENTAL_PACKAGES_AVAILABLE` unset until all baseline tags exist.

The App must not have repository administration permission or installation access to production repositories.
A local Git test cannot prove these controls. Record the actual installation scope and ruleset settings during remote validation.
The App permission list follows the test plan. If Release Please labeling fails, inspect the exact API requirement before broadening permissions.
No Apple Developer, App Store Connect, Swift registry, vendor, or data-plane credentials are required.

## Later production request

After the experimental proof passes, request the public repository `rudder-sdk-swift-monorepo` for [SDK-5385](https://linear.app/rudderstack/issue/SDK-5385).
Keep its publication disabled during history import and shadow validation.
Do not create replacement repositories for `rudder-sdk-swift` or the existing integrations.
Those public URLs and their histories remain the customer publication endpoints.

The current ticket names six integrations: Adjust, AppsFlyer, Braze, Facebook, Firebase, and Sprig.
Reconfirm the live integration inventory before production import; a local CleverTap checkout also exists.

## Request sources

- [Parent implementation task](https://linear.app/rudderstack/issue/SDK-5384)
- [Experimental publication task](https://linear.app/rudderstack/issue/SDK-5388)
- [Remote test plan and approved experimental names](https://app.notion.com/p/3c1f2b415dd081fdbe08d46a9927b266)
- [Production import task and production repository name](https://linear.app/rudderstack/issue/SDK-5385)
