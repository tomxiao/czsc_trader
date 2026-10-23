from pathlib import Path
import json
import importlib.util
import pandas as pd

root = Path.cwd()
home = root / "research/S015/experiments/EX052_20261024"
path = home / "src/strategy_runtime/strategies/price_process.py"
spec = importlib.util.spec_from_file_location("runtime", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
f = pd.read_csv(
    root / "research/S015/experiments/EX051_20261024/others/features.csv",
    index_col="date",
    parse_dates=["date"],
)
cols = [
    "m",
    "p",
    "dcenter",
    "center_gain",
    "concentration",
    "up_count",
    "atr",
    "r1",
    "r3",
    "r5",
    "vol20",
    "feature_ready",
]
f = f[cols]
seed = pd.DataFrame(
    [{**{k: 0.0 for k in cols}, "feature_ready": False}],
    index=pd.DatetimeIndex(["2024-12-31"], name="date"),
)
f = pd.concat([seed, f])
configs = json.loads((home / "protocols/accounts.json").read_bytes())["configurations"]
n = 0
for p in configs:
    out = m.intentions(f, p)
    for stop in list(range(1, 12)) + list(range(15, len(f), 20)) + [len(f)]:
        pd.testing.assert_frame_equal(m.intentions(f.iloc[:stop], p), out.iloc[:stop])
        n += 1
    assert out.loc[out.target_position.eq(0), "entry_allocation_fraction"].isna().all()
    assert out.loc[out.target_position.gt(0), "entry_allocation_fraction"].eq(p["allocation"]).all()
    assert not (out.entry_signal.eq(1) & out.exit_signal.eq(1)).any()
    if p["exit_mode"] == "fixed":
        assert out.intent_age.max() <= p["hold"]
bad = dict(configs[0], allocation=0)
try:
    m.validate_parameters(bad)
except ValueError:
    pass
else:
    raise AssertionError("invalid fraction accepted")
v = {
    "status": "PASS",
    "intention_prefix_checks": n,
    "physical_feature_prefix_checks": json.loads(
        (root / "research/S015/experiments/EX051_20261024/others/results.json").read_bytes()
    )["physical_prefix_checks"],
    "configuration_count": len(configs),
    "checks": [
        "truncated histories identical",
        "flat null allocation",
        "constant within-cycle allocation",
        "no same-day exit/reentry",
        "fixed intent age bounded",
        "invalid zero fraction rejected",
    ],
    "limits": "No predictive claim; serial-parallel checks performed in account preflight.",
}
(home / "others/runtime_checks.json").write_text(json.dumps(v, indent=2) + "\n", encoding="utf-8")
print(v)
