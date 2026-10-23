"""Reconcile selected/forgone opportunity amounts; no account simulation or selection."""

from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from czsc_trader.research_tools import EvidenceRef

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
MODES = ("U", "center", "distributed", "concentrated", "impulse", "momentum")


def read(path):
    return json.loads(path.read_bytes())


def amount(values):
    return {
        "observations": len(values),
        "positive_count": int(values.gt(0).sum()),
        "negative_count": int(values.lt(0).sum()),
        "zero_count": int(values.eq(0).sum()),
        "positive_amount_yuan": float(values.clip(lower=0).sum()),
        "negative_amount_yuan": float(-values.clip(upper=0).sum()),
        "net_amount_yuan": float(values.sum()),
    }


def main():
    target = HERE / "others/opportunity_cost.json"
    if target.exists():
        raise FileExistsError("Preserve the existing analysis; do not silently overwrite")
    refs = read(HERE / "others/protocol_refs.json")
    for relative, value in refs.items():
        ref = EvidenceRef.from_dict(value)
        if ref.experiment.strategy_id != "S015":
            raise ValueError("Only S015 evidence is in scope")
        assert ref.resolve(ROOT).read_bytes() == (ROOT / relative).read_bytes()
    protocol = read(HERE / "protocols/process.json")
    event_ref = EvidenceRef.from_dict(protocol["events"])
    assert event_ref.experiment.strategy_id == "S015"
    events = pd.read_csv(event_ref.resolve(ROOT))
    features_path = HERE / "others/features.csv"
    features = pd.read_csv(features_path)
    assert len(features) == 434 and features.date.is_unique
    assert all(features[col].dtype == bool for col in ("feature_ready", *MODES))
    assert features.U.equals(features.feature_ready)
    events = events[events.horizon.eq(3)]
    assert len(events) == 434 and events.date.is_unique
    merged = events.merge(features, on="date", validate="one_to_one")
    base = merged[merged.feature_ready]
    rows = []
    existing = read(HERE / "others/results.json")
    for mode in MODES:
        selected = base[mode]
        for label, summary_key in (("entry_net", "entry"), ("net", "net")):
            known = base[label].notna()
            all_values = base.loc[known, label]
            denominator = amount(all_values)
            parts = {}
            for name, mask in (("selected", selected), ("rejected", ~selected)):
                values = base.loc[known & mask, label]
                part = amount(values)
                part["positive_amount_fraction"] = (
                    part["positive_amount_yuan"] / denominator["positive_amount_yuan"]
                    if denominator["positive_amount_yuan"]
                    else None
                )
                part["negative_amount_fraction"] = (
                    part["negative_amount_yuan"] / denominator["negative_amount_yuan"]
                    if denominator["negative_amount_yuan"]
                    else None
                )
                part["signals"] = int(mask.sum())
                part["unobserved_labels"] = int((mask & ~known).sum())
                part["status_counts"] = {
                    str(k): int(v) for k, v in base.loc[mask, "status"].value_counts().items()
                }
                parts[name] = part
            for key in (
                "observations",
                "positive_count",
                "negative_count",
                "zero_count",
                "positive_amount_yuan",
                "negative_amount_yuan",
                "net_amount_yuan",
            ):
                assert np.isclose(
                    parts["selected"][key] + parts["rejected"][key],
                    denominator[key],
                    rtol=1e-12,
                    atol=1e-8,
                ), (mode, label, key)
            old = next(
                row
                for row in existing["rows"]
                if row["mode"] == mode
                and row["horizon"] == 3
                and row["year"] == "all"
                and row["sample"] == "all"
            )[summary_key]
            assert parts["selected"]["observations"] == old["n"]
            assert np.isclose(parts["selected"]["positive_amount_yuan"] / 100000, old["positive"])
            assert np.isclose(parts["selected"]["negative_amount_yuan"] / 100000, old["negative"])
            rows.append({"mode": mode, "label": label, "denominator": denominator, **parts})
    result = {
        "analysis": "Prospectively requested h3 opportunity-cost decomposition; deterministic reuse, not a new experiment",
        "rounds_added": 0,
        "event_reference": event_ref.to_dict(),
        "features_sha256": sha256(features_path.read_bytes()).hexdigest(),
        "population": {
            "all_development_sessions": 434,
            "feature_ready_opportunities": len(base),
            "feature_not_ready": int((~merged.feature_ready).sum()),
            "start": base.date.min(),
            "end": base.date.max(),
            "horizon": 3,
            "status_counts": {str(k): int(v) for k, v in base.status.value_counts().items()},
        },
        "semantics": {
            "capital": "Each event independently starts with 100000 yuan. Events overlap; their sums are not a continuous portfolio/account PnL.",
            "entry_net": "Actual entry-session marked PnL after buy fee; label can be observed before the three-day exit is available.",
            "net": "Actual closed three-session event PnL after both fees; unfilled or right-censored outcomes remain unobserved, never zero-filled.",
            "fractions": "Selected/rejected positive amounts divided by all observed positive amounts in the feature_ready population; negative fractions analogously use absolute loss amounts. Not prediction accuracy.",
            "execution": "Authenticated EX026 event labels make one T+1 buy attempt, unlike continuous-account cycle retry semantics.",
        },
        "rows": rows,
        "checks": {
            "partition_reconciled": True,
            "existing_EX051_summary_reconciled": True,
            "account_equivalence_claimed": False,
        },
    }
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"opportunities": len(base), "rows": len(rows), "checks": result["checks"]}),
        flush=True,
    )


if __name__ == "__main__":
    main()
