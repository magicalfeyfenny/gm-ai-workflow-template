#!/usr/bin/env python3
"""Obtain bounded Git LFS object evidence for one committed candidate."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

if __package__:
    from .candidate_git import candidate_snapshot, parse_lfs_pointer
    from .storage_policy import storage_rules
else:
    from candidate_git import candidate_snapshot, parse_lfs_pointer
    from storage_policy import storage_rules


ROOT = Path(__file__).resolve().parents[2]


class IntegrityError(ValueError):
    """The requested evidence could not be obtained."""


def _git(root, *args, environment=None, timeout=120):
    """Run bounded Git commands without inherited repository redirection."""
    env = os.environ.copy() if environment is None else environment.copy()
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        env.pop(name, None)
    env.update({
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1", "LC_ALL": "C",
    })
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", "-c", "core.fsmonitor=false",
             "-C", str(root), *args],
            capture_output=True, env=env, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntegrityError(str(error)) from error


def _details(result):
    """Keep command evidence readable without interpreting failure prose."""
    return (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()


def _mode(snapshot):
    """Use the same candidate enablement, defaults, and schema as pointer policy."""
    if "PROJECT_POLICY.toml" not in snapshot.entries:
        raise IntegrityError("The candidate has no PROJECT_POLICY.toml.")
    policy = tomllib.loads(snapshot.read_blob("PROJECT_POLICY.toml").decode("utf-8"))
    rules = storage_rules(policy)
    return rules["lfs"]["fsck"] if rules["enabled"] else "off"


def _pointers(snapshot):
    """Collect canonical pointer identities from stored candidate blobs only."""
    pointers = {}
    for path, entry in snapshot.entries.items():
        if entry.mode not in ("100644", "100755") or entry.size > 1024:
            continue
        pointer = parse_lfs_pointer(snapshot.read_blob(path).decode("utf-8", errors="replace"))
        if pointer is not None:
            pointers[path] = pointer
    return pointers


def _capability(root):
    """Require the object-checking option, rather than merely finding Git LFS."""
    version = _git(root, "lfs", "version")
    if version.returncode:
        return False, _details(version) or "Git LFS is unavailable."
    help_result = _git(root, "lfs", "fsck", "-h")
    if help_result.returncode or b"--objects" not in help_result.stdout:
        return False, "This Git LFS does not support fsck --objects."
    return True, version.stdout.decode("utf-8", errors="replace").strip()


def _copy_objects(root, pointers, storage):
    """Copy only candidate objects so fsck quarantine cannot change real storage."""
    result = _git(root, "lfs", "env")
    if result.returncode:
        raise IntegrityError("Git LFS storage information is unavailable: " + _details(result))
    locations = [line[len("LocalMediaDir="):] for line in
                 result.stdout.decode("utf-8", errors="replace").splitlines()
                 if line.startswith("LocalMediaDir=")]
    if len(locations) != 1 or not Path(locations[0]).is_absolute():
        raise IntegrityError("Git LFS did not identify its local object directory.")
    for oid in {pointer["oid"] for pointer in pointers.values()}:
        relative = Path(oid[:2]) / oid[2:4] / oid
        target = storage / "objects" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(Path(locations[0]) / relative, target)
        except FileNotFoundError:
            # Leave absence visible to fsck; a pointer is not object evidence.
            continue


def _lfs_options(storage):
    """Clear exclusions and recent-history expansion for this isolated check."""
    return (
        "-c", f"lfs.storage={storage}",
        "-c", f"core.hooksPath={storage / 'hooks'}",
        "-c", "lfs.fetchexclude=", "-c", "lfs.fetchinclude=",
        "-c", "lfs.fetchrecentalways=false",
    )


def _check_sizes(pointers, storage):
    """Check declared sizes, which fsck --objects alone does not enforce."""
    errors = []
    for path, pointer in pointers.items():
        oid = pointer["oid"]
        target = storage / "objects" / oid[:2] / oid[2:4] / oid
        if not target.is_file():
            errors.append(f"{path}: object {oid} is missing")
        elif target.stat().st_size != pointer["size"]:
            errors.append(f"{path}: object size differs from its stored pointer")
    return errors


def collect_integrity(root, candidate_ref="HEAD", *, fetch_remote=None):
    """Report capability and actual object evidence separately from pointer policy."""
    root = Path(root).resolve()
    report = {"candidate_ref": candidate_ref, "status": "unavailable", "mode": None}
    try:
        resolved = _git(root, "rev-parse", "--verify", "--end-of-options",
                        candidate_ref + "^{commit}")
        if resolved.returncode or b"ambiguous" in resolved.stderr:
            raise IntegrityError("Candidate commit is unavailable: " + _details(resolved))
        commit = resolved.stdout.decode().strip()
        report["candidate_commit"] = commit
        with candidate_snapshot(root, commit) as snapshot:
            report["candidate_tree"] = snapshot.tree
            mode = _mode(snapshot)
            report["mode"] = mode
            if mode == "off":
                report.update(status="off", reason="Object integrity checking is disabled by candidate policy.")
                return report
            pointers = _pointers(snapshot)
            report["pointer_count"] = len(pointers)
            if not pointers:
                report.update(status="not-applicable", reason="The candidate contains no canonical stored LFS pointers; pointer storage policy is checked separately.")
                return report
            supported, detail = _capability(root)
            report["capability"] = detail
            if not supported:
                report.update(status="unsupported", reason="Git LFS object integrity capability is unavailable.")
                return report
            storage = snapshot.root / ".git" / "integrity-lfs"
            _copy_objects(root, pointers, storage)
            options = _lfs_options(storage)
            if fetch_remote is not None:
                if not fetch_remote or fetch_remote.startswith("-"):
                    raise IntegrityError("Fetch remote must be a non-option remote name.")
                fetched = _git(root, *options, "lfs", "fetch", "--include=", "--exclude=",
                               fetch_remote, commit, timeout=600)
                report["fetch_exit_code"] = fetched.returncode
                if fetched.returncode:
                    raise IntegrityError("Candidate LFS objects could not be fetched: " + _details(fetched))
            size_errors = _check_sizes(pointers, storage)
            result = _git(snapshot.root, *options, "lfs", "fsck", "--objects", commit,
                          environment=snapshot.environment, timeout=600)
            report["fsck_exit_code"] = result.returncode
            report["fsck_output"] = _details(result)
            report["object_errors"] = size_errors
            if result.returncode or size_errors:
                report.update(status="failed", reason="Candidate LFS object integrity failed.")
            else:
                report.update(status="passed", reason="git lfs fsck --objects succeeded for the candidate; object sizes match its pointers.")
    except (IntegrityError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status="unavailable", reason=str(error))
    return report


def evidence_exit_code(report):
    """Only optional unsupported capability may omit applicable object evidence."""
    if report["status"] in ("passed", "off", "not-applicable"):
        return 0
    if report["status"] == "unsupported" and report["mode"] == "optional":
        return 0
    return 1


def main(argv=None):
    """Emit a reviewable result and fail closed when required evidence is absent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate-ref", default="HEAD")
    parser.add_argument("--fetch-remote")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = collect_integrity(args.root, args.candidate_ref, fetch_remote=args.fetch_remote)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return evidence_exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
