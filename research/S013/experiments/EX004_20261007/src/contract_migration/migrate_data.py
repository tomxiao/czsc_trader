"""Republish S013's historical inputs through DFLS without changing old records.

Only the authorized local S013 data space is consumed. The offline supplier
reads authenticated immutable assets from a verified backup; every write uses
the public prepare(REFRESH) API. Historical preparation references are retained
and their successors are recorded separately from asset provenance.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import UUID

import pandas as pd

from dataflows import (
    DataCoverageRequirement, Dataflows, DataRequest, DataSpace, Dataset,
    NoParameters, PreparedDataRef, PreparePolicy, ProviderBinding, ProviderConfig,
)
from dataflows.contract import DATA_CONTRACT_VERSION
from dataflows.facade import _request_record, canonical_frame_sha256


ROOT = Path(__file__).resolve().parents[6]
FORMAL_SPACE = Path("research/S013/assets/data")
FORMAL_OUTPUT = Path("research/S013/assets/runs/EX004_20261007/contract_migration")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def reference_record(reference: PreparedDataRef) -> dict:
    return {"space_id": str(reference.space_id),
            "preparation_id": str(reference.preparation_id),
            "manifest_sha256": reference.manifest_sha256}


def selector(record: dict) -> str:
    return json.dumps({key: value for key, value in record.items()
                       if key not in {"coverage", "required_cutoff"}}, sort_keys=True)


def request_from_record(raw: dict) -> DataRequest:
    request = DataRequest(Dataset(raw["dataset"]), raw["symbol"], raw["start"], raw["end"],
                          raw["required_cutoff"], frequency=raw["frequency"],
                          parameters=NoParameters(),
                          coverage=DataCoverageRequirement(**raw["coverage"])
                          if raw.get("coverage") else None)
    if _request_record(request) != raw:
        raise ValueError("historical request cannot be reconstructed exactly")
    return request


def local_path(relative: Path) -> Path:
    result = (ROOT / relative).resolve()
    if relative.is_absolute() or not result.is_relative_to(ROOT) or result == ROOT:
        raise ValueError("path must remain inside the repository")
    return result


def migrate(space: Path, output: Path) -> dict:
    if space != FORMAL_SPACE and not space.as_posix().startswith(".tmp/"):
        raise ValueError("only S013 or an isolated .tmp rehearsal is authorized")
    db = local_path(space) / "assets.sqlite3"
    out = local_path(output)
    out.mkdir(parents=True, exist_ok=False)
    before = digest(db)
    backup_dir = ROOT / ".tmp/s013-contract-migration-backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup = backup_dir / "assets.sqlite3"
    shutil.copy2(db, backup)
    if digest(backup) != before:
        raise AssertionError("backup differs from original database")
    with sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True) as connection:
        preparations = connection.execute("SELECT * FROM preparations ORDER BY prepared_at,preparation_id").fetchall()
        assets = connection.execute("SELECT * FROM assets ORDER BY asset_id").fetchall()
    if len(preparations) != 28 or len(assets) != 31:
        raise AssertionError("expected the original 28 preparations and 31 assets")

    historical = Dataflows(base_dir=ROOT, space=DataSpace(backup_dir.relative_to(ROOT)),
                          providers=ProviderConfig(bindings={}))
    original_space_id = historical.binding.space_id
    source_assets = {row[0]: historical._store.read(row[0]) for row in assets}
    plans = []
    for prep_id, manifest_sha, _, _ in preparations:
        old_ref = PreparedDataRef(original_space_id, UUID(prep_id), manifest_sha)
        entries = historical._store.load_preparation(old_ref)
        if any("data_contract_version" in entry for entry in entries):
            raise AssertionError("a preparation has already been migrated")
        requests = tuple(request_from_record(entry["request"]) for entry in entries)
        originals = []
        selections = {}
        for request, entry in zip(requests, entries):
            stored = source_assets[entry["asset_id"]]
            if "data_contract_version" in stored.identity.metadata:
                raise AssertionError("a source asset has already been migrated")
            selected_key = selector(_request_record(request))
            if selected_key in selections and selections[selected_key] != entry["asset_id"]:
                raise AssertionError("one preparation selects multiple source assets for one request")
            selections[selected_key] = entry["asset_id"]
            checked = historical._checked_result(stored, request, validated=True)
            if not checked.ready:
                raise AssertionError(f"historical input does not meet current validators: {checked.error}")
            originals.append(checked)
        plans.append((old_ref, entries, requests, originals, selections))

    selected = {}
    local_calls = []

    def offline_source(request: DataRequest):
        key = selector(_request_record(request))
        if key not in selected:
            raise AssertionError("offline supplier received an undeclared request")
        asset_id = selected[key]
        stored = source_assets[asset_id]
        local_calls.append({"request": _request_record(request), "source_asset_id": asset_id})
        metadata = dict(stored.identity.metadata)
        metadata["migration_origin"] = {"space_id": str(original_space_id), "asset_id": asset_id}
        return stored.dataframe.copy(deep=True), metadata

    datasets = {request.dataset for _, _, requests, _, _ in plans for request in requests}
    current = Dataflows(base_dir=ROOT, space=DataSpace(space), providers=ProviderConfig(bindings={
        dataset: ProviderBinding(str(dataset), "S013-offline-contract-migration-v1", offline_source)
        for dataset in datasets}))
    if current.binding.space_id != original_space_id:
        raise AssertionError("backup and target have different space identities")
    # The ordinary configuration creates bindings named str(dataset). Verify
    # those names, then block every supplier call during consumer REUSE checks.
    default = Dataflows(base_dir=ROOT, space=DataSpace(space), providers=ProviderConfig())
    if any(default._providers[str(dataset)].name != str(dataset) for dataset in datasets):
        raise AssertionError("default provider names differ from migration names")
    forbidden_calls = []

    def forbidden_supplier(request: DataRequest):
        forbidden_calls.append(_request_record(request))
        raise AssertionError("REUSE must never access a supplier")

    consumer = Dataflows(base_dir=ROOT, space=DataSpace(space), providers=ProviderConfig(bindings={
        dataset: ProviderBinding(default._providers[str(dataset)].name,
                                 default._providers[str(dataset)].revision, forbidden_supplier)
        for dataset in datasets}))

    references = []
    asset_map = {}
    comparisons = []
    try:
        for old_ref, entries, requests, originals, selections in plans:
            selected.clear()
            selected.update(selections)
            result = current.prepare(requests, policy=PreparePolicy.REFRESH)
            if not result.ready:
                raise AssertionError(f"contract republication failed: {result}")
            new_entries = current._store.load_preparation(result.reference)
            count = len(local_calls)
            reused = consumer.prepare(requests, policy=PreparePolicy.REUSE)
            if not reused.ready or reused.reference != result.reference or len(local_calls) != count:
                raise AssertionError("ordinary-provider-name REUSE did not preserve the new reference")
            for request, old, old_entry, new_entry in zip(requests, originals, entries, new_entries):
                new = consumer.fetch(request, prepared=result.reference)
                if not new.ready:
                    raise AssertionError(f"new preparation is unreadable: {new.error}")
                pd.testing.assert_frame_equal(old.dataframe, new.dataframe, check_exact=True)
                if old.identity.content_sha256 != new.identity.content_sha256:
                    raise AssertionError("request frame hash differs")
                old_asset, new_asset = old_entry["asset_id"], new_entry["asset_id"]
                if old_asset in asset_map and asset_map[old_asset] != new_asset:
                    raise AssertionError("one historical asset generated multiple metadata copies")
                asset_map[old_asset] = new_asset
                published = current._store.read(new_asset)
                source = source_assets[old_asset]
                pd.testing.assert_frame_equal(source.dataframe, published.dataframe, check_exact=True)
                if source.identity.content_sha256 != published.identity.content_sha256:
                    raise AssertionError("whole-asset frame hash differs")
                comparisons.append({"old_reference": reference_record(old_ref),
                                    "new_reference": reference_record(result.reference),
                                    "request": _request_record(request), "old_asset_id": old_asset,
                                    "new_asset_id": new_asset, "rows": len(new.dataframe),
                                    "column_dtypes": {str(key): str(value) for key, value in new.dataframe.dtypes.items()},
                                    "old_frame_sha256": canonical_frame_sha256(old.dataframe),
                                    "new_frame_sha256": canonical_frame_sha256(new.dataframe),
                                    "exact_values_types_and_index": True})
            references.append({"old": reference_record(old_ref), "new": reference_record(result.reference),
                               "requests": [_request_record(request) for request in requests],
                               "ordinary_provider_reuse": True})
            save(out / "progress.json", {"completed_preparations": len(references), "references": references})
        if forbidden_calls:
            raise AssertionError("supplier access occurred during REUSE")
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
            for row in assets:
                if connection.execute("SELECT * FROM assets WHERE asset_id=?", (row[0],)).fetchone() != row:
                    raise AssertionError("historical asset changed")
            for row in preparations:
                if connection.execute("SELECT * FROM preparations WHERE preparation_id=?", (row[0],)).fetchone() != row:
                    raise AssertionError("historical preparation changed")
            asset_count = connection.execute("SELECT count(*) FROM assets").fetchone()[0]
            prep_count = connection.execute("SELECT count(*) FROM preparations").fetchone()[0]
        if len(comparisons) != 103 or len(asset_map) != 31 or asset_count != 62 or prep_count != 56:
            raise AssertionError("migration did not produce exactly 31 successors and 28 preparations")
        if digest(backup) != before:
            raise AssertionError("original backup changed")
        asset_records = [{"old_asset_id": old, "new_asset_id": new,
                          "content_sha256": source_assets[old].identity.content_sha256,
                          "exact_values_types_and_index": True} for old, new in sorted(asset_map.items())]
        save(out / "prepared_reference_mapping.json", references)
        save(out / "asset_mapping.json", asset_records)
        save(out / "input_equivalence.json", comparisons)
        save(out / "offline_source_calls.json", local_calls)
        report = {"status": "PASS", "space": space.as_posix(), "data_contract_version": DATA_CONTRACT_VERSION,
                  "original_database_sha256": before, "migrated_database_sha256": digest(db),
                  "backup": backup.relative_to(ROOT).as_posix(), "backup_unchanged": True,
                  "historical_assets_preserved": len(assets), "historical_preparations_preserved": len(preparations),
                  "new_assets": asset_count - len(assets), "new_preparations": prep_count - len(preparations),
                  "exact_request_frame_comparisons": len(comparisons), "exact_whole_asset_comparisons": len(asset_map),
                  "reused_new_preparations_without_source_calls": len(references), "offline_source_calls": len(local_calls),
                  "external_supplier_access": False, "default_provider_name_reuse_verified": True,
                  "prepare_api_changed": False, "historical_artifacts_modified": False,
                  "strategy_or_account_equivalence_checked": False}
        save(out / "migration.json", report)
        return report
    except BaseException as error:
        save(out / "failure.json", {"status": "FAILED", "error_type": type(error).__name__,
                                  "error": str(error), "completed_preparations": len(references),
                                  "backup": backup.relative_to(ROOT).as_posix()})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", type=Path, default=FORMAL_SPACE)
    parser.add_argument("--output", type=Path, default=FORMAL_OUTPUT)
    arguments = parser.parse_args()
    print(json.dumps(migrate(arguments.space, arguments.output), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
