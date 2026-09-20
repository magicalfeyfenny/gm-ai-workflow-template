# Greenfield bootstrap

Use this procedure when starting a repository from a valid GameMaker project
or from a repository freshly generated from this template. The bootstrap
installs the current repository-local framework, verifies it, and configures
the applicable GitHub settings when the remote state and credentials permit
it.

This is a greenfield route. It does not adopt, overwrite, or reconcile an
existing governance system. For a repository with meaningful governance,
earlier framework lineage, or uncertain partial setup, use the read-only
[adoption and recovery plan](ADOPTION.md) instead. An already-adopted
repository taking a newer framework revision uses the
[bounded policy-update procedure](POLICY_UPDATE.md).

Repository-change lifecycle rules remain authoritative in
[GOVERNANCE.md](../GOVERNANCE.md#authority). The bootstrap is a setup tool, not
a second policy authority or an adoption registry.

## Prerequisites

Install and authenticate:

- Git;
- Git LFS;
- Python 3.12 or later; and
- GitHub CLI (`gh`) when GitHub configuration is wanted.

The bootstrap runs the full repository-local test suite. Dependency-sensitive
checks use the repository's bounded environment router. It reads an explicit
interpreter from `.python-version`, then validates `.venv`, then validates the
ambient Python against the Python 3.12-or-later and pinned-dependency contract,
and creates a temporary isolated environment from a compatible Python only
when those routes do not produce a usable environment. It installs only the
pinned requirements into isolated environments.

To preinstall the pinned dependencies in a chosen isolated environment, use:

```sh
/path/to/isolated-python -m pip install -r /path/to/gm-ai-workflow-template/tools/tests/requirements.txt
```

For a repository already generated from the template, run the same command
from that repository with `tools/tests/requirements.txt` as the path. An
isolated Python 3.12-or-later virtual environment is recommended. Do not treat a
missing dependency in the ambient interpreter as a project failure when the
router can satisfy the check in isolation.

The GitHub identity used for configuration needs permission to read and update
repository settings, labels, and rulesets. If the identity lacks a capability,
the tool leaves the local work resumable and reports the missing operation.

## Run the bootstrap

From a trusted clone of this template, run one of these paths.

### Existing GameMaker folder

The folder may already contain a Git repository. It may also be unversioned;
the tool initializes one with `dev` as its initial branch in that case. The
GameMaker project stays where it is.

```sh
python3.12 /path/to/gm-ai-workflow-template/tools/setup_github.py bootstrap \
  --source-root /path/to/gm-ai-workflow-template \
  --root /path/to/my-game \
  --repo OWNER/REPOSITORY
```

If the GitHub repository is not ready yet, intentionally perform the local
portion first:

```sh
python3.12 /path/to/gm-ai-workflow-template/tools/setup_github.py bootstrap \
  --source-root /path/to/gm-ai-workflow-template \
  --root /path/to/my-game \
  --no-github
```

Review the result, stage and commit the project and framework files on `dev`,
push that branch to the intended GitHub repository, and rerun without
`--no-github` to configure and verify the hosted settings.

### Repository generated from this template

Clone the generated repository and run the same command from its root. The
repository name is inferred from a GitHub `origin` when possible, so the
explicit `--repo` argument is optional.

```sh
cd /path/to/generated-repository
python3.12 tools/setup_github.py bootstrap --repo OWNER/REPOSITORY
```

This path recognizes the framework already present in the generated tree,
verifies it, and performs the GitHub setup. It does not move an existing
`main`; `main` is created from the observed `dev` commit only when absent.

Use `--dry-run --json` to inspect classification and planned local writes
without initializing Git, changing files, or calling GitHub:

```sh
python3.12 tools/setup_github.py bootstrap \
  --root /path/to/my-game --dry-run --json
```

## What the tool establishes

The source tree is read directly from the trusted template checkout. The
bootstrap installs the current canonical Governance, policy, repository-local
skills, validation and CI tooling, issue/PR support, ruleset recipes, setup
documentation, Codex prompt templates, and framework asset-policy scaffolding.
It also merges the canonical storage lines into an existing `.gitignore` or
`.gitattributes` without discarding project-specific lines.

Existing project content is preserved. In particular, the tool discovers valid
`.yyp` or legacy `.gmx` projects in place, does not move or rewrite them,
preserves an existing asset export manifest, and keeps a project README while
adding one idempotent link to setup, adoption, and policy-update guidance.
Existing framework files are left unchanged when identical. A conflicting
framework authority is never silently replaced.

## Classification and output

The command classifies the target before writing:

| Classification | Meaning | Action |
| --- | --- | --- |
| `greenfield` | A valid GameMaker project exists without meaningful framework authority. | Install the framework. |
| `partial-framework` | Existing files are an explicit subset of the current framework without prior-lineage evidence. | Complete the missing framework files. |
| `current-framework` | The current framework is already present. | Verify and configure only what is applicable. |
| `independent` | Existing project governance or automation would be overwritten by greenfield setup. | Stop and use `adopt-existing --plan`. |
| `ambiguous` | A framework-shaped conflict, invalid project, or incomplete evidence cannot be classified safely. | Stop and resolve the comparison basis. |

Historical framework evidence with only a partial surviving framework is
`ambiguous`, even when one surviving file matches the current source. A
complete current core framework is sufficient evidence for the resumable
`current-framework` path.

The report separates local work, GitHub work, validation, and remaining human
actions. Exit status `0` means local validation and the requested hosted
portion passed, GitHub was explicitly skipped with `--no-github`, and required
Git setup is ready. Exit status `1` means setup is incomplete or blocked and
can be resumed; this includes an uncommitted result or an ordinary non-`dev`
branch that still needs human resolution. Exit status `2` means the command or
target was invalid.
The command never treats a permission failure, missing `dev`, validation
failure, or ambiguous lineage as success.

## Configure GitHub

When a repository is supplied or inferred, the existing
[setup tool](../tools/setup_github.py) updates and then verifies:

- `dev` as the default branch;
- `main` created from `dev` only when it is absent;
- squash merging and auto-merge enabled;
- merge commits, rebase merges, and automatic branch deletion disabled;
- the labels in `REQUIRED_LABELS`; and
- the active `dev-protection` and `main-release` ruleset recipes. API-managed
  response fields and stronger or unowned ruleset settings are preserved.
  Framework-owned branch applicability conditions and bypass actors must still
  match; an exclusion of a managed branch is reconciled rather than accepted.
  Required check contexts are reconciled by context so differing integration
  metadata does not create duplicate logical checks.

The tool does not create a GitHub repository, push commits, move an existing
branch, install a GitHub App, or make security and ownership decisions. Those
steps remain human-owned. If configuration stops after some successful API
calls, rerun the same command after fixing the reported permission or branch
condition; named settings, labels, and rulesets are reconciled in place.

## Validate the generated repository

After local installation, the tool freezes the working tree into a temporary
candidate Git index, uses that stored tree for repository policy, and
materializes the same tree into an isolated test checkout before running:

```sh
python3 tools/ci/run_repository_checks.py repository-policy \
  --baseline-ref origin/dev --candidate-ref CANDIDATE_TREE
python3 tools/ci/run_repository_checks.py tests
```

The router prints the selected route and distinguishes environment setup
failure from a repository-policy or test failure.

The real index and working-tree contents are not staged by this verification,
and user-owned changes are not committed or discarded. The candidate must pass
both checks, and the post-bootstrap Git state must be ready, before the tool
attempts hosted mutation. A validated but uncommitted candidate remains
incomplete until the intended local baseline is committed on `dev`.
`--skip-tests` is available only for diagnosis; it reports incomplete and does
not configure GitHub.

The label set is the executable inventory used by the setup tool. Its shared
authority is the [Inventory authority](../GOVERNANCE.md#inventory-authority)
rule; the setup command does not maintain a second label count in this guide.

## Remaining human-owned setup

The bootstrap cannot safely decide or perform actions that require project
ownership, credentials, security boundaries, or product decisions. Review and
complete the reported items that apply:

1. Create or select the GitHub repository, review the project and framework
   files, commit the intended tree to `dev`, and push it before hosted setup.
   Bootstrap may install into an ordinary existing non-`dev` branch, but it
   remains incomplete until the repository's normal owner resolves that branch.
   It never writes to a reserved `human/*` branch.
2. Install and authenticate Git LFS when the project uses configured binary
   asset formats.
3. Initialize or extend the GameMaker project tests and pin the required
   GM-Testing-Library release. Connect game-specific hosted runners and secrets
   through the [CI extension procedure](CI.md).
4. Create Codex scheduled automations deliberately in the Codex app, choosing
   their schedule and execution identity. Use the
   [Project Steward template](../templates/codex/project-steward.txt) for
   evidence-backed issue audits and the
   [Governed Change template](../templates/codex/governed-change.txt) for
   executing one existing issue at a time.
5. If automatic low/medium merging is wanted, provision the dedicated GitHub App
   described in [governed merge authentication](#configure-governed-merge-authentication).

### Configure governed merge authentication

The low/medium automatic merge workflow needs a repository-scoped GitHub App for its final
linked-issue merge call. A human repository owner must register and install a
private App with only Contents, Issues, and Pull requests read/write access,
then store its client ID as `GOVERNED_MERGE_APP_CLIENT_ID` and its complete PEM
private key as `GOVERNED_MERGE_APP_PRIVATE_KEY`. Never commit the key. Verify
the identity path with a fresh bounded automatic-path documentation change, as
described in the existing workflow policy; provisioning and revocation remain
human-owned.

## Pinned imported libraries

When a pinned, read-only imported source file needs a large-file exception,
follow [Source structure](../GOVERNANCE.md#source-structure) and register its
exact path in `structure.large_file_exceptions`. Do not use bootstrap to hide
ordinary source growth or to replace a project-owned library.
