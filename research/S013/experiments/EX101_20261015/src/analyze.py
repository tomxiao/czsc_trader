"""Offline recomputation from authenticated S013 account evidence; no replay."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import json
import math

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef, ExperimentRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
MANIFEST = ROOT / "research/S013/assets/evidence/EX100_20261013/908193106deb3e0334720fabfdc60b67d1afc37062e6144e821d133bcb1fa97d.json"
OWNERS = ("BASE", "TREND")


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def load(reference):
    ref = EvidenceRef.from_dict(reference)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("Only S013 evidence is in scope")
    return read(ref.resolve(ROOT)), ref


def frame(value):
    # The published dataframe contract is explicit, not inferred from raw lists.
    if not isinstance(value, dict) or "data" not in value:
        raise TypeError("Published dataframe required")
    return pd.DataFrame(value["data"])


def records(data):
    return json.loads(data.to_json(orient="records", date_format="iso", double_precision=15))


def close_enough(actual, expected, label, atol=1e-6):
    if not np.allclose(actual, expected, rtol=0, atol=atol):
        raise AssertionError(label)


def yearly(account, initial_cash):
    result = {}
    anchor = float(initial_cash)
    for year, part in account.groupby(account.date.dt.year, sort=True):
        wealth = np.r_[anchor, part.equity.to_numpy(dtype=float)]
        result[str(int(year))] = dict(sessions=len(part), opening_equity=anchor,
            closing_equity=float(wealth[-1]), net_return=float(wealth[-1] / anchor - 1),
            max_drawdown=float(np.max(1 - wealth / np.maximum.accumulate(wealth))))
        anchor = float(wealth[-1])
    return result


def account_frames(document):
    if document["schema_version"] != 6 or document["source_kind"] != "published_result":
        raise ValueError("Original published schema-6 account required")
    if len(document["runs"]) != 1 or len(document["assessment_evidence"]) != 1:
        raise ValueError("Exactly one FULL coordinate required")
    run = document["runs"][0]
    if document["execution_mode"] != "FULL":
        raise ValueError("FULL account required")
    ledgers = {k: frame(v) for k, v in run["ledgers"].items()}
    for key, column in (("account_daily", "date"), ("decisions", "valid_session"),
                        ("fills", "fill_time"), ("orders", "execution_date")):
        ledgers[key]["date"] = pd.to_datetime(ledgers[key][column]).dt.normalize()
    ledgers["trades"]["entry_date"] = pd.to_datetime(ledgers["trades"].entry_date).dt.normalize()
    ledgers["trades"]["exit_date"] = pd.to_datetime(ledgers["trades"].exit_date).dt.normalize()
    bh = frame(run["buyhold"]["execution"]["account_daily"])
    bh["date"] = pd.to_datetime(bh.date).dt.normalize()
    account = ledgers["account_daily"]
    if (len(account), account.date.iloc[0], account.date.iloc[-1]) != (
            1636, pd.Timestamp("2020-01-02"), pd.Timestamp("2026-09-30")):
        raise ValueError("Original 1636-session development pool required")
    if account.date.duplicated().any() or not account.date.is_monotonic_increasing:
        raise ValueError("Account sessions must be strictly increasing")
    if not account.date.equals(bh.date) or not account.date.equals(ledgers["decisions"].date):
        raise ValueError("Strategy, decision and benchmark axes differ")
    initial = float(document["request_identity"]["initial_cash"])
    assessment = document["assessment_evidence"][0]
    if initial != 1_000_000 or assessment["opening_quantity"] != 0:
        raise ValueError("Original cash/zero-opening-position contract required")
    assessed = pd.DataFrame(assessment["account"])
    if not pd.to_datetime(assessed.session).astype('datetime64[ns]').equals(account.date):
        raise AssertionError("Assessment and raw ledger dates differ")
    for key in ("equity", "cash", "quantity", "close"):
        close_enough(assessed[key], account[key], "Assessment/raw " + key)
    close_enough(assessment["benchmark_equity"], bh.equity, "Benchmark evidence")
    assessed_fills = pd.DataFrame(assessment["fills"])
    raw_fills = ledgers["fills"]
    if len(assessed_fills) != len(raw_fills):
        raise AssertionError("Assessment/raw fill count")
    if not pd.to_datetime(assessed_fills.session).astype('datetime64[ns]').equals(raw_fills.date):
        raise AssertionError("Assessment/raw fill sessions")
    for key in ("cycle_id", "side"):
        if not assessed_fills[key].equals(raw_fills[key]):
            raise AssertionError("Assessment/raw fill " + key)
    for key in ("price", "quantity", "fees"):
        close_enough(assessed_fills[key], raw_fills[key], "Assessment/raw fill " + key)
    assessed_closed = {r["cycle_id"] for r in assessment["closed_cycles"]}
    raw_closed = set(ledgers["trades"].loc[ledgers["trades"].status.eq("CLOSED"), "cycle_id"])
    if assessed_closed != raw_closed:
        raise AssertionError("Assessment/raw closed cycles")
    return ledgers, bh, initial


def inspect(label, document, anomaly_dates):
    ledgers, bh, initial = account_frames(document)
    account, fills, trades, decisions = (ledgers[k] for k in (
        "account_daily", "fills", "trades", "decisions"))
    if decisions.decision_id.duplicated().any():
        raise ValueError("Decision identity must be unique")
    by_id = decisions.set_index("decision_id")
    cycle_owner = {}
    cycles = []
    daily_rows = []
    balances = defaultdict(int)
    cash = initial
    prior_close = 0.0
    fill_groups = {d: p for d, p in fills.groupby("date", sort=False)}
    for cycle_id, group in fills.groupby("cycle_id", sort=False):
        buys = group.loc[group.side.eq("BUY")]
        sells = group.loc[group.side.eq("SELL")]
        if buys.empty:
            raise AssertionError("Cycle with no actual buy")
        first = buys.iloc[0]
        owner = "BASE" if label == "BASE" else str(by_id.loc[first.decision_id, "signal_owner"])
        if owner not in OWNERS:
            raise AssertionError("Actual BUY must have a nonempty signal owner")
        cycle_owner[cycle_id] = owner
        trade = trades.loc[trades.cycle_id.eq(cycle_id)]
        if len(trade) != 1:
            raise AssertionError("Exactly one recorded trade per actual cycle")
        trade = trade.iloc[0]
        buy_qty, sell_qty = int(buys.quantity.sum()), int(sells.quantity.sum())
        is_closed = trade.status == "CLOSED"
        if is_closed != (buy_qty == sell_qty) or sell_qty > buy_qty:
            raise AssertionError("Trade status and fill quantities disagree")
        cost = float((buys.quantity * buys.price + buys.fees).sum())
        proceeds = float((sells.quantity * sells.price - sells.fees).sum())
        remaining = buy_qty - sell_qty
        terminal_mark = remaining * float(account.close.iloc[-1])
        net_pnl = proceeds + terminal_mark - cost
        row = dict(configuration=label, cycle_id=cycle_id, owner=owner,
            entry_date=first.date, entry_signal_date=pd.Timestamp(first.signal_date).normalize(),
            exit_date=None if not is_closed else sells.date.iloc[-1], status=str(trade.status),
            buy_quantity=buy_qty, sell_quantity=sell_qty, remaining_quantity=remaining,
            entry_cost=cost, net_pnl=net_pnl, cycle_net_return=net_pnl / cost,
            total_fees=float(group.fees.sum()), entry_fill_trigger=str(first.trigger))
        if is_closed:
            close_enough(float(trade.net_return), net_pnl / cost, "Cycle net return", 1e-10)
        cycles.append(row)
    if set(trades.cycle_id) != set(cycle_owner):
        raise AssertionError("Trades and actual fill cycles differ")
    for day in account.itertuples():
        pnl = {owner: 0.0 for owner in OWNERS}
        fees = {owner: 0.0 for owner in OWNERS}
        for cycle_id, quantity in balances.items():
            pnl[cycle_owner[cycle_id]] += quantity * (day.close - prior_close)
        if day.date in fill_groups:
            for fill in fill_groups[day.date].itertuples():
                if fill.side not in ("BUY", "SELL") or fill.quantity <= 0 or fill.quantity % 100:
                    raise AssertionError("Invalid fill quantity/side")
                sign = 1 if fill.side == "BUY" else -1
                owner = cycle_owner[fill.cycle_id]
                close_enough(fill.fees, fill.price * fill.quantity * .001, "Fixed fee")
                cash += -sign * fill.price * fill.quantity - fill.fees
                pnl[owner] += sign * fill.quantity * (day.close - fill.price) - fill.fees
                fees[owner] += fill.fees
                balances[fill.cycle_id] += sign * int(fill.quantity)
                if balances[fill.cycle_id] < 0:
                    raise AssertionError("Sold more than actual cycle position")
        nonzero = [c for c, q in balances.items() if q]
        if len(nonzero) > 1 or sum(balances.values()) != day.quantity:
            raise AssertionError("Single actual position reconciliation")
        close_enough(cash, day.cash, "Actual cash reconciliation")
        close_enough(cash + day.quantity * day.close, day.equity, "Actual mark reconciliation")
        previous_equity = initial if not daily_rows else daily_rows[-1]["equity"]
        close_enough(sum(pnl.values()), day.equity - previous_equity, "Owner daily PnL")
        position_owner = cycle_owner[nonzero[0]] if nonzero else "EMPTY"
        daily_rows.append(dict(configuration=label, date=day.date, equity=float(day.equity),
            quantity=int(day.quantity), actual_position_owner=position_owner,
            base_net_pnl=pnl["BASE"], trend_net_pnl=pnl["TREND"],
            base_fees=fees["BASE"], trend_fees=fees["TREND"]))
        prior_close = day.close
    cycle_frame = pd.DataFrame(cycles, columns=("configuration", "cycle_id", "owner", "entry_date",
        "entry_signal_date", "exit_date", "status", "buy_quantity", "sell_quantity", "remaining_quantity",
        "entry_cost", "net_pnl", "cycle_net_return", "total_fees", "entry_fill_trigger"))
    cycle_frame["entry_date"] = pd.to_datetime(cycle_frame.entry_date)
    cycle_frame["exit_date"] = pd.to_datetime(cycle_frame.exit_date)
    daily = pd.DataFrame(daily_rows)
    close_enough(cycle_frame.net_pnl.sum(), account.equity.iloc[-1] - initial, "Cycle/account total")
    annual, benchmark_annual = yearly(account, initial), yearly(bh, initial)
    positive = [y for y in annual if benchmark_annual[y]["net_return"] > 0]
    negative = [y for y in annual if benchmark_annual[y]["net_return"] < 0]
    positive_sessions = sum(annual[y]["sessions"] for y in positive)
    closed = cycle_frame.loc[cycle_frame.status.eq("CLOSED")]
    profitable_year_closed = int(closed.exit_date.dt.year.astype(str).isin(positive).sum())
    cagr = float((account.equity.iloc[-1] / initial) ** (252 / len(account)) - 1)
    bcagr = float((bh.equity.iloc[-1] / initial) ** (252 / len(bh)) - 1)
    gates = dict(return_target=cagr >= 1.5 * bcagr if bcagr > 0 else cagr > 0,
        annual_drawdown=all(annual[y]["max_drawdown"] < benchmark_annual[y]["max_drawdown"] for y in annual),
        positive_buyhold_year_frequency=profitable_year_closed * 60 >= 4 * positive_sessions,
        negative_buyhold_year_profit=all(annual[y]["net_return"] > 0 for y in negative))
    close_enough(cagr, document["runs"][0]["observation"]["net_cagr"], "Published CAGR", 1e-12)
    if positive_sessions != 1152 or math.ceil(4 * positive_sessions / 60) != 77:
        raise AssertionError("Fixed benchmark positive-year denominator changed")
    owner_rows = []
    for owner in OWNERS:
        sub = cycle_frame.loc[cycle_frame.owner.eq(owner)]
        owner_rows.append(dict(owner=owner, actual_cycles=len(sub),
            closed_cycles=int(sub.status.eq("CLOSED").sum()),
            terminal_open_cycles=int(sub.status.ne("CLOSED").sum()),
            closed_cycle_net_pnl=float(sub.loc[sub.status.eq("CLOSED"), "net_pnl"].sum()),
            terminal_open_marked_net_pnl=float(sub.loc[sub.status.ne("CLOSED"), "net_pnl"].sum()),
            total_net_pnl=float(daily[owner.lower() + "_net_pnl"].sum()),
            fees=float(sub.total_fees.sum()), close_position_sessions=int(daily.actual_position_owner.eq(owner).sum())))
    for y in annual:
        part = daily.loc[daily.date.dt.year.eq(int(y))]
        annual[y]["closed_cycles"] = int(closed.exit_date.dt.year.eq(int(y)).sum())
        annual[y]["owner_pnl"] = {o: float(part[o.lower() + "_net_pnl"].sum()) for o in OWNERS}
        annual[y]["owner_return_contribution"] = {
            o: annual[y]["owner_pnl"][o] / annual[y]["opening_equity"] for o in OWNERS}
    orders = ledgers["orders"]
    replay = document["runs"][0]["replay_evidence"]
    anomalies = []
    for date in anomaly_dates:
        event_day = pd.Timestamp(date)
        day_orders = orders.loc[orders.date.eq(event_day)]
        day_fills = fills.loc[fills.date.eq(event_day)]
        daily_prices = [r for r in replay["execution_daily"] if r["date"].startswith(date)]
        bars = [r for r in replay["execution_intraday"] if r["time"].startswith(date)]
        if len(daily_prices) != 1 or len(bars) != 8:
            raise AssertionError("Known anomaly session must retain its original daily/eight bars")
        minute_low = min(float(bar["low"]) for bar in bars)
        limit_checks = []
        for order in day_orders.loc[day_orders.side.eq("BUY") & day_orders.order_type.eq("LIMIT")].itertuples():
            actual_fills = day_fills.loc[day_fills.order_id.eq(order.order_id)]
            touches = [bar for bar in bars if float(bar["low"]) <= float(order.limit_price)]
            intraday_fills = actual_fills.loc[actual_fills.trigger.eq("INTRADAY_LIMIT")]
            limit_checks.append(dict(order_id=order.order_id, status=order.status,
                limit_price=float(order.limit_price), actual_fills=records(actual_fills),
                intraday_limit_fill_count=len(intraday_fills),
                first_recorded_bar_low_touch=None if not touches else touches[0],
                daily_low=float(daily_prices[0]["low"]), minimum_30m_low=minute_low,
                daily_low_reaches_limit=bool(float(daily_prices[0]["low"]) <= order.limit_price),
                minute_low_reaches_limit=bool(minute_low <= order.limit_price),
                interpretation=("Actual intraday first-touch BUY uses bars from a known anomalous session; source flags the session, not a particular corrected bar, so causal dependence on the bad observation cannot be proved without independent source evidence."
                    if len(intraday_fills) else "No actual INTRADAY_LIMIT BUY on this order; retain OPEN/unfilled status and daily-versus-minute touch facts without a counterfactual replay.")))
        anomalies.append(dict(date=date, decisions=records(decisions.loc[decisions.date.eq(event_day)]),
            orders=records(day_orders), fills=records(day_fills),
            actual_owner_pnl=records(daily.loc[daily.date.eq(event_day)]),
            execution_daily=daily_prices, execution_intraday=bars, limit_buy_touch_checks=limit_checks))
    wealth = np.r_[initial, account.equity.to_numpy(dtype=float)]
    summary = dict(configuration=label, net_cagr=cagr, benchmark_net_cagr=bcagr,
        max_drawdown=float(np.max(1 - wealth / np.maximum.accumulate(wealth))),
        closed_cycles=len(closed), positive_benchmark_years=positive, negative_benchmark_years=negative,
        positive_benchmark_year_sessions=positive_sessions, positive_year_closed_cycles=profitable_year_closed,
        positive_year_required_closed_cycles=77, positive_year_frequency60=profitable_year_closed * 60 / positive_sessions,
        annual=annual, benchmark_annual=benchmark_annual, gates=gates, four_targets_jointly_pass=all(gates.values()),
        fees=float(fills.fees.sum()), terminal_quantity=int(account.quantity.iloc[-1]),
        terminal_open_cycles=int(cycle_frame.status.ne("CLOSED").sum()),
        order_status_counts={str(k): int(v) for k, v in orders.status.value_counts().items()},
        unfilled_orders=records(orders.loc[orders.status.eq("UNFILLED")]), owners=owner_rows,
        known_anomalous_30m_sessions=anomalies, audits=dict(actual_fill_cash_quantity_equity="PASS", owner_daily_pnl="PASS",
            closed_cycle_returns="PASS", cycle_total_to_terminal_equity="PASS", assessment_ledger_alignment="PASS"))
    return summary, cycle_frame, daily, ledgers, bh


def pair(base, combined):
    _, old_cycles, _, old_ledgers, _ = base
    _, new_cycles, new_daily, new_ledgers, _ = combined
    old = old_cycles.loc[old_cycles.status.eq("CLOSED")]
    new = new_cycles.loc[new_cycles.status.eq("CLOSED")]
    keys = set(zip(new.entry_date, new.exit_date, new.owner))
    same = old.apply(lambda r: (r.entry_date, r.exit_date, "BASE") in keys, axis=1)
    new_entries = set(new_cycles.loc[new_cycles.owner.eq("BASE"), "entry_date"])
    absent = old_cycles.loc[~old_cycles.entry_date.isin(new_entries)]
    exposure = new_daily.set_index("date").actual_position_owner
    occupied = absent.entry_date.map(exposure).eq("TREND")
    original_decisions = old_ledgers["decisions"].set_index("date")
    combo_decisions = new_ledgers["decisions"].set_index("date")
    before = combo_decisions.prior_owner
    base_entry = original_decisions.signal_reason.eq("entry")
    if not original_decisions.signal_reason.equals(combo_decisions.base_signal_reason):
        raise AssertionError("Combined original BASE shadow changed")
    if not original_decisions.target_position.equals(combo_decisions.base_target_position):
        close_enough(original_decisions.target_position, combo_decisions.base_target_position, "Original BASE shadow target", 0)
    expected_blocked = base_entry & before.ne("EMPTY")
    if not np.array_equal(expected_blocked, combo_decisions.blocked_base_entry):
        raise AssertionError("Published blocked BASE entry diagnostic differs from original shadow")
    blocked = base_entry & before.eq("TREND")
    return dict(same_base_closed_entry_exit_pairs=int(same.sum()),
        removed_or_retimed_old_closed_cycles=records(old.loc[~same]),
        original_actual_entry_dates_absent_in_combo_base=len(absent),
        absent_original_entry_dates_with_actual_trend_position=int(occupied.sum()),
        absent_original_entry_cycles=records(absent),
        original_base_entry_signal_days_blocked_by_trend_signal_owner=int(blocked.sum()),
        blocked_base_signal_days=[d.date().isoformat() for d in blocked.index[blocked]],
        caveat="Matched dates compare routes only; quantities/cash differ. Removed BASE PnL is descriptive, not recoverable or additive counterfactual profit.")


def main():
    experiment = ExperimentRef.from_dict(read(Path(__file__).resolve().parents[1] / "experiment.json"))
    if experiment.strategy_id != "S013":
        raise ValueError("S013 only")
    manifest_bytes = MANIFEST.read_bytes()
    if sha256(manifest_bytes).hexdigest() != MANIFEST.stem:
        raise AssertionError("Original diagnostic manifest hash")
    manifest = json.loads(manifest_bytes)
    original_quality_refs = read(ROOT / "research/S013/experiments/EX099_20261013/protocols/result_references.json")
    quality, quality_ref = load(original_quality_refs["ledger_verification.json"])
    anomaly_dates = quality["known_anomalous_30m_dates"]
    if quality["status"] != "PASS" or len(anomaly_dates) != 5 or len(set(anomaly_dates)) != 5:
        raise AssertionError("Authenticated original five-session quality diagnostic required")
    sources = {"BASE": manifest["original_account_refs"]["C2132"]}
    new_sources = read(experiment.resolve(ROOT) / "protocols/account_references.json")
    if set(new_sources) != {"TREND_ONLY", "COMBINED"}:
        raise ValueError("Exactly two fixed new account references required")
    sources.update(new_sources)
    results, verified, documents = {}, {}, {}
    for label, source in sources.items():
        document, ref = load(source)
        results[label] = inspect(label, document, anomaly_dates)
        verified[label] = ref.to_dict()
        documents[label] = document
    benchmark = results["BASE"][4]
    for label, result in results.items():
        pd.testing.assert_frame_equal(benchmark, result[4], check_exact=True)
        for key in ("symbol", "asset_type", "windows", "data_cutoff", "initial_cash", "costs", "benchmark", "price_basis", "pricing"):
            if documents[label]["request_identity"][key] != documents["BASE"]["request_identity"][key]:
                raise AssertionError("Shared execution contract differs: " + key)
    comparisons = []
    for label in ("TREND_ONLY", "COMBINED"):
        a, b = results["BASE"][0], results[label][0]
        comparisons.append(dict(comparison=label + " minus BASE", net_cagr_difference=b["net_cagr"]-a["net_cagr"],
            max_drawdown_difference=b["max_drawdown"]-a["max_drawdown"],
            positive_year_closed_cycle_difference=b["positive_year_closed_cycles"]-a["positive_year_closed_cycles"],
            fees_difference=b["fees"]-a["fees"], annual_return_differences={
                y: b["annual"][y]["net_return"]-a["annual"][y]["net_return"] for y in a["annual"]}))
    report = dict(kind="FIXED_TREND_COMPARISON_AUTHENTICATED_LEDGER_RECOMPUTATION", status="PASS",
        experiment=experiment.to_dict(), sources=verified, rows=[r[0] for r in results.values()],
        original_anomaly_source=quality_ref.to_dict(), known_anomalous_30m_dates=anomaly_dates,
        anomaly_policy="Original inputs unchanged; no repair, sample removal or counterfactual account rerun. Session-level source quality flags do not identify individual corrected bars.",
        comparisons=comparisons, capital_occupation=pair(results["BASE"], results["COMBINED"]),
        counts=dict(authenticated_account_documents=3, reused_original_accounts=1, new_business_accounts=2,
            analyzer_strategy_executions=0, analyzer_provider_calls=0, analyzer_model_fits=0,
            analyzer_new_full_evaluations=0),
        limitations=["Previously seen development pool; rules selected after historical diagnosis, not independent out-of-sample evidence.",
            "Annual benchmark profitability is used only for ex-post acceptance, never for strategy decisions.",
            "Signal ownership is not actual holdings. Owner PnL is assigned from actual fill cycles and reconciled to the single cash account.",
            "Original five anomalous 30m sessions remain unchanged. Actual order/fill exposure and recorded-bar first low touches are diagnostics, not a repaired result or proof that an erroneous bar caused the fill.",
            "Passing the two fixed centers does not establish standard32 robustness, fee-stress qualification, final candidate eligibility or production readiness."])
    out = ROOT / "research/S013/assets/runs" / experiment.experiment_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    annual_rows = []
    for label, result in results.items():
        result[1].to_csv(out / (label.lower() + "_cycles.csv"), index=False, lineterminator="\n")
        result[2].to_csv(out / (label.lower() + "_owner_daily.csv"), index=False, lineterminator="\n")
        for year, row in result[0]["annual"].items():
            annual_rows.append(dict(configuration=label, year=year, **{k: v for k, v in row.items() if not isinstance(v, dict)}))
    pd.DataFrame(annual_rows).to_csv(out / "annual_comparison.csv", index=False, lineterminator="\n")
    pd.DataFrame([{k: v for k, v in r[0].items() if isinstance(v, (str, int, float, bool))}
                  for r in results.values()]).to_csv(out / "comparison.csv", index=False, lineterminator="\n")
    print(json.dumps(dict(status="PASS", analysis=out.relative_to(ROOT).as_posix() + "/analysis.json",
        rows=[{k: r[0][k] for k in ("configuration", "net_cagr", "max_drawdown", "positive_year_closed_cycles", "gates")}
              for r in results.values()]), ensure_ascii=False))


if __name__ == "__main__":
    main()
