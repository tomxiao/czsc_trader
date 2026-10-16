"""State and coverage diagnosis, and fixed role-specific mechanism tests."""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from io import BytesIO
from multiprocessing import get_context
from pathlib import Path
from uuid import UUID
import json
import time

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef
from czsc_trader.application import RepositoryContext, create_research_context, validate_delivery
from czsc_trader.research_tools import ResearchBatchRef, DeliveryReference, EvidenceRef, EvaluationResources, ValidationStatus
from methods import fitted_scores, rolling_threshold, extended_features, association, mean_or_none, bootstrap_pair, precheck

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX005_20261016/first"


def fetch_inputs(context, prior):
    ref = EvidenceRef.from_dict(prior["evidence"]["input-readiness"])
    ready = json.loads(ref.resolve(ROOT).read_text(encoding="utf-8"))
    inputs = {}
    for record in ready["records"]:
        request, reference = record["request"], record["reference"]
        bound = PreparedDataRef(UUID(reference["space_id"]), UUID(reference["preparation_id"]), reference["manifest_sha256"])
        fetched = context.data.fetch(DataRequest(Dataset(request["dataset"]), request["symbol"], request["start"], request["end"], request["required_cutoff"]), prepared=bound)
        if not fetched.ready or fetched.identity.content_sha256 != record["content_sha256"]:
            raise RuntimeError("Pinned native input failed or changed")
        inputs[request["dataset"]] = fetched.dataframe.sort_values("Date").reset_index(drop=True)
    dates = pd.DatetimeIndex(pd.to_datetime(inputs["stock.ohlcv"].Date))
    for name in ("stock.unadjusted_daily", "security.price_limits", "security.trading_status"):
        if not dates.equals(pd.DatetimeIndex(pd.to_datetime(inputs[name].Date))):
            raise RuntimeError("Input dates differ")
    if not inputs["security.trading_status"].Status.eq("TRADING").all():
        raise RuntimeError("Unexpected halt requires a separately declared label calendar")
    return inputs, dates


def read_frame(prior, name):
    ref = EvidenceRef.from_dict(prior["evidence"][name])
    return pd.read_csv(BytesIO(ref.resolve(ROOT).read_bytes()))


