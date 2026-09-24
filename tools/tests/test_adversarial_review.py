import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.adversarial_review import (
    ADJUDICATION_RESULT_OUTPUT_SCHEMA,
    ADJUDICATION_RESULT_SCHEMA,
    REVIEW_RESULT_OUTPUT_SCHEMA,
    REVIEW_RESULT_SCHEMA,
    ReviewContractError,
    build_adjudication_packet,
    build_review_packet,
    candidate_identity,
    validate_adjudication_result,
    validate_review_packet,
    validate_review_result,
)
from tools.ci.adversarial_review_session import (
    run_adversarial_review,
    run_review_lifecycle,
)


REVISION = "568b72bd89a4cdbbc5be6f86e9cce4d976422b599d7e19b69c1ed0dd4c655daa"
DIFF = "diff --git a/tools/ci/adversarial_review.py b/tools/ci/adversarial_review.py\n"
DIFF_SHA = hashlib.sha256(DIFF.encode("utf-8")).hexdigest()
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
        "body": "## Acceptance criteria\n- Preserve invariant A in the completed outcome.\n",
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


def stage2(value: dict | None = None) -> dict:
    current = candidate()
    return {
        "issue_contract_revision": REVISION,
        "candidate_identity": candidate_identity(current),
        "checks": [
            {"name": "repository policy", "result": "passed", "evidence": ["policy"]},
            {"name": "full Python suite", "result": "passed", "evidence": ["tests"]},
            {"name": "diff check", "result": "passed", "evidence": ["whitespace"]},
        ],
    } if value is None else value


def governance() -> dict:
    return {
        "sources": [
            {
                "path": "GOVERNANCE.md",
                "section": "Adversarial review and adjudication",
                "text": "Review is read-only and bounded by the accepted contract.",
            },
        ],
        "review_doctrine": (
            "Use independent evidence. Do not infer compatibility or manual "
            "validation obligations."
        ),
    }


def packet() -> dict:
    return build_review_packet(
        issue_contract(),
        candidate(),
        governance(),
        stage2(),
        {"included": INCLUDED, "exclusions": ["readiness", "merge", "release"]},
        risk="high",
    )


def finding(
    finding_id: str,
    claim: str,
    *,
    severity: str = "medium",
    location: str | None = INCLUDED[0],
) -> dict:
    result = {
        "finding_id": finding_id,
        "severity": severity,
        "defect_or_invariant": claim,
        "supporting_evidence": ["issue_contract"],
        "contract_or_governance": "Issue #116 acceptance criterion: preserve invariant A",
    }
    if location is not None:
        result["affected_location"] = location
    return result


def review_result(review_packet: dict, findings: list[dict]) -> dict:
    return {
        "schema": REVIEW_RESULT_SCHEMA,
        "issue_contract_revision": review_packet["issue_contract"]["revision"],
        "candidate_identity": candidate_identity(review_packet["candidate"]),
        "findings": findings,
    }


def correction() -> dict:
    return {"summary": "Apply the supported current-pass correction."}


def adjudication_result(
    adjudication_packet: dict,
    decisions: list[dict],
    *,
    handoff: bool = False,
    reason: str | None = None,
) -> dict:
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
        "issue_contract_revision": adjudication_packet["issue_contract_revision"],
        "candidate_identity": adjudication_packet["candidate_identity"],
        "dispositions": decisions,
        "human_handoff": {"required": handoff, "reason": reason},
    }


def decision(finding_id: str, disposition: str, value: dict | None = None) -> dict:
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "basis": f"supported basis for {finding_id}",
        "correction": value,
        "correction_accepted": value is not None,
    }


