"""Install the current workflow framework into a greenfield GameMaker folder."""

from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from urllib.parse import urlsplit

from tools.ci.candidate_git import candidate_snapshot
from tools.setup_github import (
    ROOT as TEMPLATE_ROOT,
    SetupError,
    configure_repository,
    repository_name,
)


ROOT_FILES = frozenset({
    ".gitattributes", ".gitignore", ".python-version", "AGENTS.md",
    "GOVERNANCE.md", "PROJECT_POLICY.toml", "README.md",
})
FRAMEWORK_ROOTS = (".agents", ".github", "docs", "templates", "tools")
FRAMEWORK_DATA_ROOTS = ("assets",)
FRAMEWORK_CONTENT_FILES = frozenset({"content/.gitkeep"})
SKIPPED_FRAMEWORK_PREFIXES = ("docs/audits/",)
CORE_FILES = frozenset({
    "AGENTS.md", "GOVERNANCE.md", "PROJECT_POLICY.toml",
    ".github/workflows/ci.yml", ".github/pull_request_template.md",
    "docs/SETUP.md", "tools/setup_github.py", "tools/ci/check_repo.py",
})
MERGE_FILES = frozenset({".gitignore", ".gitattributes"})
PRESERVE_FILES = frozenset({"assets/exports.json"})
INDEPENDENT_FILES = frozenset({
    "AGENTS.md", "GOVERNANCE.md", "PROJECT_POLICY.toml",
    ".github/pull_request_template.md",
})
INDEPENDENT_ROOT_FILES = frozenset({
    "CODEOWNERS", ".github/CODEOWNERS", "CONTRIBUTING.md", "POLICY.md",
    "REPOSITORY_POLICY.md", "SECURITY.md", "docs/GOVERNANCE.md",
})
ONBOARDING_MARKER = "<!-- gm-ai-workflow-template:onboarding -->"

