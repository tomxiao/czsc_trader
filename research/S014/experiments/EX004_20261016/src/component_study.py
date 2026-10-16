"""Causal daily features and execution-aligned component diagnostics for S014."""
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, time
from hashlib import sha256
from multiprocessing import get_context
from pathlib import Path
from uuid import UUID
import json
import math

import numpy as np
import pandas as pd
from tsfresh import extract_features
from strategy_runtime import ExecutionPolicy
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import OrderSpec, DailyQuote, SessionPriceLimits, resolve_fill
from dataflows import DataRequest, Dataset, PreparedDataRef
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources
from component_models import predict, bootstrap

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX004_20261016/first"
PROTOCOL = EXPERIMENT / "protocols/component_protocol.json"


def load_inputs(context, protocol):
    ready = json.loads((ROOT / protocol["source_readiness"]).read_text(encoding="utf-8"))
    if not ready["ready"]:
        raise RuntimeError("Stage-one inputs are not ready")
    result = {}
    for item in ready["records"]:
        request = item["request"]
        reference = item["reference"]
        prepared = PreparedDataRef(UUID(reference["space_id"]), UUID(reference["preparation_id"]), reference["manifest_sha256"])
        fetched = context.data.fetch(DataRequest(Dataset(request["dataset"]), request["symbol"], request["start"],
                                                request["end"], request["required_cutoff"]), prepared=prepared)
        if not fetched.ready or fetched.identity.content_sha256 != item["content_sha256"]:
            raise RuntimeError("Pinned inputs changed or failed")
        result[request["dataset"]] = fetched.dataframe.sort_values("Date").reset_index(drop=True)
    adjusted, raw = result["stock.ohlcv"], result["stock.unadjusted_daily"]
    dates = pd.DatetimeIndex(pd.to_datetime(raw.Date))
    calendar = result["calendar.trading_sessions"]
    expected = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), "Date"]))
    if not dates.equals(expected) or not dates.equals(pd.DatetimeIndex(pd.to_datetime(adjusted.Date))):
        raise RuntimeError("Current no-halt study requires fully aligned source sessions")
    if not result["security.trading_status"].Status.eq("TRADING").all():
        raise RuntimeError("Revisit the study calendar before analyzing a newly observed halt")
    return result, dates


def features(adjusted):
    close, volume, amount = (adjusted[name].astype(float) for name in ("Close", "Volume", "Amount"))
    returns = close.pct_change()
    change = close.diff()
    spread = adjusted.High - adjusted.Low
    denominator = change.abs().rolling(14).sum()
    frame = pd.DataFrame({
        "ret_1": returns, "ret_5": close.pct_change(5), "ret_20": close.pct_change(20),
        "range_1": spread / close, "volume_ratio_5_20": volume.rolling(5).mean() / volume.rolling(20).mean(),
        "efficiency_20": close.diff(20).abs() / change.abs().rolling(20).sum(),
        "close_location": ((close - adjusted.Low) / spread.replace(0, np.nan)).fillna(.5),
        "distance_ma10": close / close.rolling(10).mean() - 1,
        "gain_loss_balance_14": (change.rolling(14).sum() / denominator.replace(0, np.nan)).fillna(0),
        "downside_std_20": returns.clip(upper=0).rolling(20).std(),
        "amount_ratio_5_20": amount.rolling(5).mean() / amount.rolling(20).mean(),
        "return_volume_corr_20": returns.rolling(20).corr(np.log1p(volume).diff()),
    })
    identifiers = np.arange(20, len(adjusted))
    source = {"log_price": np.log(close), "return": returns, "volume_change": np.log1p(volume).diff()}
    rows = []
    for name, values in source.items():
        windows = np.lib.stride_tricks.sliding_window_view(values.to_numpy(), 20)[1:]
        rows.append(pd.DataFrame({"id": np.repeat(identifiers, 20), "offset": np.tile(np.arange(20), len(identifiers)),
                                  "kind": name, "value": windows.reshape(-1)}))
    extracted = extract_features(
        pd.concat(rows, ignore_index=True), column_id="id", column_sort="offset", column_kind="kind", column_value="value",
        kind_to_fc_parameters={"log_price": {"linear_trend": [{"attr": "slope"}, {"attr": "rvalue"}]},
                               "return": {"autocorrelation": [{"lag": 1}], "skewness": None, "standard_deviation": None},
                               "volume_change": {"absolute_sum_of_changes": None}},
        n_jobs=2, disable_progressbar=True,
    )
    return frame.join(extracted).replace([np.inf, -np.inf], np.nan)


