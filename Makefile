# Developer commands. Thin wrappers only: every rule lives in scripts/.
PYTHON ?= python3
MODE ?= history
KIND ?= integration

.PHONY: sync check test new-integration import-integration

# make prepare (git hooks, tool checks, vendor cache) arrives with the developer setup (plan P3).

## Refresh vendor metadata and markers, shared-source markers and generated GitHub files.
sync:
	$(PYTHON) scripts/dependency_policy.py sync
	$(PYTHON) scripts/release_plan.py sync-shared
	$(PYTHON) scripts/generate_github.py

## The CI policy checks (CI also runs `make test`).
check:
	$(PYTHON) scripts/release_plan.py sync-shared --check
	$(PYTHON) scripts/dependency_policy.py check
	$(PYTHON) scripts/check_inventory.py
	$(PYTHON) scripts/generate_github.py --check
	$(PYTHON) -m compileall -q scripts

## Python tests for the release tooling.
test:
	$(PYTHON) -m unittest discover -s Tests -p 'test_*.py'

## Path B: make new-integration NAME=Braze [PLATFORMS="iOS 15,tvOS 15"] [SDK_MIN=1.4.1]
##         [VENDOR_URL=... VENDOR_PRODUCTS=A,B VENDOR_FROM=X.Y.Z]
new-integration:
	$(PYTHON) scripts/scaffold.py "$(NAME)" \
		$(if $(PLATFORMS),--platforms "$(PLATFORMS)") $(if $(SDK_MIN),--sdk-minimum "$(SDK_MIN)") \
		$(if $(VENDOR_URL),--vendor-url "$(VENDOR_URL)" --vendor-products "$(VENDOR_PRODUCTS)" --vendor-from "$(VENDOR_FROM)")

## Path A: make import-integration REPO=<repo> TAG=<X.Y.Z> NAME=<Name> MODE=history|snapshot [KIND=core]
import-integration:
	$(PYTHON) scripts/import_package.py "$(REPO)" "$(TAG)" "$(NAME)" --mode "$(MODE)" --kind "$(KIND)"
