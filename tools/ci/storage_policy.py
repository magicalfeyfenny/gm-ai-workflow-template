"""Configurable hygiene and LFS storage rules over identified Git trees."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath

if __package__:
    from .candidate_git import candidate_snapshot, is_lfs_pointer
else:
    from candidate_git import candidate_snapshot, is_lfs_pointer


def string_list(value: object, subject: str) -> list[str]:
    """Reject malformed lists before Git interprets configured patterns."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or "\0" in item or "\n" in item
        for item in value
    ):
        raise ValueError(f"{subject}: expected a list of nonempty single-line strings")
    return value


def storage_rules(policy: dict) -> dict:
    """Validate the small storage schema; omitted storage means no enforcement."""
    if "storage" not in policy:
        return {"enabled": False}
    rules = policy["storage"]
    allowed = {"enabled", "check_tracked_ignored", "prohibited_patterns", "exceptions", "lfs"}
    if not isinstance(rules, dict) or set(rules) - allowed:
        raise ValueError("storage: expected a table with only supported storage settings")
    result = {
        "enabled": True,
        "check_tracked_ignored": True,
        "prohibited_patterns": [],
        "exceptions": [],
        **rules,
    }
    for name in ("enabled", "check_tracked_ignored"):
        if type(result[name]) is not bool:
            raise ValueError(f"storage.{name}: expected a boolean")
    for name in ("prohibited_patterns", "exceptions"):
        string_list(result[name], f"storage.{name}")
    for path in result["exceptions"]:
        if (
            PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(character in path for character in "*?[]\\")
        ):
            raise ValueError(f"storage.exceptions: expected an exact file path: {path!r}")

    lfs = result.get("lfs", {})
    fields = {"enforce_pointers", "raw_patterns", "max_raw_bytes", "binary_only", "fsck"}
    if not isinstance(lfs, dict) or set(lfs) - fields:
        raise ValueError("storage.lfs: expected a table with only supported LFS settings")
    result["lfs"] = {
        "enforce_pointers": True,
        "raw_patterns": [],
        "max_raw_bytes": 10485760,
        "binary_only": True,
        "fsck": "required",
        **lfs,
    }
    lfs = result["lfs"]
    for name in ("enforce_pointers", "binary_only"):
        if type(lfs[name]) is not bool:
            raise ValueError(f"storage.lfs.{name}: expected a boolean")
    string_list(lfs["raw_patterns"], "storage.lfs.raw_patterns")
    if type(lfs["max_raw_bytes"]) is not int or lfs["max_raw_bytes"] < 0:
        raise ValueError("storage.lfs.max_raw_bytes: expected a nonnegative integer")
    if lfs["fsck"] not in ("required", "optional", "off"):
        raise ValueError("storage.lfs.fsck: expected required, optional, or off")
    return result


def candidate_policy(candidate) -> dict:
    """Policy comes from the same stored tree as its paths and attributes."""
    return tomllib.loads(candidate.read_blob("PROJECT_POLICY.toml").decode("utf-8"))


def storage_errors(candidate, policy: dict) -> list[str]:
    """Collect exact storage identities without imposing a severity ordering."""
    rules = storage_rules(policy)
    if not rules["enabled"]:
        return []
    paths = sorted(set(candidate.entries) - set(rules["exceptions"]))
    ignored = candidate.ignored(paths) if rules["check_tracked_ignored"] else set()
    prohibited = candidate.match_patterns(paths, rules["prohibited_patterns"])
    lfs = rules["lfs"]
    size_paths = candidate.match_patterns(paths, lfs["raw_patterns"])
    attributes = candidate.attributes(paths, ["filter"])
    errors: list[str] = []

    for path in paths:
        entry = candidate.entries[path]

        def violation(rule: str, message: str) -> None:
            """Bind each obligation to the exact path, mode, and stored object."""
            errors.append(
                f"{path}: storage[{rule}]: {message} "
                f"(mode {entry.mode}, blob {entry.oid})"
            )

        if path in ignored:
            violation("tracked-ignore", "tracked path is ignored by candidate repository rules")
        if path in prohibited:
            violation("artifact", "tracked path matches configured prohibited artifacts")

        requires_pointer = (
            lfs["enforce_pointers"] and attributes[path].get("filter") == "lfs"
        )
        oversized = (
            path in size_paths and entry.size is not None
            and entry.size > lfs["max_raw_bytes"]
        )
        if not requires_pointer and not oversized:
            continue
        # Gitlinks are not blob content; attributed links cannot stand in for pointers.
        regular = entry.mode in ("100644", "100755")
        prefix = candidate.read_blob(path, limit=8000) if regular else b""
        try:
            pointer = regular and entry.size < 1024 and is_lfs_pointer(prefix.decode("utf-8"))
        except UnicodeDecodeError:
            pointer = False
        if requires_pointer and not pointer:
            violation("lfs-pointer", "effective filter=lfs requires a canonical stored LFS pointer")
        if oversized and regular and not pointer and (
            not lfs["binary_only"] or b"\0" in prefix
        ):
            violation(
                "raw-size",
                f"raw blob exceeds {lfs['max_raw_bytes']} bytes "
                f"(binary_only={lfs['binary_only']})",
            )
    return errors


