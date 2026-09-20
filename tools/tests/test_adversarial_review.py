import hashlib
import json
import os
import re
import shutil
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
from tools.ci.adversarial_review_state import (
    MAX_CORRECTION_CYCLES,
    review_loop_decision,
    stage2_evidence_current,
)
from tools.ci.adversarial_review_session import run_adversarial_review


REVISION = "220cc0114ced1c521c25b5f26d3ec0a597469afb50429b1699615497fce0f372"
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
        "supporting_evidence": ["issue_contract.body"],
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
        "correction_accepted": value is not None,
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
        evidence = {item["evidence_id"]: item for item in value["evidence_catalog"]}
        self.assertEqual(evidence["candidate.diff"]["text"], DIFF)
        self.assertEqual(evidence["issue_contract.body"]["text"], issue_contract()["body"])

    def test_packet_rejects_stale_or_hidden_context(self):
        stale = packet()
        stale["stage2_evidence"]["issue_contract_revision"] = "b" * 64
        with self.assertRaises(ReviewContractError):
            validate_review_packet(stale)

        hidden = packet()
        hidden["implementation_context"] = "implementation scratchpad"
        with self.assertRaises(ReviewContractError):
            validate_review_packet(hidden)

        tampered_evidence = packet()
        tampered_evidence["evidence_catalog"][0]["text"] = "reviewer paraphrase"
        with self.assertRaisesRegex(ReviewContractError, "not derived"):
            validate_review_packet(tampered_evidence)

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
                "Python 3.13+ concern is a bounded same-outcome improvement",
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
        cases[0]["supporting_evidence"] = [
            "candidate.diff",
            "issue_contract.body",
        ]
        cases[1]["supporting_evidence"] = [
            "governance.0",
        ]
        cases[2]["supporting_evidence"] = [
            "scope.boundary",
        ]
        cases[3]["supporting_evidence"] = [
            "issue_contract.body",
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
                    "issue_contract",
                    "candidate_identity",
                    "applicable_governance",
                    "evidence",
                    "findings",
                    "scope",
                },
            )
            self.assertNotIn("candidate", payload)
            self.assertNotIn("diff", payload)
            source_items = payload["evidence"]["source_items"]
            self.assertTrue(source_items)
            self.assertTrue(all(item["text"].strip() for item in source_items))
            self.assertNotIn(
                "accepted invariant is absent from the candidate",
                [item["text"] for item in source_items],
            )
            decisions = []
            for item in payload["findings"]:
                evidence_ids = set(item["supporting_evidence"])
                if "candidate.diff" in evidence_ids:
                    disposition = "blocker"
                    value = correction()
                elif "governance.0" in evidence_ids:
                    disposition = "patch-now"
                    value = correction()
                elif "scope.boundary" in evidence_ids:
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
            ["blocker", "patch-now", "follow-up", "reject", "reject"],
        )
        self.assertEqual([call[0] for call in calls], ["reviewer", "adjudicator"])
        self.assertNotIn("findings", result)


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
        commit_only = candidate(head_sha="g" * 40)
        self.assertTrue(stage2_evidence_current(packet(), commit_only))
        changed = candidate(
            head_sha="g" * 40,
            diff=DIFF + "changed\n",
            tree_sha="u" * 40,
        )
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

    def test_changed_candidate_without_correction_cannot_complete(self):
        review_packet = packet()
        adjudication_packet = build_adjudication_packet(review_packet, [])
        result = adjudication_result(adjudication_packet, [])
        changed = candidate(head_sha="g" * 40, diff=DIFF + "changed\n")
        transition = review_loop_decision(
            result,
            adjudication_packet,
            cycle=0,
            candidate_changed=True,
            next_candidate=changed,
        )
        self.assertEqual(transition["status"], "human-handoff")
        self.assertIn("changed", transition["reason"])

    def test_content_oscillation_with_new_commit_identity_hands_off(self):
        original = candidate()
        middle = candidate(
            head_sha="g" * 40,
            diff=DIFF + "middle\n",
            tree_sha="u" * 40,
        )
        middle_stage2 = {
            "issue_contract_revision": REVISION,
            "candidate_identity": candidate_identity(middle),
            "checks": [
                {"name": "middle", "result": "passed", "evidence": ["middle"]}
            ],
        }
        middle_packet = build_review_packet(
            issue_contract(),
            middle,
            governance(),
            middle_stage2,
            {"included": INCLUDED, "exclusions": ["readiness"]},
        )
        adjudication_packet = build_adjudication_packet(
            middle_packet, [finding("F1", "supported correction")]
        )
        result = adjudication_result(
            adjudication_packet,
            [decision("F1", "patch-now", correction())],
        )
        revisited = candidate(head_sha="j" * 40)
        transition = review_loop_decision(
            result,
            adjudication_packet,
            cycle=1,
            candidate_changed=True,
            next_candidate=revisited,
            previous_candidates=[original],
        )
        self.assertEqual(transition["status"], "human-handoff")
        self.assertIn("oscillat", transition["reason"])

    def test_blocker_correction_runs_fresh_stage2_and_fresh_review(self):
        original_packet = packet()
        adjudication_packet = build_adjudication_packet(
            original_packet, [finding("F-blocker", "supported blocker")]
        )
        result = adjudication_result(
            adjudication_packet,
            [decision("F-blocker", "blocker", correction())],
        )
        corrected = candidate(head_sha="g" * 40, diff=DIFF + "corrected\n")
        transition = review_loop_decision(
            result,
            adjudication_packet,
            cycle=0,
            candidate_changed=True,
            next_candidate=corrected,
        )
        self.assertEqual(transition["status"], "revalidate-and-rereview")
        corrected_stage2 = {
            "issue_contract_revision": REVISION,
            "candidate_identity": candidate_identity(corrected),
            "checks": [
                {"name": "fresh Stage 2", "result": "passed", "evidence": ["fresh"]}
            ],
        }
        corrected_packet = build_review_packet(
            issue_contract(),
            corrected,
            governance(),
            corrected_stage2,
            {"included": INCLUDED, "exclusions": ["readiness", "merge", "release"]},
        )
        self.assertTrue(stage2_evidence_current(corrected_packet, corrected))
        calls = []

        def fake_runner(role, payload, output_schema):
            calls.append((role, payload, output_schema))
            if role == "reviewer":
                return review_result(payload, [])
            return adjudication_result(payload, [])

        final = run_adversarial_review(corrected_packet, session_runner=fake_runner)
        self.assertEqual([call[0] for call in calls], ["reviewer", "adjudicator"])
        self.assertIs(calls[0][2], REVIEW_RESULT_OUTPUT_SCHEMA)
        self.assertIs(calls[1][2], ADJUDICATION_RESULT_OUTPUT_SCHEMA)
        self.assertEqual(final["dispositions"], [])
        self.assertNotEqual(
            original_packet["candidate"]["head_sha"],
            corrected_packet["candidate"]["head_sha"],
        )

    def test_cycle_cap_and_oscillation_surface_human_handoff(self):
        result, adjudication_packet = self._adjudication()
        changed = candidate(
            head_sha="g" * 40,
            diff=DIFF + "changed\n",
            tree_sha="u" * 40,
        )
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
        ), patch(
            "tools.ci.adversarial_review_session._sandbox_path",
            return_value="/usr/bin/sandbox-exec",
        ):
            result = run_adversarial_review(
                review_packet,
                codex_executable="/fake/codex",
            )

        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0][1]["cwd"], calls[1][1]["cwd"])
        for command, kwargs in calls:
            self.assertEqual(command[0], "/usr/bin/sandbox-exec")
            self.assertEqual(command[1], "-f")
            self.assertEqual(command[3], "--")
            self.assertEqual(command[4], "/fake/codex")
            self.assertEqual(command[5], "exec")
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ignore-rules", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertNotIn("--ask-for-approval", command)
            self.assertNotIn("resume", command)
            self.assertNotIn("fork", command)
            self.assertNotIn("--worktree", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn(str(Path.cwd()), str(kwargs["cwd"]))
            self.assertEqual(
                set(kwargs["env"]) - {"PATH", "HOME", "TMPDIR", "CODEX_HOME", "LANG", "LC_CTYPE"},
                set(),
            )
        self.assertNotIn("findings", result)

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS Seatbelt")
    def test_real_subprocesses_cannot_read_external_sentinels(self):
        review_packet = packet()
        identity_json = json.dumps(candidate_identity(review_packet["candidate"]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider_root = root / "provider"
            sentinel_root = root / "sentinels"
            for path in (provider_root, sentinel_root): path.mkdir()
            external_sentinel = sentinel_root / "external.txt"
            repository_sentinel = Path.cwd() / "GOVERNANCE.md"
            implementation_sentinel = Path.cwd() / "tools/ci/adversarial_review.py"
            reviewer_sentinel = sentinel_root / "reviewer-artifact.txt"
            provider_sibling_sentinel = provider_root / "sibling-artifact.txt"
            for path in (external_sentinel, reviewer_sentinel, provider_sibling_sentinel):
                path.write_text("must remain unreadable", encoding="utf-8")
            executable = provider_root / "fake-codex"
            script = """#!/bin/bash
set -eu
    prompt=""
    while IFS= read -r line; do
        prompt="$prompt$line
"
    done
for sentinel in \
    "EXTERNAL_SENTINEL" \
    "REVIEWER_SENTINEL" \
    "PROVIDER_SIBLING_SENTINEL" \
    "REPOSITORY_SENTINEL" \
    "IMPLEMENTATION_SENTINEL"; do
    if [[ -r "$sentinel" ]]; then
        exit 91
    fi
done
set +u
parent_secret="$PARENT_SECRET"
set -u
[ -z "$parent_secret" ] || exit 92
case "$prompt" in
    *'"candidate":'*) role=reviewer ;;
    *) role=adjudicator ;;
esac
if [ "$role" = reviewer ]; then
    case "$prompt" in *'"evidence_catalog"'*) ;; *) exit 93 ;; esac
else
    case "$prompt" in *'"candidate":'*) exit 94 ;; esac
    case "$prompt" in *'"source_items"'*) ;; *) exit 95 ;; esac
fi
output=""
previous=""
for argument in "$@"; do
    if [ "$previous" = "--output-last-message" ]; then
        output="$argument"
    fi
    previous="$argument"
done
[ -n "$output" ]
cwd="$PWD"
record="role=$role;pid=$$;cwd=$cwd;sentinel=blocked;env=clean"
if [ "$role" = reviewer ]; then
    printf '%s\n' '{"schema":"adversarial-review-result:v2","candidate_identity":IDENTITY_JSON,"findings":[{"finding_id":"isolation-observation","severity":"low","defect_or_invariant":"isolation fixture observed no ambient access","supporting_evidence":["candidate.diff"],"contract_or_governance":"packet boundary","affected_location":null,"confidence":1,"uncertainty":"'"$record"'"}]}' > "$output"
else
    reviewer_record=""
    uncertainty_pattern='"uncertainty"[[:space:]]*:[[:space:]]*"([^"]*)"'
    if [[ "$prompt" =~ $uncertainty_pattern ]]; then
        reviewer_record="${BASH_REMATCH[1]}"
    fi
    record="$record;reviewer=$reviewer_record"
    printf '%s\n' '{"schema":"adversarial-adjudication-result:v2","candidate_identity":IDENTITY_JSON,"dispositions":[{"finding_id":"isolation-observation","disposition":"reject","basis":"fixture observation is not an implementation finding","correction":null,"correction_accepted":false}],"human_handoff":{"required":true,"reason":"'"$record"'"}}' > "$output"
fi
"""
            script = script.replace("EXTERNAL_SENTINEL", str(external_sentinel))
            script = script.replace("REVIEWER_SENTINEL", str(reviewer_sentinel))
            script = script.replace("PROVIDER_SIBLING_SENTINEL", str(provider_sibling_sentinel))
            script = script.replace("REPOSITORY_SENTINEL", str(repository_sentinel))
            script = script.replace("IMPLEMENTATION_SENTINEL", str(implementation_sentinel))
            script = script.replace("IDENTITY_JSON", identity_json)
            executable.write_text(script, encoding="utf-8")
            executable.chmod(0o755)
            with patch.dict(os.environ, {"PARENT_SECRET": "must-not-inherit"}):
                result = run_adversarial_review(
                    review_packet,
                    codex_executable=str(executable),
                )

        reason = result["human_handoff"]["reason"]
        self.assertIn("role=reviewer", reason)
        self.assertIn("role=adjudicator", reason)
        self.assertIn("sentinel=blocked", reason)
        self.assertIn("env=clean", reason)
        self.assertEqual(len(set(re.findall(r"pid=([0-9]+)", reason))), 2)
        self.assertEqual(len(set(re.findall(r"cwd=([^;]+)", reason))), 2)
        self.assertNotIn("findings", result)
