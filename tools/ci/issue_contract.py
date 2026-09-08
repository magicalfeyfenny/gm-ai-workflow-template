#!/usr/bin/env python3
"""Bind completion evidence to the accepted, live governing issue contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable

from tools.ci.pr_policy import branch_issue, is_human_created

COMPLETION_LABELS = {"work:complete", "work:review-ready"}
MARKER = re.compile(
    r"<!-- issue-contract:v1 #([1-9][0-9]*) sha256:([0-9a-f]{64}) -->"
)
MARKER_START = re.compile(r"<!--\s*issue-contract\b", re.IGNORECASE)
ISSUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!,
      $labels_after: String, $blockers_after: String,
      $fetch_labels: Boolean!, $fetch_blockers: Boolean!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id number title body state repository { nameWithOwner }
      labels(first: 100, after: $labels_after) @include(if: $fetch_labels) {
        nodes { name }
        pageInfo { hasNextPage endCursor }
      }
      blockedBy(first: 100, after: $blockers_after)
        @include(if: $fetch_blockers) {
        nodes { id state }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class ContractError(ValueError):
    """Reject incomplete, changed, or ineligible issue contract evidence."""


def _object(value: object, field: str) -> dict:
    """Require an object rather than interpreting missing API data as empty."""
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be an object")
    return value


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    """Require exact textual contract content without normalizing its bytes."""
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ContractError(f"{field} must be {'a' if allow_empty else 'a nonempty'} string")
    return value


def _number(value: object) -> int:
    """Require a positive issue number, excluding JSON booleans."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError("issue number must be a positive integer")
    return value


def _repository(value: object) -> str:
    """Require an unambiguous owner/repository identity."""
    repository = _string(value, "repository")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise ContractError("repository must have owner/name form")
    return repository


def _state(value: object, field: str) -> str:
    """Reject unknown issue states instead of treating them as resolved."""
    if value not in ("OPEN", "CLOSED"):
        raise ContractError(f"{field} must be OPEN or CLOSED")
    return value


def _connection(value: object, field: str, *, complete: bool = True) -> dict:
    """Require explicit pagination evidence for each native connection."""
    connection = _object(value, field)
    if not isinstance(connection.get("nodes"), list):
        raise ContractError(f"{field}.nodes must be an array")
    page_info = _object(connection.get("pageInfo"), f"{field}.pageInfo")
    if type(page_info.get("hasNextPage")) is not bool:
        raise ContractError(f"{field}.pageInfo.hasNextPage must be a boolean")
    if complete and page_info["hasNextPage"]:
        raise ContractError(f"{field} pagination is incomplete")
    return connection


def _accepted_marker(body: str, number: int) -> str:
    """Read exactly one well-formed acceptance marker for the branch issue."""
    matches = MARKER.findall(body)
    if len(matches) != 1 or len(MARKER_START.findall(body)) != 1:
        raise ContractError("completed PR requires exactly one valid issue-contract:v1 marker")
    marker_number, revision = matches[0]
    if int(marker_number) != number:
        raise ContractError("issue contract marker must match branch issue")
    return revision


