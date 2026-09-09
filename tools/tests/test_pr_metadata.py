import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.ci.issue_contract import (
    acceptance_marker,
    canonical_contract,
    contract_digest,
)
from tools.ci.pr_metadata import (
    INVALID,
    MATCH,
    STALE,
    build_attestation,
    compare_attestation,
    main,
)

REPOSITORY = "owner/game"
PR_NUMBER = 15
HEAD_SHA = "a" * 40
RUN_ID = 123456
RUN_ATTEMPT = 1
ROOT = Path(__file__).resolve().parents[2]


def issue_payload(number: int = PR_NUMBER) -> dict:
    """Build the issue fields available from a complete native GraphQL read."""
    return {
        "id": f"I_{number}",
        "number": number,
        "repository": {"nameWithOwner": REPOSITORY},
        "title": "Bind evidence to the accepted contract",
        "body": "## Acceptance criteria\n\n- Complete the requested scope.\n",
        "state": "OPEN",
        "labels": {"nodes": [], "pageInfo": {"hasNextPage": False}},
        "blockedBy": {"nodes": [], "pageInfo": {"hasNextPage": False}},
    }


def completion_body(body: str | None, issue: dict) -> str:
    """Attach the revision accepted by local evidence to a completion body."""
    number = issue["number"]
    digest = contract_digest(canonical_contract(issue, REPOSITORY, number))
    return f"{body or ''}\n{acceptance_marker(number, digest)}\n"


def metadata_body(body: str | None, labels: list[str] | None) -> str | None:
    """Keep metadata fixtures valid while their tests vary PR-only fields."""
    completion = {"work:complete", "work:review-ready"}.intersection(labels or [])
    if "human-created" not in (labels or []) and (
        completion or "Closes #" in (body or "")
    ):
        return completion_body(body, issue_payload())
    return body


def event_payload(
    *,
    body: str | None = "Summary\n",
    labels: list[str] | None = None,
) -> dict:
    return {
        "repository": {
            "full_name": REPOSITORY,
        },
        "pull_request": {
            "number": PR_NUMBER,
            "base": {
                "ref": "dev",
            },
            "head": {
                "ref": "work/15-bind-auto-merge-metadata",
                "sha": HEAD_SHA,
                "repo": {
                    "full_name": REPOSITORY,
                },
            },
            "body": metadata_body(body, labels),
            "labels": [
                {"name": name}
                for name in (
                    labels
                    if labels is not None
                    else ["risk:low"]
                )
            ],
        },
    }


def current_pull_request(
    *,
    body: str | None = "Summary\n",
    labels: list[str] | None = None,
) -> dict:
    return {
        "number": PR_NUMBER,
        "baseRefName": "dev",
        "headRefName": "work/15-bind-auto-merge-metadata",
        "headRefOid": HEAD_SHA,
        "headRepository": {
            "nameWithOwner": REPOSITORY,
        },
        "body": metadata_body(body, labels),
        "labels": [
            {"name": name}
            for name in (
                labels
                if labels is not None
                else ["risk:low"]
            )
        ],
    }


def compare(
    attestation: object,
    current: object,
    **overrides,
) -> tuple[int, str]:
    arguments = {
        "repository": REPOSITORY,
        "pull_request_number": PR_NUMBER,
        "head_sha": HEAD_SHA,
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "current_issue": issue_payload(),
    }
    arguments.update(overrides)

    return compare_attestation(
        attestation,
        current,
        **arguments,
    )


