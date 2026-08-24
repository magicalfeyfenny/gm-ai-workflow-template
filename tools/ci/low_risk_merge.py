#!/usr/bin/env python3

"""Reconcile low-risk auto-merge with one owned pull-request snapshot.

Normal reads, readiness, and revocation use the built-in workflow token. The
repository App token is passed only to the final exact-head native merge call.

An eligible candidate deliberately has two PR reads around one complete file
fetch. The first read opens the ownership window; the second proves that the
attested metadata, base/head OIDs, and diff counts did not change while files
were fetched. Policy is evaluated once from that composite snapshot. A ready
PR needs one such window. Marking a draft ready is an external mutation, so it
requires a fresh complete window before merge configuration.

A failed CI run needs one metadata read to distinguish current evidence from a
stale run. Revocation keeps its final read even when the pre-read found no
request, because another worker could install one inside that window. Stale
evidence never mutates newer PR state. If a request appears between revocation
reads, one bounded retry disables it and verifies the result.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from tools.ci.pr_metadata import (
    INVALID,
    MATCH,
    STALE,
    MetadataError,
    compare_attestation,
    read_json_evidence,
)
from tools.ci.pr_policy import (
    PolicyEvaluation,
    changed_file_paths,
    evaluate_pull_request,
)


PR_FIELDS = ",".join(
    (
        "number",
        "baseRefName",
        "baseRefOid",
        "headRefName",
        "headRefOid",
        "headRepository",
        "body",
        "labels",
        "additions",
        "deletions",
        "changedFiles",
        "isDraft",
        "state",
        "autoMergeRequest",
    )
)


class MergeOutcome(str, Enum):
    """Describe the externally meaningful result of one merge run."""

    STALE = "stale CI evidence ignored"
    REJECTED = "unsafe auto-merge state rejected"
    CONFIGURED = "squash auto-merge configured"
    ALREADY_CONFIGURED = "auto-merge already configured"


@dataclass(frozen=True)
class MergeResult:
    """Pair an externally meaningful outcome with its concrete reason."""

    outcome: MergeOutcome
    reason: str


@dataclass(frozen=True)
class CiRun:
    """Bind orchestration inputs to one completed CI workflow run."""

    repository: str
    pull_request_number: int
    head_sha: str
    conclusion: str
    run_id: int
    run_attempt: int
    merge_token: str


class GitHubClient:
    """Perform the GitHub operations used by the low-risk state machine."""

    def __init__(
        self,
        repository: str,
        pull_request_number: int,
        token: str,
        workspace: Path,
    ) -> None:
        """Bind all normal operations to one repository, PR, and token."""
        self.repository = repository
        self.pull_request_number = pull_request_number
        self.token = token
        self.workspace = workspace

    def _run_gh(
        self,
        arguments: list[str],
        *,
        token: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run GitHub CLI with an explicit token and captured output."""
        environment = os.environ.copy()
        environment.pop("MERGE_TOKEN", None)
        environment["GH_TOKEN"] = self.token if token is None else token
        result = subprocess.run(
            ["gh", *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(detail or "GitHub CLI command failed")

        return result

    def snapshot(self) -> dict[str, object]:
        """Read one structured snapshot of the current pull request."""
        result = self._run_gh(
            [
                "pr",
                "view",
                str(self.pull_request_number),
                "--repo",
                self.repository,
                "--json",
                PR_FIELDS,
            ]
        )
        try:
            value = json.loads(result.stdout)
        except ValueError as exc:
            raise ValueError("pull request snapshot is not valid JSON") from exc

        if not isinstance(value, dict):
            raise ValueError("pull request snapshot must be an object")

        return value

    def changed_files(self) -> object:
        """Fetch every complete changed-file record, including rename data."""
        result = self._run_gh(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/pulls/"
                f"{self.pull_request_number}/files?per_page=100",
            ]
        )
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise ValueError("changed-file response is not valid JSON") from exc

    def download_attestation(
        self,
        run_id: int,
        run_attempt: int,
    ) -> tuple[object | None, int | None]:
        """Download this run's newest available metadata attestation."""
        last_error = "metadata artifact was not found"

        for attempt in range(run_attempt, 0, -1):
            destination = self.workspace / f"ci-metadata-{attempt}"
            artifact = f"pr-metadata-{run_id}-{attempt}"
            result = self._run_gh(
                [
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    self.repository,
                    "--name",
                    artifact,
                    "--dir",
                    str(destination),
                ],
                check=False,
            )

            if result.returncode != 0:
                last_error = (
                    result.stderr.strip()
                    or result.stdout.strip()
                    or last_error
                )
                continue

            path = destination / "pr-metadata.json"

            try:
                return read_json_evidence(path), attempt
            except MetadataError as exc:
                raise MetadataError(
                    f"downloaded CI metadata is invalid: {exc}"
                ) from exc

        raise RuntimeError(
            f"CI metadata artifact is unavailable: {last_error}"
        )

    def mark_ready(self) -> None:
        """Mark the current PR ready using the built-in workflow token."""
        self._run_gh(
            [
                "pr",
                "ready",
                str(self.pull_request_number),
                "--repo",
                self.repository,
            ]
        )

    def disable_auto_merge(self) -> None:
        """Disable auto-merge using the built-in workflow token."""
        self._run_gh(
            [
                "pr",
                "merge",
                str(self.pull_request_number),
                "--repo",
                self.repository,
                "--disable-auto",
            ]
        )

    def configure_auto_merge(
        self,
        head_sha: str,
        merge_token: str,
    ) -> None:
        """Use the App identity only for the exact-head final merge request."""
        if not merge_token:
            raise ValueError("merge App token is required")

        self._run_gh(
            [
                "pr",
                "merge",
                str(self.pull_request_number),
                "--repo",
                self.repository,
                "--auto",
                "--squash",
                "--match-head-commit",
                head_sha,
            ],
            token=merge_token,
        )


def _metadata_status(
    context: CiRun,
    attestation: object,
    attestation_attempt: int,
    snapshot: object,
) -> tuple[int, str]:
    """Classify current PR metadata against the triggering CI evidence."""
    return compare_attestation(
        attestation,
        snapshot,
        repository=context.repository,
        pull_request_number=context.pull_request_number,
        head_sha=context.head_sha,
        run_id=context.run_id,
        run_attempt=context.run_attempt,
        attestation_run_attempt=attestation_attempt,
    )


def _diff_identity(snapshot: dict[str, object]) -> tuple[object, ...]:
    """Extract immutable diff identity and counts from one PR snapshot."""
    base_oid = snapshot.get("baseRefOid")
    head_oid = snapshot.get("headRefOid")
    counts = tuple(
        snapshot.get(field)
        for field in (
            "additions",
            "deletions",
            "changedFiles",
        )
    )

    if not isinstance(base_oid, str) or not base_oid:
        raise ValueError("pull request base OID is missing")

    if not isinstance(head_oid, str) or not head_oid:
        raise ValueError("pull request head OID is missing")

    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for value in counts
    ):
        raise ValueError("pull request diff counts are invalid")

    return (base_oid, head_oid, *counts)


