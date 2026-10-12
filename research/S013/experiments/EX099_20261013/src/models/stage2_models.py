"""Pure fixed S013 kernels. Caller owns binding, preflight, IO and fit quota."""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = (
    "momentum20", "range_position60", "acf1", "volatility20",
    "intraday_return", "overnight_gap", "intraday_energy20", "intraday_rms20",
    "confirmation_score", "daily_close_location", "feature_intraday_down_energy20",
    "feature_overnight_down_energy20", "turnover20", "volume_ratio20",
)
GROUPS = {"A": (), "B": ("g1",), "C": ("g2",), "D": ("g1", "g2")}
LABEL_COLUMNS = ("l0", "l1", "end_l0", "end_l1")


def validate_axis(axis):
    if (not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None
            or axis.hasnans or axis.has_duplicates or not axis.is_monotonic_increasing
            or not axis.equals(axis.normalize())):
        raise ValueError("unique ordered naive midnight axis required")


def ecdf(train, values):
    train, values = np.asarray(train, float), np.asarray(values, float)
    if not len(train) or not np.isfinite(train).all() or not np.isfinite(values).all():
        raise ValueError("finite ECDF support required")
    ordered = np.sort(train)
    return (np.searchsorted(ordered, values, side="left")
            + np.searchsorted(ordered, values, side="right")) / (2.0 * len(train))


def design(train, test, group):
    columns = list(FEATURES) + list(GROUPS[group])
    tx = np.column_stack([ecdf(train[c].to_numpy(), train[c].to_numpy()) for c in columns])
    vx = np.column_stack([ecdf(train[c].to_numpy(), test[c].to_numpy()) for c in columns])
    position = columns.index("range_position60")
    for c in GROUPS[group]:
        index = columns.index(c)
        tx = np.column_stack([tx, (tx[:, index] - .5) * (tx[:, position] - .5)])
        vx = np.column_stack([vx, (vx[:, index] - .5) * (vx[:, position] - .5)])
    return tx, vx


def ridge(train_x, train_y, test_x):
    mx, my = train_x.mean(axis=0), float(train_y.mean())
    cx = train_x - mx
    beta = np.linalg.solve(cx.T @ cx + 10.0 * np.eye(train_x.shape[1]),
                           cx.T @ (train_y - my))
    return my + (test_x - mx) @ beta, {"mean_y": my, "mean_x": mx.tolist(),
                                      "slopes": beta.tolist(), "alpha": 10.0}