class PrMetadataTests(unittest.TestCase):
    def attestation(
        self,
        *,
        body: str | None = "Summary\n",
        labels: list[str] | None = None,
    ) -> dict:
        return build_attestation(
            event_payload(
                body=body,
                labels=labels,
            ),
            REPOSITORY,
            RUN_ID,
            RUN_ATTEMPT,
            issue=issue_payload(),
        )

    def test_exact_metadata_matches_with_canonical_label_order(self):
        attestation = self.attestation(
            body="Closes #15\n\n魔法 ◇\n",
            labels=[
                "triage,blue",
                "work:complete",
                "risk:low",
            ],
        )
        current = current_pull_request(
            body="Closes #15\n\n魔法 ◇\n",
            labels=[
                "risk:low",
                "triage,blue",
                "work:complete",
            ],
        )

        status, _ = compare(attestation, current)

        self.assertEqual(status, MATCH)

    def test_body_bytes_are_preserved(self):
        attestation = self.attestation(body="Summary\n")
        current = current_pull_request(body="Summary")

        status, _ = compare(attestation, current)

        self.assertEqual(status, STALE)

    def test_null_body_is_canonical_empty_body(self):
        attestation = self.attestation(body=None)
        current = current_pull_request(body="")

        status, _ = compare(attestation, current)

        self.assertEqual(status, MATCH)

    def test_completion_metadata_requires_its_own_ci_attestation(self):
        old = self.attestation(
            body="Summary\n",
            labels=["risk:low"],
        )
        completed = current_pull_request(
            body="Closes #15\n\nSummary\n",
            labels=["risk:low", "work:complete"],
        )

        stale_status, _ = compare(old, completed)
        current = self.attestation(
            body="Closes #15\n\nSummary\n",
            labels=["work:complete", "risk:low"],
        )
        current_status, _ = compare(current, completed)

        self.assertEqual(stale_status, STALE)
        self.assertEqual(current_status, MATCH)

    def test_same_head_policy_label_changes_are_stale(self):
        cases = (
            (
                ["risk:high", "work:review-ready"],
                ["risk:low", "work:complete"],
            ),
            (
                ["risk:low"],
                ["risk:low", "work:complete"],
            ),
            (
                ["risk:low", "work:complete"],
                ["risk:low"],
            ),
            (
                ["risk:low", "manual-merge"],
                ["risk:low", "work:complete"],
            ),
            (
                ["risk:low", "human-created"],
                ["risk:low", "work:complete"],
            ),
            (
                ["risk:low", "work:blocked"],
                ["risk:low", "work:complete"],
            ),
        )

        for validated, current_labels in cases:
            with self.subTest(
                validated=validated,
                current=current_labels,
            ):
                body = (
                    "Closes #15\n"
                    if {"work:complete", "work:review-ready"}.intersection(validated)
                    else "Summary\n"
                )
                attestation = self.attestation(body=body, labels=validated)
                current = current_pull_request(body=body, labels=current_labels)

                status, _ = compare(attestation, current)

                self.assertEqual(status, STALE)

    def test_current_identity_changes_are_stale(self):
        attestation = self.attestation()
        cases = {
            "number": PR_NUMBER + 1,
            "baseRefName": "main",
            "headRefName": "work/16-other",
            "headRefOid": "b" * 40,
        }

        for field, value in cases.items():
            with self.subTest(field=field):
                current = current_pull_request()
                current[field] = value

                status, _ = compare(attestation, current)

                self.assertEqual(status, STALE)

    def test_wrong_attestation_envelope_is_invalid(self):
        attestation = self.attestation()
        cases = (
            {"repository": "other/game"},
            {"pull_request_number": PR_NUMBER + 1},
            {"head_sha": "b" * 40},
            {"run_id": RUN_ID + 1},
            {"run_attempt": RUN_ATTEMPT + 1},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                status, _ = compare(
                    attestation,
                    current_pull_request(),
                    **overrides,
                )

                self.assertEqual(status, INVALID)

    def test_partial_rerun_accepts_same_run_earlier_attestation(self):
        attestation = self.attestation()

        status, _ = compare(
            attestation,
            current_pull_request(),
            run_attempt=2,
            attestation_run_attempt=1,
        )

        self.assertEqual(status, MATCH)

    def test_attestation_attempt_is_cross_bound_and_not_future(self):
        attestation = self.attestation()
        cases = (
            {
                "run_attempt": 2,
                "attestation_run_attempt": 2,
            },
            {
                "run_attempt": 1,
                "attestation_run_attempt": 2,
            },
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                status, _ = compare(
                    attestation,
                    current_pull_request(),
                    **overrides,
                )

                self.assertEqual(status, INVALID)

    def test_malformed_attestations_are_invalid(self):
        valid = self.attestation()
        cases = []

        missing_digest = deepcopy(valid)
        del missing_digest["metadata_sha256"]
        cases.append(missing_digest)

        wrong_schema = deepcopy(valid)
        wrong_schema["schema_version"] = 1
        cases.append(wrong_schema)

        malformed_digest = deepcopy(valid)
        malformed_digest["metadata_sha256"] = "not-a-digest"
        cases.append(malformed_digest)

        extra_field = deepcopy(valid)
        extra_field["unexpected"] = True
        cases.append(extra_field)

        for attestation in cases:
            with self.subTest(attestation=attestation):
                status, _ = compare(
                    attestation,
                    current_pull_request(),
                )

                self.assertEqual(status, INVALID)

    def test_malformed_current_metadata_is_invalid(self):
        attestation = self.attestation()
        current = current_pull_request()
        current["labels"] = [
            {"name": "risk:low"},
            {"name": "risk:low"},
        ]

        status, _ = compare(attestation, current)

        self.assertEqual(status, INVALID)

    def completion_evidence(self, issue: dict) -> tuple[dict, dict]:
        """Bind a current completion PR and its hosted evidence to one issue."""
        event = event_payload()
        current = current_pull_request()
        body = completion_body("Closes #15\n", issue)
        labels = [{"name": "risk:low"}, {"name": "work:complete"}]
        event["pull_request"].update(body=body, labels=labels)
        current.update(body=body, labels=labels)
        return build_attestation(
            event, REPOSITORY, RUN_ID, RUN_ATTEMPT, issue=issue
        ), current

    def test_completion_binds_the_accepted_contract_revision(self):
        """Scope edits stale evidence even when every PR field is unchanged."""
        accepted = issue_payload()
        evidence, current = self.completion_evidence(accepted)
        self.assertEqual(compare(evidence, current)[0], MATCH)
        self.assertIsInstance(evidence["issue_contract"], dict)
        for field, replacement in (
            ("title", "Revised issue scope"),
            ("body", accepted["body"] + "- Complete another outcome.\n"),
            ("body", accepted["body"] + "\n"),
            ("state", "CLOSED"),
        ):
            with self.subTest(field=field, replacement=replacement):
                revised = deepcopy(accepted)
                revised[field] = replacement
                self.assertEqual(
                    compare(evidence, current, current_issue=revised)[0], STALE
                )

    def test_issue_conversation_activity_keeps_completion_evidence_current(self):
        """Conversation changes are outside the accepted issue contract."""
        evidence, current = self.completion_evidence(issue_payload())
        conversation = issue_payload()
        conversation.update(
            comments={"nodes": [{"body": "Discussion after validation."}]},
            reactions={"totalCount": 8},
            updatedAt="2026-09-08T01:02:03Z",
        )
        conversation["labels"]["nodes"] = [{"name": "discussion"}]
        self.assertEqual(
            compare(evidence, current, current_issue=conversation)[0], MATCH
        )

    def test_new_native_blocker_invalidates_existing_completion(self):
        """Native unresolved dependencies cannot reuse otherwise matching CI."""
        evidence, current = self.completion_evidence(issue_payload())
        for blocked in ("native", "label"):
            with self.subTest(blocked=blocked):
                revised = issue_payload()
                if blocked == "native":
                    revised["blockedBy"]["nodes"] = [
                        {"id": "I_29", "state": "OPEN"}
                    ]
                else:
                    revised["labels"]["nodes"] = [{"name": "work:blocked"}]
                self.assertEqual(
                    compare(evidence, current, current_issue=revised)[0], STALE
                )

    def test_changed_contract_can_pass_after_accepted_evidence_refresh(self):
        """An authorized edit needs a new accepted marker and new hosted CI."""
        accepted = issue_payload()
        old_evidence, old_pr = self.completion_evidence(accepted)
        revised = deepcopy(accepted)
        revised["body"] += "- Deliver the newly authorized scope.\n"
        unchanged_event = event_payload()
        unchanged_event["pull_request"]["body"] = old_pr["body"]
        unchanged_event["pull_request"]["labels"] = old_pr["labels"]
        with self.assertRaises(ValueError):
            build_attestation(
                unchanged_event, REPOSITORY, RUN_ID, RUN_ATTEMPT, issue=revised
            )
        fresh_evidence, refreshed_pr = self.completion_evidence(revised)
        self.assertEqual(compare(old_evidence, refreshed_pr)[0], STALE)
        self.assertEqual(
            compare(fresh_evidence, refreshed_pr, current_issue=revised)[0], MATCH
        )

    def test_completion_rejects_missing_incomplete_or_wrong_issue_evidence(self):
        """Missing data must not silently become an empty blocker contract."""
        evidence, current = self.completion_evidence(issue_payload())
        incomplete = issue_payload()
        incomplete["blockedBy"]["pageInfo"]["hasNextPage"] = True
        wrong_issue = issue_payload(PR_NUMBER + 1)
        wrong_repository = issue_payload()
        wrong_repository["repository"]["nameWithOwner"] = "other/game"
        for issue in (None, {}, incomplete, wrong_issue, wrong_repository):
            with self.subTest(issue=issue):
                self.assertEqual(
                    compare(evidence, current, current_issue=issue)[0], INVALID
                )

    def test_completion_cannot_capture_without_an_accepted_marker(self):
        """Capturing live scope alone cannot silently approve a revision."""
        event = event_payload()
        event["pull_request"]["body"] = "Closes #15\n"
        event["pull_request"]["labels"].append({"name": "work:complete"})
        with self.assertRaises(ValueError):
            build_attestation(
                event, REPOSITORY, RUN_ID, RUN_ATTEMPT, issue=issue_payload()
            )

    def test_milestones_and_human_prs_have_no_contract_requirement(self):
        """The binding applies to agent completion, preserving human authority."""
        for labels in (["risk:low"], ["human-created", "work:complete"]):
            with self.subTest(labels=labels):
                event = event_payload(labels=labels)
                evidence = build_attestation(
                    event, REPOSITORY, RUN_ID, RUN_ATTEMPT
                )
                self.assertIsNone(evidence["issue_contract"])
                self.assertEqual(
                    compare(
                        evidence, current_pull_request(labels=labels),
                        current_issue=None,
                    )[0], MATCH,
                )

    def test_cli_capture_and_compare_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_path = root / "event.json"
            attestation_path = root / "attestation.json"
            current_path = root / "current.json"
            issue_path = root / "issue.json"
            issue_path.write_text(json.dumps(issue_payload()), encoding="utf-8")
            event_path.write_text(
                json.dumps(event_payload(
                    body="Closes #15\n", labels=["risk:low", "work:complete"]
                )),
                encoding="utf-8",
            )
            current_path.write_text(
                json.dumps(current_pull_request(
                    body="Closes #15\n", labels=["risk:low", "work:complete"]
                )),
                encoding="utf-8",
            )

            capture_result = main(
                [
                    "capture",
                    "--event-path",
                    str(event_path),
                    "--issue-path",
                    str(issue_path),
                    "--output",
                    str(attestation_path),
                    "--repository",
                    REPOSITORY,
                    "--run-id",
                    str(RUN_ID),
                    "--run-attempt",
                    str(RUN_ATTEMPT),
                ]
            )
            compare_result = main(
                [
                    "compare",
                    "--attestation-path",
                    str(attestation_path),
                    "--current-pr-path",
                    str(current_path),
                    "--current-issue-path",
                    str(issue_path),
                    "--repository",
                    REPOSITORY,
                    "--pull-request-number",
                    str(PR_NUMBER),
                    "--head-sha",
                    HEAD_SHA,
                    "--run-id",
                    str(RUN_ID),
                    "--run-attempt",
                    str(RUN_ATTEMPT),
                ]
            )

        self.assertEqual(capture_result, MATCH)
        self.assertEqual(compare_result, MATCH)

    def test_cli_missing_attestation_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_path = root / "current.json"
            current_path.write_text(
                json.dumps(current_pull_request()),
                encoding="utf-8",
            )

            result = main(
                [
                    "compare",
                    "--attestation-path",
                    str(root / "missing.json"),
                    "--current-pr-path",
                    str(current_path),
                    "--repository",
                    REPOSITORY,
                    "--pull-request-number",
                    str(PR_NUMBER),
                    "--head-sha",
                    HEAD_SHA,
                    "--run-id",
                    str(RUN_ID),
                    "--run-attempt",
                    str(RUN_ATTEMPT),
                ]
            )

        self.assertEqual(result, INVALID)

    def test_cli_parser_error_is_not_stale_evidence(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/ci/pr_metadata.py"),
                "compare",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertNotEqual(result.returncode, STALE)


if __name__ == "__main__":
    unittest.main()
