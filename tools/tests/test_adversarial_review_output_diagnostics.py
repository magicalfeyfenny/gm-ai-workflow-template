import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.adversarial_review_contracts import SESSION_FAILURE_SCHEMA
from tools.ci.adversarial_review_process import ProviderHangError
from tools.ci.adversarial_review_session import ReviewSessionError, run_review_lifecycle
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

    def test_provider_failure_classes_are_bounded_and_do_not_infer_auth(self):
        packet = semantic_packet()

        def run_case(
            *,
            returncode=None,
            output=None,
            timeout=False,
            auth=True,
            sandbox_unavailable=False,
        ):
            sandbox_path_patch = (
                {"side_effect": ReviewSessionError("RAW_SANDBOX_FAILURE")}
                if sandbox_unavailable
                else {"return_value": "/usr/bin/sandbox-exec"}
            )

            def fake_process(command, **kwargs):
                if output is not None:
                    Path(command[command.index("--output-last-message") + 1]).write_text(
                        output, encoding="utf-8"
                    )
                if timeout:
                    raise ProviderHangError("pre-turn startup")
                return returncode

            with tempfile.TemporaryDirectory() as directory:
                source_home = Path(directory) / "source-codex-home"
                source_home.mkdir()
                if auth:
                    (source_home / "auth.json").write_text(
                        '{"access_token":"sentinel"}', encoding="utf-8"
                    )
                with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}), patch(
                    "tools.ci.adversarial_review_session._sandbox_path",
                    **sandbox_path_patch,
                ), patch(
                    "tools.ci.adversarial_review_session._run_provider_process",
                    side_effect=fake_process,
                ):
                    return run_review_lifecycle(
                        packet, initial=True, codex_executable="/fake/codex"
                    )

        raw_provider_error = json.dumps(
            {"error": "authentication rejected; RAW_PROVIDER_SECRET"}
        )
        cases = [
            (
                "provider-unclassified-auth-present",
                "provider-unclassified",
                run_case(returncode=23, output=raw_provider_error, auth=True),
            ),
            (
                "provider-unclassified-auth-absent",
                "provider-unclassified",
                run_case(returncode=23, output=raw_provider_error, auth=False),
            ),
            (
                "positive-sandbox-setup-failure",
                "sandbox",
                run_case(auth=True, sandbox_unavailable=True),
            ),
            ("timeout", "timeout", run_case(timeout=True)),
            (
                "invalid-output",
                "invalid-output",
                run_case(returncode=0, output="not-json"),
            ),
        ]
        for case_name, failure_class, result in cases:
            with self.subTest(case=case_name):
                diagnostic = result["human_handoff"]["session_failure"]
                self.assertEqual(diagnostic["schema"], SESSION_FAILURE_SCHEMA)
                self.assertEqual(diagnostic["role"], "reviewer")
                self.assertEqual(diagnostic["failure_class"], failure_class)
                self.assertNotIn("RAW_PROVIDER_SECRET", json.dumps(result))
                self.assertNotIn("RAW_SANDBOX_FAILURE", json.dumps(result))
                self.assertNotIn("sentinel", json.dumps(result))
                self.assertNotIn("BOUNDARY-PACKET", json.dumps(result))
                self.assertNotIn("pre-turn startup", json.dumps(result))
                if failure_class == "provider-unclassified":
                    self.assertEqual(diagnostic["exit_status"], 23)
                    self.assertTrue(diagnostic["output_exists"])
                if failure_class == "invalid-output":
                    self.assertEqual(diagnostic["validation_stage"], "parse")
                    self.assertEqual(diagnostic["diagnostic_code"], "output_json_parse")
                    self.assertIsNone(diagnostic["diagnostic_detail_code"])
                else:
                    self.assertIsNone(diagnostic["validation_stage"])
                    self.assertIsNone(diagnostic["diagnostic_code"])
                    self.assertIsNone(diagnostic["diagnostic_detail_code"])

    def test_malformed_json_is_distinct_from_top_level_shape_failure(self):
        malformed = self.provider_output_handoff(
            '{"schema":"adversarial-review-result:v2"'
        )
        shaped = self.provider_output_handoff("[]")

        malformed_diagnostic = malformed["human_handoff"]["session_failure"]
        shaped_diagnostic = shaped["human_handoff"]["session_failure"]
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
            return 0

        original_read_text = Path.read_text

        def fail_result_read(path, *args, **kwargs):
            if path.name == "last-message.json":
                raise OSError("RAW_PROVIDER_PATH_AND_SECRET")
            return original_read_text(path, *args, **kwargs)

        with patch(
            "tools.ci.adversarial_review_session._sandbox_path",
            return_value="/usr/bin/sandbox-exec",
        ), patch(
            "tools.ci.adversarial_review_session._run_provider_process",
            side_effect=fake_process,
        ), patch.object(Path, "read_text", fail_result_read):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )

        diagnostic = result["human_handoff"]["session_failure"]
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
        diagnostic = result["human_handoff"]["session_failure"]
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
        self.assertEqual(
            correction_diagnostic["diagnostic_detail_code"],
            "adjudication_correction_on_non_mutating_disposition",
        )
        encoded = json.dumps(correction_failure)
        self.assertNotIn("source-backed correction", encoded)
        self.assertNotIn("BOUNDARY-PACKET", encoded)
        self.assertNotIn("access_token", encoded)

    def test_correction_contract_rules_have_distinct_sanitized_detail_codes(self):
        packet = semantic_packet()
        finding_value = semantic_findings()[0]
        finding_id = finding_value["finding_id"]
        outside_scope = correction()
        outside_scope["locations"] = ["model-controlled-outside-scope"]
        outside_scope["summary"] = "RAW_ADJUDICATOR_CORRECTION"
        acceptance_mismatch = decision(finding_id, "blocker", correction())
        acceptance_mismatch["correction_accepted"] = False
        cases = {
            "adjudication_correction_on_non_mutating_disposition": decision(
                finding_id, "reject", correction()
            ),
            "adjudication_correction_required_missing": decision(
                finding_id, "blocker"
            ),
            "adjudication_correction_acceptance_mismatch": acceptance_mismatch,
            "adjudication_correction_scope": decision(
                finding_id, "blocker", outside_scope
            ),
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
                diagnostic = result["human_handoff"]["session_failure"]
                self.assertEqual(diagnostic["role"], "adjudicator")
                self.assertEqual(diagnostic["validation_stage"], "semantic")
                self.assertEqual(
                    diagnostic["diagnostic_code"],
                    "adjudication_correction_contract",
                )
                self.assertEqual(diagnostic["diagnostic_detail_code"], expected_code)
                encoded = json.dumps(result)
                self.assertNotIn("RAW_ADJUDICATOR_CORRECTION", encoded)
                self.assertNotIn("model-controlled-outside-scope", encoded)

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
