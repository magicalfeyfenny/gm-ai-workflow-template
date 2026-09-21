import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.adversarial_review_contracts import SESSION_FAILURE_SCHEMA
from tools.ci.adversarial_review_session import run_review_lifecycle
from tools.tests.test_adversarial_review_followup import (
    adjudication_result,
    correction,
    decision,
    review_result,
    semantic_findings,
    semantic_packet,
)


class StructuredOutputDiagnosticTests(unittest.TestCase):
    def provider_output_handoff(self, output: str) -> dict:
        packet = semantic_packet()

        def fake_process(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text(
                output, encoding="utf-8"
            )
            return 0

        with patch(
            "tools.ci.adversarial_review_session._sandbox_path",
            return_value="/usr/bin/sandbox-exec",
        ), patch(
            "tools.ci.adversarial_review_session._run_provider_process",
            side_effect=fake_process,
        ):
            return run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )

    def test_malformed_json_is_distinct_from_top_level_shape_failure(self):
        malformed = self.provider_output_handoff(
            '{"schema":"adversarial-review-result:v2"'
        )
        shaped = self.provider_output_handoff("[]")

        malformed_diagnostic = malformed["human_handoff"]["session_failure"]
        shaped_diagnostic = shaped["human_handoff"]["session_failure"]
        self.assertEqual(malformed_diagnostic["validation_stage"], "parse")
        self.assertEqual(malformed_diagnostic["diagnostic_code"], "output_json_parse")
        self.assertEqual(shaped_diagnostic["validation_stage"], "shape")
        self.assertEqual(shaped_diagnostic["diagnostic_code"], "output_top_level_shape")
        self.assertNotEqual(
            malformed_diagnostic["diagnostic_code"], shaped_diagnostic["diagnostic_code"]
        )

    def test_successful_provider_exit_status_survives_reviewer_validation_failure(self):
        packet = semantic_packet()
        output = review_result(packet, [])
        output.pop("findings")
        result = self.provider_output_handoff(json.dumps(output))
        diagnostic = result["human_handoff"]["session_failure"]
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertEqual(diagnostic["exit_status"], 0)
        self.assertTrue(diagnostic["output_exists"])
        self.assertEqual(diagnostic["validation_stage"], "shape")
        self.assertEqual(
            diagnostic["diagnostic_code"], "output_missing_required_field"
        )

    def test_successful_provider_exit_status_survives_adjudicator_validation_failure(self):
        packet = semantic_packet()
        finding = semantic_findings()[0]
        reviewer_output = review_result(packet, [finding])
        adjudicator_output = {
            "schema": "adversarial-adjudication-result:v2",
            "candidate_identity": reviewer_output["candidate_identity"],
            "dispositions": [],
            "human_handoff": {"required": False, "reason": None},
        }
        calls = 0

        def fake_process(command, **kwargs):
            nonlocal calls
            output = reviewer_output if calls == 0 else adjudicator_output
            Path(command[command.index("--output-last-message") + 1]).write_text(
                json.dumps(output), encoding="utf-8"
            )
            calls += 1
            return 0

        with patch(
            "tools.ci.adversarial_review_session._sandbox_path",
            return_value="/usr/bin/sandbox-exec",
        ), patch(
            "tools.ci.adversarial_review_session._run_provider_process",
            side_effect=fake_process,
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        diagnostic = result["human_handoff"]["session_failure"]
        self.assertEqual(diagnostic["role"], "adjudicator")
        self.assertEqual(diagnostic["exit_status"], 0)
        self.assertTrue(diagnostic["output_exists"])
        self.assertEqual(diagnostic["validation_stage"], "semantic")
        self.assertEqual(
            diagnostic["diagnostic_code"], "adjudication_disposition_contract"
        )

    def test_schema_shape_failure_is_distinct_from_semantic_contract_failure(self):
        packet = semantic_packet()
        shaped_output = review_result(packet, [])
        shaped_output.pop("findings")
        shaped_output["provider_secret"] = "RAW_PROVIDER_SECRET"

        def shaped_runner(role, payload, output_schema):
            if role == "reviewer":
                return shaped_output
            raise AssertionError("schema failure must stop before adjudication")

        shaped = run_review_lifecycle(
            packet, initial=True, session_runner=shaped_runner
        )

        def semantic_runner(role, payload, output_schema):
            if role == "reviewer":
                output = review_result(payload, [])
                output["candidate_identity"]["head_sha"] = "R" * 40
                return output
            raise AssertionError("semantic reviewer failure must stop before adjudication")

        semantic = run_review_lifecycle(
            packet, initial=True, session_runner=semantic_runner
        )
        shaped_diagnostic = shaped["human_handoff"]["session_failure"]
        semantic_diagnostic = semantic["human_handoff"]["session_failure"]
        self.assertEqual(shaped_diagnostic["validation_stage"], "shape")
        self.assertEqual(
            shaped_diagnostic["diagnostic_code"],
            "output_missing_required_field",
        )
        self.assertEqual(semantic_diagnostic["validation_stage"], "semantic")
        self.assertEqual(
            semantic_diagnostic["diagnostic_code"],
            "review_candidate_identity_mismatch",
        )
        self.assertNotIn("RAW_PROVIDER_SECRET", json.dumps(shaped))
        self.assertNotIn("R" * 40, json.dumps(semantic))

    def test_semantic_diagnostics_preserve_role_and_contract_boundary(self):
        packet = semantic_packet()
        finding_value = semantic_findings()[0]

        def disposition_runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [finding_value])
            return adjudication_result(payload, [])

        disposition = run_review_lifecycle(
            packet, initial=True, session_runner=disposition_runner
        )
        disposition_diagnostic = disposition["human_handoff"]["session_failure"]
        self.assertEqual(disposition_diagnostic["role"], "adjudicator")
        self.assertEqual(disposition_diagnostic["validation_stage"], "semantic")
        self.assertEqual(
            disposition_diagnostic["diagnostic_code"],
            "adjudication_disposition_contract",
        )

        def correction_runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [finding_value])
            return adjudication_result(
                payload, [decision(finding_value["finding_id"], "reject", correction())]
            )

        correction_failure = run_review_lifecycle(
            packet, initial=True, session_runner=correction_runner
        )
        correction_diagnostic = correction_failure["human_handoff"]["session_failure"]
        self.assertEqual(correction_diagnostic["role"], "adjudicator")
        self.assertEqual(correction_diagnostic["validation_stage"], "semantic")
        self.assertEqual(
            correction_diagnostic["diagnostic_code"],
            "adjudication_correction_contract",
        )
        encoded = json.dumps(correction_failure)
        self.assertNotIn("source-backed correction", encoded)
        self.assertNotIn("BOUNDARY-PACKET", encoded)
        self.assertNotIn("access_token", encoded)

    def test_valid_reviewer_and_adjudicator_outputs_remain_accepted(self):
        packet = semantic_packet()

        def valid_runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [])
            return adjudication_result(payload, [])

        result = run_review_lifecycle(
            packet, initial=True, session_runner=valid_runner
        )
        self.assertEqual(result["transition"]["status"], "complete")
        self.assertEqual(result["adjudication"]["dispositions"], [])
        self.assertNotIn("session_failure", result)


if __name__ == "__main__":
    unittest.main()
