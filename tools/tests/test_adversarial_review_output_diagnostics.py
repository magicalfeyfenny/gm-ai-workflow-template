import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.adversarial_review_contracts import (
    ADJUDICATION_RESULT_SCHEMA,
    SESSION_FAILURE_SCHEMA,
)
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
            return subprocess.CompletedProcess(command, 0)

        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=fake_process,
        ):
            return run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )

    def test_nonzero_provider_exit_is_bounded_without_raw_output(self):
        packet = semantic_packet()
        raw_provider_output = json.dumps(
            {"error": "authentication rejected; RAW_PROVIDER_SECRET"}
        )

        def fake_process(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text(
                raw_provider_output, encoding="utf-8"
            )
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            return subprocess.CompletedProcess(command, 23)

        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=fake_process,
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )

        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["schema"], SESSION_FAILURE_SCHEMA)
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertEqual(diagnostic["failure_class"], "provider-unclassified")
        self.assertEqual(diagnostic["exit_status"], 23)
        self.assertTrue(diagnostic["output_exists"])
        self.assertIsNone(diagnostic["validation_stage"])
        self.assertNotIn("RAW_PROVIDER_SECRET", json.dumps(result))

    def test_process_startup_failure_is_sanitized(self):
        packet = semantic_packet()
        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=OSError("RAW_STARTUP_SECRET"),
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["failure_class"], "startup")
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertNotIn("RAW_STARTUP_SECRET", json.dumps(result))

    def test_successful_process_without_result_file_fails_closed(self):
        packet = semantic_packet()
        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            return_value=subprocess.CompletedProcess(["codex", "exec"], 0),
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["failure_class"], "invalid-output")
        self.assertEqual(diagnostic["validation_stage"], "shape")
        self.assertEqual(diagnostic["diagnostic_code"], "output_missing_file")
        self.assertFalse(diagnostic["output_exists"])

    def test_malformed_json_is_distinct_from_top_level_shape_failure(self):
        malformed = self.provider_output_handoff(
            '{"schema":"adversarial-review-result:v2"'
        )
        shaped = self.provider_output_handoff("[]")

        malformed_diagnostic = malformed["session_failure"]
        shaped_diagnostic = shaped["session_failure"]
        self.assertEqual(malformed_diagnostic["validation_stage"], "parse")
        self.assertEqual(malformed_diagnostic["diagnostic_code"], "output_json_parse")
        self.assertIsNone(malformed_diagnostic["diagnostic_detail_code"])
        self.assertEqual(shaped_diagnostic["validation_stage"], "shape")
        self.assertEqual(shaped_diagnostic["diagnostic_code"], "output_top_level_shape")
        self.assertIsNone(shaped_diagnostic["diagnostic_detail_code"])
        self.assertNotEqual(
            malformed_diagnostic["diagnostic_code"], shaped_diagnostic["diagnostic_code"]
        )

    def test_successful_provider_output_read_failure_is_distinct_from_json_parse(self):
        packet = semantic_packet()
        valid_output = json.dumps(review_result(packet, []))

        def fake_process(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text(
                valid_output, encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0)

        original_read_text = Path.read_text

        def fail_result_read(path, *args, **kwargs):
            if path.name == "last-message.json":
                raise OSError("RAW_PROVIDER_PATH_AND_SECRET")
            return original_read_text(path, *args, **kwargs)

        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=fake_process,
        ), patch.object(Path, "read_text", fail_result_read):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )

        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertEqual(diagnostic["failure_class"], "invalid-output")
        self.assertEqual(diagnostic["exit_status"], 0)
        self.assertTrue(diagnostic["output_exists"])
        self.assertEqual(diagnostic["validation_stage"], "parse")
        self.assertEqual(diagnostic["diagnostic_code"], "output_read_failure")
        self.assertNotIn("RAW_PROVIDER_PATH_AND_SECRET", json.dumps(result))

    def test_successful_provider_exit_status_survives_reviewer_validation_failure(self):
        packet = semantic_packet()
        output = review_result(packet, [])
        output.pop("findings")
        result = self.provider_output_handoff(json.dumps(output))
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertEqual(diagnostic["exit_status"], 0)
        self.assertTrue(diagnostic["output_exists"])
        self.assertEqual(diagnostic["validation_stage"], "shape")
        self.assertEqual(
            diagnostic["diagnostic_code"], "output_missing_required_field"
        )
        self.assertIsNone(diagnostic["diagnostic_detail_code"])

    def test_successful_provider_exit_status_survives_adjudicator_validation_failure(self):
        packet = semantic_packet()
        finding = semantic_findings()[0]
        reviewer_output = review_result(packet, [finding])
        adjudicator_output = {
            "schema": ADJUDICATION_RESULT_SCHEMA,
            "issue_contract_revision": packet["issue_contract"]["revision"],
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
            return subprocess.CompletedProcess(command, 0)

        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=fake_process,
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["role"], "adjudicator")
        self.assertEqual(diagnostic["exit_status"], 0)
        self.assertTrue(diagnostic["output_exists"])
        self.assertEqual(diagnostic["validation_stage"], "semantic")
        self.assertEqual(
            diagnostic["diagnostic_code"], "adjudication_disposition_contract"
        )
        self.assertEqual(
            diagnostic["diagnostic_detail_code"], "adjudication_disposition_count"
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
        shaped_diagnostic = shaped["session_failure"]
        semantic_diagnostic = semantic["session_failure"]
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
        disposition_diagnostic = disposition["session_failure"]
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
        correction_diagnostic = correction_failure["session_failure"]
        self.assertEqual(correction_diagnostic["role"], "adjudicator")
        self.assertEqual(correction_diagnostic["validation_stage"], "semantic")
        self.assertEqual(
            correction_diagnostic["diagnostic_code"],
            "adjudication_correction_contract",
        )
        self.assertEqual(
            correction_diagnostic["diagnostic_detail_code"],
            "adjudication_correction_on_non_mutating_disposition",
        )
        encoded = json.dumps(correction_failure)
        self.assertNotIn("source-backed correction", encoded)
        self.assertNotIn("BOUNDARY-PACKET", encoded)
        self.assertNotIn("access_token", encoded)

    def test_review_outputs_are_bound_to_the_accepted_issue_revision(self):
        packet = semantic_packet()

        def stale_reviewer(role, payload, output_schema):
            output = review_result(payload, [])
            output["issue_contract_revision"] = "a" * 64
            return output

        stale_review = run_review_lifecycle(
            packet, initial=True, session_runner=stale_reviewer
        )
        self.assertEqual(stale_review["status"], "human-handoff")
        self.assertEqual(
            stale_review["session_failure"]["diagnostic_code"],
            "review_issue_revision_mismatch",
        )
        self.assertEqual(
            stale_review["session_failure"]["validation_stage"], "semantic"
        )

        finding_value = semantic_findings()[0]

        def stale_adjudicator(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [finding_value])
            output = adjudication_result(
                payload,
                [decision(finding_value["finding_id"], "reject")],
            )
            output["issue_contract_revision"] = "b" * 64
            return output

        stale_adjudication = run_review_lifecycle(
            packet, initial=True, session_runner=stale_adjudicator
        )
        self.assertEqual(stale_adjudication["status"], "human-handoff")
        self.assertEqual(
            stale_adjudication["session_failure"]["diagnostic_code"],
            "adjudication_issue_revision_mismatch",
        )
        self.assertEqual(
            stale_adjudication["session_failure"]["validation_stage"],
            "semantic",
        )

    def test_correction_contract_rules_have_distinct_sanitized_detail_codes(self):
        packet = semantic_packet()
        finding_value = semantic_findings()[0]
        finding_id = finding_value["finding_id"]
        acceptance_mismatch = decision(finding_id, "blocker", correction())
        acceptance_mismatch["correction_accepted"] = False
        acceptance_mismatch["correction"]["summary"] = "RAW_ADJUDICATOR_CORRECTION"
        cases = {
            "adjudication_correction_on_non_mutating_disposition": decision(
                finding_id, "reject", correction()
            ),
            "adjudication_correction_required_missing": decision(
                finding_id, "blocker"
            ),
            "adjudication_correction_acceptance_mismatch": acceptance_mismatch,
        }

        def run_case(adjudication_decision):
            def runner(role, payload, output_schema):
                if role == "reviewer":
                    return review_result(payload, [finding_value])
                return adjudication_result(payload, [adjudication_decision])

            return run_review_lifecycle(
                packet, initial=True, session_runner=runner
            )

        for expected_code, adjudication_decision in cases.items():
            with self.subTest(expected_code=expected_code):
                result = run_case(adjudication_decision)
                diagnostic = result["session_failure"]
                self.assertEqual(diagnostic["role"], "adjudicator")
                self.assertEqual(diagnostic["validation_stage"], "semantic")
                self.assertEqual(
                    diagnostic["diagnostic_code"],
                    "adjudication_correction_contract",
                )
                self.assertEqual(diagnostic["diagnostic_detail_code"], expected_code)
                encoded = json.dumps(result)
                self.assertNotIn("RAW_ADJUDICATOR_CORRECTION", encoded)

    def test_correction_cannot_supply_validation_instructions(self):
        packet = semantic_packet()
        finding_value = semantic_findings()[0]
        unsupported_correction = {
            **correction(),
            "validation": ["RAW_CORRECTION_VALIDATION"],
        }

        def runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [finding_value])
            return adjudication_result(
                payload,
                [decision(finding_value["finding_id"], "patch-now", unsupported_correction)],
            )

        result = run_review_lifecycle(
            packet, initial=True, session_runner=runner
        )
        diagnostic = result["session_failure"]
        self.assertEqual(diagnostic["role"], "adjudicator")
        self.assertEqual(diagnostic["validation_stage"], "shape")
        self.assertEqual(diagnostic["diagnostic_code"], "output_unsupported_field")
        self.assertIsNone(diagnostic["diagnostic_detail_code"])
        self.assertNotIn("RAW_CORRECTION_VALIDATION", json.dumps(result))

    def test_valid_zero_finding_reviewer_output_skips_adjudication(self):
        packet = semantic_packet()
        calls = []

        def valid_runner(role, payload, output_schema):
            calls.append(role)
            if role == "reviewer":
                return review_result(payload, [])
            raise AssertionError("empty reviewer output must skip adjudication")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=valid_runner
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls, ["reviewer"])
        self.assertIsNone(result["session_failure"])


if __name__ == "__main__":
    unittest.main()
