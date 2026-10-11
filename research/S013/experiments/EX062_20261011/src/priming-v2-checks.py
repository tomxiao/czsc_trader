"""Pure provenance correction checks, no asset reads/preparation/evaluation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from dataflows import canonical_frame_sha256
import prime_existing_assets_v2 as v2


def main():
    frame = pd.DataFrame({"Date": pd.to_datetime(["2019-04-10"]), "Open": [50.0], "High": [51.0],
        "Low": [49.0], "Close": [50.5], "Volume": [1000.0], "Amount": [50500.0],
        "AvailableDate": pd.to_datetime(["2019-04-10 17:00:00"])})
    metadata = {"adjustment": "hfq", "adjustment_factor_source": "fund_adj",
        "adjustment_factor_publication_schedule": "daily 17:00 Asia/Shanghai", "price_anchor": "unchanged",
        "adjustment_factor_sha256": "1"*64}
    original = SimpleNamespace(dataframe=frame, identity=SimpleNamespace(dataset="etf.ohlcv", metadata=metadata))
    actual = SimpleNamespace(dataframe=frame.copy(), identity=SimpleNamespace(dataset="etf.ohlcv",
        content_sha256=canonical_frame_sha256(frame), metadata={**metadata, "adjustment_factor_sha256": "2"*64}))
    row = {"content_sha256": actual.identity.content_sha256, "price_contract": metadata}
    hashes = v2.verify_materialized(actual, original, row)
    assert hashes == {"pinned_source_query_sha256": "1"*64, "materialized_source_query_sha256": "2"*64}
    count = 1
    for case in ("price", "dtype", "date", "volume", "amount", "available", "hash", "basis", "factor_source", "schedule", "anchor", "missing_factor"):
        changed = deepcopy(actual)
        if case in {"price", "volume", "amount"}:
            field = {"price": "Close", "volume": "Volume", "amount": "Amount"}[case]
            changed.dataframe.loc[0, field] += 1
        elif case == "dtype":
            changed.dataframe["Open"] = changed.dataframe.Open.astype("int64")
        elif case in {"date", "available"}:
            changed.dataframe.loc[0, "Date" if case == "date" else "AvailableDate"] += pd.Timedelta(days=1)
        elif case == "hash":
            changed.identity.content_sha256 = "3"*64
        else:
            field = {"basis": "adjustment", "factor_source": "adjustment_factor_source",
                "schedule": "adjustment_factor_publication_schedule", "anchor": "price_anchor",
                "missing_factor": "adjustment_factor_sha256"}[case]
            changed.identity.metadata[field] = "invalid"
        try:
            v2.verify_materialized(changed, original, row)
        except (ValueError, AssertionError):
            count += 1
        else:
            raise AssertionError(case)
    folder = Path(__file__).resolve().parent
    v2.driver.write(folder / "priming-v2-checks.json", {"status": "PURE_PASS", "checks": count,
        "source_sha256": v2.digest(folder / "prime_existing_assets_v2.py"),
        "checks_source_sha256": v2.digest(__file__), "original_source_sha256": v2.digest(folder / "prime_existing_assets.py"),
        "preparations": 0, "new_account_evaluations": 0, "asset_reads": 0})
    print({"status": "PURE_PASS", "checks": count})


if __name__ == "__main__":
    main()
