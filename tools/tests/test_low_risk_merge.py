import json
import os
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tools.ci.low_risk_merge import (
    CiRun,
    GitHubClient,
    MergeOutcome,
    revoke_pending_auto_merge,
    run_low_risk_merge,
)
from tools.ci.pr_metadata import (
    MAX_JSON_BYTES,
    MetadataError,
    build_attestation,
)


REPOSITORY = "owner/game"
PR_NUMBER = 42
HEAD_SHA = "a" * 40
BASE_OID = "b" * 40
RUN_ID = 987654
RUN_ATTEMPT = 2
BUILTIN_TOKEN = "built-in-token"
MERGE_TOKEN = "app-token"


def pull_request_snapshot(
    *,
    body: str = "Closes #42\n",
    labels: tuple[str, ...] = ("risk:low", "work:complete"),
    base_oid: str = BASE_OID,
    head_oid: str = HEAD_SHA,
    additions: int = 12,
    deletions: int = 3,
    changed_files: int = 1,
    is_draft: bool = False,
    state: str = "OPEN",
    auto_merge_request: object | None = None,
) -> dict[str, object]:
    """Build one complete PR snapshot used by policy and race checks."""
    return {
        "number": PR_NUMBER,
        "baseRefName": "dev",
        "baseRefOid": base_oid,
        "headRefName": "work/42-simplify-low-risk-merge",
        "headRefOid": head_oid,
        "headRepository": {
            "nameWithOwner": REPOSITORY,
        },
        "body": body,
        "labels": [{"name": label} for label in labels],
        "additions": additions,
        "deletions": deletions,
        "changedFiles": changed_files,
        "isDraft": is_draft,
        "state": state,
        "autoMergeRequest": auto_merge_request,
    }


def file_pages(count: int = 1) -> list[list[dict[str, str]]]:
    """Build paginated complete file records for one ownership window."""
    return [
        [
            {
                "filename": (
                    "README.md"
                    if index == 0
                    else f"docs/example-{index}.md"
                ),
                "status": "modified",
            }
            for index in range(count)
        ]
    ]


def attestation_for(
    snapshot: dict[str, object],
    *,
    run_id: int = RUN_ID,
    run_attempt: int = RUN_ATTEMPT,
) -> dict[str, object]:
    """Build CI evidence whose metadata exactly matches a PR snapshot."""
    head_repository = snapshot["headRepository"]
    labels = snapshot["labels"]

    if not isinstance(head_repository, dict) or not isinstance(labels, list):
        raise ValueError("test snapshot metadata is malformed")

    event = {
        "repository": {
            "full_name": REPOSITORY,
        },
        "pull_request": {
            "number": snapshot["number"],
            "base": {
                "ref": snapshot["baseRefName"],
            },
            "head": {
                "ref": snapshot["headRefName"],
                "sha": snapshot["headRefOid"],
                "repo": {
                    "full_name": head_repository["nameWithOwner"],
                },
            },
            "body": snapshot["body"],
            "labels": deepcopy(labels),
        },
    }
    return build_attestation(
        event,
        REPOSITORY,
        run_id,
        run_attempt,
    )


def ci_context(
    *,
    conclusion: str = "success",
    run_attempt: int = RUN_ATTEMPT,
) -> CiRun:
    """Build one completed-CI context for orchestration tests."""
    return CiRun(
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        head_sha=HEAD_SHA,
        conclusion=conclusion,
        run_id=RUN_ID,
        run_attempt=run_attempt,
        merge_token=MERGE_TOKEN,
    )