def governing_issue(state: dict) -> int | None:
    """Identify completion scope while preserving milestone and human routing."""
    state = _object(state, "PR state")
    labels = state.get("labels")
    if not isinstance(labels, (list, set, tuple)) or any(
        not isinstance(label, str) or not label for label in labels
    ):
        raise ContractError("PR labels must contain nonempty strings")
    if len(labels) != len(set(labels)):
        raise ContractError("PR labels contain duplicate names")
    labels = set(labels)
    repository = _repository(state.get("repository"))
    head = _string(state.get("head_ref"), "PR head_ref")
    head_repository = _string(state.get("head_repository"), "PR head_repository")
    if is_human_created(head, labels, head_repository, repository):
        return None

    body = _string(state.get("body"), "PR body", allow_empty=True)
    closing_lines = re.findall(r"(?mi)^Closes\b[^\r\n]*$", body)
    completion_labels = labels.intersection(COMPLETION_LABELS)
    if not completion_labels and not closing_lines:
        return None
    if len(completion_labels) != 1:
        raise ContractError("completed PR requires exactly one work completion label")
    if "work:blocked" in labels:
        raise ContractError("work:blocked PR cannot claim completion")

    number, errors = branch_issue(
        _string(state.get("base_ref"), "PR base_ref"), head,
    )
    if errors or number is None:
        raise ContractError("; ".join(errors) or "missing branch issue")
    closures = re.findall(r"(?mi)^Closes #([1-9][0-9]*)\s*$", body)
    if len(closing_lines) != 1 or len(closures) != 1:
        raise ContractError("completed PR requires exactly one Closes #<issue> line")
    if int(closures[0]) != number:
        raise ContractError("PR closing issue must match branch issue")
    _accepted_marker(body, number)
    return number


def accepted_revision(state: dict) -> str | None:
    """Return explicit Stage 2 acceptance, never acceptance inferred by CI."""
    number = governing_issue(state)
    return None if number is None else _accepted_marker(state["body"], number)


def canonical_contract(issue: object, repository: str, number: int) -> dict:
    """Capture contract-bearing content and unresolved native blocker IDs."""
    repository = _repository(repository)
    number = _number(number)
    issue = _object(issue, "issue")
    identity = _object(issue.get("repository"), "issue.repository")
    if identity.get("nameWithOwner") != repository or _number(issue.get("number")) != number:
        raise ContractError("live issue identity does not match governing repository/number")
    labels = _connection(issue.get("labels"), "issue.labels")["nodes"]
    names = [
        _string(_object(label, "issue label").get("name"), "issue label.name")
        for label in labels
    ]
    if len(names) != len(set(names)):
        raise ContractError("issue labels contain duplicate names")

    blocker_ids: set[str] = set()
    open_blocker_ids: list[str] = []
    for entry in _connection(issue.get("blockedBy"), "issue.blockedBy")["nodes"]:
        blocker = _object(entry, "issue blocker")
        identifier = _string(blocker.get("id"), "issue blocker.id")
        blocker_state = _state(blocker.get("state"), "issue blocker.state")
        if identifier in blocker_ids:
            raise ContractError("issue blockers contain duplicate IDs")
        blocker_ids.add(identifier)
        if blocker_state == "OPEN":
            open_blocker_ids.append(identifier)

    return {
        "repository": repository,
        "id": _string(issue.get("id"), "issue.id"),
        "number": number,
        "title": _string(issue.get("title"), "issue.title"),
        "body": _string(issue.get("body"), "issue.body", allow_empty=True),
        "state": _state(issue.get("state"), "issue.state"),
        "work_blocked": "work:blocked" in names,
        "open_blocker_ids": sorted(open_blocker_ids),
    }


