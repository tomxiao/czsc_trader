"""SOURCE ONLY: independent arithmetic audit, no file/provider/platform I/O.

This is not a second study or a scientific classification. Callers must authenticate
the public preflight/statistics EvidenceRefs and original cache identity first.
Actual use needs a new root verification authority; synthetic calls do not.
"""

from collections import Counter

import numpy as np
import pandas as pd

CONTROLS = (
    "momentum20",
    "range_position60",
    "acf1",
    "volatility20",
    "intraday_return",
    "overnight_gap",
    "intraday_energy20",
    "intraday_rms20",
    "confirmation_score",
    "daily_close_location",
    "feature_intraday_down_energy20",
    "feature_overnight_down_energy20",
    "turnover20",
    "volume_ratio20",
    "late_recovery",
    "early_volume_reclaim",
    "short_stretch4",
)
COMPONENT = "curvature4"
LABELS = ("return4_net", "downside4_oc")


def ranks(values):
    """Average ties by explicit sorted equal runs; no scipy rankdata."""
    order = np.argsort(values, kind="stable")
    result = np.empty(len(values), dtype=float)
    a = 0
    while a < len(values):
        b = a + 1
        while b < len(values) and values[order[b]] == values[order[a]]:
            b += 1
        result[order[a:b]] = (a + 1 + b) / 2
        a = b
    return result


def ic(x, y, controls=None):
    mask = np.isfinite(x) & np.isfinite(y)
    if controls is not None:
        mask &= np.isfinite(controls).all(axis=1)
    positions = np.flatnonzero(mask)
    n = len(positions)
    out = dict(
        n=n,
        finite_positions=positions.tolist(),
        value=None,
        reason=None,
        design_rank=None,
        residual_df=None,
        singular_values=None,
        condition_number=None,
        component_residual_fraction=None,
        target_residual_fraction=None,
    )
    a, b = ranks(x[mask]), ranks(y[mask])
    if n:
        a -= np.mean(a)
        b -= np.mean(b)
    basis = None
    if controls is not None:
        design = np.empty((n, 18))
        design[:, 0] = 1
        for j in range(17):
            design[:, j + 1] = ranks(controls[mask, j])
        u, s, _ = np.linalg.svd(design, full_matrices=False)
        tolerance = s[0] * max(design.shape) * np.finfo(float).eps if len(s) else 0
        rank = int(np.count_nonzero(s > tolerance))
        basis = u[:, :rank]
        out.update(
            design_rank=rank,
            residual_df=n - rank,
            singular_values=s.tolist(),
            condition_number=float(s[0] / s[-1]) if len(s) and s[-1] > 0 else None,
        )
    if n < 20:
        out["reason"] = "INSUFFICIENT_SAMPLE"
    elif controls is not None and out["residual_df"] < 10:
        out["reason"] = "INSUFFICIENT_RESIDUAL_DF"
    else:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            out["reason"] = "CONSTANT_COMPONENT" if na == 0 else "CONSTANT_TARGET"
        else:
            if basis is not None:
                # SVD orthogonal projection, independently of source OLS/lstsq.
                a = a - basis @ (basis.T @ a)
                b = b - basis @ (basis.T @ b)
                out["component_residual_fraction"] = float(np.linalg.norm(a) / na)
                out["target_residual_fraction"] = float(np.linalg.norm(b) / nb)
                if np.linalg.norm(a) <= 1e-10 * na:
                    out["reason"] = "EXPLAINED_COMPONENT"
                elif np.linalg.norm(b) <= 1e-10 * nb:
                    out["reason"] = "TARGET_EXPLAINED_OR_CONSTANT"
            if out["reason"] is None:
                out["value"] = float(
                    np.clip(np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)
                )
    return out


def full_axis_blocks(n):
    """Seed13 starts on the full T axis, explicit block assembly and truncation."""
    if n < 40:
        return None
    count = (n + 39) // 40
    starts = np.random.Generator(np.random.PCG64(13)).integers(0, n - 39, (500, count))
    output = np.empty((500, n), dtype=int)
    for rep in range(500):
        output[rep] = np.concatenate([np.arange(start, start + 40) for start in starts[rep]])[:n]
    return output


