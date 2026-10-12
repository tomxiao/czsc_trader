"""Independent scalar Huber stationarity and causal annual forecast audit.

No primary optimizer is called. Final coefficients permit independent convex
stationarity certification, not replay of every IRLS iterate or a unique optimum
claim. Runtime/preaccount equality remains a separate execution requirement.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import math

import numpy as np
import pandas as pd

FEATURES = (
    "momentum20", "range_position60", "acf1", "volatility20", "intraday_return",
    "overnight_gap", "intraday_energy20", "intraday_rms20", "confirmation_score",
    "daily_close_location", "feature_intraday_down_energy20", "feature_overnight_down_energy20",
    "turnover20", "volume_ratio20",
)


def parameters(ridge_alpha, huber_multiple):
    if type(ridge_alpha) is not float or not math.isfinite(ridge_alpha) or not 1 <= ridge_alpha <= 100:
        raise ValueError("finite float ridge alpha1..100 required")
    if type(huber_multiple) is not float or not math.isfinite(huber_multiple) or not .5 <= huber_multiple <= 3:
        raise ValueError("finite float Huber multiple.5..3 required")


def median(values):
    ordered = sorted(float(v) for v in values)
    if not ordered or not all(math.isfinite(v) for v in ordered):
        raise ValueError("nonempty finite median observations required")
    n = len(ordered)
    return ordered[n//2] if n % 2 else math.fsum((ordered[n//2-1], ordered[n//2]))/2


def objective_gradient(train, target, beta, delta, ridge_alpha):
    losses, psi, design = [], [], []
    for row, value in zip(train, target):
        a = [1.] + [float(v) for v in row]
        prediction = math.fsum(v*b for v, b in zip(a, beta))
        residual = float(value)-prediction
        absolute = abs(residual)
        losses.append(.5*residual*residual if absolute <= delta else delta*(absolute-.5*delta))
        psi.append(residual if absolute <= delta else math.copysign(delta, residual))
        design.append(a)
    loss = math.fsum(losses)+.5*ridge_alpha*math.fsum(v*v for v in beta[1:])
    gradient = [
        -math.fsum(a[j]*p for a, p in zip(design, psi))+(ridge_alpha*beta[j] if j else 0.)
        for j in range(len(beta))
    ]
    return loss, gradient


def verify_fit(train, target, test, reported_prediction, proof, ridge_alpha=10.0, huber_multiple=1.345):
    parameters(ridge_alpha, huber_multiple)
    x, y, query = np.asarray(train, float), np.asarray(target, float), np.asarray(test, float)
    pred = np.asarray(reported_prediction, float)
    if x.ndim != 2 or query.ndim != 2 or x.shape[1] != query.shape[1] or y.shape != (len(x),) or len(x) < 40 or pred.shape != (len(query),):
        raise ValueError("complete aligned training>=40/test matrices and predictions required")
    if not all(np.isfinite(a).all() for a in (x, y, query)):
        raise ValueError("finite fit inputs required")
    keys = {
        "status", "reason", "training_n", "ridge_alpha", "huber_multiple", "training_median",
        "training_mad", "delta", "mad_normalisation_multiplier", "targets_clipped", "intercept_penalized",
        "coefficients", "iterations", "max_abs_gradient", "max_coefficient_change", "objective",
        "constant_target_definition",
    }
    if not isinstance(proof, dict) or set(proof) != keys:
        raise ValueError("exact final fit proof schema required")
    centre = median(y)
    mad = median(abs(float(v)-centre) for v in y)
    delta = huber_multiple*mad
    constant = all(float(v) == float(y[0]) for v in y)
    fixed = {"training_n": len(y), "ridge_alpha": ridge_alpha, "huber_multiple": huber_multiple,
             "mad_normalisation_multiplier": 1.0, "targets_clipped": False, "intercept_penalized": False}
    if any(proof[key] != value for key, value in fixed.items()):
        raise ValueError("fit protocol metadata differs")
    for key, value in (("training_median", centre), ("training_mad", mad), ("delta", delta)):
        if proof[key] is None or not math.isfinite(float(proof[key])) or not math.isclose(float(proof[key]), value, rel_tol=0, abs_tol=1e-14):
            raise ValueError("training-only scale mismatch: "+key)
    if mad == 0 and not constant:
        expect = {"status": "UNAVAILABLE", "reason": "ZERO_MAD_WITH_VARIED_TARGET", "coefficients": None,
                  "iterations": 0, "max_abs_gradient": None, "max_coefficient_change": None,
                  "objective": None, "constant_target_definition": False}
        if any(proof[key] != value for key, value in expect.items()) or not np.isnan(pred).all():
            raise ValueError("varied zero-MAD must be explicit NA without fallback")
        return {"status": "PASS", "available": False, "reason": "ZERO_MAD_WITH_VARIED_TARGET",
                "scope": "independent zero-scale unavailability contract"}
    if proof["status"] != "AVAILABLE" or proof["reason"] is not None:
        raise ValueError("available fitted coefficient proof required")
    beta = proof["coefficients"]
    if not isinstance(beta, list) or len(beta) != x.shape[1]+1 or not all(math.isfinite(float(v)) for v in beta):
        raise ValueError("finite intercept and slopes required")
    beta = [float(v) for v in beta]
    if constant:
        if beta != [float(y[0])] + [0.]*x.shape[1] or proof["iterations"] != 0 or not proof["constant_target_definition"]:
            raise ValueError("constant-target intercept definition differs")
        if proof["max_abs_gradient"] != 0 or proof["max_coefficient_change"] != 0 or proof["objective"] != 0:
            raise ValueError("constant-target zero diagnostics differ")
    else:
        if type(proof["iterations"]) is not int or not 1 <= proof["iterations"] <= 500 or proof["constant_target_definition"]:
            raise ValueError("converged IRLS must declare integer iteration1..500")
        change = proof["max_coefficient_change"]
        if change is None or not math.isfinite(float(change)) or not 0 <= change <= 1e-12:
            raise ValueError("declared coefficient-change criterion not met")
    loss, gradient = objective_gradient(x, y, beta, delta, ridge_alpha)
    norm = max(abs(v) for v in gradient)
    if norm > 1e-10:
        raise ValueError("independent true convex Huber gradient not stationary")
    if proof["max_abs_gradient"] is None or not math.isfinite(float(proof["max_abs_gradient"])) or not 0 <= proof["max_abs_gradient"] <= 1e-10 or not math.isclose(float(proof["max_abs_gradient"]), norm, rel_tol=0, abs_tol=1e-12):
        raise ValueError("reported true gradient norm differs")
    if proof["objective"] is None or not math.isfinite(float(proof["objective"])) or proof["objective"] < 0 or not math.isclose(float(proof["objective"]), loss, rel_tol=0, abs_tol=1e-12):
        raise ValueError("reported Huber loss and slope-only penalty differs")
    wanted = np.asarray([math.fsum([beta[0]]+[float(v)*b for v, b in zip(row, beta[1:])]) for row in query])
    if not np.isfinite(pred).all() or not np.allclose(pred, wanted, rtol=0, atol=1e-12):
        raise ValueError("reported predictions inconsistent with fitted coefficients")
    if not np.array_equal(pred > 0, wanted > 0):
        raise ValueError("strict positive opportunity flags differ")
    return {"status": "PASS", "available": True, "delta": delta, "objective": loss,
            "true_gradient_norm": norm, "forecast_rows": len(query),
            "scope": "independent scale, slope-only Huber objective, final stationarity and coefficient predictions",
            "limitations": "No full IRLS trajectory or independent last-change recomputation; convex optimum may have nonunique intercept plateau. Fixed implementation/source and runtime exact equivalence are separate evidence.",
            "economic_semantics": "Huber location is not conditional expected net mean or proven alpha"}


def _axis(index):
    if not isinstance(index, pd.DatetimeIndex) or not len(index) or index.tz is not None or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing or not index.equals(index.normalize()):
        raise ValueError("nonempty unique ordered naive midnight dates required")


def verify(features, labels, scores, fit_trace, ridge_alpha=10.0, huber_multiple=1.345):
    parameters(ridge_alpha, huber_multiple)
    if not isinstance(features, pd.DataFrame) or tuple(features.columns) != FEATURES:
        raise ValueError("exact original14 ordered feature columns required")
    axis = features.index
    _axis(axis)
    if not isinstance(labels, pd.DataFrame) or labels.columns.has_duplicates or not {"return_4", "label_end_return_4"}.issubset(labels.columns) or not labels.index.equals(axis):
        raise ValueError("complete paired original horizon aliases and axis required")
    if not isinstance(scores, pd.DataFrame) or tuple(scores.columns) != ("training_mean", "huber_net") or not scores.index.equals(axis):
        raise ValueError("two matched forecast fields required")
    if not isinstance(fit_trace, list) or len(fit_trace) != 6:
        raise ValueError("exact2021..2026 fit traces required")
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if np.isinf(x).any() or np.isinf(y).any() or ends.dt.tz is not None or not ends.equals(ends.dt.normalize()) or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError("finite/missing features and paired naive maturity required")
    if any(pd.Timestamp(e) <= t for t, e, value in zip(axis, ends, y) if math.isfinite(value)):
        raise ValueError("label maturity must be after its actual signal")
    complete = [bool(np.isfinite(row).all()) for row in x]
    wanted = np.full((len(axis), 2), np.nan)
    certificates, cdf_values = [], 0
    for year, row in zip(range(2021, 2027), fit_trace):
        first = next((day for day in axis if day.year == year), None)
        train = [i for i, t in enumerate(axis) if first is not None and complete[i] and math.isfinite(y[i]) and 2020 <= t.year < year and pd.Timestamp(ends.iloc[i]) < first]
        test = [i for i, t in enumerate(axis) if complete[i] and t.year == year]
        preliminary = "NO_TEST_YEAR" if first is None else "INSUFFICIENT_MATURE_TRAINING" if len(train) < 40 else None
        meta = {"year": year, "first_test": first.isoformat() if first is not None else None,
                "train_positions": train, "test_positions": test, "train_n": len(train),
                "test_feature_n": len(test), "max_maturity": max(pd.Timestamp(ends.iloc[i]) for i in train).isoformat() if train else None,
                "future_test_count_gate": False, "cdf_rule": "training midpointECDF-.5, all complete mature training"}
        keys = set(meta) | {"available", "reason", "cdf_training_sorted", "target_mean", "fit"}
        if not isinstance(row, dict) or set(row) != keys or any(row[key] != value for key, value in meta.items()):
            raise ValueError("annual causal protocol/support metadata differs")
        if preliminary is not None:
            if row["reason"] != preliminary or row["available"] is not False or any(row[k] is not None for k in ("cdf_training_sorted", "target_mean", "fit")):
                raise ValueError("unsupported year must not synthesize a fit or prior")
            continue
        ordered = [sorted(float(x[i, j]) for i in train) for j in range(14)]
        if row["cdf_training_sorted"] != ordered:
            raise ValueError("exact past-training-only CDF source values differ")
        cdf_values += 14*len(train)
        def ranked(locations):
            return np.asarray([
                [(bisect_left(ordered[j], float(x[i, j]))+bisect_right(ordered[j], float(x[i, j])))/(2*len(train))-.5 for j in range(14)]
                for i in locations], dtype=float).reshape(len(locations), 14)
        tx, vx = ranked(train), ranked(test)
        target_mean = math.fsum(float(y[i]) for i in train)/len(train)
        if row["target_mean"] is None or not math.isclose(row["target_mean"], target_mean, rel_tol=0, abs_tol=1e-14):
            raise ValueError("matched actual training mean differs")
        cert = verify_fit(tx, y[train], vx, scores.huber_net.iloc[test].to_numpy(float), row["fit"], ridge_alpha, huber_multiple)
        certificates.append(cert)
        if row["available"] != cert["available"] or row["reason"] != (None if cert["available"] else cert["reason"]):
            raise ValueError("fit availability and annual matched mask differ")
        if cert["available"]:
            wanted[test, 0] = target_mean
            beta = row["fit"]["coefficients"]
            wanted[test, 1] = [math.fsum([beta[0]]+[float(v)*b for v, b in zip(line, beta[1:])]) for line in vx]
    actual = scores.to_numpy(float)
    if not np.array_equal(np.isnan(actual), np.isnan(wanted)) or not np.allclose(actual, wanted, rtol=0, atol=1e-12, equal_nan=True):
        raise ValueError("matched means/Huber forecast values or unavailable masks differ")
    if not np.array_equal(actual > 0, wanted > 0):
        raise ValueError("strict positive selection flags differ")
    return {"status": "PASS", "annual_traces": 6, "score_cells": scores.size,
            "training_cdf_values": cdf_values, "final_fit_certificates": certificates,
            "method_scope": "independent final convex stationarity and causal fitted provenance, not every IRLS iterate",
            "no_unique_optimum_claim": True, "not_expected_net_mean": True}
