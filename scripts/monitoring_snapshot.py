"""Read-only GitHub evidence collection. No models, tickets, or remote writes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from common import ROOT, CONSUMER_NAME, OWNER, SOURCE_NAME, allowlist, load, write_json


def github(endpoint, paginate=False):
    command = ["gh", "api", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=45)
    if result.returncode:
        # Retain operational evidence without printing credentials/environment.
        raise RuntimeError(f"GitHub read failed ({result.returncode}): {endpoint}")
    return json.loads(result.stdout)


def alert_records(repository, pages):
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("Alert pagination is not a complete page list")
    records = []
    seen = set()
    for page in pages:
        for alert in page:
            identity = (repository["id"], alert["number"])
            if identity in seen:
                raise ValueError("Repeated alert identity during pagination")
            seen.add(identity)
            records.append({"identity": list(identity), "repository": repository["full_name"],
                            "number": alert["number"], "state": alert["state"],
                            "url": alert["html_url"], "dependency": alert["dependency"],
                            "advisory": alert.get("security_advisory"),
                            "vulnerability": alert.get("security_vulnerability"),
                            "nativeAlert": alert})
    return records


def collect(scope, reader=github):
    allowed = {f"{OWNER}/{name}" for name in [SOURCE_NAME, CONSUMER_NAME, *allowlist().values()]}
    names = [item["name"] for item in scope["repositories"]]
    if len(names) != len(set(names)) or any(name not in allowed for name in names):
        raise ValueError("Monitoring scope must contain unique approved experimental repositories")
    result = {"schemaVersion": 1, "observedAt": datetime.now(timezone.utc).isoformat(),
              "mode": scope["mode"], "repositories": [], "complete": True}
    for item in scope["repositories"]:
        name = item["name"]
        record = {**item, "complete": False, "alertsStatus": "not-collected",
                  "graphStatus": "not-collected", "errors": []}
        try:
            repository = reader(f"repos/{name}")
            if repository["full_name"].lower() != name.lower():
                raise ValueError("Repository identity differs from requested scope")
            record["repositoryId"] = repository["id"]
            record["defaultBranch"] = repository["default_branch"]
            commit = reader(f"repos/{name}/commits/{repository['default_branch']}")
            record["defaultBranchCommit"] = commit["sha"]
            for kind, endpoint, paginate in [
                # Omit state/severity/scope/patch filters to retain all native findings.
                ("alerts", f"repos/{name}/dependabot/alerts?per_page=100", True),
                ("graph", f"repos/{name}/dependency-graph/sbom", False),
            ]:
                try:
                    raw = reader(endpoint, paginate=paginate)
                    if kind == "alerts":
                        record["alertsPages"] = raw
                    record[kind] = alert_records(repository, raw) if kind == "alerts" else raw
                    record[kind + "Status"] = "collected"
                except (RuntimeError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as error:
                    record[kind + "Status"] = "failed"
                    record["errors"].append(str(error))
            # Detect moving input; retain observations but do not call them complete.
            latest = reader(f"repos/{name}")
            latest_commit = reader(f"repos/{name}/commits/{latest['default_branch']}")
            if (latest["default_branch"] != record["defaultBranch"] or
                    latest_commit["sha"] != record["defaultBranchCommit"]):
                record["errors"].append("Default branch changed during collection")
            record["complete"] = not record["errors"]
        except (RuntimeError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as error:
            record["errors"].append(str(error))
        if not record["complete"]:
            result["complete"] = False
        result["repositories"].append(record)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output path; previous evidence must be preserved")
    scope = load(ROOT / "docs/dependency-management/monitoring-scope.json")
    evidence = collect(scope)
    write_json(args.output, evidence)
    print(json.dumps({"complete": evidence["complete"], "output": str(args.output)}))
    raise SystemExit(0 if evidence["complete"] else 1)
