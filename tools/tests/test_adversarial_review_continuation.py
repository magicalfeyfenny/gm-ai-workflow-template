import unittest

from tools.ci.adversarial_review import REVIEW_RESULT_SCHEMA, candidate_identity
from tools.ci.adversarial_review_session import ReviewSessionError, run_review_lifecycle
from tools.ci.adversarial_review_state import validate_lifecycle_artifact
from tools.tests.test_adversarial_review_lifecycle import (
    DIFF,
    REVISION,
    candidate,
    correction,
    decision,
    finding,
    make_packet,
)


class LifecycleContinuationTests(unittest.TestCase):
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
            from tools.tests.test_adversarial_review_lifecycle import adjudication_result

            return adjudication_result(payload, decisions)

        return run

    def first_action(self):
        return run_review_lifecycle(
            make_packet(),
            initial=True,
            session_runner=self.runner(
                [finding()], [decision("F-correction", "patch-now", correction())]
            ),
        )

    def test_metadata_only_or_repeated_content_cannot_continue(self):
        first = self.first_action()
        metadata_only = candidate(head_sha="g" * 40)
        calls = []
        result = run_review_lifecycle(
            make_packet(metadata_only),
            state=first,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertIn("did not change", result["reason"])
        self.assertEqual(calls, [])

    def test_correction_cycles_are_bounded(self):
        first = self.first_action()
        second_candidate = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "second cycle\n",
        )
        second = run_review_lifecycle(
            make_packet(second_candidate),
            state=first,
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "blocker", correction())],
            ),
        )
        self.assertEqual(second["status"], "revalidate-and-rereview")
        self.assertEqual(second["cycle"], 2)
        self.assertEqual(len(second["prior_candidate_identities"]), 1)

        third_candidate = candidate(
            head_sha="j" * 40,
            tree_sha="v" * 40,
            diff=DIFF + "third cycle\n",
        )
        capped = run_review_lifecycle(
            make_packet(third_candidate),
            state=second,
            session_runner=self.runner(
                [finding("F-third")],
                [decision("F-third", "patch-now", correction())],
            ),
        )
        self.assertEqual(capped["status"], "human-handoff")
        self.assertIn("retry budget", capped["reason"])
        self.assertEqual(capped["corrections"], [])

    def test_low_risk_has_one_retry_and_then_hands_off(self):
        first = run_review_lifecycle(
            make_packet(risk="low"),
            initial=True,
            session_runner=self.runner(
                [finding()], [decision("F-correction", "patch-now", correction())]
            ),
        )
        self.assertEqual(first["status"], "revalidate-and-rereview")
        self.assertEqual(first["cycle"], 1)

        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "low-risk correction\n",
        )
        capped = run_review_lifecycle(
            make_packet(corrected, risk="low"),
            state=first,
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "patch-now", correction())],
            ),
        )
        self.assertEqual(capped["status"], "human-handoff")
        self.assertIn("risk:low", capped["reason"])
        self.assertIn("retry budget 1", capped["reason"])

    def test_medium_risk_has_two_retries_without_a_distinct_lifecycle(self):
        first = run_review_lifecycle(
            make_packet(risk="medium"),
            initial=True,
            session_runner=self.runner(
                [finding()], [decision("F-correction", "patch-now", correction())]
            ),
        )
        second_candidate = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "medium second correction\n",
        )
        second = run_review_lifecycle(
            make_packet(second_candidate, risk="medium"),
            state=first,
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "patch-now", correction())],
            ),
        )
        self.assertEqual(second["status"], "revalidate-and-rereview")
        self.assertEqual(second["cycle"], 2)

        third_candidate = candidate(
            head_sha="j" * 40,
            tree_sha="v" * 40,
            diff=DIFF + "medium third correction\n",
        )
        calls = []
        mismatched = run_review_lifecycle(
            make_packet(third_candidate, risk="low"),
            state=second,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(mismatched["status"], "human-handoff")
        self.assertEqual(mismatched["risk"], "medium")
        self.assertEqual(mismatched["cycle"], 2)
        self.assertIn("fresh human-authorized lifecycle", mismatched["reason"])
        self.assertEqual(calls, [])
        self.assertEqual(validate_lifecycle_artifact(mismatched), mismatched)

        capped = run_review_lifecycle(
            make_packet(third_candidate, risk="medium"),
            state=second,
            session_runner=self.runner(
                [finding("F-third")],
                [decision("F-third", "patch-now", correction())],
            ),
        )
        self.assertEqual(capped["status"], "human-handoff")
        self.assertIn("retry budget 2", capped["reason"])

    def test_exhausted_handoff_cannot_reset_without_a_new_initial_run(self):
        first = self.first_action()
        second_candidate = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "second cycle\n",
        )
        second = run_review_lifecycle(
            make_packet(second_candidate),
            state=first,
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "blocker", correction())],
            ),
        )
        third_candidate = candidate(
            head_sha="j" * 40,
            tree_sha="v" * 40,
            diff=DIFF + "third cycle\n",
        )
        capped = run_review_lifecycle(
            make_packet(third_candidate),
            state=second,
            session_runner=self.runner(
                [finding("F-third")],
                [decision("F-third", "patch-now", correction())],
            ),
        )
        self.assertEqual(capped["status"], "human-handoff")

        calls = []
        reset_attempt = run_review_lifecycle(
            make_packet(candidate(head_sha="k" * 40)),
            state=capped,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(reset_attempt["status"], "human-handoff")
        self.assertEqual(calls, [])

    def test_new_candidate_can_start_a_fresh_budget_after_handoff(self):
        first = run_review_lifecycle(
            make_packet(risk="low"),
            initial=True,
            session_runner=self.runner(
                [finding()], [decision("F-correction", "patch-now", correction())]
            ),
        )
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "low-risk correction\n",
        )
        handoff = run_review_lifecycle(
            make_packet(corrected, risk="low"),
            state=first,
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "patch-now", correction())],
            ),
        )
        self.assertEqual(handoff["status"], "human-handoff")

        fresh = candidate(
            head_sha="j" * 40,
            tree_sha="v" * 40,
            diff=DIFF + "human-directed replacement\n",
        )
        result = run_review_lifecycle(
            make_packet(fresh, risk="low"),
            initial=True,
            session_runner=self.runner(),
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["cycle"], 0)

    def test_risk_tier_change_cannot_continue_saved_state(self):
        first = self.first_action()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "corrected\n",
        )
        calls = []
        result = run_review_lifecycle(
            make_packet(corrected, risk="low"),
            state=first,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertEqual(result["risk"], first["risk"])
        self.assertIn("different risk tier", result["reason"])
        self.assertEqual(calls, [])

    def test_oscillation_is_rejected_by_content_identity(self):
        first = self.first_action()
        middle = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "middle\n",
        )
        second = run_review_lifecycle(
            make_packet(middle),
            state=first,
            session_runner=self.runner(
                [finding("F-second")],
                [decision("F-second", "patch-now", correction())],
            ),
        )
        returned_to_first = candidate(head_sha="j" * 40)
        calls = []
        result = run_review_lifecycle(
            make_packet(returned_to_first),
            state=second,
            session_runner=self.runner(calls=calls),
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertIn("oscillated", result["reason"])
        self.assertEqual(calls, [])

    def test_review_session_failure_is_a_bounded_handoff(self):
        first = self.first_action()
        corrected = candidate(
            head_sha="g" * 40,
            tree_sha="u" * 40,
            diff=DIFF + "corrected\n",
        )

        def failed_session(role, payload, output_schema):
            raise ReviewSessionError("RAW_PROVIDER_SECRET")

        result = run_review_lifecycle(
            make_packet(corrected), state=first, session_runner=failed_session
        )
        self.assertEqual(result["status"], "human-handoff")
        self.assertEqual(result["session_failure"]["role"], "reviewer")
        self.assertNotIn("RAW_PROVIDER_SECRET", str(result))
        self.assertEqual(result["issue_contract_revision"], REVISION)


if __name__ == "__main__":
    unittest.main()