def old_model_diagnosis(pool, features, extended, labels, old, design, dates):
    base = design["features"]["baseline"]
    models = {"return-base": ("net_return", base), "reversal": ("net_return", base + design["features"]["reversal"]),
              "tree-risk-base": ("adverse", base), "tree-risk": ("adverse", base + design["features"]["risk"])}
    tasks, forecasts, drifts, states, ranks = [], [], [], [], []
    for horizon in (3, 5):
        eligible = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0)]
        for year in (2023, 2024, 2025, 2026):
            first = int(np.flatnonzero(dates.year == year)[0])
            train = eligible.loc[eligible.maturity.lt(first)]
            test = eligible.loc[pd.to_datetime(eligible.signal_date).dt.year.eq(year)]
            if not train.maturity.lt(first).all():
                raise AssertionError("Training label leak")
            for name, (target, columns) in models.items():
                task = (name, features.loc[train.signal, columns].to_numpy(), features[columns].to_numpy(), train[target].to_numpy())
                tasks.append((horizon, year, name, target, train, test, pool.submit(fitted_scores, task)))
    for horizon, year, name, target, train, test, future in tasks:
        train_scores, scores = future.result()
        saved = old.loc[old.model.eq(name) & old.horizon.eq(horizon) & old.year.eq(year)].sort_values("signal")
        if not np.array_equal(saved.signal, test.signal):
            raise AssertionError("Replication samples differ")
        np.testing.assert_allclose(scores[test.signal], saved.prediction, atol=1e-10, rtol=0)
        q = .25 if target == "adverse" else .75
        fixed = float(np.quantile(train_scores, q))
        adaptive = rolling_threshold(scores, q)[test.signal]
        if not np.isfinite(adaptive).all():
            raise AssertionError("Missing strict-past calibration history")
        selected = scores[test.signal] <= fixed if target == "adverse" else scores[test.signal] >= fixed
        np.testing.assert_array_equal(selected, saved.selected)
        vol_median = float(extended.loc[train.signal, "std20"].median())
        state = np.where(extended.loc[test.signal, "ret_20"].to_numpy() >= 0, "UP", "DOWN")
        state = np.char.add(np.char.add(state, "_"), np.where(extended.loc[test.signal, "std20"].to_numpy() > vol_median, "HIGHVOL", "LOWVOL"))
        output = test.copy()
        output = output.assign(model=name, year=year, prediction=scores[test.signal], threshold=fixed,
                               selected=selected, rolling_threshold=adaptive,
                               rolling_selected=scores[test.signal] <= adaptive if target == "adverse" else scores[test.signal] >= adaptive,
                               state=state, train_rows=len(train), train_last_maturity=int(train.maturity.max()),
                               first_test_signal=int(np.flatnonzero(dates.year == year)[0]))
        forecasts.append(output)
        ranks.append({"model": name, "horizon": horizon, "year": year, "target": target,
                      "score_target_spearman": association(output.prediction, output[target]),
                      "selected": int(output.selected.sum()), "rolling_selected": int(output.rolling_selected.sum())})
        for column in ("ret_20", "std20", "range_1"):
            training, testing = extended.loc[train.signal, column], extended.loc[test.signal, column]
            drifts.append({"model": name, "horizon": horizon, "year": year, "feature": column,
                           "train_median": float(training.median()), "test_median": float(testing.median()),
                           "outside_train_q10_q90": float(((testing < training.quantile(.1)) | (testing > training.quantile(.9))).mean())})
        drifts.append({"model": name, "horizon": horizon, "year": year, "feature": "model_score",
                       "train_median": float(np.median(train_scores)), "test_median": float(np.median(output.prediction)),
                       "outside_train_q10_q90": float(((output.prediction < np.quantile(train_scores, .1)) | (output.prediction > np.quantile(train_scores, .9))).mean())})
        for state_name, part in output.groupby("state"):
            for mode, chosen in (("fixed", part.selected), ("rolling", part.rolling_selected)):
                picked = part.loc[chosen]
                states.append({"model": name, "horizon": horizon, "year": year, "state": state_name, "mode": mode,
                    "dates": len(part), "selected": len(picked), "mean_return": mean_or_none(picked.net_return),
                    "mean_adverse": mean_or_none(picked.adverse), "all_mean_return": float(part.net_return.mean()),
                    "all_mean_adverse": float(part.adverse.mean()), "fill_rate": mean_or_none(picked.entry_filled)})
    return pd.concat(forecasts, ignore_index=True), pd.DataFrame(drifts), pd.DataFrame(states), pd.DataFrame(ranks)


def describe_pair(name, horizon, year, part, chosen, control, target):
    first, second = part.loc[chosen], part.loc[control]
    risk = target == "adverse"
    difference = ((-1 if risk else 1) * (first[target].mean() - second[target].mean())) if len(first) and len(second) else None
    # Remove the largest positive contribution of the chosen rule, holding both masks fixed.
    values = part[target].to_numpy() * (-1 if risk else 1)
    concentration = None
    if chosen.any() and control.any():
        contribution = values * (chosen / chosen.mean() - control / control.mean())
        positive = contribution[contribution > 0]
        concentration = float(np.max(positive) / positive.sum()) if len(positive) else None
    row = {"comparison": name, "horizon": horizon, "year": year, "dates": len(part),
        "selected": len(first), "control_selected": len(second), "difference": float(difference) if difference is not None else None,
        "selected_mean_return": mean_or_none(first.net_return), "control_mean_return": mean_or_none(second.net_return),
        "selected_mean_adverse": mean_or_none(first.adverse), "control_mean_adverse": mean_or_none(second.adverse),
        "selected_fill_rate": mean_or_none(first.entry_filled), "control_fill_rate": mean_or_none(second.entry_filled),
        "selected_filled_adverse": mean_or_none(first.loc[first.entry_filled, "adverse"]),
        "control_filled_adverse": mean_or_none(second.loc[second.entry_filled, "adverse"]),
        "selected_gap": mean_or_none(first.gap_next_open) if "gap_next_open" in first else None,
        "control_gap": mean_or_none(second.gap_next_open) if "gap_next_open" in second else None,
        "largest_positive_contribution_share": concentration}
    removal = []
    for k in range(1, 4):
        if chosen.sum() > k and control.any():
            positions = np.argsort(np.where(chosen, values, -np.inf))[-k:]
            keep = np.ones(len(part), dtype=bool)
            keep[positions] = False
            if (control & keep).any():
                removal.append(float(values[chosen & keep].mean() - values[control & keep].mean()))
            else:
                removal.append(None)
        else:
            removal.append(None)
    row.update({f"remove_top_{index + 1}": value for index, value in enumerate(removal)})
    return row


