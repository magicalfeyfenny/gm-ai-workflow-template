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

    def accepted_first_pass(self):
        return run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [finding()], [decision("F-correction", "patch-now", correction())]
            ),
        )

    def test_emitted_state_is_the_only_continuation_authority(self):
        first = self.accepted_first_pass()
        state = first["continuation_state"]
        self.assertEqual(state["schema"], "adversarial-review-continuation:v3")
        self.assertTrue(state["accepted_correction"])
        self.assertEqual(state["cycle"], 1)
        self.assertNotIn("authorized_locations", state)
        self.assertEqual(state["pending_implementation_action"]["schema"], "adversarial-review-implementation-action:v2")
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
        self.assertEqual(prior["F-patch"]["correction"], correction())
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

    def test_packet_context_paths_do_not_restrict_corrected_candidate(self):
        first = self.accepted_first_pass()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\n"
                "diff --git a/docs/review-boundary.md b/docs/review-boundary.md\n"
                "review against the accepted issue\n"
            ),
        )
        calls = []
        result = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["transition"]["status"], "complete")
        self.assertEqual(calls, ["reviewer", "adjudicator"])

    def test_multiple_corrections_do_not_create_path_authority(self):
        second_finding = finding("F-second")
        first = run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [finding(), second_finding],
                [
                    decision("F-correction", "patch-now", correction()),
                    decision("F-second", "patch-now", correction()),
                ],
            ),
        )
        self.assertNotIn("authorized_locations", first["continuation_state"])
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
                "diff --git a/docs/review-boundary.md "
                "b/docs/review-boundary.md\nthird\n"
            ),
        )
        result = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(result["transition"]["status"], "complete")

    def test_candidate_oscillation_hands_off(self):
        first = self.accepted_first_pass()
        original = make_packet()
        oscillation = run_review_lifecycle(
            original,
            state=first["continuation_state"],
            session_runner=self.runner(),
        )
        self.assertEqual(oscillation["transition"]["status"], "human-handoff")
        self.assertIn("candidate", oscillation["transition"]["reason"])

    def test_second_cycle_action_recovers_from_json_round_trip(self):
        first = self.accepted_first_pass()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=(
                "diff --git a/tools/ci/adversarial_review.py "
                "b/tools/ci/adversarial_review.py\ncorrected\n"
            ),
        )

        def second_cycle_runner(role, payload, output_schema):
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": [finding("F-second-cycle")],
                }
            return adjudication_result(
                payload,
                [decision("F-second-cycle", "blocker", correction())],
            )

        second = run_review_lifecycle(
            make_packet(corrected),
            state=first["continuation_state"],
            session_runner=second_cycle_runner,
        )
        self.assertEqual(
            second["transition"]["status"], "revalidate-and-rereview"
        )
        self.assertEqual(
            second["continuation_state"]["adjudication_history"][-1]["cycle"], 1
        )
        self.assertEqual(second["implementation_payload"]["correction_cycle"], 2)

        saved = json.loads(json.dumps(second))
        recovered = recover_implementation_payload(saved)
        self.assertEqual(recovered, saved["implementation_payload"])
        self.assertEqual(recovered["candidate_identity"], candidate_identity(corrected))
        self.assertEqual(recovered["issue_contract_revision"], REVISION)
        self.assertEqual(recovered["correction_cycle"], 2)


if __name__ == "__main__":
    unittest.main()