def linear_percentile(values, probabilities):
    ordered = sorted(values)
    result = []
    for probability in probabilities:
        position = (len(ordered) - 1) * probability
        lower, upper = int(np.floor(position)), int(np.ceil(position))
        fraction = position - lower
        result.append(float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction))
    return result


def boot(x, y, controls, blocks):
    rows = []
    for rep in range(500):
        if blocks is None:
            row = dict(
                value=None, reason="INSUFFICIENT_FULL_AXIS", n=0, design_rank=None, residual_df=None
            )
        else:
            pos = blocks[rep]
            row = ic(x[pos], y[pos], None if controls is None else controls[pos])
            del row["finite_positions"]
        row["replicate"] = rep
        rows.append(row)
    valid = [row["value"] for row in rows if row["value"] is not None]
    return dict(
        requested=500,
        valid=len(valid),
        replicates=rows,
        status_counts=dict(Counter(row["reason"] or "VALID" for row in rows)),
        ic95=linear_percentile(valid, (0.025, 0.975)) if len(valid) >= 400 else None,
        reason=None if len(valid) >= 400 else "INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES",
    )


def empirical_transform(train, values):
    # Unique counts and cumulative mass instead of searchsorted twice on raw train.
    unique, counts = np.unique(train, return_counts=True)
    cumulative = np.r_[0, np.cumsum(counts)]
    result = np.empty(len(values))
    for j, value in enumerate(values):
        p = int(np.searchsorted(unique, value))
        equal = counts[p] if p < len(unique) and unique[p] == value else 0
        result[j] = (cumulative[p] + equal / 2) / len(train)
    return result


def predict(train, y, test):
    # Intercept augmented normal equations; source uses centered features.
    design = np.column_stack([np.ones(len(train)), train])
    penalty = np.diag([0.0] + [10.0] * train.shape[1])
    coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return np.column_stack([np.ones(len(test)), test]) @ coef


def score(records):
    n = len(records)
    if n < 20:
        return dict(
            n=n,
            reason="INSUFFICIENT_TEST_SAMPLE",
            mse_controls=None,
            mse_augmented=None,
            mse_pastmean=None,
            delta_controls=None,
            delta_pastmean=None,
            ic_controls=None,
            ic_augmented=None,
        )
    target = np.array([row["target"] for row in records])
    out = dict(n=n, reason=None)
    for name in ("controls", "augmented", "pastmean"):
        p = np.array([row[name] for row in records])
        out["mse_" + name] = float(np.dot(target - p, target - p) / n)
        if name != "pastmean":
            out["ic_" + name] = ic(p, target)
    out["delta_controls"] = out["mse_controls"] - out["mse_augmented"]
    out["delta_pastmean"] = out["mse_pastmean"] - out["mse_augmented"]
    return out


def past_only(index, features18, target, ends):
    common = np.isfinite(features18).all(axis=1) & np.isfinite(target)
    records, yearly = [], {}
    for year in range(2021, 2027):
        dates = [day for day in index if day.year == year]
        start = dates[0] if dates else None
        train = [
            p
            for p, day in enumerate(index)
            if start is not None and common[p] and 2020 <= day.year < year and ends.iloc[p] < start
        ]
        test = [p for p, day in enumerate(index) if common[p] and day.year == year]
        reason = (
            "NO_TEST_YEAR"
            if start is None
            else "INSUFFICIENT_TRAIN_SAMPLE"
            if len(train) < 40
            else "INSUFFICIENT_TEST_SAMPLE"
            if len(test) < 20
            else None
        )
        local = []
        if reason is None:
            tx = np.empty((len(train), 18))
            vx = np.empty((len(test), 18))
            for j in range(18):
                tx[:, j] = empirical_transform(features18[train, j], features18[train, j])
                vx[:, j] = empirical_transform(features18[train, j], features18[test, j])
            pc = predict(tx[:, :17], target[train], vx[:, :17])
            pa = predict(tx, target[train], vx)
            mean = float(sum(target[train]) / len(train))
            local = [
                dict(
                    position=p,
                    signaldate=index[p].isoformat(),
                    target=float(target[p]),
                    controls=float(pc[j]),
                    augmented=float(pa[j]),
                    pastmean=mean,
                )
                for j, p in enumerate(test)
            ]
        yearly[str(year)] = dict(
            first_actual_signaldate=start.isoformat() if start else None,
            train_positions=train,
            test_positions=test,
            train_n=len(train),
            test_n=len(test),
            latest_train_label_end=max(ends.iloc[train]).isoformat() if train else None,
            reason=reason,
            metrics=score(local),
        )
        records.extend(local)
    return dict(yearly=yearly, aggregate=score(records), records=records)


