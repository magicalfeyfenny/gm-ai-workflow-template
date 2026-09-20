#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]

RULESET_PATHS = (
    ROOT / ".github/rulesets/dev-protection.json",
    ROOT / ".github/rulesets/main-release.json",
)

REPOSITORY_SETTINGS: dict[str, object] = {
    "default_branch": "dev",
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "allow_auto_merge": True,
    "delete_branch_on_merge": False,
}

REQUIRED_LABELS: tuple[dict[str, str], ...] = (
    {
        "name": "risk:low",
        "color": "5c881b",
        "description": "Automatic path after work:complete and required CI.",
    },
    {
        "name": "risk:medium",
        "color": "fbca04",
        "description": (
            "Substantial safe work; automatic path with focused evidence."
        ),
    },
    {
        "name": "risk:high",
        "color": "38e6e7",
        "description": "Requires additional checks and manual merging.",
    },
    {
        "name": "manual-merge",
        "color": "f10186",
        "description": "Must be merged by a human, regardless of risk level.",
    },
    {
        "name": "work:blocked",
        "color": "9150b7",
        "description": "Cannot be worked until blockers are resolved.",
    },
    {
        "name": "work:complete",
        "color": "1d76db",
        "description": "Full issue scope is ready for completion handling.",
    },
    {
        "name": "work:review-ready",
        "color": "5319e7",
        "description": "Finished manual work is waiting for human review.",
    },
    {
        "name": "human-created",
        "color": "d4c5f9",
        "description": "Human-owned PR; agent work prohibited; manual bypass.",
    },
    {
        "name": "release",
        "color": "cb2f2a",
        "description": "Release version",
    },
)

RENAMED_LABELS: dict[str, str] = {
    "blocked": "work:blocked",
}

JsonObject = dict[str, Any]
ApiCall = Callable[[str, str, JsonObject | None], Any]


class SetupError(RuntimeError):
    """Raised when GitHub bootstrap cannot be completed safely."""


def repository_name(value: str) -> str:
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        value,
    ):
        raise argparse.ArgumentTypeError(
            "repository must be OWNER/REPOSITORY"
        )

    owner, name = value.split("/", maxsplit=1)

    if owner in {".", ".."} or name in {".", ".."}:
        raise argparse.ArgumentTypeError(
            "repository must be OWNER/REPOSITORY"
        )

    return value


def github_api(
    method: str,
    endpoint: str,
    payload: JsonObject | None = None,
) -> Any:
    command = [
        "gh",
        "api",
        "--method",
        method,
        endpoint,
    ]

    stdin = None

    if payload is not None:
        command.extend(["--input", "-"])
        stdin = json.dumps(payload)

    try:
        result = subprocess.run(
            command,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise SetupError(
            "GitHub CLI (gh) is required"
        ) from exc

    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit status {result.returncode}"
        )
        raise SetupError(
            f"gh api failed for {method} {endpoint}: {detail}"
        )

    if not result.stdout.strip():
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError(
            f"gh api returned invalid JSON for {method} {endpoint}"
        ) from exc


def load_rulesets(
    paths: Sequence[Path] = RULESET_PATHS,
) -> list[JsonObject]:
    recipes: list[JsonObject] = []
    names: set[str] = set()

    for path in paths:
        try:
            recipe = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise SetupError(
                f"cannot load ruleset recipe {path}: {exc}"
            ) from exc

        if not isinstance(recipe, dict):
            raise SetupError(
                f"ruleset recipe must be an object: {path}"
            )

        name = recipe.get("name")

        if not isinstance(name, str) or not name:
            raise SetupError(
                f"ruleset recipe needs a name: {path}"
            )

        if name in names:
            raise SetupError(
                f"duplicate ruleset recipe name: {name}"
            )

        names.add(name)
        recipes.append(recipe)

    return recipes


def exact_ref_sha(
    api: ApiCall,
    repo: str,
    branch: str,
) -> str | None:
    exact_ref = f"refs/heads/{branch}"
    response = api(
        "GET",
        f"repos/{repo}/git/matching-refs/heads/{branch}",
        None,
    )

    if not isinstance(response, list):
        raise SetupError(
            f"unexpected branch response for {branch}"
        )

    matches = [
        item
        for item in response
        if isinstance(item, dict)
        and item.get("ref") == exact_ref
    ]

    if not matches:
        return None

    if len(matches) != 1:
        raise SetupError(
            f"multiple exact refs returned for {branch}"
        )

    try:
        sha = matches[0]["object"]["sha"]
    except (KeyError, TypeError) as exc:
        raise SetupError(
            f"branch response has no commit SHA for {branch}"
        ) from exc

    if not isinstance(sha, str) or not sha:
        raise SetupError(
            f"branch response has no commit SHA for {branch}"
        )

    return sha


