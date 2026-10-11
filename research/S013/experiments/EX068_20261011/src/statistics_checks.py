"""Focused synthetic model/maturity contract checks; no market statistics."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import opportunity_statistics as s

index = pd.bdate_range("2020-01-02", periods=100).append(pd.bdate_range("2021-01-04", periods=45))
rng = np.random.default_rng(13)
features = pd.DataFrame(rng.normal(size=(len(index), 20)), index=index, columns=[*s.CONTROLS, *s.COMPONENTS])
target = .01 * features.early_down_share.to_numpy() + rng.normal(0., .005, len(index))
ends = pd.Series(index + pd.Timedelta(days=10), index=index)
result = s._walk_forward(index, features, target, ends, np.ones(len(index), bool))
checks = []
assert len(s.CONTROLS) == 18 and len(s.COMPONENTS) == 2 and len(s.HORIZONS) == 4
checks.append("18controls2components4labels")
assert tuple(result["aggregate_models"]) == ("controls", "controls+early", "controls+run", "controls+both")
checks.append("four_models_declared")
assert len({v["n"] for v in result["aggregate_models"].values()}) == 1
checks.append("same_test_rows")
assert pd.Timestamp(result["yearly"]["2021"]["latest_train_label_end"]) < index[100]
checks.append("strict_mature_training")
changed = features.copy()
changed.iloc[100:] *= 100.
assert np.array_equal(s._cdf_apply(features.iloc[:100, 0].to_numpy(), features.iloc[:100, 0].to_numpy()), s._cdf_apply(changed.iloc[:100, 0].to_numpy(), changed.iloc[:100, 0].to_numpy()))
checks.append("future_change_no_training_rank_effect")
assert s._ic(np.ones(30), np.arange(30.))["value"] is None
checks.append("constant_is_unavailable")
assert s._ic(np.arange(19.), np.arange(19.))["value"] is None
checks.append("thin_sample_unavailable")
payload = {"status": "PASS", "checks": checks, "count": len(checks), "synthetic_only": True, "market_reads": 0}
Path(__file__).with_name("statistics_checks.json").write_text(json.dumps(payload, indent=2), "utf-8")
print({"status": "PASS", "count": len(checks)})
