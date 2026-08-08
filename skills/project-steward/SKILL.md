---
name: project-steward
description: Audit repository issues and pull requests and create bounded issues from concrete evidence without modifying code.
---

# Project steward

Inspect open issues and PRs.

Report:

- duplicates;
- issues without actionable acceptance criteria;
- PRs without linked issues;
- blocked PRs;
- persistent CI failures;
- clearly abandoned or superseded tracking.

Create an issue only from concrete evidence:

- a reproducible CI failure not already tracked;
- an explicit TODO(ISSUE) marker;
- an explicit user-authored backlog item.
- a merged `human-created` PR that provides concrete evidence for a bounded
  repository-standardizing issue.

Search for duplicates before creating anything.

Every created issue contains:

- summary;
- acceptance criteria;
- bounded scope;
- expected risk;
- source evidence.

Assign created issues to the current user.

Create no more than five issues per run.

Do not:

- modify code;
- treat an open `human-created` PR as a governance defect or work item;
- modify, review, validate, label, ready, or merge a `human-created` PR;
- mark PRs ready;
- merge PRs;
- close stale issues automatically;
- create speculative work.
