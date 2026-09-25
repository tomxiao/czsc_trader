"""Development-only PySR method comparison for S003, S007, and S008.

The source repository is read-only. Results belong only to this METHODS experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


SEED = 20260926
SPEC = {
    "S003": {
        "symbol": "510500.SH",
        "features": ["moneyflow_breadth", "prior_60_breadth_q80"],
        "feature_file": "experiments/S003/20260911_S003_EX44/artifacts/moneyflow_breadth_features.csv.gz",
        "train_end": "2023-12-31",
        "eval_start": "2024-01-01",
        "cutoff": "2026-09-08",
        "horizon": 0,
        "cost": 0.00012,
    },
    "S007": {
        "symbol": "588080.SH",
        "features": [
            "micro_share_change_5d_lag1",
            "tsfresh__log_volume_change__mean__lb20",
            "price_close_vwap_deviation",
            "risk_global_spx_return",
            "risk_chinext_turnover_z20",
            "risk_shibor_on_change_5d",
            "price_intraday_range",
        ],
        "feature_file": "experiments/S007/20260915_S007_EX04/artifacts/causal_feature_panel.csv.gz",
        "train_end": "2024-12-31",
        "eval_start": "2025-01-01",
        "cutoff": "2026-09-02",
        "horizon": 3,
        "cost": 0.001,
    },
    "S008": {
        "symbol": "518880.SH",
        "features": [
            "currency_usdcnh_return_20d",
            "price_return_120d",
            "price_return_5d",
            "price_trend_distance_20",
        ],
        "feature_file": "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz",
        "train_end": "2020-12-31",
        "eval_start": "2021-01-01",
        "cutoff": "2024-12-31",
        "horizon": 20,
        "cost": 0.001,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_daily_opens(source_root: Path, symbol: str, years: range, used: dict) -> pd.Series:
    stem = symbol.split(".")[0]
    frames = []
    for year in years:
        relative = f"data/raw/{stem}_execution_daily_{year}.csv"
        path = source_root / relative
        used[relative] = sha256(path)
        frames.append(pd.read_csv(path))
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["date"])
    assert data["date"].is_unique and data["date"].is_monotonic_increasing
    return data.set_index("date")["open"].astype(float)


def load_s003(source_root: Path, used: dict) -> tuple[pd.DataFrame, set[str], dict]:
    spec = SPEC["S003"]
    relative = spec["feature_file"]
    used[relative] = sha256(source_root / relative)
    panel = pd.read_csv(source_root / relative)
    panel["date"] = pd.to_datetime(panel.pop("dt"))

    bars = []
    for year in range(2021, 2027):
        relative = f"data/raw/510500_5m_{year}.csv"
        used[relative] = sha256(source_root / relative)
        data = pd.read_csv(source_root / relative, usecols=["datetime", "open", "close"])
        data["datetime"] = pd.to_datetime(data["datetime"])
        data["date"] = data["datetime"].dt.normalize()
        first = data.loc[data["datetime"].dt.strftime("%H:%M") == "09:35", ["date", "open"]]
        last = data.loc[data["datetime"].dt.strftime("%H:%M") == "11:30", ["date", "close"]]
        bars.append(first.merge(last, on="date", validate="one_to_one"))
    prices = pd.concat(bars, ignore_index=True).sort_values("date").set_index("date")
    assert prices.index.is_unique
    prices["gross_return"] = prices["close"] / prices["open"] - 1.0
    next_date = pd.Series(prices.index, index=prices.index).shift(-1)
    next_gross = prices["gross_return"].shift(-1)
    next_open = prices["open"].shift(-1)
    next_close = prices["close"].shift(-1)
    panel = panel.join(next_date.rename("exit_date"), on="date")
    panel = panel.join(next_gross.rename("target"), on="date")
    panel = panel.join(next_open.rename("entry_price"), on="date")
    panel = panel.join(next_close.rename("exit_price"), on="date")
    panel = panel.loc[
        (panel["date"] >= pd.Timestamp("2021-04-14"))
        & (panel["exit_date"] <= pd.Timestamp(spec["cutoff"]))
    ].copy()
    assert panel[list(spec["features"]) + ["target"]].notna().all().all()

    relative = "experiments/S003/20260911_S003_EX44/artifacts/mechanism_events.csv"
    used[relative] = sha256(source_root / relative)
    events = pd.read_csv(source_root / relative)
    frozen_signals = set(events["signal_date"].astype(str))

    relative = "experiments/S003/20260911_S003_EX45/artifacts/episodes.csv.gz"
    used[relative] = sha256(source_root / relative)
    episodes = pd.read_csv(source_root / relative)
    episodes = episodes.loc[episodes["variant"].eq("PRIMARY_LONG")]
    matched = episodes.merge(
        panel[["date", "entry_price", "exit_price", "target"]],
        left_on="signal_date", right_on=panel["date"].dt.strftime("%Y-%m-%d"),
        validate="one_to_one",
    )
    assert len(matched) == len(episodes) == len(events)
    price_error = max(
        float(np.max(np.abs(matched["entry_price_x"] - matched["entry_price_y"]))),
        float(np.max(np.abs(matched["exit_price_x"] - matched["exit_price_y"]))),
        float(np.max(np.abs(matched["gross_return"] - matched["target"]))),
    )
    if price_error > 1e-9:
        raise ValueError(f"S003 event reconstruction differs from EX45: {price_error}")
    return panel, frozen_signals, {"frozen_event_count": len(events), "max_price_return_error": price_error}


def load_daily_case(source_root: Path, case: str, used: dict) -> pd.DataFrame:
    spec = SPEC[case]
    relative = spec["feature_file"]
    used[relative] = sha256(source_root / relative)
    panel = pd.read_csv(source_root / relative)
    date_name = next((name for name in ("date", "Date", "dt") if name in panel), None)
    if date_name is None:
        raise ValueError(f"{case}: feature panel has no date column")
    panel["date"] = pd.to_datetime(panel[date_name])
    years = range(2021, 2027) if case == "S007" else range(2013, 2025)
    opens = load_daily_opens(source_root, spec["symbol"], years, used)
    horizon = spec["horizon"]
    exit_date = pd.Series(opens.index, index=opens.index).shift(-(horizon + 1))
    target = opens.shift(-(horizon + 1)) / opens.shift(-1) - 1.0
    one_day = opens.shift(-2) / opens.shift(-1) - 1.0
    panel = panel.join(exit_date.rename("exit_date"), on="date")
    panel = panel.join(target.rename("target"), on="date")
    panel = panel.join(one_day.rename("one_day_return"), on="date")
    panel = panel.loc[panel["exit_date"] <= pd.Timestamp(spec["cutoff"])].copy()
    assert panel["date"].is_unique and panel["date"].is_monotonic_increasing
    return panel


def preprocess(train: pd.DataFrame, evaluate: pd.DataFrame, features: list[str]):
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    standardizer = StandardScaler()
    train_x = standardizer.fit_transform(imputer.fit_transform(train[features]))
    eval_x = standardizer.transform(imputer.transform(evaluate[features]))
    return np.clip(train_x, -5, 5).astype(np.float32), np.clip(eval_x, -5, 5).astype(np.float32)


def rankic(actual: np.ndarray, prediction: np.ndarray) -> float | None:
    if len(actual) < 3 or np.std(prediction) < 1e-9:
        return None
    value = float(spearmanr(actual, prediction).statistic)
    return value if np.isfinite(value) else None


def predictor_metrics(evaluate: pd.DataFrame, actual: np.ndarray, prediction: np.ndarray) -> dict:
    years = evaluate["date"].dt.year.to_numpy()
    return {
        "observations": len(actual),
        "mse_bp2": float(np.mean((actual - prediction) ** 2)),
        "rankic": rankic(actual, prediction),
        "annual_rankic": {
            str(year): rankic(actual[years == year], prediction[years == year])
            for year in sorted(set(years))
        },
    }


def daily_account(evaluate: pd.DataFrame, position: np.ndarray, cost: float) -> tuple[dict, pd.DataFrame]:
    position = np.asarray(position, dtype=int)
    gross = evaluate["one_day_return"].to_numpy(dtype=float)
    turns = np.abs(position - np.r_[0, position[:-1]])
    net = (1.0 - cost * turns) * (1.0 + position * gross) - 1.0
    equity = np.cumprod(1.0 + net)
    peak = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    drawdown = equity / peak - 1.0
    years = evaluate["date"].dt.year.to_numpy()
    annual = {
        str(year): float(np.prod(1.0 + net[years == year]) - 1.0)
        for year in sorted(set(years))
    }
    annualized = float(equity[-1] ** (252.0 / len(equity)) - 1.0)
    max_drawdown = float(drawdown.min())
    report = {
        "annualized": annualized,
        "terminal_equity": float(equity[-1]),
        "max_drawdown": max_drawdown,
        "calmar": annualized / abs(max_drawdown) if max_drawdown < 0 else None,
        "closed_trades_including_final_liquidation": int(np.sum((position[:-1] == 1) & (position[1:] == 0)) + position[-1]),
        "one_way_turnovers_including_final_liquidation": int(turns.sum() + position[-1]),
        "exposure_fraction": float(position.mean()),
        "annual_returns": annual,
    }
    ledger = evaluate[["date", "target", "one_day_return"]].copy()
    ledger["position"] = position
    ledger["turn"] = turns
    ledger["net_return"] = net
    ledger["equity"] = equity
    return report, ledger


def event_account(evaluate: pd.DataFrame, selected: np.ndarray, cost: float) -> tuple[dict, pd.DataFrame]:
    selected = np.asarray(selected, dtype=bool)
    gross = evaluate["target"].to_numpy(dtype=float)
    net = np.where(selected, gross - 2 * cost, 0.0)
    overlay = np.cumprod(1.0 + 0.5 * net)
    years = evaluate["date"].dt.year.to_numpy()
    annual = {
        str(year): {
            "events": int(np.sum(selected & (years == year))),
            "mean_net_bp": float(np.mean(net[selected & (years == year)]) * 1e4)
            if np.any(selected & (years == year)) else None,
        }
        for year in sorted(set(years))
    }
    report = {
        "events": int(selected.sum()),
        "mean_net_bp": float(np.mean(net[selected]) * 1e4) if selected.any() else None,
        "overlay_terminal_proxy": float(overlay[-1]),
        "exposure_fraction": float(selected.mean()),
        "annual": annual,
    }
    ledger = evaluate[["date", "exit_date", "target"]].copy()
    ledger["selected"] = selected
    ledger["net_event_return"] = net
    ledger["overlay_terminal_proxy"] = overlay
    return report, ledger


def fit_pysr(x: np.ndarray, y: np.ndarray, name: str, experiment: Path):
    from pysr import PySRRegressor

    output_root = experiment.parents[2] / ".tmp" / "pysr_runs"
    temp_root = experiment.parents[2] / ".tmp" / "pysr_temp"
    output_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    model = PySRRegressor(
        niterations=20,
        populations=2,
        population_size=40,
        ncycles_per_iteration=100,
        maxsize=9,
        maxdepth=5,
        binary_operators=["+", "-", "*"],
        unary_operators=[],
        precision=32,
        parallelism="serial",
        deterministic=True,
        random_state=SEED,
        model_selection="best",
        progress=False,
        verbosity=0,
        output_directory=str(output_root),
        tempdir=str(temp_root),
        run_id=name,
    )
    start = time.monotonic()
    model.fit(x, y, variable_names=[f"x{index}" for index in range(x.shape[1])])
    elapsed = time.monotonic() - start
    return model, elapsed


def synthetic_precheck() -> None:
    frame = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=4), "one_day_return": [0.01, -0.02, 0.03, 0.01], "target": [0.0] * 4})
    report, ledger = daily_account(frame, np.array([1, 0, 1, 1]), 0.001)
    assert report["closed_trades_including_final_liquidation"] == 2
    assert report["one_way_turnovers_including_final_liquidation"] == 4
    assert abs(ledger.iloc[0]["net_return"] - ((1 - 0.001) * 1.01 - 1)) < 1e-12
    event, _ = event_account(frame.assign(exit_date=frame["date"]), np.array([True, False, True, False]), 0.00012)
    assert event["events"] == 2


def run(source_root: Path, experiment: Path) -> None:
    synthetic_precheck()
    artifacts = experiment / "artifacts"
    artifacts.mkdir(exist_ok=True)
    all_used = {}
    summaries = {}
    for case, spec in SPEC.items():
        used = {}
        if case == "S003":
            frame, frozen_signals, source_check = load_s003(source_root, used)
        else:
            frame = load_daily_case(source_root, case, used)
            frozen_signals, source_check = set(), {}
        train = frame.loc[(frame["date"] <= pd.Timestamp(spec["train_end"])) & (frame["exit_date"] <= pd.Timestamp(spec["train_end"]))].copy()
        evaluate = frame.loc[frame["date"] >= pd.Timestamp(spec["eval_start"])].copy()
        if len(train) < 40 or len(evaluate) < 40:
            raise ValueError(f"{case}: insufficient train/evaluation observations")
        train_x, eval_x = preprocess(train, evaluate, spec["features"])
        train_y = train["target"].to_numpy(dtype=np.float32) * 1e4
        eval_y = evaluate["target"].to_numpy(dtype=np.float32) * 1e4
        linear = Ridge(alpha=1.0).fit(train_x, train_y)
        linear_train = linear.predict(train_x)
        linear_eval = linear.predict(eval_x)
        model, elapsed = fit_pysr(train_x, train_y, case, experiment)
        pysr_train = np.asarray(model.predict(train_x), dtype=float).ravel()
        pysr_eval = np.asarray(model.predict(eval_x), dtype=float).ravel()
        shift = max(31, len(train_y) // 3)
        null_model, null_elapsed = fit_pysr(train_x, np.roll(train_y, shift), f"{case}_SHIFTED", experiment)
        null_eval = np.asarray(null_model.predict(eval_x), dtype=float).ravel()
        for name, fitted in (("real", model), ("shifted", null_model)):
            fitted.equations_.to_csv(artifacts / f"{case.lower()}_{name}_equations.csv", index=False)

        if case == "S003":
            train_rate = float(train["date"].dt.strftime("%Y-%m-%d").isin(frozen_signals).mean())
            frozen_eval = evaluate["date"].dt.strftime("%Y-%m-%d").isin(frozen_signals).to_numpy()
            positions = {"frozen": frozen_eval}
            for name, train_pred, eval_pred in (("linear", linear_train, linear_eval), ("pysr", pysr_train, pysr_eval)):
                threshold = float(np.quantile(train_pred, 1 - train_rate))
                positions[name] = eval_pred > threshold
            accounts = {}
            for cost_name, cost in (("base", spec["cost"]), ("stress", 0.0006)):
                accounts[cost_name] = {}
                for name, position in positions.items():
                    report, ledger = event_account(evaluate, position, cost)
                    accounts[cost_name][name] = report
                    ledger.to_csv(artifacts / f"s003_{name}_{cost_name}_events.csv", index=False)
        else:
            positions = {"linear": linear_eval > 0, "pysr": pysr_eval > 0, "buyhold": np.ones(len(eval_y), dtype=bool)}
            accounts = {}
            for name, position in positions.items():
                report, ledger = daily_account(evaluate, position, spec["cost"])
                accounts[name] = report
                ledger.to_csv(artifacts / f"{case.lower()}_{name}_daily.csv", index=False)

        forecast_ledger = evaluate[["date", "exit_date", "target"]].copy()
        forecast_ledger["linear_bp"] = linear_eval
        forecast_ledger["pysr_bp"] = pysr_eval
        forecast_ledger["shifted_bp"] = null_eval
        forecast_ledger.to_csv(artifacts / f"{case.lower()}_forecast.csv", index=False)
        summaries[case] = {
            "train_count": len(train),
            "evaluate_count": len(evaluate),
            "train_last_exit": str(train["exit_date"].max().date()),
            "eval_last_exit": str(evaluate["exit_date"].max().date()),
            "source_check": source_check,
            "source_sha256": used,
            "selected_equation": str(model.get_best()["equation"]),
            "selected_complexity": int(model.get_best()["complexity"]),
            "search_seconds": elapsed,
            "shifted_search_seconds": null_elapsed,
            "shifted_label_offset": shift,
            "training": {
                "linear": predictor_metrics(train, train_y, linear_train),
                "pysr": predictor_metrics(train, train_y, pysr_train),
            },
            "evaluation": {
                "linear": predictor_metrics(evaluate, eval_y, linear_eval),
                "pysr": predictor_metrics(evaluate, eval_y, pysr_eval),
                "shifted": predictor_metrics(evaluate, eval_y, null_eval),
                "prediction_correlation_linear_pysr": rankic(linear_eval, pysr_eval),
                "different_position_days": int(np.sum(positions["linear"] != positions["pysr"])),
            },
            "accounts": accounts,
        }
        all_used.update(used)
        (artifacts / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(f"{case} COMPLETE", flush=True)
    (artifacts / "source_sha256.json").write_text(json.dumps(all_used, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--synthetic-only", action="store_true")
    args = parser.parse_args()
    if args.synthetic_only:
        synthetic_precheck()
        print("SYNTHETIC_PASS")
        return
    if args.source_root is None:
        parser.error("--source-root is required for historical comparison")
    run(args.source_root.resolve(), Path(__file__).resolve().parent)


if __name__ == "__main__":
    main()
