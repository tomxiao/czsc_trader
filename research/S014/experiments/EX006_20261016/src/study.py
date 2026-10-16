"""Attribute fixed-execution observations and test bounded causal contrasts."""
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, time
from hashlib import sha256
from io import BytesIO
from multiprocessing import get_context
from pathlib import Path
from uuid import UUID
import json
import time as timer

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef
from strategy_runtime import ExecutionPolicy
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import OrderSpec, DailyQuote, SessionPriceLimits, resolve_fill
from czsc_trader.application import RepositoryContext, create_research_context, validate_delivery
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, DeliveryReference, EvaluationResources, ValidationStatus
from attribution import horizon_study, synthetic_task
from paired import compare

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX006_20261016/first"


def load_inputs(context, prior):
    reference = EvidenceRef.from_dict(prior["evidence"]["input-readiness"])
    ready = json.loads(reference.resolve(ROOT).read_text(encoding="utf-8"))
    inputs = {}
    for record in ready["records"]:
        request, bound = record["request"], record["reference"]
        prepared = PreparedDataRef(UUID(bound["space_id"]), UUID(bound["preparation_id"]), bound["manifest_sha256"])
        fetched = context.data.fetch(DataRequest(Dataset(request["dataset"]), request["symbol"], request["start"], request["end"], request["required_cutoff"]), prepared=prepared)
        if not fetched.ready or fetched.identity.content_sha256 != record["content_sha256"]:
            raise RuntimeError("Pinned input failed or changed")
        inputs[request["dataset"]] = fetched.dataframe.sort_values("Date").reset_index(drop=True)
    dates = pd.DatetimeIndex(pd.to_datetime(inputs["stock.ohlcv"].Date))
    calendar = inputs["calendar.trading_sessions"]
    expected = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), "Date"]))
    if not dates.equals(expected):
        raise AssertionError("Calendar mismatch")
    for name in ("stock.unadjusted_daily", "security.price_limits", "security.trading_status"):
        if not dates.equals(pd.DatetimeIndex(pd.to_datetime(inputs[name].Date))):
            raise AssertionError("Source sessions mismatch")
    if not inputs["security.trading_status"].Status.eq("TRADING").all():
        raise RuntimeError("Unexpected halt requires explicit calendar redesign")
    return inputs, dates


def observations(inputs):
    bars, raw = inputs["stock.ohlcv"], inputs["stock.unadjusted_daily"]
    anchor = float(bars.Close.iloc[0] / raw.Close.iloc[0])
    prices = bars[["Open", "High", "Low", "Close"]].to_numpy(dtype=float) / anchor
    scales = prices[:, 3] / raw.Close.to_numpy(dtype=float)
    bounds = inputs["security.price_limits"]
    down, up, ticks = bounds.DownLimit.to_numpy(dtype=float) * scales, bounds.UpLimit.to_numpy(dtype=float) * scales, .01 * scales
    ret1, ret5, ret20 = bars.Close.pct_change(), bars.Close.pct_change(5), bars.Close.pct_change(20)
    pullback = (bars.Close > bars.Close.rolling(60).mean()) & ret5.lt(0)
    breakout = bars.Close > bars.High.shift(1).rolling(20).max()
    volume = bars.Volume > bars.Volume.shift(1).rolling(20).mean()
    flags = np.column_stack((ret20.ge(0), pullback, pullback & ret1.gt(0), breakout, breakout & volume,
                             (raw.Close - bounds.UpLimit).abs().le(.005)))
    return anchor, prices, scales, down, up, ticks, flags