class ReviewPacketTests(unittest.TestCase):
    def test_packet_binds_contract_candidate_diff_and_stage2(self):
        value = packet()

        self.assertEqual(value["issue_contract"]["revision"], REVISION)
        self.assertEqual(value["risk"], "high")
        self.assertEqual(value["candidate"]["diff_sha256"], DIFF_SHA)
        self.assertEqual(
            value["stage2_evidence"]["candidate_identity"],
            candidate_identity(value["candidate"]),
        )
        self.assertEqual(value["scope"]["exclusions"], ["readiness", "merge", "release"])
        self.assertEqual(value["issue_contract"]["evidence_id"], "issue_contract")
        self.assertEqual(value["candidate"]["evidence_id"], "candidate")
        self.assertEqual(
            value["applicable_governance"]["sources"][0]["evidence_id"],
            "governance.0",
        )
        self.assertEqual(
            value["applicable_governance"]["review_doctrine_evidence_id"],
            "governance.doctrine",
        )
        self.assertNotIn("evidence_catalog", value)
        encoded = json.dumps(value)
        self.assertEqual(encoded.count(json.dumps(DIFF)), 1)
        self.assertEqual(encoded.count(json.dumps(issue_contract()["body"])), 1)

    def test_packet_rejects_stale_or_hidden_context(self):
        stale = packet()
        stale["stage2_evidence"]["issue_contract_revision"] = "b" * 64
        with self.assertRaises(ReviewContractError):
            validate_review_packet(stale)

        hidden = packet()
        hidden["implementation_context"] = "implementation scratchpad"
        with self.assertRaises(ReviewContractError):
            validate_review_packet(hidden)

        invalid_risk = packet()
        invalid_risk["risk"] = "important"
        with self.assertRaises(ReviewContractError):
            validate_review_packet(invalid_risk)

        tampered_source = packet()
        tampered_source["candidate"]["evidence_id"] = "reviewer.paraphrase"
        with self.assertRaisesRegex(ReviewContractError, "evidence ID"):
            validate_review_packet(tampered_source)

    def test_packet_rejects_candidate_diff_mismatch_and_non_open_contract(self):
        broken_candidate = packet()
        broken_candidate["candidate"]["diff"] = "different"
        with self.assertRaises(ReviewContractError):
            validate_review_packet(broken_candidate)

        closed = issue_contract()
        closed["state"] = "CLOSED"
        with self.assertRaises(ReviewContractError):
            build_review_packet(
                closed, candidate(), governance(), stage2(),
                {"included": INCLUDED, "exclusions": []},
                risk="high",
            )


class FindingAndDispositionTests(unittest.TestCase):
    def test_findings_are_structured_and_candidate_bound(self):
        review_packet = packet()
        finding_value = finding("F1", "a supported defect", severity="low")
        validated = validate_review_result(
            review_result(review_packet, [finding_value]), review_packet,
        )
        self.assertEqual(validated["findings"][0]["finding_id"], "F1")
        self.assertEqual(validated["findings"][0]["severity"], "low")

        invalid = review_result(review_packet, [finding_value])
        invalid["findings"][0]["instruction"] = "change the code"
        with self.assertRaises(ReviewContractError):
            validate_review_result(invalid, review_packet)

        wrong_candidate = review_result(review_packet, [])
        wrong_candidate["candidate_identity"]["head_sha"] = "z" * 40
        with self.assertRaises(ReviewContractError):
            validate_review_result(wrong_candidate, review_packet)

    def test_each_finding_receives_exactly_one_disposition(self):
        review_packet = packet()
        findings = [
            finding("F-blocker", "candidate omits accepted invariant A", severity="low"),
            finding(
                "F-patch",
                "candidate violates accepted invariant A with a bounded remedy",
                severity="low",
            ),
            finding("F-follow", "legitimate separate outcome", severity="critical"),
            finding("F-reject", "unsupported preference", severity="critical"),
        ]
        adjudication_packet = build_adjudication_packet(review_packet, findings)
        result = adjudication_result(
            adjudication_packet,
            [
                decision("F-blocker", "blocker", correction()),
                decision("F-patch", "patch-now", correction()),
                decision("F-follow", "follow-up"),
                decision("F-reject", "reject"),
            ],
        )
        validated = validate_adjudication_result(result, adjudication_packet)
        self.assertEqual(
            [item["disposition"] for item in validated["dispositions"]],
            ["blocker", "patch-now", "follow-up", "reject"],
        )

        missing = dict(result)
        missing["dispositions"] = result["dispositions"][:-1]
        with self.assertRaises(ReviewContractError):
            validate_adjudication_result(missing, adjudication_packet)

    def test_correction_remedy_has_no_path_authority(self):
        review_packet = packet()
        findings = [finding("F1", "supported defect")]
        adjudication_packet = build_adjudication_packet(review_packet, findings)
        no_path_limit = adjudication_result(
            adjudication_packet,
            [decision("F1", "patch-now", correction())],
        )
        validated = validate_adjudication_result(no_path_limit, adjudication_packet)
        self.assertEqual(
            validated["dispositions"][0]["correction"], correction()
        )

        forbidden_for_reject = adjudication_result(
            adjudication_packet,
            [decision("F1", "reject", correction())],
        )
        with self.assertRaises(ReviewContractError):
            validate_adjudication_result(forbidden_for_reject, adjudication_packet)

    def test_unresolved_blocker_requires_human_handoff(self):
        review_packet = packet()
        adjudication_packet = build_adjudication_packet(
            review_packet, [finding("F1", "supported blocker")]
        )
        result = adjudication_result(
            adjudication_packet,
            [decision("F1", "blocker")],
            handoff=True,
            reason="the correction is disputed",
        )
        self.assertTrue(validate_adjudication_result(result, adjudication_packet)["human_handoff"]["required"])


