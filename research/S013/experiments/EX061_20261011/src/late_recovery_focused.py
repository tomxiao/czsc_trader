"""Synthetic-only causal and definition tests; no market/account computation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import late_recovery_component as c


def synthetic(days: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=days)
    offsets = pd.to_timedelta([f"{clock}:00" for clock in c.BAR_END_TIMES])
    index = pd.DatetimeIndex(np.repeat(dates.to_numpy(), 8) + np.tile(offsets.to_numpy(), days), name="Datetime")
    close_path = np.array([99., 98., 97., 96., 98., 99., 100., 101.])
    volume_path = np.array([10., 20., 30., 40., 50., 60., 70., 80.])
    prices = np.tile(close_path, days) + np.repeat(np.arange(days) / 10., 8)
    opens = np.tile(np.r_[100., close_path[:-1]], days) + np.repeat(np.arange(days) / 10., 8)
    return pd.DataFrame({"Open": opens, "Close": prices,
                         "Volume": np.tile(volume_path, days)}, index=index)


def run() -> dict:
    checks, refusals = [], []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def refuse(name: str, mutated: pd.DataFrame) -> None:
        try:
            c.build_features(mutated)
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError(name)

    bars = synthetic()
    result = c.build_features(bars)
    check("canonical_daily_Date_index", result.index.name == "Date" and
          isinstance(result.index, pd.DatetimeIndex) and result.index.equals(bars.index.normalize().unique().rename("Date")))
    check("exact_declared_columns", tuple(result.columns) == (*c.FEATURES, *c.EXPLANATIONS))
    check("single_complete_day_mature_no_window", len(c.build_features(bars.iloc[:8])) == 1 and
          np.isfinite(c.build_features(bars.iloc[:8]).to_numpy()).all())
    check("late_return_definition", np.isclose(result.iloc[0]["late_recovery"], np.log(101. / 99.), atol=1e-14))
    check("early_return_definition", np.isclose(result.iloc[0]["early_return"], np.log(99. / 100.), atol=1e-14))
    check("tail_volume_share_definition", np.isclose(result.iloc[0]["tail_volume_share"], 150. / 360.))
    check("all_early_prices_reclaimed", result.iloc[0]["early_volume_reclaim"] == 1.)
    for days in (1, 3, 20):
        prefix = c.build_features(bars.iloc[:8 * days])
        check(f"prefix_invariance_{days}_days", np.array_equal(prefix.to_numpy(), result.iloc[:days].to_numpy()))
    future = bars.copy()
    future.iloc[8 * 10:, :] *= 10.
    mutated = c.build_features(future)
    check("future_changes_do_not_affect_earlier_features", np.array_equal(mutated.iloc[:10].to_numpy(), result.iloc[:10].to_numpy()))
    rescaled = bars.copy()
    scales = np.repeat(np.geomspace(.01, 100., len(result)), 8)
    rescaled.loc[:, ["Open", "Close", "Volume"]] = rescaled.loc[:, ["Open", "Close", "Volume"]].mul(scales, axis=0)
    scaled_result = c.build_features(rescaled)
    check("cross_day_positive_HFQ_price_volume_scale_invariance", np.allclose(scaled_result.to_numpy(), result.to_numpy(), atol=1e-14, rtol=1e-13))

    path1 = synthetic(1)
    path1["Open"] = 100.
    path1["Close"] = [90., 92., 94., 96., 98., 99., 100., 100.]
    path1["Volume"] = 1.
    path2 = path1.copy()
    path2["Close"] = [110., 108., 106., 104., 102., 101., 100., 100.]
    r1, r2 = c.build_features(path1).iloc[0], c.build_features(path2).iloc[0]
    check("same_daily_net_return_distinct_intraday_paths", path1.iloc[-1]["Close"] / path1.iloc[0]["Open"] ==
          path2.iloc[-1]["Close"] / path2.iloc[0]["Open"] and
          r1["late_recovery"] > 0 and r2["late_recovery"] < 0 and
          r1["early_volume_reclaim"] == 1 and r2["early_volume_reclaim"] == -1)
    reordered1 = synthetic(1)
    reordered1["Open"] = 100.
    reordered1["Close"] = [90., 110., 90., 110., 90., 95., 105., 100.]
    reordered1["Volume"] = 1.
    reordered2 = reordered1.copy()
    reordered2["Close"] = [90., 110., 90., 110., 95., 105., 90., 100.]
    ordered_r1, ordered_r2 = c.build_features(reordered1).iloc[0], c.build_features(reordered2).iloc[0]
    check("same_close_multiset_reordered_path_different_features", np.array_equal(
        np.sort(reordered1["Close"]), np.sort(reordered2["Close"])) and
        ordered_r1["late_recovery"] > 0 and ordered_r2["late_recovery"] < 0 and
        ordered_r1["early_volume_reclaim"] != ordered_r2["early_volume_reclaim"])
    weighted = synthetic(1)
    weighted["Close"] = [90., 110., 100., 100., 100., 100., 100., 100.]
    weighted["Volume"] = [3., 1., 1., 1., 1., 1., 1., 1.]
    value = c.build_features(weighted).iloc[0]
    check("weighted_reclaim_with_exact_price_ties", np.isclose(value["early_volume_reclaim"], (3. - 1.) / 8.))
    altered_volume = weighted.copy()
    altered_volume["Volume"] = [1., 3., 1., 1., 1., 1., 1., 1.]
    check("volume_weights_change_reclaim_at_identical_prices", np.isclose(c.build_features(altered_volume).iloc[0]["early_volume_reclaim"], -.25))
    flat = synthetic(1)
    flat.loc[:, ["Open", "Close"]] = 100.
    flat_result = c.build_features(flat)
    check("zero_features_retained", len(flat_result) == 1 and
          (flat_result.loc[:, list(c.FEATURES)] == 0.).all().all())
    check("negative_features_retained", len(c.build_features(path2)) == 1 and
          (c.build_features(path2).loc[:, list(c.FEATURES)] < 0.).all().all())
    ignored = bars.assign(High=np.nan, Low=-999., future_label=999.)
    check("High_Low_and_labels_are_unused", np.array_equal(c.build_features(ignored).to_numpy(), result.to_numpy()))
    rng = np.random.default_rng(13)
    wide = synthetic(30)
    wide["Close"] = rng.uniform(80., 120., len(wide))
    wide["Volume"] = np.exp(rng.normal(size=len(wide)))
    wide_result = c.build_features(wide)
    check("reclaim_bounded_minus1_plus1", wide_result["early_volume_reclaim"].between(-1., 1.).all())
    check("tail_share_bounded_zero_one", wide_result["tail_volume_share"].between(0., 1.).all())
    tiny_early = synthetic(1)
    tiny_early["Volume"] = [1e-300] * 6 + [1e300] * 2
    check("finite_extreme_volume_ratios", np.isfinite(c.build_features(tiny_early).to_numpy()).all())

    refuse("missing_bar", bars.drop(bars.index[3]))
    extra = pd.concat([bars, bars.iloc[[0]].set_axis(pd.DatetimeIndex([bars.index[0] + pd.Timedelta(minutes=1)]))]).sort_index()
    refuse("extra_offgrid_bar", extra)
    wrong_time = bars.copy()
    times = wrong_time.index.to_list()
    times[0] += pd.Timedelta(seconds=1)
    wrong_time.index = pd.DatetimeIndex(times)
    refuse("wrong_bar_end_time", wrong_time)
    refuse("duplicate_bar", pd.concat([bars.iloc[[0]], bars]))
    refuse("unsorted_bars", bars.iloc[::-1])
    refuse("empty_input", bars.iloc[:0])
    zoned = bars.copy()
    zoned.index = zoned.index.tz_localize("Asia/Shanghai")
    refuse("timezone_ambiguous_input", zoned)
    missing_col = bars.drop(columns=["Volume"])
    refuse("missing_volume_column", missing_col)
    duplicate_col = pd.concat([bars, bars[["Close"]]], axis=1)
    refuse("duplicate_column", duplicate_col)
    for column in ("Open", "Close", "Volume"):
        for name, bad in (("zero", 0.), ("negative", -1.), ("nan", np.nan), ("infinite", np.inf)):
            invalid = bars.copy()
            invalid.loc[invalid.index[0], column] = bad
            refuse(f"{column}_{name}", invalid)
    return {"status": "PASS", "synthetic_only": True, "market_reads": 0, "account_runs": 0,
            "publications": 0, "checks": checks, "refusals": refusals,
            "source_sha256": hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest(),
            "method_sha256": hashlib.sha256(json.dumps(c.METHOD, sort_keys=True,
                                  separators=(",", ":")).encode()).hexdigest()}


if __name__ == "__main__":
    out = Path(__file__).parent
    proof = run()
    (out / "late_recovery_focused.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    c.write_method(out / "late_recovery_method.json")
    print(json.dumps({"status": proof["status"], "checks": len(proof["checks"]),
                      "refusals": len(proof["refusals"]), "source_sha256": proof["source_sha256"]}))
