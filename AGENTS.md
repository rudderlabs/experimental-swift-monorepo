# Scope

This is a local experimental repository for SDK-5388.
Read README.md and REMOTE-RUNBOOK.md before work.
Do not publish to GitHub unless the user authorizes that remote action.
Only the fixed experimental repository inventory is valid.
Never replace immutable tags or reset previous `.lab` runs.
Run `python3 -m unittest discover -s Tests -p 'test_*.py'` for script changes. The demo packages are test data in `Tests/Fixtures/demo/`; `scripts/rehearse.py` still targets the old layout until it is rewritten.
The consumer template is the sibling `experimental-swift-example-consumer-app` repository.
Report local Git evidence separately from GitHub Actions and production verification.

Use `main` for source, consumer, and generated publication work. Initial source creation succeeded on GitHub. Subsequent protected source/consumer updates require reviewed PRs. Publication updates require an explicitly approved publisher App bypass or another reviewed route; do not assume Contents write bypasses PR rules.
Preserve historical tags and earlier `.lab` evidence. Source and consumer GitHub defaults are `main`.
Use the configured Git identity for real and rehearsal commits. Do not substitute a placeholder author.
