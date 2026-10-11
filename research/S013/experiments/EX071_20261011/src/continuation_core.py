"""Pure T-close holding state and fixed observed-price continuation labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

METHOD = {
    "version": "s013-actual-held-continuation-prospective-v1",
    "status": "SOURCE_ONLY_NO_EXPERIMENT_ALLOCATION_OR_REAL_STATISTICS",
    "component": "late_weakness=-EX061 late_recovery=-log(C8/C6); positive return and negative risk hypotheses fixed",
    "state_time": "account_daily.date=T quantity is post T fills, marked with T close, known at T17; account_daily.signal_date is prior execution-plan signal and must not align T features",
    "actual_held": "quantity[T]>0, not target_position or entry_eligible",
    "signal_before": "decision.target_position keyed by valid_session=T; previous signal already formed before T",
    "signal_after": "decision.target_position keyed by signal_date=T; intended next-session target, not current holdings",
    "known_controls": {
        "holding_age": "number of actual execution sessions since first BUY in current position including entry day; entry day=1",
        "entry_mark_pnl": "Close[T]/remaining known cost-weighted gross entry price-1; BUY fees excluded; only fills on/before T used",
        "known_falling": "original known momentum20[T]<0, not realized annual return",
    },
    "labels": {
        "continue_open_h": "(1-f)*Open[T+1+h]/((1-f)*Open[T+1])-1 = futureOpen/nextOpen-1; hold versus sell next open, same quantity/sell fee, no new BUY fee",
        "risk_open_h": "max(0,1-min(Open/Close at T+1..T+h and final Open[T+1+h])/Open[T+1]); fixed daily observations, excludes initial Tclose->nextOpen gap",
        "marked_close_net_h": "(1-f)*Open[T+1+h]/Close[T]-1; remaining holding liquidation from Tclose mark, exactly one future SELL fee and no sunk BUY fee",
        "risk_close_h": "max(0,1-same_future_observed_min/Close[T]); includes initial next-open movement; price risk not fee-adjusted",
        "immediate_close_net": "(1-f)*Open[T+1]/Close[T]-1; companion showing next-open liquidation and unavoidable first overnight",
        "increment_mark_h": "marked_close_net_h-immediate_close_net = (1-f)*(futureOpen-nextOpen)/Close[T]",
        "maturity": "all horizon labels mature at final Open[T+1+h]; missing tails remain missing, no extension",
        "statistical_primary": ["return_4", "downside_4"],
        "statistical_auxiliary": ["return_8", "downside_8"],
        "accounting_companions_only": "close-mark labels, risk_close, immediate liquidation and increment_mark retained but no additional model/IC searches",
    },
    "fee": 0.001,
    "risk_limit": "OPEN/CLOSE observation downside omits intraday extremes and is not actual path or account maximum drawdown; High/Low deliberately unused",
    "counterfactual": "fixed T quantity hypothetically retained across future old strategy exits; not old realized account return and not a proposed execution rule",
    "strongest_counterargument": "next-open continuation return is affine-equivalent to old fee-adjusted fresh-entry label; fee removal cannot create predictive ordering; novelty is actual-held pool and causal holding controls",
    "selection": "retain every requested T row; flat age/PnL remain NaN, not zero; future label or future trade exit cannot select population",
}


def _dates(index):
    if not isinstance(index, pd.DatetimeIndex) or index.tz is not None or index.hasnans:
        raise ValueError("finite timezone-naive DatetimeIndex required")
    if (
        index.has_duplicates
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("unique increasing daily-midnight dates required")


def build_known_state(account, fills, decisions, signal_index):
    """Replay only past fills to expose entry metadata; never consume trade exits."""
    _dates(signal_index)
    ledger = account.set_index("date").copy()
    ledger.index = pd.to_datetime(ledger.index).as_unit("ns")
    _dates(ledger.index)
    if not signal_index.isin(ledger.index).all():
        raise ValueError("requested signal dates must have T-close account rows")
    if ledger.iloc[0].quantity_before != 0:
        raise ValueError("opening position requires its actual prior BUY evidence")
    numeric = ledger[["quantity_before", "quantity", "close"]].to_numpy(float)
    if not np.isfinite(numeric).all() or (numeric[:, :2] < 0).any() or (numeric[:, 2] <= 0).any():
        raise ValueError("finite nonnegative holdings and positive marks required")
    if not np.equal(numeric[:, :2], np.floor(numeric[:, :2])).all():
        raise ValueError("integer quantities required")
    if not np.array_equal(ledger.quantity_before.iloc[1:], ledger.quantity.iloc[:-1]):
        raise ValueError("ledger holdings must be continuous")
    events = fills.copy()
    times = pd.DatetimeIndex(pd.to_datetime(events.fill_time)).as_unit("ns")
    if (
        times.tz is not None
        or times.hasnans
        or not times.is_monotonic_increasing
        or events.fill_id.duplicated().any()
    ):
        raise ValueError("finite chronological unique fills required")
    values = events[["quantity", "price", "fees"]].to_numpy(float)
    if not np.isfinite(values).all() or (values[:, :2] <= 0).any() or (values[:, 2] < 0).any():
        raise ValueError("positive fill quantity/price and nonnegative fees required")
    if (
        not np.equal(values[:, 0], np.floor(values[:, 0])).all()
        or not events.side.isin(["BUY", "SELL"]).all()
    ):
        raise ValueError("integer BUY/SELL fills required")
    if ((times - times.normalize()) > pd.Timedelta(hours=15)).any():
        raise ValueError("fills after T-close are not T decision information")
    signal_dates = pd.DatetimeIndex(pd.to_datetime(events.signal_date)).normalize()
    if not (signal_dates < times.normalize()).all():
        raise ValueError("fill signal must precede execution session")
    position, gross_cost, entry_pos, pointer = 0, 0.0, None, 0
    rows = []
    for i, (day, row) in enumerate(ledger.iterrows()):
        if day > signal_index[-1]:
            break
        if position != int(row.quantity_before):
            raise ValueError("past-fill quantity disagrees with ledger opening")
        while pointer < len(events) and times[pointer].normalize() <= day:
            if times[pointer].normalize() != day:
                raise ValueError("fill execution date missing in ledger")
            event = events.iloc[pointer]
            quantity = int(event.quantity)
            if event.side == "BUY":
                if position == 0:
                    entry_pos = i
                position += quantity
                gross_cost += quantity * float(event.price)
            else:
                if quantity > position:
                    raise ValueError("SELL exceeds known holdings")
                gross_cost *= (position - quantity) / position
                position -= quantity
                if position == 0:
                    gross_cost, entry_pos = 0.0, None
            pointer += 1
        if position != int(row.quantity):
            raise ValueError("past-fill quantity disagrees with T-close ledger")
        held = position > 0
        rows.append(
            {
                "Date": day,
                "actual_quantity": position,
                "actual_held": held,
                "holding_age": float(i - entry_pos + 1) if held else np.nan,
                "entry_mark_pnl": float(row.close) / (gross_cost / position) - 1
                if held
                else np.nan,
                "entry_gross_price": gross_cost / position if held else np.nan,
                "entry_session": ledger.index[entry_pos] if held else pd.NaT,
            }
        )
    state = pd.DataFrame(rows).set_index("Date").reindex(signal_index)
    before = decisions.copy().set_index("valid_session")
    before.index = pd.to_datetime(before.index).as_unit("ns")
    after = decisions.copy().set_index("signal_date")
    after.index = pd.to_datetime(after.index).as_unit("ns")
    if before.index.has_duplicates or after.index.has_duplicates:
        raise ValueError("unique decision/valid dates required")
    for name, source in (("signal_held_before", before), ("signal_held_after", after)):
        if (
            not signal_index.isin(source.index).all()
            or not source.target_position.isin([0, 1]).all()
        ):
            raise ValueError("every T needs original 0/1 signal state")
        state[name] = source.target_position.reindex(signal_index).astype(bool)
    state.index = state.index.rename("Date")
    return state


def build_labels(prices, signal_index):
    """Future labels only; caller never joins them into predictor input."""
    _dates(prices.index)
    _dates(signal_index)
    if not signal_index.isin(prices.index).all():
        raise ValueError("signal calendar outside original price coverage")
    values = prices[["Open", "Close"]].to_numpy(float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("positive finite Open/Close labels required")
    output = pd.DataFrame(index=signal_index)
    for horizon in (4, 8):
        names = (
            f"return_{horizon}",
            f"downside_{horizon}",
            f"marked_close_net_{horizon}",
            f"risk_close_{horizon}",
            f"increment_mark_{horizon}",
        )
        for name in names:
            output[name] = np.nan
            output["label_end_" + name] = pd.NaT
        for day in signal_index:
            i = prices.index.get_loc(day)
            if i + horizon + 1 >= len(prices):
                continue
            mark, next_open, final_open = values[i, 1], values[i + 1, 0], values[i + horizon + 1, 0]
            observed_min = min(values[i + 1 : i + horizon + 1].min(), final_open)
            liquidation = 0.999 * final_open / mark - 1
            immediate = 0.999 * next_open / mark - 1
            observations = (
                final_open / next_open - 1,
                max(0.0, 1 - observed_min / next_open),
                liquidation,
                max(0.0, 1 - observed_min / mark),
                liquidation - immediate,
            )
            for name, value in zip(names, observations):
                output.loc[day, name] = value
                output.loc[day, "label_end_" + name] = prices.index[i + horizon + 1]
    output["immediate_close_net"] = np.nan
    output["initial_gap_price"] = np.nan
    for day in signal_index:
        i = prices.index.get_loc(day)
        if i + 1 < len(prices):
            output.loc[day, "immediate_close_net"] = 0.999 * values[i + 1, 0] / values[i, 1] - 1
            output.loc[day, "initial_gap_price"] = values[i + 1, 0] / values[i, 1] - 1
    return output