def _evaluate_policy(
    context: CiRun,
    snapshot: dict[str, object],
    changed_paths: list[str],
    changed_file_count: int,
) -> PolicyEvaluation:
    """Evaluate exact structured PR and file data through repository policy."""
    labels_value = snapshot.get("labels")
    head_repository_value = snapshot.get("headRepository")

    if not isinstance(labels_value, list):
        raise ValueError("pull request labels must be a list")

    if not isinstance(head_repository_value, dict):
        raise ValueError("pull request head repository is missing")

    label_names: set[str] = set()

    for label in labels_value:
        if not isinstance(label, dict) or not isinstance(label.get("name"), str):
            raise ValueError("pull request label is invalid")

        label_names.add(label["name"])

    body = snapshot.get("body")

    if body is None:
        body = ""

    if not isinstance(body, str):
        raise ValueError("pull request body is invalid")

    evaluation = evaluate_pull_request(
        base=str(snapshot.get("baseRefName", "")),
        head=str(snapshot.get("headRefName", "")),
        head_repository=str(
            head_repository_value.get("nameWithOwner", "")
        ),
        repository=context.repository,
        body=body,
        labels=label_names,
        additions=int(snapshot.get("additions", -1)),
        deletions=int(snapshot.get("deletions", -1)),
        changed_paths=changed_paths,
        changed_file_count=changed_file_count,
    )
    return evaluation


