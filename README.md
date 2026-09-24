# GameMaker AI Workflow Template

This repository is a reusable governance and tooling scaffold for GameMaker
projects. It is not a game. It gives a project a canonical repository policy,
machine-verifiable checks, GitHub workflow configuration, reusable Codex task
prompts, and an explicit boundary between agent work and human authority.

## Governance overview (non-normative)

This overview is navigation only. The authoritative workflow and rationale
live in [GOVERNANCE.md](GOVERNANCE.md#authority), executable values live in
[PROJECT_POLICY.toml](PROJECT_POLICY.toml), and task routing starts in
[AGENTS.md](AGENTS.md#authority-and-task-routing).

## What it provides

- authoritative workflow rules in [GOVERNANCE.md](GOVERNANCE.md#authority);
- executable paths, asset formats, storage rules, and risk limits in
  [PROJECT_POLICY.toml](PROJECT_POLICY.toml);
- repository-policy, asset, storage, CI, and issue-contract tooling under
  [the tools directory](tools/setup_github.py);
- GitHub workflows, issue/PR support, and portable branch ruleset recipes;
- repository-local Codex skills and automation prompt templates; and
- a resumable [greenfield bootstrap](docs/SETUP.md) for a new GameMaker folder
  or a repository generated from this template.

## Start here

Choose the path that matches the repository before changing anything:

- A valid GameMaker project with no meaningful governance: run the
  [greenfield bootstrap](docs/SETUP.md).
- An existing repository with independent governance, earlier framework
  lineage, or uncertain history: use the read-only
  [brownfield adoption plan](docs/ADOPTION.md).
- A repository that already adopted this framework and needs a newer upstream
  policy: use the [bounded policy-update procedure](docs/POLICY_UPDATE.md).

The bootstrap detects the latter cases and stops before overwriting authority.
It discovers an existing GameMaker project instead of moving it into a
template-specific directory. Read [docs/SETUP.md](docs/SETUP.md) for commands,
verification, recovery, and the setup actions that remain human-owned.

## Day-to-day workflow

Normal agent-governed work starts with one coherent issue, branches from the
current `origin/dev`, and opens a draft pull request after its first tested
milestone. Focused checks support milestones, whole-issue local evidence comes
before completion metadata, and hosted CI verifies the exact pull-request
candidate. See [AGENTS.md](AGENTS.md#authority-and-task-routing) for task
routing and [GOVERNANCE.md](GOVERNANCE.md#authority) for the authoritative
rules.

`dev` is the integration branch. `main` is release-only. Low-risk and
medium-risk work can use the automatic completion path when its evidence is
current; high-risk and human-created work stays at the human review, readiness,
and merge gates. Release and publication actions always require explicit human
authority.
