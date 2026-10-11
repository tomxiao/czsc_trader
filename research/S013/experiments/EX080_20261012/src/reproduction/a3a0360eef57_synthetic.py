"""Artificial-only source verification for the fixed native expression."""

from pathlib import Path
from hashlib import sha256
import json
import sys
import importlib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MAIN = HERE.parent / "s013-confirm-net-execution"
sys.path.insert(0, str(MAIN))
kernel = importlib.import_module("confirm_kernel")
sys.path.insert(0, str(HERE))
audit = importlib.import_module("audit")


def supplied(frame):
    return frame.rename_axis("Date").reset_index()


def run():
    rng = np.random.default_rng(63)
    grid = pd.DatetimeIndex(
        np.concatenate(
            [pd.bdate_range(f"{year}-01-02", periods=65).to_numpy() for year in range(2020, 2027)]
        )
    )
    signals = pd.DatetimeIndex([pd.Timestamp("2019-12-31"), *grid])
    native_axis = signals.append(pd.DatetimeIndex([grid[-1] + pd.offsets.BDay()]))
    warm = pd.bdate_range(end="2019-12-30", periods=220)
    allaxis = warm.append(native_axis)
    close = np.exp(np.cumsum(rng.normal(0.0005, 0.02, len(allaxis))))
    opening = close * np.exp(rng.normal(0, 0.01, len(close)))
    daily = pd.DataFrame(
        {
            "Open": opening,
            "High": np.maximum(opening, close) * 1.03,
            "Low": np.minimum(opening, close) * 0.97,
            "Close": close,
            "Volume": np.exp(rng.normal(10, 0.6, len(close))),
            "Amount": np.exp(rng.normal(14, 0.8, len(close))),
        },
        index=allaxis,
    )
    native = daily.loc[native_axis].copy()
    records = []
    clocks = ["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]
    for day, row in native.iloc[1:].iterrows():
        points = np.exp(np.linspace(np.log(row.Open), np.log(row.Close), 9))
        points[1:-1] *= np.exp(rng.normal(0, 0.005, 7))
        for j, clock in enumerate(clocks):
            records.append(
                dict(
                    Date=pd.Timestamp(str(day.date()) + " " + clock),
                    Open=points[j],
                    High=max(points[j : j + 2]) * 1.01,
                    Low=min(points[j : j + 2]) * 0.99,
                    Close=points[j + 1],
                    Volume=100.0,
                    Amount=1000.0,
                )
            )
    intraday = pd.DataFrame(records).set_index("Date")
    features = kernel.rebuild(supplied(daily), supplied(native), supplied(intraday), signals)
    scores, fit = kernel.annual_forecasts(features, native, signals)
    history = kernel.episode_history(scores, signals)
    proof = audit.verify(daily, native, intraday, signals, features, scores, fit, history)
    assert not np.isfinite(features.intraday_energy20.iloc[:20]).any() and np.isfinite(
        features.intraday_energy20.iloc[20]
    )
    assert (
        scores[signals.year <= 2020].isna().all()
        and history.loc[signals.year <= 2020, "target_position"].eq(0).all()
    )
    assert scores.iloc[-4:].notna().all()
    prefixes = 0
    for end in [210, 400]:
        axis = signals[:end]
        pf = kernel.rebuild(supplied(daily), supplied(native), supplied(intraday), axis)
        ps, pfit = kernel.annual_forecasts(pf, native, axis)
        ph = kernel.episode_history(ps, axis)
        pd.testing.assert_frame_equal(pf, features.loc[axis])
        pd.testing.assert_series_equal(ps, scores.loc[axis])
        pd.testing.assert_frame_equal(ph, history.loc[axis], check_names=False)
        audit.verify(daily, native, intraday, axis, pf, ps, pfit, ph)
        prefixes += 1
    # Explicit zero/negative score, expiry priority and year-boundary signalclock.
    axis = pd.bdate_range("2021-12-29", periods=10)
    fixture = pd.Series([0.1, -0.2, 0.0, -0.2, 0.3, 0.3, -0.1, 0.0, 0.0, 0.0], index=axis)
    expected = audit.episodes(fixture)
    actual = kernel.episode_history(fixture, axis)
    for name in expected:
        pd.testing.assert_series_equal(
            actual[name], expected[name], check_names=False, check_dtype=False
        )
    assert expected.target_position.tolist() == [1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0]
    assert expected.policy_age.iloc[4] == 4 and pd.isna(expected.episode_entry_position.iloc[4])
    assert kernel.episode_history(pd.Series(0.0, index=axis), axis).target_position.eq(0).all()
    assert kernel.episode_history(pd.Series(np.nan, index=axis), axis).target_position.eq(0).all()
    changed = native.copy()
    changed.loc[changed.index.year == 2026, "Open"] *= 1.7
    new_scores, new_fit = kernel.annual_forecasts(features, changed, signals)
    pd.testing.assert_series_equal(new_scores, scores)
    assert new_fit == fit
    np.testing.assert_array_equal(
        audit.empirical_transform(np.array([1.0, 1.0, 3.0]), np.array([0.0, 1.0, 2.0, 3.0, 4.0])),
        [0, 1 / 3, 2 / 3, 5 / 6, 1],
    )
    refusals = 0
    for bad in [0, 61, True]:
        try:
            audit.episodes(fixture, bad)
        except ValueError:
            refusals += 1
    try:
        audit.scalar_forecasts(features, native, signals, alpha=float("nan"))
    except ValueError:
        refusals += 1
    assert refusals == 4
    record = dict(
        status="PASS",
        artificial_only=True,
        audit=proof,
        focused_checks=8,
        causal_prefix_checks=prefixes,
        refusals=refusals,
        fill_state_inputs=0,
        real_inputs=0,
        real_statistics=0,
        new_accounts=0,
        publication=0,
        source_files={
            name: sha256((HERE / name).read_bytes()).hexdigest()
            for name in ["audit.py", "synthetic.py"]
        },
        main_kernel_sha256=sha256((MAIN / "confirm_kernel.py").read_bytes()).hexdigest(),
    )
    (HERE / "synthetic.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    run()
