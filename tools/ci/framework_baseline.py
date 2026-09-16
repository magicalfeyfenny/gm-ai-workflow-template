"""Verify that a validated framework candidate is durably committed."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _tree_entries(root: Path, tree: str) -> dict[str, tuple[str, str, str]] | None:
    result = _git(root, "ls-tree", "-r", "--full-tree", "-z", tree)
    if result.returncode != 0:
        return None
    entries = {}
    for record in result.stdout.split("\0"):
        if record:
            metadata, path = record.split("\t", 1)
            entries[path] = tuple(metadata.split())
    return entries


def _verify_framework_baseline(
    root: Path, candidate_tree: str | None, framework_paths: list[str], has_commit: bool,
) -> dict:
    result = {
        "candidate_tree": candidate_tree,
        "checked_paths": sorted(framework_paths),
        "ready": False,
    }
    if not has_commit:
        result.update({
            "status": "incomplete",
            "reason": "HEAD has no commit containing the validated framework baseline",
        })
        return result
    if not candidate_tree:
        result.update({
            "status": "incomplete",
            "reason": "local validation did not produce a candidate tree to verify",
        })
        return result
    resolved = _git(
        root, "rev-parse", "--verify", "--end-of-options", f"{candidate_tree}^{{tree}}",
    )
    if resolved.returncode != 0:
        result.update({
            "status": "failed",
            "reason": "could not resolve the validated candidate tree",
        })
        return result
    candidate_tree = resolved.stdout.strip()
    result["candidate_tree"] = candidate_tree
    candidate = _tree_entries(root, candidate_tree)
    head = _tree_entries(root, "HEAD")
    if candidate is None or head is None:
        result.update({
            "status": "failed",
            "reason": "could not inspect the validated candidate and durable HEAD trees",
        })
        return result
    expected = set(framework_paths)
    missing_from_candidate = sorted(expected - candidate.keys())
    if missing_from_candidate:
        result.update({
            "status": "incomplete",
            "reason": "the validated candidate is missing required framework paths",
            "missing_from_candidate": missing_from_candidate,
        })
        return result
    missing_from_head = sorted(expected - head.keys())
    differing_from_head = sorted(
        path for path in expected & head.keys() if head[path] != candidate[path]
    )
    if missing_from_head or differing_from_head:
        result.update({
            "status": "incomplete",
            "reason": "the validated framework baseline is not durably represented in HEAD",
            "missing_from_head": missing_from_head,
            "differing_from_head": differing_from_head,
        })
        return result
    result.update({
        "status": "complete",
        "reason": "HEAD contains the validated framework paths and contents",
        "ready": True,
    })
    return result


def gate_git_state(
    root: Path, git_state: dict, validation: dict, framework_paths: list[str],
) -> dict:
    """Add the durable framework-baseline check to post-validation Git state."""
    baseline = _verify_framework_baseline(
        root, validation.get("candidate_tree"), framework_paths,
        git_state["has_commit"],
    )
    git_state["framework_baseline"] = baseline
    if not baseline["ready"]:
        git_state["manual_actions"].append(
            "review, stage, and commit the validated framework baseline on dev, then rerun bootstrap before configuring GitHub"
        )
        git_state["ready"] = False
    return git_state
