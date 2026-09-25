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
| Authored or derived asset | Use the [Asset production skill](.agents/skills/asset-production/SKILL.md). |
| GameMaker structured data | Use the [GameMaker production skill](.agents/skills/gamemaker-production/SKILL.md). |
| Issue and PR audit | Use the [Project Steward skill](.agents/skills/project-steward/SKILL.md) and [Issue authority](GOVERNANCE.md#issue-authority). |
| Release | Only when explicitly authorized, read [Releases](GOVERNANCE.md#releases) and the governed lifecycle routes. |
| Generated-repository setup | Follow [docs/SETUP.md](docs/SETUP.md). |
| Existing-repository adoption or recovery | Start with the read-only [adoption procedure](docs/ADOPTION.md). |
| Update previously adopted upstream policy | Follow the [policy-update procedure](docs/POLICY_UPDATE.md) through governed-change. |

Read an anchored section with its subsections; follow sibling sections only
when the task routes to them. Do not load unrelated governance sections merely
because the repository is governed.

## Tooling

Repository tooling requires Python 3.12 or later. Use
`python3 tools/ci/run_repository_checks.py` for dependency-sensitive policy
and test commands; it follows the repository's explicit interpreter, a
validated `.venv`, a compatible ambient interpreter with the pinned
dependencies, and then a bounded isolated environment. Standalone commands
must likewise use any compatible Python 3.12-or-later interpreter.

## Standing permission

On the current issue-scoped branch, agents may commit each coherent milestone
after [Stage 1 evidence](GOVERNANCE.md#stage-1-milestone-evidence), push it, and
open or update its draft PR under
[Milestone commits and draft publication](GOVERNANCE.md#milestone-commits-and-draft-publication).
That permission does not grant readiness, merge, release, or publication
authority. Completion metadata remains an evidence-backed transition under
the [Completion transition](GOVERNANCE.md#completion-transition). A scheduled
worker may carry eligible low- or medium-risk work through whole-issue Stage 2 evidence,
the immediate pre-transition issue re-fetch, completion metadata, and fresh
Stage 3 evidence; existing automatic low/medium automation owns readiness and squash
auto-merge, while high-risk and manual-path work waits for human review,
readiness, and merge.

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
- Issue authority is repository-local. A related issue elsewhere grants no
  authority; any cross-repository work requires separate explicit human
  direction naming the target repository and work to perform. As part of this
  issue, do not create, modify, claim, or execute issues, branches, PRs, files,
  or other work in another repository.
- Treat complexity, importance, and ordinary scope as medium-risk signals, not
  high-risk bases; voluntary high risk requires a configured structured basis.
- Do not force-push, automatically delete branches, or rewrite history merely
  to simplify it.
- Add completion metadata only after the entire issue scope has valid
  [Stage 2 evidence](GOVERNANCE.md#stage-2-whole-issue-local-evidence), then use
  the [Completion transition](GOVERNANCE.md#completion-transition) and path
  selected by [Risk](GOVERNANCE.md#risk).
- Before completion metadata, complete the bounded
  [adversarial review and adjudication](GOVERNANCE.md#adversarial-review-and-adjudication)
  stage. Use its validated lifecycle outcome as the implementation and handoff
  input; the actual risk tier provides one correction retry for low and two for
  medium or high, with no autonomous reset after handoff.
- High-risk and `manual-merge` work waits for human review, readiness, and
  merge after valid [Stage 3 evidence](GOVERNANCE.md#stage-3-hosted-pr-evidence).
- Do not merge into `main` or create release builds, tags, releases, or
  publication without explicit human authority.
