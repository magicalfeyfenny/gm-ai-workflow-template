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
    validate_review_result,
)
from tools.ci.adversarial_review_session import main, run_review_lifecycle


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


def make_packet(value: dict | None = None) -> dict:
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
            "checks": [{"name": "fresh", "result": "passed", "evidence": ["tests"]}],
        },
        {"included": INCLUDED, "exclusions": ["readiness", "merge", "release"]},
    )


def finding(finding_id: str = "F-correction") -> dict:
    return {
        "finding_id": finding_id,
        "severity": "medium",
        "defect_or_invariant": "supported current-pass correction",
        "supporting_evidence": ["issue_contract.body"],
        "contract_or_governance": "accepted contract",
        "affected_location": INCLUDED[0],
    }


def correction() -> dict:
    return {
        "summary": "Apply the supported correction.",
        "locations": [INCLUDED[0]],
        "validation": ["rerun focused tests"],
    }


def adjudication_result(packet: dict, decisions: list[dict]) -> dict:
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
        "candidate_identity": packet["candidate_identity"],
        "dispositions": decisions,
        "human_handoff": {"required": False, "reason": None},
    }


def decision(finding_id: str, disposition: str, value: dict | None = None) -> dict:
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "basis": "independent source evidence supports the bounded decision",
        "correction": value,
        "correction_accepted": value is not None,
    }


class LifecycleOrchestrationTests(unittest.TestCase):
    def runner(self, findings=None, decisions=None):
        findings = [] if findings is None else findings
        decisions = [] if decisions is None else decisions

        def run(role, payload, output_schema):
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": findings,
                }
            return adjudication_result(payload, decisions)

        return run

    def test_production_orchestration_routes_correction_and_fresh_rereview(self):
        original = make_packet()
        stable = run_review_lifecycle(
            original, initial=True, session_runner=self.runner()
        )
        self.assertEqual(stable["transition"]["status"], "complete")

        correction_finding = finding()
        first = run_review_lifecycle(
            original,
            initial=True,
            session_runner=self.runner(
                [correction_finding], [decision("F-correction", "patch-now", correction())]
            ),
        )
        self.assertEqual(first["transition"]["status"], "revalidate-and-rereview")
        self.assertEqual(first["transition"]["next_cycle"], 1)

        corrected = candidate(
            head_sha="g" * 40, tree_sha="u" * 40, diff=DIFF + "corrected\n"
        )
        corrected_packet = make_packet(corrected)
        final = run_review_lifecycle(
            corrected_packet,
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(final["transition"]["status"], "complete")

    def test_cli_writes_deterministic_transition_and_stops_before_stale_sessions(self):
        packet = make_packet()
        adjudication_packet = build_adjudication_packet(packet, [])
        result = adjudication_result(adjudication_packet, [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "packet.json"
            state_path = root / "state.json"
            output_path = root / "result.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            state_path.write_text(
                json.dumps({"issue_contract_revision": "b" * 64}), encoding="utf-8"
            )
            with patch(
                "tools.ci.adversarial_review_session._run_adversarial_review_sessions"
            ) as run_sessions:
                run_sessions.return_value = (result, adjudication_packet)
                exit_code = main(
                    [
                        "run",
                        "--packet",
                        str(packet_path),
                        "--state",
                        str(state_path),
                        "--output",
                        str(output_path),
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertFalse(output_path.exists())
        run_sessions.assert_not_called()

    def test_reviewer_paraphrase_cannot_become_adjudicator_evidence(self):
        packet = make_packet()
        unsupported = {
            "schema": REVIEW_RESULT_SCHEMA,
            "candidate_identity": candidate_identity(packet["candidate"]),
            "findings": [
                {
                    **finding("F-unsupported"),
                    "supporting_evidence": ["reviewer.paraphrase"],
                }
            ],
        }
        with self.assertRaisesRegex(ReviewContractError, "unsupported evidence IDs"):
            validate_review_result(unsupported, packet)


if __name__ == "__main__":
    unittest.main()