def execution_labels(inputs, horizons):
    raw = inputs["stock.unadjusted_daily"]
    adjusted = inputs["stock.ohlcv"]
    dates = pd.DatetimeIndex(pd.to_datetime(raw.Date))
    anchor = float(adjusted.Close.iloc[0] / raw.Close.iloc[0])
    prices = adjusted[["Open", "High", "Low", "Close"]].astype(float) / anchor
    scales = prices.Close / raw.Close
    bounds = inputs["security.price_limits"].set_index(pd.to_datetime(inputs["security.price_limits"].Date))
    limits = [SessionPriceLimits(day.date(), float(bounds.loc[day, "DownLimit"] * scales.iloc[index]),
                                float(bounds.loc[day, "UpLimit"] * scales.iloc[index]), .01 * float(scales.iloc[index]))
              for index, day in enumerate(dates)]
    policy = ExecutionPolicy("FROZEN_RULE", {
        "capital": {"fee_rate": .001, "mode": "full_available_cash", "target_scope": "entry_cycle"},
        "entry": {"order_type": "LIMIT", "limit_parameter": .01},
        "exit": {"order_type": "MARKET", "limit_ratio": .1},
        "instrument": {"lot_size": 100, "maximum_order_quantity": 1000000, "price_limit_ratio": .1, "price_tick": .01},
    })

    def resolve(index, order):
        row = prices.iloc[index]
        return resolve_fill(order, session_open=float(row.Open),
                            session_time=datetime.combine(dates[index].date(), time(9, 30)), intraday_touches=(),
                            daily_quote=DailyQuote(float(row.Low), float(row.High)), session_limits=limits[index])

    rows = []
    for signal in range(20, len(dates) - 1):
        entry = signal + 1
        plan = build_execution_plan(deployment_settings={}, available_cash=100000., position_quantity=0,
                                    target_position=1., policy=policy, signal_reference_price=float(prices.Close.iloc[signal]),
                                    execution_reference_price=float(prices.Close.iloc[signal]), price_scale=float(scales.iloc[signal]),
                                    unadjusted_reference_price=float(raw.Close.iloc[signal]))
        if len(plan["orders"]) != 1:
            raise RuntimeError("Unexpected full-cash entry plan")
        order = plan["orders"][0]
        quantity = int(order["quantity"])
        buy = resolve(entry, OrderSpec("BUY", "LIMIT", quantity, float(order["limit_price"])))
        for horizon in horizons:
            planned_exit = entry + horizon
            record = {"signal": signal, "signal_date": dates[signal], "horizon": horizon,
                      "entry": entry, "entry_filled": buy.filled, "entry_reason": buy.reason,
                      "quantity": quantity, "planned_exit": planned_exit}
            if planned_exit >= len(dates):
                record.update(status="RIGHT_CENSORED", maturity=-1, net_return=np.nan, adverse=np.nan)
            elif not buy.filled:
                record.update(status="UNFILLED", maturity=planned_exit, net_return=0., adverse=0., exit_delay=0)
            else:
                exit_index, sell = planned_exit, None
                while exit_index < len(dates):
                    sell = resolve(exit_index, OrderSpec("SELL", "MARKET", quantity))
                    if sell.filled:
                        break
                    exit_index += 1
                if exit_index >= len(dates):
                    record.update(status="RIGHT_CENSORED", maturity=-1, net_return=np.nan, adverse=np.nan)
                else:
                    profit = quantity * (float(sell.price) * (1 - .001) - float(buy.price) * (1 + .001))
                    minimum = min(float(prices.Close.iloc[entry:exit_index].min()), float(sell.price))
                    record.update(status="CLOSED", maturity=exit_index, net_return=profit / 100000,
                                  adverse=max(0., 1 - minimum / float(buy.price)), exit_delay=exit_index - planned_exit,
                                  entry_price=float(buy.price), exit_price=float(sell.price),
                                  entry_precision=buy.time_precision.value, exit_precision=sell.time_precision.value)
            rows.append(record)
    return pd.DataFrame(rows), anchor


