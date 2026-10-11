"""Pure synthetic checks only; no market/statistics/publication calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import order_component as c


def synthetic(returns: list[float], days: int = 1) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=days)
    offsets = pd.to_timedelta([f"{clock}:00" for clock in c.BAR_END_TIMES])
    index = pd.DatetimeIndex(np.repeat(dates.to_numpy(), 8) + np.tile(offsets.to_numpy(), days))
    closes = 100. * np.exp(np.cumsum(returns))
    opens = np.r_[100., closes[:-1]]
    return pd.DataFrame({"Open": np.tile(opens, days), "Close": np.tile(closes, days),
                         "Volume": np.tile(np.arange(1., 9.), days)}, index=index)


def run() -> dict:
    checks, refusals = [], []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def refuse(name: str, bars) -> None:
        try:
            c.build_features(bars)
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError(name)

    bars = synthetic([-.02, -.01, .03, 0., -.04, .04, -.01, -.01], 30)
    result = c.build_features(bars)
    first = result.iloc[0]
    check("declared_schema_and_Date_index", tuple(result.columns) == (*c.FEATURES, *c.CONTROLS)
          and result.index.name == "Date" and len(result) == 30)
    check("known_total_down_up", np.allclose(first[list(c.CONTROLS)], [.09, .07], atol=1e-13))
    check("known_early_share", np.isclose(first.early_down_share, 1. / 3., atol=1e-13))
    check("largest_cumulative_run_not_longest_length", np.isclose(first.max_down_run_share, 4. / 9., atol=1e-13))
    zero_break = c.build_features(synthetic([-.02, 0., -.03, .05, 0., 0., 0., 0.])).iloc[0]
    check("zero_return_interrupts_down_run", np.isclose(zero_break.max_down_run_share, .6, atol=1e-13))
    for name, path in (("flat", [0.] * 8), ("all_up", [.01] * 8)):
        observed = c.build_features(synthetic(path)).iloc[0]
        check(name + "_no_down_zero_semantics_retained", observed.total_down == 0.
              and observed.early_down_share == 0. and observed.max_down_run_share == 0.)
    down = c.build_features(synthetic([-.01] * 8)).iloc[0]
    check("all_down_full_run_and_half_early", np.isclose(down.early_down_share, .5)
          and np.isclose(down.max_down_run_share, 1.))
    early_path = [-.02, -.02, .02, .02, 0., 0., 0., 0.]
    late_path = [0., 0., 0., 0., -.02, -.02, .02, .02]
    early = c.build_features(synthetic(early_path)).iloc[0]
    late = c.build_features(synthetic(late_path)).iloc[0]
    check("same_return_multiset_energy_distinct_timing", np.allclose(early[list(c.CONTROLS)], late[list(c.CONTROLS)])
          and early.early_down_share == 1. and late.early_down_share == 0.)
    alternating = c.build_features(synthetic([-.01, .01] * 4)).iloc[0]
    grouped = c.build_features(synthetic([-.01] * 4 + [.01] * 4)).iloc[0]
    check("same_return_multiset_energy_distinct_continuity", np.allclose(alternating[list(c.CONTROLS)], grouped[list(c.CONTROLS)])
          and np.isclose(alternating.max_down_run_share, .25) and np.isclose(grouped.max_down_run_share, 1.))
    reordered_a = synthetic([0.] * 8)
    reordered_a["Close"] = [90., 95., 105., 110., 100., 100., 100., 100.]
    reordered_a["Volume"] = 1.
    reordered_b = reordered_a.copy()
    reordered_b["Close"] = [110., 105., 95., 90., 100., 100., 100., 100.]
    a, b = c.build_features(reordered_a).iloc[0], c.build_features(reordered_b).iloc[0]

    def old_observations(frame):
        prices = frame["Close"].to_numpy()
        changes = np.diff(np.log(np.r_[frame["Open"].iloc[0], prices]))
        return np.array([np.log(prices[-1] / prices[5]),
                         np.sign(prices[-1] - prices[:6]).mean(),
                         prices[-1] / frame["Open"].iloc[0],
                         np.sum(changes ** 2)])

    check("same_EX061_observations_endpoint_energy_distinct_order",
          np.allclose(old_observations(reordered_a), old_observations(reordered_b))
          and np.allclose(a[list(c.CONTROLS)], b[list(c.CONTROLS)])
          and not np.allclose(a[list(c.FEATURES)], b[list(c.FEATURES)]))
    for days in (1, 3, 20):
        check("prefix_invariance_" + str(days), np.array_equal(c.build_features(bars.iloc[:8 * days]).to_numpy(), result.iloc[:days].to_numpy()))
    future = bars.copy()
    future.iloc[8 * 10:, :] *= 3.
    future.loc[future.index[8 * 10:], "Close"] *= np.linspace(.7, 1.3, len(future) - 8 * 10)
    check("future_mutation_no_effect", np.array_equal(c.build_features(future).iloc[:10].to_numpy(), result.iloc[:10].to_numpy()))
    scaled = bars.copy()
    factors = np.repeat(np.logspace(-100., 100., 30), 8)
    scaled.loc[:, ["Open", "Close"]] = scaled[["Open", "Close"]].mul(factors, axis=0)
    check("session_price_scale_invariance", np.allclose(c.build_features(scaled), result, rtol=1e-10, atol=1e-11))
    volume = bars.copy()
    volume["Volume"] = np.tile([1e-300, 1e300] * 4, 30)
    check("volume_validated_but_unused", np.array_equal(c.build_features(volume), result))
    ignored = bars.assign(High=np.nan, Low=-99., future_profit=999.)
    check("High_Low_future_labels_unused", np.array_equal(c.build_features(ignored), result))
    later_open = bars.copy()
    mask = np.tile([False] + [True] * 7, 30)
    later_open.loc[mask, "Open"] *= 2.
    check("only_first_Open_anchors_returns", np.array_equal(c.build_features(later_open), result))
    rng = np.random.default_rng(13)
    random = bars.copy()
    random["Close"] = rng.uniform(50., 150., len(random))
    random_result = c.build_features(random)
    check("shares_bounded_and_controls_nonnegative", random_result[list(c.FEATURES)].ge(0.).all().all()
          and random_result[list(c.FEATURES)].le(1.).all().all()
          and random_result[list(c.CONTROLS)].ge(0.).all().all())
    refuse("missing_bar", bars.drop(bars.index[3]))
    refuse("duplicate_bar", pd.concat([bars.iloc[[0]], bars]))
    refuse("unsorted_bars", bars.iloc[::-1])
    refuse("empty", bars.iloc[:0])
    refuse("missing_required_column", bars.drop(columns="Volume"))
    refuse("duplicate_column", pd.concat([bars, bars[["Close"]]], axis=1))
    refuse("non_datetime_index", bars.reset_index(drop=True))
    refuse("not_dataframe", None)
    zoned = bars.copy()
    zoned.index = zoned.index.tz_localize("Asia/Shanghai")
    refuse("timezone", zoned)
    wrong = bars.copy()
    times = list(wrong.index)
    times[0] += pd.Timedelta(seconds=1)
    wrong.index = pd.DatetimeIndex(times)
    refuse("wrong_clock", wrong)
    extra = pd.concat([bars, bars.iloc[[0]].set_axis(pd.DatetimeIndex([bars.index[0] + pd.Timedelta(minutes=1)]))]).sort_index()
    refuse("extra_bar", extra)
    missing_time = bars.copy()
    times = list(missing_time.index)
    times[0] = pd.NaT
    missing_time.index = pd.DatetimeIndex(times)
    refuse("NaT", missing_time)
    for column in ("Open", "Close", "Volume"):
        for name, bad in (("zero", 0.), ("negative", -1.), ("nan", np.nan), ("inf", np.inf)):
            invalid = bars.copy()
            invalid.loc[invalid.index[0], column] = bad
            refuse(column + "_" + name, invalid)
    invalid = bars.copy()
    invalid["Close"] = "bad"
    refuse("nonnumeric", invalid)
    return {"status": "PASS", "synthetic_only": True, "market_reads": 0, "statistics_runs": 0,
            "account_runs": 0, "publications": 0, "experiment_creations": 0,
            "checks": checks, "refusals": refusals,
            "source_sha256": hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest(),
            "check_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__ == "__main__":
    folder = Path(__file__).parent
    proof = run()
    (folder / "focused_checks.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    c.write_method(folder / "method.json")
    print(json.dumps({"status": proof["status"], "checks": len(proof["checks"]), "refusals": len(proof["refusals"])}))
