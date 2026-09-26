import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.adversarial_review import (
    ADJUDICATION_RESULT_SCHEMA,
    REVIEW_RESULT_SCHEMA,
    ReviewContractError,
    build_adjudication_packet,
    build_review_packet,
    candidate_identity,
)
from tools.ci.adversarial_review_session import main, run_review_lifecycle
from tools.ci.adversarial_review_state import (
    LIFECYCLE_ARTIFACT_SCHEMA,
    lifecycle_artifact,
    load_lifecycle_artifact,
)


REVISION = "220cc0114ced1c521c25b5f26d3ec0a597469afb50429b1699615497fce0f372"
DIFF = "diff --git a/tools/ci/adversarial_review.py b/tools/ci/adversarial_review.py\n"
INCLUDED = [
    "tools/ci/adversarial_review.py",
    "tools/ci/adversarial_review_state.py",
    "tools/ci/adversarial_review_session.py",
]


def issue_contract() -> dict:
    return {
        "repository": "owner/game",
        "id": "I_116",
        "number": 116,
        "title": "Add adversarial review and adjudication",
        "body": "Acceptance criteria\nEngineering constraints\nValidation\n",
        "state": "OPEN",
        "work_blocked": False,
        "open_blocker_ids": [],
        "revision": REVISION,
    }


def candidate(
    head_sha: str = "h" * 40,
    diff: str = DIFF,
    tree_sha: str = "t" * 40,
) -> dict:
    return {
        "base_ref": "origin/dev",
        "head_ref": "work/116-adversarial-review-adjudication",
        "head_sha": head_sha,
        "tree_sha": tree_sha,
        "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "diff": diff,
    }


def make_packet(value: dict | None = None, *, risk: str = "high") -> dict:
    current = candidate() if value is None else value
    return build_review_packet(
        issue_contract(),
        current,
        {
            "sources": [
                {
                    "path": "GOVERNANCE.md",
                    "section": "Adversarial review and adjudication",
                    "text": "Review is read-only and bounded by the accepted contract.",
                }
            ],
            "review_doctrine": "Use independent evidence; do not invent obligations.",
        },
        {
            "issue_contract_revision": REVISION,
            "candidate_identity": candidate_identity(current),
            "checks": [
                {
                    "name": "fresh",
                    "result": "passed",
                    "evidence": ["tests"],
                    "establishes": ["the accepted issue behavior"],
                }
            ],
        },
        {"included": INCLUDED, "exclusions": ["readiness", "merge", "release"]},
        risk=risk,
    )


def finding(
    finding_id: str = "F-correction",
    description: str = "supported current-pass invariant",
) -> dict:
    return {
        "finding_id": finding_id,
        "severity": "medium",
        "defect_or_invariant": description,
        "supporting_evidence": ["issue_contract"],
        "contract_or_governance": "accepted contract",
        "affected_location": INCLUDED[0],
    }


def decision(finding_id: str, disposition: str) -> dict:
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "basis": "independent source evidence supports the bounded decision",
    }


def adjudication_result(packet: dict, decisions: list[dict]) -> dict:
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
        "issue_contract_revision": packet["issue_contract_revision"],
        "candidate_identity": packet["candidate_identity"],
        "dispositions": decisions,
        "human_handoff": {"required": False, "reason": None},
    }


