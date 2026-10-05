# Dependency monitoring acceptance

Prepared: 2026-10-02. Owner: SDK team. Hosted execution pending.

The canonical experiment matrix is [the local Swift project matrix](/Users/denis/Documents/rudderstack/projects/proj-swift-integration-monorepo-feasibility/dependency-monitoring-acceptance-matrix.md). The [procedure](README.md) remains the portable repository runbook. This local KB link is a preparation reference; copy or attach the reviewed matrix to the GitHub test evidence before remote review.

## Commands

Validate dependency metadata and reviewed release markers:

```sh
python3 scripts/dependency_policy.py check
python3 -m unittest discover -s Tests -p 'test_*.py'
```

After reviewing a canonical `Package.swift` vendor requirement change, update export metadata and affected package markers:

```sh
python3 scripts/dependency_policy.py sync
python3 scripts/release_plan.py affected --base-ref HEAD Package.swift
```

Include the changed inventory and package markers in the reviewed `fix:` commit. For an already committed change, choose the pre-change commit with `--base-ref`. Review the resulting Release Please PR; local selection is not real Release Please evidence. If `sdkMinimum` changes, run sync and review the coordinated SDK/integration release requirements.

The exact-Git fixture rejects unsupported ranges. Lock-only changes do not automatically release a product. Do not edit generated publication manifests as remediation.

After provisioning, collect read-only native monitoring evidence:

```sh
python3 scripts/monitoring_snapshot.py --output .lab/monitoring-2026-10-02.json
```

Choose a fresh output filename each run. Reads use the authenticated `gh` identity and the explicit [experiment-only scope](monitoring-scope.json). The reader needs repository metadata, dependency graph, and native alert read access. Verify the intended monitoring identity separately from the publisher App; do not broaden publisher permissions for this collector. No model calls, remote writes, or Linear publication occur. A failed read is retained and causes a nonzero exit. Successful API collection does not prove package coverage. Review source/consumer locks and expected package identities against the saved graph.

## Outstanding hosted gates

- Confirm actual defaults and dependency graph/alert/security-PR settings.
- Verify source, independent consumer, and all publication graph inputs.
- Verify publication graph coverage from generated output on default `main`.
- Run the real Dependabot PR through reviewed release intent and consumer verification.
- Run the shared external-vendor and dependency-range/refresh trials.
- Capture existing suitable native security findings when available; otherwise retain an unverified result.
- Verify DAMP collection permissions, source routing, and native alert identities.
- Record pinned Actions advisory limitations and a supplementary monitoring decision.
- Carry real Firebase indirect/binary/platform cases into production shadow validation.

Preserve all severities and no-fix/no-PR findings. Keep synthetic collector tests separate from live native evidence. Keep experimental repositories outside the production 26-repository baseline.

The snapshot is an evidence artifact, not a drop-in DAMP model request. A later approved adapter must supply the full DAMP collection/evidence contract, including source paths, support constraints, advisory/fix evidence, and PR/check inventory. Raw native alerts retain timestamps and original fields for that handoff.