class FakeGitHub:
    """Expose deterministic PR windows and record every external mutation."""

    def __init__(
        self,
        snapshots: list[dict[str, object]],
        *,
        attestation: object | None,
        attestation_attempt: int | None = RUN_ATTEMPT,
        file_windows: list[object] | None = None,
    ) -> None:
        """Store ordered reads; the final supplied value repeats if needed."""
        if not snapshots:
            raise ValueError("at least one snapshot is required")

        self._snapshots = deepcopy(snapshots)
        self._file_windows = deepcopy(file_windows or [file_pages()])
        self.attestation = deepcopy(attestation)
        self.attestation_attempt = attestation_attempt
        self.snapshot_calls = 0
        self.changed_files_calls = 0
        self.downloads: list[tuple[int, int]] = []
        self.events: list[str] = []
        self.ready_count = 0
        self.disabled_count = 0
        self.configurations: list[tuple[str, str]] = []

    def snapshot(self) -> dict[str, object]:
        """Return the next PR snapshot without sharing mutable test state."""
        index = min(self.snapshot_calls, len(self._snapshots) - 1)
        self.snapshot_calls += 1
        self.events.append("snapshot")
        return deepcopy(self._snapshots[index])

    def changed_files(self) -> object:
        """Return complete file pages for the next ownership window."""
        index = min(
            self.changed_files_calls,
            len(self._file_windows) - 1,
        )
        self.changed_files_calls += 1
        self.events.append("files")
        return deepcopy(self._file_windows[index])

    def download_attestation(
        self,
        run_id: int,
        run_attempt: int,
    ) -> tuple[object | None, int | None]:
        """Return the configured same-run attestation candidate."""
        self.downloads.append((run_id, run_attempt))
        self.events.append("attestation")
        return deepcopy(self.attestation), self.attestation_attempt

    def mark_ready(self) -> None:
        """Record the built-in-token readiness mutation."""
        self.ready_count += 1
        self.events.append("ready")

    def disable_auto_merge(self) -> None:
        """Record the built-in-token revocation mutation."""
        self.disabled_count += 1
        self.events.append("disable")

    def configure_auto_merge(
        self,
        head_sha: str,
        merge_token: str,
    ) -> None:
        """Record the App-token exact-head final operation."""
        self.configurations.append((head_sha, merge_token))
        self.events.append("configure")