def comparisons(pool, forecasts, extended, labels, dates):
    definitions, annual, observations, pending, conditional = [], [], [], [], []
    for horizon in (3, 5):
        for family, target, baseline in (("reversal", "net_return", "return-base"), ("tree-risk", "adverse", "tree-risk-base")):
            for mode, column in (("fixed", "selected"), ("rolling", "rolling_selected")):
                groups = []
                name = f"{mode}-{family}"
                for year in (2023, 2024, 2025, 2026):
                    a = forecasts.loc[forecasts.model.eq(family) & forecasts.horizon.eq(horizon) & forecasts.year.eq(year)].set_index("signal")
                    b = forecasts.loc[forecasts.model.eq(baseline) & forecasts.horizon.eq(horizon) & forecasts.year.eq(year)].set_index("signal")
                    if not a.index.equals(b.index):
                        raise AssertionError("Different pair samples")
                    chosen, control = a[column].to_numpy(), b[column].to_numpy()
                    annual.append(describe_pair(name, horizon, year, a, chosen, control, target))
                    groups.append((year, a[target].to_numpy() * (-1 if target == "adverse" else 1), chosen, control))
                definitions.append((name, horizon, groups))
    for horizon in (3, 5, 10):
        for name in ("pullback_turn", "breakout_volume", "shock_close", "risk_scale"):
            groups = []
            target = "adverse" if name == "risk_scale" else "net_return"
            eligible = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0) & labels.signal.ge(60)]
            for year in (2023, 2024, 2025, 2026):
                first = int(np.flatnonzero(dates.year == year)[0])
                train = eligible.loc[eligible.maturity.lt(first)]
                test = eligible.loc[pd.to_datetime(eligible.signal_date).dt.year.eq(year)].copy()
                frame = extended.loc[test.signal]
                if name == "pullback_turn":
                    control = (frame.above_ma60 & frame.ret_5.lt(0)).to_numpy()
                    chosen = control & frame.ret_1.gt(0).to_numpy()
                elif name == "breakout_volume":
                    control = frame.breakout20.to_numpy()
                    chosen = control & frame.volume_confirmation.to_numpy()
                elif name == "shock_close":
                    threshold = float(extended.loc[train.signal, "ret_1"].quantile(.1))
                    control = frame.ret_1.le(threshold).to_numpy()
                    chosen = control & frame.close_location.ge(.5).to_numpy()
                else:
                    vol = extended.std20.shift(1).rolling(252, min_periods=252).quantile(.25)
                    spread = extended.range_1.shift(1).rolling(252, min_periods=252).quantile(.25)
                    if not vol.loc[test.signal].notna().all() or not spread.loc[test.signal].notna().all():
                        raise AssertionError("Missing risk-scale calibration history")
                    chosen = frame.std20.le(vol.loc[test.signal]).to_numpy()
                    control = frame.range_1.le(spread.loc[test.signal]).to_numpy()
                    boundaries = extended.loc[train.signal, "range_1"].quantile([.25, .5, .75]).to_numpy()
                    bins = np.searchsorted(boundaries, frame.range_1.to_numpy(), side="right")
                    for index in range(4):
                        where = bins == index
                        conditional.append({"year": year, "horizon": horizon, "range_bin": index, "count": int(where.sum()),
                            "std_adverse_spearman": association(frame.std20.to_numpy()[where], test.adverse.to_numpy()[where]),
                            "std_return_spearman": association(frame.std20.to_numpy()[where], test.net_return.to_numpy()[where])})
                test["gap_next_open"] = frame.gap_next_open.to_numpy()
                annual.append(describe_pair(name, horizon, year, test, chosen, control, target))
                groups.append((year, test[target].to_numpy() * (-1 if target == "adverse" else 1), chosen, control))
                observations.append(test.assign(comparison=name, selected=chosen, control_selected=control))
            definitions.append((name, horizon, groups))
    if len(definitions) != 20:
        raise AssertionError("Undeclared comparison count")
    for index, (name, horizon, groups) in enumerate(definitions):
        pending.append((name, horizon, pool.submit(bootstrap_pair, (groups, 13 + index, 20))))
    aggregate = []
    for name, horizon, future in pending:
        result = future.result()
        result.update(comparison=name, horizon=horizon)
        aggregate.append(result)
    return pd.DataFrame(annual), aggregate, pd.concat(observations, ignore_index=True), pd.DataFrame(conditional)