def paged_list(
    api: ApiCall,
    endpoint: str,
) -> list[JsonObject]:
    """Read complete finite inventories instead of assuming the first page."""
    values: list[JsonObject] = []
    separator = "&" if "?" in endpoint else "?"
    page = 1
    while True:
        response = api(
            "GET",
            f"{endpoint}{separator}per_page=100&page={page}",
            None,
        )
        if not isinstance(response, list):
            raise SetupError(f"unexpected inventory response for {endpoint}")
        values.extend(item for item in response if isinstance(item, dict))
        if len(response) < 100:
            return values
        page += 1


RULESET_RESPONSE_FIELDS = frozenset({
    "id", "node_id", "source", "source_type", "created_at",
    "updated_at", "current_user_can_bypass", "_links",
})
STRONGER_RULESET_BOOLEAN_FIELDS = frozenset({
    "dismiss_stale_reviews_on_push",
    "require_code_owner_review",
    "require_last_push_approval",
})
EXACT_RULESET_LIST_FIELDS = frozenset({
    "include", "exclude", "bypass_actors",
})


def _without_ruleset_response_fields(
    value: object,
    key: str | None = None,
) -> object:
    if isinstance(value, dict):
        response_fields = set(RULESET_RESPONSE_FIELDS) if key is None else set()
        if key in {"rules", "bypass_actors", "required_status_checks"}:
            response_fields.update({"id", "node_id"})
        return {
            child: _without_ruleset_response_fields(item, child)
            for child, item in value.items()
            if child not in response_fields
        }
    if isinstance(value, list):
        return [_without_ruleset_response_fields(item, key) for item in value]
    return value


def _ruleset_stronger_than(actual: object, expected: object, key: str | None) -> bool:
    if key in STRONGER_RULESET_BOOLEAN_FIELDS:
        return expected is False and actual is True
    if key == "required_approving_review_count":
        return (
            isinstance(actual, int)
            and not isinstance(actual, bool)
            and isinstance(expected, int)
            and not isinstance(expected, bool)
            and actual >= expected
        )
    return False


def _ruleset_list_contains(actual: object, expected: list[object]) -> bool:
    if not isinstance(actual, list):
        return False
    remaining = list(actual)
    for value in expected:
        match = next(
            (
                index for index, candidate in enumerate(remaining)
                if _ruleset_semantics_match(candidate, value)
            ),
            None,
        )
        if match is None:
            return False
        remaining.pop(match)
    return True


def _ruleset_list_exact(actual: object, expected: list[object]) -> bool:
    return (
        isinstance(actual, list)
        and len(actual) == len(expected)
        and _ruleset_list_contains(actual, expected)
    )


def _ruleset_semantics_match(
    actual: object,
    expected: object,
    key: str | None = None,
) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            child in actual
            and _ruleset_semantics_match(actual[child], value, child)
            for child, value in expected.items()
        )
    if isinstance(expected, list):
        if key in EXACT_RULESET_LIST_FIELDS:
            return _ruleset_list_exact(actual, expected)
        if key == "required_status_checks":
            if not isinstance(actual, list):
                return False
            identities = [
                _ruleset_item_identity(value) for value in actual
            ]
            if any(
                identity is not None and identities.count(identity) > 1
                for identity in identities
            ):
                return False
            return _ruleset_list_contains(actual, expected)
        if not isinstance(actual, list):
            return False
        if key == "allowed_merge_methods":
            actual_set = set(actual)
            expected_set = set(expected)
            return actual_set.issubset(expected_set)
        return _ruleset_list_contains(actual, expected)
    return actual == expected or _ruleset_stronger_than(actual, expected, key)


def _ruleset_item_identity(value: object) -> tuple[object, ...] | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("context"), str):
        return ("context", value["context"])
    if "type" in value:
        return ("type", value["type"])
    if "actor_id" in value:
        return ("actor_id", value["actor_id"], value.get("actor_type"))
    return None


