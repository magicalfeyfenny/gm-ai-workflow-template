"""Select a declared framework comparison basis from the existing PR evidence.

This validates the declaration's shape and baseline binding. It does not prove
framework lineage or interpret the cited project authority; those conclusions
must be established by the adoption procedure and its reviewable evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?$")
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
STATES = frozenset({"ungoverned", "independent", "update", "ambiguous"})


def _nonempty(value: object, field: str) -> str:
    """Require an explicit statement rather than an empty assertion."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"framework adoption: {field} must be a nonempty string")
    return value


def _commit(value: object, field: str) -> str:
    """Require an immutable full commit identity, never a movable ref."""
    if not isinstance(value, str) or COMMIT_SHA.fullmatch(value) is None:
        raise ValueError(f"framework adoption: {field} must be a full commit SHA")
    return value


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    """Reject JSON duplicate keys instead of choosing one interpretation."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"framework adoption: duplicate field {key}")
        result[key] = value
    return result


def _declaration_text(body: str) -> str | None:
    """Select a top-level fence, keeping examples inside other fences inert."""
    fence = None
    collecting = False
    declaration = None
    lines = []
    for line in body.splitlines(keepends=True):
        match = FENCE.fullmatch(line.rstrip("\r\n"))
        if fence is not None:
            if (
                match is not None and not match.group(2).strip()
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= len(fence)
            ):
                if collecting:
                    declaration = "".join(lines)
                fence = None
                collecting = False
            elif collecting:
                lines.append(line)
            continue
        if match is None:
            continue
        fence, information = match.groups()
        if information.strip().startswith("framework-adoption"):
            if information.strip() != "framework-adoption":
                raise ValueError("framework adoption: malformed opening fence")
            if declaration is not None:
                raise ValueError("framework adoption: expected only one declaration")
            collecting = True
    if collecting:
        raise ValueError("framework adoption: declaration fence is not closed")
    return declaration


def _declaration(body: str) -> dict | None:
    """Read one optional declaration without interpreting other PR prose."""
    declaration = _declaration_text(body)
    if declaration is None:
        return None
    record = json.loads(declaration, object_pairs_hook=_unique_fields)
    if not isinstance(record, dict):
        raise ValueError("framework adoption: declaration must be an object")
    required = {"state", "baseline", "evidence"}
    if not required <= record.keys() or record.keys() - required - {"authority_disposition"}:
        raise ValueError("framework adoption: invalid declaration fields")
    return record


def _event_body(event_path: Path, baseline_sha: str | None) -> str:
    """Bind hosted selection to the same pull-request base being compared."""
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pull = event.get("pull_request") if isinstance(event, dict) else None
    base = pull.get("base") if isinstance(pull, dict) else None
    if not isinstance(base, dict):
        raise ValueError("framework adoption: event must contain a pull-request base")
    event_sha = _commit(base.get("sha"), "event base")
    if event_sha != _commit(baseline_sha, "selected baseline"):
        raise ValueError("framework adoption: event base does not match selected baseline")
    body = pull.get("body")
    if body is None:
        return ""
    if not isinstance(body, str):
        raise ValueError("framework adoption: event pull-request body must be a string")
    return body


def first_adoption(
    pr_body_file: Path | None,
    event_path: Path | None,
    baseline_sha: str | None,
) -> bool:
    """Select first adoption only from an explicit, resolved PR declaration.

    No declaration and known updates retain the historical comparison. File
    presence, filenames, and textual similarity do not determine lineage.
    """
    if pr_body_file is not None and event_path is not None:
        raise ValueError("framework adoption: select a PR body file or event, not both")
    if event_path is not None:
        body = _event_body(event_path, baseline_sha)
    elif pr_body_file is not None:
        body = pr_body_file.read_text(encoding="utf-8")
    else:
        return False
    record = _declaration(body)
    if record is None:
        return False
    state = record["state"]
    if not isinstance(state, str) or state not in STATES:
        raise ValueError("framework adoption: unknown lineage state")
    baseline = _commit(record["baseline"], "declared baseline")
    if baseline != _commit(baseline_sha, "selected baseline"):
        raise ValueError("framework adoption: declaration does not match selected baseline")
    _nonempty(record["evidence"], "evidence")
    if state == "independent" or "authority_disposition" in record:
        _nonempty(record.get("authority_disposition"), "authority_disposition")
    if state == "ambiguous":
        raise ValueError("framework adoption: ambiguous lineage needs a resolved comparison basis")
    return state in {"ungoverned", "independent"}
