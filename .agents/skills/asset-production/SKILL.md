---
name: asset-production
description: Create, edit, convert, and integrate authored assets while preserving practical editable sources, configured runtime outputs, and human authoring ergonomics.
---

# Asset production

Use this skill for repository-owned visual, audio, 3D, animation, and similar
authored assets.

Follow [Derived assets](../../../GOVERNANCE.md#derived-assets) and the affected
`[assets]` and `[assets.pipelines.*]` tables in
[PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml).

## Production defaults

1. Choose the simplest useful authoring form.
   Do not create a separate source file when the asset is most naturally authored
   directly in the engine or when no editable external source is useful.

2. Preserve editable sources when derivation is useful.
   When a runtime asset is exported, converted, baked, compressed, or otherwise
   derived from an authored asset, keep the practical editable source and record
   the configured source-to-runtime relationship.

3. Prefer open, widely supported source formats.
   Use an open or interoperable format when it adequately preserves the asset
   and normal editing workflow. Use a tool-specific or proprietary source format
   when the requested workflow depends on that tool or the format preserves
   authoring information that an open format would lose.

4. Authoring ergonomics count.
   A technically valid source is not useful if a human cannot reasonably inspect,
   edit, or continue working with it using ordinary asset tools.

5. Do not invent conversion layers.
   Use the configured asset pipeline directly. Do not add intermediate formats,
   schemas, registries, metadata layers, or custom converters unless the current
   asset or workflow actually requires them.

6. Keep one intentional source-to-runtime path.
   Do not maintain competing editable representations of the same derived asset
   unless the requested workflow requires them.

7. Runtime formats are outputs, not substitutes for useful sources.
   Do not treat a generated runtime representation as the preferred editing form
   when a practical authored source is needed.

8. Preserve tool-native information when it matters.
   Features such as armatures, animation tracks, modifiers, layered artwork,
   project structure, or editable music arrangements may justify keeping the
   native authoring file rather than flattening to a simpler interchange format.

9. Verify the actual derived result.
   After conversion or export, check that the runtime asset exists, matches the
   configured pipeline and manifest, and can be consumed by the target project
   when practical.

10. Do not generalize from one asset.
    A conversion needed by one model, image, sound, or animation does not by
    itself justify a new repository-wide asset framework.