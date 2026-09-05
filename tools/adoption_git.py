"""Collect local Git and LFS evidence without changing the inspected repository."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from itertools import combinations
from pathlib import Path

POINTER_LIMIT = 1024
REFLOG_LIMIT = 200


def _git(root: Path, *args: str, stdin: bytes | None = None):
    """Read Git state with optional writes and partial-clone fetching disabled."""
    env = os.environ.copy()
    for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        env.pop(key, None)
    env.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    })
    command = [
        "git", "--no-replace-objects", "--no-optional-locks",
        "-c", "core.fsmonitor=false", "-c", "core.warnAmbiguousRefs=true",
        "-C", str(root), *args,
    ]
    try:
        return subprocess.run(
            command, input=stdin, capture_output=True, env=env, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(command, 127, b"", str(error).encode())


def _error(result) -> str:
    """Keep unavailable-evidence diagnostics readable in the plan."""
    return result.stderr.decode("utf-8", errors="replace").strip()


def _resolve_ref(root: Path, requested: str) -> dict:
    """Capture a ref once, then peel its immutable object for consistent evidence."""
    evidence = {"requested": requested, "available": False}
    for key, suffix in (("object_id", ""), ("commit_id", "^{commit}"),
                        ("tree_id", "^{tree}")):
        revision = requested if key == "object_id" else evidence["object_id"] + suffix
        result = _git(root, "rev-parse", "--verify", "--end-of-options", revision)
        if result.returncode or b"ambiguous" in result.stderr:
            evidence["reason"] = _error(result) or "The ref is unavailable."
            return evidence
        evidence[key] = result.stdout.decode().strip()
    evidence["available"] = True
    return evidence


def _ancestry(root: Path, left: dict, right: dict, shallow: bool) -> dict:
    """Describe observed ancestry without treating divergence as rewriting."""
    result = {
        "left": left["requested"], "right": right["requested"],
        "relationship": "unknown", "merge_bases": [],
    }
    if not left["available"] or not right["available"]:
        result["reason"] = "At least one selected ref is unavailable."
        return result
    result["tree_equal"] = left["tree_id"] == right["tree_id"]
    a, b = left["commit_id"], right["commit_id"]
    if a == b:
        result.update(relationship="same_commit", merge_bases=[a])
        return result
    bases = _git(root, "merge-base", "--all", a, b)
    if bases.returncode not in (0, 1):
        result["reason"] = _error(bases)
        return result
    result["merge_bases"] = bases.stdout.decode().splitlines()
    if not result["merge_bases"]:
        if shallow:
            result["reason"] = "Shallow history cannot establish unrelatedness."
        else:
            result["relationship"] = "unrelated"
    elif a in result["merge_bases"]:
        result["relationship"] = "ancestor"
    elif b in result["merge_bases"]:
        result["relationship"] = "descendant"
    else:
        result["relationship"] = "divergent"
        if shallow:
            result["limitations"] = [
                "Divergence describes the available shallow graph only."
            ]
    return result


def _history(root: Path, refs: list[dict]) -> dict:
    """Preserve available historical records as evidence, without inference."""
    history = {
        "reflog_records": [], "replace_refs": [],
        "limitations": [
            "Divergence alone does not establish that history was rewritten.",
            f"Only the latest {REFLOG_LIMIT} locally available reflog records "
            "are inspected; expired, remote, and unavailable records are unknown.",
            "An absent matching reflog record does not establish unchanged history.",
            "Replace refs are recorded but disabled when resolving raw identities.",
        ],
    }
    selected = {ref["commit_id"] for ref in refs if ref["available"]}
    reflogs = _git(root, "reflog", "show", "--all", f"-n{REFLOG_LIMIT}",
                   "--date=iso-strict", "--format=%H%x00%gD%x00%gs")
    history["reflog_available"] = reflogs.returncode == 0
    if reflogs.returncode:
        history["limitations"].append(_error(reflogs))
    else:
        for line in reflogs.stdout.splitlines():
            parts = line.decode("utf-8", errors="replace").split("\0", 2)
            if len(parts) == 3 and parts[0] in selected:
                history["reflog_records"].append({
                    "commit_id": parts[0], "selector": parts[1],
                    "message": parts[2],
                })
    replacements = _git(root, "for-each-ref", "--format=%(refname) %(objectname)",
                        "refs/replace/")
    if replacements.returncode:
        history["limitations"].append(_error(replacements))
    else:
        for line in replacements.stdout.decode().splitlines():
            ref, object_id = line.split(" ", 1)
            history["replace_refs"].append({"ref": ref, "object_id": object_id})
    return history


def _lfs_storage(root: Path, common_dir: Path, git_dir: Path) -> dict:
    """Identify configured local LFS storage locations without invoking filters."""
    result = _git(root, "config", "--path", "--get", "lfs.storage")
    evidence = {"configured": None, "locations": [], "limitations": []}
    if result.returncode not in (0, 1):
        evidence["limitations"].append(_error(result))
        return evidence
    if result.returncode == 0:
        configured = result.stdout.decode("utf-8", errors="replace").strip()
        evidence["configured"] = configured
        storage = Path(configured)
        if storage.is_absolute():
            paths = [storage / "objects"]
        else:
            paths = [common_dir / storage / "objects", git_dir / storage / "objects"]
            if common_dir != git_dir:
                evidence["limitations"].append(
                    "Relative custom storage was checked against both the common "
                    "and worktree Git directories."
                )
    else:
        paths = [common_dir / "lfs" / "objects"]
    evidence["locations"] = list(dict.fromkeys(str(path) for path in paths))
    return evidence


def _lfs_object(pointer: dict, storage: dict) -> dict:
    """Check local object bytes against the pointer's distinct SHA-256 and size."""
    oid = pointer["oid"]
    checked = []
    errors = []
    for location in storage["locations"]:
        path = Path(location) / oid[:2] / oid[2:4] / oid
        checked.append(str(path))
        try:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
        except FileNotFoundError:
            continue
        except OSError as error:
            errors.append(str(error))
            continue
        actual = digest.hexdigest()
        valid = actual == oid and size == pointer["size"]
        return {
            "status": "available" if valid else "invalid",
            "path": str(path), "sha256": actual, "size": size,
            "digest_matches": actual == oid, "size_matches": size == pointer["size"],
        }
    return {
        "status": "unavailable" if errors or not checked else "missing",
        "checked_paths": checked, "errors": errors,
    }


