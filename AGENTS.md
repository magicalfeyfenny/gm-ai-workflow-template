# GameMaker project instructions

## Authority and task routing

[GOVERNANCE.md](GOVERNANCE.md#authority) owns normative repository rules and
rationale. [PROJECT_POLICY.toml](PROJECT_POLICY.toml) owns executable values.
This file routes work, exposes standing permission, and repeats only the
critical stops that must be visible before mutation. The
[README governance overview](README.md#governance-overview-non-normative) is
non-normative.

Before modifying the repository, follow only the routes relevant to the task:

| Task | Required route |
| --- | --- |
| Governed repository change | Use the [governed-change skill](.agents/skills/governed-change/SKILL.md), then the Governance sections it names. |
| Any repository-owned source or imported-library registration | Read [Source structure](GOVERNANCE.md#source-structure) and `[structure]` in `PROJECT_POLICY.toml`. |
| GameMaker production code | Use the [GameMaker production skill](.agents/skills/gamemaker-production/SKILL.md). The source route above also applies. |
| Derived asset | Use the [GameMaker production skill](.agents/skills/gamemaker-production/SKILL.md). |
| GameMaker structured data | Use the [GameMaker production skill](.agents/skills/gamemaker-production/SKILL.md). |
| Issue and PR audit | Use the [Project Steward skill](.agents/skills/project-steward/SKILL.md) and [Issue authority](GOVERNANCE.md#issue-authority). |
| Release | Only when explicitly authorized, read [Releases](GOVERNANCE.md#releases) and the governed lifecycle routes. |
| Repository setup | Follow [docs/SETUP.md](docs/SETUP.md). |

Do not load unrelated governance sections merely because the repository is
governed.

## Tooling

Repository tooling requires Python 3.12 or later. Use `python3.12` for policy
and test commands.

## Standing permission

On the current issue-scoped branch, agents may commit each coherent milestone
after [Stage 1 evidence](GOVERNANCE.md#stage-1-milestone-evidence), push it, and
open or update its draft PR under
[Milestone commits and draft publication](GOVERNANCE.md#milestone-commits-and-draft-publication).
That permission does not grant completion, readiness, merge, release, or
publication authority.

## Critical stops

These reminders intentionally repeat authoritative Governance rules because
they must be visible before mutation:

- Start agent-governed work from current `origin/dev`, never local `dev`, and
  never create, switch to, push to, or modify a `human/*` branch.
- If a PR uses a `human/*` branch or has `human-created`, stop. Do not modify,
  review, validate, label, ready, or merge it, and never invoke a ruleset
  bypass.
- Do not work a PR labeled `work:blocked` until its blockers are resolved.
- Keep the change bounded to its issue and do not perform unrelated cleanup.
- Do not force-push, automatically delete branches, or rewrite history merely
  to simplify it.
- Add completion metadata only after the entire issue scope has valid
  [Stage 2 evidence](GOVERNANCE.md#stage-2-whole-issue-local-evidence), then use
  the [Completion transition](GOVERNANCE.md#completion-transition) and path
  selected by [Risk](GOVERNANCE.md#risk).
- High-risk and `manual-merge` work waits for human review, readiness, and
  merge after valid [Stage 3 evidence](GOVERNANCE.md#stage-3-hosted-pr-evidence).
- Do not merge into `main` or create release builds, tags, releases, or
  publication without explicit human authority.
