"""Independent loops/linear algebra. No file/provider/account execution IO."""

from collections import Counter
from hashlib import sha256
import json
from math import fsum, sqrt
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
COMPONENT = "vol_concentration"
LABELS = ("return_4", "downside_4")
SCOPE = "actual_signal_continue"


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


def dates(index):
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.tz is not None
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("complete ordered normalized session axis required")
    return index.as_unit("ns")


def component(close):
    axis = dates(close.index)
    values = [float(value) for value in close]
    if not all(np.isfinite(value) and value > 0 for value in values):
        raise ValueError("positive finite Close; no fill")
    logs = [float(np.log(value)) for value in values]
    changes = [logs[p] - logs[p - 1] for p in range(1, len(logs))]
    rows = []
    for p in range(len(values)):
        observed = []
        for width in (4, 20):
            if p < width:
                observed.append(float("nan"))
            else:
                window = changes[p - width : p]
                mean = fsum(window) / width
                observed.append(sqrt(fsum((value - mean) ** 2 for value in window) / width))
        s4, s20 = observed
        usable = np.isfinite(s20) and s20 > 0
        rows.append(
            dict(
                vol_concentration=s4 / s20 if usable else np.nan,
                log_sigma20=s20 if usable else np.nan,
                sigma4=s4,
                sigma20=s20,
                unavailable_reason=None
                if usable
                else "ZERO_SIGMA20"
                if s20 == 0
                else "INSUFFICIENT_20_COMPLETE_RETURNS",
            )
        )
    result = pd.DataFrame(rows, index=axis)
    result.unavailable_reason = result.unavailable_reason.astype("string")
    return result


def held_state(account, fills, decisions, sessions):
    sessions = dates(sessions)
    ledger = account.set_index("date").copy()
    ledger.index = dates(pd.DatetimeIndex(pd.to_datetime(ledger.index)))
    if not sessions.isin(ledger.index).all() or ledger.iloc[0].quantity_before != 0:
        raise ValueError("T-close ledger rows and original zero opening required")
    after, before = {}, {}
    for row in decisions.itertuples():
        t, executed = (
            pd.Timestamp(row.signal_date).normalize(),
            pd.Timestamp(row.valid_session).normalize(),
        )
        if t in after or executed in before or row.target_position not in (0, 1):
            raise ValueError("unique original binary decision coordinates required")
        after[t], before[executed] = bool(row.target_position), bool(row.target_position)
    grouped = {}
    previous_time = None
    seen = set()
    for row in fills.itertuples():
        time = pd.Timestamp(row.fill_time)
        if (
            time.tz is not None
            or pd.isna(time)
            or (previous_time is not None and time < previous_time)
            or row.fill_id in seen
        ):
            raise ValueError("chronological unique observed fills required")
        if pd.Timestamp(
            row.signal_date
        ).normalize() >= time.normalize() or time - time.normalize() > pd.Timedelta(hours=15):
            raise ValueError("fill must be known at T-close and prior signal")
        if (
            row.side not in ("BUY", "SELL")
            or not np.isfinite(row.price)
            or row.price <= 0
            or row.quantity != int(row.quantity)
            or row.quantity <= 0
        ):
            raise ValueError("valid positive integer BUY/SELL")
        seen.add(row.fill_id)
        previous_time = time
        grouped.setdefault(time.normalize(), []).append(row)
    quantity, cost, entry = 0, None, None
    rows = {}
    for age_index, (day, row) in enumerate(ledger.iterrows()):
        if day > sessions[-1]:
            break
        if int(row.quantity_before) != quantity:
            raise AssertionError("quantity before differs from past fills")
        for fill in grouped.pop(day, []):
            units = int(fill.quantity)
            if fill.side == "BUY":
                if quantity == 0:
                    entry, cost = age_index, float(fill.price)
                else:
                    cost = (quantity * cost + units * fill.price) / (quantity + units)
                quantity += units
            else:
                quantity -= units
                if quantity < 0:
                    raise AssertionError("short holding")
                if quantity == 0:
                    entry = cost = None
        if row.quantity != quantity or not np.isfinite(row.close) or row.close <= 0:
            raise AssertionError("T known quantity/Close invalid")
        if day not in sessions:
            continue
        rows[day] = dict(
            actual_quantity=quantity,
            actual_held=quantity > 0,
            entry_gross_price=cost if quantity else np.nan,
            entry_mark_pnl=float(row.close) / cost - 1 if quantity else np.nan,
            entry_session=ledger.index[entry] if quantity else pd.NaT,
            holding_age=age_index - entry + 1 if quantity else np.nan,
            signal_held_before=before[day],
            signal_held_after=after[day],
        )
    if any(day <= sessions[-1] for day in grouped):
        raise AssertionError("fill absent from original account calendar")
    return pd.DataFrame.from_dict(rows, orient="index").reindex(sessions)


