"""S015 daily-information study. No strategy, account or candidate construction."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import importlib.metadata
import json
from multiprocessing import get_context
import os
from pathlib import Path
import time
from uuid import UUID

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
from threadpoolctl import threadpool_limits

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources
from dataflows import DataRequest, Dataset, PreparedDataRef
from factor_signal_catalog.calculations import (
    calculate_daily_close_vwap_deviation, calculate_daily_intraday_range,
)

HERE = Path(__file__).resolve().parent.parent
FOLDS = ((150, 220), (220, 290), (290, 360), (360, 434))
HORIZONS = (1, 3, 5, 10)
FC = {
    "mean": None, "median": None, "standard_deviation": None,
    "skewness": None, "quantile": [{"q": 0.25}, {"q": 0.75}],
    "autocorrelation": [{"lag": 1}], "linear_trend": [{"attr": "slope"}],
    "mean_abs_change": None,
}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8", newline="\n")


def load_data():
    repository = RepositoryContext.discover(Path.cwd())
    context = create_research_context(repository, ResearchBatchRef("S015"),
                                     resources=EvaluationResources(8, 1, 13))
    audit = json.loads((repository.root / "research/S015/experiments/EX001_20261021/others/data_audit.json").read_text(encoding="utf-8"))
    saved = audit["prepared_reference"]
    prepared = PreparedDataRef(UUID(saved["space_id"]), UUID(saved["preparation_id"]),
                               saved["manifest_sha256"])
    values = {}
    for ds in (Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_OHLCV):
        req = DataRequest(dataset=ds, symbol="159326.SZ", frequency="daily",
                          start="2024-09-09", end="2026-10-21", required_cutoff="2026-10-21")
        result = context.data.fetch(req, prepared=prepared)
        if not result.ready:
            raise RuntimeError(result.error)
        values[ds] = result.dataframe.sort_values("Date").reset_index(drop=True)
        expected = next(x for x in audit["items"] if x["dataset"] == ds.value)
        if result.identity.content_sha256 != expected["identity"]["content_sha256"]:
            raise ValueError("input identity changed")
    raw = values[Dataset.ETF_UNADJUSTED_DAILY]
    adjusted = values[Dataset.ETF_OHLCV]
    if not raw.Date.equals(adjusted.Date) or len(raw) != 509:
        raise ValueError("daily inputs differ in dates")
    diffs = np.log(raw.Close).diff() - np.log(adjusted.Close).diff()
    facts = {"prepared": saved, "daily_rows": 509, "evaluation_sessions": 434,
             "max_raw_adjusted_log_return_difference": float(diffs.abs().max()),
             "difference_gt_1bp_dates": raw.loc[diffs.abs() > 0.0001, "Date"].astype(str).tolist(),
             "scope": "Existing S015 retained DFLS inputs only; no provider refresh or other batch reads."}
    return raw, facts


def hand_features(d, use_codegen=False):
    c, o, h, low = (d[k].astype(float) for k in ("Close", "Open", "High", "Low"))
    volume, amount = (d[k].astype(float) for k in ("Volume", "Amount"))
    r = np.log(c).diff()
    result = {}
    for n in (1, 3, 5, 10, 20, 60):
        result[f"ret{n}"] = np.log(c).diff(n)
    for n in (5, 10, 20, 60):
        result[f"ma_dev{n}"] = c / c.rolling(n).mean() - 1
        result[f"vol{n}"] = r.rolling(n).std(ddof=0)
        result[f"range{n}"] = ((h - low) / c).rolling(n).mean()
    for n in (20, 60):
        for name, seq in (("amount", np.log(amount)), ("volume", np.log(volume))):
            result[f"{name}_z{n}"] = (seq - seq.rolling(n).mean()) / seq.rolling(n).std(ddof=0)
        result[f"efficiency{n}"] = np.log(c).diff(n) / r.abs().rolling(n).sum()
        result[f"price_location{n}"] = (c - low.rolling(n).min()) / (h.rolling(n).max() - low.rolling(n).min())
    for n in (1, 5, 20):
        result[f"volume_change{n}"] = np.log(volume).diff(n)
    result["ret_previous1"] = r.shift(1)
    result["body"] = np.log(c / o)
    result["gap"] = np.log(o / c.shift(1))
    result["close_location"] = (2 * c - h - low) / (h - low)
    result["range_value"] = (h - low) / c
    result["vwap_dev"] = c / (amount / volume) - 1
    result["volume_return_corr20"] = r.rolling(20).corr(np.log(volume).diff())
    result["illiquidity20"] = (r.abs() / amount * 1e8).rolling(20).mean()
    if use_codegen:
        from expr_codegen import codegen_exec
        generated_root = Path.cwd() / ".tmp/s015-codegen"
        generated_root.mkdir(parents=True, exist_ok=True)
        frame = d.copy().assign(date=pd.to_datetime(d.Date), asset="159326.SZ")
        generated = codegen_exec(frame, "body = log(Close / Open)\nrange_value = (High - Low) / Close",
                                 over_null=None, style="pandas",
                                 output_file=str(generated_root / "daily_components.py"))
        for name in ("body", "range_value"):
            np.testing.assert_allclose(generated[name], result[name], rtol=1e-12, atol=1e-14)
            result[name] = generated[name]
        base = d.rename(columns={"Date": "trade_date", "Close": "close", "High": "high",
                                 "Low": "low", "Volume": "volume", "Amount": "amount"}).assign(ts_code="159326.SZ")
        a = calculate_daily_intraday_range(base)["daily_intraday_range"]
        b = calculate_daily_close_vwap_deviation(base)["daily_close_vwap_deviation"]
        np.testing.assert_allclose(a, result["range_value"], rtol=1e-12, atol=1e-14)
        np.testing.assert_allclose(b, result["vwap_dev"], rtol=1e-12, atol=1e-14)
    return pd.DataFrame(result).replace([np.inf, -np.inf], np.nan)


def ts_features(d, test_mode=False):
    from tsfresh import extract_features
    series = {"return": np.log(d.Close).diff(), "range": (d.High - d.Low) / d.Close,
              "volume_change": np.log(d.Volume).diff()}
    output = []
    for window in (20, 60):
        ids = np.arange(75, len(d))
        if test_mode:
            ids = ids[:4]
        pieces = []
        for name, values in series.items():
            arr = values.to_numpy()
            pieces.append(pd.DataFrame({"id": np.repeat(ids, window),
                "time": np.tile(np.arange(window), len(ids)), "kind": name,
                "value": np.concatenate([arr[i - window + 1:i + 1] for i in ids])}))
        long = pd.concat(pieces, ignore_index=True)
        extracted = extract_features(long, column_id="id", column_sort="time", column_kind="kind",
            column_value="value", default_fc_parameters=FC, n_jobs=8, chunksize=32,
            disable_progressbar=True, impute_function=None, show_warnings=False)
        # Same production path with one worker on a fixed small sample verifies transport equivalence.
        subset = long[long.id.isin(ids[:2])]
        serial = extract_features(subset, column_id="id", column_sort="time", column_kind="kind",
            column_value="value", default_fc_parameters=FC, n_jobs=0,
            disable_progressbar=True, impute_function=None, show_warnings=False)
        np.testing.assert_allclose(extracted.loc[serial.index, serial.columns], serial,
                                   equal_nan=True, rtol=1e-12, atol=1e-14)
        extracted.columns = [f"ts{window}__{x}" for x in extracted.columns]
        output.append(extracted)
    return pd.concat(output, axis=1).reindex(np.arange(len(d)))


def make_labels(d):
    labels, ends = {}, {}
    positions = np.arange(len(d), dtype=float)
    for horizon in HORIZONS:
        labels[f"open{horizon}"] = d.Open.shift(-horizon - 1) / d.Open.shift(-1) - 1
        ends[f"open{horizon}"] = positions + horizon + 1
        labels[f"close{horizon}"] = d.Close.shift(-horizon) / d.Close - 1
        ends[f"close{horizon}"] = positions + horizon
    labels["range3"] = pd.concat([np.log(d.High / d.Low).shift(-j) for j in (1, 2, 3)], axis=1).mean(axis=1, skipna=False)
    labels["downside3"] = (1 - pd.concat([d.Low.shift(-j) for j in (1, 2, 3)], axis=1).min(axis=1, skipna=False) / d.Open.shift(-1)).clip(lower=0)
    ends["range3"] = positions + 3
    ends["downside3"] = positions + 3
    return pd.DataFrame(labels), ends


def corr(a, b):
    if len(a) < 4 or np.std(a) < 1e-14 or np.std(b) < 1e-14:
        return 0.0
    return float(spearmanr(a, b).statistic)


def standardize(train, test):
    med = np.nanmedian(train, axis=0)
    if not np.isfinite(med).all():
        raise ValueError("feature has no finite training values")
    train, test = np.where(np.isfinite(train), train, med), np.where(np.isfinite(test), test, med)
    low, high = np.quantile(train, [0.01, 0.99], axis=0)
    train, test = np.clip(train, low, high), np.clip(test, low, high)
    mean, std = train.mean(axis=0), train.std(axis=0)
    std = np.where(std < 1e-12, 1, std)
    return (train - mean) / std, (test - mean) / std


def ridge(train, y, test):
    average = y.mean()
    beta = np.linalg.solve(train.T @ train + 10 * np.eye(train.shape[1]), train.T @ (y - average))
    return average + test @ beta


def fold_indices(y, end):
    valid = np.isfinite(y)
    for a, b in FOLDS:
        train = np.flatnonzero(valid & (end < 75 + a) & (np.arange(len(y)) < a))
        test = np.flatnonzero(valid & (np.arange(len(y)) >= a) & (np.arange(len(y)) < b))
        if not len(train) or not len(test):
            raise ValueError("empty temporal fold")
        yield train, test


def bootstrap_indices(n, block, draws=999):
    rng = np.random.default_rng(13 + block)
    starts = rng.integers(0, n - block + 1, size=(draws, int(np.ceil(n / block))))
    return (starts[:, :, None] + np.arange(block)).reshape(draws, -1)[:, :n]


def quantile_ci(value):
    value = value[np.isfinite(value)]
    if not len(value):
        return [None, None]
    return [float(x) for x in np.quantile(value, [0.025, 0.975])]


def ratio_sum_ci(numerators, denominators, indices):
    a, b = numerators[indices].sum(axis=1), denominators[indices].sum(axis=1)
    return quantile_ci(a / np.maximum(b, 1e-20))


def evaluate_label(job):
    name, x, columns, y, end, dates = job
    with threadpool_limits(limits=1):
        baseline_names = ["range20"] if name == "range3" else ["vol20"] if name == "downside3" else ["ret5", "vol20"]
        bi = [columns.index(s) for s in baseline_names]
        rows = []
        folds = []
        stores = {key: [] for key in ("y", "dates", "scores", "groups", "single", "incremental", "baseline", "mean", "fold", "state")}
        for fi, (train, test) in enumerate(fold_indices(y, end)):
            tx, vx = standardize(x[train], x[test])
            ty, vy = y[train], y[test]
            directions = np.array([1.0 if corr(tx[:, j], ty) >= 0 else -1.0 for j in range(x.shape[1])])
            train_scores, scores = tx * directions, vx * directions
            q1, q2 = np.quantile(train_scores, [1 / 3, 2 / 3], axis=0)
            groups = np.where(scores >= q2, 1, np.where(scores <= q1, -1, 0))
            # Constant features have no valid high-low contrast.
            groups[:, np.abs(q2 - q1) < 1e-12] = 0
            single = np.column_stack([ridge(tx[:, [j]], ty, vx[:, [j]]) for j in range(x.shape[1])])
            baseline = ridge(tx[:, bi], ty, vx[:, bi])
            incremental = np.column_stack([ridge(tx[:, sorted(set(bi + [j]))], ty, vx[:, sorted(set(bi + [j]))]) for j in range(x.shape[1])])
            fold_ic = [corr(scores[:, j], vy) for j in range(x.shape[1])]
            median_vol = np.median(x[train, columns.index("vol20")])
            state = np.column_stack([x[test, columns.index("ret20")] >= 0,
                                     x[test, columns.index("vol20")] >= median_vol]).astype(int)
            folds.append({"fold": fi, "train_n": len(train), "test_n": len(test),
                "train_last_date": dates[train[-1]], "train_last_label_position": float(end[train[-1]]),
                "test_first_date": dates[test[0]], "test_last_date": dates[test[-1]],
                "purged": int((np.arange(len(y)) < FOLDS[fi][0]).sum() - len(train)),
                "directions": directions.tolist(), "ic": fold_ic})
            for key, value in (("y", vy), ("dates", dates[test]), ("scores", scores), ("groups", groups),
                ("single", single), ("incremental", incremental), ("baseline", baseline),
                ("mean", np.full(len(test), ty.mean())), ("fold", np.full(len(test), fi)), ("state", state)):
                stores[key].append(value)
        data = {k: np.concatenate(v) for k, v in stores.items()}
        yy, score, group = data["y"], data["scores"], data["groups"]
        n = len(yy)
        ix10, ix20 = bootstrap_indices(n, 10), bootstrap_indices(n, 20)
        ry = rankdata(yy)
        ry = (ry - ry.mean()) / np.linalg.norm(ry - ry.mean())
        rx = np.column_stack([rankdata(score[:, j]) for j in range(x.shape[1])])
        rx -= rx.mean(axis=0)
        norms = np.linalg.norm(rx, axis=0)
        rx /= np.where(norms == 0, 1, norms)
        observed = ry @ rx
        eligible = np.arange(20, n - 19)
        shifts = eligible[np.unique(np.linspace(0, len(eligible) - 1, min(198, len(eligible))).astype(int))]
        null = np.stack([np.roll(ry, shift) @ rx for shift in shifts])
        rawp = (1 + (np.abs(null) >= np.abs(observed)).sum(axis=0)) / (1 + len(shifts))
        maxp = (1 + (np.max(np.abs(null), axis=1)[:, None] >= np.abs(observed)).sum(axis=0)) / (1 + len(shifts))
        order = np.argsort(rawp)
        bh = np.empty(len(columns))
        bh[order] = np.minimum(1, np.minimum.accumulate((rawp[order] * len(columns) / np.arange(1, len(columns) + 1))[::-1])[::-1])
        baseline_loss = (data["baseline"] - yy) ** 2
        mean_loss = (data["mean"] - yy) ** 2
        for j, feature in enumerate(columns):
            high, low = group[:, j] == 1, group[:, j] == -1
            highn, lown = int(high.sum()), int(low.sum())
            delta = float(yy[high].mean() - yy[low].mean()) if highn and lown else None
            samples = []
            for ix in (ix10, ix20):
                hs, ls = high[ix], low[ix]
                hd, ld = hs.sum(axis=1), ls.sum(axis=1)
                ok = (hd > 0) & (ld > 0)
                samples.append(quantile_ci((yy[ix][ok] * hs[ok]).sum(axis=1) / hd[ok] - (yy[ix][ok] * ls[ok]).sum(axis=1) / ld[ok]))
            incremental_loss = (data["incremental"][:, j] - yy) ** 2
            single_loss = (data["single"][:, j] - yy) ** 2
            fold_values = [fold["ic"][j] for fold in folds]
            year_values = {}
            for year in ("2025", "2026"):
                mask = np.char.startswith(data["dates"].astype(str), year)
                if mask.sum() >= 10:
                    year_values[year] = {"n": int(mask.sum()), "ic": corr(score[mask, j], yy[mask]),
                        "delta": float(yy[mask & high].mean() - yy[mask & low].mean()) if (mask & high).sum() and (mask & low).sum() else None}
            states = {}
            for state_col, state_name in ((0, "past_ret20_positive"), (1, "past_vol20_high")):
                for state_value in (0, 1):
                    mask = data["state"][:, state_col] == state_value
                    if mask.sum() >= 10:
                        states[f"{state_name}={state_value}"] = {"n": int(mask.sum()), "ic": corr(score[mask, j], yy[mask])}
            inc_num = baseline_loss - incremental_loss
            rows.append({"feature": feature, "label": name, "n": n, "ic": float(observed[j]),
                "raw_shift_p": float(rawp[j]), "bh_within_label": float(bh[j]), "max_feature_shift_p": float(maxp[j]),
                "positive_folds": sum(v > 0 for v in fold_values), "fold_ic": fold_values,
                "directions": [fold["directions"][j] for fold in folds], "high_n": highn, "low_n": lown,
                "high_mean": float(yy[high].mean()) if highn else None, "low_mean": float(yy[low].mean()) if lown else None,
                "delta": delta, "delta_ci_block10": samples[0], "delta_ci_block20": samples[1],
                "single_mse_gain": float(1 - single_loss.sum() / mean_loss.sum()),
                "incremental_mse_gain": float(inc_num.sum() / baseline_loss.sum()),
                "incremental_ci_block10": ratio_sum_ci(inc_num, baseline_loss, ix10),
                "incremental_ci_block20": ratio_sum_ci(inc_num, baseline_loss, ix20),
                "years": year_values, "states": states})
        arrays = {**data, "columns": np.asarray(columns)}
        return name, {"rows": rows, "folds": folds, "null_shifts": shifts.tolist(),
                      "baseline": baseline_names, "mean_label": float(yy.mean())}, arrays


def multivariate(x, columns, y, end, dates):
    groups = {
        "continuation": ["ret5", "ret20", "ret60", "efficiency20", "efficiency60", "ma_dev20"],
        "reversal": ["ret1", "body", "gap", "close_location", "vwap_dev", "ma_dev5"],
        "risk": ["vol5", "vol20", "range_value", "range20", "amount_z20", "volume_change1"],
        "limited_tsfresh": [s for s in columns if s.startswith("ts20__") and any(k in s for k in ("autocorrelation", "skewness", "linear_trend"))],
    }
    groups["all_mechanisms"] = list(dict.fromkeys(sum(groups.values(), [])))
    records = []
    for label in ("open1", "open3", "open5", "open10", "range3", "downside3"):
        yy = y[label].to_numpy()
        bi_names = ["range20"] if label == "range3" else ["vol20"] if label == "downside3" else ["ret5", "vol20"]
        for group_name, names in groups.items():
            chosen = list(dict.fromkeys(bi_names + names))
            ci = [columns.index(s) for s in chosen]
            bi = [chosen.index(s) for s in bi_names]
            actual, pred, base, intercept, date_values, fold_records = [], [], [], [], [], []
            for fi, (train, test) in enumerate(fold_indices(yy, end[label])):
                tx, vx = standardize(x[train][:, ci], x[test][:, ci])
                p = ridge(tx, yy[train], vx)
                b = ridge(tx[:, bi], yy[train], vx[:, bi])
                actual.extend(yy[test])
                pred.extend(p)
                base.extend(b)
                intercept.extend(np.full(len(test), yy[train].mean()))
                date_values.extend(dates[test])
                fold_records.append({"fold": fi, "n": len(test), "incremental_gain": float(1 - np.sum((p - yy[test])**2) / np.sum((b - yy[test])**2))})
            actual, pred, base, intercept = map(np.asarray, (actual, pred, base, intercept))
            base_loss, full_loss = (base - actual)**2, (pred - actual)**2
            n = len(actual)
            records.append({"label": label, "group": group_name, "features": names, "n": n,
                "incremental_mse_gain": float(1 - full_loss.sum() / base_loss.sum()),
                "mean_baseline_mse_gain": float(1 - full_loss.sum() / np.sum((intercept - actual)**2)),
                "ci_block10": ratio_sum_ci(base_loss - full_loss, base_loss, bootstrap_indices(n, 10)),
                "ci_block20": ratio_sum_ci(base_loss - full_loss, base_loss, bootstrap_indices(n, 20)),
                "folds": fold_records})
    return records


def self_checks(d):
    full = hand_features(d)
    for n in (120, 240, 400):
        pd.testing.assert_frame_equal(full.iloc[:n], hand_features(d.iloc[:n]), check_exact=False, rtol=1e-12, atol=1e-14)
    toy = pd.DataFrame({"Open": np.arange(1, 30, dtype=float), "Close": np.arange(1, 30, dtype=float),
                        "High": np.arange(1, 30, dtype=float) + .5, "Low": np.arange(1, 30, dtype=float) - .5})
    lab, _ = make_labels(toy)
    for h in HORIZONS:
        if lab[f"open{h}"].notna().sum() != len(toy) - h - 1:
            raise AssertionError("label tail")
        np.testing.assert_allclose(lab[f"open{h}"].iloc[0], toy.Open.iloc[h + 1] / toy.Open.iloc[1] - 1)
    lab, ends = make_labels(d)
    for label in lab:
        yy = lab[label].to_numpy()[75:]
        for train, test in fold_indices(yy, ends[label][75:]):
            if ends[label][75:][train].max() >= 75 + test[0]:
                raise AssertionError("purge boundary")
    return {"hand_feature_prefix": "PASS", "label_alignment_and_tail": "PASS", "purge": "PASS"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    start = time.perf_counter()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    root = Path.cwd()
    work = root / "research/S015/assets/runs/EX002_20261021/daily_information"
    work.mkdir(parents=True, exist_ok=True)
    d, facts = load_data()
    checks = self_checks(d)
    if args.check:
        ts_features(d, test_mode=True)
        hand_features(d, use_codegen=True)
        print(json.dumps({"checks": checks, "tsfresh_parallel_serial": "PASS", "expr_codegen_reference": "PASS", "fsc_reference": "PASS"}))
        return
    print("Inputs and causal/label checks passed", flush=True)
    features = pd.concat([hand_features(d, use_codegen=True), ts_features(d)], axis=1)
    features = features.replace([np.inf, -np.inf], np.nan)
    if features.iloc[75:].isna().all(axis=0).any():
        raise ValueError("unavailable feature")
    labels, ends = make_labels(d)
    dates = d.Date.astype(str).str[:10].to_numpy()[75:]
    x = features.iloc[75:].to_numpy(dtype=float)
    columns = features.columns.tolist()
    labels = labels.iloc[75:].reset_index(drop=True)
    ends = {k: v[75:] for k, v in ends.items()}
    features.assign(Date=d.Date).to_csv(work / "features.csv", index=False)
    labels.assign(Date=dates).to_csv(work / "labels.csv", index=False)
    jobs = [(label, x, columns, labels[label].to_numpy(), ends[label], dates) for label in labels]
    result, summaries = {}, {}
    with ProcessPoolExecutor(max_workers=8, mp_context=get_context("spawn")) as pool:
        for name, summary, arrays in pool.map(evaluate_label, jobs):
            result[name] = summary
            np.savez_compressed(work / f"oos_{name}.npz", **arrays)
            summaries[name] = {"n": len(arrays["y"]), "features": len(columns)}
            print(json.dumps({"label_completed": name, **summaries[name]}), flush=True)
    # Parallel result equality on the same full representative label is checked once.
    serial_name, serial_result, _ = evaluate_label(jobs[0])
    if json.dumps(serial_result, sort_keys=True) != json.dumps(result[serial_name], sort_keys=True):
        raise AssertionError("parallel and serial research calculation differ")
    records = multivariate(x, columns, labels, ends, dates)
    feature_corr = features.iloc[75:].corr(method="spearman").fillna(0)
    feature_corr.to_csv(work / "feature_rank_correlations.csv")
    single_rows = [row for entry in result.values() for row in entry["rows"]]
    # All tested labels/features count for the across-label diagnostic adjustment.
    p = np.array([row["raw_shift_p"] for row in single_rows])
    order = np.argsort(p)
    q = np.empty(len(p))
    q[order] = np.minimum(1, np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p)+1))[::-1])[::-1])
    for row, value in zip(single_rows, q, strict=True):
        row["bh_all_feature_label_pairs"] = float(value)
    costs = {}
    for label in (f"open{h}" for h in HORIZONS):
        yy = labels[label].dropna().to_numpy()
        costs[label] = {"n": len(yy), "mean_gross_label": float(yy.mean()),
            "mean_net_price_label": float(((1+yy)*(1-.001)/(1+.001)-1).mean()),
            "mean_pressure_net_price_label": float(((1+yy)*(1-.002)/(1+.002)-1).mean()),
            "positive_gross_fraction": float((yy>0).mean())}
    ratios = np.floor(d.Close.to_numpy()[75:] * 1.01 / .001 + 1e-10) * .001
    next_open = d.Open.shift(-1).to_numpy()[75:]
    next_low = d.Low.shift(-1).to_numpy()[75:]
    ok = np.isfinite(next_open)
    limits = {"n": int(ok.sum()), "next_open_above_1pct_limit": int((next_open[ok] > ratios[ok]).sum()),
        "next_daily_low_above_limit": int((next_low[ok] > ratios[ok]).sum()),
        "meaning": "Daily geometry only: no minute fill, queue, cash path, actual order or return claim."}
    summary = {"facts": facts, "checks": {**checks, "tsfresh_parallel_serial": "PASS", "label_parallel_serial": "PASS", "expr_codegen_and_fsc_reference": "PASS"},
        "versions": {s: importlib.metadata.version(s) for s in ("numpy", "pandas", "scipy", "tsfresh", "optuna", "expr_codegen", "scikit-learn")},
        "resources": {"processes": 8, "native_threads": 1, "seed": 13},
        "feature_count": len(columns), "hand_features": sum(not c.startswith("ts") for c in columns),
        "tsfresh_features": sum(c.startswith("ts") for c in columns), "labels": list(labels),
        "feature_label_comparisons": len(single_rows), "multivariate_comparisons": len(records),
        "feature_missing_counts": {c: int(features.iloc[75:][c].isna().sum()) for c in columns if features.iloc[75:][c].isna().any()},
        "results": result, "multivariate": records, "cost_price_labels": costs, "limit_geometry": limits,
        "elapsed_seconds": float(time.perf_counter()-start),
        "code_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "independence": "All 434 sessions are seen development information; temporal validation is within-pool only.",
        "null_limit": "Fixed realized predictions/orientations under circular label shifts; the entire training/selection pipeline is not refitted under each shift; p/q values are exploratory diagnostics, not controlled confirmatory significance."}
    save_json(work / "study_results.json", summary)
    pd.DataFrame(single_rows).drop(columns=["years", "states"]).to_csv(work / "single_feature_summary.csv", index=False)
    print(json.dumps({"finished": True, "features": len(columns), "comparisons": len(single_rows), "elapsed_seconds": summary["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