def _eligible_snapshot(
    context: CiRun,
    github: GitHubClient,
    attestation: object,
    attestation_attempt: int,
) -> tuple[int, dict[str, object] | None, str]:
    """Own one PR-and-files candidate between two attested snapshots."""
    try:
        before = github.snapshot()
        before_status, reason = _metadata_status(
            context,
            attestation,
            attestation_attempt,
            before,
        )

        if before_status != MATCH:
            return before_status, None, reason

        changed_file_pages = github.changed_files()
        after = github.snapshot()
        after_status, reason = _metadata_status(
            context,
            attestation,
            attestation_attempt,
            after,
        )

        if after_status != MATCH:
            return after_status, None, reason

        if before.get("state") != "OPEN" or after.get("state") != "OPEN":
            return INVALID, None, "pull request is not open"

        if _diff_identity(before) != _diff_identity(after):
            return (
                INVALID,
                None,
                "PR diff identity changed while files were fetched",
            )

        changed_paths, fetched_count = changed_file_paths(
            changed_file_pages
        )

        if fetched_count != after.get("changedFiles"):
            return (
                INVALID,
                None,
                "fetched file count differs from the PR snapshot",
            )

        evaluation = _evaluate_policy(
            context,
            after,
            changed_paths,
            fetched_count,
        )

        if not evaluation.auto_merge_allowed:
            details = [
                *evaluation.errors,
                *evaluation.high_risk_reasons,
            ]

            if evaluation.human_created:
                details.append("human-created PR requires human handling")
            elif evaluation.effective_high and not details:
                details.append("high-risk PR requires human handling")
            elif not details:
                details.append("current PR labels require manual handling")

            return INVALID, None, "; ".join(details)

        if not isinstance(after.get("isDraft"), bool):
            return INVALID, None, "pull request draft state is invalid"

        return MATCH, after, "current PR and changed files are eligible"
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        return INVALID, None, f"candidate snapshot is invalid: {exc}"


def revoke_pending_auto_merge(github: GitHubClient) -> bool:
    """Revoke pending state, including one concurrent installation race."""
    before = github.snapshot()
    changed = (
        before.get("state") == "OPEN"
        and before.get("autoMergeRequest") is not None
    )

    if changed:
        github.disable_auto_merge()

    after = github.snapshot()

    if (
        after.get("state") == "OPEN"
        and after.get("autoMergeRequest") is not None
    ):
        github.disable_auto_merge()
        changed = True
        after = github.snapshot()

    if after.get("autoMergeRequest") is not None:
        raise RuntimeError("auto-merge request remains after revocation")

    return changed


