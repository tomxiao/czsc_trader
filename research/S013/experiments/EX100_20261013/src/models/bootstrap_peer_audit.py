"""Independent read-only result arithmetic audit; no model fit or clock replay in bootstrap."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-stage2-20261013"
sys.path.insert(0, str(WORK))
import governance as g


def read_csv(path):
    frame = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    frame.index = pd.to_datetime(frame.index).as_unit("ns")
    return frame


def same(actual, expected):
    if expected is None:
        assert actual is None
    else:
        assert actual is not None and np.isclose(actual, expected, rtol=2e-10, atol=2e-14), (actual, expected)


def audit(number):
    if number not in (99, 100):
        raise ValueError("only authorized two result sets")
    out = WORK / f"result{number}"
    stats = g.read(out / "statistics.json")
    features = read_csv(WORK / "inputs/features.csv")
    labels = read_csv(WORK / "execution/labels.csv")
    scores = read_csv(out / "all_scores.csv")
    baseline = read_csv(WORK / "result99/means.csv")
    axis = features.index
    assert axis.equals(labels.index) and axis.equals(scores.index) and axis.equals(baseline.index)
    common = np.isfinite(features.to_numpy(float)).all(axis=1)
    y, mean = labels.l1.to_numpy(float), baseline.l1.to_numpy(float)
    selection = {}
    for name in scores:
        selection[name] = {}
        for clock in ("greedy", *(f"clock_{p}" for p in range(5))):
            frame = read_csv(out / "selections" / f"{name}_{clock}.csv")
            assert frame.index.equals(axis) and frame.selected.dtype == bool
            selection[name][clock] = frame.selected.to_numpy(bool)
    masks = {"all": np.ones(len(axis), bool),
             **{f"year_{z}": axis.year == z for z in range(2020, 2027)},
             **{f"phase_{p}": np.arange(len(axis)) % 5 == p for p in range(5)}}
    n = len(axis)
    draws = None
    if n >= 40:
        rng = np.random.default_rng(13)
        starts = rng.integers(0, n - 40 + 1, size=(500, int(np.ceil(n / 40))))
        draws = np.concatenate([starts[:, j, None] + np.arange(40)
                                for j in range(starts.shape[1])], axis=1)[:, :n]
    checked_panels, checked_boot_values = 0, 0
    for pair, panels in stats["paired"].items():
        new, old = pair.split("-")
        a, b = scores[new].to_numpy(float), scores[old].to_numpy(float)
        forecast_support = common & np.isfinite(a) & np.isfinite(b)
        support = forecast_support & np.isfinite(y) & np.isfinite(mean)
        for panel_name, scope in masks.items():
            panel = panels[panel_name]
            assert panel["paired_forecast_n"] == int((scope & forecast_support).sum())
            valid_score = scope & support
            score_n = int(valid_score.sum())
            ma = float(np.mean((y[valid_score]-a[valid_score])**2)) if score_n >= 20 else None
            mb = float(np.mean((y[valid_score]-b[valid_score])**2)) if score_n >= 20 else None
            same(panel["mse_reduction"], mb-ma if ma is not None else None)
            for clock in ("positive", "greedy", *(f"clock_{p}" for p in range(5))):
                means = {}
                for model, prediction, key in ((new, a, "new"), (old, b, "old")):
                    selected = prediction > 0 if clock == "positive" else selection[model][clock]
                    candidates = scope & forecast_support & selected
                    mature = candidates & np.isfinite(y)
                    count = int(mature.sum())
                    expected = float(y[mature].mean()) if count >= 20 else None
                    record = panel[key][clock]
                    assert record["selected_forecast_n"] == int(candidates.sum())
                    assert record["selected_mature_n"] == count
                    assert record["selected_unscored_n"] == int((candidates & ~np.isfinite(y)).sum())
                    same(record["mean_l1"], expected)
                    same(record["loss_rate"], float((y[mature] < 0).mean()) if count >= 20 else None)
                    same(record["nonpositive_rate"], float((y[mature] <= 0).mean()) if count >= 20 else None)
                    means[key] = expected
                same(panel[clock+"_mean_delta"], means["new"]-means["old"]
                     if means["new"] is not None and means["old"] is not None else None)
            checked_panels += 1
        sa, sb = selection[new]["greedy"], selection[old]["greedy"]
        def value(rows):
            valid = support[rows]
            yy, aa, bb = y[rows][valid], a[rows][valid], b[rows][valid]
            pa, pb = yy[aa > 0], yy[bb > 0]
            ga, gb = y[rows][valid & sa[rows]], y[rows][valid & sb[rows]]
            def delta(x, z):
                return float(x.mean()-z.mean()) if min(len(x),len(z)) >= 20 else None
            return {"mse_reduction":float(np.mean((yy-bb)**2-(yy-aa)**2)) if len(yy)>=20 else None,
                    "positive_mean_delta":delta(pa,pb), "greedy_mean_delta":delta(ga,gb)}, {
                        "paired":len(yy),"positive_new":len(pa),"positive_old":len(pb),
                        "greedy_new":len(ga),"greedy_old":len(gb)}
        boot = stats["bootstrap"]["pairs"][pair]
        original, original_n = value(np.arange(n))
        assert boot["original_counts"] == original_n
        independently_valid = {key: [] for key in original}
        assert len(boot["records"]) == 500
        for i, record in enumerate(boot["records"]):
            vals, counts = value(draws[i]) if draws is not None else ({k:None for k in original}, {})
            assert record["replicate"] == i and record["counts"] == counts
            for key, expected in vals.items():
                same(record["values"][key], expected)
                assert record["status"][key] == ("VALID" if expected is not None else "INSUFFICIENT_SUPPORT")
                if expected is not None:
                    independently_valid[key].append(expected)
                checked_boot_values += 1
        for key, expected in original.items():
            record, values = boot["summary"][key], independently_valid[key]
            same(record["original"], expected)
            assert record["valid_replicates"] == len(values)
            enough = expected is not None and len(values) >= 400
            if enough:
                np.testing.assert_allclose(record["ci95"], np.quantile(values,[.025,.975],method="linear"),
                                           rtol=2e-10,atol=2e-14)
                assert record["reason"] is None
            else:
                assert record["ci95"] is None and record["reason"] == "INSUFFICIENT_ORIGINAL_OR_REPLICATES"
    assert stats["bootstrap"]["block_days"] == 40 and stats["bootstrap"]["replicates"] == 500
    assert stats["bootstrap"]["seed"] == 13 and stats["bootstrap"]["refits"] == 0
    assert not stats["bootstrap"]["replayed_clock"]
    result = {"status":"PASS","round":number,"paired_panels_verified":checked_panels,
              "bootstrap_replicate_quantities_verified":checked_boot_values,
              "paired_positive_greedy_five_clock_means_counts_losses_verified":True,
              "common_day_axis_seed40_500_seed13_verified":True,"valid_repeats_and_linear95_intervals_verified":True,
              "real_additional_model_fits":0,"source_kernel_calls":0,"bootstrap_clock_replays":0,
              "statistics_sha256":g.digest(out/"statistics.json")}
    g.write(out/"bootstrap_peer_verification.json", result)
    print(result)


if __name__ == "__main__":
    audit(int(sys.argv[1]))
