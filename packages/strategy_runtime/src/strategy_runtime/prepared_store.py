"""Persist business input bindings and calculation context, never source data."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from .errors import RuntimeContractError
from .input_binding import StrategyInputBinding
from .models import canonical_sha256
from .preparation import PreparedInputs


def save_prepared_inputs(prepared: PreparedInputs, directory: Path, *, binding: StrategyInputBinding) -> None:
    """Append an immutable binding record; historical CSV workspaces remain untouched."""
    if prepared.strategy != binding.plan.strategy or prepared.tradable_window != binding.plan.tradable_window:
        raise RuntimeContractError("input binding differs from prepared calculation context")
    root = Path(directory).resolve()
    target_root = root / "input-bindings"
    temporary_root = root / ".tmp"
    target_root.mkdir(parents=True, exist_ok=True)
    temporary_root.mkdir(exist_ok=True)
    manifest = {
        "schema_version": 3,
        "binding": binding.to_dict(),
        "data_identity": prepared.data_identity,
        "input_identities": prepared.input_identities,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    target = target_root / f"{binding.identity}.json"
    contents = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != contents:
            raise RuntimeContractError("stored input binding was modified")
        return
    staging = temporary_root / f"binding-{uuid4().hex}.json"
    try:
        staging.write_text(contents, encoding="utf-8", newline="\n")
        try:
            staging.rename(target)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != contents:
                raise RuntimeContractError("stored input binding was modified")
    finally:
        staging.unlink(missing_ok=True)