def precheck(pool):
    generator = np.random.default_rng(13)
    task = (generator.normal(size=(40, 3)), generator.normal(size=(12, 3)), generator.normal(size=40))
    serial = predict(task)
    parallel = pool.submit(predict, task).result()
    np.testing.assert_allclose(serial["prediction"], parallel["prediction"], rtol=0, atol=1e-12)
    trial = pd.DataFrame({"Close": np.exp(np.linspace(0, .1, 80) + generator.normal(0, .01, 80)),
                          "Volume": generator.uniform(100, 200, 80), "Amount": generator.uniform(1000, 2000, 80)})
    trial["High"], trial["Low"] = trial.Close * 1.02, trial.Close * .98
    left, right = features(trial), features(trial.iloc[:60])
    pd.testing.assert_frame_equal(left.iloc[:60], right, check_exact=False, rtol=0, atol=1e-12)
    return {"status": "PASS", "serial_spawn_equivalent": True, "tsfresh_prefix_causality": True,
            "workers": 2, "native_threads_per_worker": 1}


def study(pool, feature_frame, labels, dates, protocol):
    base = protocol["features"]["baseline"]
    models = {"return-base": ("net_return", base), "risk-base": ("adverse", base),
              "trend": ("net_return", base + protocol["features"]["trend"]),
              "reversal": ("net_return", base + protocol["features"]["reversal"]),
              "risk": ("adverse", base + protocol["features"]["risk"])}
    pending = []
    for horizon in protocol["labels"]["horizons"]:
        eligible = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0)].copy()
        for year in protocol["design"]["test_years"]:
            first = int(np.flatnonzero(dates.year == year)[0])
            training = eligible.loc[eligible.maturity.lt(first)]
            testing = eligible.loc[pd.to_datetime(eligible.signal_date).dt.year.eq(year)]
            if len(training) < 200 or len(testing) < 40:
                raise RuntimeError("Revisit protocol for insufficient chronological samples")
            for name, (target, columns) in models.items():
                task = (feature_frame.loc[training.signal, columns].to_numpy(),
                        feature_frame.loc[testing.signal, columns].to_numpy(), training[target].to_numpy())
                pending.append((horizon, year, name, target, columns, training, testing, pool.submit(predict, task)))
    predictions, coefficients = [], []
    for horizon, year, name, target, columns, training, testing, future in pending:
        fitted = future.result()
        threshold = float(np.quantile(fitted["train_prediction"], .75 if target == "net_return" else .25))
        selected = fitted["prediction"] >= threshold if target == "net_return" else fitted["prediction"] <= threshold
        frame = testing[["signal", "signal_date", "entry_filled", "net_return", "adverse", "exit_delay"]].copy()
        frame = frame.assign(horizon=horizon, year=year, model=name, prediction=fitted["prediction"],
                             threshold=threshold, selected=selected, train_rows=len(training),
                             train_last_maturity=int(training.maturity.max()), test_first_signal=int(np.flatnonzero(dates.year == year)[0]))
        predictions.append(frame)
        for column, coefficient, mean, scale in zip(columns, fitted["coefficient"], fitted["train_mean"], fitted["train_scale"], strict=True):
            coefficients.append({"horizon": horizon, "year": year, "model": name, "feature": column,
                                 "standardized_coefficient": float(coefficient), "training_mean": float(mean), "training_scale": float(scale)})
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(coefficients)


def compare(pool, predictions):
    annual, jobs = [], []
    for family in ("trend", "reversal", "risk"):
        target = "adverse" if family == "risk" else "net_return"
        baseline = "risk-base" if family == "risk" else "return-base"
        for horizon in (3, 5, 10, 20):
            groups, rows = [], []
            for year in (2023, 2024, 2025, 2026):
                left = predictions.loc[predictions.model.eq(family) & predictions.horizon.eq(horizon) & predictions.year.eq(year)].set_index("signal")
                right = predictions.loc[predictions.model.eq(baseline) & predictions.horizon.eq(horizon) & predictions.year.eq(year)].set_index("signal")
                if not left.index.equals(right.index):
                    raise RuntimeError("Comparator samples differ")
                select, control = left.selected.to_numpy(), right.selected.to_numpy()
                if select.sum() == 0 or control.sum() == 0:
                    row = {"family": family, "horizon": horizon, "year": year, "dates": len(left),
                           "selected": int(select.sum()), "baseline_selected": int(control.sum()),
                           "status": "INSUFFICIENT_DATA", "reason": "NO_SELECTIONS", "difference": None}
                    annual.append(row)
                    rows.append(row)
                    continue
                values = left[target].to_numpy()
                contribution = values * (select / select.mean() - control / control.mean())
                if family == "risk":
                    contribution = -contribution
                group = left.loc[left.selected]
                base = right.loc[right.selected]
                filled = group.loc[group.entry_filled]
                base_filled = base.loc[base.entry_filled]
                row = {"family": family, "horizon": horizon, "year": year, "dates": len(left),
                       "selected": int(select.sum()), "baseline_selected": int(control.sum()),
                       "mean_net_return": float(group.net_return.mean()), "baseline_mean_net_return": float(base.net_return.mean()),
                       "mean_adverse": float(group.adverse.mean()), "baseline_mean_adverse": float(base.adverse.mean()),
                       "filled_only_adverse": float(filled.adverse.mean()) if len(filled) else None,
                       "baseline_filled_only_adverse": float(base_filled.adverse.mean()) if len(base_filled) else None,
                       "fill_rate": float(group.entry_filled.mean()), "baseline_fill_rate": float(base.entry_filled.mean()),
                       "unconditional_net_return": float(left.net_return.mean()), "difference": float(contribution.mean())}
                annual.append(row)
                rows.append(row)
                groups.append(contribution)
            jobs.append((family, horizon, rows, pool.submit(bootstrap, (groups, 13 + horizon)) if len(groups) == 4 else None))
    comparisons = []
    for family, horizon, rows, future in jobs:
        values = future.result() if future is not None else {"status": "INSUFFICIENT_DATA", "reason": "NO_SELECTIONS_IN_A_YEAR",
                                                            "difference": None, "interval_95": None, "interval_familywise": None}
        values.update(family=family, horizon=horizon, positive_years=sum(row["difference"] is not None and row["difference"] > 0 for row in rows),
                      years=len(rows), eligible_dates=sum(row["dates"] for row in rows))
        comparisons.append(values)
    return pd.DataFrame(annual), comparisons


