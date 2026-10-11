"""Read-only provenance-hash diagnosis; never materialize or evaluate."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

import pandas as pd
from dataflows import PreparedDataRef

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parent))
import prime_existing_assets as prime  # noqa: E402


def main():
    coverage = prime.driver.read(FOLDER / "coverage.json")
    method_ref = prime.EvidenceRef.from_dict(coverage["method_reference"])
    ctx = prime.driver.draft.existing_only_context(method_ref, 1)
    connection = sqlite3.connect((prime.ROOT / "research/S013/assets/data/assets.sqlite3").resolve().as_uri()+"?mode=ro", uri=True)
    space = connection.execute("select space_id from space_metadata").fetchone()[0]
    rows = []
    for proposed in coverage["requests"]:
        r = proposed["request"]
        if r["dataset"] != "etf.ohlcv":
            continue
        selector = {k: v for k, v in r.items() if k not in ("coverage", "required_cutoff")}
        asset_key = sha256(json.dumps({"request": selector, "provider": r["dataset"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prepare_key = sha256(json.dumps({"requests": [{"request": r, "asset_key": asset_key}]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        retained = connection.execute("select p.preparation_id,p.manifest_sha256,p.manifest from preparation_lookup l join preparations p on l.preparation_id=p.preparation_id where l.request_key=?", (prepare_key,)).fetchone()
        row = {"request": r, "prepare_key": prepare_key, "source_prepared": coverage["sources"]["etf.ohlcv"]["prepared"]}
        if retained is None:
            row["status"] = "EXACT_PREPARATION_MISSING"
        else:
            pid, hashed, manifest = retained
            if sha256(manifest.encode()).hexdigest() != hashed:
                raise ValueError("Retained manifest SHA drift")
            request = prime.request_from(r)
            prepared = PreparedDataRef(UUID(space), UUID(pid), hashed)
            actual = ctx.data.fetch(request, prepared=prepared)
            original = prime.pinned_fetch(ctx, request, coverage["sources"])
            if not actual.ready:
                raise ValueError("Existing exact preparation cannot be read")
            pd.testing.assert_frame_equal(actual.dataframe, original.dataframe, check_exact=True)
            if actual.identity.content_sha256 != original.identity.content_sha256 or original.identity.content_sha256 != proposed["content_sha256"]:
                raise ValueError("Exact content SHA differs")
            if actual.identity.metadata["adjustment"] != "hfq" or original.identity.metadata["adjustment"] != "hfq":
                raise ValueError("HFQ basis differs")
            other_contract = {k: v for k, v in proposed["price_contract"].items() if k != "adjustment_factor_sha256"}
            if any(actual.identity.metadata.get(k) != v for k, v in other_contract.items()):
                raise ValueError("Other adjustment/availability contract differs")
            row.update(status="EXISTING_EXACT_FRAME_EQUAL", observations=len(actual.dataframe),
                columns=list(actual.dataframe.columns), all_columns_and_dtypes_exact=True,
                content_sha256=actual.identity.content_sha256,
                actual_prepared={"space_id": space, "preparation_id": pid, "manifest_sha256": hashed},
                actual_asset_id=json.loads(manifest)[0]["asset_id"],
                provider_binding=actual.identity.metadata["provider_binding"],
                original_factor_series_sha256=original.identity.metadata["adjustment_factor_sha256"],
                actual_factor_series_sha256=actual.identity.metadata["adjustment_factor_sha256"],
                only_factor_source_series_digest_differs=actual.identity.metadata["adjustment_factor_sha256"] != original.identity.metadata["adjustment_factor_sha256"],
                other_price_contract_exact=True)
        rows.append(row)
    connection.close()
    failure = FOLDER / "failure-1791702401631532900.json"
    contracts = (prime.ROOT / "packages/dataflows/src/dataflows/tushare_etf.py", prime.ROOT / "packages/dataflows/src/dataflows/bar_utils.py", prime.ROOT / "packages/dataflows/src/dataflows/facade.py")
    output = {"status": "READONLY_PASS", "source_sha256": prime.digest(__file__),
        "coverage_sha256": prime.digest(FOLDER / "coverage.json"), "failed_priming_sha256": prime.digest(failure),
        "rows": rows, "existing_exact_frame_equal": sum(r['status']=='EXISTING_EXACT_FRAME_EQUAL' for r in rows),
        "missing_exact_preparations": sum(r['status']=='EXACT_PREPARATION_MISSING' for r in rows),
        "contracts": {p.relative_to(prime.ROOT).as_posix(): prime.digest(p) for p in contracts},
        "explanation": "adjustment_factor_sha256 hashes the entire normalized Date/AdjFactor table fetched for each original request interval, not the selected OHLCV prices or a normalized-to-first-date price anchor. Public fetch slices rows but retains original source metadata. REUSE may select an existing exact asset with a narrower factor-series digest. All8 returned columns/dtypes and actual content SHA are exact; adjustment=hfq and every other recorded price contract equal. This proves the selected data was unchanged, not that full factor query tables are equal.",
        "new_account_evaluations": 0, "preparations": 0, "external_provider_calls": 0,
        "recommendation": "Separate minimal correction may record both provenance hashes rather than equate them; retain strict all-column content/dtype/date equality, HFQ basis and all other contract fields. Never retry automatically or weaken economic/source/domain rules."}
    prime.driver.write(FOLDER / "factor_diagnosis.json", output)
    print({k: output[k] for k in ('status', 'existing_exact_frame_equal', 'missing_exact_preparations')})


if __name__ == "__main__":
    main()