def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
def _safe_destination(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".git" in path.parts or ".." in path.parts:
        raise SetupError(f"unsafe bootstrap destination: {relative}")
    root = root.resolve()
    current = root
    for part in path.parts[:-1]:
        current /= part
        if current.exists() and (current.is_symlink() or not current.is_dir()):
            raise SetupError(f"bootstrap destination parent is unsafe: {relative}")
    destination = root / path
    try:
        destination.parent.resolve().relative_to(root)
    except ValueError as exc:
        raise SetupError(f"bootstrap destination escapes target: {relative}") from exc
    return destination
def _tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [
            os.fsdecode(value)
            for value in result.stdout.split(b"\0")
            if value
        ]
    paths = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        paths.append(_relative(path, root))
    return sorted(paths)
def framework_paths(source_root: Path) -> list[str]:
    """Select portable framework files directly from the trusted template tree."""
    paths = []
    for relative in _tracked_paths(source_root):
        if relative in ROOT_FILES or relative in FRAMEWORK_CONTENT_FILES:
            paths.append(relative)
            continue
        if relative.startswith(SKIPPED_FRAMEWORK_PREFIXES):
            continue
        if any(relative == root or relative.startswith(root + "/")
               for root in FRAMEWORK_ROOTS + FRAMEWORK_DATA_ROOTS):
            if relative.startswith("project/"):
                continue
            paths.append(relative)
    return sorted(set(paths))
def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SetupError(f"cannot read {path}: {exc}") from exc
def _is_nonempty(path: Path) -> bool:
    try:
        return bool(path.is_file() and path.read_bytes().strip())
    except OSError:
        return False
def _discover_projects(root: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Find valid modern or legacy projects without relocating their topology."""
    projects: list[dict[str, str]] = []
    invalid: list[str] = []
    skip = {".git", ".venv", "build", "dist", "node_modules", "tmp"}
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name not in skip]
        directory_path = Path(directory)
        for filename in filenames:
            path = directory_path / filename
            relative = _relative(path, root)
            if path.suffix.casefold() == ".yyp":
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    invalid.append(relative)
                    continue
                if (
                    isinstance(value, dict)
                    and value.get("resourceType") == "GMProject"
                ):
                    projects.append({
                        "path": relative,
                        "format": "yyp",
                    })
                else:
                    invalid.append(relative)
            elif path.suffix.casefold() == ".gmx":
                try:
                    tree = ElementTree.parse(path)
                    root_name = tree.getroot().tag.rsplit("}", 1)[-1]
                except (OSError, ElementTree.ParseError):
                    invalid.append(relative)
                    continue
                if root_name in {"assets", "project"}:
                    projects.append({
                        "path": relative,
                        "format": "gmx",
                    })
                else:
                    invalid.append(relative)
    return sorted(projects, key=lambda item: item["path"]), sorted(invalid)
def _custom_authority_paths(
    target_root: Path,
    source_root: Path,
    source_paths: set[str],
) -> list[str]:
    found: set[str] = set()
    for relative in INDEPENDENT_ROOT_FILES:
        if _is_nonempty(target_root / relative):
            found.add(relative)
    for relative in INDEPENDENT_FILES:
        target = target_root / relative
        if target.is_file() and _is_nonempty(target):
            source = source_root / relative
            if not source.is_file() or target.read_bytes() != source.read_bytes():
                found.add(relative)
    for directory in (
        ".github/workflows",
        ".github/rulesets",
        ".github/ISSUE_TEMPLATE",
        ".agents/skills",
        "tools/ci",
    ):
        candidate_root = target_root / directory
        if not candidate_root.is_dir():
            continue
        for path in candidate_root.rglob("*"):
            if not path.is_file():
                continue
            relative = _relative(path, target_root)
            source = source_root / relative
            if relative not in source_paths or not source.is_file():
                if _is_nonempty(path):
                    found.add(relative)
            elif path.read_bytes() != source.read_bytes():
                found.add(relative)
    return sorted(found)
def _historical_framework_paths(
    target_root: Path,
    owned_paths: set[str],
) -> list[str]:
    result = subprocess.run(
        [
            "git", "-C", str(target_root), "log", "--all", "--format=",
            "--name-only", "--", *sorted(owned_paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip() in owned_paths})
def classify_target(
    target_root: Path,
    source_root: Path,
    source_paths: list[str] | None = None,
) -> dict:
    """Classify the target before any framework file is written."""
    target_root = target_root.resolve()
    source_root = source_root.resolve()
    source_paths = source_paths or framework_paths(source_root)
    source_set = set(source_paths)
    projects, invalid_projects = _discover_projects(target_root)
    historical = _historical_framework_paths(target_root, source_set)
    matching: list[str] = []
    differing: list[str] = []
    present: list[str] = []
    for relative in source_paths:
        target = target_root / relative
        source = source_root / relative
        if not target.exists() and not target.is_symlink():
            continue
        present.append(relative)
        if target.is_symlink() or not target.is_file() or not source.is_file():
            differing.append(relative)
        elif target.read_bytes() == source.read_bytes():
            matching.append(relative)
        else:
            differing.append(relative)
    custom_authority = _custom_authority_paths(
        target_root, source_root, source_set,
    )
    authority_differences = [
        relative for relative in differing
        if relative not in MERGE_FILES and relative not in PRESERVE_FILES
        and relative != "README.md"
    ]
    safe_differences = [
        relative for relative in differing
        if relative in MERGE_FILES or relative in PRESERVE_FILES
        or relative == "README.md"
    ]
    current_framework = CORE_FILES.issubset(set(matching))
    if custom_authority:
        classification = "independent"
        reasons = [
            "existing repository-owned governance or automation was found",
        ]
    elif authority_differences:
        if any(relative in INDEPENDENT_FILES for relative in authority_differences):
            classification = "independent"
            reasons = ["an existing authoritative file differs from the framework"]
        else:
            classification = "ambiguous"
            reasons = ["a framework-shaped file differs without a resolved lineage"]
    elif historical and not current_framework:
        classification = "ambiguous"
        reasons = [
            "historical framework evidence exists without a complete current framework",
        ]
    elif current_framework or matching:
        classification = "current-framework" if current_framework else "partial-framework"
        reasons = ["existing framework files provide explicit current-framework evidence"]
    elif invalid_projects:
        classification = "ambiguous"
        reasons = ["a GameMaker project file exists but is not valid enough to classify"]
    elif not projects:
        classification = "ambiguous"
        reasons = ["no valid GameMaker project or complete framework was found"]
    else:
        classification = "greenfield"
        reasons = ["valid GameMaker project found without meaningful framework authority"]
    return {
        "classification": classification,
        "reasons": reasons,
        "projects": projects,
        "invalid_projects": invalid_projects,
        "framework_files_present": sorted(present),
        "framework_files_matching": sorted(matching),
        "framework_files_differing": sorted(differing),
        "safe_differences": sorted(safe_differences),
        "custom_authority": custom_authority,
        "historical_framework_files": historical,
    }
def _onboarding_readme(source: Path, target: Path) -> bytes:
    if not target.exists():
        return source.read_bytes()
    existing = _read_text(target)
    if ONBOARDING_MARKER in existing or "docs/SETUP.md" in existing:
        return existing.encode("utf-8")
    block = (
        f"\n\n{ONBOARDING_MARKER}\n"
        "## Repository workflow\n\n"
        "This repository uses the GameMaker AI Workflow Template for its "
        "governance, validation, and agent-assisted development workflow. "
        "The game project and its existing topology remain the project\'s own.\n\n"
        "Begin with [greenfield setup and recovery](docs/SETUP.md). Existing "
        "governance or earlier framework lineage must use the "
        "[brownfield adoption plan](docs/ADOPTION.md), and later framework "
        "revisions use the [policy-update procedure](docs/POLICY_UPDATE.md).\n"
    )
    return (existing.rstrip() + block).encode("utf-8")
def _merge_text(source: Path, target: Path) -> bytes:
    existing = _read_text(target).splitlines()
    existing_keys = {line.strip() for line in existing if line.strip()}
    additions = [
        line for line in _read_text(source).splitlines()
        if line.strip() and line.strip() not in existing_keys
    ]
    if not additions:
        return ("\n".join(existing) + ("\n" if existing else "")).encode("utf-8")
    return ("\n".join(existing + additions) + "\n").encode("utf-8")
def _plan_local_writes(
    target_root: Path,
    source_root: Path,
    classification: dict,
    source_paths: list[str],
) -> tuple[list[dict], list[str]]:
    if classification["classification"] in {"independent", "ambiguous"}:
        return [], []
    writes: list[dict] = []
    conflicts: list[str] = []
    for relative in source_paths:
        source = source_root / relative
        target = _safe_destination(target_root, relative)
        if not source.is_file() or source.is_symlink():
            raise SetupError(f"framework source is not a regular file: {relative}")
        if relative == "README.md":
            content = _onboarding_readme(source, target) if target.exists() else source.read_bytes()
            if not target.exists() or target.read_bytes() != content:
                writes.append({
                    "path": relative,
                    "content": content,
                    "expected": target.read_bytes() if target.exists() else None,
                })
            continue
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                conflicts.append(relative)
                continue
            current = target.read_bytes()
            source_bytes = source.read_bytes()
            if current == source_bytes:
                continue
            if relative in MERGE_FILES:
                content = _merge_text(source, target)
                if content != current:
                    writes.append({
                        "path": relative,
                        "content": content,
                        "expected": current,
                    })
            elif relative in PRESERVE_FILES or relative.startswith("assets/"):
                continue
            else:
                conflicts.append(relative)
            continue
        writes.append({
            "path": relative,
            "content": source.read_bytes(),
            "expected": None,
            "kind": "copy",
        })
    return writes, conflicts
def _apply_local_writes(target_root: Path, source_root: Path, writes: list[dict]) -> None:
    with tempfile.TemporaryDirectory(prefix=".workflow-bootstrap-", dir=target_root) as temporary:
        staging = Path(temporary)
        for item in writes:
            staged = staging / item["path"]
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(item["content"])
            source = source_root / item["path"]
            if source.is_file():
                staged.chmod(source.stat().st_mode & 0o777)

        for item in writes:
            destination = _safe_destination(target_root, item["path"])
            expected = item["expected"]
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or not destination.is_file():
                    raise SetupError(f"bootstrap destination changed: {item['path']}")
                if expected is None or destination.read_bytes() != expected:
                    raise SetupError(f"bootstrap destination changed: {item['path']}")
            elif expected is not None:
                raise SetupError(f"bootstrap destination changed: {item['path']}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / item["path"], destination)
def _git(target_root: Path, *arguments: str, env: dict[str, str] | None = None,
         check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(target_root), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )
def _current_branch(target_root: Path) -> str | None:
    result = _git(target_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return (result.stdout.strip() or None) if result.returncode == 0 else None
def _ensure_git_repository(target_root: Path) -> dict:
    """Initialize only an unversioned folder; never rewrite existing history."""
    probe = _git(target_root, "rev-parse", "--show-toplevel")
    created = False
    if probe.returncode != 0:
        initialized = _git(
            target_root, "init", "--quiet", "--template=", "--initial-branch=dev",
        )
        if initialized.returncode != 0:
            raise SetupError(
                "cannot initialize Git repository: "
                + (initialized.stderr.strip() or initialized.stdout.strip())
            )
        created = True
    else:
        actual = Path(probe.stdout.strip()).resolve()
        if actual != target_root.resolve():
            raise SetupError(
                "target must be the Git repository root; refusing to modify its parent"
            )

    branch_result = _git(target_root, "symbolic-ref", "--short", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    commit_result = _git(target_root, "rev-parse", "--verify", "HEAD")
    has_commit = commit_result.returncode == 0
    actions = []
    if created:
        actions.append("initialized a Git repository with dev as its initial branch")
    manual: list[str] = []
    if branch != "dev":
        manual.append(
            "make dev the integration branch through the repository's normal human-owned Git workflow"
        )
    if not has_commit:
        manual.append(
            "review, stage, commit, and push the project and framework files to dev"
        )

    status_result = _git(
        target_root, "status", "--porcelain=v1", "--untracked-files=all",
    )
    dirty_paths = []
    if status_result.returncode != 0:
        manual.append("inspect Git working-tree state before treating setup as complete")
    elif has_commit:
        dirty_paths = [
            line[3:] if len(line) >= 3 else line
            for line in status_result.stdout.splitlines()
            if line
        ]
        if dirty_paths:
            manual.append(
                "review, stage, commit, or resolve the uncommitted repository changes before treating setup as complete"
            )

    lfs = _git(target_root, "lfs", "install", "--local")
    if lfs.returncode == 0:
        actions.append("initialized local Git LFS configuration")
    else:
        manual.append(
            "install Git LFS and rerun bootstrap so configured binary assets use LFS"
        )

    return {
        "created": created,
        "branch": branch,
        "has_commit": has_commit,
        "dirty_paths": dirty_paths,
        "ready": not manual,
        "actions": actions,
        "manual_actions": manual,
    }
def _github_repository(target_root: Path) -> str | None:
    result = _git(target_root, "config", "--get", "remote.origin.url")
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(value)
        if parsed.hostname != "github.com":
            return None
        value = parsed.path.lstrip("/")
    value = value.removesuffix(".git").strip("/")
    try:
        return repository_name(value)
    except argparse.ArgumentTypeError:
        return None
def _command_result(result: subprocess.CompletedProcess[str]) -> dict:
    return {"returncode": result.returncode, "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:]}
def _local_validation(target_root: Path, required_paths: list[str]) -> dict:
    """Validate an uncommitted bootstrap through a temporary Git index."""
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="workflow-bootstrap-index-") as temporary:
        environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        empty = _git(target_root, "read-tree", "--empty", env=environment, check=False)
        if empty.returncode != 0:
            return {
                "status": "failed",
                "reason": "could not prepare an isolated candidate index",
                "commands": {"read_tree": _command_result(empty)},
            }
        add = _git(target_root, "add", "--all", env=environment, check=False)
        if add.returncode != 0:
            return {
                "status": "failed",
                "reason": "could not capture the bootstrap candidate",
                "commands": {"git_add": _command_result(add)},
            }
        framework_add = _git(
            target_root, "add", "--force", "--", *required_paths,
            env=environment, check=False,
        )
        if framework_add.returncode != 0:
            return {
                "status": "failed",
                "reason": "could not capture all framework files",
                "commands": {"git_add_framework": _command_result(framework_add)},
            }
        tree = _git(target_root, "write-tree", env=environment, check=False)
        if tree.returncode != 0:
            return {
                "status": "failed",
                "reason": "could not freeze the bootstrap candidate",
                "commands": {"git_write_tree": _command_result(tree)},
            }

        checker = subprocess.run(
            [
                sys.executable,
                "tools/ci/check_repo.py",
                "--candidate-ref",
                tree.stdout.strip(),
            ],
            cwd=target_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        test_environment = {key: value for key, value in environment.items() if not key.startswith("GIT_")}
        try:
            with candidate_snapshot(target_root, tree.stdout.strip()) as candidate:
                tests = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        "tools/tests",
                        "-p",
                        "test_*.py",
                    ],
                    cwd=candidate.root,
                    env=test_environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            return {
                "status": "failed",
                "reason": "could not materialize the bootstrap candidate for tests",
                "commands": {"candidate_checkout": {"error": str(exc)}},
            }
    status = "complete" if checker.returncode == 0 and tests.returncode == 0 else "failed"
    return {
        "status": status,
        "commands": {
            "repository_policy": _command_result(checker),
            "template_tests": _command_result(tests),
        },
    }
def bootstrap(
    target_root: Path,
    *,
    source_root: Path = TEMPLATE_ROOT,
    repo: str | None = None,
    no_github: bool = False,
    dry_run: bool = False,
    api=None,
    run_tests: bool = True,
) -> dict:
    """Run the resumable local bootstrap and optional verified GitHub setup."""
    target_root = target_root.resolve()
    source_root = source_root.resolve()
    if not target_root.is_dir():
        raise SetupError(f"target is not an existing folder: {target_root}")
    try:
        target_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        if target_root != source_root:
            raise SetupError("target cannot be inside the trusted template checkout")

    source_paths = framework_paths(source_root)
    required = {"AGENTS.md", "GOVERNANCE.md", "PROJECT_POLICY.toml", "tools/setup_github.py"}
    if not required.issubset(source_paths):
        raise SetupError("trusted source does not contain the current framework bundle")
    classification = classify_target(target_root, source_root, source_paths)
    report = {
        "status": "incomplete",
        "target": str(target_root),
        "source": str(source_root),
        "classification": classification,
        "local": {},
        "github": {"status": "skipped" if no_github else "not-selected"},
        "manual_actions": [],
    }

    if classification["classification"] in {"independent", "ambiguous"}:
        report["local"] = {
            "status": "blocked",
            "writes": [],
            "reason": classification["reasons"][0],
        }
        report["manual_actions"].append(
            "use tools/setup_github.py adopt-existing --plan and resolve the "
            "recorded lineage or authority before applying framework changes"
        )
        report["status"] = "blocked"
        return report

    branch = _current_branch(target_root)
    if branch and branch.startswith("human/"):
        report["local"] = {"status": "blocked", "writes": [],
                            "reason": "the current branch is reserved for human-owned work",
                            "git": {"branch": branch}}
        report["manual_actions"].append("switch to an agent-owned branch before rerunning bootstrap; do not modify a human/* branch")
        report["status"] = "blocked"
        return report

    writes, conflicts = _plan_local_writes(
        target_root, source_root, classification, source_paths,
    )
    if conflicts:
        report["local"] = {
            "status": "blocked",
            "writes": [],
            "conflicts": conflicts,
        }
        report["manual_actions"].append(
            "resolve the listed framework-file conflicts and rerun bootstrap"
        )
        report["status"] = "blocked"
        return report

    report["local"]["writes"] = [item["path"] for item in writes]
    report["local"]["unchanged"] = [
        relative for relative in source_paths
        if relative not in report["local"]["writes"]
    ]
    report["local"]["preserved"] = classification["safe_differences"]
    if dry_run:
        report["local"]["status"] = "planned"
        report["status"] = "dry-run"
        report["manual_actions"].append("rerun without --dry-run to apply this local plan")
        return report

    git_state = _ensure_git_repository(target_root)
    report["local"]["git"] = git_state
    report["manual_actions"].extend(git_state["manual_actions"])
    _apply_local_writes(target_root, source_root, writes)

    validation = (
        _local_validation(target_root, source_paths) if run_tests else
        {"status": "skipped", "reason": "template tests explicitly skipped"}
    )
    report["local"]["validation"] = validation
    post_git_state = _ensure_git_repository(target_root)
    post_git_state["created"] = git_state["created"]
    post_git_state["actions"] = git_state["actions"] + post_git_state["actions"]
    git_state = post_git_state
    report["local"]["git"] = git_state
    report["manual_actions"] = list(dict.fromkeys(report["manual_actions"] + git_state["manual_actions"]))
    git_ready = git_state.get("ready", not git_state["manual_actions"])
    report["local"]["status"] = validation["status"]
    if validation["status"] == "complete" and not git_ready:
        report["local"].update({"status": "incomplete",
                                "reason": "required Git setup remains unresolved"})
        if report["github"]["status"] == "not-selected":
            report["github"] = {"status": "incomplete", "reason": "GitHub configuration was deferred until the local Git baseline is committed and ready"}
            report["manual_actions"].append("commit or resolve the local Git changes, then rerun bootstrap before configuring GitHub")
        return report
    if validation["status"] == "failed":
        report["manual_actions"].append(
            "resolve local repository-policy or template-test failures and rerun bootstrap"
        )
        return report
    if validation["status"] == "skipped":
        report["manual_actions"].append(
            "run the repository policy checker and template tests before treating setup as complete"
        )
        return report

    selected_repo = repo or _github_repository(target_root)
    if no_github:
        report["github"] = {
            "status": "skipped",
            "reason": "GitHub configuration was explicitly disabled",
        }
    elif not selected_repo:
        report["github"] = {
            "status": "incomplete",
            "reason": "no GitHub owner/repository was supplied or inferred from origin",
        }
        report["manual_actions"].append(
            "create or identify the GitHub repository, push the reviewed dev branch, "
            "then rerun bootstrap with --repo OWNER/REPOSITORY"
        )
    else:
        try:
            if api is None:
                messages = configure_repository(selected_repo)
            else:
                messages = configure_repository(selected_repo, api=api)
        except SetupError as exc:
            report["github"] = {
                "status": "incomplete",
                "repository": selected_repo,
                "error": str(exc),
            }
            report["manual_actions"].append(
                "resolve the GitHub permission, branch, or repository-state error and rerun bootstrap"
            )
        else:
            report["github"] = {
                "status": "complete",
                "repository": selected_repo,
                "messages": messages,
            }

    local_ok = validation["status"] == "complete" and git_ready
    github_ok = report["github"]["status"] in {"complete", "skipped"}
    report["status"] = "complete" if local_ok and github_ok else "incomplete"
    return report
def _print_report(report: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(f"greenfield-bootstrap: {report['status']}")
    print(f"greenfield-bootstrap: classification={report['classification']['classification']}")
    local = report.get("local", {})
    if local:
        print(f"greenfield-bootstrap: local={local.get('status', 'not-started')}")
        for path in local.get("writes", []):
            print(f"greenfield-bootstrap: installed {path}")
    github = report.get("github", {})
    print(f"greenfield-bootstrap: github={github.get('status')}")
    if github.get("repository"):
        print(f"greenfield-bootstrap: repository={github['repository']}")
    for action in report.get("manual_actions", []):
        print(f"greenfield-bootstrap: action required: {action}")
def main(argv: list[str] | None = None) -> int:
    """Parse the explicit bootstrap command and preserve resumable status."""
    parser = argparse.ArgumentParser(
        description="Install the current framework into a greenfield GameMaker folder."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="target folder")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=TEMPLATE_ROOT,
        help="trusted template checkout (default: this template checkout)",
    )
    parser.add_argument("--repo", type=repository_name, metavar="OWNER/REPOSITORY")
    github = parser.add_mutually_exclusive_group()
    github.add_argument(
        "--no-github",
        action="store_true",
        help="intentionally perform local setup without GitHub configuration",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.no_github and args.repo:
        parser.error("--repo cannot be combined with --no-github")
    try:
        report = bootstrap(
            args.root,
            source_root=args.source_root,
            repo=args.repo,
            no_github=args.no_github,
            dry_run=args.dry_run,
            run_tests=not args.skip_tests,
        )
    except (OSError, SetupError, ValueError) as exc:
        print(f"greenfield-bootstrap: {exc}", file=sys.stderr)
        return 2
    _print_report(report, args.as_json)
    if report["status"] in {"complete", "dry-run"}:
        return 0
    return 1
if __name__ == "__main__":
    raise SystemExit(main())
