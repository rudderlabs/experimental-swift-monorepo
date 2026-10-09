# Contributing to the experiment

Edit canonical source here. Do not edit generated publication repositories.
Use short `feat:`, `fix:`, or internal Conventional Commit subjects with the SDK ticket key.
Run `make prepare` once per clone (git hooks: release markers, commit message and branch name checks), then `make check test` before review (see the developer path in README.md).
Add packages with `make new-integration` or `make import-integration`, never by hand.
Keep independent changes in separate commits.
`.github/CODEOWNERS` assigns every path to `@rudderlabs/sdk_team`, so sdk_team reviews every change, including `release/allowlist.json`.
Do not enable production publication from this fixture.
