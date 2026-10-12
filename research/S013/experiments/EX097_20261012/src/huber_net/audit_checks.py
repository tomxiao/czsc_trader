"""Synthetic-only independent Huber optimum/provenance audit checks."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_huber as audit
import huber_kernel as primary


def annual_fixture():
    rng = np.random.default_rng(101)
    dates = pd.DatetimeIndex([
        day for year in range(2020, 2027)
        for day in pd.bdate_range(str(year)+"-01-02", periods=90 if year == 2020 else 60)
    ])
    features = pd.DataFrame(rng.normal(0, 1, (len(dates), 14)), index=dates, columns=audit.FEATURES)
    target = .004+.003*features.iloc[:, 0].to_numpy()+rng.normal(0, .008, len(dates))
    ends = pd.Series(dates, index=dates).shift(-5)
    target[-5:] = np.nan
    return features, pd.DataFrame({"return_4": target, "label_end_return_4": ends}, index=dates)


def run():
    checks, refused, certs, fits = [], [], [], []
    rng = np.random.default_rng(103)
    x = rng.uniform(-.5, .5, (400, 14))
    target = .01+.004*x[:, 0]
    query = x[:25]
    pred, proof = primary.fit(x, target, query)
    fits.append(audit.verify_fit(x, target, query, pred, proof))
    design = np.column_stack((np.ones(len(x)), x))
    beta = np.linalg.solve(design.T@design+np.diag(np.r_[0., np.full(14, 10.)]), design.T@target)
    assert np.max(np.abs(target-design@beta)) <= proof["delta"]
    np.testing.assert_allclose(proof["coefficients"], beta, rtol=0, atol=2e-12)
    checks.append("all-inlier Huber equals slope-penalized OLS with unpenalized intercept")
    shocks = target.copy()
    shocks[[4, 51, 205]] += .8
    robust, shockproof = primary.fit(x, shocks, query)
    fits.append(audit.verify_fit(x, shocks, query, robust, shockproof))
    shock_ols = np.linalg.solve(design.T@design+np.diag(np.r_[0., np.full(14, 10.)]), design.T@shocks)
    assert np.linalg.norm(np.asarray(shockproof["coefficients"])-beta) < np.linalg.norm(shock_ols-beta)
    assert shockproof["training_n"] == len(shocks) and not shockproof["targets_clipped"]
    checks.append("few shocks lower coefficient influence while every target remains in loss")
    for values, label in ((np.full(400, .013), "positive_constant"),
                          (np.full(400, -.013), "negative_constant"),
                          (np.zeros(400), "zero_constant"),
                          (np.r_[np.zeros(360), np.full(40, .03)], "varied_zero_MAD")):
        prediction, fitted = primary.fit(x, values, query)
        fits.append(audit.verify_fit(x, values, query, prediction, fitted))
        if label == "varied_zero_MAD":
            assert np.isnan(prediction).all() and fitted["coefficients"] is None
        else:
            assert fitted["coefficients"] == [float(values[0])]+[0.]*14
        checks.append(label+" explicit definition/unavailability without epsilon or OLS fallback")
    plateau_x = np.zeros((40, 14))
    plateau_y = np.r_[np.full(20, -1.), np.full(20, 1.)]
    plateau_pred, plateau = primary.fit(plateau_x, plateau_y, plateau_x[:2], huber_multiple=.5)
    fits.append(audit.verify_fit(plateau_x, plateau_y, plateau_x[:2], plateau_pred, plateau, huber_multiple=.5))
    loss0, grad0 = audit.objective_gradient(plateau_x, plateau_y, [0.]+[0.]*14, plateau["delta"], 10.)
    loss1, grad1 = audit.objective_gradient(plateau_x, plateau_y, [.2]+[0.]*14, plateau["delta"], 10.)
    assert loss0 == loss1 and max(abs(v) for v in grad0+grad1) == 0
    checks.append("intercept plateau demonstrates optimum not necessarily unique; fixed-source runtime equality separate")
    for alpha, multiple in ((1., .5), (1., 3.), (100., .5), (100., 3.)):
        pp, fit = primary.fit(x, target, query, alpha, multiple)
        fits.append(audit.verify_fit(x, target, query, pp, fit, alpha, multiple))
    checks.append("alpha1..100 and Huber multiple.5..3 full float-domain endpoints")
    # Fault injection forces the true-gradient stopping guard to fail for exactly
    # 500 pure iterations. It is a refusal-path test, not a natural-data result.
    original = primary.objective_gradient
    calls = [0]

    def never_stationary(design, target, coefficients, delta, ridge_alpha):
        calls[0] += 1
        loss, _ = original(design, target, coefficients, delta, ridge_alpha)
        return loss, np.ones(len(coefficients))

    primary.objective_gradient = never_stationary
    try:
        primary.fit(x, target, query)
    except ValueError as error:
        failure = error.args[0]
        assert failure["reason"] == "HUBER_IRLS_NONCONVERGENCE_500" and failure["iterations"] == 500
        assert calls[0] == 500 and failure["status"] == "FAILED"
        refused.append("injected_nonconvergence_exact500_no_fallback")
    else:
        raise AssertionError("nonconvergence returned an OLS fallback")
    finally:
        primary.objective_gradient = original
    checks.append("exact500 nonconvergence explicit refusal; no primary file changed")
    features, labels = annual_fixture()
    scores, traces = primary.forecasts(features, labels)
    certs.append(audit.verify(features, labels, scores, traces))
    assert scores.loc[features.index.year == 2020].isna().all().all()
    assert scores.iloc[-5:].notna().all().all()
    for year in (2021, 2024, 2026):
        limit = features.index[features.index.year == year][0]
        chosen = features.index <= limit
        pf, pl = features.loc[chosen], labels.loc[chosen]
        ps, pt = primary.forecasts(pf, pl)
        certs.append(audit.verify(pf, pl, ps, pt))
        pd.testing.assert_frame_equal(ps, scores.loc[chosen], check_exact=False, atol=1e-14, rtol=0)
        np.testing.assert_array_equal(ps.to_numpy()>0, scores.loc[chosen].to_numpy()>0)
    future = labels.copy()
    first2024 = features.index[features.index.year == 2024][0]
    future.loc[future.label_end_return_4 >= first2024, "return_4"] = .8
    chosen = features.index <= first2024
    altered, at = primary.forecasts(features.loc[chosen], future.loc[chosen])
    certs.append(audit.verify(features.loc[chosen], future.loc[chosen], altered, at))
    pd.testing.assert_frame_equal(altered, scores.loc[chosen], check_exact=False, atol=1e-14, rtol=0)
    checks.append("six past-year causal CDF/fit supports,2020 unavailable, tailtruth NA predicted, prefix/future-label invariant")
    no_tests = features.copy()
    no_tests.loc[no_tests.index.year == 2021] = np.nan
    ns, nt = primary.forecasts(no_tests, labels)
    certs.append(audit.verify(no_tests, labels, ns, nt))
    assert nt[0]["test_feature_n"] == 0 and nt[0]["available"]
    thin = features.copy()
    old_dates = thin.index[thin.index.year == 2020]
    thin.loc[old_dates[35:]] = np.nan
    ts, tt = primary.forecasts(thin, labels)
    certs.append(audit.verify(thin, labels, ts, tt))
    assert tt[0]["reason"] == "INSUFFICIENT_MATURE_TRAINING"
    zero_mad = labels.copy()
    oldmask = zero_mad.index.year == 2020
    zero_mad.loc[oldmask, "return_4"] = 0
    zero_mad.loc[old_dates[-10:], "return_4"] = .02
    zs, zt = primary.forecasts(features, zero_mad)
    certs.append(audit.verify(features, zero_mad, zs, zt))
    assert zt[0]["reason"] == "ZERO_MAD_WITH_VARIED_TARGET"
    assert zs.loc[features.index.year == 2021].isna().all().all()
    checks.append("feature-only current availability and variedMAD0 matched two-column NA; no historical-mean rescue")
    cutoff = labels.copy()
    first2021 = features.index[features.index.year == 2021][0]
    last2020 = features.index[features.index.year == 2020][-1]
    cutoff.loc[last2020, "label_end_return_4"] = first2021
    cs, ct = primary.forecasts(features, cutoff)
    certs.append(audit.verify(features, cutoff, cs, ct))
    assert features.index.get_loc(last2020) not in ct[0]["train_positions"]
    checks.append("label maturity equal firstyear T excluded without discarding future-label predictions")
    for name, key, value in (("delta_tampered", "delta", proof["delta"]*1.4826),
                             ("ridge_tampered", "ridge_alpha", 11.),
                             ("change_not_converged", "max_coefficient_change", 1e-9),
                             ("claim_501iterations", "iterations", 501),
                             ("intercept_penalized", "intercept_penalized", True)):
        forged = copy.deepcopy(proof)
        forged[key] = value
        try:
            audit.verify_fit(x, target, query, pred, forged)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("fit proof forgery accepted "+name)
    forged = copy.deepcopy(proof)
    forged["coefficients"][1] += .01
    try:
        audit.verify_fit(x, target, query, pred, forged)
    except ValueError:
        refused.append("beta_tampered_truegradient")
    else:
        raise AssertionError("nonstationary beta accepted")
    for alpha, multiple in ((10, 1.345), (.99, 1.345), (100.01, 1.345),
                            (10., .49), (10., 3.01), (10., 1), (float("nan"), 1.345)):
        try:
            audit.verify_fit(x, target, query, pred, proof, alpha, multiple)
        except ValueError:
            refused.append("invalid_hyperparameters_"+str(alpha)+"_"+str(multiple))
        else:
            raise AssertionError("invalid typed domain accepted")
    corruptions = []
    bad = scores.copy()
    bad.iloc[-1, 1] = np.nan
    corruptions.append(("tail_future_gate", features, labels, bad, traces))
    bad = labels.copy()
    bad.iloc[0, 1] = features.index[0]
    corruptions.append(("nonfuture_maturity", features, bad, scores, traces))
    bad = labels.copy()
    bad.iloc[2, 1] = pd.NaT
    corruptions.append(("unpaired_maturity", features, bad, scores, traces))
    bad_trace = copy.deepcopy(traces)
    bad_trace[0]["cdf_training_sorted"][0][0] += .01
    corruptions.append(("false_CDF", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(traces)
    bad_trace[0]["train_positions"].append(features.index.get_loc(features.index[features.index.year == 2021][0]))
    corruptions.append(("future_training", features, labels, scores, bad_trace))
    bad = features.copy()
    bad.index = bad.index.tz_localize("Asia/Shanghai")
    corruptions.append(("timezone", bad, labels, scores, traces))
    corruptions.append(("unordered_axis", features.iloc[::-1], labels.iloc[::-1], scores.iloc[::-1], traces))
    bad = features.copy()
    bad.iloc[0, 1] = np.inf
    corruptions.append(("feature_inf", bad, labels, scores, traces))
    bad_trace = copy.deepcopy(traces)
    bad_trace[0]["future_test_count_gate"] = True
    corruptions.append(("future_test_count_gate", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(traces)
    bad_trace[0]["fit"]["delta"] *= 1.4826
    corruptions.append(("annual_delta_normalization", features, labels, scores, bad_trace))
    bad_trace = copy.deepcopy(traces)
    bad_trace[0]["fit"]["coefficients"][0] += .01
    corruptions.append(("annual_beta_tamper", features, labels, scores, bad_trace))
    bad = features.copy()
    bad.index = bad.index.insert(1, bad.index[0])[:len(bad)]
    corruptions.append(("duplicate_axis", bad, labels, scores, traces))
    bad = features.copy()
    bad.index = bad.index+pd.Timedelta(hours=1)
    corruptions.append(("not_midnight_axis", bad, labels, scores, traces))
    corruptions.append(("missing_label_field", features, labels.drop(columns="return_4"), scores, traces))
    for name, fs, ls, sc, tr in corruptions:
        try:
            audit.verify(fs, ls, sc, tr)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("corruption accepted "+name)
    checks.append("scale/beta/penalty/convergence/CDF/provenance/availability/date corruption rejected")
    return {"status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
            "accounts": 0, "experiments_allocated": 0, "new_statistics": 0,
            "checks": checks, "rejections": refused, "final_fit_certificates": fits,
            "annual_certificates": certs, "check_count": len(checks), "rejection_count": len(refused),
            "scope_limitation": "Final convex stationarity/causal provenance, not IRLS trajectory replay or unique-optimum certification. Huber location is not expected net mean or alpha."}


if __name__ == "__main__":
    result = run()
    Path(__file__).with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "check_count", "rejection_count")}, ensure_ascii=False))