def contract_digest(contract: dict) -> str:
    """Hash canonical JSON with exact title/body text and deterministic order."""
    encoded = json.dumps(
        contract, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def acceptance_marker(number: int, sha256: str) -> str:
    """Format the explicit issue revision accepted after Stage 2 re-evaluation."""
    _number(number)
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ContractError("issue contract digest must be 64 lowercase hexadecimal characters")
    return f"<!-- issue-contract:v1 #{number} sha256:{sha256} -->"


def completion_contract(state: dict, issue: object) -> dict | None:
    """Require the accepted revision to remain live, open, and unblocked."""
    number = governing_issue(state)
    if number is None:
        return None
    contract = canonical_contract(issue, state["repository"], number)
    if contract["state"] != "OPEN":
        raise ContractError("governing issue must remain OPEN for completion")
    if contract["work_blocked"] or contract["open_blocker_ids"]:
        raise ContractError("governing issue has unresolved blockers")
    revision = contract_digest(contract)
    if revision != accepted_revision(state):
        raise ContractError("governing issue contract changed; re-evaluate Stage 2 and accept its new revision")
    return {"number": number, "sha256": revision}


def _run_gh(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Read GitHub without exposing the separately scoped merge token."""
    environment = os.environ.copy()
    environment.pop("MERGE_TOKEN", None)
    return subprocess.run(
        ["gh", *arguments], check=False, capture_output=True,
        text=True, env=environment,
    )


def fetch_issue(
    repository: str,
    number: int,
    run_gh: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict:
    """Fetch all connection pages and reject API errors or changing page identity."""
    repository = _repository(repository)
    number = _number(number)
    owner, name = repository.split("/")
    runner = _run_gh if run_gh is None else run_gh
    cursors: dict[str, str | None] = {"labels": None, "blockedBy": None}
    cursor_names = {"labels": "labels_after", "blockedBy": "blockers_after"}
    fetch_names = {"labels": "fetch_labels", "blockedBy": "fetch_blockers"}
    seen_cursors: dict[str, set[str]] = {key: set() for key in cursors}
    pending = set(cursors)
    combined: dict = {}
    baseline: dict | None = None

    while pending:
        arguments = [
            "api", "graphql", "-f", f"query={ISSUE_QUERY}",
            "-f", f"owner={owner}", "-f", f"name={name}",
            "-F", f"number={number}",
        ]
        for field, cursor in cursors.items():
            arguments.extend(["-F", f"{fetch_names[field]}={str(field in pending).lower()}"])
            if cursor is not None:
                arguments.extend(["-f", f"{cursor_names[field]}={cursor}"])
        try:
            result = runner(arguments)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            raise ContractError(f"cannot fetch governing issue: {error}") from error
        if result.returncode:
            raise ContractError("cannot fetch governing issue: GitHub CLI failed")
        try:
            response = _object(json.loads(result.stdout), "GraphQL response")
        except (TypeError, json.JSONDecodeError) as error:
            raise ContractError("governing issue response is not valid JSON") from error
        if "errors" in response and response["errors"] != []:
            raise ContractError("governing issue GraphQL response contains errors")
        data = _object(response.get("data"), "GraphQL data")
        repo = _object(data.get("repository"), "GraphQL repository")
        issue = _object(repo.get("issue"), "GraphQL issue")
        identity = {key: issue.get(key) for key in (
            "id", "number", "title", "body", "state", "repository",
        )}
        if baseline is None:
            baseline = identity
            combined.update(identity)
        elif identity != baseline:
            raise ContractError("governing issue changed during pagination; retry the snapshot")
        for field in tuple(pending):
            connection = _connection(issue.get(field), f"issue.{field}", complete=False)
            target = combined.setdefault(field, {"nodes": [], "pageInfo": {"hasNextPage": False}})
            target["nodes"].extend(connection["nodes"])
            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                pending.remove(field)
                continue
            cursor = _string(page_info.get("endCursor"), f"issue.{field}.pageInfo.endCursor")
            if cursor in seen_cursors[field]:
                raise ContractError(f"issue.{field} pagination cursor did not advance")
            seen_cursors[field].add(cursor)
            cursors[field] = cursor

    canonical_contract(combined, repository, number)
    return combined


def main(argv: list[str] | None = None) -> int:
    """Print a read-only snapshot and marker for explicit Stage 2 acceptance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    arguments = parser.parse_args(argv)
    try:
        issue = fetch_issue(arguments.repository, arguments.issue_number)
        contract = canonical_contract(issue, arguments.repository, arguments.issue_number)
        revision = contract_digest(contract)
        print(json.dumps({
            "contract": contract,
            "sha256": revision,
            "acceptance_marker": acceptance_marker(arguments.issue_number, revision),
        }, ensure_ascii=False, indent=2, sort_keys=True))
    except ContractError as error:
        print(f"issue contract: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
