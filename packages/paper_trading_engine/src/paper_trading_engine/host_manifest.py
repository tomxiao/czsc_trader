"""Lightweight validation of independently versioned WDG host provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime_release import RELEASE_ID_PATTERN, file_sha256


HOST_MANIFEST_NAME = "host-manifest.json"
BUILD_MANIFEST_NAME = "build-manifest.json"


def validate_watchdog_host_manifest(host: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((host / HOST_MANIFEST_NAME).read_text(encoding="utf-8"))
        source_path = host / BUILD_MANIFEST_NAME
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot read WDG host provenance") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "wdg-host"
        or manifest.get("host_version") != host.name
        or not RELEASE_ID_PATTERN.fullmatch(host.name)
    ):
        raise RuntimeError("WDG host directory and manifest identity differ")
    if (
        not isinstance(source, dict)
        or type(source.get("schema_version")) is not int
        or source.get("schema_version") != 1
        or file_sha256(source_path) != manifest.get("source_build_sha256")
        or source.get("release_id") != manifest.get("source_release_id")
        or source.get("git_commit") != manifest.get("source_git_commit")
    ):
        raise RuntimeError("WDG host source build differs from manifest")
    wheels = list((host / "artifacts").glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].name.startswith("paper_trading_engine-"):
        raise RuntimeError("WDG host requires exactly one host wheel")
    wheel = wheels[0]
    expected = manifest.get("artifacts")
    if (
        not isinstance(expected, dict)
        or expected != {wheel.name: file_sha256(wheel)}
        or not isinstance(source.get("artifacts"), dict)
        or source["artifacts"].get(wheel.name) != expected.get(wheel.name)
    ):
        raise RuntimeError("WDG host artifact differs from source build")
    return manifest
