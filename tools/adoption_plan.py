"""Read-only evidence and proposed GitHub changes for existing repositories."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools.adoption_git import collect_git_evidence
from tools.adoption_release import verify_release
from tools.setup_github import (
    ApiCall, REQUIRED_LABELS, RENAMED_LABELS, REPOSITORY_SETTINGS,
    RULESET_PATHS, SetupError, github_api, load_rulesets, repository_name,
)


class Observations:
    """Keep successful GET evidence separate from unavailable observations."""

    def __init__(self, api: ApiCall):
        self.api = api
        self.unavailable: list[dict] = []

    def get(self, endpoint: str, expected: type = dict) -> Any:
        try:
            value = self.api("GET", endpoint, None)
            if not isinstance(value, expected):
                raise SetupError(f"expected {expected.__name__} response")
            return value
        except (SetupError, OSError) as exc:
            self.unavailable.append({"endpoint": endpoint, "reason": str(exc)})
            return None

    def pages(self, endpoint: str) -> list | None:
        """Do not mistake a partial inventory for a complete observation."""
        values = []
        separator = "&" if "?" in endpoint else "?"
        page = 1
        while True:
            batch = self.get(
                f"{endpoint}{separator}per_page=100&page={page}", list,
            )
            if batch is None:
                return None
            values.extend(batch)
            if len(batch) < 100:
                return values
            page += 1


def branch_evidence(reader: Observations, prefix: str, name: str) -> dict:
    """Resolve an exact live branch, without trusting local tracking refs."""
    ref = f"refs/heads/{name}"
    matches = reader.pages(f"{prefix}/git/matching-refs/heads/{quote(name, safe='')}")
    if matches is None:
        return {"ref": ref, "status": "unavailable"}
    exact = [item for item in matches if item.get("ref") == ref]
    if not exact:
        return {"ref": ref, "status": "missing"}
    if len(exact) != 1 or not exact[0].get("object", {}).get("sha"):
        return {"ref": ref, "status": "ambiguous", "matches": exact}
    sha = exact[0]["object"]["sha"]
    commit = reader.get(f"{prefix}/git/commits/{sha}")
    return {
        "ref": ref, "status": "observed" if commit else "unavailable",
        "commit": sha, "tree": (commit or {}).get("tree", {}).get("sha"),
        "parents": (commit or {}).get("parents"),
    }


def protection_evidence(reader: Observations, prefix: str, branches: dict) -> dict:
    """Retain inherited/custom rules plus active and classic protection."""
    rulesets = reader.pages(f"{prefix}/rulesets?includes_parents=true")
    details = []
    for rule in rulesets or []:
        detail = reader.get(f"{prefix}/rulesets/{rule['id']}?includes_parents=true")
        details.append({"summary": rule, "detail": detail})
    effective = {}
    for name in branches:
        encoded = quote(name, safe="")
        effective[name] = {
            "active_rules": reader.pages(f"{prefix}/rules/branches/{encoded}"),
            # A 404 is ambiguous between absent protection and access limits.
            # Preserve that limitation instead of claiming an unprotected branch.
            "classic_protection": reader.get(f"{prefix}/branches/{encoded}/protection"),
        }
    return {"rulesets": rulesets, "details": details, "branches": effective}


def proposed_settings(repo: str, metadata: dict | None, labels: list | None,
                      protection: dict, recipes: list, decisions: list) -> list:
    """Describe exact optional adoption operations; never execute them."""
    prefix = f"repos/{repo}"
    changes = []

    def add(method: str, endpoint: str, payload: dict, before: Any) -> None:
        changes.append({
            "method": method, "endpoint": endpoint, "payload": payload,
            "before": before, "requires": "separate explicit apply authorization",
        })

    if metadata is not None:
        payload = {key: value for key, value in REPOSITORY_SETTINGS.items()
                   if metadata.get(key) != value}
        if payload:
            add("PATCH", prefix, payload,
                {key: metadata.get(key) for key in payload})
    if labels is not None:
        by_name = {label["name"]: label for label in labels}
        for label in REQUIRED_LABELS:
            name = label["name"]
            old = next((old for old, new in RENAMED_LABELS.items()
                        if new == name and old in by_name), None)
            current_name = name if name in by_name else old
            if current_name:
                before = by_name[current_name]
                if current_name != name or any(before.get(key) != value
                                               for key, value in label.items()):
                    add("PATCH", f"{prefix}/labels/{quote(current_name, safe='')}",
                        {"new_name": name, "color": label["color"],
                         "description": label["description"]}, before)
            else:
                add("POST", f"{prefix}/labels", dict(label), None)
    if protection["rulesets"] is not None:
        local = [item for item in protection["details"]
                 if item["summary"].get("source_type") == "Repository"
                 and item["summary"].get("source") == repo]
        for recipe in recipes:
            matches = [item for item in local
                       if item["summary"].get("name") == recipe["name"]]
            if len(matches) > 1:
                decisions.append({"kind": "ruleset_collision", "name": recipe["name"]})
            elif matches:
                current = matches[0]["detail"]
                if current is None:
                    continue
                if any(current.get(key) != value for key, value in recipe.items()):
                    add("PUT", f"{prefix}/rulesets/{matches[0]['summary']['id']}",
                        recipe, current)
                    decisions.append({"kind": "ruleset_replacement",
                                      "name": recipe["name"],
                                      "reason": "Review preserved custom differences before replacement."})
            else:
                add("POST", f"{prefix}/rulesets", recipe, None)
    return changes


def create_plan(repo: str, root: Path, *, api: ApiCall = github_api,
                lineage: str | None = None, lineage_reason: str | None = None,
                outcomes: list[str] | None = None, refs: list[str] | None = None,
                release_tag: str | None = None, candidate_ref: str | None = None,
                artifacts: list[dict] | None = None,
                ruleset_paths=RULESET_PATHS) -> dict:
    """Collect a timestamped, reviewable plan without any apply capability."""
    reader = Observations(api)
    prefix = f"repos/{repo}"
    metadata = reader.get(prefix)
    names = {"main", "dev"}
    if metadata and metadata.get("default_branch"):
        names.add(metadata["default_branch"])
    branches = {name: branch_evidence(reader, prefix, name) for name in sorted(names)}
    requested_candidate = candidate_ref
    candidate_ref = candidate_ref or branches["main"].get("commit") or "refs/heads/main"
    protection = protection_evidence(reader, prefix, branches)
    labels = reader.pages(f"{prefix}/labels")
    issues = reader.pages(f"{prefix}/issues?state=open")
    pulls = reader.pages(f"{prefix}/pulls?state=open")
    releases = reader.pages(f"{prefix}/releases")
    for release in releases or []:
        tag = release.get("tag_name")
        if tag:
            release["tag_ref"] = reader.get(f"{prefix}/git/ref/tags/{quote(tag, safe='')}")
        # Release asset lists can be longer than the embedded inventory.
        if release.get("id") is not None:
            assets = reader.pages(f"{prefix}/releases/{release['id']}/assets")
            release["assets"] = assets if assets is not None else []
            release["assets_unavailable"] = assets is None

    local_refs = set(refs or []) | {candidate_ref}
    for name, branch in branches.items():
        local_refs.update({f"refs/heads/{name}", f"refs/remotes/origin/{name}"})
        if branch.get("commit"):
            local_refs.add(branch["commit"])
    local_refs.update(f"refs/tags/{release['tag_name']}" for release in releases or []
                      if release.get("tag_name"))
    if lineage:
        local_refs.add(lineage)
    git = collect_git_evidence(root, sorted(local_refs))
    comparisons = []
    for left, right in combinations(branches.values(), 2):
        if left.get("commit") and right.get("commit"):
            comparison = reader.get(
                f"{prefix}/compare/{left['commit']}...{right['commit']}")
            comparisons.append({"left": left["ref"], "right": right["ref"],
                                "evidence": comparison})
    verification = verify_release(root, releases or [], release_tag, candidate_ref, artifacts)
    if releases is None:
        verification = {"status": "unavailable", "reason": "Published release inventory unavailable."}
    elif requested_candidate is None and branches["main"]["status"] != "observed":
        verification = {"status": "unavailable", "reason": "Live main source anchor unavailable; select an explicit candidate if appropriate."}
    decisions = []
    if not lineage or not lineage_reason or not outcomes:
        decisions.append({"kind": "canonical_lineage",
                          "reason": "Select a lineage, explain its evidence, and state recovery outcomes."})
    selected = next((item for item in git.get("refs", []) if item["requested"] == lineage), None)
    if lineage and not (selected and selected.get("available")):
        decisions.append({"kind": "canonical_lineage_unavailable", "ref": lineage})
    if metadata and metadata.get("archived"):
        decisions.append({"kind": "archive_disposition",
                          "reason": "Archived state is preserved; any unarchive needs separate authority."})
    if verification["status"] != "pass":
        decisions.append({"kind": "release_evidence", "status": verification["status"]})
    for name, branch in branches.items():
        if branch["status"] != "observed":
            decisions.append({"kind": "branch_anchor", "branch": name, "status": branch["status"]})
    changes = proposed_settings(repo, metadata, labels, protection,
                                load_rulesets(ruleset_paths), decisions)
    return {
        "mode": "plan", "observed_at": datetime.now(timezone.utc).isoformat(),
        "repository": repo, "local_root": str(root.resolve()),
        "authority": "No apply, ref, content, archive, tracking, or publication changes are performed.",
        "remote": {"repository": metadata, "branches": branches,
                   "branch_comparisons": comparisons, "protection": protection,
                   "labels": labels, "issues": issues, "pull_requests": pulls,
                   "releases": releases},
        "local": git, "release_verification": verification,
        "recovery": {"selected_lineage": lineage, "selection_reason": lineage_reason,
                     "lineage_identity": selected,
                     "intended_outcomes": outcomes or [],
                     "history_policy": "Preserve observed histories; divergence alone does not establish rewriting."},
        "proposed_mutations": changes, "unresolved_decisions": decisions,
        "unavailable_evidence": reader.unavailable,
    }


def main(argv: list[str] | None = None) -> int:
    """Print planning evidence to stdout; never write an output file implicitly."""
    parser = argparse.ArgumentParser(description="Read-only adoption/recovery planning; no apply operation.")
    parser.add_argument("--repo", required=True, type=repository_name)
    parser.add_argument("--plan", action="store_true", help="Explicitly select the default read-only operation.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Existing local repository (default: current directory).")
    parser.add_argument("--ref", action="append", default=[], help="Additional local ref or commit to preserve as evidence.")
    parser.add_argument("--lineage", help="Explicitly selected local canonical lineage ref or commit.")
    parser.add_argument("--lineage-reason", help="Evidence supporting the lineage selection.")
    parser.add_argument("--recover-outcome", action="append", default=[], help="Concrete intended recovery outcome; repeatable.")
    parser.add_argument("--release-tag", help="Exact published tag; otherwise select the uniquely latest stable publication.")
    parser.add_argument("--candidate-ref", help="Source state to compare; default: observed live main commit (must be locally available).")
    parser.add_argument("--artifacts", type=Path, help="JSON array of artifact evidence: name, path, sha256, required.")
    args = parser.parse_args(argv)
    try:
        artifacts = None
        if args.artifacts:
            artifacts = json.loads(args.artifacts.read_text(encoding="utf-8"))
            if not isinstance(artifacts, list) or not all(isinstance(item, dict) for item in artifacts):
                raise SetupError("artifact evidence must be a JSON array of objects")
        plan = create_plan(
            args.repo, args.root, lineage=args.lineage, lineage_reason=args.lineage_reason,
            outcomes=args.recover_outcome, refs=args.ref, release_tag=args.release_tag,
            candidate_ref=args.candidate_ref, artifacts=artifacts,
        )
    except (SetupError, OSError, ValueError) as exc:
        print(f"adoption-plan: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2))
    # A printed report is not a successful release-verification claim.
    if plan["release_verification"]["status"] != "pass" or plan["unavailable_evidence"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