def main():
    import time as timer
    started = timer.monotonic()
    if (RUN / "result.json").exists():
        raise RuntimeError("Review completed output before a new explicit run")
    binding = json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8"))
    if sha256(PROTOCOL.read_bytes()).hexdigest() != binding["protocol"]["sha256"]:
        raise RuntimeError("Design changed after pre-registration")
    for name in ("component_study.py", "component_models.py"):
        if sha256((EXPERIMENT / "src" / name).read_bytes()).hexdigest() != binding[name]["sha256"]:
            raise RuntimeError("Implementation changed after pre-registration")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"), resources=EvaluationResources(2, 1, 13))
    RUN.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        checked = precheck(pool)
        (EXPERIMENT / "others/precheck.json").write_text(json.dumps(checked, indent=2) + "\n", encoding="utf-8")
        print("COMPONENT_PRECHECK=PASS", flush=True)
        inputs, dates = load_inputs(context, protocol)
        feature_frame = features(inputs["stock.ohlcv"])
        feature_frame.assign(signal_date=dates).to_csv(RUN / "features.csv", index_label="signal")
        labels, anchor = execution_labels(inputs, protocol["labels"]["horizons"])
        labels.to_csv(RUN / "labels.csv", index=False)
        print(f"LABELS={len(labels)} FILLED={int(labels.entry_filled.sum())}", flush=True)
        predictions, coefficients = study(pool, feature_frame, labels, dates, protocol)
        predictions.to_csv(RUN / "predictions.csv", index=False)
        coefficients.to_csv(RUN / "coefficients.csv", index=False)
        annual, comparisons = compare(pool, predictions)
        annual.to_csv(RUN / "annual_comparisons.csv", index=False)
    duration = timer.monotonic() - started
    if duration > 2 * 3600:
        raise RuntimeError("Component resource budget exceeded")
    if not all(x["difference"] is None or math.isfinite(x["difference"]) for x in comparisons):
        raise RuntimeError("Nonfinite comparison")
    result = {"status": "COMPONENT_DIAGNOSTICS_COMPLETE", "symbol": "600722.SH", "date_rows": len(dates),
              "feature_count": len(feature_frame.columns), "precheck": checked, "comparisons": comparisons,
              "label_counts": labels.groupby(["horizon", "status"]).size().reset_index(name="count").to_dict("records"),
              "exit_delays": labels.groupby("horizon").exit_delay.sum().to_dict(), "hfq_anchor_factor": anchor,
              "seconds": duration, "new_source_calls": 0, "parameter_searches": 0, "strategy_account_evaluations": 0,
              "model_fits": 80, "workers": 2, "native_threads_per_worker": 1,
              "limitations": ["Same-source features and development-pool temporal validation", "Overlapping independent attempts, not an investable single-position account", "No annual strategy acceptance or future success probability inferred", "Publication timing and revision history unverified"]}
    (RUN / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (EXPERIMENT / "others/computation_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "seconds": duration, "comparisons": comparisons}), flush=True)


if __name__ == "__main__":
    main()
