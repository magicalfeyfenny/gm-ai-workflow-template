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
        "description": "Auto-merges after work:complete and required CI.",
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
            if not isinstance(current, dict) or any(
                current.get(key) != value for key, value in recipe.items()
            ):
                api(
                    "PUT",
                    f"repos/{repo}/rulesets/{ruleset_id}",
                    recipe,
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
        if not isinstance(detail, dict) or any(
            detail.get(key) != value for key, value in recipe.items()
        ):
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
