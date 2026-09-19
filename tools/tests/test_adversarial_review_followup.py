import hashlib
import json
import subprocess
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
    validate_adjudication_packet,
    validate_review_packet,
)
from tools.ci.adversarial_review_session import (
    ReviewSessionError,
    _run_fresh_codex_session,
    _write_sandbox_profile,
    run_adversarial_review,
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
Source-backed semantic evidence fixture:

- The candidate omits a required invariant that the accepted contract requires.
- The Python 3.13+ concern is a bounded same-outcome improvement within this issue.
- The separately meaningful concern is outside the accepted outcome.
- The python3.12 documentation example already uses a supported interpreter.
- The mocked temporary-environment path adds no defect because unit and live integration evidence cover it.
- The compatibility claim has no independent compatibility evidence and no concrete consumer.
- Manual visual observation is not an accepted requirement.
- The unavailable environment capability is not candidate failure because existing evidence passes.
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
            "Python 3.13+ concern is a bounded same-outcome improvement",
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
        "candidate_identity": candidate_identity(packet["candidate"]),
        "findings": findings,
    }


def correction() -> dict:
    return {
        "summary": "Apply the bounded source-backed correction.",
        "locations": [INCLUDED[0]],
        "validation": ["rerun semantic fixtures"],
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
        "candidate_identity": packet["candidate_identity"],
        "dispositions": decisions,
        "human_handoff": {"required": False, "reason": None},
    }


def source_backed_decisions(packet: dict) -> list[dict]:
    source_text = "\n".join(item["text"] for item in packet["evidence"]["source_items"])
    decisions = []
    for item in packet["findings"]:
        claim = item["defect_or_invariant"].casefold()
        evidence = source_text.casefold()
        if "required invariant" in claim and "accepted contract requires" in evidence:
            value = correction()
            disposition = "blocker"
        elif "python 3.13+" in claim and "bounded same-outcome improvement" in evidence:
            value = correction()
            disposition = "patch-now"
        elif "python 3.13+" in claim and "outside the accepted outcome" in evidence:
            value = None
            disposition = "follow-up"
        elif "separately meaningful" in claim and "outside the accepted outcome" in evidence:
            value = None
            disposition = "follow-up"
        elif "python3.12" in claim and "already uses a supported interpreter" in evidence:
            value = None
            disposition = "reject"
        elif "temporary-environment" in claim and "unit and live integration evidence cover it" in evidence:
            value = None
            disposition = "reject"
        elif "compatible" in claim and "no independent compatibility evidence" in evidence:
            value = None
            disposition = "reject"
        elif "manual visual" in claim and "not an accepted requirement" in evidence:
            value = None
            disposition = "reject"
        elif "unavailable environment" in claim and "existing evidence passes" in evidence:
            value = None
            disposition = "reject"
        else:
            value = None
            disposition = "reject"
        decisions.append(decision(item["finding_id"], disposition, value))
    return decisions


class SourceBackedFixtureTests(unittest.TestCase):
    def test_contract_revision_binds_snapshot_contents(self):
        packet = semantic_packet()
        packet["issue_contract"]["body"] += "changed without re-acceptance\n"
        with self.assertRaisesRegex(ReviewContractError, "accepted snapshot"):
            validate_review_packet(packet)

    def test_semantic_cases_are_classified_from_actual_source_text(self):
        review_packet = semantic_packet()
        findings = semantic_findings()

        def runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, findings)
            return adjudication_result(payload, source_backed_decisions(payload))

        result = run_adversarial_review(review_packet, session_runner=runner)
        self.assertEqual(
            [item["disposition"] for item in result["dispositions"]],
            ["blocker", "patch-now", "follow-up", "reject", "reject", "reject", "reject", "reject"],
        )

    def test_material_source_change_changes_classification_with_same_evidence_id(self):
        review_packet = semantic_packet()
        findings = semantic_findings()
        original = build_adjudication_packet(review_packet, findings)
        changed = json.loads(json.dumps(original))
        original_item = original["evidence"]["source_items"][0]
        changed_item = changed["evidence"]["source_items"][0]
        self.assertEqual(original_item["evidence_id"], changed_item["evidence_id"])
        changed_item["text"] = changed_item["text"].replace(
            "bounded same-outcome improvement within this issue",
            "outside the accepted outcome",
        )
        validate_adjudication_packet(changed)
        original_decisions = source_backed_decisions(original)
        changed_decisions = source_backed_decisions(changed)
        self.assertEqual(original_decisions[1]["disposition"], "patch-now")
        self.assertEqual(changed_decisions[1]["disposition"], "follow-up")


class SandboxBoundaryTests(unittest.TestCase):
    def test_profile_allows_selected_provider_not_its_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = root / "provider"
            provider.mkdir()
            executable = provider / "fake-codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            codex_home = root / "codex-home"
            codex_home.mkdir()
            profile = root / "sandbox.sb"
            _write_sandbox_profile(profile, root, executable, codex_home)
            text = profile.read_text(encoding="utf-8")
        self.assertIn(f'(allow file-read* (literal "{executable.resolve()}"))', text)
        self.assertNotIn(f'(allow file-read* (subpath "{provider.resolve()}"))', text)
        self.assertNotIn('(allow file-read* (subpath "/usr"))', text)


class SessionFailureTests(unittest.TestCase):
    def test_invalid_session_result_becomes_bounded_handoff(self):
        packet = semantic_packet()

        def invalid_runner(role, payload, output_schema):
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": [
                        {
                            **semantic_findings()[0],
                            "supporting_evidence": ["missing-evidence"],
                        }
                    ],
                }
            raise AssertionError("invalid reviewer output must stop before adjudication")

        result = run_review_lifecycle(packet, session_runner=invalid_runner)
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertEqual(result["human_handoff"]["candidate_identity"], candidate_identity(packet["candidate"]))
        self.assertEqual(result["human_handoff"]["finding_dispositions"], [])
        self.assertNotIn("missing-evidence", json.dumps(result))

    def test_provider_failure_becomes_bounded_handoff_without_raw_text(self):
        packet = semantic_packet()

        def failing_runner(role, payload, output_schema):
            raise ReviewSessionError("raw-provider-instruction")

        result = run_review_lifecycle(packet, session_runner=failing_runner)
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertEqual(result["human_handoff"]["finding_dispositions"], [])
        self.assertNotIn("raw-provider-instruction", json.dumps(result))


class ProviderOutputBoundaryTests(unittest.TestCase):
    def test_raw_provider_streams_do_not_enter_session_errors(self):
        for stream in ("stdout", "stderr"):
            raw = "raw-provider-instruction-" + stream
            completed = subprocess.CompletedProcess(
                ["sandbox-exec"], 23, raw if stream == "stdout" else "", raw if stream == "stderr" else ""
            )
            with self.subTest(stream=stream):
                with patch(
                    "tools.ci.adversarial_review_session._sandbox_path",
                    return_value="/usr/bin/sandbox-exec",
                ), patch(
                    "tools.ci.adversarial_review_session.subprocess.run",
                    return_value=completed,
                ):
                    with self.assertRaises(ReviewSessionError) as raised:
                        _run_fresh_codex_session(
                            "reviewer", {}, {}, executable="/fake/codex"
                        )
                self.assertIn("exit status 23", str(raised.exception))
                self.assertNotIn(raw, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
