"""Pure first actual BUY authentication and fixed two-part continuation labels."""

import numpy as np
import pandas as pd

METHOD = {
    "version": "s013-pressure-entry-late-continuation-v1",
    "entry": "Replay first positive BUY from flat; freeze flag and original controls at its fill.signal_date T; BUY must match original T action/regime and execute valid_session=T+1. No future SELL/trade-exit population selection.",
    "pressure": "Last4 complete sessions including T: sum max(-log(Open[s]/Close[s-1]),0) > sum max(-log(Close[s]/Open[s]),0); equality or no down => false; missing warmup unavailable, never false fallback.",
    "primary": {
        "late_return": "Open[T+5]/Open[T+3]-1; fixed quantity and same single SELL fee cancel; no fresh BUY fee",
        "late_downside": "max(0,1-min(Open/Close[T+3,T+4],Open[T+5])/Open[T+3]); initial unavoidable overnight excluded, no HL, not actual account/path DD",
    },
    "companions": "first2=Open[T+3]/Open[T+1]-1; full4=Open[T+5]/Open[T+1]-1; (1+first2)*(1+late_return)=1+full4. Descriptive algebra only, no IC/CI/model.",
    "maturity": "late/full/risk mature at T+5 OPEN; first2 at T+3 OPEN; missing end stays NaN/NaT, no extension",
    "counterfactual": "hypothetical continuation across old actual exits, not native account PnL or a proposed exit implementation",
    "quantity": "first entry-session filled quantity documented only; labels normalized price returns, no quantity or future exit selection",
}


def dates(index):
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.tz is not None
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("unique ordered timezone-naive midnight dates required")


def prices_valid(prices):
    dates(prices.index)
    data = prices[["Open", "Close"]].to_numpy(float)
    if not np.isfinite(data).all() or (data <= 0).any():
        raise ValueError("finite positive Open/Close required")
    return data


def pressure(prices):
    prices_valid(prices)
    overnight = (
        (-np.log(prices.Open / prices.Close.shift())).clip(lower=0).rolling(4, min_periods=4).sum()
    )
    intraday = (-np.log(prices.Close / prices.Open)).clip(lower=0).rolling(4, min_periods=4).sum()
    available = overnight.notna() & intraday.notna()
    denom = overnight + intraday
    share = overnight / denom
    share.loc[available & denom.eq(0)] = 0
    flag = pd.Series(np.nan, index=prices.index)
    flag.loc[available] = overnight[available].gt(intraday[available]).astype(float)
    return pd.DataFrame(
        {
            "overnight_down4": overnight,
            "intraday_down4": intraday,
            "pressure_share4": share,
            "pressure_flag": flag,
            "pressure_available": available,
        }
    )


def actual_entries(account, fills, decisions):
    ledger = account.set_index("date").copy()
    ledger.index = pd.DatetimeIndex(pd.to_datetime(ledger.index)).as_unit("ns")
    dates(ledger.index)
    d = decisions.set_index("signal_date").copy()
    d.index = pd.DatetimeIndex(pd.to_datetime(d.index)).as_unit("ns")
    dates(d.index)
    ev = fills.copy()
    times = pd.DatetimeIndex(pd.to_datetime(ev.fill_time)).as_unit("ns")
    if (
        times.tz is not None
        or times.hasnans
        or not times.is_monotonic_increasing
        or ev.fill_id.duplicated().any()
    ):
        raise ValueError("chronological unique fills required")
    values = ev[["quantity", "price", "fees"]].to_numpy(float)
    if (
        not np.isfinite(values).all()
        or (values[:, :2] <= 0).any()
        or (values[:, 2] < 0).any()
        or not np.equal(values[:, 0], np.floor(values[:, 0])).all()
    ):
        raise ValueError("positive integer BUY/SELL quantity and finite price/fees required")
    if (
        not ev.side.isin(["BUY", "SELL"]).all()
        or ((times - times.normalize()) > pd.Timedelta(hours=15)).any()
    ):
        raise ValueError("known by close BUY/SELL required")
    if int(ledger.iloc[0].quantity_before) != 0:
        raise ValueError("full original account beginning flat required")
    position, pointer, records, active_record = 0, 0, [], None
    for day, row in ledger.iterrows():
        if float(row.quantity_before) != position:
            raise ValueError("opening holdings disagree with past fills")
        while pointer < len(ev) and times[pointer].normalize() <= day:
            if times[pointer].normalize() != day:
                raise ValueError("fill day missing from original account calendar")
            e = ev.iloc[pointer]
            t = pd.Timestamp(e.signal_date).normalize()
            if t >= day or t not in d.index:
                raise ValueError("fill must identify a past original decision")
            decision = d.loc[t]
            if pd.Timestamp(decision.valid_session).normalize() != day or decision.action != e.side:
                raise ValueError("fill must match original action and T+1 valid session")
            if e.side == "BUY":
                if position == 0:
                    if decision.signal_reason != "entry" or decision.regime not in ("bear", "bull"):
                        raise ValueError("original entry identity required")
                    records.append(
                        {
                            "signal_date": t,
                            "entry_session": day,
                            "regime": decision.regime,
                            "entry_fill_id": str(e.fill_id),
                            "entry_quantity": 0,
                            "first_fill_price": float(e.price),
                            "entry_fill_time": times[pointer],
                        }
                    )
                    active_record = len(records) - 1
                if records[active_record]["entry_session"] == day:
                    records[active_record]["entry_quantity"] += int(e.quantity)
                position += int(e.quantity)
            else:
                position -= int(e.quantity)
                if position < 0:
                    raise ValueError("SELL exceeds known position")
                if position == 0:
                    active_record = None
            pointer += 1
        if float(row.quantity) != position:
            raise ValueError("close holdings disagree with past fills")
    if pointer != len(ev):
        raise ValueError("fills outside account calendar")
    out = pd.DataFrame(records).set_index("signal_date")
    dates(out.index)
    # Future old exits are replayed only to authenticate the account, never used as selectors.
    return out


def labels(prices, signal_index):
    values = prices_valid(prices)
    dates(signal_index)
    if not signal_index.isin(prices.index).all():
        raise ValueError("T must be in original execution calendar")
    out = pd.DataFrame(index=signal_index)
    for n in ("first2", "late_return", "full4", "late_downside"):
        out[n], out["label_end_" + n] = np.nan, pd.NaT
    for t in signal_index:
        i = prices.index.get_loc(t)
        if i + 3 < len(prices):
            out.loc[t, "first2"] = values[i + 3, 0] / values[i + 1, 0] - 1
            out.loc[t, "label_end_first2"] = prices.index[i + 3]
        if i + 5 >= len(prices):
            continue
        base, final = values[i + 3, 0], values[i + 5, 0]
        v = {
            "late_return": final / base - 1,
            "full4": final / values[i + 1, 0] - 1,
            "late_downside": max(0.0, 1 - min(values[i + 3 : i + 5].min(), final) / base),
        }
        for n, value in v.items():
            out.loc[t, n] = value
            out.loc[t, "label_end_" + n] = prices.index[i + 5]
    return out
