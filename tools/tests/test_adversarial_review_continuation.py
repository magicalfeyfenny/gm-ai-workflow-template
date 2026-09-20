import copy
import unittest

from tools.ci.adversarial_review import REVIEW_RESULT_SCHEMA, candidate_identity
from tools.ci.adversarial_review_session import run_review_lifecycle
from tools.tests.test_adversarial_review_lifecycle import (
    INCLUDED,
    adjudication_result,
    candidate,
    correction,
    decision,
    finding,
    make_packet,
)


class ContinuationStateTests(unittest.TestCase):
    def runner(self, findings=None, decisions=None, calls=None):
        findings = [] if findings is None else findings
        decisions = [] if decisions is None else decisions

        def run(role, payload, output_schema):
            if calls is not None:
                calls.append(role)
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": findings,
                }
            return adjudication_result(payload, decisions)

        return run

    def accepted_first_pass(self, *, locations=None):
        current_correction = correction()
        if locations is not None:
            current_correction["locations"] = locations
        return run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [finding()], [decision("F-correction", "patch-now", current_correction)]
            ),
        )

    def test_emitted_state_is_the_only_continuation_authority(self):
        first = self.accepted_first_pass()
        state = first["continuation_state"]
        self.assertEqual(state["schema"], "adversarial-review-continuation:v1")
        self.assertTrue(state["accepted_correction"])
        self.assertEqual(state["cycle"], 1)
        self.assertIn(INCLUDED[0], state["authorized_locations"])
        self.assertNotIn("candidate_changed", state)
        self.assertNotIn("expected_candidate", state)
        self.assertNotIn("previous_candidates", state)

        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncorrected\n"
            ),
        )
        result = run_review_lifecycle(
            make_packet(corrected),
            state=state,
            session_runner=self.runner(),
        )
        self.assertEqual(result["transition"]["status"], "complete")
        self.assertEqual(result["transition"]["cycle"], 1)

    def test_omitted_legacy_or_tampered_state_fails_closed(self):
        first = self.accepted_first_pass()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncorrected\n"
            ),
        )
        for state in (
            None,
            {
                "cycle": 1,
                "candidate_changed": True,
                "accepted_correction": True,
                "expected_candidate": candidate_identity(corrected),
                "previous_candidates": [],
                "issue_contract_revision": "2" * 64,
            },
            {**copy.deepcopy(first["continuation_state"]), "cycle": 2},
        ):
            with self.subTest(state=state):
                calls = []
                result = run_review_lifecycle(
                    make_packet(corrected),
                    state=state,
                    session_runner=self.runner(calls=calls),
                )
                self.assertEqual(result["transition"]["status"], "human-handoff")
                self.assertEqual(calls, [])
                self.assertIn("state", result["transition"]["reason"])

    def test_unauthorized_delta_hands_off_before_sessions(self):
        first = self.accepted_first_pass()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\n"
                "diff --git a/GOVERNANCE.md b/GOVERNANCE.md\nunauthorized\n"
            ),
        )
        calls = []
        result = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertIn("GOVERNANCE.md", result["transition"]["reason"])
        self.assertEqual(calls, [])

    def test_accepted_location_union_allows_multiple_corrections(self):
        second_finding = finding("F-second")
        second_correction = correction()
        second_correction["locations"] = [INCLUDED[1]]
        first = run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [finding(), second_finding],
                [
                    decision("F-correction", "patch-now", correction()),
                    decision("F-second", "patch-now", second_correction),
                ],
            ),
        )
        self.assertEqual(
            first["continuation_state"]["authorized_locations"],
            sorted([INCLUDED[0], INCLUDED[1]]),
        )
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\nfirst\n"
                "diff --git a/tools/ci/adversarial_review_state.py "
                "b/tools/ci/adversarial_review_state.py\nsecond\n"
            ),
        )
        result = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(result["transition"]["status"], "complete")

    def test_oscillation_and_unparseable_delta_handoff(self):
        first = self.accepted_first_pass()
        original = make_packet()
        oscillation = run_review_lifecycle(
            original,
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(oscillation["transition"]["status"], "human-handoff")
        self.assertIn("candidate", oscillation["transition"]["reason"])

        malformed = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff="not a unified diff",
        )
        malformed_result = run_review_lifecycle(
            make_packet(malformed),
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(malformed_result["transition"]["status"], "human-handoff")
        self.assertIn("delta", malformed_result["transition"]["reason"])


if __name__ == "__main__":
    unittest.main()
