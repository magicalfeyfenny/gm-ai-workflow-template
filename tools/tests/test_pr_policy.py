import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.ci.pr_policy import (
    auto_merge_eligible,
    branch_issue,
    changed_file_paths,
    completion_policy_errors,
    forced_high_risk,
    is_human_created,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]


class PrPolicyTests(unittest.TestCase):
    def test_work_branch(self):
        issue, errors = branch_issue(
            "dev",
            "work/12-stage-editor",
        )

        self.assertEqual(issue, 12)
        self.assertEqual(errors, [])

    def test_invalid_work_branch(self):
        issue, errors = branch_issue(
            "dev",
            "feature/stage-editor",
        )

        self.assertIsNone(issue)
        self.assertTrue(errors)

    def test_release_branch(self):
        issue, errors = branch_issue(
            "main",
            "release/27-v1.0.0",
        )

        self.assertEqual(issue, 27)
        self.assertEqual(errors, [])

    def test_sensitive_path_is_high_risk(self):
        high, reasons = forced_high_risk(
            "dev",
            [".github/workflows/ci.yml"],
            1,
            1,
        )

        self.assertTrue(high)
        self.assertTrue(reasons)

    def test_project_sensitive_paths_are_high_risk(self):
        """Keep governance and core project paths on the high-risk path."""
        paths = [
            "AGENTS.md",
            "GOVERNANCE.md",
            "PROJECT_POLICY.toml",
            ".agents/skills/gamemaker-production/SKILL.md",
            ".agents/skills/governed-change/SKILL.md",
            ".agents/skills/project-steward/SKILL.md",
            "project/game.yyp",
            "project/options/main/options_main.yy",
            "project/extensions/store/store.yy",
            "project/scripts/core/state.gml",
            "project/scripts/save/write_save.gml",
            "project/scripts/persistence/profile.gml",
            "project/scripts/migrations/save_v2.gml",
        ]

        for path in paths:
            with self.subTest(path=path):
                high, reasons = forced_high_risk(
                    "dev",
                    [path],
                    1,
                    0,
                )

                self.assertTrue(high)
                self.assertTrue(reasons)

    def test_small_game_change_can_be_low_risk(self):
        high, reasons = forced_high_risk(
            "dev",
            ["project/scripts/player/player.gml"],
            20,
            10,
        )

        self.assertFalse(high)
        self.assertEqual(reasons, [])

    def test_main_is_high_risk(self):
        high, reasons = forced_high_risk(
            "main",
            ["README.md"],
            1,
            1,
        )

        self.assertTrue(high)
        self.assertIn(
            "PR targets main",
            reasons,
        )

    def test_human_branch_requires_same_repository(self):
        self.assertTrue(
            is_human_created(
                "human/combat-prototype",
                set(),
                "owner/game",
                "owner/game",
            )
        )
        self.assertFalse(
            is_human_created(
                "human/combat-prototype",
                set(),
                "fork/game",
                "owner/game",
            )
        )

    def test_human_label_is_authoritative(self):
        self.assertTrue(
            is_human_created(
                "experiment/combat",
                {"human-created"},
                "fork/game",
                "owner/game",
            )
        )

    def test_human_created_bypasses_policy_but_not_manual_merge(self):
        environment = {
            "PR_HEAD": "human/combat-prototype",
            "PR_HEAD_REPOSITORY": "owner/game",
            "PR_REPOSITORY": "owner/game",
        }

        expectations = {
            False: "PR policy bypassed: human-created",
            True: "false",
        }

        for auto_eligible, expected in expectations.items():
            with self.subTest(auto_eligible=auto_eligible):
                output = io.StringIO()

                with (
                    patch.dict(os.environ, environment, clear=True),
                    redirect_stdout(output),
                ):
                    result = validate(auto_eligible)

                self.assertEqual(result, 0)
                self.assertEqual(output.getvalue().strip(), expected)

    def test_auto_merge_requires_completed_low_risk_work(self):
        complete = {
            "risk:low",
            "work:complete",
        }

        self.assertTrue(
            auto_merge_eligible("dev", False, complete)
        )
        self.assertFalse(
            auto_merge_eligible("dev", False, {"risk:low"})
        )
        self.assertFalse(
            auto_merge_eligible(
                "dev",
                False,
                complete | {"manual-merge"},
            )
        )
        self.assertFalse(
            auto_merge_eligible("dev", True, complete)
        )
        self.assertFalse(
            auto_merge_eligible("main", False, complete)
        )
        self.assertFalse(
            auto_merge_eligible(
                "dev",
                False,
                complete | {"work:blocked"},
            )
        )

    def test_closing_line_is_completion_only(self):
        self.assertEqual(
            completion_policy_errors(
                12,
                {"risk:low"},
                [],
                False,
            ),
            [],
        )
        self.assertIn(
            "Closes #<issue> is allowed only when work is complete",
            completion_policy_errors(
                12,
                {"risk:low"},
                ["12"],
                False,
            ),
        )

    def test_completion_label_matches_merge_path(self):
        self.assertEqual(
            completion_policy_errors(
                12,
                {"risk:low", "work:complete"},
                ["12"],
                False,
            ),
            [],
        )
        self.assertEqual(
            completion_policy_errors(
                12,
                {"risk:high", "work:review-ready"},
                ["12"],
                True,
            ),
            [],
        )
        self.assertIn(
            "completion state requires work:review-ready",
            completion_policy_errors(
                12,
                {"risk:high", "work:complete"},
                ["12"],
                True,
            ),
        )

    def test_blocked_work_cannot_be_complete(self):
        errors = completion_policy_errors(
            12,
            {
                "risk:low",
                "work:blocked",
                "work:complete",
            },
            ["12"],
            False,
        )

        self.assertIn(
            "work:blocked PR cannot be marked complete or review-ready",
            errors,
        )

    def test_completed_work_requires_one_matching_closure(self):
        missing = completion_policy_errors(
            12,
            {"risk:low", "work:complete"},
            [],
            False,
        )
        wrong = completion_policy_errors(
            12,
            {"risk:low", "work:complete"},
            ["13"],
            False,
        )

        self.assertTrue(missing)
        self.assertIn("PR issue must match branch issue", wrong)

    def test_rename_preserves_sensitive_source_path(self):
        paths, count = changed_file_paths(
            [[
                {
                    "filename": (
                        "project/scripts/player/state.gml"
                    ),
                    "previous_filename": (
                        "project/scripts/core/state.gml"
                    ),
                }
            ]]
        )

        high, reasons = forced_high_risk(
            "dev",
            paths,
            0,
            0,
            count,
        )

        self.assertEqual(count, 1)
        self.assertTrue(high)
        self.assertTrue(reasons)

    def test_renames_do_not_inflate_changed_file_count(self):
        entries = [
            {
                "filename": (
                    f"project/scripts/player/new_{index}.gml"
                ),
                "previous_filename": (
                    f"project/scripts/archive/old_{index}.gml"
                ),
            }
            for index in range(20)
        ]

        paths, count = changed_file_paths([entries])
        high, reasons = forced_high_risk(
            "dev",
            paths,
            20,
            20,
            count,
        )

        self.assertEqual(count, 20)
        self.assertEqual(len(paths), 40)
        self.assertFalse(high)
        self.assertEqual(reasons, [])