def forecasts(features, labels, groups=("A",), common_groups=(), years=range(2021, 2027), max_fits=None):
    """Two labels share strictly mature training rows. No test-label selection.

    All models share common_groups' available training support. A can still
    predict every original14-complete T, using the same common-support fit.
    Return scores, means, reasons, fitting evidence, actual number of fits.
    """
    validate_axis(features.index)
    if not features.index.equals(labels.index) or features.columns.has_duplicates:
        raise ValueError("aligned unique frames required")
    if not set(FEATURES).issubset(features.columns) or not set(LABEL_COLUMNS).issubset(labels.columns):
        raise ValueError("original14 and paired labels required")
    if any(g not in GROUPS for g in groups) or len(set(groups)) != len(groups):
        raise ValueError("unique fixed groups required")
    extra = tuple(dict.fromkeys(c for g in common_groups for c in GROUPS[g]))
    required = list(FEATURES) + list(extra)
    if not set(required).issubset(features.columns):
        raise ValueError("common-group fields unavailable")
    requested = tuple(dict.fromkeys(c for g in groups for c in GROUPS[g]))
    if not set(requested).issubset(features.columns):
        raise ValueError("requested model fields unavailable")
    if max_fits is not None and (type(max_fits) is not int or max_fits < 0):
        raise ValueError("nonnegative integer fitting cap required")
    if np.isinf(features[list(FEATURES) + list(set(extra + requested))].to_numpy(float)).any():
        raise ValueError("infinite features prohibited")
    axis = features.index
    y = labels[["l0", "l1"]].to_numpy(float)
    ends = labels[["end_l0", "end_l1"]].apply(pd.to_datetime)
    if np.isinf(y).any():
        raise ValueError("infinite labels prohibited")
    for j in range(2):
        finite = np.isfinite(y[:, j])
        if not np.array_equal(finite, ends.iloc[:, j].notna().to_numpy()):
            raise ValueError("finite label and maturity must pair")
        if (ends.iloc[:, j][finite].to_numpy() <= axis[finite].to_numpy()).any():
            raise ValueError("label maturity must follow T")
    names = [g + str(j) for g in groups for j in range(2)]
    scores = pd.DataFrame(np.nan, index=axis, columns=names)
    means = pd.DataFrame(np.nan, index=axis, columns=["l0", "l1"])
    reasons = pd.DataFrame("NO_PROSPECTIVE_FORECAST", index=axis, columns=names)
    common = np.isfinite(features[required].to_numpy(float)).all(axis=1)
    metadata, fits = {}, 0
    for year in years:
        test_year = axis.year == year
        if not test_year.any():
            metadata[str(year)] = {"reason": "NO_TEST_YEAR", "fits": 0}
            continue
        first = axis[test_year][0]
        train = (common & (axis.year >= 2020) & (axis.year < year)
                 & np.isfinite(y).all(axis=1)
                 & (ends.end_l0 < first).to_numpy() & (ends.end_l1 < first).to_numpy())
        item = {"first_test_T": first.isoformat(), "train_n": int(train.sum()),
                "train_dates": [d.isoformat() for d in axis[train]],
                "latest_maturity": ends.loc[train].max().max().isoformat() if train.any() else None,
                "common_training_groups": list(common_groups), "models": {}, "fits": 0}
        metadata[str(year)] = item
        enough = train.sum() >= 40
        for group in groups:
            columns = list(FEATURES) + list(GROUPS[group])
            if not set(columns).issubset(features.columns):
                raise ValueError("requested model fields unavailable")
            test = test_year & np.isfinite(features[columns].to_numpy(float)).all(axis=1)
            for j in range(2):
                name = group + str(j)
                reasons.loc[test_year, name] = "INCOMPLETE_FEATURES"
                reasons.loc[test, name] = "INSUFFICIENT_TRAIN_SAMPLE" if not enough else "AVAILABLE"
            if not enough:
                continue
            # Fitting is governed only by training support, never future test counts.
            tx, vx = design(features.loc[train], features.loc[test], group)
            for j in range(2):
                name = group + str(j)
                if max_fits is not None and fits >= max_fits:
                    raise ValueError("fixed fitting quota would be exceeded")
                p, coefficient = ridge(tx, y[train, j], vx)
                scores.loc[test, name] = p
                item["models"][name] = {**coefficient, "feature_test_n": int(test.sum())}
                fits += 1
                item["fits"] += 1
        if enough:
            for j in range(2):
                means.loc[test_year, "l" + str(j)] = float(y[train, j].mean())
    return {"scores": scores, "means": means, "reasons": reasons,
            "fit_years": metadata, "fit_count": fits,
            "training_complete": pd.Series(common, index=axis)}


def select_attempts(scores, attempts, phase=None):
    """One occupied position; release-day exit precedes and prevents reentry.

    release_date is actual cancellation/exit decision-day release. Unknown
    release keeps the position occupied through the tail. Phase uses full-axis i.
    """
    validate_axis(scores.index)
    if not scores.index.equals(attempts.index):
        raise ValueError("aligned attempts required")
    if phase is not None and phase not in range(5):
        raise ValueError("only fixed five phases allowed")
    if not {"release_date", "filled", "closed"}.issubset(attempts.columns):
        raise ValueError("actual release/fill/close required")
    if (attempts.closed.astype(bool) & ~attempts.filled.astype(bool)).any():
        raise ValueError("closed implies filled")
    release = pd.to_datetime(attempts.release_date)
    known = release.notna()
    if (release[known].to_numpy() <= scores.index[known].to_numpy()).any():
        raise ValueError("release must follow signal T")
    positive = scores.gt(0) & scores.notna()
    chosen = pd.Series(False, index=scores.index)
    reason = pd.Series("NO_POSITIVE_PREDICTION", index=scores.index)
    occupied_until = None
    unknown_release = False
    for i, day in enumerate(scores.index):
        if not positive.iloc[i]:
            continue
        if unknown_release or (occupied_until is not None and day <= occupied_until):
            reason.iloc[i] = "OCCUPIED_OR_RELEASE_DAY"
        elif phase is not None and i % 5 != phase:
            reason.iloc[i] = "OTHER_FIXED_PHASE"
        else:
            chosen.iloc[i] = True
            reason.iloc[i] = "SELECTED_ATTEMPT"
            occupied_until = release.iloc[i]
            unknown_release = pd.isna(occupied_until)
    return pd.DataFrame({"positive": positive, "selected": chosen, "reason": reason})


