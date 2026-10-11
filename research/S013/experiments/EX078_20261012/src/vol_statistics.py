"""Fixed prospective volatility-concentration continuation statistics; no market/account I/O."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

COMPONENTS = ("vol_concentration",)
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
    "early_volume_reclaim",
    "total_down",
    "total_up",
    "early_down_share",
    "max_down_run_share",
    "holding_age",
    "entry_mark_pnl",
    "known_falling",
    "late_recovery",
    "log_sigma20",
)
HORIZONS = {
    "return_4": 4,
    "downside_4": 4,
}
YEARS = tuple(range(2021, 2027))
METHOD = {
    "version": "s013-held-vol-concentration-fixed4-20-v1",
    "components": list(COMPONENTS),
    "controls": list(CONTROLS),
    "labels": HORIZONS,
    "component_definition": "vol_concentration=population std of last4 complete Close logreturns / population std of last20 complete Close logreturns; fixed windows4/20, no fitted thresholds; insufficient/zero20 denominator NaN",
    "nuisance_definition": "log_sigma20 is std20 OF LOGRETURNS, NOT logarithm of std20; positive available sigma20 only",
    "expected_signs": {"return_4": "negative", "downside_4": "positive"},
    "interpretation": "Observed O/C price downside is not native account DD or executable profitability. Return not clearly harmed is only a subsequent research clue, never a new acceptance gate. Negative/boundary evidence retained; no sign flip, window search, account escalation or EX077 rescue.",
    "label_contract": {
        "return_h": "Open[T+1+h]/Open[T+1]-1; same future/current SELL fee cancels, no new BUY fee",
        "downside_h": "max(0,1-min(Open/Close T+1..T+h and finalOpen[T+1+h])/Open[T+1]); fixed daily observation downside, not path/account DD",
        "negative_gap_next": "Initial Tclose-to-nextOpen gap retained for accounting attribution only; both T+1 decision alternatives share it",
        "maturity_columns": "label_end_<label>; first test signal strictly after train label maturity",
    },
    "correlation": "Spearman average ties; partial rank IC uses OLS residuals with intercept and all twenty-four fixed controls, restoring late_recovery and adding log_sigma20, partial residual DF n-rank(design)>=10 required; otherwise unavailable, recording design_rank/residual_df; residual norm <=1e-10 of original centered-rank norm is explained/unavailable",
    "minimum_correlation_n": 20,
    "non_overlap": "h+1 phases fixed by original full signal index positions before finite/opportunity filtering",
    "bootstrap": {
        "replicates": 500,
        "block_sessions": 40,
        "seed": 13,
        "sampling": "overlapping full-time-axis blocks, uniform starts, truncate to original length; filter opportunity after sampling",
        "interval": "2.5/97.5% linear quantiles; at least 400 valid replicates",
        "scope": "only actual_signal_continue predeclared scope; descriptive, no search-selection correction",
    },
    "walk_forward": {
        "test_years": list(YEARS),
        "initial_train_year": 2020,
        "train": "2020 <= signal year < test year AND label_end_label < first actual test-year signaldate",
        "groups": "train feature Q25/Q75 linear; test low <= Q25, high >= Q75; original label means",
        "ridge": "rank features via train empirical CDF midpoint ties; original target; intercept unpenalized; alpha=10",
        "models": ["controls", "controls+concentration"],
        "common_model_rows": "all 25 feature columns finite, target finite, training target mature; identical model rows",
        "minimum_train_n": 40,
        "minimum_test_n": 20,
        "baseline": "training target mean on identical training rows; compare test MSE and Spearman IC",
    },
    "scope": "actual_signal_continue only; actualT quantity>0 AND currentT next-session target1; no flat zero imputation; no profitable-row selection",
    "limitations": [
        "Already-seen development pool; chronological pseudo-out-of-sample, not sealed independent validation.",
        "No hyperparameter search; all labels, years, phases, components and failures retained.",
        "Future labels never enter feature columns, ECDF, thresholds, or fitting before maturity.",
        "Intervals are descriptive diagnostics and do not correct development-pool selection bias.",
    ],
}
MIN_N = 20
MIN_TRAIN = 40


def _finite(*arrays: np.ndarray) -> np.ndarray:
    good = np.ones(len(arrays[0]), dtype=bool)
    for arr in arrays:
        good &= np.isfinite(arr) if arr.ndim == 1 else np.isfinite(arr).all(axis=1)
    return good


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    x, y = x - x.mean(), y - y.mean()
    scale = float(np.linalg.norm(x) * np.linalg.norm(y))
    if scale <= np.finfo(float).eps * max(1.0, float(len(x))):
        return None
    return float(np.clip(x @ y / scale, -1.0, 1.0))


def _ic(x: np.ndarray, y: np.ndarray, controls: np.ndarray | None = None) -> dict:
    good = _finite(x, y) if controls is None else _finite(x, y, controls)
    n = int(good.sum())
    metadata = {"n": n, "design_rank": None, "residual_df": None}
    design = None
    if controls is not None:
        design = np.column_stack(
            [np.ones(n), *(rankdata(col, method="average") for col in controls[good].T)]
        )
        design_rank = int(np.linalg.matrix_rank(design)) if n else 0
        metadata.update(design_rank=design_rank, residual_df=n - design_rank)
        if n - design_rank < 10:
            return {**metadata, "value": None, "reason": "INSUFFICIENT_RESIDUAL_DF"}
    if n < MIN_N:
        return {**metadata, "value": None, "reason": "INSUFFICIENT_SAMPLE"}
    if np.ptp(x[good]) == 0 or np.ptp(y[good]) == 0:
        return {**metadata, "value": None, "reason": "CONSTANT_COMPONENT_OR_LABEL"}
    xr, yr = rankdata(x[good], method="average"), rankdata(y[good], method="average")
    if design is not None:
        x_norm, y_norm = np.linalg.norm(xr - xr.mean()), np.linalg.norm(yr - yr.mean())
        xr = xr - design @ np.linalg.lstsq(design, xr, rcond=None)[0]
        yr = yr - design @ np.linalg.lstsq(design, yr, rcond=None)[0]
        if np.linalg.norm(xr) <= 1e-10 * x_norm or np.linalg.norm(yr) <= 1e-10 * y_norm:
            return {**metadata, "value": None, "reason": "CONSTANT_OR_EXPLAINED_RESIDUAL"}
    value = _pearson(xr, yr)
    return {
        **metadata,
        "value": value,
        "reason": None if value is not None else "CONSTANT_OR_EXPLAINED_RESIDUAL",
    }


def _cdf_apply(train: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Training empirical CDF midpoint ties; test extremes map exactly to 0/1."""
    ordered = np.sort(train)
    return (
        np.searchsorted(ordered, values, side="left")
        + np.searchsorted(ordered, values, side="right")
    ) / (2.0 * len(train))


