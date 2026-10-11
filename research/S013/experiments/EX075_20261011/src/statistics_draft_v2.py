"""Pure fixed standby statistics. No file, provider, account or registry I/O."""

from collections import Counter

import numpy as np
import pandas as pd
from scipy.stats import rankdata

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
    "mean_negative_body",
    "past_volume_shape_projection",
)
COMPONENT = "down_volume_cov"
LABELS = ("return4_net", "downside4_oc")
YEARS = tuple(range(2021, 2027))


def finite(*values):
    mask = np.ones(len(values[0]), dtype=bool)
    for value in values:
        mask &= np.isfinite(value) if value.ndim == 1 else np.isfinite(value).all(axis=1)
    return mask


def correlation(x, y, controls=None):
    """All controls retained; actual rank, residual DF and norms explicit."""
    mask = finite(x, y) if controls is None else finite(x, y, controls)
    n = int(mask.sum())
    result = {
        "n": n,
        "finite_positions": np.flatnonzero(mask).tolist(),
        "value": None,
        "reason": None,
        "design_rank": None,
        "residual_df": None,
        "singular_values": None,
        "condition_number": None,
        "component_residual_fraction": None,
        "target_residual_fraction": None,
    }
    a, b = rankdata(x[mask], method="average"), rankdata(y[mask], method="average")
    a, b = a - a.mean() if n else a, b - b.mean() if n else b
    design = None
    if controls is not None:
        design = np.column_stack([np.ones(n), *(rankdata(c) for c in controls[mask].T)])
        singular = np.linalg.svd(design, compute_uv=False)
        rank = int(np.linalg.matrix_rank(design)) if n else 0
        result.update(
            design_rank=rank,
            residual_df=n - rank,
            singular_values=singular.tolist(),
            condition_number=float(singular[0] / singular[-1])
            if len(singular) and singular[-1] > 0
            else None,
        )
    if n < 20:
        result["reason"] = "INSUFFICIENT_SAMPLE"
        return result
    if controls is not None and result["residual_df"] < 10:
        result["reason"] = "INSUFFICIENT_RESIDUAL_DF"
        return result
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        result["reason"] = "CONSTANT_COMPONENT" if na == 0 else "CONSTANT_TARGET"
        return result
    if design is not None:
        a -= design @ np.linalg.lstsq(design, a, rcond=None)[0]
        b -= design @ np.linalg.lstsq(design, b, rcond=None)[0]
        result["component_residual_fraction"] = float(np.linalg.norm(a) / na)
        result["target_residual_fraction"] = float(np.linalg.norm(b) / nb)
        if np.linalg.norm(a) <= 1e-10 * na or np.linalg.norm(b) <= 1e-10 * nb:
            result["reason"] = (
                "EXPLAINED_COMPONENT"
                if np.linalg.norm(a) <= 1e-10 * na
                else "TARGET_EXPLAINED_OR_CONSTANT"
            )
            return result
    result["value"] = float(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))
    return result


