"""Exercise issue-contract freshness at the existing low-risk merge boundary."""

import unittest
from copy import deepcopy

from tools.ci.low_risk_merge import MergeOutcome, run_low_risk_merge
from tools.tests.test_low_risk_merge import (
    FakeGitHub,
    PR_NUMBER,
    attestation_for,
    ci_context,
    pull_request_snapshot,
)
from tools.tests.test_pr_metadata import completion_body, issue_payload


class LowRiskIssueContractTests(unittest.TestCase):
    """Prove that unchanged PR metadata cannot hide a changed governing issue."""

    def test_issue_changes_before_ci_completes_or_during_file_fetch(self):
        """Each owned window requires the same accepted issue on both reads."""
        accepted = issue_payload(PR_NUMBER)
        changed = deepcopy(accepted)
        changed["body"] += "- Additional scope accepted after the old CI began.\n"
        current = pull_request_snapshot()
        for issues, file_reads in (([changed], 0), ([accepted, changed], 1)):
            with self.subTest(file_reads=file_reads):
                github = FakeGitHub(
                    [current], attestation=attestation_for(current), issues=issues
                )
                outcome = run_low_risk_merge(ci_context(), github)
                self.assertEqual(outcome.outcome, MergeOutcome.REJECTED)
                self.assertEqual(github.changed_files_calls, file_reads)
                self.assertEqual(github.issue_calls, file_reads + 1)
                self.assertEqual(github.ready_count, 0)
                self.assertEqual(github.configurations, [])

    def test_issue_change_after_readiness_requires_new_evidence(self):
        """Readiness never lets the initial issue read stand in for a fresh one."""
        accepted = issue_payload(PR_NUMBER)
        changed = deepcopy(accepted)
        changed["title"] = "The revised accepted outcome"
        draft = pull_request_snapshot(is_draft=True)
        ready = pull_request_snapshot()
        github = FakeGitHub(
            [draft, draft, ready],
            attestation=attestation_for(draft),
            issues=[accepted, accepted, changed],
        )
        outcome = run_low_risk_merge(ci_context(), github)
        self.assertEqual(outcome.outcome, MergeOutcome.REJECTED)
        self.assertEqual(github.ready_count, 1)
        self.assertEqual(github.issue_calls, 3)
        self.assertEqual(github.changed_files_calls, 1)
        self.assertEqual(github.configurations, [])

    def test_issue_drift_revokes_a_pending_request_for_attested_pr_metadata(self):
        """An installed request cannot survive a detected issue-contract change."""
        pending = pull_request_snapshot(auto_merge_request={"enabledAt": "earlier"})
        cleared = pull_request_snapshot()
        revised = issue_payload(PR_NUMBER)
        revised["body"] += "- Changed scope invalidates the pending request.\n"
        github = FakeGitHub(
            [pending, pending, cleared],
            attestation=attestation_for(pending),
            issues=[revised],
        )
        outcome = run_low_risk_merge(ci_context(), github)
        self.assertEqual(outcome.outcome, MergeOutcome.REJECTED)
        self.assertEqual(github.disabled_count, 1)
        self.assertEqual(github.configurations, [])

    def test_new_native_blocker_cannot_reuse_old_completion(self):
        """The native unresolved-blocker set participates in merge freshness."""
        current = pull_request_snapshot()
        blocked = issue_payload(PR_NUMBER)
        blocked["blockedBy"]["nodes"] = [{"id": "I_83", "state": "OPEN"}]
        github = FakeGitHub(
            [current], attestation=attestation_for(current), issues=[blocked]
        )
        outcome = run_low_risk_merge(ci_context(), github)
        self.assertEqual(outcome.outcome, MergeOutcome.REJECTED)
        self.assertEqual(github.configurations, [])
        self.assertEqual(github.ready_count, 0)

    def test_unavailable_or_incomplete_issue_reads_reject_completion(self):
        """A failed native read cannot be replaced with missing issue evidence."""
        current = pull_request_snapshot()
        incomplete = issue_payload(PR_NUMBER)
        incomplete["blockedBy"]["pageInfo"]["hasNextPage"] = True
        for issue in (None, {}, incomplete, RuntimeError("issue API unavailable")):
            for conclusion in ("success", "failure"):
                with self.subTest(issue=issue, conclusion=conclusion):
                    github = FakeGitHub(
                        [current],
                        attestation=attestation_for(current),
                        issues=[issue],
                    )
                    outcome = run_low_risk_merge(
                        ci_context(conclusion=conclusion), github
                    )
                    self.assertEqual(outcome.outcome, MergeOutcome.REJECTED)
                    self.assertEqual(github.ready_count, 0)
                    self.assertEqual(github.configurations, [])

    def test_refreshed_scope_passes_and_comments_do_not_stale_it(self):
        """Fresh accepted evidence allows an authorized revision to complete."""
        revised = issue_payload(PR_NUMBER)
        revised["body"] += "- Deliver the newly accepted scope.\n"
        current = pull_request_snapshot()
        current["body"] = completion_body(f"Closes #{PR_NUMBER}\n", revised)
        evidence = attestation_for(current, issue=revised)
        conversation = deepcopy(revised)
        conversation.update(comments={"totalCount": 12}, reactions={"totalCount": 3})
        github = FakeGitHub(
            [current], attestation=evidence, issues=[revised, conversation]
        )
        outcome = run_low_risk_merge(ci_context(), github)
        self.assertEqual(outcome.outcome, MergeOutcome.CONFIGURED)
        self.assertEqual(github.issue_calls, 2)
        self.assertEqual(len(github.configurations), 1)

    def test_stale_pr_metadata_does_not_read_or_mutate_newer_issue_state(self):
        """An older PR run cannot claim the current candidate via an API failure."""
        validated = pull_request_snapshot()
        newer = deepcopy(validated)
        newer["body"] += "Newer completion evidence description.\n"
        github = FakeGitHub(
            [newer],
            attestation=attestation_for(validated),
            issues=[RuntimeError("issue API unavailable")],
        )
        outcome = run_low_risk_merge(ci_context(), github)
        self.assertEqual(outcome.outcome, MergeOutcome.STALE)
        self.assertEqual(github.issue_calls, 0)
        self.assertEqual(github.disabled_count, 0)
        self.assertEqual(github.configurations, [])

    def test_partial_rerun_still_requires_the_current_issue_contract(self):
        """Earlier same-run artifacts retain their accepted issue revision."""
        current = pull_request_snapshot()
        revised = issue_payload(PR_NUMBER)
        revised["body"] += "\n"
        github = FakeGitHub(
            [current],
            attestation=attestation_for(current, run_attempt=1),
            attestation_attempt=1,
            issues=[revised],
        )
        outcome = run_low_risk_merge(ci_context(), github)
        self.assertEqual(outcome.outcome, MergeOutcome.REJECTED)
        self.assertEqual(github.configurations, [])


if __name__ == "__main__":
    unittest.main()
