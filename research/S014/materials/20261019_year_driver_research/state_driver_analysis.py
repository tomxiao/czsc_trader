"""C0056 observed-account state attribution; no rules, fits or counterfactuals.

Real execution requires published source/design EvidenceRefs in --lock. Synthetic
checks do not read any research input. All state features precede outcome day E.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import itertools
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
ATOMS = ("entry_mark_pnl", "hold_mark_pnl", "exit_mark_pnl", "fees_pnl")
COMPONENTS = ("hold_market_pnl", "hold_sector_minus_market_pnl", "hold_stock_minus_sector_pnl")
POSTURES = ("PLAN_BUY", "PLAN_SELL", "HOLD", "FLAT")
STATES = tuple(f"{outside}__STOCK_{stock}" for outside in ("COMMON_UP", "COMMON_NONUP", "DIVERGENT")
               for stock in ("UP", "NONUP")) + ("UNKNOWN",)
ACCOUNT_SHA = "7d535b90bfc6edaf78833bfd2c317425e59615d50dee4464aac7be1f3eebd5ab"
ACCOUNT_RESULT = "423a1ccf05574d17eb4fa3d5984de02dc869c7387cbe66bf4f502b54c7510ef6"
PINNED = {
    "features20": ("EX032_20261018", "others/inputs.csv", "5b3429c2b4eb2d7d8061bc396d911f8262a123968660b62fc9ec28faeb825722"),
    "features1": ("EX033_20261018", "others/decision_features.csv", "2acb27cdff70de69c4a16776b1ffa4145da966a1239b33a727e56902a95eb605"),
    "calendar": ("EX032_20261018", "others/calendar.csv", "046902392e6c280f24242a5f1097b6e390446da33a6da99c41690143b1c665c4"),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def close(left, right, message, atol=1e-7, rtol=0):
    require(np.allclose(left, right, atol=atol, rtol=rtol, equal_nan=False), message)


def published(value, expected_sha=None):
    from czsc_trader.research_tools import EvidenceRef

    ref = EvidenceRef.from_dict(value)
    require(ref.experiment.strategy_id == "S014", "Only S014 references are permitted")
    if expected_sha is not None:
        require(ref.sha256 == expected_sha, "Unexpected published source identity")
    raw = ref.resolve(ROOT).read_bytes()
    require(sha256(raw).hexdigest() == ref.sha256, "Published bytes differ")
    return raw, ref.to_dict()


def boolean(series):
    require(series.notna().all() and series.astype(str).isin(["True", "False", "0", "1", "0.0", "1.0"]).all(),
            "Missing or invalid explicit boolean")
    return series.astype(str).isin(["True", "1", "1.0"])


def dated(frame, column="date"):
    result = frame.copy()
    result[column] = pd.to_datetime(result[column], errors="raise").dt.normalize()
    require(result[column].notna().all() and not result[column].duplicated().any(), "Invalid unique date key")
    require(result[column].is_monotonic_increasing, "Source dates are not ascending")
    return result


def classify(stock, market, sector):
    if not all(np.isfinite(v) for v in (stock, market, sector)):
        return "UNKNOWN"
    outside = "COMMON_UP" if market > 0 and sector > 0 else (
        "COMMON_NONUP" if market <= 0 and sector <= 0 else "DIVERGENT")
    return f"{outside}__STOCK_{'UP' if stock > 0 else 'NONUP'}"


def atoms_from_ledger(daily, fills, initial_cash):
    """Independent arithmetic of original fills, never a replay or alternate fill."""
    d = dated(daily)
    require(np.isfinite(d[["cash", "cash_before", "close", "equity", "quantity", "quantity_before"]]).all().all(),
            "Invalid original account value")
    require((d.close > 0).all() and (d.equity > 0).all(), "Nonpositive original valuation")
    close(d.quantity_before, d.quantity.shift(fill_value=0), "Position path breaks")
    close(d.cash_before, d.cash.shift(fill_value=initial_cash), "Cash path breaks")
    close(d.cash + d.quantity * d.close, d.equity, "Original NAV identity differs")
    previous_close = d.close.shift()
    previous_equity = d.equity.shift(fill_value=initial_cash)
    f = fills.copy()
    if not f.empty:
        f["date"] = pd.to_datetime(f.fill_time).dt.normalize()
        require(not f.date.duplicated().any(), "More than one daily fill is unsupported by original contract")
        require(f.date.isin(d.date).all(), "Fill lies outside original account")
        require(f.side.isin(["BUY", "SELL"]).all(), "Unexpected original fill side")
        close(f.fees, f.quantity * f.price * .001, "Original fill fee differs", atol=1e-6)
        lookup = f.set_index("date").to_dict("index")
    else:
        lookup = {}
    rows = []
    for i, row in d.iterrows():
        atoms = dict.fromkeys(ATOMS, 0.)
        phase = "FLAT"
        fill = lookup.get(row.date)
        if fill is not None:
            atoms["fees_pnl"] = -float(fill["fees"])
            if fill["side"] == "BUY":
                require(row.quantity_before == 0 and row.quantity == fill["quantity"], "Entry quantity differs")
                atoms["entry_mark_pnl"] = float(fill["quantity"] * (row.close - fill["price"]))
                phase = "ENTRY"
            else:
                require(i > 0 and row.quantity_before == fill["quantity"] and row.quantity == 0,
                        "Exit quantity differs")
                atoms["exit_mark_pnl"] = float(fill["quantity"] * (fill["price"] - previous_close.iloc[i]))
                phase = "EXIT"
        elif row.quantity_before:
            require(i > 0 and row.quantity_before == row.quantity, "Hold quantity differs")
            atoms["hold_mark_pnl"] = float(row.quantity * (row.close - previous_close.iloc[i]))
            phase = "HOLD"
        else:
            require(row.quantity == 0, "Unexplained new quantity")
        rows.append({"date": row.date, **atoms, "actual_pnl": float(row.equity - previous_equity.iloc[i]),
                     "phase": phase})
    result = pd.DataFrame(rows)
    close(result[list(ATOMS)].sum(axis=1), result.actual_pnl, "Original daily four-atom identity differs", atol=1e-6)
    return result


def build_panel(daily, decisions, fills, buyhold, features20, features1, reconciliation,
                calendar, initial_cash=100000., enforce_real=True, orders=None):
    d, b, f20, f1, original = map(dated, (daily, buyhold, features20, features1, reconciliation))
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    for frame in (d, b, f20, f1, original):
        require(frame.date.tolist() == calendar.tolist(), "Exact calendar identity differs")
    if enforce_real:
        require(len(calendar) == 1642 and set(calendar.year) == set(range(2020, 2027)), "Wrong original evaluation window")
    require(f20.signal.tolist() == list(range(len(calendar))), "Feature signal ordinal differs")
    require((b.equity > 0).all(), "Invalid original BuyHold wealth")
    close(d.close, b.close, "Strategy/BuyHold price units differ")
    require(d.valuation_source_date.tolist() == b.valuation_source_date.tolist(), "Valuation identities differ")
    derived = atoms_from_ledger(d, fills, initial_cash)
    require(derived.phase.tolist() == original.phase.tolist(), "Published phase classification differs")
    for column in (*ATOMS, "actual_pnl"):
        # The published CSV uses %.12g; permit its declared decimal serialization only.
        close(derived[column], original[column], f"Published original {column} differs", atol=1e-6, rtol=6e-12)
    dec = decisions.copy()
    dec["valid_session"] = pd.to_datetime(dec.valid_session).dt.normalize()
    dec["signal_date"] = pd.to_datetime(dec.signal_date).dt.normalize()
    require(len(dec) == len(d) and dec.valid_session.tolist() == calendar.tolist(), "D valid_session != E")
    require(dec.signal_date.tolist() == pd.to_datetime(d.signal_date).dt.normalize().tolist(), "Ledger/decision signal dates differ")
    require((dec.signal_date < dec.valid_session).all(), "Decision is not strictly before E")
    require(dec.signal_date.iloc[1:].tolist() == calendar[:-1].tolist(), "D is not exact preceding session")
    require(dec.signal_date.iloc[0] < calendar[0], "First D must precede first E")
    held, pending, entry = map(boolean, (dec.held_at_close, dec.exit_pending, dec.entry_signal))
    require(held.eq(d.quantity_before.gt(0)).all(), "Known D position differs from E opening position")
    require((~entry | ~held).all(), "Entry signal while already held")
    posture = np.select([entry, held & pending, held], POSTURES[:3], default="FLAT")
    target = np.isin(posture, ["PLAN_BUY", "HOLD"]).astype(float)
    close(dec.target_position, target, "D posture target differs", atol=0)
    close(d.target_position, dec.target_position, "E target differs from D", atol=0)
    require(orders is not None or not enforce_real, "Original orders are required")
    if orders is not None:
        require(dec.decision_id.notna().all() and not dec.decision_id.duplicated().any(),
                "Original decision IDs are not unique")
        planned = dec.loc[np.isin(posture, ["PLAN_BUY", "PLAN_SELL"]),
                          ["decision_id", "signal_date", "valid_session"]].copy()
        planned["expected_side"] = np.where(np.asarray(posture)[np.isin(posture, ["PLAN_BUY", "PLAN_SELL"])]
                                            == "PLAN_BUY", "BUY", "SELL")
        order = orders.copy()
        require(order.decision_id.notna().all() and not order.decision_id.duplicated().any(),
                "More than one original order per decision")
        require(len(order) == len(planned) and set(order.decision_id) == set(planned.decision_id),
                "Original order IDs do not exactly cover planned D postures")
        order["order_signal_date"] = pd.to_datetime(order.signal_date).dt.normalize()
        order["order_execution_date"] = pd.to_datetime(order.execution_date).dt.normalize()
        joined = planned.merge(order[["decision_id", "side", "order_signal_date", "order_execution_date"]],
                               on="decision_id", how="inner", validate="one_to_one")
        require(joined.side.eq(joined.expected_side).all(), "Original order side differs from D posture")
        require(joined.order_signal_date.eq(joined.signal_date).all()
                and joined.order_execution_date.eq(joined.valid_session).all(), "Original order D/E dates differ")
    source20 = f20.set_index("date")
    # Stock ret20 is simple (EX008); external ret20 fields are logarithmic (EX009/10).
    stock20 = d.close / d.close.shift(20) - 1
    for name, expected in (("ret20", stock20),
                           ("market_ret20", np.log1p(f1.market_return).rolling(20).sum()),
                           ("sector_ret20", np.log1p(f1.sector_return).rolling(20).sum())):
        comparable = np.isfinite(f20[name]) & np.isfinite(expected)
        require(comparable.iloc[20:].all(), "Missing required post-warmup feature identity")
        close(f20.loc[comparable, name], expected.loc[comparable], f"Twenty-session {name} semantics differ", atol=1e-10)
    one_day = d.close / d.close.shift() - 1
    close(one_day.iloc[1:], f1.stock_return.iloc[1:], "Same-day simple stock return/ledger ratio differs", atol=1e-10)
    require((f1[["market_return", "sector_return"]].iloc[1:] > -1).all().all(), "Invalid external simple return")
    state_input = source20.reindex(pd.DatetimeIndex(dec.signal_date))
    state_input.index = d.index
    panel = d.copy()  # Preserve every original account_daily field and its meaning.
    for column in dec:
        panel[f"D_{column}"] = dec[column].to_numpy()
    for column in b:
        panel[f"buyhold_{column}"] = b[column].to_numpy()
    for column in original:
        if column != "date":
            panel[column] = original[column].to_numpy()
    for column in ("ret20", "market_ret20", "sector_ret20"):
        panel[f"D_{column}"] = state_input[column].to_numpy()
    panel["D_state"] = [classify(*values) for values in state_input[["ret20", "market_ret20", "sector_ret20"]].to_numpy()]
    panel["D_posture"] = posture
    panel["D_ready"] = boolean(dec.ready).to_numpy()
    previous_equity = d.equity.shift(fill_value=initial_cash)
    previous_bh = b.equity.shift(fill_value=initial_cash)
    previous_price = d.close.shift()
    require(d.quantity_before.iloc[0] == 0, "Initial held exposure requires prior exact valuation")
    exposure = (d.quantity_before * previous_price).where(d.quantity_before.gt(0), 0.)
    panel["known_position_value_D"] = exposure
    panel["known_exposure_D"] = exposure / previous_equity
    panel["previous_equity"] = previous_equity
    panel["previous_ledger_close"] = previous_price
    panel["actual_daily_return"] = d.equity / previous_equity - 1
    panel["buyhold_pnl"] = b.equity - previous_bh
    panel["buyhold_daily_return"] = b.equity / previous_bh - 1
    panel["active_log_return"] = np.log(d.equity / previous_equity) - np.log(b.equity / previous_bh)
    panel["year"] = calendar.year
    panel["month"] = calendar.strftime("%Y-%m")
    panel["annual_open_equity"] = panel.groupby("year").previous_equity.transform("first")
    panel["buyhold_annual_open_equity"] = pd.Series(previous_bh).groupby(calendar.year).transform("first")
    panel["annual_return_contribution"] = panel.actual_pnl / panel.annual_open_equity
    panel["buyhold_annual_return_contribution"] = panel.buyhold_pnl / panel.buyhold_annual_open_equity
    hold = panel.phase.eq("HOLD")
    # These E-day returns are ex-post HOLD accounting components, NEVER state features.
    for column in ("stock_return", "market_return", "sector_return", "amplitude", "hfq_close", "previous_date"):
        panel[f"E_{column}"] = f1[column].to_numpy()
    component_values = (exposure * f1.market_return,
                        exposure * (f1.sector_return - f1.market_return),
                        exposure * (f1.stock_return - f1.sector_return))
    for name, values in zip(COMPONENTS, component_values, strict=True):
        panel[name] = values.where(hold, np.nan)
    close(panel.loc[hold, list(COMPONENTS)].sum(axis=1), panel.loc[hold, "hold_mark_pnl"],
          "Exact same-unit HOLD attribution differs", atol=1e-6, rtol=6e-12)
    require(panel.loc[~hold, list(COMPONENTS)].isna().all().all(), "Non-HOLD phase given industry attribution")
    return panel


def group_summary(g):
    n = len(g)
    return {"days": n, "known_exposure_days": int(g.known_exposure_D.gt(0).sum()),
            "ready_days": int(g.D_ready.sum()),
            "phases": {phase: int(g.phase.eq(phase).sum()) for phase in ("ENTRY", "HOLD", "EXIT", "FLAT")},
            "actual_pnl": float(g.actual_pnl.sum()),
            "original_annual_return_contribution": float(g.annual_return_contribution.sum()),
            "buyhold_annual_return_contribution": float(g.buyhold_annual_return_contribution.sum()),
            "mean_actual_daily_return": float(g.actual_daily_return.mean()) if n else None,
            "mean_buyhold_daily_return": float(g.buyhold_daily_return.mean()) if n else None,
            "mean_active_log_return": float(g.active_log_return.mean()) if n else None,
            "mean_known_exposure_D": float(g.known_exposure_D.mean()) if n else None,
            "active_log_return_sum": float(g.active_log_return.sum()),
            "atoms": {atom: float(g[atom].sum()) for atom in ATOMS},
            "hold_accounting_components": {name: float(g[name].sum()) if g[name].notna().any() else None
                                           for name in COMPONENTS}}


def summaries(panel):
    annual, monthly, groups, references = [], [], [], []
    for year, g in panel.groupby("year", sort=True):
        opening = float(g.annual_open_equity.iloc[0])
        actual = float(g.equity.iloc[-1] / opening - 1)
        close(g.actual_pnl.sum() / opening, actual, "Annual original contribution does not reconcile", atol=1e-10)
        close(g.annual_return_contribution.sum(), actual, "Annual grouped contribution does not reconcile", atol=1e-10)
        bh_return = float(g.buyhold_equity.iloc[-1] / g.buyhold_annual_open_equity.iloc[0] - 1)
        close(g.buyhold_annual_return_contribution.sum(), bh_return, "Annual BuyHold contribution differs", atol=1e-10)
        close(g.active_log_return.sum(), np.log1p(actual) - np.log1p(bh_return), "Annual active log differs", atol=1e-10)
        annual.append({"year": int(year), "opening_equity": opening, "closing_equity": float(g.equity.iloc[-1]),
                       "return": actual, "buyhold_return": bh_return, **group_summary(g)})
        for state, posture in itertools.product(STATES, POSTURES):
            subset = g.loc[g.D_state.eq(state) & g.D_posture.eq(posture)]
            groups.append({"year": int(year), "state": state, "D_posture": posture, **group_summary(subset)})
            for mode, selection in (("ALL_OTHER_YEARS", panel.year.ne(year)), ("PAST_ONLY", panel.year.lt(year))):
                other = panel.loc[selection & panel.D_state.eq(state) & panel.D_posture.eq(posture)]
                references.append({"target_year": int(year), "state": state, "D_posture": posture,
                                   "mode": mode, "target_days": len(subset), "reference_days": len(other),
                                   "reference_years": sorted(int(v) for v in other.year.unique()),
                                   "support": "OBSERVED_SAME_STATE_POSTURE" if len(other) else "NO_SUPPORT",
                                   "observed_reference_mean_daily_return": float(other.actual_daily_return.mean()) if len(other) else None,
                                   "observed_reference_mean_active_log": float(other.active_log_return.mean()) if len(other) else None,
                                   "observed_reference_mean_known_exposure": float(other.known_exposure_D.mean()) if len(other) else None})
    for month, g in panel.groupby("month", sort=True):
        month_return = float(g.equity.iloc[-1] / g.previous_equity.iloc[0] - 1)
        close(g.actual_pnl.sum(), g.equity.iloc[-1] - g.previous_equity.iloc[0], "Monthly money reconciliation differs", atol=1e-6)
        close(np.log1p(g.actual_daily_return).sum(), np.log1p(month_return), "Monthly wealth return differs", atol=1e-10)
        monthly.append({"month": month, "month_return": month_return, **group_summary(g)})
    return {"annual": annual, "monthly": monthly, "year_state_D_posture": groups,
            "cross_year_observed_references": references}


def load_inputs(lock_path):
    lock = json.loads(lock_path.read_bytes())
    source_raw, source_ref = published(lock["source"])
    require(source_raw == Path(__file__).read_bytes(), "Source differs from publicly locked bytes")
    _, design_ref = published(lock["design"])
    refs = {"source": source_ref, "design": design_ref}
    raw = {}
    for name, (experiment, key, checksum) in PINNED.items():
        result = json.loads((ROOT / f"research/S014/experiments/{experiment}/others/result.json").read_bytes())
        raw[name], refs[name] = published(result["evidence"][key], checksum)
    publication = json.loads((ROOT / "research/S014/materials/20261018_c0056_coverage_review/publication.json").read_bytes())
    review_raw, refs["account_review"] = published(publication["evidence"]["account_review.json"],
        "bd65fda1cf6571575be9e0bae29ce55a8ab17aaf0adb5859acb85ef0889461c0")
    reconciliation_raw, refs["daily_reconciliation"] = published(publication["evidence"]["daily_reconciliation.csv"],
        "4506ba6c4bc913abdc30660b9f15b10e70f60fc1170f51adc6698624320a0a87")
    review = json.loads(review_raw)
    account_raw, refs["original_account_and_embedded_buyhold"] = published(review["account_evidence"], ACCOUNT_SHA)
    account = json.loads(account_raw)
    require(account["result_hash"] == review["account_result_hash"] == ACCOUNT_RESULT, "Original result hash differs")
    require(len(account["runs"]) == 1, "Original account must contain one run")
    request = account["request_identity"]
    require(request["strategy_reference"] == "S014-C0056" and request["initial_cash"] == 100000,
            "Wrong original candidate or cash")
    require(request["symbol"] == "600722.SH" and request["price_basis"] == "HFQ_RESEARCH", "Wrong account price identity")
    require(request["pricing"]["quantity_unit"] == "RESEARCH_UNIT", "Wrong account quantity units")
    run = account["runs"][0]
    require(run["buyhold"]["benchmark"] == request["benchmark"], "Embedded BuyHold contract differs")
    ledgers = run["ledgers"]
    tables = {name: pd.DataFrame(ledgers[name]["data"]) for name in ("account_daily", "decisions", "fills", "orders")}
    panel = build_panel(tables["account_daily"], tables["decisions"], tables["fills"],
                        pd.DataFrame(run["buyhold"]["account_daily"]["data"]),
                        pd.read_csv(BytesIO(raw["features20"]), usecols=["date", "signal", "ret20", "market_ret20", "sector_ret20"]),
                        pd.read_csv(BytesIO(raw["features1"])), pd.read_csv(BytesIO(reconciliation_raw)),
                        pd.read_csv(BytesIO(raw["calendar"])).date, initial_cash=request["initial_cash"],
                        orders=tables["orders"])
    for annual in review["annual"]:
        g = panel.loc[panel.year.eq(annual["year"])]
        close(g.annual_return_contribution.sum(), annual["return"], "Original formal annual review differs", atol=1e-10)
    return panel, refs, {"price_basis": request["price_basis"], "pricing": request["pricing"],
                        "data_identity": request["data_identity"], "result_hash": account["result_hash"]}


def synthetic_check():
    require(classify(0, 0, 0) == "COMMON_NONUP__STOCK_NONUP", "Zero boundary differs")
    require(classify(.1, .1, .1) == "COMMON_UP__STOCK_UP", "Positive boundary differs")
    require(classify(-.1, .1, -.1) == "DIVERGENT__STOCK_NONUP", "Mixed external state differs")
    require(classify(np.nan, .1, .1) == "UNKNOWN", "Missing feature must remain unknown")
    require({classify(s, m, t) for s in (-.1, .1) for m, t in ((.1, .2), (0., -.1), (.1, -.1))}
            == set(STATES) - {"UNKNOWN"}, "All six fixed states must be reachable")
    dates = pd.bdate_range("2023-12-01", periods=70)
    price = 10. * np.exp(np.arange(70) * .001)
    quantity = np.zeros(70)
    cash = np.full(70, 100000.)
    quantity[5:31] = 100
    buy_fee = 100 * price[5] * .001
    sell_fee = 100 * price[31] * .001
    cash[5:31] -= 100 * price[5] + buy_fee
    cash[31:] = cash[5] + 100 * price[31] - sell_fee
    signal_dates = pd.DatetimeIndex([dates[0] - pd.Timedelta(days=1), *dates[:-1]])
    d = pd.DataFrame({"date": dates, "close": price, "cash": cash, "quantity": quantity,
                      "quantity_before": np.r_[0, quantity[:-1]], "cash_before": np.r_[100000., cash[:-1]],
                      "equity": cash + quantity * price, "signal_date": signal_dates,
                      "valuation_source_date": dates, "target_position": quantity.astype(bool).astype(float)})
    # E=31 executes the sell planned at D; E=32 failed-buy reset must remain FLAT.
    dec = pd.DataFrame({"signal_date": signal_dates, "valid_session": dates, "entry_signal": False,
                        "held_at_close": d.quantity_before.gt(0), "exit_pending": False,
                        "ready": True, "action": "HOLD", "target_position": d.target_position})
    dec.loc[5, "entry_signal"] = True
    dec.loc[31, "exit_pending"] = True
    dec.loc[32, "action"] = "SELL"
    dec.loc[0:3, "ready"] = False
    dec["decision_id"] = [f"synthetic-decision-{i}" for i in range(70)]
    fills = pd.DataFrame({"fill_time": [dates[5], dates[31]], "side": ["BUY", "SELL"],
                          "price": price[[5, 31]], "quantity": [100, 100], "fees": [buy_fee, sell_fee]})
    atoms = atoms_from_ledger(d, fills, 100000.)
    returns = pd.Series(price).pct_change()
    f1 = pd.DataFrame({"date": dates, "stock_return": returns, "market_return": returns * .4,
                       "sector_return": returns * .7, "amplitude": .02, "hfq_close": price * 5.892,
                       "previous_date": signal_dates})
    f20 = pd.DataFrame({"date": dates, "signal": range(70), "ret20": pd.Series(price).pct_change(20),
                        "market_ret20": np.log1p(f1.market_return).rolling(20).sum(),
                        "sector_ret20": np.log1p(f1.sector_return).rolling(20).sum()})
    orders = pd.DataFrame({"decision_id": dec.loc[[5, 31], "decision_id"].to_list(),
                           "signal_date": signal_dates[[5, 31]], "execution_date": dates[[5, 31]],
                           "side": ["BUY", "SELL"]})
    calendar_series = pd.Series(dates.strftime("%Y-%m-%d"))
    panel = build_panel(d, dec, fills, d.copy(), f20, f1, atoms, calendar_series,
                        enforce_real=False, orders=orders)
    require(panel.D_state.iloc[20] == "UNKNOWN" and panel.D_state.iloc[21] == "COMMON_UP__STOCK_UP",
            "Feature must be D, never E")
    require(panel.D_posture.iloc[5] == "PLAN_BUY" and panel.D_posture.iloc[31] == "PLAN_SELL"
            and panel.D_posture.iloc[32] == "FLAT", "Causal posture differs")
    require(panel.loc[panel.phase.ne("HOLD"), list(COMPONENTS)].isna().all().all(), "Entry received industry attribution")
    require(panel.date.tolist() == dates.tolist(), "Real-type CSV calendar Series failed")
    summary = summaries(panel)
    require(any(r["mode"] == "PAST_ONLY" and r["support"] == "NO_SUPPORT"
                and r["observed_reference_mean_daily_return"] is None for r in summary["cross_year_observed_references"]),
            "Unsupported past references must be null")
    for mutation, message in (("same_day", "Same-day state accepted"), ("target", "Broken target accepted"),
                              ("return", "Unit/return mismatch accepted"), ("atom", "Corrupt original atom accepted"),
                              ("order", "Wrong order side accepted")):
        baddec, badf1, badatom = dec.copy(), f1.copy(), atoms.copy()
        badorders = orders.copy()
        if mutation == "same_day":
            baddec.loc[5, "signal_date"] = dates[5]
        elif mutation == "target":
            baddec.loc[5, "target_position"] = 0
        elif mutation == "return":
            badf1.loc[25, "stock_return"] += .01
        elif mutation == "atom":
            badatom.loc[25, "hold_mark_pnl"] += 1
        else:
            badorders.loc[0, "side"] = "SELL"
        try:
            build_panel(d, baddec, fills, d.copy(), f20, badf1, badatom, calendar_series,
                        enforce_real=False, orders=badorders)
        except ValueError:
            pass
        else:
            raise ValueError(message)
    print(json.dumps({"status": "PASS_SYNTHETIC_ONLY", "real_state_outcome_join": False,
                      "checks": ["six-state zero boundaries", "unknown preserved", "strict prior-session state",
                                 "causal posture including failed-buy reset", "target identity", "four original atoms",
                                 "same-unit HOLD exact three-part decomposition", "non-HOLD components null",
                                 "annual and monthly reconciliation", "past-only no-support null",
                                 "same-day feature rejected", "target mismatch rejected", "stock unit mismatch rejected",
                                 "corrupt formal atom rejected", "CSV calendar Series accepted",
                                 "original order/posture one-to-one identity", "wrong order side rejected"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--synthetic-check", action="store_true")
    args = parser.parse_args()
    if args.synthetic_check:
        require(args.lock is None, "Synthetic check cannot open a real lock")
        synthetic_check()
        return
    require(args.lock is not None, "Public source/design lock is required")
    paths = [OUT / "state_driver_daily_panel.csv", OUT / "state_driver_analysis.json"]
    require(not any(path.exists() for path in paths), "Immutable outputs already exist; do not rerun")
    panel, refs, identity = load_inputs(args.lock)
    result = {"status": "COMPLETE_OBSERVED_ACCOUNT_ATTRIBUTION_ONLY", "source_references": refs,
              "account_identity": identity, "feature_timing": "Strict previous exchange session D; valid_session E; no E data in state",
              "feature_units": "Stock ret20 simple; market/sector ret20 logarithmic; zero signs only define states",
              "six_states": STATES, "D_postures": POSTURES,
              "hold_decomposition": "Observed HOLD only: Qprev*prev ledger close times [market, sector-market, stock-sector] simple returns; accounting identity, not causal beta",
              "reference_policy": "Observed same-state/posture equal-day means in all other years or complete previous years; no model or action value",
              "limitations": ["All history already seen; other-year comparisons are not independent validation",
                              "No filtered account, new trading rule, counterfactual action or predictive alpha",
                              "Entry/exit/fees retain original atoms; no industry attribution outside actual HOLD",
                              "Annual contributions use original year-opening equity; drawdowns are not additive",
                              "UNKNOWN warmup dates remain in full account reconciliation"],
              "resources": {"new_fits": 0, "new_accounts": 0, "new_source_calls": 0, "new_counterfactual_labels": 0},
              "validation": {"daily_reconciliations": len(panel), "original_years": sorted(int(y) for y in panel.year.unique()),
                             "strict_prior_session_decisions": len(panel), "actual_HOLD_decompositions": int(panel.phase.eq("HOLD").sum()),
                             "original_order_posture_reconciliations": int(panel.D_posture.isin(["PLAN_BUY", "PLAN_SELL"]).sum()),
                             "original_ledger_fields_preserved": True, "original_annual_review_reconciled": True,
                             "stock20_simple_external20_log_semantics_checked": True},
              **summaries(panel)}
    panel_bytes = panel.to_csv(index=False, lineterminator="\n").encode("utf-8")
    result["daily_panel_sha256"] = sha256(panel_bytes).hexdigest()
    result_bytes = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    for path, raw in zip(paths, (panel_bytes, result_bytes), strict=True):
        with path.open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"status": result["status"], "rows": len(panel), "panel_sha256": result["daily_panel_sha256"],
                      "result_sha256": sha256(result_bytes).hexdigest()}))


if __name__ == "__main__":
    def blocked(*args, **kwargs):
        raise RuntimeError("Network/source calls prohibited")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    main()