def replay_entries(labels, inputs, dates, prices, scales, down, up, ticks):
    policy = ExecutionPolicy("FROZEN_RULE", {
        "capital": {"fee_rate": .001, "mode": "full_available_cash", "target_scope": "entry_cycle"},
        "entry": {"order_type": "LIMIT", "limit_parameter": .01}, "exit": {"order_type": "MARKET", "limit_ratio": .1},
        "instrument": {"lot_size": 100, "maximum_order_quantity": 1000000, "price_limit_ratio": .1, "price_tick": .01}})
    raw = inputs["stock.unadjusted_daily"]
    entries = []
    for signal, records in labels.groupby("signal", sort=True):
        signal = int(signal)
        entry = signal + 1
        planned = build_execution_plan(deployment_settings={}, available_cash=100000., position_quantity=0,
            target_position=1., policy=policy, signal_reference_price=float(prices[signal, 3]),
            execution_reference_price=float(prices[signal, 3]), price_scale=float(scales[signal]),
            unadjusted_reference_price=float(raw.Close.iloc[signal]))
        if len(planned["orders"]) != 1:
            raise AssertionError("Unexpected entry plan")
        order = planned["orders"][0]
        limits = SessionPriceLimits(dates[entry].date(), float(down[entry]), float(up[entry]), float(ticks[entry]))
        fill = resolve_fill(OrderSpec("BUY", "LIMIT", int(order["quantity"]), float(order["limit_price"])),
            session_open=float(prices[entry, 0]), session_time=datetime.combine(dates[entry].date(), time(9, 30)),
            intraday_touches=(), daily_quote=DailyQuote(float(prices[entry, 2]), float(prices[entry, 1])), session_limits=limits)
        if not records.quantity.eq(order["quantity"]).all() or not records.entry_filled.eq(fill.filled).all():
            raise AssertionError("Prior quantity or entry flag does not replicate")
        closed = records.loc[records.status.eq("CLOSED")]
        if len(closed) and not np.allclose(closed.entry_price, fill.price, rtol=0, atol=1e-10):
            raise AssertionError("Prior actual entry does not replicate")
        entries.append({"signal": signal, "entry": entry, "quantity": int(order["quantity"]), "limit_price": float(order["limit_price"]),
                        "filled": fill.filled, "fill_price": fill.price, "reason": fill.reason})
    return pd.DataFrame(entries)


def mean(frame, column):
    if column not in frame or not frame[column].notna().any():
        return None
    return float(frame[column].mean())


def summarize(frame):
    closed = frame.loc[frame.status.eq("CLOSED")]
    unfilled = frame.loc[frame.status.eq("UNFILLED")]
    losses = closed.loc[closed.net_return.le(0)]
    output = {"attempts": len(frame), "filled_closed": len(closed), "unfilled": len(unfilled),
              "mean_net_per_attempt": mean(frame, "net_return"), "mean_net_filled": mean(closed, "net_return"),
              "mean_gap_fraction": mean(frame, "gap_fraction"), "losses": len(losses),
              "positive_mark_attempts": int(closed.had_positive_mark.sum()),
              "positive_mark_to_loss": int(closed.positive_mark_to_loss.sum()),
              "hindsight_rescues": int(closed.hindsight_rescue.sum()),
              "delay_attempts": int(closed.exit_delay.gt(0).sum()), "delay_sessions": int(closed.exit_delay.sum())}
    for column in ("signal_exit_same_quantity_cash", "gap_cash", "intraday_entry_cash", "fees_cash", "holding_gross_cash",
                   "positive_close_mark_peak", "positive_profit_returned", "peak_to_exit_drop", "hindsight_headroom", "signed_delay_proceeds_effect"):
        output[f"mean_{column}_filled"] = mean(closed, column)
    output["noninvested_market_path_mean"] = mean(unfilled, "noninvested_market_path")
    return output


def summary_tables(paths):
    rows = []
    mature = paths.loc[paths.status.ne("RIGHT_CENSORED")]
    for scope, available in (("common", mature.loc[mature.common]), ("native", mature)):
        for horizon, horizon_rows in available.groupby("horizon"):
            groups = {"all": horizon_rows, "uptrend": horizon_rows.loc[horizon_rows.known_uptrend],
                "downtrend": horizon_rows.loc[~horizon_rows.known_uptrend], "upper-limit-close": horizon_rows.loc[horizon_rows.upper_limit_close],
                "other-close": horizon_rows.loc[~horizon_rows.upper_limit_close]}
            for name in ("pullback_parent", "pullback_confirm", "breakout_parent", "breakout_confirm"):
                groups[name] = horizon_rows.loc[horizon_rows.parent_ready & horizon_rows[name]]
            for group, subset in groups.items():
                for year, part in [("ALL", subset), *list(subset.groupby("year"))]:
                    rows.append(dict(scope=scope, horizon=int(horizon), group=group, year=str(year), **summarize(part)))
    return pd.DataFrame(rows)


