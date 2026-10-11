"""One artificial fixture comparison only; never loads real frames or wrappers."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import independent_curvature_verification as audit


def main():
    here = Path(__file__).resolve().parent
    module_path = here.parent / "curvature_statistics.py"
    spec = importlib.util.spec_from_file_location("artificial_curvature_statistics", module_path)
    kernel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kernel)
    assert audit.CONTROLS == kernel.CONTROLS and len(audit.CONTROLS) == 17
    assert audit.COMPONENT == kernel.COMPONENT == "curvature4"
    assert np.array_equal(audit.ranks(np.array([3, 1, 1, 2])), [4, 1.5, 1.5, 3])
    assert np.array_equal(audit.full_axis_blocks(122), kernel.block_indices(122))
    assert audit.full_axis_blocks(39) is None
    assert np.array_equal(
        audit.empirical_transform(np.array([1, 1, 3]), np.array([0, 1, 2, 3, 4])),
        [0, 1 / 3, 2 / 3, 5 / 6, 1],
    )
    rng = np.random.default_rng(23)
    calendar = (
        pd.bdate_range("2020-01-02", periods=60)
        .append(pd.bdate_range("2021-01-04", periods=32))
        .append(pd.bdate_range("2022-01-03", periods=30))
        .as_unit("ns")
    )
    index = calendar.copy()
    values = rng.integers(-9, 10, (len(index), 18)).astype(float)
    values[:2, 0] = np.nan
    features = pd.DataFrame(values, index=index, columns=(*audit.CONTROLS, audit.COMPONENT))
    ends = pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    ends.iloc[:-5] = calendar[5:].to_numpy()
    labels = pd.DataFrame(
        {
            "return4_net": rng.normal(0.004, 0.02, len(index)),
            "downside4_oc": rng.uniform(0, 0.06, len(index)),
            "label_end4": ends,
        },
        index=index,
    )
    labels.loc[index[-5:], list(audit.LABELS)] = np.nan
    scope = pd.Series(np.arange(len(index)) % 4 != 0, index=index)
    before = features.copy(deep=True), labels.copy(deep=True), scope.copy(deep=True)
    # This invocation is explicitly confined to this freshly constructed fixture.
    reported = kernel.analyze(features, labels, calendar, flat_eligible=scope)
    verification = audit.verify_statistics(
        features, labels, calendar, reported, flat_eligible=scope
    )
    assert verification["comparison"]["prediction_comparisons"] > 0
    assert verification["bootstrap_records_checked"] == 4000
    for name, panel in reported["scopes"].items():
        assert panel["full_axis_n"] == len(index)
        for label in audit.LABELS:
            for year, row in panel["labels"][label]["walk_forward"]["yearly"].items():
                if row["train_positions"]:
                    assert pd.Timestamp(row["latest_train_label_end"]) < pd.Timestamp(
                        row["first_actual_signaldate"]
                    )
                if name != "all":
                    assert all(
                        scope.iloc[p] for p in (*row["train_positions"], *row["test_positions"])
                    )
            if name != "all":
                assert all(scope.iloc[p] for p in panel["labels"][label]["raw"]["finite_positions"])
    for current, original in zip((features, labels, scope), before):
        if isinstance(current, pd.Series):
            pd.testing.assert_series_equal(current, original)
        else:
            pd.testing.assert_frame_equal(current, original)
    refused = 0
    for invalid_scope in (
        scope.astype(int),
        scope.iloc[1:],
        scope.rename(index={index[0]: index[0] + pd.Timedelta(hours=1)}),
    ):
        try:
            audit.recompute(features, labels, calendar, flat_eligible=invalid_scope)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("invalid scope accepted")
    wrong_maturity = labels.copy()
    wrong_maturity.loc[index[10], "label_end4"] = calendar[14]
    future_features = features.assign(return4_net=labels.return4_net)
    for bad_features, bad_labels in ((features, wrong_maturity), (future_features, labels)):
        try:
            audit.authenticate_frames(bad_features, bad_labels, calendar)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("future/maturity assertion lost")
    bad = deepcopy(reported)
    bad["scopes"]["causal_original_policy_flat_eligible"]["full_axis_n"] -= 1
    try:
        audit.assert_equal(bad, reported)
    except AssertionError:
        refused += 1
    else:
        raise AssertionError("compressed scope axis accepted")
    assert audit.ic(np.ones(40), np.arange(40))["reason"] == "CONSTANT_COMPONENT"
    assert audit.ic(np.arange(10), np.arange(10))["reason"] == "INSUFFICIENT_SAMPLE"
    result = {
        "status": "PASS",
        "artificial_only": True,
        "fixture_axis_n": len(index),
        "scopes": ["all", "causal_original_policy_flat_eligible"],
        "scope_only_target_mask": True,
        "fixed_controls": 17,
        "features": 18,
        "refusals": refused,
        "verification": verification,
        "source_hashes": {
            name: sha256((here / name).read_bytes()).hexdigest()
            for name in ("independent_curvature_verification.py", "focused_proof.py")
        },
        "production_kernel_sha256": sha256(module_path.read_bytes()).hexdigest(),
        "real_data_reads": 0,
        "real_statistics": 0,
        "accounts": 0,
        "provider": 0,
        "publication": 0,
    }
    (here / "focused_proof.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
    )
    print(result)


if __name__ == "__main__":
    main()
