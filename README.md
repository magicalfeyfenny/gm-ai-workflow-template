# GameMaker AI Workflow Template

This repository is a reusable governance scaffold for GameMaker projects, not a
game. It lets agents work in small, auditable units while humans retain
authority over high-risk and release decisions.

## Governance overview (non-normative)

This README is a user-facing summary, not a source of rules. The authoritative
workflow and rationale live in [GOVERNANCE.md](GOVERNANCE.md#authority), while
[PROJECT_POLICY.toml](PROJECT_POLICY.toml) owns executable paths, formats,
limits, and risk patterns.

Normal agent-governed work starts with one atomic issue. Broader requests split
into independently governed sub-issues, each with its own risk. Each issue
branches from current `origin/dev`, uses an issue-numbered branch, and opens a
draft pull request after the first meaningful, tested milestone. Blocked work
waits until its blockers are resolved.

Validation happens in three stages: focused checks support each milestone,
the complete change receives whole-issue local validation, and hosted CI then
verifies the exact pull-request head, body, and labels. Completion metadata is
added only after the whole change is locally valid.

Risk determines the final path. Eligible completed low-risk work targeting
`dev` can be marked ready and squash-merged by repository automation after its
final hosted evidence passes. High-risk or manually handled work remains a
draft for human review, readiness, and merge. Automatic high risk is reserved
for authority-bearing governance, release-bound work, and exceptional
structural size; ordinary game code, content, project metadata, and assets can
use the low-risk path. Any change can still be classified high risk when its
actual circumstances warrant it.

`main` is release-only, and releases require explicit human authorization.
Human-created work uses a separate protected lane that agents do not modify.

## Start here

Follow [docs/SETUP.md](docs/SETUP.md) when creating a repository from this
template. For day-to-day work, [AGENTS.md](AGENTS.md#authority-and-task-routing)
routes each task to only the governance sections and local skill it needs.