class EvidenceTransportTests(unittest.TestCase):
    def test_packet_transport_fixture_keeps_source_items_separate(self):
        review_packet = packet()
        cases = [
            finding(
                "F-blocker",
                "candidate violates an accepted required invariant",
                severity="medium",
            ),
            finding(
                "F-python313",
                "separately actionable Python 3.13+ concern is outside this issue",
                severity="low",
            ),
            finding(
                "F-follow-up",
                "separately meaningful concern is outside accepted outcome",
                severity="critical",
            ),
            finding(
                "F-doc-example",
                "python3.12 documentation example is already satisfied",
                severity="high",
            ),
            finding(
                "F-compat",
                "compatibility requested without independent compatibility evidence",
                severity="critical",
            ),
        ]
        cases[1]["contract_or_governance"] = (
            "No accepted issue requirement or Governance rule is identified"
        )
        cases[2]["contract_or_governance"] = (
            "No accepted issue requirement or Governance rule is identified"
        )
        cases[0]["supporting_evidence"] = [
            "candidate",
            "issue_contract",
        ]
        cases[1]["supporting_evidence"] = [
            "governance.0",
        ]
        cases[2]["supporting_evidence"] = [
            "scope",
        ]
        cases[3]["supporting_evidence"] = [
            "issue_contract",
        ]
        cases[4]["supporting_evidence"] = [
            "governance.doctrine",
        ]
        calls = []

        def evidence_runner(role, payload, output_schema):
            calls.append((role, payload, output_schema))
            if role == "reviewer":
                return review_result(payload, cases)
            self.assertEqual(
                set(payload),
                {
                    "schema",
                    "issue_contract_revision",
                    "candidate_identity",
                    "evidence",
                    "findings",
                },
            )
            source_items = payload["evidence"]["source_items"]
            self.assertTrue(source_items)
            self.assertTrue(all(item["text"].strip() for item in source_items))
            self.assertEqual(
                {item["evidence_id"] for item in source_items},
                {
                    evidence_id
                    for finding_item in cases
                    for evidence_id in finding_item["supporting_evidence"]
                },
            )
            self.assertNotIn(
                "accepted invariant is absent from the candidate",
                [item["text"] for item in source_items],
            )
            decisions = []
            for item in payload["findings"]:
                evidence_ids = set(item["supporting_evidence"])
                if "candidate" in evidence_ids:
                    disposition = "blocker"
                    value = correction()
                elif "governance.0" in evidence_ids:
                    disposition = "follow-up"
                    value = None
                elif "scope" in evidence_ids:
                    disposition = "follow-up"
                    value = None
                else:
                    disposition = "reject"
                    value = None
                decisions.append(decision(item["finding_id"], disposition, value))
            return adjudication_result(payload, decisions)

        result = run_adversarial_review(review_packet, session_runner=evidence_runner)
        self.assertEqual(
            [item["disposition"] for item in result["dispositions"]],
            ["blocker", "follow-up", "follow-up", "reject", "reject"],
        )
        self.assertEqual([call[0] for call in calls], ["reviewer", "adjudicator"])
        self.assertNotIn("findings", result)