def block_indices(n):
    if n < 40:
        return None
    starts = np.random.default_rng(13).integers(0, n - 39, size=(500, (n + 39) // 40))
    return (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]


def bootstrap(x, y, controls, sampled):
    """Full axis sampled BEFORE finite filtering; every status preserved."""
    records = []
    for i in range(500):
        if sampled is None:
            record = {
                "replicate": i,
                "value": None,
                "reason": "INSUFFICIENT_FULL_AXIS",
                "n": 0,
                "design_rank": None,
                "residual_df": None,
            }
        else:
            pos = sampled[i]
            record = correlation(x[pos], y[pos], None if controls is None else controls[pos])
            record.pop("finite_positions")
            record["replicate"] = i
        records.append(record)
    values = [r["value"] for r in records if r["value"] is not None]
    return {
        "requested": 500,
        "valid": len(values),
        "replicates": records,
        "status_counts": dict(Counter(r["reason"] or "VALID" for r in records)),
        "ic95": np.quantile(values, [0.025, 0.975], method="linear").tolist()
        if len(values) >= 400
        else None,
        "reason": None if len(values) >= 400 else "INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES",
    }


def ecdf(train, values):
    ordered = np.sort(train)
    return (
        np.searchsorted(ordered, values, "left") + np.searchsorted(ordered, values, "right")
    ) / (2 * len(train))


def ridge(train, target, test):
    mean, target_mean = train.mean(axis=0), target.mean()
    centered = train - mean
    slope = np.linalg.solve(
        centered.T @ centered + 10 * np.eye(train.shape[1]), centered.T @ (target - target_mean)
    )
    return target_mean + (test - mean) @ slope


def metrics(records):
    if len(records) < 20:
        return {
            "n": len(records),
            "reason": "INSUFFICIENT_TEST_SAMPLE",
            "mse_controls": None,
            "mse_augmented": None,
            "mse_pastmean": None,
            "delta_controls": None,
            "delta_pastmean": None,
            "ic_controls": None,
            "ic_augmented": None,
        }
    y = np.array([r["target"] for r in records])
    out = {"n": len(records), "reason": None}
    for name in ("controls", "augmented", "pastmean"):
        pred = np.array([r[name] for r in records])
        out["mse_" + name] = float(np.mean((y - pred) ** 2))
        if name != "pastmean":
            out["ic_" + name] = correlation(pred, y)
    out["delta_controls"] = out["mse_controls"] - out["mse_augmented"]
    out["delta_pastmean"] = out["mse_pastmean"] - out["mse_augmented"]
    return out


def walk_forward(index, all_x, target, ends):
    common = finite(all_x, target)
    yearly, records = {}, []
    for year in YEARS:
        days = index[index.year == year]
        start = days[0] if len(days) else None
        tr = (
            np.zeros(len(index), bool)
            if start is None
            else common & (index.year >= 2020) & (index.year < year) & (ends < start).to_numpy()
        )
        te = common & (index.year == year)
        row = {
            "first_actual_signaldate": start.isoformat() if start is not None else None,
            "train_positions": np.flatnonzero(tr).tolist(),
            "test_positions": np.flatnonzero(te).tolist(),
            "train_n": int(tr.sum()),
            "test_n": int(te.sum()),
            "latest_train_label_end": ends[tr].max().isoformat() if tr.any() else None,
        }
        reason = (
            "NO_TEST_YEAR"
            if start is None
            else "INSUFFICIENT_TRAIN_SAMPLE"
            if tr.sum() < 40
            else "INSUFFICIENT_TEST_SAMPLE"
            if te.sum() < 20
            else None
        )
        row["reason"] = reason
        local = []
        if reason is None:
            train = np.column_stack([ecdf(col, col) for col in all_x[tr].T])
            test = np.column_stack([ecdf(col, val) for col, val in zip(all_x[tr].T, all_x[te].T)])
            controls = ridge(train[:, :18], target[tr], test[:, :18])
            augmented = ridge(train, target[tr], test)
            mean = float(target[tr].mean())
            local = [
                {
                    "position": int(p),
                    "signaldate": index[p].isoformat(),
                    "target": float(y),
                    "controls": float(c),
                    "augmented": float(a),
                    "pastmean": mean,
                }
                for p, y, c, a in zip(np.flatnonzero(te), target[te], controls, augmented)
            ]
        row["metrics"] = metrics(local)
        records.extend(local)
        yearly[str(year)] = row
    return {"yearly": yearly, "aggregate": metrics(records), "records": records}


def validate(features, labels, price_calendar=None):
    index = features.index
    if (
        not isinstance(index, pd.DatetimeIndex)
        or not index.equals(labels.index)
        or index.has_duplicates
        or index.hasnans
        or index.tz is not None
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("unique aligned ordered timezone-naive full-session axis required")
    if features.columns.has_duplicates or labels.columns.has_duplicates:
        raise ValueError("duplicate columns prohibited")
    if (
        not isinstance(price_calendar, pd.DatetimeIndex)
        or price_calendar.has_duplicates
        or price_calendar.hasnans
        or price_calendar.tz is not None
        or not price_calendar.is_monotonic_increasing
        or not price_calendar.equals(price_calendar.normalize())
        or not index.isin(price_calendar).all()
    ):
        raise ValueError("authenticated complete ordered session price calendar required")
    if set(LABELS).intersection(features.columns) or any(
        str(c).startswith("label_end") for c in features
    ):
        raise ValueError("future labels prohibited in feature frame")
    if not set((*CONTROLS, COMPONENT)).issubset(features) or not set(
        (*LABELS, "label_end4")
    ).issubset(labels):
        raise ValueError("fixed19 features/two labels/maturity required")
    all_x = features[[*CONTROLS, COMPONENT]].to_numpy(float)
    if np.isinf(all_x).any():
        raise ValueError("infinite inputs prohibited; missing explicit unavailable")
    ends = pd.to_datetime(labels["label_end4"], errors="raise")
    if ends.dt.tz is not None:
        raise ValueError("timezone-naive maturity required")
    expected = pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    positions = price_calendar.get_indexer(index) + 5
    available = positions < len(price_calendar)
    expected.iloc[np.flatnonzero(available)] = price_calendar[positions[available]].to_numpy()
    for name in LABELS:
        y = labels[name].to_numpy(float)
        good = np.isfinite(y)
        if np.isinf(y).any() or (good & (ends.isna() | (ends != expected)).to_numpy()).any():
            raise ValueError("finite labels require exact full-axis T+5 OPEN maturity")
        if name == "downside4_oc" and (good & ((y < 0) | (y >= 1))).any():
            raise ValueError("O/C downside must lie in [0,1)")
        if name == "return4_net" and (good & (y <= -1)).any():
            raise ValueError("positive-price net return must exceed -1")
    return index, all_x, ends


def analyze(features, labels, price_calendar=None):
    """Caller must obtain separate authorization before any real input call."""
    index, all_x, ends = validate(features, labels, price_calendar)
    component, controls = all_x[:, -1], all_x[:, :18]
    sampled, positions = block_indices(len(index)), np.arange(len(index))
    result = {
        "status": "DESCRIPTIVE_STATISTICS_NOT_SCIENTIFIC_OR_ECONOMIC_ACCEPTANCE",
        "full_axis_n": len(index),
        "labels": {},
    }
    for name in LABELS:
        target = labels[name].to_numpy(float)
        panel = {
            "raw": correlation(component, target),
            "partial": correlation(component, target, controls),
            "raw_bootstrap": bootstrap(component, target, None, sampled),
            "partial_bootstrap": bootstrap(component, target, controls, sampled),
            "years": {},
            "phases": {},
            "walk_forward": walk_forward(index, all_x, target, ends),
        }
        for year in sorted(set(index.year)):
            mask = index.year == year
            panel["years"][str(year)] = {
                "raw": correlation(component[mask], target[mask]),
                "partial": correlation(component[mask], target[mask], controls[mask]),
            }
        for phase in range(5):
            mask = positions % 5 == phase
            panel["phases"][str(phase)] = {
                "raw": correlation(component[mask], target[mask]),
                "partial": correlation(component[mask], target[mask], controls[mask]),
            }
        result["labels"][name] = panel
    return result