def continuation_labels(prices, sessions):
    axis, sessions = dates(prices.index), dates(sessions)
    values = prices[["Open", "Close"]].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("positive finite OPEN/CLOSE required")
    position = {day: p for p, day in enumerate(axis)}
    rows = []
    for day in sessions:
        p = position[day]
        if p + 5 >= len(axis):
            rows.append(
                dict(
                    return_4=np.nan,
                    downside_4=np.nan,
                    label_end_return_4=pd.NaT,
                    label_end_downside_4=pd.NaT,
                )
            )
            continue
        opening = float(values[p + 1, 0])
        terminal = float(values[p + 5, 0])
        observed = [terminal]
        for q in range(p + 1, p + 5):
            observed.extend([float(values[q, 0]), float(values[q, 1])])
        rows.append(
            dict(
                return_4=terminal / opening - 1,
                downside_4=max(0, 1 - min(observed) / opening),
                label_end_return_4=axis[p + 5],
                label_end_downside_4=axis[p + 5],
            )
        )
    return pd.DataFrame(rows, index=sessions)


def verify_inputs(old, warm_close, prices, account, fills, decisions, reported):
    """Caller first authenticates original public/native identities; in-memory only."""
    grid = dates(old.index)
    state = held_state(account, fills, decisions, grid)
    observed = component(warm_close).reindex(grid)
    labels = continuation_labels(prices, grid)
    scope = pd.DataFrame({SCOPE: state.actual_held & state.signal_held_after}, index=grid)
    features = pd.DataFrame(index=grid)
    for name in CONTROLS:
        features[name] = (
            state[name]
            if name in ("holding_age", "entry_mark_pnl")
            else (
                old.momentum20.lt(0).astype(float)
                if name == "known_falling"
                else observed.log_sigma20
                if name == "log_sigma20"
                else old[name]
            )
        )
    features[COMPONENT] = observed[COMPONENT]
    expected = dict(features=features, labels=labels, scope=scope, state=state)
    # construct's public six-tuple omits this debug table; its two economic
    # coordinates are already independently checked in features above.
    if "component" in reported:
        expected["component"] = observed
    for name, frame in expected.items():
        if not frame.index.equals(reported[name].index) or set(frame.columns) != set(
            reported[name].columns
        ):
            raise AssertionError(name + ": exact frame coordinates")
        for col in frame:
            if pd.api.types.is_numeric_dtype(frame[col]) and not pd.api.types.is_bool_dtype(
                frame[col]
            ):
                np.testing.assert_allclose(
                    reported[name][col], frame[col], rtol=2e-10, atol=2e-12, equal_nan=True
                )
            else:
                pd.testing.assert_series_equal(reported[name][col], frame[col], check_names=False)
    return dict(
        status="PASS", actual_scope_n=int(scope[SCOPE].sum()), signal_n=len(grid), new_accounts=0
    )


