"""Independent actual fill replay and price-label identities; no research fits."""

import numpy as np
import pandas as pd


def verify_inputs(account, fills, decisions, state, prices, labels, old_labels):
    checks = 0
    ledger = account.copy().set_index("date")
    ledger.index = pd.to_datetime(ledger.index)
    events = fills.copy()
    events["execution_day"] = pd.to_datetime(events.fill_time).dt.normalize()
    before = decisions.copy().set_index("valid_session")
    before.index = pd.to_datetime(before.index)
    after = decisions.copy().set_index("signal_date")
    after.index = pd.to_datetime(after.index)
    position, unit_cost, entry_day = 0, np.nan, None
    for i, day in enumerate(ledger.index):
        if day > state.index[-1]:
            break
        assert int(ledger.loc[day, "quantity_before"]) == position
        for row in events.loc[events.execution_day == day].itertuples():
            if row.side == "BUY":
                if position == 0:
                    unit_cost, entry_day = float(row.price), i
                else:
                    unit_cost = (unit_cost * position + row.price * row.quantity) / (
                        position + row.quantity
                    )
                position += int(row.quantity)
            elif row.side == "SELL":
                position -= int(row.quantity)
                assert position >= 0
                if position == 0:
                    unit_cost, entry_day = np.nan, None
            else:
                raise AssertionError("unknown side")
        assert position == int(ledger.loc[day, "quantity"])
        if day not in state.index:
            continue
        row = state.loc[day]
        assert row.actual_quantity == position and row.actual_held == (position > 0)
        if position:
            assert (
                row.holding_age == i - entry_day + 1
                and pd.Timestamp(row.entry_session) == ledger.index[entry_day]
            )
            np.testing.assert_allclose(row.entry_gross_price, unit_cost, atol=1e-13)
            np.testing.assert_allclose(
                row.entry_mark_pnl, ledger.loc[day, "close"] / unit_cost - 1, atol=1e-13
            )
        else:
            assert (
                pd.isna(row.holding_age)
                and pd.isna(row.entry_mark_pnl)
                and pd.isna(row.entry_gross_price)
                and pd.isna(row.entry_session)
            )
        assert row.signal_held_before == bool(before.loc[day, "target_position"])
        assert row.signal_held_after == bool(after.loc[day, "target_position"])
        checks += 6
    opening, closing = prices.Open.to_numpy(), prices.Close.to_numpy()
    affine_rows = {}
    for horizon in (4, 8):
        affine_rows[str(horizon)] = 0
        for day in state.index:
            i = prices.index.get_loc(day)
            end = i + 1 + horizon
            if end >= len(prices):
                assert pd.isna(labels.loc[day, f"return_{horizon}"])
                assert pd.isna(labels.loc[day, f"label_end_return_{horizon}"])
                checks += 1
                continue
            minimum = min([opening[end], *opening[i + 1 : end], *closing[i + 1 : end]])
            expected = {
                f"return_{horizon}": opening[end] / opening[i + 1] - 1,
                f"downside_{horizon}": max(0, 1 - minimum / opening[i + 1]),
                f"marked_close_net_{horizon}": 0.999 * opening[end] / closing[i] - 1,
                f"risk_close_{horizon}": max(0, 1 - minimum / closing[i]),
                f"increment_mark_{horizon}": 0.999 * (opening[end] - opening[i + 1]) / closing[i],
            }
            for name, value in expected.items():
                np.testing.assert_allclose(labels.loc[day, name], value, rtol=0, atol=5e-15)
                assert pd.Timestamp(labels.loc[day, "label_end_" + name]) == prices.index[end]
                checks += 1
            np.testing.assert_allclose(
                labels.loc[day, f"marked_close_net_{horizon}"]
                - labels.loc[day, "immediate_close_net"],
                labels.loc[day, f"increment_mark_{horizon}"],
                rtol=0,
                atol=5e-15,
            )
            fresh = old_labels.loc[day, f"return_{horizon}"]
            if np.isfinite(fresh):
                np.testing.assert_allclose(
                    (fresh + 1) * 1.001 / 0.999 - 1,
                    labels.loc[day, f"return_{horizon}"],
                    rtol=0,
                    atol=5e-15,
                )
                affine_rows[str(horizon)] += 1
            checks += 2
    return {"checks": checks, "affine_paired_rows": affine_rows}
