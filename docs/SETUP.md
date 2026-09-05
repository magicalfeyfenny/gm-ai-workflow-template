# Setup after creating a repository

Use this checklist for a repository generated from this GameMaker workflow
template.

For an existing repository, start with the read-only
[adoption and recovery plan](ADOPTION.md). That route inventories current
state and verifies an existing release before proposing separately authorized
changes. Do not run the generated-repository bootstrap as an adoption probe.

This document owns setup procedure. Repository-change lifecycle policy remains
in [GOVERNANCE.md](../GOVERNANCE.md#authority).

## Prerequisites

Install:

- Git;
- Git LFS;
- Python 3.12 or later;
- GitHub CLI (`gh`).

Authenticate `gh` as a repository administrator. The authenticated identity
needs repository Administration, Contents, and Issues write access so the
setup tool can configure settings and rulesets, create `main`, and manage
labels.


## Configure GitHub

1. Create the repository from this template. Its initial branch must be the
   template's default `dev` branch.
   When creating the repository, do not select "Include all branches".
   Generate it from the template's default `dev` branch only.
2. Clone the generated repository and enter its root directory.
3. Initialize Git LFS for the local account:

   ```sh
   git lfs install
   ```

4. Check GitHub CLI authentication:

   ```sh
   gh auth status
   ```

5. Run the bootstrap tool with the generated repository's full name:

   ```sh
   python3.12 tools/setup_github.py --repo OWNER/REPOSITORY
   ```

The tool requires an explicit repository name. It creates `main` from the
current `dev` commit only when `main` is absent, makes `dev` the default,
enables squash merging and auto-merge, disables merge commits, rebase merges,
and automatic branch deletion, ensures the eight governance labels, and
installs the active `dev-protection` and `main-release` rulesets.

The tool creates the labels used by the Governance
[low-risk](../GOVERNANCE.md#low-risk-changes),
[manual](../GOVERNANCE.md#manual-and-high-risk-changes), and
[blocked-work](../GOVERNANCE.md#milestone-commits-and-draft-publication) paths.
It renames a legacy `blocked` label to `work:blocked`, preserving assignments
when the new name is absent.

Both rulesets grant repository administrators pull-request-only bypass.
[Human-created changes](../GOVERNANCE.md#human-created-changes) owns the limits
on that bypass and protected-branch behavior.

The tool is safe to rerun: it never moves an existing `main`, and it updates
the named labels and rulesets in place. Review its output if it reports that
`main` already existed.

## Configure governed merge authentication

The built-in Actions `GITHUB_TOKEN` cannot provide the identity context needed
for GitHub-native linked-issue closure when the low-risk workflow performs the
merge. Configure a dedicated GitHub App for that final merge call:

1. Register a private GitHub App owned by the repository owner. Disable
   webhooks and grant no account or organization permissions.
2. Grant exactly these repository permissions:
   - Contents: read and write;
   - Issues: read and write;
   - Pull requests: read and write.
   Metadata read access is implicit.
3. Install the App only on the generated repository. Do not grant access to
   other repositories.
4. Add the App client ID as the repository Actions variable
   `GOVERNED_MERGE_APP_CLIENT_ID`.
5. Generate a private key and store the complete PEM as the repository Actions
   secret `GOVERNED_MERGE_APP_PRIVATE_KEY`. Never commit the key.

Provisioning, installation, private-key rotation, and revocation are
human-owned setup steps. The workflow uses the built-in job token for CI
evidence, current-PR reads, readiness, and stale auto-merge revocation. It
mints a separate installation token limited to the current repository and the
three permissions above, uses it only for the final exact-head merge, and
revokes it when the job ends. No personal access token is required or
supported. If the App variable or secret is absent, automatic low-risk merging
fails closed before the merge call.

After provisioning, verify this identity path with one fresh, bounded
documentation-only issue and low-risk pull request targeting `dev`. Let the
repository automation mark the pull request ready and merge its exact head;
do not manually ready, merge, or close it. Confirm that Required CI used the
current pull-request metadata, the App performed the merge, and GitHub natively
closed the linked issue. Preserve the issue, pull request, and workflow-run
evidence if any part of that smoke check fails.

## Register pinned imported libraries

Follow [Source structure](../GOVERNANCE.md#source-structure) when a pinned,
read-only imported source file needs an exception. Add an authorized exact path
to `structure.large_file_exceptions` in `PROJECT_POLICY.toml`:

```toml
large_file_exceptions = [
    "project/game/scripts/vendor_library/vendor_library.gml",
]
```

Register the exception as bounded governed work, then run the validation below.

## Validate the generated repository

From the generated repository root, run:

```sh
python3.12 tools/ci/check_repo.py
python3.12 -m unittest discover -s tools/tests -p 'test_*.py'
git diff --check
```

## Remaining manual setup

The GitHub bootstrap tool does not perform these project-specific or
human-owned steps:

1. Initialize the GameMaker project under `project/`.
2. Download the latest GM-Testing-Library release when the GameMaker project
   is initialized, pin that version, and add the project's GameMaker tests.
3. In Codex, manually create whichever scheduled automations the generated
   repository should use. Choose each automation's schedule and execution
   identity:
   - Project Steward uses
     [templates/codex/project-steward.txt](../templates/codex/project-steward.txt)
     to audit the repository and create evidence-backed issues without changing
     implementation.
   - Governed Change uses
     [templates/codex/governed-change.txt](../templates/codex/governed-change.txt)
     to select at most one eligible existing issue and execute its governed
     workflow.
   Keep these automations separate: Project Steward creates and tracks
   actionable issue work, while Governed Change executes one existing
   agent-workable issue.
4. Add any game-specific hosted runner configuration or secrets needed by the
   GameMaker tests. Do not infer visual or runtime success from the Python
   policy checks.

If the bootstrap tool completes successfully, no manual GitHub branch,
default-branch, merge-strategy, label, or ruleset configuration remains.

Repository-local Codex skills are stored directly under `.agents/skills/`.
They are included automatically when the repository is created from this
template.
