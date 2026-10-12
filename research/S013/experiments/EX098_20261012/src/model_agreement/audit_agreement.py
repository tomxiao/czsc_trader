"""Independent agreement audit: causal models, strict votes and one policy clock.

CART/Huber verifiers are exact copies of the separately frozen independent
audits. Ridge final stationarity is recomputed with scalar sums; no primary fit
is used. Huber final optimality is not an IRLS trajectory or unique-intercept
certificate. Votes are admission decisions, never expected return estimates.
"""
from bisect import bisect_left, bisect_right
import math

import numpy as np
import pandas as pd

from . import audit_tree, audit_huber

FEATURES = audit_tree.FEATURES
MODELS = ("joint_ridge", "cart_net", "huber_net")
SCORE_COLUMNS = MODELS + ("all_available", "positive_votes", "vote_score")


def _equal(actual, wanted, description):
    a, b = np.asarray(actual, float), np.asarray(wanted, float)
    if a.shape != b.shape or np.isinf(a).any() or not np.array_equal(np.isnan(a), np.isnan(b)) or not np.allclose(a, b, atol=1e-12, rtol=0, equal_nan=True):
        raise ValueError(description + " values/unavailability differ")
    if not np.array_equal(a > 0, b > 0):
        raise ValueError(description + " strict positive flags differ")


def verify_joint_fit(train, target, test, predictions, proof, ridge_alpha=10.0):
    audit_huber.parameters(ridge_alpha, 1.345)
    x, y, query = np.asarray(train, float), np.asarray(target, float), np.asarray(test, float)
    if x.ndim != 2 or query.ndim != 2 or x.shape[1] != 14 or query.shape[1] != 14 or y.shape != (len(x),) or len(x) < 40 or not all(np.isfinite(a).all() for a in (x, y, query)):
        raise ValueError("finite joint14 aligned matrices with training>=40 required")
    keys = {"training_n", "ridge_alpha", "feature_count", "intercept_penalized", "coefficients", "gradient", "max_abs_gradient", "objective"}
    if not isinstance(proof, dict) or set(proof) != keys or proof["training_n"] != len(x) or proof["ridge_alpha"] != ridge_alpha or proof["feature_count"] != 14 or proof["intercept_penalized"] is not False:
        raise ValueError("exact joint14 unpenalized-intercept proof required")
    beta = proof["coefficients"]
    if not isinstance(beta, list) or len(beta) != 15 or not all(math.isfinite(float(v)) for v in beta):
        raise ValueError("finite15 joint coefficients required")
    fitted = [math.fsum([beta[0]] + [float(v)*b for v, b in zip(row, beta[1:])]) for row in x]
    residual = [value-float(target) for value, target in zip(fitted, y)]
    gradient = [math.fsum(residual)] + [math.fsum(float(row[j])*r for row, r in zip(x, residual)) + ridge_alpha*beta[j+1] for j in range(14)]
    norm = max(abs(v) for v in gradient)
    objective = .5*math.fsum(r*r for r in residual) + .5*ridge_alpha*math.fsum(b*b for b in beta[1:])
    if norm > 1e-10:
        raise ValueError("independent joint ridge true gradient is not stationary")
    for value, wanted, name in ((proof["max_abs_gradient"], norm, "gradient norm"), (proof["objective"], objective, "objective")):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or not math.isclose(value, wanted, abs_tol=1e-12, rel_tol=0):
            raise ValueError("joint ridge " + name + " differs")
    if not isinstance(proof["gradient"], list) or len(proof["gradient"]) != 15 or not np.allclose(proof["gradient"], gradient, atol=1e-12, rtol=0):
        raise ValueError("joint ridge all gradient coordinates differ")
    wanted = [math.fsum([beta[0]] + [float(v)*b for v, b in zip(row, beta[1:])]) for row in query]
    _equal(predictions, wanted, "joint predictions")
    return {"status": "PASS", "gradient_norm": norm, "objective": objective, "forecast_rows": len(query), "unique_ridge_optimum": True}


def verify_votes(scores):
    if not isinstance(scores, pd.DataFrame) or tuple(scores.columns) != SCORE_COLUMNS:
        raise ValueError("exact six agreement score columns required")
    audit_tree._axis(scores.index)
    if scores.all_available.dtype != bool:
        raise ValueError("all_available must have boolean dtype")
    models = scores.loc[:, list(MODELS)].to_numpy(float)
    if np.isinf(models).any():
        raise ValueError("infinite model predictions refused")
    available, votes, aggregate = [], [], []
    for row in models:
        usable = all(math.isfinite(float(v)) for v in row)
        available.append(usable)
        count = sum(float(v) > 0 for v in row) if usable else math.nan
        votes.append(count)
        aggregate.append(float(count >= 2) if usable else math.nan)
    if scores.all_available.tolist() != available:
        raise ValueError("all3 availability differs")
    _equal(scores.positive_votes, votes, "strict positive vote count")
    _equal(scores.vote_score, aggregate, "current2of3 vote")
    return {"status": "PASS", "vote_rows": len(scores), "available_rows": sum(available), "no_two_model_fallback": True}


