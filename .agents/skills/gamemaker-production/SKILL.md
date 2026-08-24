---
name: gamemaker-production
description: Make production GameMaker changes while preserving readable architecture, tests, content data, and source/runtime asset boundaries.
---

# GameMaker production

Use this skill alongside `governed-change` for repository mutations. Follow
only the routes matching the files and behavior in scope:

| Work | Required route |
| --- | --- |
| Repository-owned production code | [Production code](../../../GOVERNANCE.md#production-code), [Source structure](../../../GOVERNANCE.md#source-structure), and `[structure]` in [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml) |
| Derived asset | [Derived assets](../../../GOVERNANCE.md#derived-assets) and `[assets]` plus the matching `[assets.pipelines.*]` table in [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml) |
| GameMaker structured data | [GameMaker structured data](../../../GOVERNANCE.md#gamemaker-structured-data) and `assets.content_root` in [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml) |

Imported-library source follows the exception in Source structure, not the
repository-owned production-code style rules.

## Production procedure

When reusing an older project:

1. identify the useful behavior;
2. understand its assumptions;
3. adapt it to the current architecture;
4. leave unrelated legacy structure behind.

Preserve valid GameMaker resource relationships and verify any relationship
changed by the work.

For visual behavior, report observed results rather than inferring visual
correctness from code.