def _merge_ruleset_list(
    live: object,
    expected: list[object],
    key: str | None,
) -> list[object]:
    if key in EXACT_RULESET_LIST_FIELDS:
        existing = list(live) if isinstance(live, list) else []
        result: list[object] = []
        for value in expected:
            match = next(
                (
                    index for index, candidate in enumerate(existing)
                    if _ruleset_semantics_match(candidate, value)
                ),
                None,
            )
            if match is None:
                identity = _ruleset_item_identity(value)
                if identity is not None:
                    match = next(
                        (
                            index for index, candidate in enumerate(existing)
                            if _ruleset_item_identity(candidate) == identity
                        ),
                        None,
                    )
            if match is None:
                result.append(_without_ruleset_response_fields(value, key))
                continue
            current = existing.pop(match)
            result.append(_merge_ruleset_value(current, value, key))
        return result
    if key == "allowed_merge_methods" and _ruleset_semantics_match(
        live, expected, key
    ):
        preserved = _without_ruleset_response_fields(live, key)
        return preserved if isinstance(preserved, list) else []
    existing = list(live) if isinstance(live, list) else []
    result: list[object] = []
    for value in expected:
        match = next(
            (
                index for index, candidate in enumerate(existing)
                if _ruleset_semantics_match(candidate, value)
            ),
            None,
        )
        if match is None:
            identity = _ruleset_item_identity(value)
            if identity is not None:
                match = next(
                    (
                        index for index, candidate in enumerate(existing)
                        if _ruleset_item_identity(candidate) == identity
                    ),
                    None,
                )
        if match is None:
            result.append(_without_ruleset_response_fields(value, key))
            continue
        current = existing.pop(match)
        result.append(_merge_ruleset_value(current, value, key))
    matched_identities = {
        _ruleset_item_identity(value)
        for value in result
        if key == "required_status_checks"
    }
    if key == "required_status_checks":
        identities = set(matched_identities)
        for item in existing:
            identity = _ruleset_item_identity(item)
            if identity is not None and identity in identities:
                continue
            if identity is not None:
                identities.add(identity)
            result.append(_without_ruleset_response_fields(item, key))
    else:
        result.extend(_without_ruleset_response_fields(item, key) for item in existing)
    return result


def _merge_ruleset_value(
    live: object,
    expected: object,
    key: str | None = None,
) -> object:
    if isinstance(expected, dict):
        current = live if isinstance(live, dict) else {}
        result = _without_ruleset_response_fields(current, key)
        assert isinstance(result, dict)
        for child, value in expected.items():
            result[child] = _merge_ruleset_value(current.get(child), value, child)
        return result
    if isinstance(expected, list):
        return _merge_ruleset_list(live, expected, key)
    if _ruleset_semantics_match(live, expected, key):
        return _without_ruleset_response_fields(live, key)
    return expected


def ensure_labels(
    api: ApiCall,
    repo: str,
) -> list[str]:
    response = paged_list(api, f"repos/{repo}/labels")

    existing = {
        item["name"]: item
        for item in response
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
    }

    messages: list[str] = []

    labels_by_name = {
        label["name"]: label
        for label in REQUIRED_LABELS
    }

    for old_name, new_name in RENAMED_LABELS.items():
        if old_name not in existing or new_name in existing:
            continue

        target = labels_by_name[new_name]
        api(
            "PATCH",
            f"repos/{repo}/labels/{quote(old_name, safe='')}",
            {
                "new_name": new_name,
                "color": target["color"],
                "description": target["description"],
            },
        )
        del existing[old_name]
        existing[new_name] = {
            **existing.get(new_name, {}),
            **target,
        }
        messages.append(
            f"renamed label {old_name} to {new_name}"
        )

    for label in REQUIRED_LABELS:
        name = label["name"]

        current = existing.get(name)

        if current is not None:
            payload: JsonObject = {
                "new_name": name,
                "color": label["color"],
                "description": label["description"],
            }
            if any(current.get(key) != value for key, value in label.items()):
                api(
                    "PATCH",
                    f"repos/{repo}/labels/{quote(name, safe='')}",
                    payload,
                )
                messages.append(f"updated label {name}")
                existing[name] = {**current, **label}
            else:
                messages.append(f"kept label {name}")
        else:
            api(
                "POST",
                f"repos/{repo}/labels",
                dict(label),
            )
            existing[name] = dict(label)
            messages.append(f"created label {name}")

    return messages


def install_rulesets(
    api: ApiCall,
    repo: str,
    recipes: Sequence[JsonObject],
) -> list[str]:
    response = paged_list(
        api,
        f"repos/{repo}/rulesets?includes_parents=false",
    )

    messages: list[str] = []

    for recipe in recipes:
        name = recipe["name"]
        matches = [
            item
            for item in response
            if isinstance(item, dict)
            and item.get("name") == name
        ]

        if len(matches) > 1:
            raise SetupError(
                f"multiple repository rulesets named {name}"
            )

        if matches:
            ruleset_id = matches[0].get("id")

            if not isinstance(ruleset_id, int):
                raise SetupError(
                    f"ruleset {name} has no numeric id"
                )

            current = api(
                "GET",
                f"repos/{repo}/rulesets/{ruleset_id}",
                None,
            )
            if not _ruleset_semantics_match(current, recipe):
                api(
                    "PUT",
                    f"repos/{repo}/rulesets/{ruleset_id}",
                    _merge_ruleset_value(current, recipe),
                )
                messages.append(f"updated ruleset {name}")
            else:
                messages.append(f"kept ruleset {name}")
        else:
            api(
                "POST",
                f"repos/{repo}/rulesets",
                recipe,
            )
            messages.append(f"created ruleset {name}")

    return messages


