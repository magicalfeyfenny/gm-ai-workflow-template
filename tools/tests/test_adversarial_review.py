import hashlib
import json
import subprocess
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
    validate_adjudication_result,
    validate_review_packet,
    validate_review_result,
)
from tools.ci.adversarial_review_state import (
    MAX_CORRECTION_CYCLES,
    review_loop_decision,
    stage2_evidence_current,
)
from tools.ci.adversarial_review_session import run_adversarial_review


REVISION = "a" * 64
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
        "body": "Acceptance criteria\nEngineering constraints\nValidation\n",
        "state": "OPEN",
        "work_blocked": False,
        "open_blocker_ids": [],
        "revision": REVISION,
    }


def candidate(head_sha: str = "h" * 40, diff: str = DIFF) -> dict:
    return {
        "base_ref": "origin/dev",
        "head_ref": "work/116-adversarial-review-adjudication",
        "head_sha": head_sha,
        "tree_sha": "t" * 40,
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
        "supporting_evidence": [f"evidence for {finding_id}"],
        "contract_or_governance": "accepted contract",
    }
    if location is not None:
        result["affected_location"] = location
    return result


def review_result(review_packet: dict, findings: list[dict]) -> dict:
    return {
        "schema": REVIEW_RESULT_SCHEMA,
        "candidate_identity": candidate_identity(review_packet["candidate"]),
        "findings": findings,
    }


def correction(location: str = INCLUDED[0]) -> dict:
    return {
        "summary": "Apply the supported current-pass correction.",
        "locations": [location],
        "validation": ["rerun the focused semantic tests"],
    }


def adjudication_result(
    adjudication_packet: dict,
    decisions: list[dict],
    *,
    handoff: bool = False,
    reason: str | None = None,
) -> dict:
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
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
    }