def _pointer(data: bytes) -> dict | None:
    """Recognize v1 LFS pointers and report malformed candidates explicitly."""
    if not data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        return None
    oid = re.findall(rb"^oid sha256:([0-9a-f]{64})$", data, re.MULTILINE)
    size = re.findall(rb"^size ([0-9]+)$", data, re.MULTILINE)
    if len(oid) != 1 or len(size) != 1:
        return {"valid": False, "reason": "Malformed LFS v1 pointer metadata."}
    return {"valid": True, "oid": oid[0].decode(), "size": int(size[0])}


def _snapshot(root: Path, ref: dict, storage: dict, object_cache: dict) -> dict:
    """Read tracked configuration and pointer metadata from one exact tree."""
    snapshot = {
        "requested": ref["requested"], "commit_id": ref["commit_id"],
        "tree_id": ref["tree_id"], "available": False,
        "configuration_files": [], "lfs_pointers": [],
        "limitations": [
            f"LFS detection inspects blobs up to {POINTER_LIMIT} bytes for v1 "
            "pointer metadata; filters and network retrieval are never run.",
            "Local object availability does not establish remote LFS availability.",
        ],
    }
    tree = _git(root, "ls-tree", "-r", "-z", "--full-tree", ref["tree_id"])
    if tree.returncode:
        snapshot["limitations"].append(_error(tree))
        return snapshot
    entries = []
    for entry in tree.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split(" ")
        if kind == "blob":
            entries.append((path.decode("utf-8", errors="replace"), mode, oid))
    sizes = _git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                 stdin="".join(f"{oid}\n" for oid in dict.fromkeys(
                     entry[2] for entry in entries)).encode())
    if sizes.returncode:
        snapshot["limitations"].append(_error(sizes))
        return snapshot
    blob_sizes = {}
    for line in sizes.stdout.decode().splitlines():
        parts = line.split(" ")
        if len(parts) == 3 and parts[1] == "blob":
            blob_sizes[parts[0]] = int(parts[2])
        else:
            snapshot["limitations"].append(f"Unavailable blob evidence: {line}")
    snapshot["available"] = True
    contents = {}
    for path, mode, oid in entries:
        configuration = Path(path).name in (".gitattributes", ".lfsconfig")
        if oid not in blob_sizes:
            continue
        if not configuration and blob_sizes[oid] > POINTER_LIMIT:
            continue
        if oid not in contents:
            contents[oid] = _git(root, "cat-file", "blob", oid)
        blob = contents[oid]
        if blob.returncode:
            snapshot["limitations"].append(f"{path}: {_error(blob)}")
            continue
        if configuration:
            snapshot["configuration_files"].append({
                "path": path, "mode": mode, "blob_id": oid,
                "text": blob.stdout.decode("utf-8", errors="replace"),
            })
        pointer = _pointer(blob.stdout)
        if pointer is None:
            continue
        pointer.update(path=path, mode=mode, blob_id=oid)
        if pointer["valid"]:
            key = (pointer["oid"], pointer["size"])
            if key not in object_cache:
                object_cache[key] = _lfs_object(pointer, storage)
            pointer["local_object"] = object_cache[key]
        snapshot["lfs_pointers"].append(pointer)
    return snapshot


def collect_git_evidence(root: Path, refs: list[str]) -> dict:
    """Collect available identities, ancestry, history, and LFS snapshots read-only."""
    root = Path(root).resolve()
    evidence = {
        "repository": {"available": False, "root": str(root), "limitations": []},
        "refs": [], "ancestry": [], "history": {}, "snapshots": [],
    }
    repository = evidence["repository"]
    paths = _git(root, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    if paths.returncode:
        repository["limitations"].append(_error(paths))
        return evidence
    git_dir, common_dir = map(Path, paths.stdout.decode().splitlines())
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode:
        repository["limitations"].append(_error(shallow))
        return evidence
    repository.update(available=True, git_dir=str(git_dir), common_dir=str(common_dir),
                      shallow=shallow.stdout.strip() == b"true")
    if repository["shallow"]:
        repository["limitations"].append(
            "History is shallow; absence of an ancestor or common ancestor is inconclusive."
        )
    evidence["refs"] = [_resolve_ref(root, ref) for ref in dict.fromkeys(refs)]
    evidence["ancestry"] = [
        _ancestry(root, left, right, repository["shallow"])
        for left, right in combinations(evidence["refs"], 2)
    ]
    evidence["history"] = _history(root, evidence["refs"])
    evidence["lfs_storage"] = _lfs_storage(root, common_dir, git_dir)
    snapshots = {}
    objects = {}
    for ref in evidence["refs"]:
        if not ref["available"]:
            continue
        if ref["tree_id"] not in snapshots:
            snapshots[ref["tree_id"]] = _snapshot(root, ref, evidence["lfs_storage"], objects)
        snapshot = dict(snapshots[ref["tree_id"]])
        snapshot.update(requested=ref["requested"], commit_id=ref["commit_id"])
        evidence["snapshots"].append(snapshot)
    return evidence