def primary_comparisons(pool, paths, decisions):
    aggregate, pending, annual = [], [], []
    for horizon in (3, 5, 10, 20):
        for family in ("pullback", "breakout"):
            groups = []
            for year in (2023, 2024, 2025, 2026):
                frame = paths.loc[paths.common & paths.horizon.eq(horizon) & paths.year.eq(year) & paths.parent_ready].sort_values("signal")
                groups.append((year, frame.net_return.to_numpy(), frame[f"{family}_confirm"].to_numpy(), frame[f"{family}_parent"].to_numpy()))
            pending.append((f"{family}-confirmation", horizon, pool.submit(compare, (groups, 13 + horizon))))
        for checkpoint in ("entry-close", "midpoint"):
            groups = []
            for year in (2023, 2024, 2025, 2026):
                frame = decisions.loc[decisions.common & decisions.horizon.eq(horizon) & decisions.checkpoint.eq(checkpoint) & decisions.decision_year.eq(year)].sort_values("signal")
                selected, control = frame.selected.to_numpy(), frame.control.to_numpy()
                groups.append((year, frame.exit_advantage.to_numpy(), selected, control))
                row = {"horizon": horizon, "checkpoint": checkpoint, "year": year, "dates": len(frame),
                    "profitable_weak": int(selected.sum()), "profitable_nonweak": int(control.sum()),
                    "selected_advantage": mean(frame.loc[selected], "exit_advantage"), "control_advantage": mean(frame.loc[control], "exit_advantage"),
                    "all_advantage": mean(frame, "exit_advantage"), "selected_earlier_net": mean(frame.loc[selected], "earlier_net"),
                    "selected_fixed_net": mean(frame.loc[selected], "fixed_net"), "selected_strictly_earlier": mean(frame.loc[selected], "strictly_earlier")}
                picked = frame.loc[selected].sort_values("exit_advantage", ascending=False)
                row["selected_advantage_drop_top1"] = mean(picked.iloc[1:], "exit_advantage")
                row["selected_advantage_drop_top3"] = mean(picked.iloc[3:], "exit_advantage")
                annual.append(row)
            pending.append((f"exit-{checkpoint}", horizon, pool.submit(compare, (groups, 31 + horizon))))
    if len(pending) != 16:
        raise AssertionError("Primary comparison count changed")
    for name, horizon, future in pending:
        result = future.result()
        result.update(comparison=name, horizon=horizon)
        aggregate.append(result)
    return aggregate, pd.DataFrame(annual)


