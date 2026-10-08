# Staged dependency-management configuration

Prepared: 2026-09-22. Owner: SDK team. Updated: 2026-10-02. Status: local dependency guards implemented; template not activated; no hosted validation.

This bundle adds the dependency-management requirements to the existing SDK-5388 experiment. The October 2 preparation adds exporter dependency guards, release markers, regression tests, and a read-only monitoring collector. Dependabot and hosted settings remain inactive. Follow [acceptance commands and gates](ACCEPTANCE.md) and the linked canonical matrix before remote activation.

## Proposed configuration

`dependabot.yml.template` is valid YAML kept outside `.github/dependabot.yml`. GitHub does not load it. The current sample has one declarative root `Package.swift`, so the Swift updater uses `/`. `Packages/*` and `Integrations/*` are targets, not separate package roots. Actions also uses `/`.

The candidate uses `open-pull-requests-limit: 0` to avoid routine version PRs. It does not disable alerts or automatic security PRs. The monthly schedule is a required version-update setting, not alert or security-response cadence. Final production PR policy remains undecided; this template is one concrete security-first option.

No `target-branch` is needed when source default is `main`. Recheck the actual default branch during provisioning. No ignore, exclude, auto-dismissal, or severity filter is proposed. SHA-pinned Actions remain pinned; their native advisory-detection limitation needs separate evidence.

If only alert collection is selected, no updater YAML is required. Dependency graph inputs and alert settings are still required.

## Settings and graph inputs — separate from YAML

| Surface | Proposed requirement | Acceptance evidence |
| --- | --- | --- |
| Source monorepo | Enable dependency graph and alerts; retain all severities and no-fix/no-PR findings. Capture a clean public-URL `Package.resolved` on the source default branch. | Expected vendor identities and resolved versions appear in GitHub; record default branch, commit, graph export, run date, and any missing packages. |
| Independent consumer | Keep a reviewed resolution of the published SDK and integrations on its actual default branch. | Customer-facing package versions and transitive vendor versions appear in the consumer graph. Distinguish them from source development resolution. |
| Publication repositories | Preserve all existing native alerts. Establish a reviewed graph-input route for generated releases. | Verify each actual default branch. Output now uses default `main`, but hosted graph ingestion still requires evidence. Consumer coverage does not silently replace missing publication visibility. |
| Rules | Inventory effective organization/repository rules. Do not suppress low/development alerts to reduce noise. | Record rule state and preserve original alert identities, including existing dismissed records for audit. |
| PR settings | Select automatic, selective, or requested security PR handling separately. | Record chosen mode and hosted behavior. No automatic-merge setting is proposed. |

Local mirror resolutions are not valid remote graph inputs. The source's public vendor-only lock may be suitable after inspection; consumer locks must be regenerated against real public experiment URLs after baseline publication. Keep `.lab/` and local mirrors out of remote commits. Lockfiles used by consumers do not change the downstream version requirements of published libraries.

Do not introduce a custom Swift graph-submission workflow before checking normal lockfile ingestion. If ingestion fails, record the error and prove a supported alternative; a successful `swift package resolve` alone is not graph evidence.

## Local implementation and remaining prerequisites

1. `scripts/dependency_policy.py check` compares export vendor metadata against SwiftPM's parsed canonical manifest. Export invokes the same check before creating output. Git requirements may be `exact`, `upToNextMajor` (including `from:`), `upToNextMinor`, or a version range; markers and inventory store `{kind, lower, upper}` and the generated manifest uses the same kind. Branch and revision requirements are rejected. Products from one vendor package share a single `.package` line.
2. `scripts/dependency_policy.py sync` derives vendor metadata and writes package-local `dependency-requirements.json` markers. The check command rejects stale or missing markers. Include reviewed markers in the same `fix:` commit as a vendor update so Release Please can see the affected integration paths.
3. `release_plan.py affected --base-ref <commit> Package.swift` compares current parsed requirements with committed package markers at the pre-change baseline. Root lock-only changes are release-neutral. Local classification tests cover one vendor consumer and two integrations sharing a vendor. Real Release Please and the hosted shared-vendor release remain pending.
4. CI runs dependency guards and local regressions without publisher credentials. The extended local rehearsal tests a Swift Collections 1.1.4-to-1.1.5 update through Firebase export, release, and independent consumer resolution. These local Git results do not prove hosted updater/security behavior.
5. Clean public-URL graph input and publication-default coverage remain unresolved hosted gates. The exporter still excludes `Package.resolved`; decide how publication graph inputs are maintained without generated exports erasing them.

