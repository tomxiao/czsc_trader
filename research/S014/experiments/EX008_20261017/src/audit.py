"""Recompute executions, models, contrasts and the strongest competing controls."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from features import MODELS, features, predict, event_masks
from inputs import ROOT, EXPERIMENT, RUN, load
from study import precheck, one_day_labels, resolve_exit
from followup import contrasts
from block_stats import compare


def main():
    if (EXPERIMENT / "others/audit.json").exists():
        raise RuntimeError("Preserve completed audit")
    checks = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    for filename in ("published_design.json", "followup_published.json"):
        binding = json.loads((EXPERIMENT / "protocols" / filename).read_text(encoding="utf-8"))
        for name, value in binding.items():
            path = EXPERIMENT / ("protocols/design.json" if name == "design" else "protocols/followup_design.json" if name == "followup-design" else f"src/{name}.py")
            require(f"predeclared_{name}", EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() == path.read_bytes())
    data, dates, observation, _, inherited, prior = load()
    checks.append("predecessor_full_pass_and_native_input_hashes")
    checks.extend(precheck(data))
    original_entries = prior.replay_entries(inherited, data, dates, *observation[1:6])
    stored_entries = pd.read_csv(RUN / "entries.csv")
    require("all_srt_entry_plans_prices_and_nonfills", len(original_entries) == len(stored_entries) == 1621)
    for c in ("signal", "entry", "quantity", "filled", "fill_price", "limit_price"):
        require(f"entry_{c}", np.allclose(original_entries[c], stored_entries[c], rtol=0, atol=1e-11, equal_nan=True))
    labels = pd.read_csv(RUN / "labels.csv")
    new = one_day_labels(original_entries, dates, observation)
    old = labels.loc[labels.horizon.eq(1)].reset_index(drop=True)
    require("H1_all_statuses", new.status.equals(old.status))
    for c in ("net_return", "adverse", "maturity", "quantity", "entry_price", "exit_price"):
        require(f"H1_{c}", np.allclose(new[c], old[c], rtol=0, atol=1e-11, equal_nan=True))
    require("no_same_day_H1_sale", new.loc[new.status.eq("CLOSED"), "maturity"].gt(new.loc[new.status.eq("CLOSED"), "entry"]).all())
    exits = 0
    _, prices, _, down, up, ticks = observation[:6]
    for row in labels.loc[labels.status.eq("CLOSED")].to_dict("records"):
        i, sell = resolve_exit(int(row["planned_exit"]), int(row["quantity"]), dates, prices, down, up, ticks)
        assert i == int(row["maturity"]) and abs(sell - row["exit_price"]) < 1e-11
        net = int(row["quantity"]) * (sell * .999 - row["entry_price"] * 1.001) / 100000
        assert abs(net - row["net_return"]) < 1e-11
        exits += 1
    checks.append("all4horizon_txe_exits_same_quantity_fees")
    for h in (3, 5, 10):
        actual = labels.loc[labels.horizon.eq(h)].reset_index(drop=True)
        expected = inherited.loc[inherited.horizon.eq(h)].reset_index(drop=True)
        require(f"inherited_h{h}_status", actual.status.equals(expected.status))
        for c in ("quantity", "maturity", "net_return", "adverse", "entry_price", "exit_price"):
            np.testing.assert_allclose(actual[c], expected[c], rtol=0, atol=1e-11, equal_nan=True)
    market = features(data)
    predictions = pd.read_csv(RUN / "predictions.csv")
    result = json.loads((EXPERIMENT / "others/computation_result.json").read_text(encoding="utf-8"))
    fits = 0
    for split in result["splits"]:
        h, year = split["horizon"], split["year"]
        train = labels.loc[labels.horizon.eq(h) & labels.signal.ge(60) & labels.maturity.ge(0) & labels.maturity.lt(split["first_test_signal"])].sort_values("signal")
        test = predictions.loc[predictions.horizon.eq(h) & predictions.year.eq(year)]
        require(f"maturity_split_h{h}_{year}", len(train) == split["train"] and train.maturity.max() < test.signal.min())
        train_x, test_x = market.iloc[train.signal.astype(int)], market.iloc[test.signal.astype(int)]
        q = np.quantile(train_x.ret1, [.1, .9])
        np.testing.assert_allclose(q, [split["q10"], split["q90"]], rtol=0, atol=1e-12)
        for model, cols in MODELS.items():
            a, b = predict((model, train_x[cols].to_numpy(), test_x[cols].to_numpy(), train.net_return.to_numpy()))
            threshold = float(np.quantile(a, .75))
            key = model.replace("-", "_")
            np.testing.assert_allclose(b, test[f"prediction_{key}"], rtol=0, atol=1e-11)
            assert abs(threshold - split["thresholds"][model]) < 1e-11
            assert np.array_equal(b >= threshold, test[f"selected_{key}"])
            fits += 1
        for event, (a, b, _) in event_masks(test, *q).items():
            assert np.array_equal(a, test[f"event_{event.replace('-', '_')}"].to_numpy(dtype=bool))
            assert np.array_equal(b, test[f"control_{event.replace('-', '_')}"].to_numpy(dtype=bool))
    require("all96_model_predictions_and_selection_thresholds", fits == 96)
    require("nonfills_zero_never_filtered_from_universe", predictions.loc[~predictions.entry_filled, "net_return"].eq(0).all())
    for record in result["comparisons"]:
        p = predictions.loc[predictions.horizon.eq(record["horizon"])].reset_index(drop=True)
        if record["kind"] == "model":
            a = p[f"selected_{record['component']}"]
            base = "tree_base" if record["component"].startswith("tree") else "ridge_base"
            b = np.ones(len(p), dtype=bool) if record["comparator"] == "all" else p[f"selected_{base}"]
            actual = float((p.net_return * (a.astype(float) - np.asarray(b, dtype=float))).mean())
        else:
            pieces = []
            key = record["component"].replace("-", "_")
            for _, g in p.groupby("year"):
                a, b = g[f"event_{key}"].eq(1), g[f"control_{key}"].eq(1)
                if not a.any() or not b.any():
                    continue
                y = g.net_return if record["comparator"] == "raw" else g.net_return - g.prediction_ridge_base
                sign = -1 if key == "gap_up_fade" else 1
                pieces.append((sign * (y.loc[a].mean() - y.loc[b].mean()), int((a | b).sum())))
            actual = sum(v * n for v, n in pieces) / sum(n for _, n in pieces) if pieces else None
        assert (actual is None and record["difference"] is None) or abs(actual - record["difference"]) < 1e-11
    checks.append("all88_primary_point_estimates_and_event_weighting")
    follow = json.loads((EXPERIMENT / "others/followup_result.json").read_text(encoding="utf-8"))
    for record in follow["comparisons"]:
        frame = predictions.loc[predictions.horizon.eq(record["horizon"])]
        j = ["A-C", "interaction", "A-all", "A-B"].index(record["comparison"])
        value, without, count = 0., 0., 0
        for year, part in frame.groupby("year"):
            y = part.net_return.to_numpy()
            if record["mode"] == "residual":
                y = y - part.prediction_ridge_base.to_numpy()
            effects, _ = contrasts(part, y)
            value += effects[j] * len(part) / len(frame)
            if year != 2026:
                without += effects[j] * len(part)
                count += len(part)
        assert abs(value - record["difference"]) < 1e-11
        assert abs(without / count - record["without2026"]) < 1e-11
    checks.append("all16_followup_cell_effects_and_without2026")
    cells = pd.read_csv(EXPERIMENT / "others/followup_cells.csv")
    require("four_cells_partition_eligible_sessions", all(cells.loc[cells.horizon.eq(h) & cells.year.eq(y), "n"].sum() == len(g)
        for (h, y), g in predictions.loc[predictions.horizon.isin([1, 3])].groupby(["horizon", "year"])))
    matches = pd.read_csv(RUN / "matched_controls.csv")
    require("matched_distance_limit_and_outcome_identity", matches.distance.le(1).all() and
        np.allclose(matches.net_A - matches.net_C, matches.difference, rtol=0, atol=1e-12))
    for record in matches.to_dict("records"):
        p = predictions.loc[predictions.horizon.eq(record["horizon"]) & predictions.year.eq(record["year"])].set_index("signal")
        a, c = p.loc[record["signal_A"]], p.loc[record["signal_C"]]
        assert a.gap < 0 and a.intraday > 0 and c.gap >= 0 and c.intraday > 0
        assert abs(a.net_return - record["net_A"]) < 1e-12 and abs(c.net_return - record["net_C"]) < 1e-12
    checks.append("all226_matched_pairs_membership_and_real_net_outcomes")
    cash = pd.read_csv(RUN / "cash_attribution.csv")
    require("all1780_cash_attribution_identities", len(cash) == 1780 and np.allclose(cash.first_holding_day_price_effect + cash.later_price_effect - cash.fees, cash.actual_net, rtol=0, atol=1e-11))
    constant = np.ones(8)
    mask = np.array([True] * 4 + [False] * 4)
    synthetic = compare(([(2023, np.arange(8), constant, mask, ~mask)], "conditional", 1., 13))
    require("bootstrap_constant_conditional_zero", synthetic["difference"] == 0 and synthetic["interval95"] == [0., 0.])
    absent = compare(([(2023, np.arange(8), constant, np.zeros(8, bool), mask)], "conditional", 1., 13))
    require("bootstrap_no_events_stays_missing", absent["difference"] is None and absent["status"] == "NO_BOTH_GROUPS")
    require("source_and_account_counts_zero", result["new_source_calls"] == follow["source_calls"] == result["strategy_accounts"] == follow["strategy_accounts"] == 0)
    paths = [*RUN.glob("*.csv"), *[EXPERIMENT / "others" / f for f in ("annual.csv", "computation_result.json", "followup_cells.csv", "followup_result.json")]]
    manifest = [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p.read_bytes()).hexdigest()} for p in paths]
    report = {"status": "PASS", "checks": checks, "model_recomputations": fits, "entry_replications": len(original_entries),
        "exit_replications": exits, "cash_identities": len(cash), "matched_pairs": len(matches),
        "analysis_pairs_with_later_control_origin": int(matches.signal_C.gt(matches.signal_A).sum()),
        "manifest": manifest, "limitation": "Audit validates calculations and timing of signals, not economic validity; matched future controls are explanatory only and excluded from features."}
    (EXPERIMENT / "others/audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ("manifest", "checks")}, ensure_ascii=False))
    print('AUDIT_CHECKS',len(checks))


if __name__ == "__main__":
    main()