class ReviewPacketTests(unittest.TestCase):
    def test_packet_binds_contract_candidate_diff_and_stage2(self):
        value = packet()

        self.assertEqual(value["issue_contract"]["revision"], REVISION)
        self.assertEqual(value["candidate"]["diff_sha256"], DIFF_SHA)
        self.assertEqual(
            value["stage2_evidence"]["candidate_identity"],
            candidate_identity(value["candidate"]),
        )
        self.assertEqual(value["scope"]["exclusions"], ["readiness", "merge", "release"])

    def test_packet_rejects_stale_or_hidden_context(self):
        stale = packet()
        stale["stage2_evidence"]["issue_contract_revision"] = "b" * 64
        with self.assertRaises(ReviewContractError):
            validate_review_packet(stale)

        hidden = packet()
        hidden["implementation_context"] = "implementation scratchpad"
        with self.assertRaises(ReviewContractError):
            validate_review_packet(hidden)

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
            finding("F-blocker", "supported blocker", severity="low"),
            finding("F-patch", "bounded same-outcome improvement", severity="low"),
            finding("F-follow", "legitimate separate outcome", severity="critical"),
            finding("F-reject", "unsupported preference", severity="critical"),
        ]
        adjudication_packet = build_adjudication_packet(review_packet, findings)
        result = adjudication_result(
            adjudication_packet,
            [
                decision("F-blocker", "blocker", correction()),
                decision("F-patch", "patch-now", correction(INCLUDED[1])),
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

    def test_only_current_scope_corrections_can_change_candidate(self):
        review_packet = packet()
        findings = [finding("F1", "supported defect")]
        adjudication_packet = build_adjudication_packet(review_packet, findings)
        out_of_scope = adjudication_result(
            adjudication_packet,
            [decision("F1", "patch-now", correction("GOVERNANCE.md"))],
        )
        with self.assertRaises(ReviewContractError):
            validate_adjudication_result(out_of_scope, adjudication_packet)

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


class GovernanceBoundaryFixtureTests(unittest.TestCase):
    def test_real_motivating_cases_keep_severity_separate_from_disposition(self):
        review_packet = packet()
        cases = [
            finding(
                "F-python313",
                "Python 3.13+ concern is a bounded non-blocking improvement",
                severity="low",
            ),
            finding(
                "F-doc-example",
                "python3.12 documentation example is already satisfied",
                severity="high",
            ),
            finding(
                "F-temp-mock",
                "mocked temporary-environment path adds no defect beyond existing evidence",
                severity="critical",
            ),
            finding(
                "F-compat",
                "old representation must remain compatible without an independent consumer",
                severity="critical",
            ),
            finding(
                "F-manual",
                "manual visual observation should be added despite no contract requirement",
                severity="critical",
            ),
            finding(
                "F-unavailable",
                "unavailable environment capability proves candidate failure",
                severity="critical",
            ),
        ]
        adjudication_packet = build_adjudication_packet(review_packet, cases)
        result = adjudication_result(
            adjudication_packet,
            [
                decision("F-python313", "patch-now", correction()),
                decision("F-doc-example", "reject"),
                decision("F-temp-mock", "reject"),
                decision("F-compat", "reject"),
                decision("F-manual", "reject"),
                decision("F-unavailable", "reject"),
            ],
        )
        validated = validate_adjudication_result(result, adjudication_packet)
        self.assertEqual(validated["dispositions"][0]["disposition"], "patch-now")
        self.assertEqual(
            [item["disposition"] for item in validated["dispositions"][1:]],
            ["reject"] * 5,
        )


class ReviewLoopTests(unittest.TestCase):
    def _adjudication(self, disposition: str = "patch-now") -> tuple[dict, dict]:
        review_packet = packet()
        findings = [finding("F1", "supported current-pass correction")]
        adjudication_packet = build_adjudication_packet(review_packet, findings)
        return (
            adjudication_result(
                adjudication_packet,
                [decision("F1", disposition, correction() if disposition == "patch-now" else None)],
            ),
            adjudication_packet,
        )

    def test_unchanged_candidate_preserves_stage2_and_no_correction_completes(self):
        review_packet = packet()
        self.assertTrue(stage2_evidence_current(review_packet, review_packet["candidate"]))
        no_findings = build_adjudication_packet(review_packet, [])
        result = adjudication_result(no_findings, [])
        self.assertEqual(
            review_loop_decision(
                result, no_findings, cycle=0, candidate_changed=False,
            )["status"],
            "complete",
        )

    def test_accepted_correction_stales_old_stage2_and_requires_fresh_review(self):
        result, adjudication_packet = self._adjudication()
        changed = candidate(head_sha="g" * 40)
        self.assertFalse(stage2_evidence_current(packet(), changed))
        transition = review_loop_decision(
            result,
            adjudication_packet,
            cycle=0,
            candidate_changed=True,
            next_candidate=changed,
        )
        self.assertEqual(transition["status"], "revalidate-and-rereview")
        self.assertEqual(transition["cycle"], 1)
        self.assertEqual(transition["corrections"][0]["locations"], [INCLUDED[0]])

    def test_cycle_cap_and_oscillation_surface_human_handoff(self):
        result, adjudication_packet = self._adjudication()
        changed = candidate(head_sha="g" * 40)
        capped = review_loop_decision(
            result,
            adjudication_packet,
            cycle=MAX_CORRECTION_CYCLES,
            candidate_changed=True,
            next_candidate=changed,
        )
        self.assertEqual(capped["status"], "human-handoff")
        self.assertIn("cap", capped["reason"])

        oscillating = review_loop_decision(
            result,
            adjudication_packet,
            cycle=0,
            candidate_changed=True,
            next_candidate=changed,
            previous_candidates=[changed],
        )
        self.assertEqual(oscillating["status"], "human-handoff")
        self.assertIn("oscillat", oscillating["reason"])


class IsolatedSessionTests(unittest.TestCase):
    def test_orchestration_returns_only_adjudication_and_separates_packets(self):
        review_packet = packet()
        calls = []

        def fake_runner(role, payload, output_schema):
            calls.append((role, payload, output_schema))
            if role == "reviewer":
                return review_result(payload, [])
            adjudication_packet = payload
            return adjudication_result(adjudication_packet, [])

        result = run_adversarial_review(review_packet, session_runner=fake_runner)
        self.assertEqual([call[0] for call in calls], ["reviewer", "adjudicator"])
        self.assertIn("diff", calls[0][1]["candidate"])
        self.assertNotIn("candidate", calls[1][1])
        self.assertNotIn("findings", result)
        self.assertEqual(result["dispositions"], [])

    def test_default_runner_uses_two_fresh_read_only_packet_only_processes(self):
        review_packet = packet()
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            prompt = kwargs["input"]
            encoded = prompt.split("BOUNDARY-PACKET (JSON):\n", 1)[1]
            payload = json.loads(encoded)
            output_path = Path(command[command.index("--output-last-message") + 1])
            if "candidate" in payload:
                output = review_result(payload, [])
            else:
                output = adjudication_result(payload, [])
            output_path.write_text(json.dumps(output), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "tools.ci.adversarial_review_session.subprocess.run",
            side_effect=fake_run,
        ):
            result = run_adversarial_review(
                review_packet,
                codex_executable="/fake/codex",
            )

        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0][1]["cwd"], calls[1][1]["cwd"])
        for command, kwargs in calls:
            self.assertEqual(command[0], "/fake/codex")
            self.assertEqual(command[1], "exec")
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ignore-rules", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertEqual(command[command.index("--ask-for-approval") + 1], "never")
            self.assertNotIn("resume", command)
            self.assertNotIn("fork", command)
            self.assertNotIn("--worktree", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn(str(Path.cwd()), str(kwargs["cwd"]))
        self.assertNotIn("findings", result)


if __name__ == "__main__":
    unittest.main()