def authenticate_frames(features, labels, calendar):
    """Independent maturity checks use explicit full evaluation PRICE calendar."""
    for index in (features.index, labels.index, calendar):
        if (
            not isinstance(index, pd.DatetimeIndex)
            or index.hasnans
            or index.has_duplicates
            or index.tz is not None
            or not index.is_monotonic_increasing
            or not index.equals(index.normalize())
        ):
            raise ValueError("invalid session axis")
    if not features.index.equals(labels.index) or not features.index.isin(calendar).all():
        raise ValueError("aligned T axis and complete price calendar required")
    if features.columns.has_duplicates or labels.columns.has_duplicates:
        raise ValueError("duplicate columns")
    if any(name in features for name in LABELS) or any(
        str(name).startswith("label_end") for name in features
    ):
        raise ValueError("future feature forbidden")
    x = features[[*CONTROLS, COMPONENT]].to_numpy(float)
    if np.isinf(x).any():
        raise ValueError("infinite feature")
    ends = pd.to_datetime(labels.label_end4, errors="raise")
    if ends.dt.tz is not None:
        raise ValueError("timezone-aware maturity")
    lookup = {date: p for p, date in enumerate(calendar)}
    for p, date in enumerate(features.index):
        k = lookup[date] + 5
        expected = calendar[k] if k < len(calendar) else pd.NaT
        for name in LABELS:
            y = float(labels.iloc[p][name])
            if np.isinf(y):
                raise ValueError("infinite label")
            if np.isfinite(y):
                if pd.isna(expected) or pd.isna(ends.iloc[p]) or ends.iloc[p] != expected:
                    raise ValueError("incorrect T+5 OPEN maturity")
                if name == "return4_net" and y <= -1:
                    raise ValueError("invalid price return")
                if name == "downside4_oc" and not 0 <= y < 1:
                    raise ValueError("invalid O/C downside")
    return x, ends


def _recompute_scope(features, labels, calendar):
    x, ends = authenticate_frames(features, labels, calendar)
    index = features.index
    blocks = full_axis_blocks(len(index))
    panels = {}
    for name in LABELS:
        target = labels[name].to_numpy(float)
        panel = dict(
            raw=ic(x[:, 17], target),
            partial=ic(x[:, 17], target, x[:, :17]),
            raw_bootstrap=boot(x[:, 17], target, None, blocks),
            partial_bootstrap=boot(x[:, 17], target, x[:, :17], blocks),
            years={},
            phases={},
            walk_forward=past_only(index, x, target, ends),
        )
        for year in sorted(set(index.year)):
            pos = np.array([p for p, date in enumerate(index) if date.year == year])
            panel["years"][str(year)] = dict(
                raw=ic(x[pos, 17], target[pos]), partial=ic(x[pos, 17], target[pos], x[pos, :17])
            )
        for phase in range(5):
            pos = np.arange(phase, len(index), 5)
            panel["phases"][str(phase)] = dict(
                raw=ic(x[pos, 17], target[pos]), partial=ic(x[pos, 17], target[pos], x[pos, :17])
            )
        panels[name] = panel
    return dict(
        status="DESCRIPTIVE_STATISTICS_NOT_SCIENTIFIC_OR_ECONOMIC_ACCEPTANCE",
        full_axis_n=len(index),
        labels=panels,
    )