class ZeroFindingLifecycleTests(unittest.TestCase):
    def test_zero_findings_finish_without_an_adjudicator_session(self):
        calls = []

        def runner(role, payload, output_schema):
            calls.append(role)
            return review_result(payload, [])

        result = run_review_lifecycle(packet(), initial=True, session_runner=runner)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls, ["reviewer"])


class IsolatedSessionTests(unittest.TestCase):
    def test_orchestration_adjudicates_findings_in_a_separate_packet(self):
        review_packet = packet()
        calls = []

        def fake_runner(role, payload, output_schema):
            calls.append((role, payload, output_schema))
            if role == "reviewer":
                return review_result(
                    payload, [finding("F-session", "supported by the issue source")]
                )
            adjudication_packet = payload
            return adjudication_result(
                adjudication_packet, [decision("F-session", "reject")]
            )

        result = run_adversarial_review(review_packet, session_runner=fake_runner)
        self.assertEqual([call[0] for call in calls], ["reviewer", "adjudicator"])
        self.assertEqual(result["dispositions"][0]["finding_id"], "F-session")
        self.assertIn("diff", calls[0][1]["candidate"])
        self.assertNotIn("candidate", calls[1][1])
        self.assertEqual(
            set(calls[1][1]),
            {
                "schema",
                "issue_contract_revision",
                "candidate_identity",
                "evidence",
                "findings",
            },
        )
        self.assertNotIn("findings", result)

    def test_default_runner_uses_two_fresh_read_only_codex_invocations(self):
        review_packet = packet()
        calls = []

        def fake_process(command, **kwargs):
            calls.append((command, kwargs))
            prompt = kwargs["input"]
            encoded = prompt.split("BOUNDARY-PACKET (JSON):\n", 1)[1]
            payload = json.loads(encoded)
            output_path = Path(command[command.index("--output-last-message") + 1])
            if "candidate" in payload:
                output = review_result(
                    payload, [finding("F-fresh", "supported by the issue source")]
                )
            else:
                output = adjudication_result(
                    payload, [decision("F-fresh", "reject")]
                )
            output_path.write_text(json.dumps(output), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with patch.dict(os.environ, {"PARENT_SECRET": "must-not-inherit"}), patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=fake_process,
        ):
            result = run_adversarial_review(
                review_packet,
                codex_executable="/fake/codex",
            )

        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0][1]["cwd"], calls[1][1]["cwd"])
        for command, kwargs in calls:
            self.assertEqual(command[:2], ["/fake/codex", "exec"])
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ignore-rules", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertNotIn("--json", command)
            self.assertNotIn("resume", command)
            self.assertNotIn("fork", command)
            self.assertNotIn("--worktree", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            self.assertNotIn("PARENT_SECRET", kwargs["env"])
            self.assertIn("PACKET TRUST BOUNDARY", kwargs["input"])
        output_paths = [
            Path(command[command.index("--output-last-message") + 1])
            for command, _ in calls
        ]
        self.assertEqual(len(set(output_paths)), 2)
        self.assertTrue(all(not path.exists() for path in output_paths))
        self.assertTrue(all(not Path(kwargs["cwd"]).exists() for _, kwargs in calls))
        self.assertNotIn("findings", result)