def verify_configuration(
    api: ApiCall,
    repo: str,
    recipes: Sequence[JsonObject],
    created_main_sha: str | None = None,
) -> list[str]:
    """Verify every configured GitHub contract after the writes complete."""
    metadata = api("GET", f"repos/{repo}", None)
    if not isinstance(metadata, dict):
        raise SetupError("unexpected repository settings response during verification")
    for key, expected in REPOSITORY_SETTINGS.items():
        if metadata.get(key) != expected:
            raise SetupError(
                f"repository setting {key} did not reach the expected value"
            )

    for branch in ("dev", "main"):
        branch_sha = exact_ref_sha(api, repo, branch)
        if branch_sha is None:
            raise SetupError(f"branch {branch} was not observable after setup")
        if branch == "main" and created_main_sha is not None and branch_sha != created_main_sha:
            raise SetupError("main was not created from the observed dev commit")

    labels = paged_list(api, f"repos/{repo}/labels")
    labels_by_name = {
        item["name"]: item
        for item in labels
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for label in REQUIRED_LABELS:
        current = labels_by_name.get(label["name"])
        if current is None or any(
            current.get(key) != value for key, value in label.items()
        ):
            raise SetupError(f"label {label['name']} did not reach the expected value")

    rulesets = paged_list(
        api,
        f"repos/{repo}/rulesets?includes_parents=false",
    )
    for recipe in recipes:
        matches = [
            item for item in rulesets
            if isinstance(item, dict) and item.get("name") == recipe["name"]
        ]
        if len(matches) != 1:
            raise SetupError(
                f"ruleset {recipe['name']} was not uniquely observable after setup"
            )
        ruleset_id = matches[0].get("id")
        if not isinstance(ruleset_id, int):
            raise SetupError(f"ruleset {recipe['name']} has no numeric id")
        detail = api(
            "GET",
            f"repos/{repo}/rulesets/{ruleset_id}",
            None,
        )
        if not _ruleset_semantics_match(detail, recipe):
            raise SetupError(
                f"ruleset {recipe['name']} did not reach the expected value"
            )

    return [
        "verified repository settings, branches, required labels, and rulesets",
    ]


def configure_repository(
    repo: str,
    api: ApiCall = github_api,
    ruleset_paths: Sequence[Path] = RULESET_PATHS,
) -> list[str]:
    recipes = load_rulesets(ruleset_paths)
    messages: list[str] = []
    created_main_sha = None

    dev_sha = exact_ref_sha(api, repo, "dev")

    if dev_sha is None:
        raise SetupError(
            "dev does not exist; create the repository from "
            "the template's default branch"
        )

    main_sha = exact_ref_sha(api, repo, "main")

    if main_sha is None:
        created_main_sha = dev_sha
        api(
            "POST",
            f"repos/{repo}/git/refs",
            {
                "ref": "refs/heads/main",
                "sha": dev_sha,
            },
        )
        messages.append(f"created main from dev at {dev_sha}")
    else:
        messages.append(f"left existing main at {main_sha}")

    api(
        "PATCH",
        f"repos/{repo}",
        dict(REPOSITORY_SETTINGS),
    )
    messages.append("configured repository settings")

    messages.extend(ensure_labels(api, repo))
    messages.extend(install_rulesets(api, repo, recipes))
    messages.extend(verify_configuration(api, repo, recipes, created_main_sha))

    return messages


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 12):
        print(
            "setup-github: Python 3.12 or later is required",
            file=sys.stderr,
        )
        return 2

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "bootstrap":
        sys.dont_write_bytecode = True
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.greenfield_bootstrap import main as bootstrap_main

        return bootstrap_main(argv[1:])
    if argv and argv[0] == "adopt-existing":
        # Planning must not create import caches in the inspected repository.
        sys.dont_write_bytecode = True
        # Direct script execution starts sys.path in tools, not the repository.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.adoption_plan import main as adoption_main

        return adoption_main(argv[1:])

    parser = argparse.ArgumentParser(
        description=(
            "Configure a repository created from this template. Use bootstrap "
            "for a greenfield GameMaker folder and adopt-existing for an "
            "existing repository."
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        type=repository_name,
        metavar="OWNER/REPOSITORY",
    )
    args = parser.parse_args(argv)

    try:
        messages = configure_repository(args.repo)
    except SetupError as exc:
        print(f"setup-github: {exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(f"setup-github: {message}")

    print(f"setup-github: completed for {args.repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
