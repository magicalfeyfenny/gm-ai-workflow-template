---
name: gamemaker-production
description: Make production GameMaker changes while preserving readable architecture, tests, content data, and source/runtime asset boundaries.
---

# GameMaker production

Use this skill alongside `governed-change` for repository mutations. Follow
only the routes matching the files and behavior in scope:

| Work | Required route |
| --- | --- |
| Repository-owned production code | [Production code](../../../GOVERNANCE.md#production-code), [Compatibility obligations](../../../GOVERNANCE.md#compatibility-obligations), [Source structure](../../../GOVERNANCE.md#source-structure), and `[structure]` in [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml) |
| GameMaker structured data | [GameMaker structured data](../../../GOVERNANCE.md#gamemaker-structured-data) and `assets.content_root` in [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml) |

Imported-library source follows the exception in Source structure, not the
repository-owned production-code style rules.

## Production procedure

When reusing an older project:

1. identify the useful behavior;
2. understand its assumptions;
3. integrate the useful behavior using the simplest appropriate current design;
4. leave unrelated legacy structure behind.

Preserve valid GameMaker resource relationships and verify any relationship
changed by the work.

## Production defaults

1. GameMaker-native first. Use ordinary objects, instances, rooms, layers,
sequences, sprites, instance variables, structs and GML before creating a
parallel authoring/runtime model. Preserve direct manipulation in the GameMaker
IDE when practical.
2. Build the smallest end-to-end behavior first. For gameplay/content work,
prefer a runnable consumer over defining a representation in isolation. Do not
create a canonical schema ahead of its first consumer unless the schema itself
is the requested deliverable or an actual shared boundary.
3. Existing architecture is precedent, not authority. Reuse an abstraction when
it makes the current change simpler. Do not extend one merely because it exists.
Simplify existing architecture when doing so directly serves the requested
outcome; otherwise leave unrelated cleanup out of scope.
4. New machinery needs a present-tense reason. Before adding a schema,
validator, registry, service, adapter, port, event bus, generalized framework,
custom editor, or similar layer, identify the current requirement, trust
boundary, repeated variation, or distinct failure mode it solves. If none
exists, don't add it.
5. Strong guarantees are not free defaults. Stable IDs, schema versions,
migration layers, canonical normalization, hashes, fixed-point representations,
deterministic serialization and fail-closed cross-language validation should
protect a concrete persistence, compatibility, replay, reproducibility,
external-authoring, or trust requirement. A claimed compatibility requirement
must satisfy [Compatibility obligations](../../../GOVERNANCE.md#compatibility-obligations).
Don't add these mechanisms simply because they are theoretically nice.
6. Validation follows real boundaries. Do not invent a representation and then
use the need to validate that representation as justification for more
architecture. Tests should primarily establish requested behavior and important
invariants.
7. Authoring ergonomics count. A system that runs correctly but makes ordinary
content harder to create in GameMaker is not automatically an improvement.
Routine tuning/content should remain easy for a human to inspect and edit.
8. Legacy archaeology is bounded. When consulting old projects, inspect only
the behavior relevant to the current outcome. Treat legacy architecture as
evidence, not specification, and don't characterize an entire corpus merely
because it is available.
9. Replacement includes cleanup. When replacing a runtime/content path,
classify leftovers as still-live, compatibility, fixture/reference, or
removable. Don't let tests fossilize dead production systems.
10. Runtime execution is evidence, not ceremony. Do not launch the game merely
because the requested outcome is visual, interactive, player-visible, or
touches runtime resources. Prefer automated tests, deterministic
interaction checks, rendering or snapshot evidence, validators, and other
machine-verifiable evidence. Launch the game only for a concrete runtime
purpose permitted by Governance, such as GameMaker-hosted automated tests,
bounded deterministic UI or interaction checks, explicitly scoped
performance profiling, or another runtime-only check explicitly required
by human direction. Do not create or perform generic gameplay smoke tests,
subjective playtesting, readability review, feel review, visual-quality
review, or human experiential acceptance unless explicitly directed by the
human author.