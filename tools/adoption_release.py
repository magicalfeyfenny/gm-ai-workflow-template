"""Read-only evidence for an existing published release and candidate source."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

Evidence = dict[str, Any]


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Read local objects without replacement objects, locks, or lazy fetches."""
    environment = dict(os.environ)
    for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        environment.pop(key, None)
    environment.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    })
    command = [
        "git", "--no-replace-objects", "--no-optional-locks",
        "-c", "core.fsmonitor=false", "-c", "core.warnAmbiguousRefs=true",
        "-C", str(root), *arguments,
    ]
    try:
        return subprocess.run(
            command, text=True, capture_output=True, check=False,
            env=environment, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def _resolve(root: Path, reference: str) -> Evidence:
    """Resolve one explicit reference while refusing ambiguous short names."""
    result = _git(root, "rev-parse", "--verify", "--end-of-options", reference)
    if " is ambiguous" in result.stderr.lower():
        return {"status": "ambiguous", "reason": result.stderr.strip()}
    if result.returncode:
        return {"status": "unavailable", "reason": result.stderr.strip()}
    return {"status": "pass", "object": result.stdout.strip()}


def _published_at(release: Evidence) -> datetime | None:
    """Require a timezone-bearing publication timestamp for ordering releases."""
    try:
        value = datetime.fromisoformat(release.get("published_at", ""))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo is not None else None


def select_release(releases: list[Evidence], tag: str | None) -> Evidence:
    """Select an exact published tag or one uniquely latest stable release."""
    eligible = [
        release for release in releases
        if not release.get("draft", False)
        and (release.get("tag_name") == tag if tag is not None
             else not release.get("prerelease", False))
    ]
    if not eligible:
        return {"status": "unavailable", "reason": "No matching published release."}
    if tag is not None and len(eligible) > 1:
        return {"status": "ambiguous", "reason": "Multiple releases name the selected tag."}
    if any(_published_at(release) is None for release in eligible):
        return {"status": "unavailable", "reason": "Release publication timestamp is missing or invalid."}
    newest = max(_published_at(release) for release in eligible)
    selected = [release for release in eligible if _published_at(release) == newest]
    if len(selected) != 1:
        return {
            "status": "ambiguous",
            "reason": "Multiple stable releases share the latest publication timestamp.",
            "tags": [release.get("tag_name") for release in selected],
        }
    release = selected[0]
    if not isinstance(release.get("tag_name"), str) or not release["tag_name"]:
        return {"status": "unavailable", "reason": "Selected release has no tag name."}
    return {"status": "pass", "release": release}


def _release_anchor(root: Path, release: Evidence) -> Evidence:
    """Bind the exact remote tag object to the local object before peeling it."""
    reference = f"refs/tags/{release['tag_name']}"
    evidence: Evidence = {"ref": reference}
    valid = _git(root, "check-ref-format", reference)
    if valid.returncode == 1:
        return evidence | {"status": "fail", "reason": "Release tag is not a valid Git ref."}
    if valid.returncode:
        return evidence | {"status": "unavailable", "reason": valid.stderr.strip()}
    remote = release.get("tag_ref")
    if not isinstance(remote, dict) or remote.get("unavailable"):
        return evidence | {
            "status": "unavailable",
            "reason": "Exact remote tag reference is unavailable.",
            "remote": remote,
        }
    evidence["remote"] = remote
    if remote.get("ref") != reference:
        return evidence | {"status": "fail", "reason": "Remote reference does not name the selected tag."}
    remote_object = remote.get("object", {})
    if not isinstance(remote_object, dict) or not remote_object.get("sha"):
        return evidence | {"status": "unavailable", "reason": "Remote tag object identity is missing."}
    if remote_object.get("type") not in {"commit", "tag"}:
        return evidence | {"status": "fail", "reason": "Remote tag must identify a commit or annotated tag."}
    local = _resolve(root, reference)
    if local["status"] != "pass":
        return evidence | local
    evidence["local_object"] = local["object"]
    if local["object"] != remote_object["sha"]:
        return evidence | {"status": "fail", "reason": "Local and remote tag object identities differ."}
    object_type = _git(root, "cat-file", "-t", local["object"])
    if object_type.returncode:
        return evidence | {"status": "unavailable", "reason": object_type.stderr.strip()}
    evidence["kind"] = object_type.stdout.strip()
    if evidence["kind"] != remote_object["type"]:
        return evidence | {"status": "fail", "reason": "Local and remote tag object types differ."}
    commit = _resolve(root, f"{local['object']}^{{commit}}")
    if commit["status"] != "pass":
        return evidence | commit
    evidence["commit"] = commit["object"]
    tree = _resolve(root, f"{commit['object']}^{{tree}}")
    if tree["status"] != "pass":
        return evidence | tree
    return evidence | {"status": "pass", "tree": tree["object"]}


def _candidate(root: Path, reference: str) -> Evidence:
    """Resolve the candidate source without imposing commit or ancestry equality."""
    evidence: Evidence = {"ref": reference}
    if not reference:
        return evidence | {"status": "unavailable", "reason": "An explicit candidate ref is required."}
    commit = _resolve(root, f"{reference}^{{commit}}")
    if commit["status"] != "pass":
        return evidence | commit
    evidence["commit"] = commit["object"]
    tree = _resolve(root, f"{commit['object']}^{{tree}}")
    if tree["status"] != "pass":
        return evidence | tree
    return evidence | {"status": "pass", "tree": tree["object"]}


def _sha256(value: Any) -> str | None:
    """Recognize SHA256 values supplied directly or in GitHub digest notation."""
    if not isinstance(value, str):
        return None
    digest = value.removeprefix("sha256:")
    return digest.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", digest) else None


def _artifact(root: Path, spec: Evidence, assets: list[Evidence]) -> Evidence:
    """Compare an available local artifact with its explicit or published digest."""
    name = spec.get("name")
    required = spec.get("required", True)
    evidence: Evidence = {"name": name, "required": required}
    if not isinstance(name, str) or not name or not isinstance(required, bool):
        return evidence | {"status": "fail", "reason": "Artifact name and boolean required flag are mandatory."}
    matching = [asset for asset in assets if asset.get("name") == name]
    if len(matching) > 1:
        return evidence | {"status": "ambiguous", "reason": "Multiple published assets have this name."}
    asset = matching[0] if matching else {}
    evidence["published_metadata"] = (
        {"status": "available", "asset_id": asset.get("id")}
        if matching else
        {"status": "unavailable", "reason": "Named asset is absent from the release."}
    )
    published = _sha256(asset.get("digest"))
    evidence["published_digest"] = asset.get("digest")
    evidence["published_sha256"] = published
    expected = _sha256(spec.get("sha256"))
    if spec.get("sha256") is not None and expected is None:
        return evidence | {"status": "fail", "reason": "Explicit SHA256 digest is invalid."}
    if expected is not None and published is not None and expected != published:
        return evidence | {
            "status": "fail", "expected_sha256": expected,
            "reason": "Explicit and published SHA256 digests differ.",
        }
    evidence["expected_sha256"] = expected or published
    path = spec.get("path")
    if not isinstance(path, (str, Path)) or not str(path):
        return evidence | {"status": "unavailable", "reason": "No local artifact path was supplied."}
    local = Path(path)
    if not local.is_absolute():
        local = root / local
    evidence["path"] = str(local)
    try:
        if not local.is_file():
            return evidence | {"status": "unavailable", "reason": "Local artifact is not an available regular file."}
        with local.open("rb") as stream:
            evidence["local_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        return evidence | {"status": "unavailable", "reason": str(exc)}
    if evidence["expected_sha256"] is None:
        return evidence | {"status": "unavailable", "reason": "No expected SHA256 digest is available."}
    if evidence["local_sha256"] != evidence["expected_sha256"]:
        return evidence | {"status": "fail", "reason": "Local artifact SHA256 does not match the expected digest."}
    return evidence | {"status": "pass"}


def _combined_status(evidence: list[Evidence]) -> str:
    """Known contradictions and ambiguity take priority over missing evidence."""
    statuses = {item["status"] for item in evidence}
    for status in ("fail", "ambiguous", "unavailable"):
        if status in statuses:
            return status
    return "pass"


def verify_release(
    root: Path,
    releases: list[Evidence],
    tag: str | None,
    candidate_ref: str,
    artifacts: list[Evidence] | None = None,
) -> Evidence:
    """Verify observed source trees and separate artifact evidence without writes.

    Each release needs its exact observed GitHub ``tag_ref`` response. Explicit
    tags may select published prereleases; automatic selection uses the uniquely
    latest stable publication. Artifact specs use ``name``, local ``path``, optional
    ``sha256`` and ``required`` (default true). An explicit digest can verify a
    preserved historical file even if its published asset metadata is absent.
    Missing optional artifacts remain visible but do not prevent source
    verification; known mismatches always do.
    """
    selection = select_release(releases, tag)
    result: Evidence = {
        "status": selection["status"],
        "selection": {key: value for key, value in selection.items() if key != "release"},
        "requested_tag": tag,
        "candidate": _candidate(root, candidate_ref),
        "published_artifacts": [],
        "artifacts": [],
    }
    if selection["status"] != "pass":
        return result
    release = selection["release"]
    result["release"] = {
        key: release.get(key)
        for key in ("id", "tag_name", "published_at", "prerelease", "html_url", "target_commitish")
    }
    anchor = _release_anchor(root, release)
    result["anchor"] = anchor
    candidate = result["candidate"]
    result["provenance"] = {
        "release_commit": anchor.get("commit"),
        "candidate_commit": candidate.get("commit"),
        "target_commitish": release.get("target_commitish"),
        "target_commitish_is_immutable_anchor": False,
    }
    tree_status = _combined_status([anchor, candidate])
    equivalent = None
    if tree_status == "pass":
        equivalent = anchor["tree"] == candidate["tree"]
        tree_status = "pass" if equivalent else "fail"
    result["tree_equivalence"] = {
        "status": tree_status,
        "equivalent": equivalent,
        "release_tree": anchor.get("tree"),
        "candidate_tree": candidate.get("tree"),
    }
    assets = release.get("assets", [])
    result["published_artifacts"] = [
        {key: asset.get(key) for key in ("id", "name", "size", "digest", "browser_download_url")}
        for asset in assets
    ]
    result["artifacts"] = [_artifact(root, spec, assets) for spec in artifacts or []]
    assessed = [anchor, candidate, result["tree_equivalence"]]
    assessed.extend(
        artifact for artifact in result["artifacts"]
        if artifact["required"] or artifact["status"] in {"fail", "ambiguous"}
    )
    result["status"] = _combined_status(assessed)
    return result