def verify(features, labels, scores, traces, *, ridge_alpha=10.0, huber_multiple=1.345, tree_depth=2, minimum_leaf=40):
    audit_huber.parameters(ridge_alpha, huber_multiple)
    audit_tree.parameters(tree_depth, minimum_leaf)
    if not isinstance(features, pd.DataFrame) or tuple(features.columns) != FEATURES:
        raise ValueError("original14 feature order required")
    axis = features.index
    audit_tree._axis(axis)
    if not isinstance(labels, pd.DataFrame) or labels.columns.has_duplicates or not {"return_4", "label_end_return_4"}.issubset(labels.columns) or not labels.index.equals(axis) or not scores.index.equals(axis):
        raise ValueError("paired labels and shared exact axis required")
    vote_certificate = verify_votes(scores)
    if not isinstance(traces, dict) or set(traces) != set(MODELS) or any(not isinstance(traces[name], list) or len(traces[name]) != 6 for name in MODELS):
        raise ValueError("all three six-year trace collections required")
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if np.isinf(x).any() or np.isinf(y).any() or ends.dt.tz is not None or not ends.equals(ends.dt.normalize()) or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError("finite/missing features and paired naive maturity required")
    if any(value <= -1 or pd.Timestamp(e) <= t for t, e, value in zip(axis, ends, y) if math.isfinite(value)):
        raise ValueError("actual net target must mature after signal")
    complete = [bool(np.isfinite(row).all()) for row in x]
    joint_wanted = np.full(len(axis), np.nan)
    cart_prior, huber_prior = np.full(len(axis), np.nan), np.full(len(axis), np.nan)
    ridge_certificates = []
    cdf_values = 0
    for year, row, cart_row, huber_row in zip(range(2021, 2027), traces["joint_ridge"], traces["cart_net"], traces["huber_net"]):
        first = next((day for day in axis if day.year == year), None)
        train = [i for i, day in enumerate(axis) if first is not None and complete[i] and math.isfinite(y[i]) and 2020 <= day.year < year and pd.Timestamp(ends.iloc[i]) < first]
        test = [i for i, day in enumerate(axis) if complete[i] and day.year == year]
        reason = "NO_YEAR" if first is None else "INSUFFICIENT_MATURE_TRAINING" if len(train) < 40 else None
        meta = {"year": year, "first_test": first.isoformat() if first is not None else None, "train_positions": train,
                "test_positions": test, "train_n": len(train), "max_maturity": max(pd.Timestamp(ends.iloc[i]) for i in train).isoformat() if train else None,
                "future_test_count_gate": False, "available": reason is None, "reason": reason}
        if not isinstance(row, dict) or set(row) != set(meta) | {"train_cdfs", "fit"} or any(row[k] != value for k, value in meta.items()):
            raise ValueError("joint ridge annual causal support/protocol differs")
        if reason is not None:
            if row["fit"] is not None or row["train_cdfs"] is not None:
                raise ValueError("unsupported joint year must not fit")
            continue
        ordered = [sorted(float(x[i, j]) for i in train) for j in range(14)]
        if row["train_cdfs"] != ordered:
            raise ValueError("joint exact training CDF observations differ")
        cdf_values += len(train)*14
        def ranks(locations):
            return np.asarray([[(bisect_left(ordered[j], float(x[i, j]))+bisect_right(ordered[j], float(x[i, j])))/(2*len(train))-.5 for j in range(14)] for i in locations]).reshape(len(locations), 14)
        tx, vx = ranks(train), ranks(test)
        certificate = verify_joint_fit(tx, y[train], vx, scores.joint_ridge.iloc[test].to_numpy(float), row["fit"], ridge_alpha)
        ridge_certificates.append(certificate)
        beta = row["fit"]["coefficients"]
        joint_wanted[test] = [math.fsum([beta[0]]+[float(v)*b for v, b in zip(line, beta[1:])]) for line in vx]
        prior = math.fsum(float(y[i]) for i in train)/len(train)
        if len(train) >= max(40, minimum_leaf):
            cart_prior[test] = prior
        # This sidecar is independently sourced; the full Huber verifier below
        # independently verifies the annual reason and availability declaration.
        if huber_row.get("available") is True:
            huber_prior[test] = prior
        if cart_row.get("train_positions") != train or cart_row.get("test_positions") != test or huber_row.get("train_positions") != train or huber_row.get("test_positions") != test:
            raise ValueError("all model training/maturity/test support must agree")
    _equal(scores.joint_ridge, joint_wanted, "annual joint ridge")
    cart_scores = pd.DataFrame({"training_mean": cart_prior, "cart_net": scores.cart_net}, index=axis)
    huber_scores = pd.DataFrame({"training_mean": huber_prior, "huber_net": scores.huber_net}, index=axis)
    cart_certificate = audit_tree.verify(features, labels, cart_scores, traces["cart_net"], max_depth=tree_depth, minimum_leaf=minimum_leaf)
    huber_certificate = audit_huber.verify(features, labels, huber_scores, traces["huber_net"], ridge_alpha, huber_multiple)
    return {"status": "PASS", "annual_ridge_certificates": ridge_certificates, "ridge_cdf_values": cdf_values,
            "cart": cart_certificate, "huber": huber_certificate, "votes": vote_certificate,
            "shared_information": "same original14 and mature target; heterogeneous estimators do not establish independent information or alpha",
            "huberscope": "final convex stationarity and provenance; not every IRLS iterate or unique-intercept claim"}