def _ridge_predict(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    mean_x, mean_y = train_x.mean(axis=0), float(train_y.mean())
    centered = train_x - mean_x
    slopes = np.linalg.solve(
        centered.T @ centered + 10.0 * np.eye(train_x.shape[1]), centered.T @ (train_y - mean_y)
    )
    return mean_y + (test_x - mean_x) @ slopes


def _prediction_metrics(y: np.ndarray, prediction: np.ndarray, baseline: np.ndarray) -> dict:
    n = len(y)
    if n < MIN_N:
        return {
            "n": n,
            "mse": None,
            "baseline_mse": None,
            "mse_improvement": None,
            "ic": None,
            "reason": "INSUFFICIENT_SAMPLE",
        }
    mse, base = float(np.mean((y - prediction) ** 2)), float(np.mean((y - baseline) ** 2))
    ic = _ic(prediction, y)
    return {
        "n": n,
        "mse": mse,
        "baseline_mse": base,
        "mse_improvement": base - mse,
        "ic": ic["value"],
        "ic_reason": ic["reason"],
        "reason": None,
    }


def _bootstrap_indices(n: int) -> np.ndarray | None:
    if n < 40:
        return None
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 40 + 1, size=(500, (n + 39) // 40))
    return (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]


def _bootstrap(
    x: np.ndarray,
    y: np.ndarray,
    controls: np.ndarray,
    scope: np.ndarray,
    sampled: np.ndarray | None,
    partial: bool,
) -> dict:
    values = []
    if sampled is not None:
        for row in sampled:
            row = row[scope[row]]
            value = _ic(x[row], y[row], controls[row] if partial else None)["value"]
            if value is not None:
                values.append(value)
    sufficient = len(values) >= 400
    return {
        "requested_replicates": 500,
        "valid_replicates": len(values),
        "ic95": np.quantile(values, [0.025, 0.975], method="linear").tolist()
        if sufficient
        else None,
        "reason": None if sufficient else "INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES",
        "diagnostic_only": True,
        "search_selection_corrected": False,
    }


def _year_train_mask(
    index: pd.DatetimeIndex, label_end: pd.Series, scope: np.ndarray, year: int
) -> tuple[np.ndarray, np.ndarray, pd.Timestamp | None]:
    actual = index[index.year == year]
    start = actual[0] if len(actual) else None
    test = scope & (index.year == year)
    train = (
        np.zeros(len(index), dtype=bool)
        if start is None
        else (
            scope
            & (index.year >= 2020)
            & (index.year < year)
            & (label_end < start).to_numpy(dtype=bool)
        )
    )
    return train, test, start


def _walk_forward(
    index: pd.DatetimeIndex,
    feature_frame: pd.DataFrame,
    target: np.ndarray,
    label_end: pd.Series,
    scope: np.ndarray,
) -> dict:
    all_x = feature_frame.loc[:, [*CONTROLS, *COMPONENTS]].to_numpy(dtype=float)
    n_controls = len(CONTROLS)
    model_columns = {
        "controls": list(range(n_controls)),
        "controls+concentration": [*range(n_controls), n_controls],
    }
    yearly, records = {}, {name: [] for name in model_columns}
    group_records = {name: {"low": [], "high": []} for name in COMPONENTS}
    for year in YEARS:
        train, test, start = _year_train_mask(index, label_end, scope, year)
        row = {
            "first_actual_signaldate": start.isoformat() if start is not None else None,
            "groups": {},
            "models": {},
        }
        for component in COMPONENTS:
            x = feature_frame[component].to_numpy(dtype=float)
            tr = train & _finite(x, target)
            te = test & _finite(x, target)
            group = {
                "train_n": int(tr.sum()),
                "test_n": int(te.sum()),
                "q25": None,
                "q75": None,
                "low": {"n": 0, "mean": None},
                "high": {"n": 0, "mean": None},
                "high_minus_low": None,
            }
            if tr.sum() < MIN_TRAIN:
                group["reason"] = "INSUFFICIENT_TRAIN_SAMPLE"
            elif np.ptp(x[tr]) == 0:
                group["reason"] = "CONSTANT_TRAIN_COMPONENT"
            elif te.sum() < MIN_N:
                group["reason"] = "INSUFFICIENT_TEST_SAMPLE"
            else:
                q25, q75 = np.quantile(x[tr], [0.25, 0.75], method="linear")
                group.update(q25=float(q25), q75=float(q75), reason=None)
                group["overlap_n"] = int((te & (x <= q25) & (x >= q75)).sum())
                for key, selected in (("low", te & (x <= q25)), ("high", te & (x >= q75))):
                    n = int(selected.sum())
                    group[key] = {
                        "n": n,
                        "mean": float(target[selected].mean()) if n >= MIN_N else None,
                        "reason": None if n >= MIN_N else "INSUFFICIENT_GROUP_SAMPLE",
                    }
                    group_records[component][key].extend(target[selected].tolist())
                if group["low"]["mean"] is not None and group["high"]["mean"] is not None:
                    group["high_minus_low"] = group["high"]["mean"] - group["low"]["mean"]
            row["groups"][component] = group
        tr = train & _finite(all_x, target)
        te = test & _finite(all_x, target)
        row["common_train_n"], row["common_test_n"] = int(tr.sum()), int(te.sum())
        row["latest_train_label_end"] = label_end[tr].max().isoformat() if tr.any() else None
        reason = (
            "INSUFFICIENT_TRAIN_SAMPLE"
            if tr.sum() < MIN_TRAIN
            else "INSUFFICIENT_TEST_SAMPLE"
            if te.sum() < MIN_N
            else "CONSTANT_TRAIN_LABEL"
            if np.ptp(target[tr]) == 0
            else None
        )
        if reason is not None:
            for name in model_columns:
                row["models"][name] = {
                    "n": int(te.sum()),
                    "mse": None,
                    "baseline_mse": None,
                    "mse_improvement": None,
                    "ic": None,
                    "reason": reason,
                }
        else:
            ranked_train = np.column_stack([_cdf_apply(col, col) for col in all_x[tr].T])
            ranked_test = np.column_stack(
                [_cdf_apply(col, val) for col, val in zip(all_x[tr].T, all_x[te].T)]
            )
            baseline = np.full(te.sum(), target[tr].mean())
            for name, cols in model_columns.items():
                prediction = _ridge_predict(ranked_train[:, cols], target[tr], ranked_test[:, cols])
                row["models"][name] = _prediction_metrics(target[te], prediction, baseline)
                records[name].extend(
                    {
                        "signaldate": date.isoformat(),
                        "target": float(y),
                        "prediction": float(p),
                        "baseline": float(b),
                    }
                    for date, y, p, b in zip(index[te], target[te], prediction, baseline)
                )
        yearly[str(year)] = row
    aggregate = {}
    for name, recs in records.items():
        aggregate[name] = _prediction_metrics(
            np.array([r["target"] for r in recs]),
            np.array([r["prediction"] for r in recs]),
            np.array([r["baseline"] for r in recs]),
        )
    groups = {}
    for component, values in group_records.items():
        groups[component] = {}
        for key, vals in values.items():
            groups[component][key] = {
                "n": len(vals),
                "mean": float(np.mean(vals)) if len(vals) >= MIN_N else None,
                "reason": None if len(vals) >= MIN_N else "INSUFFICIENT_GROUP_SAMPLE",
            }
        lo, hi = groups[component]["low"]["mean"], groups[component]["high"]["mean"]
        groups[component]["high_minus_low"] = hi - lo if hi is not None and lo is not None else None
    return {
        "yearly": yearly,
        "aggregate_models": aggregate,
        "aggregate_groups": groups,
        "prediction_records": records,
    }


def analyze(
    features: pd.DataFrame, labels: pd.DataFrame, opportunity: pd.Series | None = None
) -> dict:
    """Retain every declared descriptive test, with explicit unavailable reasons."""
    if not isinstance(features.index, pd.DatetimeIndex) or not features.index.equals(labels.index):
        raise ValueError("features/labels require identical DatetimeIndex")
    if not features.index.is_monotonic_increasing or features.index.has_duplicates:
        raise ValueError("signaldate must be unique and increasing")
    if features.index.tz is not None:
        raise ValueError("timezone-naive signal dates required")
    if set(HORIZONS).intersection(features.columns) or any(
        str(c).startswith("label_end_") for c in features.columns
    ):
        raise ValueError("future labels prohibited in feature frame")
    if features.columns.has_duplicates or labels.columns.has_duplicates:
        raise ValueError("duplicate columns prohibited")
    required = [*CONTROLS, *COMPONENTS]
    missing = set(required) - set(features.columns)
    missing_labels = {c for label in HORIZONS for c in (label, f"label_end_{label}")} - set(
        labels.columns
    )
    if missing or missing_labels:
        raise ValueError(f"missing required columns: {sorted(missing | missing_labels)}")
    data = features.loc[:, required].astype(float)
    if np.isinf(data.to_numpy()).any():
        raise ValueError("infinite feature prohibited")
    if not isinstance(opportunity, pd.DataFrame) or not features.index.equals(opportunity.index):
        raise ValueError("Aligned predeclared scope frame required")
    if tuple(opportunity.columns) != ("actual_signal_continue",):
        raise ValueError("Only fixed actual_signal_continue scope required")
    if (
        any(not pd.api.types.is_bool_dtype(opportunity[c].dtype) for c in opportunity)
        or opportunity.isna().any().any()
    ):
        raise ValueError("Non-null boolean scopes required")
    scope_masks = {c: opportunity[c].to_numpy(bool) for c in opportunity}
    index, positions = features.index, np.arange(len(features))
    controls = data.loc[:, list(CONTROLS)].to_numpy(dtype=float)
    sampled = _bootstrap_indices(len(features))
    result = {
        "method": METHOD,
        "method_sha256": hashlib.sha256(
            json.dumps(METHOD, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "signal_n": len(features),
        "scopes": {},
    }
    for scope_name, scope in scope_masks.items():
        panel = {"eligible_n": int(scope.sum()), "labels": {}}
        for label, horizon in HORIZONS.items():
            target = labels[label].to_numpy(dtype=float)
            ends = pd.to_datetime(labels[f"label_end_{label}"], errors="raise")
            finite = np.isfinite(target)
            if np.isinf(target).any() or (finite & ends.isna().to_numpy()).any():
                raise ValueError(f"invalid target/maturity: {label}")
            if (finite & (ends <= index).to_numpy()).any():
                raise ValueError(f"future label must mature after signal: {label}")
            if label.startswith("downside") and (finite & (target < 0)).any():
                raise ValueError("downside must be nonnegative adverse magnitude")
            if label == "negative_gap_next" and (finite & ~np.isin(target, [0.0, 1.0])).any():
                raise ValueError("negative_gap_next must be 0/1")
            entry = {"finite_target_n": int((scope & finite).sum()), "components": {}}
            for component in COMPONENTS:
                x = data[component].to_numpy(dtype=float)
                pairs = {
                    "spearman": _ic(x[scope], target[scope]),
                    "partial_rank_ic": _ic(x[scope], target[scope], controls[scope]),
                }
                pairs["yearly"] = {}
                for year in sorted(set(index.year)):
                    subset = scope & (index.year == year)
                    pairs["yearly"][str(year)] = {
                        "spearman": _ic(x[subset], target[subset]),
                        "partial_rank_ic": _ic(x[subset], target[subset], controls[subset]),
                    }
                pairs["nonoverlap_phases"] = {}
                for phase in range(horizon + 1):
                    subset = scope & (positions % (horizon + 1) == phase)
                    pairs["nonoverlap_phases"][str(phase)] = {
                        "spearman": _ic(x[subset], target[subset]),
                        "partial_rank_ic": _ic(x[subset], target[subset], controls[subset]),
                    }
                pairs["spearman_block_ic95"] = _bootstrap(
                    x, target, controls, scope, sampled, False
                )
                pairs["partial_block_ic95"] = _bootstrap(x, target, controls, scope, sampled, True)
                entry["components"][component] = pairs
            entry["walk_forward"] = _walk_forward(index, data, target, ends, scope)
            panel["labels"][label] = entry
        result["scopes"][scope_name] = panel
    return result


def write_method(path: str | Path) -> None:
    """Write fixed method only; caller decides authorized destination."""
    source = Path(__file__).read_bytes()
    payload = {
        "method": METHOD,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "method_sha256": hashlib.sha256(
            json.dumps(METHOD, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
