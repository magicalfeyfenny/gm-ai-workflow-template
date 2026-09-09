---
name: asset-production
description: Create, edit, convert, and integrate authored assets while preserving practical editable sources, configured runtime outputs, and human authoring ergonomics.
---

# Asset production

Use this skill for repository-owned visual, audio, 3D, animation, and similar
authored assets, alongside [Governed Change](../governed-change/SKILL.md) for
repository mutations.

Follow [Derived assets](../../../GOVERNANCE.md#derived-assets) and the affected
`[assets]` and `[assets.pipelines.*]` tables in
[PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml).
Apply
[Native GameMaker functionality](../../../GOVERNANCE.md#native-gamemaker-functionality)
to native-resource and custom-loader decisions.
Before creating, changing, or replacing an authored asset, follow
[Asset completion and authority](../../../GOVERNANCE.md#asset-completion-and-authority).
For placeholders supporting a mixed implementation issue, also follow
[Placeholder-backed mixed work](../../../GOVERNANCE.md#placeholder-backed-mixed-work).

Validation follows
[Validation coverage allocation](../../../GOVERNANCE.md#validation-coverage-allocation).
If considering a GameMaker runtime launch, first follow
[Interactive runtime validation](../../../GOVERNANCE.md#interactive-runtime-validation)
to determine whether it is permitted and needed.

For the placeholder-backed mixed-work handoff, return the exact placeholder
scope, replacement point, and any canonical asset-issue link required by that
route to Governed Change.

## Production defaults

1. Choose the simplest useful authoring form.

2. Prefer open, widely supported source formats.
   Use an open or interoperable format when it adequately preserves the asset
   and normal editing workflow. Use a tool-specific or proprietary source format
   when the requested workflow depends on that tool or the format preserves
   authoring information that an open format would lose.

3. Authoring ergonomics count.
   A technically valid source is not useful if a human cannot reasonably inspect,
   edit, or continue working with it using ordinary asset tools.

4. Do not invent conversion layers.
   Use the configured asset pipeline directly. Do not add intermediate formats,
   schemas, registries, metadata layers, or custom converters unless the current
   asset or workflow actually requires them.

5. Keep one intentional source-to-runtime path.
   Do not maintain competing editable representations of the same derived asset
   unless the requested workflow requires them.

6. Runtime formats are outputs, not substitutes for useful sources.
   Do not treat a generated runtime representation as the preferred editing form
   when a practical authored source is needed.

7. Preserve tool-native information when it matters.
   Features such as armatures, animation tracks, modifiers, layered artwork,
   project structure, or editable music arrangements may justify keeping the
   native authoring file rather than flattening to a simpler interchange format.

8. Verify the actual derived result.
   After conversion or export, check that the runtime asset exists, matches the
   configured pipeline and manifest, and can be consumed by the target project
   when practical.

9. Do not generalize from one asset.
   A conversion needed by one model, image, sound, or animation does not by
   itself justify a new repository-wide asset framework.
