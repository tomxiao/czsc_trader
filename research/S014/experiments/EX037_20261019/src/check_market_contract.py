"""Confirm the first-news helper preserves the fixed existing 25-date contract."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from information_math import event_label, synthetic_precheck

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/S014/experiments/EX036_20261019"


def main():
    assert not (EX / "others/market_contract_equivalence.json").exists()
    manifest = json.loads((OLD / "others/market_inputs.json").read_bytes())
    frames = {}
    for item in manifest["native_identities"]:
        path = ROOT / item["snapshot_path"]
        assert sha256(path.read_bytes()).hexdigest() == item["snapshot_sha256"]
        frame = pd.read_csv(path)
        frames[item["name"]] = frame.set_index("Date")
    sessions = frames["stock_raw"].index.tolist()
    calendar = frames["calendar"]
    expected_sessions = calendar.loc[calendar.IsOpen.eq(1)].index.tolist()
    assert sessions == [d for d in expected_sessions if "2020-01-01" <= d <= "2026-10-15"]
    old = pd.read_csv(OLD / "others/market_event_labels.csv")
    rows = []
    for record in old.to_dict("records"):
        label = event_label(frames, sessions, record["decision_date"])
        for key in ("stock_return20", "sector_return20", "sector_excess_return20", "mae20",
                    "net_position_return", "event_cash_equity_return"):
            left, right = label[key], record[key]
            assert (left is None and pd.isna(right)) or np.isclose(left, right, rtol=1e-10, atol=1e-12), key
        assert label["price_end_date"] == record["price_endpoint_date"]
        assert label["entry_date"] == record["entry_date"]
        assert label["planned_exit_date"] == record["planned_exit_date"]
        assert label["execution_status"] == record["execution_status"]
        assert label["order_quantity"] == record["order_quantity"]
        assert label["buy_limit_raw"] == record["buy_limit_raw"]
        if record["execution_status"] == "CLOSED":
            assert label["actual_exit_date"] == record["actual_exit_date"]
        else:
            assert label["net_position_return"] is None and label["event_cash_equity_return"] == 0
        rows.append({"event_id": record["event_id"], "status": "PASS", "execution": label["execution_status"]})
    value = {"status": "PASS", "fixed_boundary_precheck": synthetic_precheck(), "events": rows,
             "source_sha256": {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), EX / "src/information_math.py",
                                         OLD / "others/market_event_labels.csv", OLD / "others/market_inputs.json")},
             "new_upstream_calls": 0, "new_model_fits": 0, "new_continuous_accounts": 0,
             "purpose": "25 existing-date equivalence checks, not new independent experiments or accounts"}
    with (EX / "others/market_contract_equivalence.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "existing_date_equivalence": len(rows), "synthetic_boundaries": 8}))


if __name__ == "__main__":
    main()