class LifecycleArtifactTests(unittest.TestCase):
    def runner(self, findings=None, decisions=None, calls=None):
        findings = [] if findings is None else findings
        decisions = [] if decisions is None else decisions

        def run(role, payload, output_schema):
            if calls is not None:
                calls.append(role)
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "issue_contract_revision": payload["issue_contract"]["revision"],
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": findings,
                }
            return adjudication_result(payload, decisions)

        return run

    def accepted_first_pass(self):
        return run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [finding("F-actionable")], [decision("F-actionable", "patch-now")]
            ),
        )

    def test_result_is_the_only_continuation_artifact(self):
        result = self.accepted_first_pass()
        self.assertEqual(result["schema"], LIFECYCLE_ARTIFACT_SCHEMA)
        self.assertEqual(result["status"], "revalidate-and-rereview")
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(
            set(result),
            {
                "schema",
                "status",
                "risk",
                "issue_contract_revision",
                "cycle",
                "candidate_identity",
                "prior_candidate_identities",
                "review_cycles",
                "reason",
                "session_failure",
            },
        )
        self.assertEqual(result["review_cycles"][0]["cycle"], 0)
        self.assertEqual(
            result["review_cycles"][0]["findings"][0]["finding_id"],
            "F-actionable",
        )
        self.assertEqual(
            result["review_cycles"][0]["findings"][0]["disposition"],
            "patch-now",
        )
        self.assertNotIn("correction", json.dumps(result))
        for obsolete in (
            "state_digest",
            "transition",
            "continuation_state",
            "implementation_payload",
            "adjudication_history",
            "adjudication",
            "human_handoff",
        ):
            self.assertNotIn(obsolete, result)
        self.assertNotIn("defect_or_invariant", json.dumps(result))
        self.assertEqual(load_lifecycle_artifact(json.loads(json.dumps(result))), result)

    def test_saved_result_is_consumed_directly_by_the_next_cli_run(self):
        first_packet = make_packet()
        first_adjudication_packet = build_adjudication_packet(
            first_packet, [finding("F-persisted")]
        )
        first_adjudication = adjudication_result(
            first_adjudication_packet,
            [decision("F-persisted", "patch-now")],
        )
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "corrected\n",
        )
        corrected_packet = make_packet(corrected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "packet.json"
            output_path = root / "lifecycle.json"
            packet_path.write_text(json.dumps(first_packet), encoding="utf-8")
            with patch(
                "tools.ci.adversarial_review_session._run_adversarial_review_sessions",
                return_value=(first_adjudication, first_adjudication_packet),
            ):
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--packet",
                            str(packet_path),
                            "--output",
                            str(output_path),
                            "--initial",
                        ]
                    ),
                    3,
                )
            first = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(first["status"], "revalidate-and-rereview")

            packet_path.write_text(json.dumps(corrected_packet), encoding="utf-8")
            with patch(
                "tools.ci.adversarial_review_session._run_adversarial_review_sessions",
                return_value=(None, None),
            ):
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--packet",
                            str(packet_path),
                            "--state",
                            str(output_path),
                            "--output",
                            str(output_path),
                        ]
                    ),
                    0,
                )
            final = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["cycle"], 1)
        self.assertEqual(final["prior_candidate_identities"][0], first["candidate_identity"])
        self.assertEqual(len(final["review_cycles"]), 2)
        self.assertEqual(final["review_cycles"][0]["findings"][0]["disposition"], "patch-now")
        self.assertEqual(final["review_cycles"][1]["adjudication_status"], "not-needed")

    def test_zero_findings_are_explicitly_persisted(self):
        result = run_review_lifecycle(
            make_packet(), initial=True, session_runner=self.runner()
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            result["review_cycles"],
            [
                {
                    "cycle": 0,
                    "candidate_identity": candidate_identity(candidate()),
                    "adjudication_status": "not-needed",
                    "findings": [],
                }
            ],
        )

    def test_all_dispositions_persist_and_only_actionable_ones_rereview(self):
        for disposition, expected_status in (
            ("blocker", "revalidate-and-rereview"),
            ("patch-now", "revalidate-and-rereview"),
            ("follow-up", "complete"),
            ("reject", "complete"),
        ):
            with self.subTest(disposition=disposition):
                result = run_review_lifecycle(
                    make_packet(),
                    initial=True,
                    session_runner=self.runner(
                        [finding("F-outcome")],
                        [decision("F-outcome", disposition)],
                    ),
                )
                outcome = result["review_cycles"][0]["findings"][0]
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(outcome["disposition"], disposition)
                self.assertEqual(
                    outcome["basis"],
                    "independent source evidence supports the bounded decision",
                )
                self.assertNotIn("correction", json.dumps(result))

    def test_follow_up_survives_fixed_actionable_finding_in_later_cycle(self):
        original = candidate()
        first = run_review_lifecycle(
            make_packet(original),
            initial=True,
            session_runner=self.runner(
                [
                    finding("F-blocker", "accepted invariant is missing"),
                    finding("F-follow-up", "separate concern for human awareness"),
                ],
                [
                    decision("F-blocker", "blocker"),
                    decision("F-follow-up", "follow-up"),
                ],
            ),
        )
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "corrected\n",
        )
        complete = run_review_lifecycle(
            make_packet(corrected),
            state=first,
            session_runner=self.runner(),
        )
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(len(complete["review_cycles"]), 2)
        self.assertEqual(
            complete["review_cycles"][0]["findings"][1]["disposition"],
            "follow-up",
        )
        self.assertEqual(complete["review_cycles"][1]["findings"], [])
        self.assertEqual(complete["prior_candidate_identities"][0], first["candidate_identity"])

    def test_adjudicator_failure_preserves_validated_findings_without_disposition(self):
        finding_value = finding("F-unadjudicated", "validated concern stays reportable")

        def invalid_adjudicator(role, payload, output_schema):
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "issue_contract_revision": payload["issue_contract"]["revision"],
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": [finding_value],
                }
            return {
                **adjudication_result(payload, [decision("F-unadjudicated", "reject")]),
                "schema": "adversarial-adjudication-result:v4",
            }

        result = run_review_lifecycle(
            make_packet(), initial=True, session_runner=invalid_adjudicator
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertEqual(result["session_failure"]["role"], "adjudicator")
        cycle = result["review_cycles"][0]
        self.assertEqual(cycle["adjudication_status"], "unavailable")
        self.assertEqual(
            cycle["findings"],
            [
                {
                    "finding_id": "F-unadjudicated",
                    "summary": "validated concern stays reportable",
                    "disposition": None,
                    "basis": None,
                }
            ],
        )
        encoded = json.dumps(result)
        self.assertNotIn("supporting_evidence", encoded)
        self.assertNotIn("contract_or_governance", encoded)

    def test_prechange_lifecycle_artifact_schema_is_rejected(self):
        current = run_review_lifecycle(
            make_packet(), initial=True, session_runner=self.runner()
        )
        legacy = {**current, "schema": "adversarial-review-lifecycle:v2"}
        with self.assertRaises(ReviewContractError):
            load_lifecycle_artifact(legacy)

    def test_invalid_revision_and_repeated_candidates_stop_before_sessions(self):
        first = self.accepted_first_pass()
        wrong_revision = {**first, "issue_contract_revision": "f" * 64}
        calls = []
        stale = run_review_lifecycle(
            make_packet(
                candidate(
                    head_sha="g" * 40,
                    tree_sha="u" * 40,
                    diff=DIFF + "corrected\n",
                )
            ),
            state=wrong_revision,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(stale["status"], "human-handoff")
        self.assertIn("issue contract revision", stale["reason"])
        self.assertEqual(calls, [])

        unchanged = run_review_lifecycle(
            make_packet(), state=first, session_runner=self.runner(calls=calls)
        )
        self.assertEqual(unchanged["status"], "human-handoff")
        self.assertIn("did not change", unchanged["reason"])
        self.assertEqual(calls, [])

    def test_accepted_issue_revision_cannot_be_replaced_by_state_edit(self):
        first = self.accepted_first_pass()
        mutated = {**first, "issue_contract_revision": "e" * 64}
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "corrected\n",
        )
        calls = []
        result = run_review_lifecycle(
            make_packet(corrected),
            state=mutated,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertEqual(calls, [])
        with self.assertRaises(ReviewContractError):
            load_lifecycle_artifact({**first, "untrusted": "field"})

    def test_handoff_reason_is_sanitized_and_bounded(self):
        result = lifecycle_artifact(
            status="human-handoff",
            risk="high",
            issue_contract_revision=REVISION,
            cycle=0,
            candidate_identity=candidate_identity(candidate()),
            reason="failure\n" + "x" * 500,
        )
        self.assertLessEqual(len(result["reason"]), 320)
        self.assertNotIn("\n", result["reason"])
        self.assertTrue(result["reason"].startswith("failure"))


if __name__ == "__main__":
    unittest.main()
