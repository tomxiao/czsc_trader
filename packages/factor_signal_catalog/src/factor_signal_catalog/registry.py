from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .models import (
    CatalogStatus,
    CatalogValidationError,
    FactorDefinition,
    InformationFamily,
    SignalDefinition,
)


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _documents(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / name
    if path.is_dir():
        canonical = path / "definitions.json"
        if not canonical.is_file():
            raise CatalogValidationError(f"{path} must contain definitions.json")
        paths = [canonical]
    else:
        paths = [path]
    rows: list[dict[str, Any]] = []
    for item in paths:
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogValidationError(f"cannot read {item}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise CatalogValidationError(f"{item} must be a schema_version 1 object")
        values = payload.get("items")
        if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
            raise CatalogValidationError(f"{item} items must be an array of objects")
        rows.extend(values)
    return rows


class CatalogRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.families = tuple(
            InformationFamily.from_dict(row) for row in _documents(self.root, "information_families.json")
        )
        self.factors = tuple(
            FactorDefinition.from_dict(row) for row in _documents(self.root, "factors")
        )
        self.signals = tuple(
            SignalDefinition.from_dict(row) for row in _documents(self.root, "signals")
        )
        self.validate()

    def validate(self) -> None:
        ids = [item.family_id for item in self.families]
        ids += [item.factor_id for item in self.factors]
        ids += [item.signal_id for item in self.signals]
        invalid = sorted(value for value in ids if not _ID.fullmatch(value))
        if invalid:
            raise CatalogValidationError(f"invalid catalog ids: {invalid[:3]}")
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise CatalogValidationError(f"duplicate catalog ids: {duplicates}")
        families = {item.family_id for item in self.families}
        factors = {item.factor_id for item in self.factors}
        missing_families = sorted(
            {item.information_family for item in (*self.factors, *self.signals)} - families
        )
        if missing_families:
            raise CatalogValidationError(f"unknown information families: {missing_families}")
        missing_factors = sorted(
            {factor_id for item in self.signals for factor_id in item.factor_ids} - factors
        )
        if missing_factors:
            raise CatalogValidationError(f"unknown factor references: {missing_factors}")
        for item in self.factors:
            if item.version < 1 or not all((item.name, item.description, item.implementation)):
                raise CatalogValidationError(f"incomplete factor definition: {item.factor_id}")
            _validate_implementation_owner(item.implementation)
        for item in self.signals:
            if item.version < 1 or not all((item.name, item.description, item.implementation)):
                raise CatalogValidationError(f"incomplete signal definition: {item.signal_id}")
            _validate_implementation_owner(item.implementation)
            if item.status is CatalogStatus.READY and not item.factor_ids and not item.embedded_factor:
                raise CatalogValidationError(
                    f"READY signal requires factor references or embedded factor: {item.signal_id}"
                )

    @property
    def digest(self) -> str:
        payload = {
            "families": [item.to_dict() for item in self.families],
            "factors": [item.to_dict() for item in self.factors],
            "signals": [item.to_dict() for item in self.signals],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def list_definitions(
        self,
        *,
        kind: str = "all",
        family: str | None = None,
        status: str | None = None,
        query: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        if kind not in {"all", "factor", "signal"}:
            raise CatalogValidationError(f"unknown definition kind: {kind}")
        if family and family not in {item.family_id for item in self.families}:
            raise CatalogValidationError(f"unknown information family: {family}")
        if status:
            try:
                CatalogStatus(status)
            except ValueError as exc:
                raise CatalogValidationError(f"unknown catalog status: {status}") from exc
        selected: list[tuple[str, FactorDefinition | SignalDefinition]] = []
        if kind in {"all", "factor"}:
            selected.extend(("factor", item) for item in self.factors)
        if kind in {"all", "signal"}:
            selected.extend(("signal", item) for item in self.signals)
        needle = query.casefold() if query else None
        rows = []
        for item_kind, item in selected:
            item_id = item.factor_id if item_kind == "factor" else item.signal_id
            if family and item.information_family != family:
                continue
            if status and item.status.value != status:
                continue
            if needle and needle not in " ".join((item_id, item.name, item.description, *item.tags)).casefold():
                continue
            rows.append({
                "kind": item_kind,
                "id": item_id,
                "name": item.name,
                "information_family": item.information_family,
                "status": item.status.value,
                "provider": item.provider,
                "version": item.version,
            })
        return tuple(sorted(rows, key=lambda row: (str(row["kind"]), str(row["id"]))))

    def show(self, definition_id: str) -> dict[str, object]:
        for kind, items in (("family", self.families), ("factor", self.factors), ("signal", self.signals)):
            for item in items:
                item_id = getattr(item, f"{kind}_id")
                if item_id == definition_id:
                    return {"kind": kind, **item.to_dict()}
        raise CatalogValidationError(f"catalog definition not found: {definition_id}")


def _validate_implementation_owner(implementation: str) -> None:
    parts = re.split(r"[\\/.]", implementation.casefold())
    if {"research", "experiments"}.intersection(parts):
        raise CatalogValidationError(
            "catalog implementation must not depend on research or experiments: "
            f"{implementation}"
        )
