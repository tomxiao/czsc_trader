"""Zero-reexecution daily ledger identity and original anomaly mapping."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    receipt = json.loads((HERE / "construction_receipt.json").read_text("utf-8"))
    for name, expected in receipt["files"].items():
        assert digest(HERE / name) == expected, name
    labels = pd.read_csv(HERE / "labels.csv", index_col="signal_date", float_precision="round_trip")
    labels.index = pd.to_datetime(labels.index).as_unit("ns")
    fills = pd.read_csv(HERE / "ledger_fills.csv", float_precision="round_trip")
    states = pd.read_csv(HERE / "ledger_account_daily.csv", float_precision="round_trip")
    trades = pd.read_csv(HERE / "ledger_trades.csv", float_precision="round_trip")
    for column in ("attempt_signal_date", "fill_time"):
        fills[column] = pd.to_datetime(fills[column]).dt.as_unit("ns")
    for column in ("attempt_signal_date", "date"):
        states[column] = pd.to_datetime(states[column]).dt.as_unit("ns")
    cash_max, equity_max = 0., 0.
    for signal, daily in states.groupby("attempt_signal_date", sort=False):
        selected = fills.loc[fills.attempt_signal_date.eq(signal)]
        cash, quantity = 1_000_000., 0
        for row in daily.itertuples(index=False):
            today = selected.loc[selected.fill_time.dt.normalize().eq(row.date)]
            assert abs(row.cash_before - cash) < 2e-7
            assert row.quantity_before == quantity
            for fill in today.itertuples(index=False):
                quantity += fill.quantity if fill.side == "BUY" else -fill.quantity
                cash += (-fill.quantity * fill.price if fill.side == "BUY" else fill.quantity * fill.price) - fill.fees
            cash_max = max(cash_max, abs(cash - row.cash))
            equity_max = max(equity_max, abs(cash + quantity * row.close - row.equity))
            assert quantity == row.quantity and cash >= -1e-8
            assert abs(cash - row.cash) < 2e-7
            assert abs(cash + quantity * row.close - row.equity) < 2e-7
        label = labels.loc[signal]
        if label.closed:
            assert abs(cash / 1_000_000 - 1 - label.l1) < 2e-12
        elif not label.entry_filled:
            assert label.l1 == 0 and cash == 1_000_000 and quantity == 0
        else:
            assert pd.isna(label.l1) and quantity > 0 and label.occupied_at_end
    raw = pd.read_csv(HERE / "normalized_daily.csv")
    axis = pd.DatetimeIndex(pd.to_datetime(raw.dt)).as_unit("ns")
    audit = json.loads((HERE / "adaptation_audit.json").read_text("utf-8"))
    anomaly_dates = pd.DatetimeIndex(audit["original30m_quality"]["minute"]["inaccurate_dates"]).as_unit("ns")
    anomaly_rows = []
    for signal, row in labels.iterrows():
        loc = axis.get_loc(signal)
        window = axis[loc + 1:loc + 6]
        hit = anomaly_dates.intersection(window)
        if len(hit):
            anomaly_rows.append({"signal_date": signal, "anomaly_dates": ",".join(x.date().isoformat() for x in hit),
                                "entry_session_anomalous": window[0] in anomaly_dates,
                                "entry_filled": bool(row.entry_filled), "closed": bool(row.closed),
                                "l0": row.l0, "l1": row.l1})
    anomalies = pd.DataFrame(anomaly_rows)
    anomalies.to_csv(HERE / "anomaly_attempts.csv", index=False)
    complete = labels.l0.notna() & labels.l1.notna()
    summary = {"status": "PASS", "actual_attempt_repeats": 0, "model_fits": 0,
               "original_receipt_all_files_hash_equal": True, "actual_daily_ledger_rows": len(states),
               "cash_max_abs_error": cash_max, "equity_max_abs_error": equity_max,
               "all_cash_nonnegative": True, "fixed_quantity_before_after_matched": True,
               "all_mature_labels_equal_independent_cash": True,
               "actual_trades_closed": int(trades.status.eq("CLOSED").sum()),
               "actual_trades_tail_open": int(trades.status.eq("OPEN").sum()),
               "positive_to_negative": int((complete & labels.l0.gt(0) & labels.l1.lt(0)).sum()),
               "negative_to_positive": int((complete & labels.l0.lt(0) & labels.l1.gt(0)).sum()),
               "nonzero_to_unfilled_zero": int((complete & labels.l0.ne(0) & labels.l1.eq(0)).sum()),
               "known_anomalous_30m_dates": [x.date().isoformat() for x in anomaly_dates],
               "attempts_with_anomaly_in_fixed_window": len(anomalies),
               "attempts_with_anomalous_entry_session": int(anomalies.entry_session_anomalous.sum()),
               "anomalies_unchanged_and_samples_not_removed": True,
               "hashes": {name: digest(HERE / name) for name in
                           ("labels.csv", "model/labels.csv", "model/attempts.csv", "anomaly_attempts.csv", "ledger_verification.py")}}
    with (HERE / "ledger_verification.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
