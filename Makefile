# Developer commands. Thin wrappers only: every rule lives in scripts/.
PYTHON ?= python3
MODE ?= history
KIND ?= integration
BASE ?= origin/main

.PHONY: prepare sync check test affected lint new-integration import-integration

## Once per clone (safe to re-run): tool checks, git hooks (repo-local), vendor cache.
prepare:
	@PYTHON="$(PYTHON)" scripts/prepare.sh

## Refresh vendor metadata and markers, shared-source markers and generated GitHub files.
## The pre-commit hook runs the matching part automatically; this is the fallback.
sync:
	$(PYTHON) scripts/dependency_policy.py sync
	$(PYTHON) scripts/release_plan.py sync-shared
	$(PYTHON) scripts/generate_github.py

## The CI policy checks.
check:
	$(PYTHON) scripts/release_plan.py sync-shared --check
	$(PYTHON) scripts/dependency_policy.py check
	$(PYTHON) scripts/check_inventory.py
	$(PYTHON) scripts/generate_github.py --check
	$(PYTHON) -m compileall -q scripts

## Python tests, then iOS Simulator tests for every package (CI's `test (<key>)`).
## make test PKG=sprig runs only that package's iOS Simulator tests.
test:
	$(if $(PKG),,$(PYTHON) -m unittest discover -s Tests -p 'test_*.py')
	$(PYTHON) scripts/package_ci.py test $(if $(PKG),--package "$(PKG)")

## Packages this branch changes since it left BASE (default origin/main), e.g. ["sprig"].
affected:
	@$(PYTHON) scripts/package_ci.py affected --base "$(BASE)"

## SwiftLint on the Swift files changed since BASE (no-op when there are none).
lint:
	@$(PYTHON) scripts/package_ci.py lint --base "$(BASE)"

## Path B: make new-integration NAME=Braze [PLATFORMS="iOS 15,tvOS 15"] [SDK_MIN=1.4.1]
##         [VENDOR_URL=... VENDOR_PRODUCTS=A,B VENDOR_FROM=X.Y.Z]
new-integration:
	$(PYTHON) scripts/scaffold.py "$(NAME)" \
		$(if $(PLATFORMS),--platforms "$(PLATFORMS)") $(if $(SDK_MIN),--sdk-minimum "$(SDK_MIN)") \
		$(if $(VENDOR_URL),--vendor-url "$(VENDOR_URL)" --vendor-products "$(VENDOR_PRODUCTS)" --vendor-from "$(VENDOR_FROM)")

## Path A: make import-integration REPO=<repo> TAG=<X.Y.Z> NAME=<Name> MODE=history|snapshot [KIND=core]
import-integration:
	$(PYTHON) scripts/import_package.py "$(REPO)" "$(TAG)" "$(NAME)" --mode "$(MODE)" --kind "$(KIND)"
