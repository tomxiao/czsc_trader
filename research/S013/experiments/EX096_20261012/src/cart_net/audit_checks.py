"""Synthetic-only independent CART/CDF/causal-year audit tests."""

from __future__ import annotations

import copy
from dataclasses import replace
import importlib
import json
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

import audit_tree as audit
import tree_kernel as primary


def annual_fixture():
    axis = pd.bdate_range("2020-01-02", "2022-02-28")
    rng = np.random.default_rng(97)
    x = rng.integers(0, 5, (len(axis), 14)).astype(float)
    features = pd.DataFrame(x, index=axis, columns=audit.FEATURES)
    truth = np.where((x[:, 0] > 2) & (x[:, 1] > 2), .03, -.01)
    ends = pd.Series(axis + pd.offsets.BDay(5), index=axis)
    truth[-4:] = np.nan
    ends.iloc[-4:] = pd.NaT
    labels = pd.DataFrame({"return_4": truth, "label_end_return_4": ends}, index=axis)
    return features, labels


def run():
    checks, refused, certs = [], [], []
    blocks = np.repeat([[0., 0.], [0., 1.], [1., 0.], [1., 1.]], 80, axis=0)
    x = np.zeros((320, 14))
    x[:, :2] = blocks
    y = np.where((blocks[:, 0] > 0) & (blocks[:, 1] > 0), .03, -.01)
    tree = primary.fit_tree(x, y)
    independent = audit.fit_scalar(x, y)
    audit.compare_tree(independent, tree)
    np.testing.assert_allclose(primary.predict_tree(tree, x), y, rtol=0, atol=1e-14)
    assert tree["feature_index"] == 0 and tree["quantile"] == .25
    checks.append("AND interaction fits depth2 with full independent node/candidate audit and first feature/quantile tie")
    xor_y = np.where(blocks[:, 0] != blocks[:, 1], .02, -.02)
    xor_tree = primary.fit_tree(x, xor_y)
    audit.compare_tree(audit.fit_scalar(x, xor_y), xor_tree)
    assert xor_tree["leaf"] and xor_tree["reason"] == "NO_STRICT_SSE_IMPROVEMENT"
    checks.append("symmetric XOR no root SSE gain stays leaf; no hidden depth2 lookahead")
    equal_y = np.full(320, .0123)
    constant_tree = primary.fit_tree(x, equal_y)
    audit.compare_tree(audit.fit_scalar(x, equal_y), constant_tree)
    assert constant_tree["leaf"]
    for size in (40, 79, 80):
        tx = np.zeros((size, 14))
        tx[:, 0] = np.arange(size)
        ty = np.r_[np.full(size//2, -.01), np.full(size-size//2, .03)]
        fitted = primary.fit_tree(tx, ty)
        audit.compare_tree(audit.fit_scalar(tx, ty), fitted)
        assert fitted["leaf"] == (size < 80)
    checks.append("constant labels strict no improvement and minleaf40 boundary40/79/80")
    ordered = [-1., -1., 0., 2.]
    for value in (-3., -1., -.5, 0., 1., 2., 4.):
        expected = audit.cdf(ordered, value)
        reported = primary.ranks(np.asarray(ordered), np.asarray([value]))[0]
        assert expected == reported
    checks.append("training-only midpoint CDF duplicate ties and out-of-range values")
    features, labels = annual_fixture()
    scores, trace = primary.forecasts(features, labels)
    certs.append(audit.verify(features, labels, scores, trace))
    assert scores.loc[features.index.year == 2020].isna().all().all()
    assert scores.iloc[-4:].notna().all().all()
    assert len(trace) == 6 and all(t["reason"] == "NO_YEAR" for t in trace[2:])
    first = trace[0]
    assert all(pd.Timestamp(labels.label_end_return_4.iloc[i]) < pd.Timestamp(first["first_test"]) for i in first["train_positions"])
    checks.append("causal yearly support with strict label maturity;2020 no predictions; current missing future truth still forecast")
    future_labels = labels.copy()
    future_labels.loc[features.index.year >= 2021, "return_4"] *= -2
    changed_scores, changed_trace = primary.forecasts(features, future_labels)
    certs.append(audit.verify(features, future_labels, changed_scores, changed_trace))
    pd.testing.assert_frame_equal(changed_scores.loc[features.index.year == 2021], scores.loc[features.index.year == 2021])
    future_features = features.copy()
    future_features.iloc[-10:] += 100
    feature_scores, feature_trace = primary.forecasts(future_features, labels)
    certs.append(audit.verify(future_features, labels, feature_scores, feature_trace))
    pd.testing.assert_frame_equal(feature_scores.iloc[:-10], scores.iloc[:-10])
    for end in (pd.Timestamp("2021-01-04"), pd.Timestamp("2021-12-31"), features.index[-1]):
        chosen = features.index <= end
        pf, pl = features.loc[chosen], labels.loc[chosen]
        ps, pt = primary.forecasts(pf, pl)
        certs.append(audit.verify(pf, pl, ps, pt))
        pd.testing.assert_frame_equal(ps, scores.loc[chosen])
    checks.append("test-year future truth cannot fit same-year tree; future features and full prefixes invariant")
    missing = features.copy()
    missing.loc[missing.index.year == 2021] = np.nan
    ms, mt = primary.forecasts(missing, labels)
    certs.append(audit.verify(missing, labels, ms, mt))
    assert ms.loc[missing.index.year == 2021].isna().all().all()
    assert mt[0]["train_n"] >= 40 and mt[0]["tree"] is not None
    short = features.copy()
    old = short.index[short.index.year == 2020]
    short.loc[old[39:]] = np.nan
    ss, st = primary.forecasts(short, labels)
    certs.append(audit.verify(short, labels, ss, st))
    assert st[0]["train_n"] < 40 and st[0]["tree"] is None
    checks.append("feature-only test support; zero test rows cannot suppress training; insufficient past training no fallback")
    bounds = labels.copy()
    first2021 = features.index[features.index.year == 2021][0]
    last2020 = features.index[features.index.year == 2020][-1]
    bounds.loc[last2020, "label_end_return_4"] = first2021
    bs, bt = primary.forecasts(features, bounds)
    certs.append(audit.verify(features, bounds, bs, bt))
    assert features.index.get_loc(last2020) not in bt[0]["train_positions"]
    checks.append("maturity equal first T excluded; full-window train positions independently verified")
    for depth, leaf in ((1, 20), (1, 120), (4, 20), (4, 120), (2, 40)):
        fitted = primary.fit_tree(x, y, max_depth=depth, minimum_leaf=leaf)
        audit.compare_tree(audit.fit_scalar(x, y, max_depth=depth, minimum_leaf=leaf), fitted)
        ds, dt = primary.forecasts(features, labels, max_depth=depth, minimum_leaf=leaf)
        certs.append(audit.verify(features, labels, ds, dt, max_depth=depth, minimum_leaf=leaf))
        if (depth, leaf) == (2, 40):
            pd.testing.assert_frame_equal(ds, scores, check_exact=True)
            assert dt == trace
    for size, leaf, allowed in ((39, 20, False), (40, 20, True), (119, 120, False), (120, 120, True)):
        tx = np.zeros((size, 14))
        ty = np.full(size, .01)
        if allowed:
            audit.compare_tree(audit.fit_scalar(tx, ty, minimum_leaf=leaf), primary.fit_tree(tx, ty, minimum_leaf=leaf))
        else:
            for fitter in (audit.fit_scalar, primary.fit_tree):
                try:
                    fitter(tx, ty, minimum_leaf=leaf)
                except ValueError:
                    refused.append("training_basic_support_"+str(size)+"_"+str(leaf))
                else:
                    raise AssertionError("basic training40 or leaf support lowered")
    for depth, leaf in ((0, 40), (5, 40), (2., 40), (True, 40), (2, 19), (2, 121), (2, 40.)):
        try:
            audit.fit_scalar(x, y, max_depth=depth, minimum_leaf=leaf)
        except ValueError:
            refused.append("illegal_depth_leaf_"+str(depth)+"_"+str(leaf))
        else:
            raise AssertionError("illegal hyperparameters accepted")
    checks.append("full depth1..4/leaf20..120 legal endpoints; center exact; train max40-and-leaf fixed support")
    package = "cart_independent_synthetic_native"
    for name, folder in ((package, Path(__file__).parent / "strategy_runtime"),
                         (package+".strategies", Path(__file__).parent / "strategy_runtime/strategies")):
        obj = types.ModuleType(name)
        obj.__path__ = [str(folder)]
        sys.modules[name] = obj
    adapter = importlib.import_module(package+".strategies.cart_net")
    parent = importlib.import_module(package+".strategies.confirm_net")
    native_core = importlib.import_module(package+".strategies.confirm_kernel")
    p = {"confirmation_lookback": 120, "holding_sessions": 4, "tree_depth": 2, "minimum_leaf": 40}
    native = adapter.CartNet(ParameterSet(p))
    old = parent.ConfirmNet(ParameterSet({"confirmation_lookback": 120, "holding_sessions": 4, "ridge_alpha": 10.}))
    assert replace(native.definition, parameters=old.definition.parameters) == old.definition
    assert adapter.CartNet.derive_calculation_scope is parent.ConfirmNet.derive_calculation_scope
    runtime_source = Path(__file__).parent / "strategy_runtime/strategies/tree_kernel.py"
    assert runtime_source.read_bytes() == (Path(__file__).parent / "tree_kernel.py").read_bytes()
    prices = pd.DataFrame({"Open": 100+np.arange(len(features))*.02,
                           "Close": 100+np.arange(len(features))*.02}, index=features.index)
    for holding in (1, 4, 60):
        hp = dict(p, holding_sessions=holding)
        history, lab, nets, proof = adapter.history_from_model(features, prices, features.index, hp)
        for i in range(len(features)):
            end = i+holding+1
            if end >= len(features):
                assert pd.isna(lab.return_4.iloc[i]) and pd.isna(lab.label_end_return_4.iloc[i])
            else:
                expected = float(prices.Open.iloc[end]/prices.Open.iloc[i+1]*(.999/1.001)-1)
                assert lab.return_4.iloc[i] == expected and lab.label_end_return_4.iloc[i] == features.index[end]
        certs.append(audit.verify(features, lab, nets, proof))
        expected_history = native_core.episode_history(nets.cart_net, features.index, holding)
        pd.testing.assert_frame_equal(history.loc[:, expected_history.columns], expected_history, check_exact=True)
    checks.append("runtime tree byteexact; inherited input/scope/execution identity; H1/4/60 labels and native0/1 episode policy exact")
    for name, tx, ty in (("thin_train", x[:39], y[:39]), ("wrong_feature_count", x[:, :13], y),
                         ("target_shape", x, y[:-1]), ("nonfinite_features", x+np.nan, y),
                         ("nonfinite_target", x, y+np.nan)):
        try:
            audit.fit_scalar(tx, ty)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("invalid fit accepted " + name)
    invalids = []
    bad = features.copy()
    bad.iloc[0, 0] = np.inf
    invalids.append(("feature_inf", bad, labels, scores, trace))
    bad = labels.copy()
    bad.iloc[-1, 0] = .1
    invalids.append(("truth_maturity_unpaired", features, bad, scores, trace))
    bad = labels.copy()
    bad.iloc[0, 1] = features.index[0]
    invalids.append(("nonfuture_maturity", features, bad, scores, trace))
    bad = scores.copy()
    bad.iloc[-1, 1] = np.nan
    invalids.append(("missing_tail_forecast", features, labels, bad, trace))
    bad = scores.copy()
    bad.iloc[300, 1] += .01
    invalids.append(("false_forecast", features, labels, bad, trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["train_positions"] += [features.index.get_loc(first2021)]
    invalids.append(("future_train_position", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["train_cdfs"][0][0] += .1
    invalids.append(("false_training_cdf", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["tree"]["mean"] += .01
    invalids.append(("false_tree_mean", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["tree"]["candidates"][0]["threshold"] += .01
    invalids.append(("false_candidate_threshold", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["tree"]["candidates"][0]["split_sse"] += .01
    invalids.append(("false_candidate_SSE", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["future_test_count_gate"] = True
    invalids.append(("future_test_count_gate", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(trace)
    bad_trace[0]["tree"]["left"]["positions"].append(9999)
    invalids.append(("false_child_positions", features, labels, scores, bad_trace))
    invalids.append(("missing_label_field", features, labels.drop(columns="return_4"), scores, trace))
    invalids.append(("missing_score_field", features, labels, scores.drop(columns="cart_net"), trace))
    invalids.append(("unordered_axis", features.iloc[::-1], labels.iloc[::-1], scores.iloc[::-1], trace))
    bad = features.copy()
    bad.index = bad.index.insert(1, bad.index[0])[:len(bad)]
    invalids.append(("duplicate_axis", bad, labels, scores, trace))
    bad = features.copy()
    bad.index = bad.index.tz_localize("Asia/Shanghai")
    invalids.append(("timezone_axis", bad, labels, scores, trace))
    for name, fs, ls, sc, tr in invalids:
        try:
            audit.verify(fs, ls, sc, tr)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("invalid forecast trace accepted " + name)
    checks.append("training/CDF/tree/SSE-candidate/prediction/maturity corruption and invalid arrays rejected")
    return {"status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
            "accounts": 0, "experiments_allocated": 0, "new_statistics": 0,
            "checks": checks, "rejections": refused, "certificates": certs,
            "check_count": len(checks), "rejection_count": len(refused)}


if __name__ == "__main__":
    result = run()
    Path(__file__).with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "check_count", "rejection_count")}, ensure_ascii=False))