class LowRiskMergeTests(unittest.TestCase):
    """Verify the low-risk merge boundary through meaningful state changes."""

    def test_ready_pr_uses_one_owned_window_and_exact_final_call(self) -> None:
        """A stable ready candidate needs two snapshots and one file fetch."""
        current = pull_request_snapshot()
        github = FakeGitHub(
            [current, current],
            attestation=attestation_for(current),
        )

        outcome = run_low_risk_merge(ci_context(), github)

        self.assertEqual(outcome.outcome, MergeOutcome.CONFIGURED)
        self.assertEqual(github.snapshot_calls, 2)
        self.assertEqual(github.changed_files_calls, 1)
        self.assertEqual(github.ready_count, 0)
        self.assertEqual(
            github.configurations,
            [(HEAD_SHA, MERGE_TOKEN)],
        )
        self.assertEqual(
            github.events,
            ["attestation", "snapshot", "files", "snapshot", "configure"],
        )

    def test_draft_is_revalidated_after_readiness_mutation(self) -> None:
        """Readiness opens a fresh full ownership window before auto-merge."""
        draft = pull_request_snapshot(is_draft=True)
        ready = pull_request_snapshot(is_draft=False)
        github = FakeGitHub(
            [draft, draft, ready, ready],
            attestation=attestation_for(draft),
            file_windows=[file_pages(), file_pages()],
        )

        outcome = run_low_risk_merge(ci_context(), github)

        self.assertEqual(outcome.outcome, MergeOutcome.CONFIGURED)
        self.assertEqual(github.snapshot_calls, 4)
        self.assertEqual(github.changed_files_calls, 2)
        self.assertEqual(github.ready_count, 1)
        self.assertEqual(
            github.events,
            [
                "attestation",
                "snapshot",
                "files",
                "snapshot",
                "ready",
                "snapshot",
                "files",
                "snapshot",
                "configure",
            ],
        )

    def test_snapshot_identity_and_file_count_drift_fail_closed(self) -> None:
        """Every owned diff field must remain stable and match file records."""
        pending = {"enabledAt": "2026-08-24T00:00:00Z"}
        stable = pull_request_snapshot(auto_merge_request=pending)
        cases = {
            "base OID": (
                stable,
                pull_request_snapshot(
                    base_oid="c" * 40,
                    auto_merge_request=pending,
                ),
                file_pages(),
                MergeOutcome.REJECTED,
                1,
            ),
            "head OID": (
                stable,
                pull_request_snapshot(
                    head_oid="d" * 40,
                    auto_merge_request=pending,
                ),
                file_pages(),
                MergeOutcome.STALE,
                0,
            ),
            "line counts": (
                stable,
                pull_request_snapshot(
                    additions=13,
                    auto_merge_request=pending,
                ),
                file_pages(),
                MergeOutcome.REJECTED,
                1,
            ),
            "fetched file count": (
                pull_request_snapshot(
                    changed_files=2,
                    auto_merge_request=pending,
                ),
                pull_request_snapshot(
                    changed_files=2,
                    auto_merge_request=pending,
                ),
                file_pages(1),
                MergeOutcome.REJECTED,
                1,
            ),
        }

        for name, (
            before,
            after,
            files,
            expected,
            revocations,
        ) in cases.items():
            with self.subTest(name=name):
                cleared = deepcopy(after)
                cleared["autoMergeRequest"] = None
                github = FakeGitHub(
                    [before, after, after, cleared],
                    attestation=attestation_for(before),
                    file_windows=[files],
                )

                outcome = run_low_risk_merge(ci_context(), github)

                self.assertEqual(outcome.outcome, expected)
                self.assertEqual(github.disabled_count, revocations)
                self.assertEqual(github.configurations, [])

    def test_metadata_drift_is_stale_without_mutation(self) -> None:
        """Same-head body or label drift must wait for new CI evidence."""
        validated = pull_request_snapshot()
        changed = pull_request_snapshot(
            body="Closes #42\n\nNew unvalidated text.\n",
            auto_merge_request={"enabledAt": "earlier"},
        )
        github = FakeGitHub(
            [changed],
            attestation=attestation_for(validated),
        )

        outcome = run_low_risk_merge(ci_context(), github)

        self.assertEqual(outcome.outcome, MergeOutcome.STALE)
        self.assertTrue(outcome.reason)
        self.assertEqual(github.snapshot_calls, 1)
        self.assertEqual(github.changed_files_calls, 0)
        self.assertEqual(github.ready_count, 0)
        self.assertEqual(github.disabled_count, 0)
        self.assertEqual(github.configurations, [])

    def test_failed_ci_revokes_matching_state_but_ignores_stale_state(self) -> None:
        """A failed run owns matching metadata but not newer PR metadata."""
        pending = pull_request_snapshot(
            auto_merge_request={"enabledAt": "earlier"}
        )
        cleared = pull_request_snapshot()
        matching = FakeGitHub(
            [pending, pending, cleared],
            attestation=attestation_for(pending),
        )

        matching_outcome = run_low_risk_merge(
            ci_context(conclusion="failure"),
            matching,
        )

        self.assertEqual(
            matching_outcome.outcome,
            MergeOutcome.REJECTED,
        )
        self.assertEqual(matching.disabled_count, 1)
        self.assertEqual(matching.configurations, [])

        validated = pull_request_snapshot()
        newer = pull_request_snapshot(
            body="Closes #42\n\nNewer metadata.\n",
            auto_merge_request={"enabledAt": "earlier"},
        )
        stale = FakeGitHub(
            [newer],
            attestation=attestation_for(validated),
        )

        stale_outcome = run_low_risk_merge(
            ci_context(conclusion="failure"),
            stale,
        )

        self.assertEqual(stale_outcome.outcome, MergeOutcome.STALE)
        self.assertEqual(stale.snapshot_calls, 1)
        self.assertEqual(stale.disabled_count, 0)
        self.assertEqual(stale.configurations, [])

    def test_missing_invalid_and_cross_run_evidence_never_configure(self) -> None:
        """Untrusted attestation states reject and revoke any old request."""
        pending = pull_request_snapshot(
            auto_merge_request={"enabledAt": "earlier"}
        )
        cleared = pull_request_snapshot()
        cases = {
            "missing": (None, None, [pending, cleared]),
            "invalid": ({}, RUN_ATTEMPT, [pending, pending, cleared]),
            "cross-run": (
                attestation_for(pending, run_id=RUN_ID + 1),
                RUN_ATTEMPT,
                [pending, pending, cleared],
            ),
        }

        for name, (evidence, attempt, snapshots) in cases.items():
            with self.subTest(name=name):
                github = FakeGitHub(
                    snapshots,
                    attestation=evidence,
                    attestation_attempt=attempt,
                )

                outcome = run_low_risk_merge(ci_context(), github)

                self.assertEqual(
                    outcome.outcome,
                    MergeOutcome.REJECTED,
                )
                self.assertEqual(github.disabled_count, 1)
                self.assertEqual(github.configurations, [])

    def test_same_run_earlier_attempt_can_configure(self) -> None:
        """A valid earlier attempt from the same run remains acceptable."""
        current = pull_request_snapshot()
        github = FakeGitHub(
            [current, current],
            attestation=attestation_for(current, run_attempt=1),
            attestation_attempt=1,
        )

        outcome = run_low_risk_merge(
            ci_context(run_attempt=RUN_ATTEMPT),
            github,
        )

        self.assertEqual(outcome.outcome, MergeOutcome.CONFIGURED)
        self.assertEqual(
            github.configurations,
            [(HEAD_SHA, MERGE_TOKEN)],
        )

    def test_manual_high_blocked_and_human_states_are_rejected(self) -> None:
        """Every non-automatic authority state rejects an old request."""
        cases = {
            "manual": (
                "Closes #42\n",
                ("risk:low", "work:review-ready", "manual-merge"),
            ),
            "high": (
                "Closes #42\n",
                ("risk:high", "work:review-ready"),
            ),
            "blocked": (
                "Summary only.\n",
                ("risk:low", "work:blocked"),
            ),
            "human": (
                "Summary only.\n",
                ("human-created",),
            ),
        }

        for name, (body, labels) in cases.items():
            with self.subTest(name=name):
                pending = pull_request_snapshot(
                    body=body,
                    labels=labels,
                    auto_merge_request={"enabledAt": "earlier"},
                )
                cleared = pull_request_snapshot(
                    body=body,
                    labels=labels,
                )
                github = FakeGitHub(
                    [pending, pending, pending, cleared],
                    attestation=attestation_for(pending),
                )

                outcome = run_low_risk_merge(ci_context(), github)

                self.assertEqual(
                    outcome.outcome,
                    MergeOutcome.REJECTED,
                )
                self.assertTrue(outcome.reason)
                self.assertEqual(github.disabled_count, 1)
                self.assertEqual(github.configurations, [])

    def test_existing_request_is_idempotent_only_after_eligibility(self) -> None:
        """An existing request is retained only for a valid current candidate."""
        pending_request = {"enabledAt": "earlier"}
        eligible = pull_request_snapshot(
            auto_merge_request=pending_request
        )
        github = FakeGitHub(
            [eligible, eligible],
            attestation=attestation_for(eligible),
        )

        outcome = run_low_risk_merge(ci_context(), github)

        self.assertEqual(
            outcome.outcome,
            MergeOutcome.ALREADY_CONFIGURED,
        )
        self.assertEqual(github.disabled_count, 0)
        self.assertEqual(github.configurations, [])

        manual = pull_request_snapshot(
            labels=("risk:low", "work:review-ready", "manual-merge"),
            auto_merge_request=pending_request,
        )
        cleared = pull_request_snapshot(
            labels=("risk:low", "work:review-ready", "manual-merge"),
        )
        ineligible = FakeGitHub(
            [manual, manual, manual, cleared],
            attestation=attestation_for(manual),
        )

        rejected = run_low_risk_merge(ci_context(), ineligible)

        self.assertEqual(rejected.outcome, MergeOutcome.REJECTED)
        self.assertEqual(ineligible.disabled_count, 1)
        self.assertEqual(ineligible.configurations, [])

    def test_revocation_closes_a_concurrent_install_window(self) -> None:
        """Revocation verifies absence and handles one racing installation."""
        pending = pull_request_snapshot(
            auto_merge_request={"enabledAt": "earlier"}
        )
        cleared = pull_request_snapshot()
        successful = FakeGitHub(
            [pending, cleared],
            attestation=None,
        )

        self.assertTrue(revoke_pending_auto_merge(successful))
        self.assertEqual(successful.snapshot_calls, 2)
        self.assertEqual(successful.disabled_count, 1)

        unchanged = FakeGitHub(
            [pending, pending],
            attestation=None,
        )

        with self.assertRaises(RuntimeError):
            revoke_pending_auto_merge(unchanged)

        no_request = FakeGitHub(
            [cleared, cleared],
            attestation=None,
        )
        self.assertFalse(revoke_pending_auto_merge(no_request))
        self.assertEqual(no_request.snapshot_calls, 2)
        self.assertEqual(no_request.disabled_count, 0)

        installed_concurrently = FakeGitHub(
            [cleared, pending, cleared],
            attestation=None,
        )

        self.assertTrue(revoke_pending_auto_merge(installed_concurrently))
        self.assertEqual(installed_concurrently.disabled_count, 1)
        self.assertEqual(installed_concurrently.snapshot_calls, 3)

        persistent_race = FakeGitHub(
            [cleared, pending, pending],
            attestation=None,
        )

        with self.assertRaises(RuntimeError):
            revoke_pending_auto_merge(persistent_race)

        self.assertEqual(persistent_race.disabled_count, 1)

    def test_client_reserves_app_token_for_exact_head_final_merge(self) -> None:
        """Reads and revocable mutations use only the built-in token."""
        current = pull_request_snapshot()
        artifact = attestation_for(current, run_attempt=1)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            client = GitHubClient(
                REPOSITORY,
                PR_NUMBER,
                BUILTIN_TOKEN,
                workspace,
            )

            def run_command(
                command: list[str],
                **kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                """Emulate GitHub CLI output and one earlier-attempt artifact."""
                if command[1:3] == ["pr", "view"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        json.dumps(current),
                        "",
                    )

                if command[1] == "api":
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        json.dumps(file_pages()),
                        "",
                    )

                if command[1:3] == ["run", "download"]:
                    artifact_name = command[command.index("--name") + 1]

                    if artifact_name.endswith("-2"):
                        return subprocess.CompletedProcess(
                            command,
                            1,
                            "",
                            "not found",
                        )

                    destination = Path(
                        command[command.index("--dir") + 1]
                    )
                    destination.mkdir(parents=True)
                    (destination / "pr-metadata.json").write_text(
                        json.dumps(artifact),
                        encoding="utf-8",
                    )

                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.dict(
                    os.environ,
                    {"MERGE_TOKEN": "ambient-app-token"},
                ),
                patch(
                    "tools.ci.low_risk_merge.subprocess.run",
                    side_effect=run_command,
                ) as run,
            ):
                self.assertEqual(client.snapshot(), current)
                self.assertEqual(client.changed_files(), file_pages())
                downloaded, attempt = client.download_attestation(
                    RUN_ID,
                    RUN_ATTEMPT,
                )
                client.mark_ready()
                client.disable_auto_merge()
                client.configure_auto_merge(HEAD_SHA, MERGE_TOKEN)

                with self.assertRaises(ValueError):
                    client.configure_auto_merge(HEAD_SHA, "")

        self.assertEqual(downloaded, artifact)
        self.assertEqual(attempt, 1)
        calls = run.call_args_list
        self.assertEqual(len(calls), 7)

        for call in calls[:-1]:
            self.assertEqual(
                call.kwargs["env"]["GH_TOKEN"],
                BUILTIN_TOKEN,
            )

        for call in calls:
            self.assertNotIn("MERGE_TOKEN", call.kwargs["env"])

        self.assertEqual(
            calls[-1].kwargs["env"]["GH_TOKEN"],
            MERGE_TOKEN,
        )
        self.assertEqual(
            calls[-1].args[0],
            [
                "gh",
                "pr",
                "merge",
                str(PR_NUMBER),
                "--repo",
                REPOSITORY,
                "--auto",
                "--squash",
                "--match-head-commit",
                HEAD_SHA,
            ],
        )

    def test_client_rejects_oversized_ci_evidence(self) -> None:
        """Keep PR-head-produced artifacts behind the existing size bound."""
        with tempfile.TemporaryDirectory() as temporary:
            client = GitHubClient(
                REPOSITORY,
                PR_NUMBER,
                BUILTIN_TOKEN,
                Path(temporary),
            )

            def download_oversized(
                command: list[str],
                **kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                """Emulate one successful download with oversized evidence."""
                destination = Path(
                    command[command.index("--dir") + 1]
                )
                destination.mkdir(parents=True)
                (destination / "pr-metadata.json").write_bytes(
                    b" " * (MAX_JSON_BYTES + 1)
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "tools.ci.low_risk_merge.subprocess.run",
                side_effect=download_oversized,
            ):
                with self.assertRaises(MetadataError):
                    client.download_attestation(RUN_ID, RUN_ATTEMPT)


if __name__ == "__main__":
    unittest.main()