def ic(x, y, controls=None):
    good = np.isfinite(x) & np.isfinite(y)
    if controls is not None:
        good &= np.isfinite(controls).all(axis=1)
    n = int(good.sum())
    meta = dict(n=n, design_rank=None, residual_df=None)
    basis = None
    if controls is not None:
        matrix = np.column_stack([np.ones(n), *(ranks(col) for col in controls[good].T)])
        u, s, _ = np.linalg.svd(matrix, full_matrices=False)
        threshold = s[0] * max(matrix.shape) * np.finfo(float).eps if len(s) else 0
        rank = int(sum(value > threshold for value in s))
        basis = u[:, :rank]
        meta.update(design_rank=rank, residual_df=n - rank)
        if n - rank < 10:
            return dict(meta, value=None, reason="INSUFFICIENT_RESIDUAL_DF")
    if n < 20:
        return dict(meta, value=None, reason="INSUFFICIENT_SAMPLE")
    a, b = ranks(x[good]), ranks(y[good])
    a -= a.mean()
    b -= b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return dict(meta, value=None, reason="CONSTANT_COMPONENT_OR_LABEL")
    if basis is not None:
        a -= basis @ (basis.T @ a)
        b -= basis @ (basis.T @ b)
        if np.linalg.norm(a) <= 1e-10 * na or np.linalg.norm(b) <= 1e-10 * nb:
            return dict(meta, value=None, reason="CONSTANT_OR_EXPLAINED_RESIDUAL")
    product = float(np.linalg.norm(a) * np.linalg.norm(b))
    value = (
        None
        if product <= np.finfo(float).eps * max(1.0, float(n))
        else float(np.clip(a @ b / product, -1, 1))
    )
    return dict(
        meta, value=value, reason=None if value is not None else "CONSTANT_OR_EXPLAINED_RESIDUAL"
    )


