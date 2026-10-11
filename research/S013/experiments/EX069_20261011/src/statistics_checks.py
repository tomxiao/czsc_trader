"""Pure synthetic residual-DF and mature shared-row model checks."""

from pathlib import Path
import json
import numpy as np
import pandas as pd
import opportunity_statistics as s

rng = np.random.default_rng(13)
checks = []
for n, expect in ((30, False), (31, True)):
    control = rng.normal(size=(n, 20))
    x, y = rng.normal(size=n), rng.normal(size=n)
    result = s._ic(x, y, control)
    assert result["design_rank"] == 21 and result["residual_df"] == n - 21
    assert (result["value"] is not None) == expect
    if not expect:
        assert result["reason"] == "INSUFFICIENT_RESIDUAL_DF"
    checks.append("df_boundary_" + str(n))
control = np.column_stack([np.arange(20.0)] * 20)
result = s._ic(rng.normal(size=20), rng.normal(size=20), control)
assert result["design_rank"] == 2 and result["residual_df"] == 18 and result["value"] is not None
checks.append("actual_design_rank_not_control_count")
small = s._ic(rng.normal(size=20), rng.normal(size=20), rng.normal(size=(20, 20)))
assert small["residual_df"] == 0 and small["value"] is None
checks.append("thin_full_rank_phase_not_fake_plus_minus_one")
index = pd.bdate_range("2020-01-02", periods=100).append(pd.bdate_range("2021-01-04", periods=45))
features = pd.DataFrame(
    rng.normal(size=(len(index), 22)), index=index, columns=[*s.CONTROLS, *s.COMPONENTS]
)
target = 0.01 * features.short_stretch4.to_numpy() + rng.normal(0.0, 0.005, len(index))
ends = pd.Series(index + pd.Timedelta(days=10), index=index)
models = s._walk_forward(index, features, target, ends, np.ones(len(index), bool))
assert len(s.CONTROLS) == 20 and len(s.COMPONENTS) == 2 and len(s.HORIZONS) == 4
checks.append("20controls2components4labels")
assert tuple(models["aggregate_models"]) == (
    "controls",
    "controls+stretch",
    "controls+overnight",
    "controls+both",
)
checks.append("four_predeclared_models")
assert len({v["n"] for v in models["aggregate_models"].values()}) == 1
checks.append("identical_model_rows")
assert pd.Timestamp(models["yearly"]["2021"]["latest_train_label_end"]) < index[100]
checks.append("maturity_strict")
assert s._ic(np.ones(30), np.arange(30.0))["value"] is None
checks.append("constant_unavailable")
payload = {
    "status": "PASS",
    "checks": checks,
    "count": len(checks),
    "synthetic_only": True,
    "market_reads": 0,
}
Path(__file__).with_name("statistics_checks.json").write_text(
    json.dumps(payload, indent=2), "utf-8"
)
print({"status": "PASS", "count": len(checks)})