def run_low_risk_merge(
    context: CiRun,
    github: GitHubClient,
) -> MergeResult:
    """Reconcile one completed CI run with the PR auto-merge state."""
    try:
        attestation, attestation_attempt = github.download_attestation(
            context.run_id,
            context.run_attempt,
        )
    except (MetadataError, RuntimeError) as exc:
        revoke_pending_auto_merge(github)
        return MergeResult(
            MergeOutcome.REJECTED,
            str(exc),
        )

    if attestation is None or attestation_attempt is None:
        revoke_pending_auto_merge(github)
        return MergeResult(
            MergeOutcome.REJECTED,
            "CI metadata evidence is missing",
        )

    if context.conclusion != "success":
        current = github.snapshot()
        status, reason = _metadata_status(
            context,
            attestation,
            attestation_attempt,
            current,
        )

        if status == STALE:
            return MergeResult(MergeOutcome.STALE, reason)

        revoke_pending_auto_merge(github)
        return MergeResult(
            MergeOutcome.REJECTED,
            (
                f"CI concluded {context.conclusion} for current metadata"
                if status == MATCH
                else reason
            ),
        )

    status, candidate, reason = _eligible_snapshot(
        context,
        github,
        attestation,
        attestation_attempt,
    )

    if status == STALE:
        return MergeResult(MergeOutcome.STALE, reason)

    if status != MATCH or candidate is None:
        revoke_pending_auto_merge(github)
        return MergeResult(MergeOutcome.REJECTED, reason)

    if candidate["isDraft"]:
        github.mark_ready()
        status, candidate, reason = _eligible_snapshot(
            context,
            github,
            attestation,
            attestation_attempt,
        )

        if status == STALE:
            return MergeResult(MergeOutcome.STALE, reason)

        if status != MATCH or candidate is None:
            revoke_pending_auto_merge(github)
            return MergeResult(MergeOutcome.REJECTED, reason)

    if candidate.get("isDraft") is not False:
        revoke_pending_auto_merge(github)
        return MergeResult(
            MergeOutcome.REJECTED,
            "pull request remained a draft after readiness",
        )

    if candidate.get("autoMergeRequest") is not None:
        return MergeResult(
            MergeOutcome.ALREADY_CONFIGURED,
            "eligible current state already has an auto-merge request",
        )

    github.configure_auto_merge(
        context.head_sha,
        context.merge_token,
    )
    return MergeResult(
        MergeOutcome.CONFIGURED,
        "eligible current state is bound to the exact CI head",
    )


def _positive_integer(value: str) -> int:
    """Parse one positive CLI integer."""
    parsed = int(value)

    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")

    return parsed


def parse_args() -> argparse.Namespace:
    """Parse the cancel or completed-CI orchestration command."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    cancel = commands.add_parser("cancel")
    cancel.add_argument("--repository", required=True)
    cancel.add_argument(
        "--pull-request-number",
        type=_positive_integer,
        required=True,
    )

    merge = commands.add_parser("merge")
    merge.add_argument("--repository", required=True)
    merge.add_argument(
        "--pull-request-number",
        type=_positive_integer,
        required=True,
    )
    merge.add_argument("--head-sha", required=True)
    merge.add_argument("--conclusion", required=True)
    merge.add_argument("--run-id", type=_positive_integer, required=True)
    merge.add_argument(
        "--run-attempt",
        type=_positive_integer,
        required=True,
    )
    return parser.parse_args()


def _required_environment(name: str) -> str:
    """Read one required non-empty environment value."""
    value = os.environ.get(name, "").strip()

    if not value:
        raise RuntimeError(f"{name} is required")

    return value


def main() -> int:
    """Run the trusted low-risk merge boundary for GitHub Actions."""
    args = parse_args()

    with tempfile.TemporaryDirectory() as temporary:
        github = GitHubClient(
            args.repository,
            args.pull_request_number,
            _required_environment("GH_TOKEN"),
            Path(temporary),
        )

        if args.command == "cancel":
            changed = revoke_pending_auto_merge(github)
            print(
                "pending auto-merge revoked"
                if changed
                else "no pending auto-merge"
            )
            return 0

        context = CiRun(
            repository=args.repository,
            pull_request_number=args.pull_request_number,
            head_sha=args.head_sha,
            conclusion=args.conclusion,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            merge_token=_required_environment("MERGE_TOKEN"),
        )
        result = run_low_risk_merge(context, github)
        print(f"{result.outcome.value}: {result.reason}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
