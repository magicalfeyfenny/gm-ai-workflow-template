import contextlib
import io
import json
import os
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import patch

from tools.ci.issue_contract import (
    ContractError,
    acceptance_marker,
    accepted_revision,
    canonical_contract,
    completion_contract,
    contract_digest,
    fetch_issue,
    governing_issue,
    main,
)

REPOSITORY = "owner/game"


def issue_payload(number: int = 15) -> dict:
    """Build complete native issue state without inferred empty connections."""
    return {
        "id": f"I_{number}",
        "number": number,
        "repository": {"nameWithOwner": REPOSITORY},
        "title": "Bind completion to its accepted issue contract",
        "body": "Acceptance criteria\n魔法 ◇\n",
        "state": "OPEN",
        "labels": {"nodes": [{"name": "risk:high"}], "pageInfo": {"hasNextPage": False}},
        "blockedBy": {"nodes": [], "pageInfo": {"hasNextPage": False}},
    }


def completed_state(issue: dict | None = None) -> dict:
    """Accept one issue revision before later observations can alter it."""
    issue = issue_payload() if issue is None else issue
    number = issue["number"]
    revision = contract_digest(canonical_contract(issue, REPOSITORY, number))
    return {
        "repository": REPOSITORY,
        "head_repository": REPOSITORY,
        "base_ref": "dev",
        "head_ref": f"work/{number}-bind-contract",
        "body": f"Closes #{number}\n\n{acceptance_marker(number, revision)}\n",
        "labels": ["risk:high", "work:review-ready"],
    }


def response(issue: object) -> subprocess.CompletedProcess:
    """Wrap an issue in the shape returned by the read-only GraphQL query."""
    return subprocess.CompletedProcess(
        ["gh"], 0, json.dumps({"data": {"repository": {"issue": issue}}}), "",
    )


