import argparse
import json
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import patch

from tools.setup_github import (
    REQUIRED_LABELS,
    REPOSITORY_SETTINGS,
    RULESET_PATHS,
    SetupError,
    configure_repository,
    github_api,
    load_rulesets,
    repository_name,
)


class FakeApi:
    def __init__(
        self,
        *,
        dev_sha="d" * 40,
        main_sha=None,
        labels=(),
        rulesets=(),
    ):
        self.dev_sha = dev_sha
        self.main_sha = main_sha
        self.labels = [
            {"name": name}
            for name in labels
        ]
        self.rulesets = list(rulesets)
        self.calls = []

    def __call__(self, method, endpoint, payload=None):
        self.calls.append(
            (method, endpoint, deepcopy(payload))
        )

        if method == "GET" and endpoint.endswith(
            "/git/matching-refs/heads/dev"
        ):
            return self._ref("dev", self.dev_sha)

        if method == "GET" and endpoint.endswith(
            "/git/matching-refs/heads/main"
        ):
            return self._ref("main", self.main_sha)

        if method == "GET" and "/labels?" in endpoint:
            return deepcopy(self.labels)

        if method == "GET" and "/rulesets?" in endpoint:
            return deepcopy(self.rulesets)

        return {}

    @staticmethod
    def _ref(branch, sha):
        if sha is None:
            return []

        return [
            {
                "ref": f"refs/heads/{branch}",
                "object": {"sha": sha},
            }
        ]


class RulesetRecipeTests(unittest.TestCase):
    def test_recipes_preserve_finite_governance(self):
        recipes = load_rulesets()
        expected = {
            "dev-protection": "refs/heads/dev",
            "main-release": "refs/heads/main",
        }

        self.assertEqual(
            {recipe["name"] for recipe in recipes},
            set(expected),
        )

        for recipe in recipes:
            self.assertEqual(
                set(recipe),
                {
                    "name",
                    "target",
                    "enforcement",
                    "bypass_actors",
                    "conditions",
                    "rules",
                },
            )
            self.assertEqual(recipe["target"], "branch")
            self.assertEqual(recipe["enforcement"], "active")
            self.assertEqual(
                recipe["bypass_actors"],
                [
                    {
                        "actor_id": 5,
                        "actor_type": "RepositoryRole",
                        "bypass_mode": "pull_request",
                    }
                ],
            )
            self.assertEqual(
                recipe["conditions"],
                {
                    "ref_name": {
                        "exclude": [],
                        "include": [expected[recipe["name"]]],
                    }
                },
            )

            rules = {
                rule["type"]: rule
                for rule in recipe["rules"]
            }
            self.assertEqual(
                list(rules),
                [
                    "deletion",
                    "non_fast_forward",
                    "pull_request",
                    "required_status_checks",
                ],
            )

            pull_request = rules["pull_request"]["parameters"]
            self.assertEqual(
                pull_request,
                {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": [
                        "merge",
                        "squash",
                        "rebase",
                    ],
                },
            )

            checks = rules[
                "required_status_checks"
            ]["parameters"]
            self.assertTrue(
                checks["strict_required_status_checks_policy"]
            )
            self.assertTrue(checks["do_not_enforce_on_create"])
            self.assertEqual(
                checks["required_status_checks"],
                [
                    {
                        "context": "PR policy",
                        "integration_id": 15368,
                    },
                    {
                        "context": "Repository policy",
                        "integration_id": 15368,
                    },
                    {
                        "context": "Tests",
                        "integration_id": 15368,
                    },
                    {
                        "context": "Format",
                        "integration_id": 15368,
                    },
                ],
            )

    def test_recipe_files_are_json_objects(self):
        for path in RULESET_PATHS:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(value, dict)


