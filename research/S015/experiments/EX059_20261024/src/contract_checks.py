# ruff: noqa: E402
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
from pathlib import Path
import sys
import json
import importlib.util
import pandas as pd

root = Path.cwd()
base = root / "research/S015/experiments"
home = base / sys.argv[1]


def mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


study = mod(base / "EX051_20261024/src/study.py", "initial_study")
old, _ = study.loader()
adj, raw, bars, rules, ids = old.inputs(old.sources())
m = mod(home / "src/strategy_runtime/strategies/price_process.py", "new_runtime")
prior = mod(
    base / "EX052_20261024/src/strategy_runtime/strategies/price_process.py", "prior_runtime"
)
configs = json.loads((home / "protocols/accounts.json").read_bytes())["configurations"]
n = 0
frames = {}
for lookback, kind in {(p["lookback"], p.get("center_kind")) for p in configs}:
    extra = () if kind is None else (kind,)
    f = m.causal_features(adj, raw, bars, lookback, *extra)
    frames[(lookback, kind)] = f
    for stop in [75, 76, 77, 79, 80, 120, 200, 300, 400, 509]:
        part = m.causal_features(
            adj.iloc[:stop], raw.iloc[:stop], bars.iloc[: max(0, stop - 75) * 8], lookback, *extra
        )
        pd.testing.assert_frame_equal(part, f.iloc[: len(part)])
        n += 1
checks = 0
for p in configs:
    f = frames[(p["lookback"], p.get("center_kind"))]
    out = m.intentions(f, p)
    for stop in [1, 2, 3, 4, 5, 10, 20, 50, 100, 200, 300, 435]:
        pd.testing.assert_frame_equal(m.intentions(f.iloc[:stop], p), out.iloc[:stop])
        checks += 1
    assert out.loc[out.target_position.eq(0), "entry_allocation_fraction"].isna().all()
    assert not (out.entry_signal.eq(1) & out.exit_signal.eq(1)).any()
priorf = prior.causal_features(adj, raw, bars)
f = m.causal_features(adj, raw, bars)
pd.testing.assert_frame_equal(f[priorf.columns], priorf)
for mode in ["U", "center", "momentum", "distributed"]:
    p = dict(
        mode=mode,
        exit_mode="fixed",
        lookback=3,
        concentration=0.75,
        hold=3,
        allocation=1.0,
        start="2025-01-02",
    )
    expected = prior.intentions(priorf, p)
    if "center_kind" in configs[0]:
        p["center_kind"] = "median"
    if "fee_rate" in configs[0]:
        p["fee_rate"] = 0.001
    p.update(confirmation=1, failure_buffer=0.0, max_hold=7)
    out = m.intentions(f, p)
    pd.testing.assert_frame_equal(out[expected.columns], expected)
v = {
    "status": "PASS",
    "physical_feature_prefix_checks": n,
    "intention_prefix_checks": checks,
    "original_four_modes_identical": True,
    "configurations": len(configs),
    "input_ids": ids,
}
(home / "others/runtime_checks.json").write_text(
    json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(v)