def verify_policy(history, scores, features, traces, inputs, H):
    if type(H) is not int or not 1 <= H <= 60:
        raise ValueError("integer shared holding clock1..60 required")
    verify_votes(scores)
    axis = scores.index
    if not isinstance(history, pd.DataFrame) or not history.index.equals(axis) or not features.index.equals(axis) or tuple(features.columns) != FEATURES or not isinstance(traces, dict) or set(traces) != set(MODELS):
        raise ValueError("aligned audited model/history/features/traces required")
    expected = {name: [] for name in ("target_position", "signal_reason", "policy_age", "episode_entry_position", "positive_forecast")}
    entry = None
    for i, (day, forecast) in enumerate(zip(axis, scores.vote_score)):
        positive = math.isfinite(float(forecast)) and float(forecast) > 0
        age = i-entry if entry is not None else None
        reason = "flat"
        if entry is not None:
            if age >= H:
                entry, reason = None, "expiry"
            else:
                reason = "hold"
        elif day.year > 2020 and positive:
            entry, age, reason = i, 0, "entry"
        for name, value in zip(expected, (float(entry is not None), reason, age, entry, bool(positive))):
            expected[name].append(value)
    expected["net_forecast"] = scores.vote_score.to_numpy(float)
    expected["common14_available"] = np.isfinite(features.to_numpy(float)).all(axis=1)
    expected["confirmation_score"] = features.confirmation_score.to_numpy(float)
    yearly = {row["year"]: row for row in traces["joint_ridge"]}
    expected["train_n"] = [yearly.get(day.year, {}).get("train_n", 0) for day in axis]
    expected["train_max_maturity"] = [yearly.get(day.year, {}).get("max_maturity") for day in axis]
    expected["all_models_available"] = scores.all_available.to_numpy()
    expected["positive_vote_count"] = scores.positive_votes.to_numpy(float)
    expected["agreement_entry_score"] = scores.vote_score.to_numpy(float)
    for name in MODELS:
        expected[name+"_score"] = scores[name].to_numpy(float)
        expected[name+"_available"] = np.isfinite(scores[name].to_numpy(float))
    if "close" in history:
        if not isinstance(inputs, dict) or "daily" not in inputs:
            raise ValueError("daily source required to audit emitted close")
        daily = pd.DataFrame(inputs["daily"], copy=False)
        days = pd.DatetimeIndex(pd.to_datetime(daily.Date))
        audit_tree._axis(days)
        if not axis.isin(days).all() or not np.isfinite(daily.Close.to_numpy(float)).all() or (daily.Close.to_numpy(float) <= 0).any():
            raise ValueError("complete positive observed Close source required")
        lookup = {day: float(value) for day, value in zip(days, daily.Close)}
        expected["close"] = [lookup[day] for day in axis]
    if set(history.columns) != set(expected) or history.columns.has_duplicates:
        raise ValueError("exact single clock policy/diagnostic fields required")
    for name, values in expected.items():
        if name == "train_max_maturity":
            for actual, wanted in zip(history[name], values):
                if not ((pd.isna(actual) and wanted is None) or actual == wanted):
                    raise ValueError("policy maturity differs")
        elif name == "signal_reason":
            if history[name].tolist() != list(values):
                raise ValueError("policy exact string/state differs: "+name)
        elif name in ("positive_forecast", "common14_available", "all_models_available") or name.endswith("_available"):
            if history[name].dtype != bool or history[name].tolist() != list(values):
                raise ValueError("policy bool differs: "+name)
        else:
            _equal(history[name], values, "single shared clock "+name)
    return {"status": "PASS", "policy_rows": len(axis), "policy_cells": history.size, "shared_H": H,
            "no_virtual_member_positions": True, "no_expiry_day_reentry": True,
            "EX018_difference": "EX018 votes virtual holdings with separate path states; this votes current model forecasts for admission and keeps one shared H clock"}
