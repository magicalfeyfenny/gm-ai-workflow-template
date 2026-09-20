import argparse
import json
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import patch
from urllib.parse import unquote

from tools.setup_github import (
    REQUIRED_LABELS,
    REPOSITORY_SETTINGS,
    RULESET_PATHS,
    SetupError,
    configure_repository,
    ensure_labels,
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
        self.labels = [{"name": name} for name in labels]
        self.rulesets = list(rulesets)
        self.rule_details = {
            item["id"]: dict(item)
            for item in self.rulesets
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
        self.metadata = dict(REPOSITORY_SETTINGS)
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

        if method == "GET" and endpoint == "repos/owner/game":
            return deepcopy(self.metadata)

        if method == "GET" and "/labels?" in endpoint:
            return deepcopy(self.labels)

        if method == "GET" and "/rulesets?" in endpoint:
            return deepcopy(self.rulesets)

        if method == "GET" and "/rulesets/" in endpoint:
            return deepcopy(self.rule_details[int(endpoint.rsplit("/", 1)[1])])

        if method == "POST" and endpoint.endswith("/git/refs"):
            self.main_sha = payload["sha"]
            return {}

        if method == "PATCH" and endpoint == "repos/owner/game":
            self.metadata.update(payload)
            return deepcopy(self.metadata)

        if method == "POST" and endpoint == "repos/owner/game/labels":
            self.labels.append(dict(payload))
            return {}

        if method == "PATCH" and "/labels/" in endpoint:
            name = unquote(endpoint.rsplit("/", 1)[1])
            current = next(item for item in self.labels if item["name"] == name)
            current.update(payload)
            if "new_name" in payload:
                current["name"] = payload["new_name"]
            return {}

        if method == "POST" and endpoint == "repos/owner/game/rulesets":
            ruleset = {"id": 100 + len(self.rulesets), **dict(payload)}
            self.rulesets.append({"id": ruleset["id"], "name": ruleset["name"]})
            self.rule_details[ruleset["id"]] = ruleset
            return {}

        if method == "PUT" and "/rulesets/" in endpoint:
            ruleset_id = int(endpoint.rsplit("/", 1)[1])
            self.rule_details[ruleset_id] = {
                "id": ruleset_id,
                **dict(payload),
            }
            for summary in self.rulesets:
                if summary.get("id") == ruleset_id:
                    summary.update({"name": payload["name"]})
            return {}

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
                set(rules),
                {
                    "deletion",
                    "non_fast_forward",
                    "pull_request",
                    "required_status_checks",
                },
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
            self.assertCountEqual(
                checks["required_status_checks"],
                (
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
                ),
            )

    def test_recipe_files_are_json_objects(self):
        for path in RULESET_PATHS:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(value, dict)


class EnsureLabelsTests(unittest.TestCase):
    def test_applies_inventory_across_ordering_and_json_formatting(self):
        fixture_labels = (
            {
                "name": "fixture:present",
                "color": "123456",
                "description": "Update this existing fixture label.",
            },
            {
                "name": "fixture:missing",
                "color": "abcdef",
                "description": "Create this missing fixture label.",
            },
        )

        for inventory in (REQUIRED_LABELS, fixture_labels):
            expected = {
                label["name"]: {
                    "color": label["color"],
                    "description": label["description"],
                }
                for label in inventory
            }
            existing_names = {inventory[0]["name"]}
            representations = {
                "original": inventory,
                "reordered": tuple(reversed(inventory)),
                "formatted_json": json.loads(
                    json.dumps(inventory, sort_keys=True, indent=4)
                ),
            }

            for representation, labels in representations.items():
                with self.subTest(
                    inventory=set(expected),
                    representation=representation,
                ):
                    api = FakeApi(labels=existing_names)
                    with patch("tools.setup_github.REQUIRED_LABELS", labels):
                        ensure_labels(api, "owner/game")

                    created = {
                        payload["name"]: {
                            "color": payload["color"],
                            "description": payload["description"],
                        }
                        for method, endpoint, payload in api.calls
                        if method == "POST"
                        and endpoint == "repos/owner/game/labels"
                    }
                    updated = {
                        payload["new_name"]: {
                            "color": payload["color"],
                            "description": payload["description"],
                        }
                        for method, endpoint, payload in api.calls
                        if method == "PATCH" and "/labels/" in endpoint
                    }
                    self.assertEqual(
                        created,
                        {
                            name: fields
                            for name, fields in expected.items()
                            if name not in existing_names
                        },
                    )
                    self.assertEqual(
                        updated,
                        {name: expected[name] for name in existing_names},
                    )


class ConfigureRepositoryTests(unittest.TestCase):
    def test_creates_main_and_applies_exact_settings(self):
        api = FakeApi()

        configure_repository(
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
        created_labels = [
            payload
            for method, endpoint, payload in api.calls
            if method == "POST"
            and endpoint == "repos/owner/game/labels"
        ]
        self.assertCountEqual(
            created_labels,
            [dict(label) for label in REQUIRED_LABELS],
        )
        self.assertIn(
            "work:complete",
            {label["name"] for label in created_labels},
        )
        self.assertIn(
            "risk:medium",
            {label["name"] for label in created_labels},
        )
        self.assertIn(
            "work:review-ready",
            {label["name"] for label in created_labels},
        )
        self.assertIn(
            "work:blocked",
            {label["name"] for label in created_labels},
        )

        created_rulesets = [
            payload["name"]
            for method, endpoint, payload in api.calls
            if method == "POST"
            and endpoint == "repos/owner/game/rulesets"
        ]
        self.assertCountEqual(
            created_rulesets,
            ("dev-protection", "main-release"),
        )

    def test_renames_legacy_blocked_label(self):
        labels = [
            label["name"]
            for label in REQUIRED_LABELS
            if label["name"] != "work:blocked"
        ]
        labels.append("blocked")
        api = FakeApi(
            main_sha="a" * 40,
            labels=labels,
        )

        configure_repository(
            "owner/game",
            api=api,
        )

        self.assertIn(
            (
                "PATCH",
                "repos/owner/game/labels/blocked",
                {
                    "new_name": "work:blocked",
                    "color": "9150b7",
                    "description": (
                        "Cannot be worked until blockers are resolved."
                    ),
                },
            ),
            api.calls,
        )
        self.assertFalse(
            any(
                method == "POST"
                and endpoint == "repos/owner/game/labels"
                and payload["name"] == "work:blocked"
                for method, endpoint, payload in api.calls
            )
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

        configure_repository(
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
        self.assertFalse(
            any(
                method == "POST"
                and endpoint == "repos/owner/game/labels"
                for method, endpoint, _ in api.calls
            )
        )
        self.assertCountEqual(
            [
                {
                    "name": payload["new_name"],
                    "color": payload["color"],
                    "description": payload["description"],
                }
                for method, endpoint, payload in api.calls
                if method == "PATCH" and "/labels/" in endpoint
            ],
            list(REQUIRED_LABELS),
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

    def test_enriched_ruleset_responses_are_semantically_current(self):
        rulesets = []
        for index, recipe in enumerate(load_rulesets(), start=17):
            enriched = deepcopy(recipe)
            enriched.update({
                "id": index,
                "node_id": f"node-{index}",
                "source": "owner/game",
                "source_type": "Repository",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "current_user_can_bypass": "pull_requests_only",
                "_links": {"self": {"href": "https://example.invalid"}},
            })
            enriched["bypass_actors"][0]["node_id"] = f"actor-{index}"
            enriched["rules"][2]["id"] = index + 100
            enriched["rules"][2]["parameters"].update({
                "required_reviewers": [],
                "require_extra_approval_for_unattributed_changes": True,
            })
            enriched["rules"][3]["parameters"]["required_status_checks"][0][
                "id"
            ] = index + 200
            rulesets.append(enriched)

        api = FakeApi(
            main_sha="a" * 40,
            labels=[label["name"] for label in REQUIRED_LABELS],
            rulesets=rulesets,
        )

        configure_repository("owner/game", api=api)

        self.assertFalse(
            any(
                method in {"POST", "PUT"}
                and "/rulesets" in endpoint
                for method, endpoint, _ in api.calls
            )
        )

    def test_ruleset_update_preserves_unowned_and_stronger_settings(self):
        recipe = load_rulesets()[0]
        enriched = deepcopy(recipe)
        enriched.update({
            "id": 17,
            "node_id": "node-17",
            "source": "owner/game",
            "source_type": "Repository",
            "current_user_can_bypass": "pull_requests_only",
        })
        enriched["enforcement"] = "disabled"
        enriched["rules"][0]["id"] = 19
        enriched["rules"][2]["parameters"].update({
            "required_approving_review_count": 2,
            "required_reviewers": [{"id": 9}],
            "require_extra_approval_for_unattributed_changes": True,
            "allowed_merge_methods": ["squash"],
        })
        enriched["rules"].append({
            "type": "required_linear_history",
            "id": 20,
        })
        api = FakeApi(
            main_sha="a" * 40,
            labels=[label["name"] for label in REQUIRED_LABELS],
            rulesets=[enriched],
        )

        configure_repository("owner/game", api=api)

        updates = [
            payload
            for method, endpoint, payload in api.calls
            if method == "PUT" and endpoint == "repos/owner/game/rulesets/17"
        ]
        self.assertEqual(len(updates), 1)
        update = updates[0]
        self.assertNotIn("node_id", update)
        pull_request = next(
            rule for rule in update["rules"] if rule["type"] == "pull_request"
        )
        self.assertEqual(
            pull_request["parameters"]["required_approving_review_count"],
            2,
        )
        self.assertEqual(
            pull_request["parameters"]["required_reviewers"],
            [{"id": 9}],
        )
        self.assertEqual(
            pull_request["parameters"]["allowed_merge_methods"],
            ["squash"],
        )
        self.assertTrue(
            pull_request["parameters"][
                "require_extra_approval_for_unattributed_changes"
            ]
        )
        self.assertIn(
            {"type": "required_linear_history"},
            update["rules"],
        )

    def test_ruleset_exclusion_of_dev_is_reconciled(self):
        recipe = load_rulesets()[0]
        altered = deepcopy(recipe)
        altered["id"] = 17
        altered["conditions"]["ref_name"]["exclude"] = ["refs/heads/dev"]
        api = FakeApi(
            main_sha="a" * 40,
            labels=[label["name"] for label in REQUIRED_LABELS],
            rulesets=[altered],
        )

        configure_repository("owner/game", api=api)

        updates = [
            payload
            for method, endpoint, payload in api.calls
            if method == "PUT" and endpoint == "repos/owner/game/rulesets/17"
        ]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["conditions"]["ref_name"]["exclude"], [])
        self.assertEqual(
            api.rule_details[17]["conditions"]["ref_name"]["exclude"],
            [],
        )

    def test_required_check_context_differences_do_not_duplicate(self):
        recipe = load_rulesets()[0]
        altered = deepcopy(recipe)
        altered["id"] = 17
        checks = altered["rules"][3]["parameters"]["required_status_checks"]
        checks[0]["integration_id"] = 999
        checks.append({"context": "PR policy", "integration_id": 15368})
        api = FakeApi(
            main_sha="a" * 40,
            labels=[label["name"] for label in REQUIRED_LABELS],
            rulesets=[altered],
        )

        configure_repository("owner/game", api=api)

        update = next(
            payload
            for method, endpoint, payload in api.calls
            if method == "PUT" and endpoint == "repos/owner/game/rulesets/17"
        )
        checks = next(
            rule for rule in update["rules"]
            if rule["type"] == "required_status_checks"
        )["parameters"]["required_status_checks"]
        self.assertEqual(
            [check for check in checks if check["context"] == "PR policy"],
            [{"context": "PR policy", "integration_id": 15368}],
        )

    def test_rerun_reconciles_without_creating_duplicate_resources(self):
        api = FakeApi()

        configure_repository("owner/game", api=api)
        api.calls.clear()
        messages = configure_repository("owner/game", api=api)

        self.assertFalse(
            any(method == "POST" for method, _, _ in api.calls)
        )
        self.assertIn(
            "verified repository settings, branches, required labels, and rulesets",
            messages,
        )

    def test_missing_dev_fails_before_writes(self):
        api = FakeApi(dev_sha=None)

        with self.assertRaises(SetupError):
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

        with self.assertRaises(SetupError):
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