class IssueContractTests(unittest.TestCase):
    def test_completion_matches_the_explicitly_accepted_revision(self):
        issue = issue_payload()
        state = completed_state(issue)
        revision = contract_digest(canonical_contract(issue, REPOSITORY, 15))
        self.assertEqual(governing_issue(state), 15)
        self.assertEqual(accepted_revision(state), revision)
        self.assertEqual(completion_contract(state, issue), {"number": 15, "sha256": revision})

    def test_milestones_and_human_work_do_not_require_issue_fetch_data(self):
        milestone = completed_state()
        milestone.update(body="Progress", labels=["risk:low"])
        human_label = completed_state()
        human_label.update(body="", labels=["human-created"])
        human_branch = completed_state()
        human_branch.update(head_ref="human/requested-change", body="")
        for state in (milestone, human_label, human_branch):
            with self.subTest(state=state):
                self.assertIsNone(governing_issue(state))
                self.assertIsNone(accepted_revision(state))
                self.assertIsNone(completion_contract(state, None))

    def test_milestone_marker_does_not_claim_completion(self):
        state = completed_state()
        state["body"] = acceptance_marker(15, "a" * 64)
        state["labels"] = ["risk:low"]
        self.assertIsNone(governing_issue(state))

    def test_release_branch_uses_its_own_issue(self):
        state = completed_state()
        state.update(base_ref="main", head_ref="release/15-v1.2.3-rc.1")
        self.assertEqual(governing_issue(state), 15)

    def test_inconsistent_completion_metadata_is_rejected(self):
        overrides = (
            {"labels": ["risk:low"]},
            {"labels": ["work:complete", "work:review-ready"]},
            {"labels": ["work:complete", "work:blocked"]},
            {"body": completed_state()["body"].replace("Closes #15", "Closes #16")},
            {"body": completed_state()["body"] + "Closes #15\n"},
            {"body": completed_state()["body"].replace("Closes #15", "Closes #abc")},
            {"body": completed_state()["body"].replace("Closes #15", "")},
            {"head_ref": "work/16-another-issue"},
            {"head_ref": "codex/unscoped"},
            {"base_ref": "unsupported"},
        )
        for override in overrides:
            with self.subTest(override=override):
                state = completed_state()
                state.update(override)
                with self.assertRaises(ContractError):
                    governing_issue(state)

    def test_missing_malformed_duplicate_or_wrong_issue_markers_are_rejected(self):
        valid = acceptance_marker(15, "a" * 64)
        markers = (
            "", valid + "\n" + valid,
            valid.replace("#15", "#16"),
            valid.replace("v1", "v2"),
            valid.replace("a" * 64, "A" * 64),
            valid.replace("a" * 64, "a" * 63),
            valid.replace("sha256:", "sha256: "),
            valid + "\n<!-- issue-contract:v1 malformed -->",
            valid + "\n<!--issue-contract:v2 malformed -->",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                state = completed_state()
                state["body"] = f"Closes #15\n\n{marker}\n"
                with self.assertRaises(ContractError):
                    governing_issue(state)

    def test_body_title_identity_and_eligibility_changes_invalidate_acceptance(self):
        mutations = (
            lambda issue: issue.update(title="New outcome"),
            lambda issue: issue.update(body=issue["body"] + "New acceptance criterion\n"),
            lambda issue: issue.update(body=issue["body"].rstrip()),
            lambda issue: issue.update(id="I_replaced"),
            lambda issue: issue.update(state="CLOSED"),
            lambda issue: issue["labels"]["nodes"].append({"name": "work:blocked"}),
            lambda issue: issue["blockedBy"]["nodes"].append({"id": "I_99", "state": "OPEN"}),
        )
        original = issue_payload()
        state = completed_state(original)
        for mutate in mutations:
            current = deepcopy(original)
            mutate(current)
            with self.subTest(current=current), self.assertRaises(ContractError):
                completion_contract(state, current)

    def test_rerunning_snapshot_does_not_silently_accept_changed_scope(self):
        original = issue_payload()
        state = completed_state(original)
        changed = deepcopy(original)
        changed["body"] += "Additional work\n"
        with patch("tools.ci.issue_contract._run_gh", return_value=response(changed)):
            fetched = fetch_issue(REPOSITORY, 15)
        with self.assertRaisesRegex(ContractError, "re-evaluate Stage 2"):
            completion_contract(state, fetched)
        state = completed_state(changed)
        self.assertIsNotNone(completion_contract(state, fetched))

    def test_activity_and_nonblocking_metadata_do_not_change_the_contract(self):
        original = issue_payload()
        state = completed_state(original)
        current = deepcopy(original)
        current.update(updatedAt="2026-09-09T00:00:00Z", comments=[{"body": "Thanks"}], reactions=[])
        current["labels"]["nodes"] = [{"name": "triage:discuss"}, {"name": "risk:low"}]
        current["blockedBy"]["nodes"] = [{"id": "I_12", "state": "CLOSED"}]
        self.assertEqual(completion_contract(state, current), completion_contract(state, original))

    def test_unresolved_blockers_use_identity_and_stable_set_order(self):
        original = issue_payload()
        original["blockedBy"]["nodes"] = [
            {"id": "I_2", "state": "OPEN"}, {"id": "I_1", "state": "OPEN"},
            {"id": "I_resolved", "state": "CLOSED"},
        ]
        current = deepcopy(original)
        current["blockedBy"]["nodes"].reverse()
        first = canonical_contract(original, REPOSITORY, 15)
        second = canonical_contract(current, REPOSITORY, 15)
        self.assertEqual(first["open_blocker_ids"], ["I_1", "I_2"])
        self.assertEqual(contract_digest(first), contract_digest(second))
        current["blockedBy"]["nodes"][1]["state"] = "CLOSED"
        self.assertNotEqual(contract_digest(first), contract_digest(canonical_contract(current, REPOSITORY, 15)))

    def test_closed_or_blocked_issues_cannot_be_completed_even_when_marker_matches(self):
        for mutate in (
            lambda issue: issue.update(state="CLOSED"),
            lambda issue: issue["labels"]["nodes"].append({"name": "work:blocked"}),
            lambda issue: issue["blockedBy"]["nodes"].append({"id": "I_1", "state": "OPEN"}),
        ):
            issue = issue_payload()
            mutate(issue)
            with self.subTest(issue=issue), self.assertRaises(ContractError):
                completion_contract(completed_state(issue), issue)

    def test_missing_null_or_unknown_contract_fields_fail_closed(self):
        for field in ("id", "number", "repository", "title", "body", "state", "labels", "blockedBy"):
            for remove in (True, False):
                issue = issue_payload()
                if remove:
                    del issue[field]
                else:
                    issue[field] = None
                with self.subTest(field=field, remove=remove), self.assertRaises(ContractError):
                    canonical_contract(issue, REPOSITORY, 15)
        for value in ("MERGED", "open", "", 1, True):
            issue = issue_payload()
            issue["state"] = value
            with self.subTest(state=value), self.assertRaises(ContractError):
                canonical_contract(issue, REPOSITORY, 15)

    def test_wrong_repository_number_and_boolean_number_fail_closed(self):
        for repository, number in (("elsewhere/game", 15), (REPOSITORY, 16), (REPOSITORY, True)):
            with self.subTest(repository=repository, number=number), self.assertRaises(ContractError):
                canonical_contract(issue_payload(), repository, number)

    def test_connections_require_complete_explicit_pagination(self):
        for field in ("labels", "blockedBy"):
            for connection in (
                {}, {"nodes": []}, {"nodes": [], "pageInfo": {}},
                {"nodes": [], "pageInfo": {"hasNextPage": None}},
                {"nodes": [], "pageInfo": {"hasNextPage": "false"}},
                {"nodes": [], "pageInfo": {"hasNextPage": True}},
                {"nodes": None, "pageInfo": {"hasNextPage": False}},
            ):
                issue = issue_payload()
                issue[field] = connection
                with self.subTest(field=field, connection=connection), self.assertRaises(ContractError):
                    canonical_contract(issue, REPOSITORY, 15)

    def test_duplicate_or_incomplete_native_nodes_fail_closed(self):
        cases = (
            ("labels", [{"name": "work:blocked"}, {"name": "work:blocked"}]),
            ("labels", [{"name": None}]),
            ("blockedBy", [{"id": "I_1", "state": "OPEN"}, {"id": "I_1", "state": "CLOSED"}]),
            ("blockedBy", [{"id": "I_1"}]),
            ("blockedBy", [{"state": "OPEN"}]),
            ("blockedBy", [{"id": "I_1", "state": "MERGED"}]),
            ("blockedBy", [None]),
        )
        for field, nodes in cases:
            issue = issue_payload()
            issue[field]["nodes"] = nodes
            with self.subTest(field=field, nodes=nodes), self.assertRaises(ContractError):
                canonical_contract(issue, REPOSITORY, 15)


class IssueContractFetchTests(unittest.TestCase):
    def test_fetch_preserves_contract_and_uses_read_only_query(self):
        issue = issue_payload()
        with patch("tools.ci.issue_contract._run_gh", return_value=response(issue)) as runner:
            fetched = fetch_issue(REPOSITORY, 15)
        self.assertEqual(canonical_contract(fetched, REPOSITORY, 15), canonical_contract(issue, REPOSITORY, 15))
        arguments = runner.call_args.args[0]
        self.assertEqual(arguments[:2], ["api", "graphql"])
        self.assertIn("number=15", arguments)
        self.assertNotIn("mutation", " ".join(arguments))

    def test_paginated_labels_and_native_blockers_are_both_complete(self):
        first = issue_payload()
        first["labels"]["pageInfo"] = {"hasNextPage": True, "endCursor": "label-1"}
        first["blockedBy"] = {
            "nodes": [{"id": "I_1", "state": "CLOSED"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "blocker-1"},
        }
        second = issue_payload()
        second["labels"]["nodes"] = [{"name": "work:blocked"}]
        second["blockedBy"] = {
            "nodes": [{"id": "I_2", "state": "OPEN"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "blocker-2"},
        }
        third = issue_payload()
        del third["labels"]
        third["blockedBy"]["nodes"] = [{"id": "I_3", "state": "OPEN"}]
        with patch("tools.ci.issue_contract._run_gh", side_effect=[response(page) for page in (first, second, third)]) as runner:
            fetched = fetch_issue(REPOSITORY, 15)
        contract = canonical_contract(fetched, REPOSITORY, 15)
        self.assertTrue(contract["work_blocked"])
        self.assertEqual(contract["open_blocker_ids"], ["I_2", "I_3"])
        self.assertEqual(runner.call_count, 3)
        self.assertIn("labels_after=label-1", runner.call_args_list[1].args[0])
        self.assertIn("blockers_after=blocker-1", runner.call_args_list[1].args[0])
        self.assertIn("fetch_labels=false", runner.call_args_list[2].args[0])
        self.assertIn("blockers_after=blocker-2", runner.call_args_list[2].args[0])

    def test_partial_errors_unavailable_issue_and_malformed_responses_fail_closed(self):
        partial = {"data": {"repository": {"issue": issue_payload()}}, "errors": [{"message": "partial"}]}
        outputs = (
            "invalid JSON", "null", "[]", "{}", json.dumps(partial),
            json.dumps({"data": None}), json.dumps({"data": {"repository": None}}),
            response(None).stdout,
        )
        for output in outputs:
            result = subprocess.CompletedProcess(["gh"], 0, output, "")
            with self.subTest(output=output), self.assertRaises(ContractError):
                fetch_issue(REPOSITORY, 15, lambda arguments: result)

    def test_cli_errors_are_contract_errors(self):
        result = subprocess.CompletedProcess(["gh"], 1, "", "unavailable")
        with self.assertRaises(ContractError):
            fetch_issue(REPOSITORY, 15, lambda arguments: result)
        with patch("tools.ci.issue_contract._run_gh", side_effect=RuntimeError("denied")):
            with self.assertRaises(ContractError):
                fetch_issue(REPOSITORY, 15)

    def test_pagination_missing_cursor_repeated_cursor_and_changed_content_fail_closed(self):
        first = issue_payload()
        first["blockedBy"]["pageInfo"] = {"hasNextPage": True, "endCursor": "cursor-1"}
        missing_cursor = deepcopy(first)
        del missing_cursor["blockedBy"]["pageInfo"]["endCursor"]
        changed = issue_payload()
        changed["body"] += "New acceptance scope"
        for pages in ((missing_cursor,), (first, first), (first, changed)):
            with self.subTest(pages=pages):
                with patch("tools.ci.issue_contract._run_gh", side_effect=[response(page) for page in pages]):
                    with self.assertRaises(ContractError):
                        fetch_issue(REPOSITORY, 15)

    def test_duplicates_across_pages_fail_closed(self):
        first = issue_payload()
        first["blockedBy"] = {
            "nodes": [{"id": "I_1", "state": "CLOSED"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
        }
        second = issue_payload()
        del second["labels"]
        second["blockedBy"]["nodes"] = [{"id": "I_1", "state": "OPEN"}]
        with patch("tools.ci.issue_contract._run_gh", side_effect=[response(first), response(second)]):
            with self.assertRaisesRegex(ContractError, "duplicate IDs"):
                fetch_issue(REPOSITORY, 15)

    def test_default_fetch_removes_merge_token_from_subprocess_environment(self):
        with patch.dict(os.environ, {"MERGE_TOKEN": "scoped-secret", "GH_TOKEN": "read-token"}):
            with patch("tools.ci.issue_contract.subprocess.run", return_value=response(issue_payload())) as runner:
                fetch_issue(REPOSITORY, 15)
        environment = runner.call_args.kwargs["env"]
        self.assertNotIn("MERGE_TOKEN", environment)
        self.assertEqual(environment["GH_TOKEN"], "read-token")

    def test_cli_prints_contract_digest_and_copyable_acceptance_marker(self):
        output = io.StringIO()
        with patch("tools.ci.issue_contract.fetch_issue", return_value=issue_payload()):
            with contextlib.redirect_stdout(output):
                status = main(["--repository", REPOSITORY, "--issue-number", "15"])
        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(result["sha256"], contract_digest(result["contract"]))
        self.assertEqual(result["acceptance_marker"], acceptance_marker(15, result["sha256"]))

    def test_cli_returns_failure_without_a_marker_when_issue_fetch_is_incomplete(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("tools.ci.issue_contract.fetch_issue", side_effect=ContractError("incomplete")):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = main(["--repository", REPOSITORY, "--issue-number", "15"])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("incomplete", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