Use the existing exporter and release-marker design. Do not add another version authority or an automatic bot commit to a Release Please branch. Updates to `sdkMinimum` remain explicit release-policy changes. Review all changed markers and the resulting Release Please intent before merging.

## Remote experiment procedure — execute later

1. Complete repository provisioning, repository-name alignment, local checks, and the remaining graph-input prerequisites.
2. Confirm all five default branches are `main`; subsequent source and consumer updates require reviewed PRs.
3. Publish the baseline experimental packages through the existing runbook.
4. Resolve the source vendor and independent consumer from clean public URLs.
5. Review and commit the appropriate resolved files to their default branches.
6. Enable/verify graph and alerts. Record package identities and all findings before enabling updater tests.
7. Copy the reviewed template to `.github/dependabot.yml` in the experimental source only.
8. For one controlled updater trial, change only the Swift version-PR limit to `1` and its interval to `weekly`. Leave Actions at zero.
9. Use the GitHub update-check UI and inspect a supported newer fixture-vendor proposal. No hosted per-alert PR API is assumed.
10. Verify the PR changes the canonical dependency requirement and that export metadata cannot remain stale.
11. Use normal review and Release Please to publish the affected Firebase fixture. SDK and Sprig must not release for this vendor-only change.
12. Install the new Firebase fixture in the independent consumer; verify the intended vendor version and unchanged unrelated package versions.
13. Restore the candidate Swift limit to zero after the trial, unless another test mode is explicitly selected. Preserve the evidence and all alerts.

A benign vendor version-update trial proves updater/export behavior, not security-fix behavior. Test an existing suitable security finding if available. Otherwise record security-PR behavior as unverified; do not add a vulnerable dependency solely to force an alert. M1 detection acceptance does not depend on any PR existing.

The trial fixture uses Swift Collections, not the real Firebase SDK. Production shadow validation must cover the real vendor packages, supported platforms, binary dependencies, and all seven integrations.

## Required failure cases and evidence

- A manifest-only vendor update with stale export metadata fails before publication, or exporter-derived metadata automatically uses the manifest requirement.
- A vendor-only fix selects the correct consumer integration and produces reviewed release intent.
- A lock-only change is classified separately from a changed public dependency requirement.
- A missing/stale default-branch graph is reported as a coverage gap, not zero vulnerabilities.
- Generated publication drift is rejected; a later export cannot overwrite a fix silently.
- Missing registry or package access produces an explicit failed result; no publisher credentials are exposed to updater PR jobs.

Retain source/consumer/publication SHAs, resolved files, package identities, graph exports, settings/rules, updater logs and PR, release selection, generated manifests, consumer output, and remaining unsupported findings. Keep critical, high, medium, low, unknown, no-fix, and no-PR findings visible.

## Production handoff

Follow [SDK-5385](https://linear.app/rudderstack/issue/SDK-5385) for import, [SDK-5386](https://linear.app/rudderstack/issue/SDK-5386) for exporter/shadow validation, and [SDK-5387](https://linear.app/rudderstack/issue/SDK-5387) for cutover. Reconfirm the actual production roots and branches before copying the template. Preserve independent package URLs, versions, and immutable tags.

The initial dependency-management run proceeds with 18 non-Swift repositories. `rudder-sdk-swift` and seven `integration-swift-*` repositories remain deferred for configuration, with existing alerts retained. Legacy iOS and native dependencies within Flutter/React Native remain active.

## References

- [Remote experiment plan](https://app.notion.com/p/3c1f2b415dd081fdbe08d46a9927b266)
- [Production migration plan](https://app.notion.com/p/3c1f2b415dd08197b28dd097c7c476cc)
- [GitHub configuration options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
- [Swift support](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories#swift)
- [Dependency graph inputs](https://docs.github.com/en/code-security/reference/supply-chain-security/dependency-graph-supported-package-ecosystems)