def main():
    started = time.monotonic()
    if (RUN / "result.json").exists():
        raise RuntimeError("Completed output exists; use an explicit new run for a correction")
    published = json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8"))
    for key, path in (("design", EXPERIMENT / "protocols/design.json"), ("methods", EXPERIMENT / "src/methods.py"), ("study", Path(__file__))):
        reference = EvidenceRef.from_dict(published[key])
        reference.resolve(ROOT)
        if sha256(path.read_bytes()).hexdigest() != reference.sha256:
            raise RuntimeError("Design or program changed after preregistration")
    prior = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    repository = RepositoryContext.discover(ROOT)
    if validate_delivery(repository, DeliveryReference.from_dict(prior["delivery"])).status is not ValidationStatus.PASS:
        raise RuntimeError("Prior delivery changed")
    context = create_research_context(repository, ResearchBatchRef("S014"), resources=EvaluationResources(2, 1, 13))
    original_request = requests.sessions.Session.request

    def prohibit_network(*args, **kwargs):
        raise RuntimeError("This component experiment is authorized for asset reuse only")

    requests.sessions.Session.request = prohibit_network
    try:
        inputs, dates = fetch_inputs(context, prior)
    finally:
        requests.sessions.Session.request = original_request
    features = read_frame(prior, "features").set_index("signal")
    labels = read_frame(prior, "labels")
    old = read_frame(prior, "followup-predictions")
    old_design = json.loads(EvidenceRef.from_dict(prior["evidence"]["protocol"]).resolve(ROOT).read_text(encoding="utf-8"))
    extended = extended_features(inputs["stock.ohlcv"])
    RUN.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        checked = precheck(pool)
        print("PRECHECK=PASS", flush=True)
        forecasts, drifts, states, ranks = old_model_diagnosis(pool, features, extended, labels, old, old_design, dates)
        print("REPLICATED_FITS=32 MATCHED_PRIOR_PREDICTIONS", flush=True)
        annual, aggregate, observations, conditional = comparisons(pool, forecasts, extended, labels, dates)
    for name, frame in (("features", extended.assign(signal_date=dates)), ("forecasts", forecasts), ("drifts", drifts),
                        ("states", states), ("ranks", ranks), ("annual", annual), ("observations", observations), ("conditional", conditional)):
        frame.to_csv(RUN / f"{name}.csv", index_label="row")
    result = {"status": "COMPUTED", "comparisons": aggregate, "precheck": checked, "model_fits": 32,
        "fit_scope": "Replications of prior fixed fits, not 32 new searched configurations", "primary_comparisons": 20,
        "new_source_calls": 0, "strategy_accounts": 0, "parameter_searches": 0, "workers": 2, "native_threads_per_worker": 1,
        "seconds": time.monotonic() - started,
        "causality": "All 32 model test predictions replicated within 1e-10; actual training maturity precedes year; score recalibration uses strictly prior63",
        "selection_history": "Adaptive development study after EX004; no independent holdout; evidence-role judgment remains distinct from economic acceptance"}
    if result["seconds"] > 7200:
        raise RuntimeError("Resource budget exceeded")
    for path in (RUN / "result.json", EXPERIMENT / "others/computation_result.json"):
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
