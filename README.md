# GameMaker AI Workflow Template

A reusable production-workflow template for governed GameMaker repositories.

It provides finite issue, branch, risk, CI, source-structure, content-data, and
source/runtime asset rules without assuming a specific game.

## Create a project

Create a repository from this template, then follow [docs/SETUP.md](docs/SETUP.md)
to configure its GitHub branches, labels, merge settings, and rulesets.

Place the GameMaker project under `project/`. Read `AGENTS.md`, `GOVERNANCE.md`,
and `PROJECT_POLICY.toml` before making repository changes.

## Governance at a glance

`GOVERNANCE.md` is the authoritative workflow policy, while
`PROJECT_POLICY.toml` supplies the executable structure, asset, and risk
limits. `AGENTS.md` gives contributors the repository-specific working rules.

- `dev` is the default integration branch and `main` is release-only. Normal
  agent-governed work starts from the current `origin/dev` on a branch named
  `work/<issue>-<slug>`, never from local `dev`; release work uses
  `release/<issue>-v<semver>`.
- Each governed change has one GitHub issue, one issue-numbered branch,
  coherent milestone commits, one draft pull request, required CI, and exactly
  one of the `risk:low` or `risk:high` labels.
- Paths and change-size limits in `PROJECT_POLICY.toml` can require high risk.
  A change may also be classified high risk voluntarily, but an automatically
  high-risk change cannot be downgraded.
- The `human/` branch namespace and the `human-created` label identify work
  controlled by a human. That work follows a separate manual path and must not
  be modified, reviewed, validated, or advanced by agents.
- Source files have one primary responsibility and stay within the configured
  size limit. Editable assets live under `assets/source`, derived assets under
  `assets/runtime`, and every derived runtime asset is recorded in
  `assets/exports.json`. Canonical GameMaker data lives once under `content/`
  as JSON.

See [GOVERNANCE.md](GOVERNANCE.md) and
[PROJECT_POLICY.toml](PROJECT_POLICY.toml) for the complete rules.

## Governed change workflow

1. Start with a bounded issue that states the acceptance criteria, scope, and
   expected risk.
2. Fetch `origin/dev`, create `work/<issue>-<slug>` from that remote branch,
   and implement only the issue scope.
3. Validate and commit each coherent milestone. After the first meaningful
   commit, push the branch and open a draft pull request into `dev`. Keep the
   closing line out of the pull request while work remains.
4. Before declaring the issue complete, run:

   ```sh
   python3.12 tools/ci/check_repo.py --baseline-ref origin/dev
   python3.12 -m unittest discover -s tools/tests -p 'test_*.py'
   git diff --check
   ```

   Run relevant GameMaker tests as soon as the project provides them.
5. When the entire change is complete and validated, choose the completion
   path required by its risk and labels:

   - A low-risk `dev` pull request without `manual-merge` gets exactly one
     `Closes #<issue>` line and the `work:complete` label. After required CI
     passes for the current head, body, and labels, automation marks it ready
     and configures squash auto-merge. Older runs for the same head cannot
     authorize a newer metadata state.
   - A high-risk or `manual-merge` pull request gets exactly one
     `Closes #<issue>` line and the `work:review-ready` label. It then waits for
     a human to review it, mark it ready, and merge it.

Agent-governed pull requests into `dev` or `main` run four required checks: PR
policy, repository policy, tests, and format. A `work:blocked` pull request
stays untouched until its blockers are resolved. Releases and every
agent-governed pull request into `main` always use the high-risk manual path;
release builds, tags, and publication are manual too.
