import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

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
            "body": body,
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
        "body": body,
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
        attestation = self.attestation(
            body="Closes #15\n",
        )
        current = current_pull_request(
            body="Closes #15",
        )

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
                attestation = self.attestation(
                    labels=validated,
                )
                current = current_pull_request(
                    labels=current_labels,
                )

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

    def test_malformed_attestations_are_invalid(self):
        valid = self.attestation()
        cases = []

        missing_digest = deepcopy(valid)
        del missing_digest["metadata_sha256"]
        cases.append(missing_digest)

        wrong_schema = deepcopy(valid)
        wrong_schema["schema_version"] = 2
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

    def test_cli_capture_and_compare_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_path = root / "event.json"
            attestation_path = root / "attestation.json"
            current_path = root / "current.json"
            event_path.write_text(
                json.dumps(event_payload()),
                encoding="utf-8",
            )
            current_path.write_text(
                json.dumps(current_pull_request()),
                encoding="utf-8",
            )

            capture_result = main(
                [
                    "capture",
                    "--event-path",
                    str(event_path),
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


if __name__ == "__main__":
    unittest.main()
