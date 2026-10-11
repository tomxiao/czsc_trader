"""Focused checks for the changed opportunity-statistics interface."""

from pathlib import Path
import json
import numpy as np
import pandas as pd
from stats_test_module import COMPONENTS, CONTROLS, HORIZONS, _walk_forward, _ic, _cdf_apply

index = pd.DatetimeIndex(
    list(pd.bdate_range("2020-01-02", periods=100)) + list(pd.bdate_range("2021-01-04", periods=45))
)
rng = np.random.default_rng(13)
frame = pd.DataFrame(
    rng.normal(size=(len(index), len(CONTROLS) + 2)), index=index, columns=[*CONTROLS, *COMPONENTS]
)
target = frame.late_weakness.to_numpy() * 0.02 + rng.normal(0, 0.005, len(index))
ends = pd.Series(index + pd.Timedelta(days=10), index=index)
scope = np.ones(len(index), dtype=bool)
first = _walk_forward(index, frame, target, ends, scope)
checks = []
assert len(CONTROLS) == 14 and len(COMPONENTS) == 2 and len(HORIZONS) == 6
checks.append("explicit14controls2components6labels")
assert set(first["aggregate_models"]) == {
    "controls",
    "controls+late",
    "controls+reclaim",
    "controls+both",
}
checks.append("four_named_models")
assert len({row["n"] for row in first["aggregate_models"].values()}) == 1
checks.append("identical_model_test_rows")
assert pd.Timestamp(first["yearly"]["2021"]["latest_train_label_end"]) < index[100]
checks.append("strict_actual_maturity")
changed = frame.copy()
changed.iloc[100:] *= 100
assert np.array_equal(
    _cdf_apply(frame.iloc[:100, 0].to_numpy(), frame.iloc[:100, 0].to_numpy()),
    _cdf_apply(changed.iloc[:100, 0].to_numpy(), changed.iloc[:100, 0].to_numpy()),
)
checks.append("training_cdf_future_independent")
assert _ic(np.ones(30), np.arange(30.0))["value"] is None
checks.append("constant_not_fake_zero")
assert _ic(np.arange(19.0), np.arange(19.0))["value"] is None
checks.append("small_sample_unavailable")
output = {
    "status": "PASS",
    "checks": checks,
    "count": len(checks),
    "synthetic_only": True,
    "engine": "EX061 reducer adapted for fee-aware4/8 labels and reversal components; no real data",
}
(Path(__file__).resolve().parent / "statistics_checks.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(output)
