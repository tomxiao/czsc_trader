"""Independent checks on retained outputs and chronological prediction isolation."""

from hashlib import sha256

from incremental_study import (
    HERE,
    ROOT,
    WORK,
    evaluate,
    inherited,
    read,
    save,
)
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef


def main():
    refs, _ = inherited()
    source = HERE / "src/incremental_study.py"
    result = read(HERE / "others/incremental_results.json")
    assert sha256(source.read_bytes()).hexdigest() == result["source_sha256"]
    prerefs = read(HERE / "others/protocol_refs.json")
    assert result["source_sha256"] == prerefs[source.name]["sha256"]
    events = pd.read_csv(WORK / "forward_predictions.csv")
    labels = pd.read_csv(refs["event_labels"].resolve(ROOT))
    x = pd.read_csv(WORK / "features_reconstructed.csv")
    assert len(result["comparisons"]) == 18
    assert len(events) == 5832
    assert not events.duplicated(["component", "control", "horizon", "date"]).any()
    assert (events.train_last_exit < events.test_start).all()
    checked_groups = 0
    for row in result["comparisons"]:
        group = events[
            (events.component == row["component"])
            & (events.control == row["control"])
            & (events.horizon == row["horizon"])
        ]
        joined = group.merge(
            labels[labels.horizon.eq(row["horizon"])],
            left_on="date",
            right_on="signal_date",
            suffixes=("", "_source"),
            validate="one_to_one",
        )
        assert len(joined) == row["summary"]["n"] == {1: 325, 2: 324, 3: 323}[row["horizon"]]
        assert joined.status.eq("FILLED").all()
        cash_label = (
            joined.quantity
            * (
                joined.sell_price
                - joined.buy_price
                - 0.001 * (joined.sell_price + joined.buy_price)
            )
            / 100000
        )
        np.testing.assert_allclose(cash_label, joined.label, rtol=1e-11, atol=1e-14)
        for target, actual in (("return", group.label), ("risk", group.downside)):
            base = (group[target + "_base_prediction"] - actual) ** 2
            added = (group[target + "_added_prediction"] - actual) ** 2
            np.testing.assert_allclose(base, group[target + "_base_loss"], atol=1e-14)
            np.testing.assert_allclose(added, group[target + "_added_loss"], atol=1e-14)
            np.testing.assert_allclose(
                1 - added.sum() / base.sum(), row["summary"][target + "_gain"], atol=1e-12
            )
        for year, values in row["years"].items():
            yr = group[group.date.str[:4].eq(year)]
            assert len(yr) == values["n"]
            np.testing.assert_allclose(
                1 - yr.return_added_loss.sum() / yr.return_base_loss.sum(),
                values["return_gain"],
                atol=1e-12,
            )
        for k in (-1, 0, 1):
            assert group.group.eq(k).sum() == row["summary"][f"group_{k}"]["n"]
            checked_groups += 1
    # Perturb ALL labels from the second test fold onward. The first fold's
    # predictions and grouping must stay exactly unchanged (test losses may change).
    modified = labels.copy()
    modified.loc[modified.signal_position.ge(259), ["label", "downside"]] += 0.5
    _, changed_records = evaluate(x, modified, "afternoon_reversal", 3, "PR")
    changed = pd.DataFrame(changed_records)
    first = events[
        (events.component == "afternoon_reversal")
        & (events.control == "PR")
        & (events.horizon == 3)
        & (events.fold == 0)
    ]
    cols = [
        "group",
        "residual_score",
        "return_base_prediction",
        "return_added_prediction",
        "risk_base_prediction",
        "risk_added_prediction",
    ]
    np.testing.assert_allclose(
        first[cols], changed.loc[changed.fold.eq(0), cols], rtol=1e-11, atol=1e-14
    )
    assert not np.allclose(
        changed.loc[changed.fold.eq(3), "return_added_prediction"],
        events.loc[
            (events.component == "afternoon_reversal")
            & (events.control == "PR")
            & (events.horizon == 3)
            & (events.fold == 3),
            "return_added_prediction",
        ],
    )
    for p in (ROOT / "research/S015/experiments/EX008_20261022/others/account_archives.json",):
        for saved in read(p).values():
            EvidenceRef.from_dict(saved).resolve(ROOT)
    report = {
        "status": "PASS",
        "predictions": len(events),
        "paired_conditions": 18,
        "group_counts_checked": checked_groups,
        "net_label_recalculation": "PASS",
        "loss_recalculation": "PASS",
        "yearly_gain_recalculation": "PASS",
        "future_label_perturbation_prediction_isolation": "PASS",
        "prior_archive_hashes": "PASS",
        "scope": "Research output verification; no account acceptance or repository full regression.",
    }
    save(HERE / "others/independent_audit.json", report)
    print(report, flush=True)


if __name__ == "__main__":
    main()
