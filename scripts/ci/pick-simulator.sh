#!/bin/bash

# ──────────────────────────────────────────────────────────────
# pick-simulator.sh
# Prints the UDID of the first available iPhone on the newest
# installed iOS runtime, so no device name is hardcoded (runner
# images and Xcode versions change their device lists).
#
# Usage: scripts/ci/pick-simulator.sh [devices.json]
#   devices.json defaults to `xcrun simctl list devices available -j`
#   (the argument exists for tests).
# ──────────────────────────────────────────────────────────────
set -euo pipefail

if [ $# -gt 0 ]; then
    devices=$(cat "$1")
else
    devices=$(xcrun simctl list devices available -j)
fi

python3 -c '
import json, re, sys

newest = None
for runtime, devices in json.load(sys.stdin)["devices"].items():
    match = re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-(\d+)-(\d+)(?:-(\d+))?", runtime)
    phones = [d for d in devices if d.get("isAvailable", True) and d["name"].startswith("iPhone")]
    if match and phones:
        version = tuple(int(part or 0) for part in match.groups())
        if newest is None or version > newest[0]:
            newest = (version, phones[0])
if newest is None:
    sys.exit("No available iPhone simulator on any iOS runtime (install one in Xcode > Settings > Components)")
print(newest[1]["udid"])
' <<< "$devices"
