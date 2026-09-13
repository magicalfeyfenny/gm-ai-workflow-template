"""Read the current asset manifest document without inspecting asset payloads."""

from __future__ import annotations

import json
from pathlib import Path


def load_manifest(root: Path, path: Path, errors: list[str]) -> dict | None:
    """Share document-shape diagnostics with adoption candidate validation."""
    try:
        manifest = json.loads((root / path).read_text(encoding="utf-8"))
    except OSError:
        errors.append(f"{path}: manifest is missing or unreadable")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid manifest: {exc}")
        return None
    if not isinstance(manifest, dict):
        errors.append(f"{path}: manifest must be an object")
        return None
    if manifest.get("version") != 1:
        errors.append(f"{path}: version must be 1")
    if not isinstance(manifest.get("exports"), list):
        errors.append(f"{path}: exports must be a list")
        return None
    return manifest