def summary(y, prediction, baseline, mask, selection=None, attempts=None):
    y, prediction, baseline, mask = (np.asarray(y, float), np.asarray(prediction, float),
                                    np.asarray(baseline, float), np.asarray(mask, bool))
    forecast = mask & np.isfinite(prediction)
    eligible = forecast & np.isfinite(y) & np.isfinite(baseline)
    selected = forecast & (prediction > 0) if selection is None else forecast & np.asarray(selection, bool)
    valid = selected & np.isfinite(y)
    n, selected_n = int(eligible.sum()), int(valid.sum())
    gains = y[valid & (y > 0)]
    stats = {"forecast_n": int(forecast.sum()), "score_n": n,
             "mse": float(np.mean((y[eligible] - prediction[eligible]) ** 2)) if n >= 20 else None,
             "baseline_mse": float(np.mean((y[eligible] - baseline[eligible]) ** 2)) if n >= 20 else None,
             "selected_forecast_n": int(selected.sum()), "selected_mature_n": selected_n,
             "selected_unscored_n": int((selected & ~np.isfinite(y)).sum()),
             "mean_l1": float(y[valid].mean()) if selected_n >= 20 else None,
             "loss_rate": float((y[valid] < 0).mean()) if selected_n >= 20 else None,
             "nonpositive_rate": float((y[valid] <= 0).mean()) if selected_n >= 20 else None,
             "fixed_independent_attempt_profit_sum": float(y[valid].sum() * 1_000_000),
             "largest_gain_share_of_positive_gains": float(gains.max() / gains.sum()) if len(gains) else None,
             "mean_reason": None if selected_n >= 20 else "INSUFFICIENT_20_SELECTED"}
    stats["mse_improvement"] = stats["baseline_mse"] - stats["mse"] if n >= 20 else None
    if attempts is not None:
        stats["actual_closed_n"] = int((valid & attempts.closed.to_numpy(bool)).sum())
        stats["actual_filled_n"] = int((selected & attempts.filled.to_numpy(bool)).sum())
        stats["unfilled_mature_attempt_n"] = int((valid & ~attempts.filled.to_numpy(bool)).sum())
        if "occupation_days" in attempts:
            stats["occupation_days_sum"] = float(attempts.loc[selected, "occupation_days"].sum())
    return stats


def panels(scores, labels, means, attempts, eligible=None):
    axis, truth = scores.index, labels.l1.to_numpy(float)
    masks = {"all": np.ones(len(axis), bool),
             **{f"year_{y}": axis.year == y for y in range(2020, 2027)},
             **{f"phase_{p}": np.arange(len(axis)) % 5 == p for p in range(5)}}
    if eligible is not None:
        if not isinstance(eligible, pd.Series) or not eligible.index.equals(axis) or eligible.isna().any():
            raise ValueError("aligned nonnull common input eligibility required")
        scores = scores.where(eligible.astype(bool), axis=0)
    result, choices = {}, {}
    for model in scores:
        model_choices = {"greedy": select_attempts(scores[model], attempts),
                         **{f"clock_{p}": select_attempts(scores[model], attempts, p) for p in range(5)}}
        choices[model] = model_choices
        item = {}
        for panel, mask in masks.items():
            item[panel] = {"positive_opportunities": summary(truth, scores[model], means.l1, mask),
                           **{clock: summary(truth, scores[model], means.l1, mask, chosen.selected, attempts)
                              for clock, chosen in model_choices.items()}}
            blocked = model_choices["greedy"].reason.eq("OCCUPIED_OR_RELEASE_DAY")
            item[panel]["occupied_positive"] = summary(truth, scores[model], means.l1, mask, blocked)
        result[model] = item
    return result, choices