def collect_storage_errors(
    root: Path, ref: str | None = None, policy: dict | None = None,
) -> list[str]:
    """Inspect a selected commit/tree or the staged index, never smudged bytes."""
    with candidate_snapshot(root, ref) as candidate:
        return storage_errors(candidate, candidate_policy(candidate) if policy is None else policy)


def introduced_errors(candidate: list[str], baseline: list[str]) -> list[str]:
    """Consume inherited occurrences once; changed violating blobs are new."""
    inherited = Counter(baseline)
    errors = []
    for error in candidate:
        if inherited[error]:
            inherited[error] -= 1
        else:
            errors.append(error)
    return errors


def storage_policy_errors(
    root: Path, baseline_ref: str | None = None, candidate_ref: str | None = None,
) -> list[str]:
    """Apply new enforcement to inherited state, while retaining old obligations."""
    with candidate_snapshot(root, candidate_ref) as candidate:
        policy = candidate_policy(candidate)
        errors = storage_errors(candidate, policy)
        if baseline_ref is None:
            return errors
        with candidate_snapshot(root, baseline_ref) as baseline:
            errors = introduced_errors(errors, storage_errors(baseline, policy))
            old_policy = candidate_policy(baseline)
            if storage_rules(policy) != storage_rules(old_policy):
                errors.extend(
                    f"under baseline storage policy: {error}"
                    for error in introduced_errors(
                        storage_errors(candidate, old_policy),
                        storage_errors(baseline, old_policy),
                    )
                )
            return errors


def historical_storage_errors(
    root: Path, baseline_ref: str, candidate_ref: str,
) -> list[str]:
    """Retain historical storage enforcement when its implementation changes.

    Run the old helper and old policy against exact stored trees in the original
    object database. Re-adding materialized files could apply clean filters and
    accidentally repair the very raw-blob violation being measured.
    """
    with candidate_snapshot(root, baseline_ref) as baseline:
        helper_path = "tools/ci/storage_policy.py"
        if helper_path not in baseline.entries:
            return []
        policy = candidate_policy(baseline)
        if not storage_rules(policy)["enabled"]:
            return []
        result = subprocess.run(
            [sys.executable, "-c",
             "import json, runpy, sys\n"
             "from pathlib import Path\n"
             "sys.path.insert(0, str(Path(sys.argv[1]).parent))\n"
             "collect = runpy.run_path(sys.argv[1])['collect_storage_errors']\n"
             "data = json.load(sys.stdin)\n"
             "print(json.dumps({name: collect(Path(data['root']), ref=data[name],\n"
             "    policy=data['policy']) for name in ('candidate', 'baseline')}))\n",
             str(baseline.root / helper_path)],
            input=json.dumps({
                "root": str(root), "policy": policy,
                "candidate": candidate_ref, "baseline": baseline.tree,
            }),
            capture_output=True, text=True, check=True,
        )
        evidence = json.loads(result.stdout)
        if not isinstance(evidence, dict) or set(evidence) != {"candidate", "baseline"}:
            raise ValueError("historical storage checker returned invalid evidence")
        for errors in evidence.values():
            if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
                raise ValueError("historical storage checker returned invalid diagnostics")
        return [
            f"under baseline storage checker and policy: {error}"
            for error in introduced_errors(evidence["candidate"], evidence["baseline"])
        ]
