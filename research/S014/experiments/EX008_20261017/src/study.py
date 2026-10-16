"""Execution-aligned phase-two tests of price bounds and session conflict."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from datetime import datetime, time
import json
import sys
import time as timer

import numpy as np
import pandas as pd
from trading_execution_engine import OrderSpec, DailyQuote, SessionPriceLimits, resolve_fill
from czsc_trader.research_tools import EvidenceRef
from features import BASE, CONSTRAINTS, SESSION, MODELS, features, predict, event_masks
from inputs import ROOT, EXPERIMENT, RUN, load
from block_stats import compare


def resolve_exit(start, quantity, dates, prices, down, up, ticks):
    for i in range(start, len(dates)):
        fill = resolve_fill(OrderSpec("SELL", "MARKET", quantity), session_open=float(prices[i, 0]),
            session_time=datetime.combine(dates[i].date(), time(9, 30)), intraday_touches=(),
            daily_quote=DailyQuote(float(prices[i, 2]), float(prices[i, 1])),
            session_limits=SessionPriceLimits(dates[i].date(), float(down[i]), float(up[i]), float(ticks[i])))
        if fill.filled:
            return i, float(fill.price)
    return -1, None


def one_day_labels(entries, dates, observation):
    _, prices, _, down, up, ticks = observation[:6]
    records = []
    for row in entries.to_dict("records"):
        s, e, q = (int(row[k]) for k in ("signal", "entry", "quantity"))
        planned = e + 1
        record = {"signal": s, "signal_date": dates[s], "entry": e, "quantity": q, "horizon": 1,
            "entry_filled": bool(row["filled"]), "entry_reason": row["reason"], "planned_exit": planned}
        if planned >= len(dates):
            record.update(status="RIGHT_CENSORED", maturity=-1, net_return=np.nan, adverse=np.nan)
        elif not row["filled"]:
            record.update(status="UNFILLED", maturity=planned, net_return=0., adverse=0.)
        else:
            i, sell = resolve_exit(planned, q, dates, prices, down, up, ticks)
            if i < 0:
                record.update(status="RIGHT_CENSORED", maturity=-1, net_return=np.nan, adverse=np.nan)
            else:
                buy = float(row["fill_price"])
                record.update(status="CLOSED", maturity=i, entry_price=buy, exit_price=sell,
                    net_return=q * (sell * .999 - buy * 1.001) / 100000,
                    adverse=max(0., 1 - min(float(prices[e:i, 3].min()), sell) / buy))
        records.append(record)
    return pd.DataFrame(records)


def precheck(data):
    complete = features(data)
    truncated = {k: v.iloc[:800] for k, v in data.items()}
    pd.testing.assert_frame_equal(complete.iloc[:800], features(truncated))
    changed = {k: v.copy() for k, v in data.items()}
    for k in ("stock.ohlcv", "stock.unadjusted_daily"):
        for col in ("Open", "High", "Low", "Close", "Volume"):
            changed[k].loc[801:, col] *= 2
    pd.testing.assert_frame_equal(complete.iloc[:801], features(changed).iloc[:801])
    np.testing.assert_allclose((complete.gap5 + complete.intraday5).iloc[5:],
        np.log(data["stock.ohlcv"].Close / data["stock.ohlcv"].Close.shift(5)).iloc[5:], rtol=0, atol=1e-12)
    dates = pd.date_range("2020-01-01", periods=4)
    prices = np.array([[10., 11., 9., 10.], [10., 12., 9., 11.], [12., 12., 12., 12.], [13., 14., 12., 13.]])
    entries = pd.DataFrame([{"signal": 0, "entry": 1, "quantity": 100, "filled": True, "fill_price": 10., "reason": "synthetic"},
        {"signal": 1, "entry": 2, "quantity": 100, "filled": False, "fill_price": None, "reason": "synthetic"},
        {"signal": 2, "entry": 3, "quantity": 100, "filled": True, "fill_price": 13., "reason": "synthetic"}])
    observation = (1., prices, np.ones(4), np.full(4, 7.), np.full(4, 20.), np.full(4, .01))
    result = one_day_labels(entries, dates, observation)
    assert abs(result.net_return.iloc[0] - 100 * (12 * .999 - 10 * 1.001) / 100000) < 1e-12
    assert result.net_return.iloc[1] == 0 and result.status.iloc[2] == "RIGHT_CENSORED"
    falling = prices.copy()
    falling[2] = [8., 9., 7.5, 8.]
    loss = one_day_labels(entries, dates, (1., falling, *observation[2:]))
    assert loss.net_return.iloc[0] < 0
    down = observation[3].copy()
    down[2] = 12.
    delayed = one_day_labels(entries, dates, (*observation[:3], down, *observation[4:]))
    assert delayed.maturity.iloc[0] == 3
    assert delayed.net_return.iloc[0] > result.net_return.iloc[0]
    return ["real_prefix_and_future_perturbation", "log_return_decomposition", "H1_cash_nonfill_censor_delay"]


def groups_from(frame, values, selected, control):
    return [(int(year), g.signal.to_numpy(dtype=int), values[g.index], selected[g.index], control[g.index])
            for year, g in frame.groupby("year", sort=True)]


def main():
    started = timer.monotonic()
    if RUN.exists():
        raise RuntimeError("Preserve existing run")
    binding = json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8"))
    for name, value in binding.items():
        path = EXPERIMENT / ("protocols/design.json" if name == "design" else f"src/{name}.py")
        if EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() != path.read_bytes():
            raise RuntimeError("Predeclared source changed")
    data, dates, observation, _, old_labels, prior = load()
    checks = precheck(data)
    entries = prior.replay_entries(old_labels, data, dates, *observation[1:6])
    labels = pd.concat([one_day_labels(entries, dates, observation), old_labels.loc[old_labels.horizon.isin([3, 5, 10])]], ignore_index=True)
    market = features(data)
    frame = labels.loc[labels.maturity.ge(0) & labels.signal.ge(60)].copy()
    for col in market.columns:
        frame[col] = market[col].to_numpy()[frame.signal.to_numpy(dtype=int)]
    frame["year"] = [dates[int(s)].year for s in frame.signal]
    assert np.isfinite(frame[BASE + CONSTRAINTS + SESSION].to_numpy()).all()
    sys.path.insert(0, str(EXPERIMENT / "src"))
    tests, splits, fits = [], [], 0
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        task = ("ridge-base", np.arange(30).reshape(10, 3), np.ones((2, 3)), np.arange(10))
        np.testing.assert_allclose(predict(task)[1], pool.submit(predict, task).result()[1], rtol=0, atol=0)
        checks.append("serial_spawn_equal")
        for h in (1, 3, 5, 10):
            available = frame.loc[frame.horizon.eq(h)].sort_values("signal")
            for year in (2023, 2024, 2025, 2026):
                test = available.loc[available.year.eq(year)].copy()
                cutoff = int(test.signal.min())
                train = available.loc[available.maturity.lt(cutoff)]
                q10, q90 = np.quantile(train.ret1, [.1, .9])
                test["q10"], test["q90"] = q10, q90
                jobs = {name: pool.submit(predict, (name, train[cols].to_numpy(), test[cols].to_numpy(), train.net_return.to_numpy()))
                        for name, cols in MODELS.items()}
                split = {"horizon": h, "year": year, "train": len(train), "test": len(test),
                    "latest_maturity": int(train.maturity.max()), "first_test_signal": cutoff, "q10": q10, "q90": q90, "thresholds": {}}
                for name, job in jobs.items():
                    train_pred, test_pred = job.result()
                    key = name.replace("-", "_")
                    threshold = float(np.quantile(train_pred, .75))
                    test[f"prediction_{key}"], test[f"selected_{key}"] = test_pred, test_pred >= threshold
                    split["thresholds"][name] = threshold
                    fits += 1
                test["prediction_mean"] = train.net_return.mean()
                test["selected_mean"] = True
                assert split["latest_maturity"] < cutoff
                splits.append(split)
                tests.append(test)
        predictions = pd.concat(tests, ignore_index=True)
        names = [n.replace("-", "_") for n in MODELS] + ["mean"]
        comparisons, annual, pending = [], [], []
        for h, original in predictions.groupby("horizon", sort=True):
            part = original.sort_values("signal").reset_index(drop=True)
            y = part.net_return.to_numpy()
            residual = y - part.prediction_ridge_base.to_numpy()
            for name in names:
                selected = part[f"selected_{name}"].to_numpy()
                base = "tree_base" if name.startswith("tree") else "ridge_base"
                for comparator in ("all", "base"):
                    control = np.ones(len(part), dtype=bool) if comparator == "all" else part[f"selected_{base}"].to_numpy()
                    pending.append(({"horizon": int(h), "kind": "model", "component": name, "comparator": comparator},
                        pool.submit(compare, (groups_from(part, y, selected, control), "allocation", 1., 13 + int(h)))))
                for year, g in [("ALL", part), *list(part.groupby("year"))]:
                    mask = g[f"selected_{name}"]
                    annual.append({"horizon": int(h), "year": str(year), "kind": "model", "component": name,
                        "n": len(g), "selected": int(mask.sum()), "filled": int((mask & g.entry_filled).sum()),
                        "selected_mean": float(g.loc[mask, "net_return"].mean()) if mask.any() else None,
                        "net_per_origin": float((g.net_return * mask).mean()), "all_mean": float(g.net_return.mean()),
                        "mae": float((g[f"prediction_{name}"] - g.net_return).abs().mean()),
                        "adverse_selected": float(g.loc[mask, "adverse"].mean()) if mask.any() else None})
            masks = {}
            for event in ("upper-close", "lower-recovery", "gap-down-repair", "gap-up-fade"):
                selected, control = np.zeros(len(part), dtype=bool), np.zeros(len(part), dtype=bool)
                for _, g in part.groupby("year"):
                    a, b, sign = event_masks(g, float(g.q10.iloc[0]), float(g.q90.iloc[0]))[event]
                    selected[g.index], control[g.index] = a, b
                    chosen, compared = g.loc[a], g.loc[b]
                    annual.append({"horizon": int(h), "year": str(int(g.year.iloc[0])), "kind": "event", "component": event,
                        "n": len(g), "selected": len(chosen), "control": len(compared), "filled": int(chosen.entry_filled.sum()),
                        "selected_mean": float(chosen.net_return.mean()) if len(chosen) else None,
                        "control_mean": float(compared.net_return.mean()) if len(compared) else None,
                        "difference": sign * float(chosen.net_return.mean() - compared.net_return.mean()) if len(chosen) and len(compared) else None,
                        "selected_filled_mean": float(chosen.loc[chosen.entry_filled, "net_return"].mean()) if chosen.entry_filled.any() else None})
                masks[event] = (selected, control)
                for mode, values in (("raw", y), ("residual", residual)):
                    pending.append(({"horizon": int(h), "kind": "event", "component": event, "comparator": mode},
                        pool.submit(compare, (groups_from(part, values, selected, control), "conditional", sign, 41 + int(h)))))
            for event, (a, b) in masks.items():
                predictions.loc[original.sort_values("signal").index, f"event_{event.replace('-', '_')}"] = a.astype(float)
                predictions.loc[original.sort_values("signal").index, f"control_{event.replace('-', '_')}"] = b.astype(float)
        comparisons = [{**identity, **job.result()} for identity, job in pending]
    RUN.mkdir(parents=True)
    labels.to_csv(RUN / "labels.csv", index=False, lineterminator="\n")
    entries.to_csv(RUN / "entries.csv", index=False, lineterminator="\n")
    market.to_csv(RUN / "features.csv", index_label="signal", lineterminator="\n")
    predictions.to_csv(RUN / "predictions.csv", index=False, lineterminator="\n")
    pd.DataFrame(annual).to_csv(EXPERIMENT / "others/annual.csv", index=False, lineterminator="\n")
    result = {"fits": fits, "test_rows": len(predictions), "comparisons": comparisons, "splits": splits,
        "nominal_contrasts": len(comparisons), "nominal_history": 192 + len(comparisons), "new_source_calls": 0,
        "strategy_accounts": 0, "prechecks": checks, "seconds": timer.monotonic() - started,
        "limit": "Fully seen development pool; independent attempts, no account/annual acceptance; source publication/revision history unverified"}
    assert fits == 96 and len(comparisons) == 88 and result["seconds"] < 7200
    (EXPERIMENT / "others/computation_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("comparisons", "splits")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
