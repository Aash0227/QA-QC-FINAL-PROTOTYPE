"""Project detection profile gate — project-specific detectors are OPT-IN.

Generic detection is always the default. A specialized profile (e.g. the
Madera/S-201 focused detector) runs only when the project manifest explicitly
declares ``detection_profile: "madera"``.

No client data lives here; the manifest field is the explicit reason.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config

KNOWN_PROFILES = ("madera",)


def detection_profile() -> str | None:
    """Read the bound project's declared profile, or None."""
    manifest_path = config.artifact_path("project_manifest")
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    profile = manifest.get("detection_profile")
    return profile if profile in KNOWN_PROFILES else None