def recompute(features, labels, calendar, *, flat_eligible):
    """Fixed full + policy-flat scope; only targets masked, never original T axis."""
    authenticate_frames(features, labels, calendar)
    if (
        not isinstance(flat_eligible, pd.Series)
        or not flat_eligible.index.equals(features.index)
        or flat_eligible.dtype != np.dtype(bool)
    ):
        raise ValueError("Exact complete original causal policy-flat Boolean scope required")
    scoped = labels.copy(deep=True)
    scoped.loc[~flat_eligible, list(LABELS)] = np.nan
    return dict(
        status="DESCRIPTIVE_STATISTICS_NOT_SCIENTIFIC_OR_ECONOMIC_ACCEPTANCE",
        primary="return4_net",
        return_direction="positive",
        risk_role="diagnostic only, no fixed sign, trading role or economic gate",
        full_axis_n=len(features),
        causal_original_policy_flat_eligible_n=int(flat_eligible.sum()),
        scopes={
            "all": _recompute_scope(features, labels, calendar),
            "causal_original_policy_flat_eligible": _recompute_scope(features, scoped, calendar),
        },
    )


def assert_equal(actual, expected, path="statistics", comparison=None):
    """Every status/position/replicate/prediction audited, null never coerced to zero."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError(path + ": keys")
        for key in expected:
            assert_equal(actual[key], expected[key], path + "." + key, comparison)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(path + ": list")
        for p, (a, b) in enumerate(zip(actual, expected)):
            assert_equal(a, b, f"{path}[{p}]", comparison)
    elif isinstance(expected, float):
        if not isinstance(actual, (int, float)) or not np.isfinite(actual):
            raise AssertionError(path + ": finite float")
        # Condition number is not claimed exact for near-singular designs.
        if path.endswith("condition_number"):
            if actual < 1 or expected < 1:
                raise AssertionError(path + ": condition")
            if expected <= 1e10:
                if not np.isclose(actual, expected, atol=2e-10, rtol=2e-7):
                    raise AssertionError(path + ": well-conditioned diagnostic")
            else:
                if actual < 1e8:
                    raise AssertionError(path + ": inconsistent near-singular diagnostic")
                if comparison is not None:
                    comparison["near_singular_condition_diagnostics"].append(
                        dict(
                            path=path,
                            reported=actual,
                            independent=expected,
                            difference=actual - expected,
                            exact_claim=False,
                            limitation="Tiny singular values make condition diagnostics unstable; rank/DF and residual arithmetic separately checked.",
                        )
                    )
        elif not np.isclose(actual, expected, atol=2e-10, rtol=2e-9):
            raise AssertionError(path + ": numeric")
        if comparison is not None:
            comparison["numeric_comparisons"] += 1
            if path.endswith((".controls", ".augmented", ".pastmean")):
                comparison["prediction_comparisons"] += 1
                comparison["maximum_absolute_prediction_error"] = max(
                    comparison["maximum_absolute_prediction_error"], abs(actual - expected)
                )
    elif actual != expected or type(actual) is not type(expected):
        raise AssertionError(path + ": exact value/null/type")


def verify_statistics(features, labels, calendar, reported, *, flat_eligible):
    expected = recompute(features, labels, calendar, flat_eligible=flat_eligible)
    comparison = dict(
        numeric_comparisons=0,
        prediction_comparisons=0,
        maximum_absolute_prediction_error=0.0,
        near_singular_condition_diagnostics=[],
    )
    assert_equal(reported, expected, comparison=comparison)
    return dict(
        status="PASS",
        arithmetic_only=True,
        bootstrap_records_checked=4000,
        scopes=["all", "causal_original_policy_flat_eligible"],
        scope_mask_only_targets=True,
        labels=list(LABELS),
        full_axis_n=len(features),
        new_accounts=0,
        scientific_or_economic_acceptance=False,
        comparison=comparison,
    )
