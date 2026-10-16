# Contributing to the experiment

## Outside contributors

Issues and pull requests for every package are welcome here. The public package repositories accept none.
Open an issue first for larger changes; pick the package in the issue form.
Title your PR as a Conventional Commit (`fix(sprig): handle empty config`); the `pr-title` check enforces it.
Maintainers review it; once merged, it ships in that package's next release.

## Maintainers

Edit canonical source here. Do not edit generated publication repositories.
Use short `feat:`, `fix:`, or internal Conventional Commit subjects with the SDK ticket key.
Run `make prepare` once per clone (git hooks: release markers, commit message and branch name checks), then `make check test` before review (see the developer path in README.md). PR CI runs only the packages your change affects (README.md, PR checks); so does a push, compared with the branch's previous commit. From a terminal, the pre-push hook tests only the packages your branch changed (against your local `origin/main`, so `git fetch origin` first); CI also tests their dependents. `SKIP_PRE_PUSH_TESTS=1 git push` skips those tests (the branch name and global checks still run; CI runs the tests).
Add packages with `make new-integration` or `make import-integration`, never by hand. To import a branch that is ahead of the latest tag with non-code changes only (license, README, CODEOWNERS), add `REF=main`; the version stays the tag's and the import fails if any code differs.
Keep independent changes in separate commits.
`.github/CODEOWNERS` assigns every path to `@rudderlabs/sdk_team`, so sdk_team reviews every change, including `release/allowlist.json`.
Do not enable production publication from this fixture.