class WorkflowPolicyTests(unittest.TestCase):
    def test_collectors_preserve_complete_file_records(self):
        workflows = [
            ROOT / ".github/workflows/ci.yml",
            ROOT / ".github/workflows/low-risk-auto-merge.yml",
        ]

        for workflow in workflows:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text(encoding="utf-8")

                self.assertIn("--slurp", text)
                self.assertNotIn("--jq '.[].filename'", text)

    def test_auto_merge_is_revocable_and_head_bound(self):
        path = ROOT / ".github/workflows/low-risk-auto-merge.yml"
        text = path.read_text(encoding="utf-8")

        self.assertIn("pull_request_target:", text)
        self.assertIn("--disable-auto", text)
        self.assertIn(
            "stale auto-merge request remains",
            (ROOT / ".github/workflows/ci.yml").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIn(
            '--match-head-commit "$CI_HEAD"',
            text,
        )
        self.assertIn("PR_HEAD_REPOSITORY", text)

    def test_native_issue_closure_uses_repository_scoped_app_token(self):
        path = ROOT / ".github/workflows/low-risk-auto-merge.yml"
        text = path.read_text(encoding="utf-8")
        workflow_header, jobs = text.split("\njobs:\n", 1)
        cancel_job, merge_job = jobs.split("\n  merge:\n", 1)
        merge_permissions = merge_job.split("\n    steps:\n", 1)[0]
        token_step = merge_job.split(
            "uses: actions/create-github-app-token@v3",
            1,
        )[1].split("\n      - name:", 1)[0]

        self.assertIn("permissions: {}", workflow_header)
        self.assertNotIn("issues:", cancel_job)
        self.assertIn("actions: read", merge_permissions)
        self.assertIn("contents: write", merge_permissions)
        self.assertIn("pull-requests: write", merge_permissions)
        self.assertNotIn("contents: read", merge_permissions)
        self.assertNotIn("issues:", merge_permissions)
        self.assertEqual(
            text.count("actions/create-github-app-token@v3"),
            1,
        )

        for required in (
            "client-id: ${{ vars.GOVERNED_MERGE_APP_CLIENT_ID }}",
            "private-key: "
            "${{ secrets.GOVERNED_MERGE_APP_PRIVATE_KEY }}",
            "permission-contents: write",
            "permission-issues: write",
            "permission-pull-requests: write",
        ):
            with self.subTest(required=required):
                self.assertIn(required, token_step)

        self.assertNotIn("owner:", token_step)
        self.assertNotIn("repositories:", token_step)
        self.assertEqual(text.count("issues: write"), 1)
        self.assertIn(
            "MERGE_TOKEN: "
            "${{ steps.governed-merge-token.outputs.token }}",
            merge_job,
        )
        self.assertEqual(
            merge_job.count('GH_TOKEN="$MERGE_TOKEN"'),
            1,
        )

        final_merge = merge_job.split(
            'GH_TOKEN="$MERGE_TOKEN" gh pr merge',
            1,
        )[1]
        self.assertIn("--auto", final_merge)
        self.assertIn("--squash", final_merge)
        self.assertIn('--match-head-commit "$CI_HEAD"', final_merge)

    def test_governed_merge_app_setup_is_explicit_and_human_owned(self):
        setup = (ROOT / "docs/SETUP.md").read_text(encoding="utf-8")

        for required in (
            "Configure governed merge authentication",
            "Contents: read and write",
            "Issues: read and write",
            "Pull requests: read and write",
            "only on the generated repository",
            "GOVERNED_MERGE_APP_CLIENT_ID",
            "GOVERNED_MERGE_APP_PRIVATE_KEY",
            "human-owned setup steps",
            "No personal access token",
            "fails closed before the merge call",
        ):
            with self.subTest(required=required):
                self.assertIn(required, setup)

    def test_auto_merge_relies_on_native_issue_closure(self):
        path = ROOT / ".github/workflows/low-risk-auto-merge.yml"
        text = path.read_text(encoding="utf-8")

        for direct_close in (
            "gh issue close",
            "closeIssue",
            "/issues/",
            "state=closed",
            '"state": "closed"',
        ):
            with self.subTest(direct_close=direct_close):
                self.assertNotIn(direct_close, text)

    def test_auto_merge_is_bound_to_exact_ci_metadata(self):
        ci_text = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        merge_text = (
            ROOT / ".github/workflows/low-risk-auto-merge.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("$GITHUB_EVENT_PATH", ci_text)
        self.assertIn("actions/upload-artifact@v4", ci_text)
        self.assertIn("retention-days: 30", ci_text)
        self.assertIn(
            "pr-metadata-${{ github.run_id }}-"
            "${{ github.run_attempt }}",
            ci_text,
        )
        self.assertLess(
            ci_text.index("Upload CI PR metadata"),
            ci_text.index("Check PR policy"),
        )

        self.assertIn("actions: read", merge_text)
        self.assertIn(
            'gh run download "$CI_RUN_ID"',
            merge_text,
        )
        self.assertIn(
            "github.event.workflow_run.run_attempt",
            merge_text,
        )
        self.assertIn(
            '--attestation-run-attempt "$CI_METADATA_ATTEMPT"',
            merge_text,
        )
        self.assertIn('while [ "$attempt" -ge 1 ]', merge_text)
        self.assertIn("attempt=$((attempt - 1))", merge_text)
        self.assertIn(
            "tools/ci/pr_metadata.py compare",
            merge_text,
        )

        first_eligibility = merge_text.index(
            "if ! eligible_current;"
        )
        ready = merge_text.index("gh pr ready")
        second_eligibility = merge_text.index(
            "if ! eligible_current;",
            first_eligibility + 1,
        )
        merge = merge_text.index(
            'GH_TOKEN="$MERGE_TOKEN" gh pr merge',
            second_eligibility,
        )

        self.assertLess(first_eligibility, ready)
        self.assertLess(ready, second_eligibility)
        self.assertLess(second_eligibility, merge)

        eligibility_failures = merge_text.split(
            "if ! eligible_current; then"
        )[1:]
        self.assertEqual(len(eligibility_failures), 2)

        for failure in eligibility_failures:
            block = failure.split("fi", 1)[0]
            self.assertIn(
                'CI_METADATA_STATUS" = "stale',
                block,
            )
            self.assertNotIn("disable_auto_merge", block)

        stale_case = merge_text.split(
            'stale)',
            1,
        )[1].split('invalid)', 1)[0]
        self.assertIn("exit 0", stale_case)
        self.assertNotIn("disable_auto_merge", stale_case)

        missing_case = merge_text.split(
            "if ! download_ci_metadata; then",
            1,
        )[1].split("fi", 1)[0]
        self.assertIn("disable_auto_merge", missing_case)

    def test_human_created_labeler_is_trusted_and_bounded(self):
        path = ROOT / ".github/workflows/human-created.yml"
        text = path.read_text(encoding="utf-8")

        self.assertIn("pull_request_target:", text)
        self.assertIn("- labeled", text)
        self.assertIn("startsWith", text)
        self.assertIn(
            "head.repo.full_name == github.repository",
            text,
        )
        self.assertIn("human/", text)
        self.assertIn("human-created", text)
        self.assertIn("manual-merge", text)
        self.assertNotIn("actions/checkout", text)

if __name__ == "__main__":
    unittest.main()
