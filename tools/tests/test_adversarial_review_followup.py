import hashlib
import json
import unittest
from unittest.mock import patch

from tools.ci.adversarial_review import (
    ADJUDICATION_RESULT_SCHEMA,
    REVIEW_RESULT_SCHEMA,
    ReviewContractError,
    build_review_packet,
    candidate_identity,
    validate_review_packet,
)
from tools.ci.adversarial_review_session import (
    ReviewSessionError,
    run_review_lifecycle,
)


REVISION = "220cc0114ced1c521c25b5f26d3ec0a597469afb50429b1699615497fce0f372"
DIFF = "diff --git a/tools/ci/adversarial_review.py b/tools/ci/adversarial_review.py\n"
INCLUDED = [
    "tools/ci/adversarial_review.py",
    "tools/ci/adversarial_review_session.py",
    "tools/tests/test_adversarial_review.py",
]
SEMANTIC_SOURCE = """
Synthetic source item for validating evidence transport and diagnostic output.
""".strip()


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


def candidate() -> dict:
    return {
        "base_ref": "origin/dev",
        "head_ref": "work/116-adversarial-review-adjudication",
        "head_sha": "h" * 40,
        "tree_sha": "t" * 40,
        "diff_sha256": hashlib.sha256(DIFF.encode()).hexdigest(),
        "diff": DIFF,
    }


def semantic_packet() -> dict:
    current = candidate()
    return build_review_packet(
        issue_contract(),
        current,
        {
            "sources": [
                {
                    "path": "tools/tests/test_adversarial_review_followup.py",
                    "section": "source-backed semantic evidence fixture",
                    "text": SEMANTIC_SOURCE,
                }
            ],
            "review_doctrine": (
                "Classify from the cited source text; do not infer compatibility "
                "or manual-validation obligations."
            ),
        },
        {
            "issue_contract_revision": REVISION,
            "candidate_identity": candidate_identity(current),
            "checks": [
                {"name": "semantic fixture", "result": "passed", "evidence": ["fixture"]}
            ],
        },
        {"included": INCLUDED, "exclusions": ["readiness", "merge", "release"]},
        risk="high",
    )


def finding(finding_id: str, claim: str, severity: str = "medium") -> dict:
    return {
        "finding_id": finding_id,
        "severity": severity,
        "defect_or_invariant": claim,
        "supporting_evidence": ["governance.0"],
        "contract_or_governance": "accepted contract and source-backed fixture",
        "affected_location": INCLUDED[0],
    }


def semantic_findings() -> list[dict]:
    return [
        finding("F-blocker", "candidate omits a required invariant", "high"),
        finding(
            "F-python313",
            "separately actionable Python 3.13+ concern has no named obligation",
            "low",
        ),
        finding(
            "F-follow-up",
            "separately meaningful concern is outside the accepted outcome",
        ),
        finding(
            "F-doc-example",
            "python3.12 documentation example is already satisfied",
            "high",
        ),
        finding(
            "F-temp-mock",
            "mocked temporary-environment path adds no defect beyond existing evidence",
            "high",
        ),
        finding(
            "F-compat",
            "old representation must remain compatible without an independent consumer",
            "high",
        ),
        finding(
            "F-manual",
            "manual visual observation should be added despite no contract requirement",
            "high",
        ),
        finding(
            "F-unavailable",
            "unavailable environment capability proves candidate failure",
            "high",
        ),
    ]


def review_result(packet: dict, findings: list[dict]) -> dict:
    return {
        "schema": REVIEW_RESULT_SCHEMA,
        "issue_contract_revision": packet["issue_contract"]["revision"],
        "candidate_identity": candidate_identity(packet["candidate"]),
        "findings": findings,
    }


def correction() -> dict:
    return {
        "summary": "Apply the bounded source-backed correction.",
    }


def decision(finding_id: str, disposition: str, value: dict | None = None) -> dict:
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "basis": "source text supports this deterministic fixture disposition",
        "correction": value,
        "correction_accepted": value is not None,
    }


def adjudication_result(packet: dict, decisions: list[dict]) -> dict:
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
        "issue_contract_revision": packet["issue_contract_revision"],
        "candidate_identity": packet["candidate_identity"],
        "dispositions": decisions,
        "human_handoff": {"required": False, "reason": None},
    }


class SourceBackedFixtureTests(unittest.TestCase):
    def test_contract_revision_binds_snapshot_contents(self):
        packet = semantic_packet()
        packet["issue_contract"]["body"] += "changed without re-acceptance\n"
        with self.assertRaisesRegex(ReviewContractError, "accepted snapshot"):
            validate_review_packet(packet)


class SessionFailureTests(unittest.TestCase):
    def test_invalid_session_result_becomes_bounded_handoff(self):
        packet = semantic_packet()

        def invalid_runner(role, payload, output_schema):
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "issue_contract_revision": payload["issue_contract"]["revision"],
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": [
                        {
                            **semantic_findings()[0],
                            "supporting_evidence": ["missing-evidence"],
                        }
                    ],
                }
            raise AssertionError("invalid reviewer output must stop before adjudication")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=invalid_runner
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertEqual(result["candidate_identity"], candidate_identity(packet["candidate"]))
        self.assertNotIn("missing-evidence", json.dumps(result))

    def test_provider_failure_becomes_bounded_handoff_without_raw_text(self):
        packet = semantic_packet()

        def failing_runner(role, payload, output_schema):
            raise ReviewSessionError("raw-provider-instruction")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=failing_runner
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertNotIn("raw-provider-instruction", json.dumps(result))
        self.assertEqual(result["session_failure"]["role"], "reviewer")
        self.assertEqual(
            result["session_failure"]["failure_class"],
            "startup",
        )
        self.assertIsNone(result["session_failure"]["exit_status"])
        self.assertFalse(result["session_failure"]["output_exists"])

    def test_provider_startup_failure_is_classified_without_raw_error_text(self):
        packet = semantic_packet()
        with patch(
            "tools.ci.adversarial_review_session._codex_path",
            side_effect=ReviewSessionError("raw-startup-detail"),
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertEqual(diagnostic["failure_class"], "startup")
        self.assertFalse(diagnostic["output_exists"])
        self.assertNotIn("raw-startup-detail", json.dumps(result))

    def test_adjudicator_failure_identifies_the_adjudicator_role(self):
        packet = semantic_packet()

        def failing_runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [semantic_findings()[0]])
            raise ReviewSessionError("raw-adjudicator-detail")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=failing_runner
        )
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["role"], "adjudicator")
        self.assertEqual(diagnostic["failure_class"], "startup")
        self.assertNotIn("raw-adjudicator-detail", json.dumps(result))
