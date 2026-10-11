"""Artificial data only; independently test the fixed arithmetic verifier."""

import ast
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

import independent_verification_draft_v2 as audit
import statistics_draft_v2 as study


def run():
    here = Path(__file__).resolve().parent
    freeze = json.loads((here / "source_freeze_v4.json").read_text(encoding="utf-8"))
    assert len(freeze["source_files"]) == 44
    assert all(
        sha256((here / name).read_bytes()).hexdigest() == digest
        for name, digest in freeze["source_files"].items()
    )
    assert audit.CONTROLS == study.CONTROLS and audit.LABELS == study.LABELS
    checks = ["frozen44_unchanged_and_fixed_controls_labels_exact"]
    rng = np.random.default_rng(75051)
    calendar = pd.bdate_range("2020-01-02", periods=421).as_unit("ns")
    axis = calendar[:-1]
    x = rng.normal(size=(420, 19))
    x[:, 2] = x[:, 0]  # exact redundant control: retain it, audit real rank.
    x[0:20, 17] = np.nan
    x[31, 18] = np.nan
    x[258, 3] = np.nan
    features = pd.DataFrame(x, index=axis, columns=[*audit.CONTROLS, audit.COMPONENT])
    labels = pd.DataFrame(index=axis)
    labels["return4_net"] = 0.002 * x[:, 18] + rng.normal(0, 0.02, len(axis))
    labels["downside4_oc"] = np.clip(
        0.03 + 0.002 * x[:, 18] + rng.normal(0, 0.01, len(axis)), 0, 0.5
    )
    # Target is independent of missing feature status: explicit common19 subset.
    labels.loc[axis[[31]], ["return4_net", "downside4_oc"]] = [0.007, 0.02]
    labels["label_end4"] = pd.NaT
    labels.loc[axis[:-4], "label_end4"] = calendar[5:].to_numpy()
    labels.loc[axis[-4:], ["return4_net", "downside4_oc"]] = np.nan
    reported = study.analyze(features, labels, calendar)
    proof = audit.verify_statistics(features, labels, calendar, reported)
    assert proof["bootstrap_records_checked"] == 2000
    for name in audit.LABELS:
        panel = reported["labels"][name]
        assert panel["partial"]["design_rank"] == 18
        assert panel["walk_forward"]["yearly"]["2021"]["reason"] is None
        assert 258 not in panel["walk_forward"]["yearly"]["2021"]["test_positions"]
        assert len(panel["raw_bootstrap"]["replicates"]) == 500
        assert len(panel["partial_bootstrap"]["replicates"]) == 500
    checks.append("full420_axis_2000_statuses_svd_rank_df_ic_linear_ci_predictions_mse")
    # Full calendar tail allows a maturity outside the shorter T feature axis.
    assert labels.label_end4.iloc[-5] == calendar[-1]
    assert labels.label_end4.iloc[-5] not in axis
    checks.append("maturity_uses_price_calendar_tail_and_strict_past_year_boundary")
    np.testing.assert_array_equal(audit.full_axis_blocks(420), study.block_indices(420))
    for rep in audit.full_axis_blocks(420):
        for k in range(0, 420, 40):
            np.testing.assert_array_equal(
                np.diff(rep[k : k + 40]), np.ones(len(rep[k : k + 40]) - 1)
            )
    checks.append("all500_calendar_blocks_seed13_order_truncation_exact")
    np.testing.assert_allclose(
        audit.empirical_transform(np.array([1, 1, 2, 4]), np.array([0, 1, 2, 3, 5])),
        [0, 0.25, 0.625, 0.75, 1],
        rtol=0,
        atol=0,
    )
    checks.append("ecdf_ties_extremes_and_intercept_unpenalized_alpha10")
    a = np.arange(60, dtype=float)
    c = rng.normal(size=(60, 18))
    c[:, 0] = a
    cases = [
        (np.ones(60), a, None, "CONSTANT_COMPONENT"),
        (a, np.ones(60), None, "CONSTANT_TARGET"),
        (a, rng.normal(size=60), c, "EXPLAINED_COMPONENT"),
        (rng.normal(size=60), a, c, "TARGET_EXPLAINED_OR_CONSTANT"),
        (a[:25], rng.normal(size=25), rng.normal(size=(25, 18)), "INSUFFICIENT_RESIDUAL_DF"),
        (a[:19], a[:19], None, "INSUFFICIENT_SAMPLE"),
    ]
    for xx, yy, cc, reason in cases:
        independent, original = audit.ic(xx, yy, cc), study.correlation(xx, yy, cc)
        audit.assert_equal(original, independent)
        assert independent["reason"] == reason
    audit.assert_equal(
        study.bootstrap(a[:30], a[:30], None, None), audit.boot(a[:30], a[:30], None, None)
    )
    # All invalid full-axis replicates retained rather than silently dropping them.
    xx = np.ones(60)
    original = study.bootstrap(xx, a, None, study.block_indices(60))
    audit.assert_equal(original, audit.boot(xx, a, None, audit.full_axis_blocks(60)))
    assert original["status_counts"] == {"CONSTANT_COMPONENT": 500}
    assert original["valid"] == 0 and original["ic95"] is None
    checks.append("constant_explained_low_df_small_n_and_all500_invalid_statuses_null")
    # Prefix forecast does not depend on future year features or targets.
    changed = features.copy()
    changed.loc[axis[-10:], :] = 1000
    original_wf = audit.past_only(axis, x, labels.return4_net.to_numpy(), labels.label_end4)
    altered = audit.past_only(
        axis, changed.to_numpy(), labels.return4_net.to_numpy(), labels.label_end4
    )
    cutoff = axis[-10]
    before = [r for r in original_wf["records"] if pd.Timestamp(r["signaldate"]) < cutoff]
    after = [r for r in altered["records"] if pd.Timestamp(r["signaldate"]) < cutoff]
    audit.assert_equal(after, before)
    checks.append("future_feature_mutation_preserves_earlier_fixed_year_predictions")
    refusals = []

    def rejected(label, mutate):
        changed_report = deepcopy(reported)
        mutate(changed_report)
        try:
            audit.assert_equal(changed_report, audit.recompute(features, labels, calendar))
        except AssertionError:
            refusals.append(label)
        else:
            raise AssertionError("missed tampering: " + label)

    rejected(
        "bootstrap_status",
        lambda r: r["labels"]["return4_net"]["partial_bootstrap"]["replicates"][17].update(
            reason="FAKE"
        ),
    )
    rejected("partial_df", lambda r: r["labels"]["return4_net"]["partial"].update(residual_df=999))
    rejected(
        "prediction",
        lambda r: r["labels"]["return4_net"]["walk_forward"]["records"][0].update(augmented=0.999),
    )
    rejected(
        "pooled_mse",
        lambda r: r["labels"]["return4_net"]["walk_forward"]["aggregate"].update(mse_controls=0.9),
    )
    rejected(
        "finite_row_selection",
        lambda r: r["labels"]["return4_net"]["walk_forward"]["yearly"]["2021"][
            "test_positions"
        ].append(258),
    )
    rejected(
        "linear_ci",
        lambda r: r["labels"]["downside4_oc"]["partial_bootstrap"].update(ic95=[-1.0, 1.0]),
    )
    badlabels = labels.copy()
    badlabels.iloc[0, badlabels.columns.get_loc("label_end4")] = calendar[4]
    for label, f, lab, cal in (
        ("future_maturity", features, badlabels, calendar),
        ("missing_calendar", features, labels, None),
        ("removed_price_tail", features, labels, calendar[:-1]),
        (
            "future_label_as_feature",
            features.assign(label_end4=labels.label_end4),
            labels,
            calendar,
        ),
    ):
        try:
            audit.authenticate_frames(f, lab, cal)
        except (ValueError, AttributeError):
            refusals.append(label)
        else:
            raise AssertionError("missed invalid input: " + label)
    source = (here / "independent_verification_draft_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            assert module.split(".")[0] in {"collections", "numpy", "pandas"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "__import__"}
    spec = importlib.util.spec_from_file_location(
        "pure_independent_audit_import", here / "independent_verification_draft_v2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert all(
        sha256((here / name).read_bytes()).hexdigest() == digest
        for name, digest in freeze["source_files"].items()
    )
    checks.append("pure_import_ast_no_original_stats_import_no_io_and_prior44_exact")
    return dict(
        status="PASS",
        source_only=True,
        actual_inputs_read=0,
        real_statistics_runs=0,
        accounts=0,
        provider_calls=0,
        publications=0,
        checks=checks,
        refusals=refusals,
        comparison=proof["comparison"],
        source_sha256=sha256(
            (here / "independent_verification_draft_v2.py").read_bytes()
        ).hexdigest(),
        checker_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        freeze_sha256=sha256((here / "source_freeze_v4.json").read_bytes()).hexdigest(),
    )


if __name__ == "__main__":
    result = run()
    path = Path(__file__).with_name("independent_verification_synthetic_proof.json")
    with path.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
