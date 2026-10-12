"""Synthetic-only boundary checks, no S013 market asset read."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from label_kernel import construct_labels, PRICING

HERE = Path(__file__).resolve().parent


def frames(mode="open", n=8, scale=1.):
    dates = pd.bdate_range("2025-12-29", periods=n).as_unit("ns")
    raw = pd.DataFrame({"dt": dates, "open": 10., "close": 10., "high": 10.2, "low": 9.9})
    bars = pd.DataFrame({"dt": dates + pd.Timedelta(hours=10), "open": 10.,
                         "close": 10., "high": 10.2, "low": 9.9})
    if mode in ("touch", "strict_touch", "unfilled"):
        raw.loc[1, ["open", "high", "close", "low"]] = [10.3, 10.4, 10.3, 10.0]
        bars.loc[1, ["open", "high", "close", "low"]] = [10.3, 10.4, 10.3,
                                                          {"touch": 10., "strict_touch": 10.1, "unfilled": 10.2}[mode]]
    d = raw.copy()
    for col in ("open", "high", "low", "close"):
        d[col] *= scale
        bars[col] *= scale
    return d, bars, raw, dates


def run():
    checks = []
    def require(name, condition):
        assert condition, name
        checks.append(name)
    def build(mode="open", n=8, scale=1.):
        d, bars, raw, dates = frames(mode, n, scale)
        return construct_labels(d, bars, raw, dates[:1], pricing=PRICING,
                                source_hash="a" * 64, emit_ledgers=True)
    labels, ledgers = build()
    row = labels.iloc[0]
    expected_qty = int(1_000_000 / (10.1 * 1.001 * 100)) * 100
    expected_cash = 1_000_000 - expected_qty * 10 * 1.001 + expected_qty * 10 * .999
    require("open limit fill and exact100 lot cash fees", row.quantity == expected_qty and
            abs(row.cash_end - expected_cash) < 1e-6 and row.quantity % 100 == 0)
    require("exact fixed L0 formula maturity", abs(row.l0 - (.999 / 1.001 - 1)) < 1e-14 and
            row.l0_maturity == pd.Timestamp("2026-01-05"))
    require("H4 exit crosses year continuous attempt", row.closed and row.exit_date == row.l0_maturity and
            row.occupation_sessions == 5 and list(ledgers["fills"].side) == ["BUY", "SELL"])
    require("fee cash and independent100w return", abs(row.l1 - (expected_cash / 1_000_000 - 1)) < 1e-14)
    touch, detail = build("touch")
    require("intraday strict crossing fills canonical limit", touch.iloc[0].entry_price == 10.1 and
            detail["fills"].iloc[0].trigger == "INTRADAY_LIMIT")
    equal, detail = build("strict_touch")
    require("exact touch refused by existing strict semantics", not equal.iloc[0].entry_filled and
            len(detail["fills"]) == 0 and equal.iloc[0].l1 == 0)
    miss, detail = build("unfilled")
    require("unfilled DAY entry no nextday retry and early cancellation maturity",
            miss.iloc[0].l1 == 0 and miss.iloc[0].l1_maturity == pd.Timestamp("2025-12-30") and
            miss.iloc[0].occupation_sessions == 1 and list(detail["orders"].side) == ["BUY"])
    tail, detail = build(n=4)
    require("tail actual filled OPEN not force closed", np.isnan(tail.iloc[0].l1) and
            pd.isna(tail.iloc[0].l1_maturity) and tail.iloc[0].occupied_at_end and
            detail["trades"].status.tolist() == ["OPEN"])
    d, b, raw, dates = frames()
    single, _ = construct_labels(d, b, raw, dates[-1:], source_hash="a" * 64)
    require("lastT noexecution cannot fabricate outcome", not single.iloc[0].attempted and
            np.isnan(single.iloc[0].l0) and np.isnan(single.iloc[0].l1))
    scaled, detail = build(scale=2.)
    require("HFQ scaled grid quantity canonical", scaled.iloc[0].entry_price == 20. and
            int(detail["orders"].iloc[0].quantity) == int(1_000_000 / (20.2 * 1.001 * 100)) * 100)
    base, _ = construct_labels(d, b, raw, dates[:3], source_hash="a" * 64)
    prefix, _ = construct_labels(d.iloc[:7], b.iloc[:7], raw.iloc[:7], dates[:2], source_hash="a" * 64)
    pd.testing.assert_frame_equal(base.iloc[:2], prefix)
    require("prefix unchanged for matured labels", True)
    changed_d, changed_b, changed_raw = d.copy(), b.copy(), raw.copy()
    for value in (changed_d, changed_b, changed_raw):
        value.loc[value.index >= 6, ["open", "high", "low", "close"]] *= 1.5
    changed, detail = construct_labels(changed_d, changed_b, changed_raw, dates[:1], source_hash="a" * 64,
                                      emit_ledgers=True)
    pd.testing.assert_frame_equal(changed, labels)
    require("future mutated after maturity leaves label ledger invariant", True)
    more, detail = construct_labels(d, b, raw, dates[:3], source_hash="a" * 64, emit_ledgers=True)
    require("overlapping attempts reset cash and do not composite", len(more) == 3 and
            len(detail["trades"]) == 3 and np.allclose(more.l1, labels.iloc[0].l1))
    bad = d.copy()
    bad.loc[0, "close"] = 0.
    try:
        construct_labels(bad, b, raw, dates[:1], source_hash="a" * 64)
    except ValueError:
        require("illegal quote refused no repair", True)
    else:
        raise AssertionError("bad quote accepted")
    return {"status": "PASS", "checks": checks, "check_count": len(checks),
            "market_reads": 0, "real_attempts": 0, "synthetic_signal_rows": 16,
            "synthetic_executors": 15,
            "model_fits": 0, "full_window_accounts": 0,
            "limits": "market sell canonical public TXE always OPEN_MARKET; no artificial delayed-sale simulation"}


if __name__ == "__main__":
    result = run()
    (HERE / "synthetic_checks.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
