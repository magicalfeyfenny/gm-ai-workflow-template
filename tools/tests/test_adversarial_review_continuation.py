import unittest

from tools.ci.adversarial_review import REVIEW_RESULT_SCHEMA, candidate_identity
from tools.ci.adversarial_review_session import ReviewSessionError, run_review_lifecycle
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
        self.assertIn("cap", capped["reason"])
        self.assertEqual(capped["corrections"], [])

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