def paired_panels(scores, labels, means, choices, pairs):
    """All-score and positive/greedy means are evaluated on pairwise shared inputs."""
    axis, y = scores.index, labels.l1.to_numpy(float)
    masks = {"all":np.ones(len(axis),bool),
             **{f"year_{z}":axis.year==z for z in range(2020,2027)},
             **{f"phase_{p}":np.arange(len(axis))%5==p for p in range(5)}}
    result = {}
    for new, old in pairs:
        support = np.isfinite(scores[new]) & np.isfinite(scores[old])
        item = {}
        for name, mask in masks.items():
            paired = mask & support.to_numpy()
            item[name] = {"paired_forecast_n":int(paired.sum()), "new":{}, "old":{}}
            for model,key in ((new,"new"),(old,"old")):
                item[name][key]["positive"] = summary(y,scores[model],means.l1,paired)
                for clock in ("greedy",*(f"clock_{p}" for p in range(5))):
                    item[name][key][clock] = summary(y,scores[model],means.l1,paired,choices[model][clock].selected)
            n,o = item[name]["new"]["positive"],item[name]["old"]["positive"]
            item[name]["mse_reduction"] = o["mse"]-n["mse"] if n["mse"] is not None and o["mse"] is not None else None
            for clock in ("positive","greedy",*(f"clock_{p}" for p in range(5))):
                n,o = item[name]["new"][clock]["mean_l1"],item[name]["old"][clock]["mean_l1"]
                item[name][clock+"_mean_delta"] = n-o if n is not None and o is not None else None
        result[new+"-"+old] = item
    return result


def bootstrap_indices(n):
    if n < 40:
        return None
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 40 + 1, size=(500, int(np.ceil(n / 40))))
    return (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]


def paired_bootstrap(scores, labels, means, choices, pairs):
    """Resample existing predictions/selections on common day axis; no refit/clock replay."""
    y, base = labels.l1.to_numpy(float), means.l1.to_numpy(float)
    n = len(y)
    indices = bootstrap_indices(n)
    output = {}
    for new, old in pairs:
        a, b = scores[new].to_numpy(float), scores[old].to_numpy(float)
        support = np.isfinite(y) & np.isfinite(a) & np.isfinite(b) & np.isfinite(base)
        sa, sb = choices[new]["greedy"].selected.to_numpy(), choices[old]["greedy"].selected.to_numpy()
        def quantities(rows):
            ok = support[rows]
            yy, aa, bb = y[rows][ok], a[rows][ok], b[rows][ok]
            positive_a, positive_b = yy[aa > 0], yy[bb > 0]
            greedy_a, greedy_b = y[rows][ok & sa[rows]], y[rows][ok & sb[rows]]
            def delta(x, z):
                return float(x.mean() - z.mean()) if min(len(x), len(z)) >= 20 else None
            return {"mse_reduction": float(np.mean((yy-bb)**2 - (yy-aa)**2)) if len(yy)>=20 else None,
                    "positive_mean_delta": delta(positive_a, positive_b),
                    "greedy_mean_delta": delta(greedy_a, greedy_b)}, {
                        "paired": len(yy), "positive_new": len(positive_a), "positive_old": len(positive_b),
                        "greedy_new": len(greedy_a), "greedy_old": len(greedy_b)}
        original, original_n = quantities(np.arange(n))
        records = []
        for i in range(500):
            vals, ns = quantities(indices[i]) if indices is not None else ({k:None for k in original}, {})
            records.append({"replicate": i, "values": vals, "counts": ns,
                            "status": {k:"VALID" if v is not None else "INSUFFICIENT_SUPPORT" for k,v in vals.items()}})
        summary_out = {}
        for key, value in original.items():
            valid = [r["values"][key] for r in records if r["values"][key] is not None]
            enough = value is not None and len(valid) >= 400
            summary_out[key] = {"original":value, "valid_replicates":len(valid),
                                "ci95":np.quantile(valid,[.025,.975],method="linear").tolist() if enough else None,
                                "reason":None if enough else "INSUFFICIENT_ORIGINAL_OR_REPLICATES"}
        output[f"{new}-{old}"] = {"original_counts":original_n, "summary":summary_out, "records":records}
    return {"pairs":output, "block_days":40,"replicates":500,"seed":13,
            "refits":0,"replayed_clock":False,"selection_history_not_corrected":True}
