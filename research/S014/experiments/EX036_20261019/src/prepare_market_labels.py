"""Offline fixed event labels, public DFLS fetch and SRT/TXE DailyRangeV3 fills."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
from pathlib import Path
import socket
from uuid import UUID

import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from strategy_runtime.execution_rules import ExecutionRuleInput, build_frozen_execution_plan
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"
FINANCIAL = ROOT / "research/S014/materials/20261019_financial_readiness/others/accepted_financial_inputs.json"
SETTINGS = {
    "instrument": {"lot_size": 100, "price_tick": 0.01, "price_limit_ratio": 0.1, "maximum_order_quantity": 100000},
    "capital": {"mode": "ALL_AVAILABLE", "target_scope": "SINGLE_SYMBOL", "fee_rate": 0.001},
    "entry": {"order_type": "LIMIT", "limit_parameter": 0.01},
    "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")


def blocked(*_args, **_kwargs):
    raise RuntimeError("EX036 strictly offline: network blocked")


def synthetic_precheck():
    day = date(2024, 1, 2)
    time = datetime(2024, 1, 2, 9, 30)
    limits = SessionPriceLimits(day, 9.0, 11.0, 0.01)
    def resolve(order, opening, low, high):
        return resolve_fill(order, session_open=opening, session_time=time, intraday_touches=(), session_limits=limits, daily_quote=DailyQuote(low, high))
    checks = []
    for name, decision, expected in [
        ("equal_daily_limit_touch_fills", resolve(OrderSpec("BUY", "LIMIT", 100, 10.0), 10.1, 10.0, 10.2), True),
        ("missed_entry_no_trade", resolve(OrderSpec("BUY", "LIMIT", 100, 10.0), 10.1, 10.01, 10.2), False),
        ("locked_down_sell_pending", resolve(OrderSpec("SELL", "MARKET", 100), 9.0, 9.0, 9.0), False),
        ("down_limit_reopened_sell_plus_tick", resolve(OrderSpec("SELL", "MARKET", 100), 9.0, 9.0, 9.01), True),
        ("outside_limit_price_rejected", resolve(OrderSpec("BUY", "LIMIT", 100, 11.01), 10.0, 9.9, 10.1), False),
    ]:
        assert decision.filled is expected, name
        if name == "down_limit_reopened_sell_plus_tick":
            assert abs(decision.price - 9.01) < 1e-10
        checks.append({"name": name, "PASS": True, "fill": asdict(decision)})
    plan = build_frozen_execution_plan(ExecutionRuleInput("FROZEN_RULE", SETTINGS, {}, 100000, 0, 1.0, 10.0, 10.0))
    order = plan["orders"][0]
    assert order["limit_price"] == 10.10 and order["quantity"] == 9800 and order["time_in_force"] == "DAY"
    assert order["quantity"] * order["limit_price"] * 1.001 <= 100000
    checks.append({"name": "one_percent_tick_lot_fee_budget", "PASS": True, "order": order})
    return checks


def fetch_inputs():
    socket.socket.connect = blocked
    socket.create_connection = blocked
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"), providers=ProviderConfig(bindings={}))
    ex033_path = ROOT / "research/S014/experiments/EX033_20261018/others/inputs.json"
    # Only native identity metadata is consumed; old labels/events are never read into calculations.
    native = json.loads(ex033_path.read_text(encoding="utf-8"))["native_identities"]
    ex002_path = ROOT / "research/S014/experiments/EX002_20261016/others/input_readiness_fixed_1.json"
    records = json.loads(ex002_path.read_text(encoding="utf-8"))["records"]
    needed = {"stock.unadjusted_daily", "security.price_limits", "security.trading_status", "calendar.trading_sessions"}
    selected = [("stock_hfq", native[0]), ("market", next(r for r in native if r["symbol"] == "000001.SH")), ("sector", next(r for r in native if r["symbol"] == "000813.CSI"))]
    names = {"stock.unadjusted_daily": "stock_raw", "security.price_limits": "limits", "security.trading_status": "status", "calendar.trading_sessions": "calendar"}
    for record in records:
        if record["request"]["dataset"] in needed:
            selected.append((names[record["request"]["dataset"]], dict(record, **record["request"])))
    frames, identity = {}, []
    for name, record in selected:
        ref = record["reference"]
        prepared = PreparedDataRef(UUID(ref["space_id"]), UUID(ref["preparation_id"]), ref["manifest_sha256"])
        request = DataRequest(Dataset(record["dataset"]), record["symbol"], record["start"], "2026-10-15", "2026-10-15")
        result = ctx.data.fetch(request, prepared=prepared)
        assert result.ready and result.identity.content_sha256 == record["content_sha256"], name
        frame = result.dataframe.copy().sort_values("Date").reset_index(drop=True)
        frame["Date"] = pd.to_datetime(frame.Date).dt.strftime("%Y-%m-%d")
        assert not frame.Date.duplicated().any(), name
        path = OUT / f"{name}_market.csv"
        if path.exists():
            raise RuntimeError("Preserve immutable market snapshot")
        frame.to_csv(path, index=False, lineterminator="\n")
        frames[name] = frame.set_index("Date", drop=False)
        identity.append({"name": name, "request": {"dataset": record["dataset"], "symbol": record["symbol"], "start": record["start"], "end": "2026-10-15", "required_cutoff": "2026-10-15"}, "prepared": ref, "content_sha256": result.identity.content_sha256, "rows": len(frame), "snapshot_path": path.relative_to(ROOT).as_posix(), "snapshot_sha256": digest(path)})
    return frames, identity


def main():
    publication = EX / "protocols/published_design.json"
    if not publication.exists():
        raise RuntimeError("Design must be formally published before outcomes are generated")
    design = json.loads((EX / "protocols/design.json").read_text(encoding="utf-8"))
    assert design["identity"] == "EX036_20261019" and design["horizon"]["sessions"] == 20
    for filename in ("market_inputs.json", "market_event_labels.csv", "market_label_checks.json"):
        if (OUT / filename).exists():
            raise RuntimeError(f"Preserve existing {filename}")
    OUT.mkdir(parents=True, exist_ok=True)
    precheck = synthetic_precheck()
    frames, identities = fetch_inputs()
    raw, hfq, market, sector, limits, statuses, calendar = (frames[name] for name in ("stock_raw", "stock_hfq", "market", "sector", "limits", "status", "calendar"))
    sessions = calendar.loc[calendar.IsOpen.eq(1), "Date"].tolist()
    assert len(sessions) == 1642
    for name in ("stock_raw", "market", "sector", "limits", "status"):
        assert frames[name].index.tolist() == sessions, name
    hfq_aligned = hfq.loc[sessions]
    factors = hfq_aligned.Close / raw.Close
    assert np.isfinite(factors).all() and (factors > 0).all()
    for col in ("Open", "High", "Low", "Close"):
        np.testing.assert_allclose(hfq_aligned[col], raw[col] * factors, rtol=1e-10, atol=1e-8)
    accepted = json.loads(FINANCIAL.read_text(encoding="utf-8"))
    period_dates = defaultdict(set)
    for fact in accepted["facts"]:
        if fact["period"] >= "20191231":
            period_dates[fact["period"]].add(fact["decision_available_at"])
    assert len(period_dates) == 27 and all(len(v) == 1 for v in period_dates.values())
    clusters = defaultdict(list)
    for period, dates in period_dates.items():
        clusters[next(iter(dates))[:10]].append(period)
    assert len(clusters) == 25
    labels = []

    def one_fill(order, session):
        if statuses.loc[session, "Status"] != "TRADING":
            return None
        row = raw.loc[session]
        boundary = limits.loc[session]
        return resolve_fill(order, session_open=float(row.Open), session_time=datetime.fromisoformat(session + "T09:30:00"), intraday_touches=(), daily_quote=DailyQuote(float(row.Low), float(row.High)), session_limits=SessionPriceLimits(date.fromisoformat(session), float(boundary.DownLimit), float(boundary.UpLimit), 0.01))

    for decision_date, periods in sorted(clusters.items()):
        decision_i = sessions.index(decision_date)
        entry_i = decision_i + 1
        label_i = entry_i + 19
        planned_exit_i = entry_i + 20
        event = {"event_id": "FIN_" + decision_date.replace("-", ""), "decision_date": decision_date, "decision_at": decision_date + "T15:00:00", "report_period": max(periods), "report_periods": "|".join(sorted(periods)), "decision_index": decision_i, "entry_index": entry_i, "price_endpoint_index": label_i, "planned_exit_index": planned_exit_i, "entry_date": sessions[entry_i] if entry_i < len(sessions) else None, "price_endpoint_date": sessions[label_i] if label_i < len(sessions) else None, "planned_exit_date": sessions[planned_exit_i] if planned_exit_i < len(sessions) else None, "price_status": "COMPLETE" if label_i < len(sessions) else "RIGHT_CENSORED", "control_status": "COMPLETE" if decision_i >= 20 else "INSUFFICIENT_PAST", "execution_status": "NOT_ENTERED", "endpoint_known_by_cutoff": label_i < len(sessions)}
        for name, frame in (("stock", hfq), ("market", market), ("sector", sector)):
            event[name + "_trailing20"] = float(frame.loc[decision_date, "Close"] / frame.loc[sessions[decision_i - 20], "Close"] - 1) if decision_i >= 20 else None
            event[name + "_return20"] = None
            if label_i < len(sessions):
                event[name + "_return20"] = float(frame.loc[sessions[label_i], "Close"] / frame.loc[sessions[entry_i], "Open"] - 1)
        event["sector_excess_return20"] = event["stock_return20"] - event["sector_return20"] if event["price_status"] == "COMPLETE" else None
        event["market_excess_return20"] = event["stock_return20"] - event["market_return20"] if event["price_status"] == "COMPLETE" else None
        event["mae20"] = float(hfq.loc[sessions[entry_i:label_i + 1], "Low"].min() / hfq.loc[sessions[entry_i], "Open"] - 1) if label_i < len(sessions) else None
        event["mae_low_date"] = hfq.loc[sessions[entry_i:label_i + 1], "Low"].idxmin() if label_i < len(sessions) else None
        event["initial_cash"] = 100000.0
        event["fee_rate"] = 0.001
        event["sell_attempts"] = "[]"
        if entry_i >= len(sessions):
            event["execution_status"] = "RIGHT_CENSORED_NO_ENTRY_SESSION"
            labels.append(event)
            continue
        entry_date = sessions[entry_i]
        reference = float(raw.loc[decision_date, "Close"])
        plan = build_frozen_execution_plan(ExecutionRuleInput("FROZEN_RULE", SETTINGS, {}, 100000.0, 0, 1.0, reference, reference))
        assert len(plan["orders"]) == 1
        order = plan["orders"][0]
        buy = one_fill(OrderSpec(order["side"], order["order_type"], order["quantity"], order["limit_price"]), entry_date)
        event.update(reference_raw_close=reference, buy_limit_raw=order["limit_price"], order_quantity=order["quantity"], buy_day_raw_open=float(raw.loc[entry_date, "Open"]), buy_day_raw_low=float(raw.loc[entry_date, "Low"]), buy_day_raw_high=float(raw.loc[entry_date, "High"]), entry_factor=float(factors.loc[entry_date]), buy_day_down_limit=float(limits.loc[entry_date, "DownLimit"]), buy_day_up_limit=float(limits.loc[entry_date, "UpLimit"]), buy_fill_trigger=buy.trigger if buy else None, buy_fill_reason=buy.reason if buy else "SUSPENDED", buy_fill_precision=str(buy.time_precision) if buy else None)
        if buy is None or not buy.filled:
            event.update(execution_status="NO_TRADE", actual_quantity=0, buy_fee_raw=0.0, cash_leftover_raw=100000.0, net_position_return=None, event_cash_equity_return=0.0, actual_exit_date=None, execution_endpoint_date=event["planned_exit_date"])
            labels.append(event)
            continue
        quantity = int(order["quantity"])
        buy_notional = quantity * buy.price
        buy_fee = buy_notional * 0.001
        leftover = 100000.0 - buy_notional - buy_fee
        assert leftover >= -1e-8
        event.update(execution_status="OPEN_PENDING", actual_quantity=quantity, actual_buy_date=entry_date, buy_price_raw=buy.price, buy_price_hfq=buy.price * factors.loc[entry_date], buy_fee_raw=buy_fee, buy_notional_raw=buy_notional, cash_leftover_raw=leftover, research_hfq_quantity=quantity / factors.loc[entry_date], actual_exit_date=None, net_position_return=None, event_cash_equity_return=None, exit_delay_sessions=None)
        attempts = []
        sold = False
        for exit_i in range(planned_exit_i, len(sessions)):
            exit_date = sessions[exit_i]
            sell_ref = float(raw.loc[sessions[exit_i - 1], "Close"])
            sell_plan = build_frozen_execution_plan(ExecutionRuleInput("FROZEN_RULE", SETTINGS, {}, leftover, quantity, 0.0, sell_ref, sell_ref))
            sell_order = sell_plan["orders"][0]
            sell = one_fill(OrderSpec(sell_order["side"], sell_order["order_type"], sell_order["quantity"], sell_order["limit_price"]), exit_date)
            attempts.append({"date": exit_date, "status": "SUSPENDED" if sell is None else sell.reason, "filled": bool(sell and sell.filled), "price": sell.price if sell else None, "trigger": sell.trigger if sell else None, "precision": str(sell.time_precision) if sell else None})
            if sell and sell.filled:
                factor_ratio = float(factors.loc[exit_date] / factors.loc[entry_date])
                adjusted_gross_sale = quantity * sell.price * factor_ratio
                adjusted_sell_fee = adjusted_gross_sale * 0.001
                net_sale = adjusted_gross_sale - adjusted_sell_fee
                net_return = net_sale / (buy_notional + buy_fee) - 1
                event.update(execution_status="CLOSED", actual_exit_date=exit_date, actual_exit_index=exit_i, execution_endpoint_date=exit_date, exit_delay_sessions=exit_i - planned_exit_i, exit_price_raw=sell.price, exit_price_hfq=sell.price * factors.loc[exit_date], exit_factor=float(factors.loc[exit_date]), factor_ratio_exit_entry=factor_ratio, sell_day_raw_open=float(raw.loc[exit_date, "Open"]), sell_day_raw_high=float(raw.loc[exit_date, "High"]), sell_day_raw_low=float(raw.loc[exit_date, "Low"]), sell_day_down_limit=float(limits.loc[exit_date, "DownLimit"]), sell_day_up_limit=float(limits.loc[exit_date, "UpLimit"]), sell_fill_trigger=sell.trigger, sell_fill_precision=str(sell.time_precision), sell_fee_raw=quantity * sell.price * 0.001, sell_fee_hfq_research_adjusted=adjusted_sell_fee, net_position_return=net_return, event_cash_equity_return=(leftover + net_sale) / 100000 - 1, research_end_equity=leftover + net_sale)
                sold = True
                break
        if not sold:
            last = sessions[-1]
            mark = quantity * float(raw.loc[last, "Close"]) * float(factors.loc[last] / factors.loc[entry_date])
            event.update(execution_endpoint_date=last, right_censor_date=last, right_censor_mark_equity=leftover + mark)
        event["sell_attempts"] = json.dumps(attempts, ensure_ascii=False)
        labels.append(event)

    frame = pd.DataFrame(labels)
    frame = frame.rename(columns={"price_status": "price_label_status"})
    frame["dependency_endpoint_date"] = frame[["price_endpoint_date", "planned_exit_date", "actual_exit_date", "execution_endpoint_date"]].apply(lambda row: max(str(x) for x in row if pd.notna(x)), axis=1)
    assert len(frame) == 25 and frame.event_id.nunique() == 25
    target = OUT / "market_event_labels.csv"
    frame.to_csv(target, index=False, lineterminator="\n")
    samples = []
    for index in (0, 5, 10, 15, 24):
        row = frame.iloc[index]
        recomputed_return = float(Decimal(str(hfq.loc[row.price_endpoint_date, "Close"])) / Decimal(str(hfq.loc[row.entry_date, "Open"])) - 1)
        assert abs(recomputed_return - row.stock_return20) < 1e-12
        independent_limit = float((Decimal(str(raw.loc[row.decision_date, "Close"])) * Decimal("1.01") / Decimal("0.01")).to_integral_value(rounding=ROUND_FLOOR) * Decimal("0.01"))
        assert abs(independent_limit - row.buy_limit_raw) < 1e-10
        sample = {"event_id": row.event_id, "stock_return20_independent_decimal": recomputed_return, "buy_limit_independent_decimal": independent_limit, "status": row.execution_status, "PASS": True}
        if row.execution_status == "CLOSED":
            independent_net = float(Decimal(str(row.exit_price_hfq)) * Decimal("0.999") / (Decimal(str(row.buy_price_hfq)) * Decimal("1.001")) - 1)
            assert abs(independent_net - row.net_position_return) < 1e-12
            assert abs(row.buy_notional_raw + row.buy_fee_raw + row.cash_leftover_raw - 100000) < 1e-7
            sample["net_position_return_independent_decimal"] = independent_net
        samples.append(sample)
    manifest = {"status": "PASS", "design_sha256": digest(EX / "protocols/design.json"), "published_design_sha256": digest(publication), "accepted_financial_inputs_sha256": digest(FINANCIAL), "native_identities": identities, "network": "socket connect/create_connection blocked; ProviderConfig empty bindings; public fetch only", "new_upstream_calls": 0, "new_accounts": 0, "new_candidates": 0, "events": len(frame), "evaluation_reports": 27, "settings": SETTINGS, "labels_path": target.relative_to(ROOT).as_posix(), "labels_sha256": digest(target), "price_scale": {"HFQ_is_raw_times_factor_verified_all_OHLC": True, "factor_unique_values_rounded12": sorted(set(round(float(v), 12) for v in factors)), "factor_comparison_tolerance": "rtol1e-10_atol1e-12; raw floating-point ratio differences are not corporate actions", "research_quantity": "raw entry quantity / entry factor; later cash-equity is synthetic HFQ position label; not a full raw-share corporate-action ledger"}, "source_hashes": {p.relative_to(ROOT).as_posix(): digest(p) for p in (Path(__file__), ROOT / "packages/trading_execution_engine/src/trading_execution_engine/fills.py", ROOT / "packages/trading_execution_engine/src/trading_execution_engine/market.py", ROOT / "packages/strategy_runtime/src/strategy_runtime/execution_rules.py")}, "limitations": ["isolated fixed-event labels, no continuous strategy account or annual qualification", "daily-range fills have session precision where applicable, not certified minute path or queue fills", "full-session MAE can precede an intraday entry fill", "no-trade net-position returns remain missing; isolated cash-equity return is zero", "historical development data already seen; no independent untouched holdout"]}
    write(OUT / "market_inputs.json", manifest)
    write(OUT / "market_label_checks.json", {"status": "PASS", "synthetic": precheck, "independent_actual_samples": samples, "rows": len(frame), "price_status_counts": frame.price_label_status.value_counts().to_dict(), "execution_status_counts": frame.execution_status.value_counts().to_dict(), "no_missing_event_rows": True, "delay_sessions_counts": frame.exit_delay_sessions.value_counts(dropna=False).rename(index=str).to_dict(), "factor_change_count": int((~np.isclose(factors.to_numpy()[1:], factors.to_numpy()[:-1], rtol=1e-10, atol=1e-12)).sum()), "labels_sha256": digest(target)})
    print(json.dumps({"status": "PASS", "events": len(frame), "execution": frame.execution_status.value_counts().to_dict(), "labels_sha256": digest(target)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
