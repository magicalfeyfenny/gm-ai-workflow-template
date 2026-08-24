# GameMaker AI Workflow Template

A reusable production-workflow template for governed GameMaker repositories.

It provides finite issue, branch, risk, CI, source-structure, content-data, and
source/runtime asset rules without assuming a specific game.

## Create a project

This template supplies the reusable governed workflow scaffold. Each generated
repository must still initialize its project-specific GameMaker project under
`project/` and download and pin the latest GM-Testing-Library release.

After creating a repository from the template, follow
[docs/SETUP.md](docs/SETUP.md). Start repository work from the task routes in
[AGENTS.md](AGENTS.md#authority-and-task-routing).

## Governance overview (non-normative)

This section is navigation only. It does not establish or restate repository
rules.

| Need | Destination |
| --- | --- |
| Workflow, permissions, rationale, and lifecycle | [GOVERNANCE.md](GOVERNANCE.md#authority) |
| Executable paths, formats, limits, and risk patterns | [PROJECT_POLICY.toml](PROJECT_POLICY.toml) |
| Task routing and critical pre-mutation stops | [AGENTS.md](AGENTS.md#authority-and-task-routing) |
| Repository setup | [docs/SETUP.md](docs/SETUP.md) |

Use the task-specific Governance sections linked by AGENTS and the local skill
for the work. Release rules are relevant only to explicitly authorized release
work.
