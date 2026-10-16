"""Independent recomputation of chronology, execution and declared comparisons."""
from datetime import datetime, time
from hashlib import sha256
import json

import numpy as np
import pandas as pd
from trading_execution_engine import OrderSpec, DailyQuote, SessionPriceLimits, resolve_fill
from components import MODELS, fit_predict
from inputs import ROOT, EXPERIMENT, RUN, load
from online import FEATURES, MODELS as ONLINE_MODELS, weighted_predict
from study import check_binding, build_frame, precheck


def main():
    if (EXPERIMENT / "others/audit.json").exists():
        raise RuntimeError("Preserve completed audit")
    checks = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    check_binding()
    checks.append("initial_design_and_source_identity")
    data, dates, observation, decisions, labels, prior = load()
    checks.append("predecessor_full_validation_and_5_native_input_identities")
    checks.extend(precheck(data))
    frame, market = build_frame(data, dates, observation, decisions, labels)
    saved = pd.read_csv(RUN / "observations.csv")
    for col in frame.select_dtypes(include=[np.number]).columns:
        require(f"recomputed_observation_{col}", np.allclose(saved[col], frame[col], rtol=0, atol=1e-11))
    require("unique_horizon_decision", not frame.duplicated(["horizon", "decision"]).any())
    require("past_entry_and_future_exit", ((frame.entry <= frame.decision) & (frame.decision < frame.earlier_exit) &
        (frame.earlier_exit <= frame.maturity)).all())
    require("holding_label_cash_identity", np.allclose(frame.target, frame.fixed_net - frame.earlier_net, rtol=0, atol=1e-12))
    anchor, prices, scales, down, up, ticks = observation[:6]
    entry_replication = prior.replay_entries(labels, data, dates, prices, scales, down, up, ticks)
    require("srt_all_original_entries_replicate", len(entry_replication) == labels.signal.nunique())
    reference = labels.set_index(["signal", "horizon"])
    exit_count = 0
    for record in frame.to_dict("records"):
        source = reference.loc[(record["signal"], record["horizon"])]
        q, buy = int(source.quantity), float(source.entry_price)
        for start, inherited_index, net in ((int(record["decision"]) + 1, int(record["earlier_exit"]), record["earlier_net"]),
                                           (int(source.planned_exit), int(record["maturity"]), record["fixed_net"])):
            for i in range(start, inherited_index + 1):
                fill = resolve_fill(OrderSpec("SELL", "MARKET", q), session_open=float(prices[i, 0]),
                    session_time=datetime.combine(dates[i].date(), time(9, 30)), intraday_touches=(),
                    daily_quote=DailyQuote(float(prices[i, 2]), float(prices[i, 1])),
                    session_limits=SessionPriceLimits(dates[i].date(), float(down[i]), float(up[i]), float(ticks[i])))
                if fill.filled:
                    assert i == inherited_index
                    assert abs(q * (float(fill.price) * .999 - buy * 1.001) / 100000 - net) < 1e-11
                    exit_count += 1
                    break
            else:
                raise AssertionError("No independently reproduced exit")
    checks.append("all_fixed_and_checkpoint_txe_exits_and_fees")
    predictions = pd.read_csv(RUN / "predictions.csv")
    fits = 0
    for (h, year), test in predictions.groupby(["horizon", "decision_year"]):
        cutoff = int(test.decision.min())
        train = frame.loc[frame.horizon.eq(h) & frame.maturity.lt(cutoff)]
        require(f"mature_before_test_{h}_{year}", train.maturity.max() < cutoff)
        for model, columns in MODELS.items():
            values = fit_predict((model, train[columns].to_numpy(), test[columns].to_numpy(), train.target.to_numpy()))
            key = model.replace("-", "_")
            np.testing.assert_allclose(values, test[f"prediction_{key}"], rtol=0, atol=1e-11)
            fits += 1
    require("all120_fixed_model_predictions_recomputed", fits == 120)
    names = [c.removeprefix("continue_") for c in predictions.columns if c.startswith("continue_")]
    for name in names:
        np.testing.assert_allclose(predictions[f"chosen_{name}"], np.where(predictions[f"continue_{name}"],
            predictions.fixed_net, predictions.earlier_net), rtol=0, atol=1e-12)
    checks.append("all_checkpoint_actions_are_fee_adjusted_cash_choices")
    annual = pd.read_csv(EXPERIMENT / "others/annual.csv", dtype={"year": str})
    for record in annual.to_dict("records"):
        subset = predictions.loc[predictions.horizon.eq(record["horizon"])]
        if record["year"] != "ALL":
            subset = subset.loc[subset.decision_year.eq(int(record["year"]))]
        chosen = subset[f"chosen_{record['model']}"]
        assert len(subset) == record["n"]
        assert abs((chosen - subset.fixed_net).mean() - record["difference_hold"]) < 1e-12
        assert abs((chosen - subset.chosen_ridge_base).mean() - record["difference_base"]) < 1e-12
    checks.append("all_fixed_annual_and_pooled_cash_differences")
    fixed = json.loads((EXPERIMENT / "others/computation_result.json").read_text(encoding="utf-8"))
    for c in fixed["comparisons"]:
        subset = predictions.loc[predictions.horizon.eq(c["horizon"])]
        comparator = subset.fixed_net if c["comparator"] == "always-hold" else subset.chosen_ridge_base
        v = subset[f"chosen_{c['model']}"] - comparator
        assert abs(v.mean() - c["mean_difference"]) < 1e-12
        assert abs(v.loc[subset.decision_year.ne(2026)].mean() - c["without2026"]) < 1e-12
        assert abs(v.sort_values(ascending=False).iloc[3:].mean() - c["drop_best3"]) < 1e-12
    checks.append("all78_primary_means_and_counterevidence")
    online = pd.read_csv(RUN / "online_predictions.csv")
    split = pd.read_csv(RUN / "online_splits.csv")
    require("online_maturity_strict_for_every_decision", (split.latest_maturity < split.signal).all() and
        (split.latest_annual_maturity < split.year_first_signal).all())
    online_fits = 0
    for horizon, actual in online.groupby("horizon"):
        available = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0) & labels.signal.ge(60)].sort_values("signal")
        x = market.iloc[available.signal.astype(int)][FEATURES].to_numpy()
        y = available.net_return.to_numpy()
        signals, maturity = available.signal.to_numpy(dtype=int), available.maturity.to_numpy(dtype=int)
        require(f"all_native_eligible_test_signals_{horizon}", set(actual.signal) == set(signals[[dates[s].year >= 2023 for s in signals]]))
        for row in actual.to_dict("records"):
            i = int(np.flatnonzero(signals == row["signal"])[0])
            first = actual.loc[actual.year.eq(row["year"]), "signal"].min()
            assert abs(y[i] - row["net"]) < 1e-12
            for model in ONLINE_MODELS:
                mask = maturity < (first if model == "annual" else row["signal"])
                weights = np.ones(int(mask.sum()))
                if model.endswith("126") or model.endswith("252"):
                    half = 126 if model.endswith("126") else 252
                    weights = np.exp2(-(row["signal"] - signals[mask]) / half)
                prediction = weighted_predict(x[mask], y[mask], x[i], weights, model.startswith("mean"))
                assert abs(prediction - row[f"pred_{model}"]) < 1e-11
                assert abs(row[f"chosen_{model}"] - (y[i] if prediction > 0 else 0)) < 1e-12
                online_fits += not model.startswith("mean")
    require("all_online_scores_actions_recomputed", online_fits == 7244)
    checks.append("nonfills_remain_zero_in_online_universe")
    require("nonfill_actual_zero", online.loc[~online.filled, "net"].eq(0).all())
    result = json.loads((EXPERIMENT / "others/online_result.json").read_text(encoding="utf-8"))
    for c in result["comparisons"]:
        g = online.loc[online.horizon.eq(c["horizon"])]
        comp = g.net if c["comparator"] == "always-enter" else g.chosen_annual if c["comparator"] == "annual" else g[f"chosen_mean{252 if c['model'].endswith('252') else 126}"]
        difference = g[f"chosen_{c['model']}"] - comp
        assert abs(difference.mean() - c["difference"]) < 1e-12
        assert abs(difference.loc[g.year.ne(2026)].mean() - c["without2026"]) < 1e-12
    checks.append("all36_online_contrasts_recomputed")
    require("no_new_source_calls_or_strategy_accounts", fixed["new_source_calls"] == result["source_calls"] == fixed["strategy_accounts"] == result["strategy_accounts"] == 0)
    # Sensitivity corrects '20 sessions' to a genuine exchange-session grid.
    # Initial intervals used 20 eligible observations, with occasional nonfill gaps.
    sensitivity = []
    rng = np.random.default_rng(13)
    for h, part in predictions.groupby("horizon"):
        part = part.sort_values("decision").reset_index(drop=True)
        keys = [(name, comp) for name in names for comp in ("always-hold", "ridge-base")]
        differences = np.column_stack([part[f"chosen_{name}"] - (part.fixed_net if comp == "always-hold" else part.chosen_ridge_base) for name, comp in keys])
        distribution, counts = np.zeros((5000, len(keys))), np.zeros(5000)
        for _, pos in part.groupby("decision_year").indices.items():
            start, end = int(part.decision.iloc[pos].min()), int(part.decision.iloc[pos].max())
            grid, observed = np.zeros((end - start + 1, len(keys))), np.zeros(end - start + 1)
            indices = part.decision.iloc[pos].to_numpy(dtype=int) - start
            grid[indices], observed[indices] = differences[pos], 1
            for batch in range(0, 5000, 100):
                origins = rng.integers(0, len(grid), (100, int(np.ceil(len(grid) / 20))))
                idx = ((origins[:, :, None] + np.arange(20)) % len(grid)).reshape(100, -1)[:, :len(grid)]
                distribution[batch:batch + 100] += grid[idx].sum(axis=1)
                counts[batch:batch + 100] += observed[idx].sum(axis=1)
        distribution /= counts[:, None]
        for j, (name, comp) in enumerate(keys):
            sensitivity.append({"horizon": int(h), "model": name, "comparator": comp,
                "mean_difference": float(differences[:, j].mean()),
                "interval95": np.quantile(distribution[:, j], [.025, .975]).tolist(),
                "interval_history192": np.quantile(distribution[:, j], [.05 / 384, 1 - .05 / 384]).tolist()})
    (EXPERIMENT / "others/calendar_interval_sensitivity.json").write_text(json.dumps(sensitivity, indent=2) + "\n", encoding="utf-8")
    checks.append("exchange_session_block_sensitivity_saved_without_rewriting_original")
    paths = [*RUN.glob("*.csv"), *[EXPERIMENT / "others" / name for name in
        ("computation_result.json", "online_result.json", "annual.csv", "online_annual.csv", "calendar_interval_sensitivity.json")]]
    manifest = [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p.read_bytes()).hexdigest()} for p in paths]
    report = {"status": "PASS", "checks": checks, "fixed_fit_recomputations": fits,
        "online_fit_recomputations": online_fits, "entries_replicated": len(entry_replication),
        "txe_exits_replicated": exit_count, "manifest": manifest,
        "method_note": "Initial fixed-model intervals used20eligible decision observations. Exact exchange-session-grid sensitivity published separately; point estimates unchanged. All adaptive choices remain seen-pool research, not independent validation."}
    (EXPERIMENT / "others/audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("manifest", "checks")},ensure_ascii=False))
    print('AUDIT_CHECKS', len(checks))


if __name__ == "__main__":
    main()
