# Scope

This is a local experimental repository for SDK-5388.
Read README.md and REMOTE-RUNBOOK.md before work.
Do not publish to GitHub unless the user authorizes that remote action.
Only the fixed experimental repository inventory is valid.
Never replace immutable tags or reset previous `.lab` runs.
Use `swift test` for source changes. Use `python3 scripts/rehearse.py --ios` for publication changes.
The consumer template is the sibling `experimental-swift-example-consumer-app` repository.
Report local Git evidence separately from GitHub Actions and production verification.

Use `dev` for source, consumer, and generated publication work. `main` is locked by organization policy.
Preserve historical tags and earlier `.lab` evidence. Source and consumer GitHub defaults must be `dev` for manual workflows.
