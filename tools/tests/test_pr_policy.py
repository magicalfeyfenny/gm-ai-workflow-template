import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.ci.pr_policy import (
    POLICY,
    auto_merge_eligible,
    branch_issue,
    changed_file_paths,
    completion_policy_errors,
    evaluate_pull_request,
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

    def test_governance_and_pipeline_paths_are_high_risk(self) -> None:
        """Keep authority and pipeline mechanisms on the manual path."""
        paths = [
            ".github/actions/validate/action.yml",
            ".github/rulesets/dev-protection.json",
            ".github/workflows/ci.yml",
            ".gitattributes",
            "AGENTS.md",
            "GOVERNANCE.md",
            "PROJECT_POLICY.toml",
            ".agents/skills/gamemaker-production/SKILL.md",
            "docs/SETUP.md",
            "templates/codex/governed-change.txt",
            "tools/assets/export_assets.py",
            "tools/ci/pr_policy.py",
            "tools/setup_github.py",
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
                self.assertEqual(reasons, [f"high-risk path: {path}"])

    def test_routine_production_paths_can_be_low_risk(self) -> None:
        """Do not use ordinary project and asset domains as risk proxies."""
        paths = [
            "project/game.yyp",
            "project/options/main/options_main.yy",
            "project/extensions/store/store.yy",
            "project/scripts/core/state.gml",
            "project/scripts/save/write_save.gml",
            "project/scripts/persistence/profile.gml",
            "project/scripts/migrations/save_v2.gml",
            "content/save/schema.json",
            "content/story/chapter_1.json",
            "assets/source/portrait.kra",
            "assets/runtime/portrait.png",
            "assets/exports.json",
            ".github/ISSUE_TEMPLATE/work-item.yml",
            ".github/pull_request_template.md",
            "docs/design.md",
        ]

        for path in paths:
            with self.subTest(path=path):
                high, reasons = forced_high_risk(
                    "dev",
                    [path],
                    1,
                    0,
                )

                self.assertFalse(high)
                self.assertEqual(reasons, [])

    def test_size_limits_only_force_massive_changes_high(self) -> None:
        """Keep exact limits inclusive and force only limit-plus-one high."""
        max_files = int(POLICY["risk"]["max_changed_files"])
        max_lines = int(POLICY["risk"]["max_changed_lines"])

        self.assertEqual((max_files, max_lines), (100, 10000))

        at_limit = forced_high_risk(
            "dev",
            ["project/scripts/player/player.gml"],
            6000,
            4000,
            max_files,
        )
        over_files = forced_high_risk(
            "dev",
            ["project/scripts/player/player.gml"],
            1,
            0,
            max_files + 1,
        )
        over_lines = forced_high_risk(
            "dev",
            ["project/scripts/player/player.gml"],
            max_lines,
            1,
            1,
        )

        self.assertEqual(at_limit, (False, []))
        self.assertEqual(
            over_files,
            (True, ["changed file count exceeds low-risk limit"]),
        )
        self.assertEqual(
            over_lines,
            (True, ["changed line count exceeds low-risk limit"]),
        )

    def test_routine_change_can_be_voluntarily_high_risk(self) -> None:
        """Honor an explicit high-risk label without a path-based reason."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-save-schema",
            head_repository="owner/game",
            repository="owner/game",
            body="Closes #12\n",
            labels={"risk:high", "work:review-ready"},
            additions=10,
            deletions=2,
            changed_paths=["project/game.yyp"],
            changed_file_count=1,
        )

        self.assertEqual(evaluation.errors, ())
        self.assertEqual(evaluation.high_risk_reasons, ())
        self.assertTrue(evaluation.effective_high)
        self.assertFalse(evaluation.auto_merge_allowed)

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

    def test_rename_preserves_governance_source_path(self) -> None:
        """Keep a renamed authority file high through its previous path."""
        paths, count = changed_file_paths(
            [[
                {
                    "filename": (
                        "docs/legacy-policy.md"
                    ),
                    "previous_filename": (
                        "tools/ci/legacy_policy.py"
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

    def test_renames_do_not_inflate_changed_file_count(self) -> None:
        """Count API file records once even when each has two paths."""
        max_files = int(POLICY["risk"]["max_changed_files"])
        entries = [
            {
                "filename": (
                    f"project/scripts/player/new_{index}.gml"
                ),
                "previous_filename": (
                    f"project/scripts/archive/old_{index}.gml"
                ),
            }
            for index in range(max_files)
        ]

        paths, count = changed_file_paths([entries])
        high, reasons = forced_high_risk(
            "dev",
            paths,
            20,
            20,
            count,
        )

        self.assertEqual(count, max_files)
        self.assertEqual(len(paths), max_files * 2)
        self.assertFalse(high)
        self.assertEqual(reasons, [])


class WorkflowPolicyTests(unittest.TestCase):
    """Keep workflow tests focused on declarative trust boundaries."""

    def test_ci_collector_preserves_complete_file_records(self):
        """Keep CI policy input complete instead of projecting filenames."""
        text = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("--slurp", text)
        self.assertNotIn("--jq '.[].filename'", text)

    def test_auto_merge_workflow_routes_to_trusted_boundary(self):
        """Keep event wiring visible and orchestration out of shell YAML."""
        path = ROOT / ".github/workflows/low-risk-auto-merge.yml"
        text = path.read_text(encoding="utf-8")

        self.assertIn("pull_request_target:", text)
        self.assertIn("workflow_run:", text)
        self.assertIn(
            "python3 -m tools.ci.low_risk_merge cancel",
            text,
        )
        self.assertIn(
            "python3 -m tools.ci.low_risk_merge merge",
            text,
        )
        self.assertEqual(text.count("persist-credentials: false"), 2)
        self.assertEqual(text.count("ref: dev"), 2)

        for inline_detail in (
            "eligible_current",
            "refresh_pr",
            "classify_ci_metadata",
            "gh pr ready",
            "gh pr merge",
            "jq ",
        ):
            with self.subTest(inline_detail=inline_detail):
                self.assertNotIn(inline_detail, text)

        self.assertIn(
            "stale auto-merge request remains",
            (ROOT / ".github/workflows/ci.yml").read_text(
                encoding="utf-8"
            ),
        )

    def test_native_issue_closure_uses_repository_scoped_app_token(self):
        """Keep App credentials scoped and separate from the ambient token."""
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
        self.assertIn(
            "python3 -m tools.ci.low_risk_merge merge",
            merge_job,
        )
        self.assertNotIn('GH_TOKEN="$MERGE_TOKEN"', merge_job)

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
        """Keep issue completion native to the merge instead of scripting it."""
        path = ROOT / ".github/workflows/low-risk-auto-merge.yml"
        text = path.read_text(encoding="utf-8") + (
            ROOT / "tools/ci/low_risk_merge.py"
        ).read_text(encoding="utf-8")

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
        """Pass every completed-run identity field into one trusted unit."""
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
            "python3 -m tools.ci.low_risk_merge merge",
            merge_text,
        )

        for source, argument in (
            ("github.event.workflow_run.pull_requests[0].number", "PR_NUMBER"),
            ("github.event.workflow_run.head_sha", "CI_HEAD"),
            ("github.event.workflow_run.conclusion", "CI_CONCLUSION"),
            ("github.event.workflow_run.id", "CI_RUN_ID"),
            ("github.event.workflow_run.run_attempt", "CI_RUN_ATTEMPT"),
        ):
            with self.subTest(source=source):
                self.assertIn(source, merge_text)
                self.assertIn(f'"${argument}"', merge_text)

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
