#!/bin/bash

# ──────────────────────────────────────────────────────────────
# prepare.sh (`make prepare`, once per clone; safe to re-run)
# 1. Checks tools and prints install hints.
# 2. Turns on the repository git hooks (repo-local core.hooksPath).
# 3. Warms the vendor cache (`swift package resolve`) when a root
#    Package.swift exists.
# Never changes global git configuration.
# ──────────────────────────────────────────────────────────────

HOOK_DIR="scripts/git-hooks"
PYTHON=${PYTHON:-python3}
cd "$(dirname "$0")/.." || exit 1

missing=0
ok() { echo "  [OK]      $1"; }
need() { echo "  [MISSING] $1"; echo "            $2"; missing=1; }
hint() { echo "  [WARNING] $1"; echo "            $2"; }

echo "Checking tools..."
xcode=$(xcodebuild -version 2>/dev/null | head -1)
if [[ $xcode =~ ^Xcode\ ([0-9]+) ]] && [ "${BASH_REMATCH[1]}" -ge 16 ]; then
    ok "$xcode"
else
    need "Xcode 16 or later (found: ${xcode:-none})" \
         "Install Xcode from the App Store, then: sudo xcode-select -s /Applications/Xcode.app"
fi
if "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    ok "$("$PYTHON" --version 2>&1)"
else
    need "Python 3.9 or later ($PYTHON)" "Install it with: brew install python"
fi
if command -v swiftlint > /dev/null; then
    ok "SwiftLint $(swiftlint version)"
else
    hint "SwiftLint is not installed (the pre-commit hook skips linting; CI still lints)" \
         "Install it with: brew install swiftlint"
fi
if git filter-repo --version > /dev/null 2>&1; then
    ok "git-filter-repo"
else
    hint "git-filter-repo is not installed (needed only for make import-integration MODE=history)" \
         "Install it with: brew install git-filter-repo"
fi
if [ $missing -ne 0 ]; then
    echo ""
    echo "[ERROR] Install the missing tools above, then run make prepare again."
    exit 1
fi

echo ""
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "[ERROR] Not inside a git clone. Clone the repository, then run make prepare."
    exit 1
fi
# Repo-local only. It overrides a global core.hooksPath for this clone;
# each hook runs the global hook of the same name first (Gitleaks, etc.).
if ! git config --local core.hooksPath "$HOOK_DIR"; then
    echo "[ERROR] Failed to set the local core.hooksPath."
    exit 1
fi
echo "Git hooks on (git config --local core.hooksPath = $HOOK_DIR):"
echo "  - pre-commit : syncs release markers when Package.swift, release/ or Shared/ is staged; SwiftLint"
echo "  - commit-msg : Conventional Commits, same rules as the PR title check"
echo "  - pre-push   : branch name; make test (terminal only)"
GLOBAL_HOOKS_PATH=$(git config --global --get core.hooksPath 2>/dev/null)
if [ -n "$GLOBAL_HOOKS_PATH" ]; then
    echo "  Global hooks in $GLOBAL_HOOKS_PATH run first (chained)."
fi

if [ -f Package.swift ]; then
    echo ""
    echo "Resolving packages (swift package resolve; slow the first time)..."
    if ! swift package resolve; then
        echo "[ERROR] swift package resolve failed (network or a vendor requirement)."
        exit 1
    fi
else
    echo ""
    echo "No root Package.swift yet (no packages imported): nothing to resolve."
fi

echo ""
echo "Ready"
