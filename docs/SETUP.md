# Setup after creating a repository

Use this checklist for a repository generated from this GameMaker workflow
template.

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

The `work:complete` label is the positive completion signal for low-risk
automation. Milestone draft PRs remain drafts until the full issue scope is
finished, the closing line is added, and this label is applied.

The equivalent manual completion signal is `work:review-ready`. The setup tool
also renames a legacy `blocked` label to `work:blocked`, preserving its current
assignments and behavior when the new name is not already present.

Both rulesets grant repository administrators pull-request-only bypass. The
bypass is reserved for manually merging PRs labeled `human-created`; it does
not permit direct pushes to protected branches.

The tool is safe to rerun: it never moves an existing `main`, and it updates
the named labels and rulesets in place. Review its output if it reports that
`main` already existed.

## Validate the generated repository

Run:

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
3. Make the bundled skills under `skills/` available to Codex. For
   repository-scoped discovery, link them under `.agents/skills/`; Codex
   supports symlinked skill directories.
4. In Codex, manually create whichever scheduled automations the generated
   repository should use. Choose each automation's schedule and execution
   identity:
   - Project Steward uses `templates/codex/project-steward.txt` to audit the
     repository and create evidence-backed issues without changing
     implementation.
   - Governed Change uses `templates/codex/governed-change.txt` to select at
     most one eligible existing issue and execute its governed branch,
     validation, draft pull request, risk, and completion workflow.
   Keep these automations separate: Project Steward creates and tracks
   actionable issue work, while Governed Change executes one existing
   agent-workable issue.
5. Add any game-specific hosted runner configuration or secrets needed by the
   GameMaker tests. Do not infer visual or runtime success from the Python
   policy checks.

If the bootstrap tool completes successfully, no manual GitHub branch,
default-branch, merge-strategy, label, or ruleset configuration remains.