def main():
    started = timer.monotonic()
    if (RUN / "result.json").exists():
        raise RuntimeError("Output exists; preserve completed run")
    published = json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8"))
    for name, path in (("design", EXPERIMENT / "protocols/design.json"), ("attribution", EXPERIMENT / "src/attribution.py"),
                       ("paired", EXPERIMENT / "src/paired.py"), ("study", Path(__file__))):
        reference = EvidenceRef.from_dict(published[name])
        reference.resolve(ROOT)
        if sha256(path.read_bytes()).hexdigest() != reference.sha256:
            raise RuntimeError("Preregistered source changed")
    repository = RepositoryContext.discover(ROOT)
    previous = json.loads((ROOT / "research/S014/experiments/EX005_20261016/others/result.json").read_text(encoding="utf-8"))
    if validate_delivery(repository, DeliveryReference.from_dict(previous["delivery"])).status is not ValidationStatus.PASS:
        raise RuntimeError("Predecessor changed")
    initial = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    label_ref = EvidenceRef.from_dict(initial["evidence"]["labels"])
    labels = pd.read_csv(BytesIO(label_ref.resolve(ROOT).read_bytes()))
    context = create_research_context(repository, ResearchBatchRef("S014"), resources=EvaluationResources(2, 1, 13))
    original = requests.sessions.Session.request

    def prohibit(*args, **kwargs):
        raise RuntimeError("No source calls in this approved asset-reuse round")

    requests.sessions.Session.request = prohibit
    try:
        inputs, dates = load_inputs(context, initial)
    finally:
        requests.sessions.Session.request = original
    anchor, prices, scales, down, up, ticks, flags = observations(inputs)
    RUN.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        ordinary, delayed = synthetic_task(), synthetic_task(True)
        serial, parallel = horizon_study(ordinary), pool.submit(horizon_study, ordinary).result()
        pd.testing.assert_frame_equal(pd.DataFrame(serial[0]), pd.DataFrame(parallel[0]))
        pd.testing.assert_frame_equal(pd.DataFrame(serial[1]), pd.DataFrame(parallel[1]))
        assert serial[0][0]["hindsight_best_exit"] == 3
        assert pool.submit(horizon_study, delayed).result()[0][0]["exit_delay"] == 1
        print("SYNTHETIC_PRECHECK=PASS", flush=True)
        entries = replay_entries(labels, inputs, dates, prices, scales, down, up, ticks)
        entries.to_csv(RUN / "entry_replay.csv", index=False)
        print(f"ENTRY_REPLICATION={len(entries)}", flush=True)
        jobs = [pool.submit(horizon_study, (horizon, labels.loc[labels.horizon.eq(horizon)].to_dict("records"), prices, down, up, ticks, dates, flags)) for horizon in (3, 5, 10, 20)]
        combined = [job.result() for job in jobs]
        paths = pd.DataFrame([record for records, _ in combined for record in records])
        decisions = pd.DataFrame([record for _, records in combined for record in records])
        common = set.intersection(*(set(labels.loc[labels.horizon.eq(h) & labels.maturity.ge(0), "signal"]) for h in (3, 5, 10, 20)))
        paths["common"] = paths.signal.isin(common)
        decisions["common"] = decisions.signal.isin(common)
        summary = summary_tables(paths)
        aggregate, annual = primary_comparisons(pool, paths, decisions)
    paths.to_csv(RUN / "paths.csv", index=False)
    decisions.to_csv(RUN / "decisions.csv", index=False)
    summary.to_csv(EXPERIMENT / "others/attribution_summary.csv", index=False)
    annual.to_csv(EXPERIMENT / "others/exit_condition_annual.csv", index=False)
    pd.DataFrame(flags, columns=["uptrend", "pullback_parent", "pullback_confirm", "breakout_parent", "breakout_confirm", "upper_limit_close"]).assign(signal_date=dates).to_csv(RUN / "features.csv", index_label="signal")
    result = {"status": "ATTRIBUTION_COMPUTED", "common_signals": len(common), "common_first": str(dates[min(common)].date()),
        "common_last": str(dates[max(common)].date()), "date_rows": len(dates), "label_rows": len(paths), "decision_rows": len(decisions),
        "entry_replications": len(entries), "hfq_anchor": anchor, "comparisons": aggregate,
        "new_primary_comparisons": 16, "nominal_history_comparisons": 78, "new_model_fits": 0, "parameter_searches": 0,
        "new_source_calls": 0, "strategy_accounts": 0, "workers": 2, "native_threads_per_worker": 1,
        "precheck": "Serial/spawn path/decision equality; delayed exit; inherited SRT quantities, buy flags/prices and every fixed TXE sell replicated",
        "seconds": timer.monotonic() - started,
        "limits": "All development data seen; independent overlapping attempts and hindsight diagnostics, not an account or annual economic acceptance; historical publication/revision timing unverified"}
    if result["seconds"] > 7200:
        raise RuntimeError("Declared program budget exceeded")
    for path in (RUN / "result.json", EXPERIMENT / "others/computation_result.json"):
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