class ConfigureRepositoryTests(unittest.TestCase):
    def test_creates_main_and_applies_exact_settings(self):
        api = FakeApi()

        messages = configure_repository(
            "owner/game",
            api=api,
        )

        self.assertIn(
            (
                "POST",
                "repos/owner/game/git/refs",
                {
                    "ref": "refs/heads/main",
                    "sha": "d" * 40,
                },
            ),
            api.calls,
        )
        self.assertIn(
            (
                "PATCH",
                "repos/owner/game",
                REPOSITORY_SETTINGS,
            ),
            api.calls,
        )
        self.assertIn(
            f"created main from dev at {'d' * 40}",
            messages,
        )

        created_labels = [
            payload
            for method, endpoint, payload in api.calls
            if method == "POST"
            and endpoint == "repos/owner/game/labels"
        ]
        self.assertEqual(
            created_labels,
            [dict(label) for label in REQUIRED_LABELS],
        )
        self.assertIn(
            "work:complete",
            {label["name"] for label in created_labels},
        )

        created_rulesets = [
            payload["name"]
            for method, endpoint, payload in api.calls
            if method == "POST"
            and endpoint == "repos/owner/game/rulesets"
        ]
        self.assertEqual(
            created_rulesets,
            ["dev-protection", "main-release"],
        )

    def test_existing_resources_are_updated_without_moving_main(self):
        labels = [
            label["name"]
            for label in REQUIRED_LABELS
        ]
        api = FakeApi(
            main_sha="a" * 40,
            labels=labels,
            rulesets=[
                {
                    "id": 17,
                    "name": "dev-protection",
                }
            ],
        )

        messages = configure_repository(
            "owner/game",
            api=api,
        )

        self.assertFalse(
            any(
                method == "POST"
                and endpoint.endswith("/git/refs")
                for method, endpoint, _ in api.calls
            )
        )
        self.assertIn(
            f"left existing main at {'a' * 40}",
            messages,
        )

        self.assertFalse(
            any(
                method == "POST"
                and endpoint == "repos/owner/game/labels"
                for method, endpoint, _ in api.calls
            )
        )
        self.assertEqual(
            sum(
                method == "PATCH"
                and "/labels/" in endpoint
                for method, endpoint, _ in api.calls
            ),
            6,
        )
        self.assertTrue(
            any(
                method == "PUT"
                and endpoint == "repos/owner/game/rulesets/17"
                and payload["name"] == "dev-protection"
                for method, endpoint, payload in api.calls
            )
        )
        self.assertTrue(
            any(
                method == "POST"
                and endpoint == "repos/owner/game/rulesets"
                and payload["name"] == "main-release"
                for method, endpoint, payload in api.calls
            )
        )

    def test_missing_dev_fails_before_writes(self):
        api = FakeApi(dev_sha=None)

        with self.assertRaisesRegex(
            SetupError,
            "dev does not exist",
        ):
            configure_repository("owner/game", api=api)

        self.assertTrue(api.calls)
        self.assertTrue(
            all(method == "GET" for method, _, _ in api.calls)
        )


class GithubApiTests(unittest.TestCase):
    @patch("tools.setup_github.subprocess.run")
    def test_serializes_json_through_stdin(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok": true}\n',
            stderr="",
        )

        result = github_api(
            "PATCH",
            "repos/owner/game",
            {"allow_auto_merge": True},
        )

        self.assertEqual(result, {"ok": True})
        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "repos/owner/game",
                "--input",
                "-",
            ],
        )
        self.assertEqual(
            json.loads(kwargs["input"]),
            {"allow_auto_merge": True},
        )
        self.assertFalse(kwargs["shell"])

    @patch("tools.setup_github.subprocess.run")
    def test_surfaces_gh_failure(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

        with self.assertRaisesRegex(
            SetupError,
            "permission denied",
        ):
            github_api("GET", "repos/owner/game")

    def test_repository_name_requires_owner_and_repo(self):
        self.assertEqual(
            repository_name("owner/game"),
            "owner/game",
        )

        with self.assertRaises(argparse.ArgumentTypeError):
            repository_name("game")


if __name__ == "__main__":
    unittest.main()