def equivalent(actual, expected, path=""):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError(path + ": keys")
        for key, value in expected.items():
            equivalent(actual[key], value, path + "." + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(path + ": length")
        for p, value in enumerate(expected):
            equivalent(actual[p], value, path + f"[{p}]")
    elif isinstance(expected, float):
        if (
            not isinstance(actual, (int, float))
            or not np.isfinite(actual)
            or not np.isclose(actual, expected, atol=2e-10, rtol=2e-9)
        ):
            raise AssertionError(path + ": numeric")
    elif actual != expected or type(actual) is not type(expected):
        raise AssertionError(path + ": exact/null/type")


def bootstrap(x, y, controls, scope, blocks):
    records = []
    for p in range(500):
        if blocks is None:
            row = dict(value=None, reason="INSUFFICIENT_FULL_AXIS")
        else:
            positions = np.array([q for q in blocks[p] if scope[q]], dtype=int)
            row = ic(x[positions], y[positions], None if controls is None else controls[positions])
        records.append(row)
    values = [row["value"] for row in records if row["value"] is not None]
    return dict(
        requested_replicates=500,
        valid_replicates=len(values),
        ic95=linear_percentile(values, (0.025, 0.975)) if len(values) >= 400 else None,
        reason=None if len(values) >= 400 else "INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES",
        diagnostic_only=True,
        search_selection_corrected=False,
    ), dict(Counter(row["reason"] or "VALID" for row in records))


def metrics(target, forecast, mean):
    n = len(target)
    if n < 20:
        return dict(
            n=n,
            mse=None,
            baseline_mse=None,
            mse_improvement=None,
            ic=None,
            reason="INSUFFICIENT_SAMPLE",
        )
    mse = float(fsum(float(value) ** 2 for value in target - forecast) / n)
    base = float(fsum(float(value) ** 2 for value in target - mean) / n)
    corr = ic(forecast, target)
    return dict(
        n=n,
        mse=mse,
        baseline_mse=base,
        mse_improvement=base - mse,
        ic=corr["value"],
        ic_reason=corr["reason"],
        reason=None,
    )


def walk_forward(features, target, ends, scope):
    index = features.index
    all_x = features[[*CONTROLS, COMPONENT]].to_numpy(float)
    finite = np.isfinite(all_x).all(axis=1) & np.isfinite(target)
    yearly, records, groups = (
        {},
        {name: [] for name in ("controls", "controls+concentration")},
        {"low": [], "high": []},
    )
    for year in range(2021, 2027):
        days = [day for day in index if day.year == year]
        first = days[0] if days else None
        train = np.array(
            [
                bool(
                    scope[p]
                    and first is not None
                    and 2020 <= day.year < year
                    and ends.iloc[p] < first
                )
                for p, day in enumerate(index)
            ]
        )
        test = scope & (index.year == year)
        tr, te = train & finite, test & finite
        x = all_x[:, -1]
        gt = train & np.isfinite(x) & np.isfinite(target)
        ge = test & np.isfinite(x) & np.isfinite(target)
        group = dict(
            train_n=int(gt.sum()),
            test_n=int(ge.sum()),
            q25=None,
            q75=None,
            low={"n": 0, "mean": None},
            high={"n": 0, "mean": None},
            high_minus_low=None,
        )
        group["reason"] = (
            "INSUFFICIENT_TRAIN_SAMPLE"
            if gt.sum() < 40
            else "CONSTANT_TRAIN_COMPONENT"
            if np.ptp(x[gt]) == 0
            else "INSUFFICIENT_TEST_SAMPLE"
            if ge.sum() < 20
            else None
        )
        if group["reason"] is None:
            lo, hi = linear_percentile(x[gt], (0.25, 0.75))
            group.update(q25=lo, q75=hi, overlap_n=int((ge & (x <= lo) & (x >= hi)).sum()))
            for name, mask in (("low", ge & (x <= lo)), ("high", ge & (x >= hi))):
                values = target[mask].tolist()
                group[name] = dict(
                    n=len(values),
                    mean=float(fsum(values) / len(values)) if len(values) >= 20 else None,
                    reason=None if len(values) >= 20 else "INSUFFICIENT_GROUP_SAMPLE",
                )
                groups[name].extend(values)
            if group["low"]["mean"] is not None and group["high"]["mean"] is not None:
                group["high_minus_low"] = group["high"]["mean"] - group["low"]["mean"]
        row = dict(
            first_actual_signaldate=first.isoformat() if first is not None else None,
            groups={COMPONENT: group},
            models={},
            common_train_n=int(tr.sum()),
            common_test_n=int(te.sum()),
            latest_train_label_end=ends[tr].max().isoformat() if tr.any() else None,
        )
        reason = (
            "INSUFFICIENT_TRAIN_SAMPLE"
            if tr.sum() < 40
            else "INSUFFICIENT_TEST_SAMPLE"
            if te.sum() < 20
            else "CONSTANT_TRAIN_LABEL"
            if np.ptp(target[tr]) == 0
            else None
        )
        if reason is not None:
            for name in records:
                row["models"][name] = dict(
                    n=int(te.sum()),
                    mse=None,
                    baseline_mse=None,
                    mse_improvement=None,
                    ic=None,
                    reason=reason,
                )
        else:
            tx = np.column_stack([empirical_transform(col, col) for col in all_x[tr].T])
            vx = np.column_stack(
                [empirical_transform(col, vals) for col, vals in zip(all_x[tr].T, all_x[te].T)]
            )
            baseline = np.full(te.sum(), fsum(target[tr]) / int(tr.sum()))
            for name, width in (("controls", 24), ("controls+concentration", 25)):
                forecast = predict(tx[:, :width], target[tr], vx[:, :width])
                row["models"][name] = metrics(target[te], forecast, baseline)
                records[name].extend(
                    dict(
                        signaldate=day.isoformat(),
                        target=float(y),
                        prediction=float(p),
                        baseline=float(b),
                    )
                    for day, y, p, b in zip(index[te], target[te], forecast, baseline)
                )
        yearly[str(year)] = row
    aggregates = {}
    for name, rows in records.items():
        aggregates[name] = metrics(
            np.array([r["target"] for r in rows]),
            np.array([r["prediction"] for r in rows]),
            np.array([r["baseline"] for r in rows]),
        )
    grouped = {
        name: dict(
            n=len(values),
            mean=float(fsum(values) / len(values)) if len(values) >= 20 else None,
            reason=None if len(values) >= 20 else "INSUFFICIENT_GROUP_SAMPLE",
        )
        for name, values in groups.items()
    }
    grouped["high_minus_low"] = (
        grouped["high"]["mean"] - grouped["low"]["mean"]
        if grouped["high"]["mean"] is not None and grouped["low"]["mean"] is not None
        else None
    )
    return dict(
        yearly=yearly,
        aggregate_models=aggregates,
        aggregate_groups={COMPONENT: grouped},
        prediction_records=records,
    )


def verify_statistics(features, labels, scopes, reported):
    index = dates(features.index)
    if (
        not index.equals(labels.index)
        or not index.equals(scopes.index)
        or tuple(scopes.columns) != (SCOPE,)
        or scopes[SCOPE].dtype != np.dtype(bool)
    ):
        raise ValueError("complete original fullT axis and single causal Boolean scope required")
    if set(reported["scopes"]) != {SCOPE} or reported["signal_n"] != len(index):
        raise AssertionError("unexpected scope or compressed fullT axis")
    method = reported["method"]
    if (
        method["controls"] != list(CONTROLS)
        or method["components"] != [COMPONENT]
        or method["labels"] != {name: 4 for name in LABELS}
    ):
        raise AssertionError("fixed24 controls, one component, onlyh4labels required")
    if (
        sha256(json.dumps(method, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        != reported["method_sha256"]
    ):
        raise AssertionError("method hash")
    panel = reported["scopes"][SCOPE]
    scope = scopes[SCOPE].to_numpy(bool)
    if panel["eligible_n"] != int(scope.sum()) or set(panel["labels"]) != set(LABELS):
        raise AssertionError("actual scope and bothlabels retained")
    x = features[COMPONENT].to_numpy(float)
    controls = features[list(CONTROLS)].to_numpy(float)
    if np.isinf(features[[*CONTROLS, COMPONENT]].to_numpy(float)).any():
        raise ValueError("infinite feature")
    blocks = full_axis_blocks(len(index))
    statuses = {}
    predictions = 0
    for label in LABELS:
        y = labels[label].to_numpy(float)
        ends = pd.to_datetime(labels["label_end_" + label])
        if np.isinf(y).any() or (np.isfinite(y) & (ends.isna() | (ends <= index)).to_numpy()).any():
            raise ValueError("target maturity")
        entry = panel["labels"][label]
        if entry["finite_target_n"] != int((scope & np.isfinite(y)).sum()) or set(
            entry["components"]
        ) != {COMPONENT}:
            raise AssertionError("label/component masks")
        pair = entry["components"][COMPONENT]
        equivalent(pair["spearman"], ic(x[scope], y[scope]), label + ".spearman")
        equivalent(
            pair["partial_rank_ic"], ic(x[scope], y[scope], controls[scope]), label + ".partial"
        )
        if set(pair["yearly"]) != {str(v) for v in set(index.year)} or set(
            pair["nonoverlap_phases"]
        ) != {str(p) for p in range(5)}:
            raise AssertionError("all years and original5phases retained")
        for category in ("yearly", "nonoverlap_phases"):
            for key, observed in pair[category].items():
                mask = scope & (
                    (index.year == int(key))
                    if category == "yearly"
                    else (np.arange(len(index)) % 5 == int(key))
                )
                equivalent(
                    observed,
                    dict(
                        spearman=ic(x[mask], y[mask]),
                        partial_rank_ic=ic(x[mask], y[mask], controls[mask]),
                    ),
                    label + "." + category + "." + key,
                )
        for name, c in (("spearman_block_ic95", None), ("partial_block_ic95", controls)):
            expected, status = bootstrap(x, y, c, scope, blocks)
            equivalent(pair[name], expected, label + "." + name)
            statuses[label + "." + name] = status
        expected = walk_forward(features, y, ends, scope)
        equivalent(entry["walk_forward"], expected, label + ".walk_forward")
        predictions += sum(len(rows) for rows in expected["prediction_records"].values())
    return dict(
        status="PASS",
        bootstrap_records=2000,
        prediction_records=predictions,
        bootstrap_statuses=statuses,
        new_accounts=0,
        scientific_judgment="not made",
    )
