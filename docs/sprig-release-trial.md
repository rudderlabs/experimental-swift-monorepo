# Sprig release and customer upgrade test

Use only the five experimental repositories. Start from public SDK, Sprig, and Firebase version 0.1.0. The Sprig fixture fix gives blank event names a fallback. Expected release selection is Sprig 0.1.1 only.

1. Run a fresh anonymous consumer and iOS build against existing 0.1.0 tags.
2. Review and merge the Sprig fix and Release Please baseline configuration.
3. Verify the configured release environment and protected-main publication route.
4. Enable the release workflow and inspect the actual main-targeted Release Please PR.
5. Verify only Sprig version, constant, changelog, and manifest version change.
6. Leave the release PR open and confirm peripheral refs and consumer runtime remain unchanged.
7. Merge the approved release PR and inspect the publication job.
8. Verify generated Sprig builds and its main commit, plain 0.1.1 tag, GitHub Release, and source provenance agree.
9. Upgrade the independent consumer with `python3 scripts/dependencies.py --set sprig=0.1.1`.
10. Review SwiftPM and Xcode selections and public resolved dependency files.
11. Run `python3 scripts/verify.py --ios` without local mirrors.
12. Verify runtime Sprig 0.1.1, SDK 0.1.0, and Firebase 0.1.0.
13. Verify `DemoSprig.track(" \n\t ").name` is `unnamed event` after upgrade.
14. Reinstall all old 0.1.0 tags in a separate fresh consumer.
15. Record unchanged SDK/Firebase tags and main commits, all workflow URLs, and old/new consumer results.

Keep real hosted evidence separate from candidate generation and local projection tests. Preserve existing tags. An authentication token does not establish protected-main push access. If publication fails, report incomplete publication and retain the approved SHA/version for recovery. Do not manually create the expected tag to make the consumer test pass.
