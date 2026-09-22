import copy
import json
import unittest

from tools.ci.adversarial_review import (
    REVIEW_RESULT_SCHEMA,
    ReviewContractError,
    candidate_identity,
)
from tools.ci.adversarial_review_state import recover_implementation_payload
from tools.ci.adversarial_review_session import run_review_lifecycle
from tools.tests.test_adversarial_review_lifecycle import (
    INCLUDED,
    REVISION,
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
        self.assertEqual(state["schema"], "adversarial-review-continuation:v2")
        self.assertTrue(state["accepted_correction"])
        self.assertEqual(state["cycle"], 1)
        self.assertIn(INCLUDED[0], state["authorized_locations"])
        self.assertNotIn("candidate_changed", state)
        self.assertNotIn("expected_candidate", state)
        self.assertNotIn("previous_candidates", state)
        action = recover_implementation_payload(json.loads(json.dumps(first)))
        self.assertEqual(action, first["implementation_payload"])
        self.assertEqual(action["candidate_identity"], first["candidate_identity"])
        self.assertEqual(action["issue_contract_revision"], REVISION)
        self.assertEqual(action["correction_cycle"], 1)
        self.assertEqual(action["corrections"][0]["finding_id"], "F-correction")
        self.assertEqual(state["pending_implementation_action"]["corrections"], action["corrections"])
        self.assertEqual(state["adjudication_history"][0]["correction_status"], "action-pending")
        self.assertNotIn("defect_or_invariant", json.dumps(state))

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

    def test_saved_action_rejects_tampering_or_stale_bindings(self):
        first = self.accepted_first_pass()
        tampered_payload = copy.deepcopy(first)
        tampered_payload["implementation_payload"]["corrections"][0]["basis"] = "changed"
        tampered_state = copy.deepcopy(first)
        tampered_state["continuation_state"]["issue_contract_revision"] = "f" * 64
        wrong_candidate = copy.deepcopy(first)
        wrong_candidate["candidate_identity"]["head_sha"] = "z" * 40
        for outcome in (tampered_payload, tampered_state, wrong_candidate):
            with self.subTest(outcome=outcome):
                with self.assertRaises(ReviewContractError):
                    recover_implementation_payload(outcome)

    def test_handoff_keeps_prior_validated_history_without_reissuing_action(self):
        first = self.accepted_first_pass()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncorrected\n"
            ),
        )

        def failed_session(role, payload, output_schema):
            raise ReviewContractError("synthetic session failure")

        handoff = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=failed_session,
        )
        self.assertEqual(handoff["transition"]["status"], "human-handoff")
        self.assertIsNone(handoff["implementation_payload"])
        self.assertEqual(
            handoff["adjudication_history"], first["adjudication_history"]
        )
        self.assertNotIn("synthetic session failure", json.dumps(handoff))

    def test_final_summary_keeps_prior_action_follow_up_and_reject(self):
        raw_finding = finding("F-patch")
        raw_finding["defect_or_invariant"] = "RAW_REVIEWER_FINDING_SECRET"
        first = run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [raw_finding, finding("F-follow"), finding("F-reject")],
                [
                    decision("F-patch", "patch-now", correction()),
                    decision("F-follow", "follow-up"),
                    decision("F-reject", "reject"),
                ],
            ),
        )
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncorrected\n"
            ),
        )
        final = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(final["transition"]["status"], "complete")
        self.assertIsNone(final["implementation_payload"])
        history = final["adjudication_history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["correction_status"], "next-cycle-adjudicated")
        prior = {row["finding_id"]: row for row in history[0]["dispositions"]}
        self.assertEqual(prior["F-patch"]["correction"]["locations"], [INCLUDED[0]])
        self.assertEqual(prior["F-follow"]["disposition"], "follow-up")
        self.assertEqual(prior["F-reject"]["disposition"], "reject")
        self.assertEqual(history[1]["correction_status"], "no-action")
        self.assertNotIn("RAW_REVIEWER_FINDING_SECRET", json.dumps(final))

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
        self.assertEqual(
            len(first["implementation_payload"]["corrections"]), 2
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

    def test_prior_cycle_locations_are_not_carried_into_next_state(self):
        first = self.accepted_first_pass()
        cycle_one_candidate = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncycle-one-a\n"
            ),
        )
        second_correction = correction()
        second_correction["locations"] = [INCLUDED[1]]
        second = run_review_lifecycle(
            make_packet(cycle_one_candidate),
            state=first["continuation_state"],
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "patch-now", second_correction)],
            ),
        )
        self.assertEqual(second["transition"]["status"], "revalidate-and-rereview")
        state = second["continuation_state"]
        self.assertEqual(state["cycle"], 2)
        self.assertEqual(len(state["candidate_history"]), 2)
        self.assertEqual(state["authorized_locations"], [INCLUDED[1]])
        self.assertNotIn(INCLUDED[0], state["authorized_locations"])

        cycle_two_candidate = candidate(
            head_sha="i" * 40,
            tree_sha="v" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncycle-two-a\n"
                "diff --git a/tools/ci/adversarial_review_state.py "
                "b/tools/ci/adversarial_review_state.py\ncycle-two-b\n"
            ),
        )
        calls = []
        result = run_review_lifecycle(
            make_packet(cycle_two_candidate),
            state=state,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertIn(INCLUDED[0], result["transition"]["reason"])
        self.assertEqual(calls, [])

    def test_current_pass_reauthorization_allows_location_again(self):
        first = self.accepted_first_pass()
        cycle_one_candidate = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncycle-one-a\n"
            ),
        )
        reauthorized_correction = correction()
        second = run_review_lifecycle(
            make_packet(cycle_one_candidate),
            state=first["continuation_state"],
            session_runner=self.runner(
                [finding("F-reauthorize")],
                [
                    decision(
                        "F-reauthorize",
                        "patch-now",
                        reauthorized_correction,
                    )
                ],
            ),
        )
        self.assertEqual(second["transition"]["status"], "revalidate-and-rereview")
        state = second["continuation_state"]
        self.assertEqual(state["authorized_locations"], [INCLUDED[0]])

        cycle_two_candidate = candidate(
            head_sha="i" * 40,
            tree_sha="v" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncycle-two-a\n"
            ),
        )
        result = run_review_lifecycle(
            make_packet(cycle_two_candidate),
            state=state,
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
