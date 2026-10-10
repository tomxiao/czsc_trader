"""Read-only reconstruction of center-conditioned historical parameter scales.

No account evaluation or source mutation. The original fixed center thresholds
remain unchanged; quantile endpoints only define this experiment's distances.
"""

from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "research/S007/assets/runs/EX004_20261010/domain-audit.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def causal_percentile(values):
    def last(items):
        valid = items[np.isfinite(items)]
        current = items[-1]
        if not np.isfinite(current) or len(valid) < 20:
            return np.nan
        return float(
            (np.count_nonzero(valid < current) + 0.5 * np.count_nonzero(valid == current))
            / len(valid)
            - 0.5
        )

    return values.astype(float).rolling(252, min_periods=20).apply(last, raw=True)


def main():
    seed_path = "strategies/S007/releases/v1/runtime/strategy_runtime/resources/s007_v1_seed.csv.gz"
    source_paths = [
        seed_path,
        "experiments/S007/20260915_S007_EX04/artifacts/causal_feature_panel.csv.gz",
        "experiments/S007/20260915_S007_EX27/artifacts/protocol.json",
        "experiments/S007/20260915_S007_EX27/run_experiment.py",
        "experiments/S007/20260915_S007_EX28/artifacts/protocol.json",
        "experiments/S007/20260915_S007_EX28/artifacts/selected_configuration.json",
        "experiments/S007/20260915_S007_EX31/candidate_payload.json",
        "research/S013/experiments/EX004_20261007/src/search.py",
        "research/S013/experiments/EX004_20261007/src/prepare_followup3.py",
        "research/S013/experiments/EX004_20261007/src/prepare_followup4.py",
        "research/S013/experiments/EX004_20261007/src/prepare_adaptive_followup.py",
        "research/S013/experiments/EX004_20261007/src/prepare_adaptive_entry_extension.py",
        "research/S013/experiments/EX006_20261009/src/declare.py",
        "research/S013/experiments/EX006_20261009/src/declare_context.py",
        "research/S013/experiments/EX007_20261009/src/strategy_runtime/strategies/confirmed_range.py",
        "research/S013/experiments/EX007_20261009/src/strategy_runtime/strategies/reentry_confirmed_range.py",
    ]
    hashes = {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths}
    assert hashes[seed_path] == "32282766b0f65be661dfad9bd0f0f5c683ef84eef4ae2817a195730d03b59a39"
    seed = pd.read_csv(ROOT / seed_path, parse_dates=["Date"]).set_index("Date")
    panel = pd.read_csv(ROOT / source_paths[1], parse_dates=["date"]).set_index("date")
    selected_panel = panel.loc[:, seed.columns].rename_axis("Date")
    assert seed.index.equals(selected_panel.index)
    assert seed.isna().equals(selected_panel.isna())
    differences = (seed - selected_panel).abs()
    panel_seed_difference = {k: float(differences[k].max()) for k in seed.columns}
    assert max(panel_seed_difference.values()) < 1e-12
    frozen = read("experiments/S007/20260915_S007_EX31/candidate_payload.json")["rule"]["score"]
    historical = read("experiments/S007/20260915_S007_EX28/artifacts/selected_configuration.json")
    bounds = read("experiments/S007/20260915_S007_EX28/artifacts/protocol.json")[
        "effective_parameter_bounds"
    ]
    original_protocol = read("experiments/S007/20260915_S007_EX27/artifacts/protocol.json")
    discovery = original_protocol["segments"]
    normalized = pd.DataFrame(
        {k: causal_percentile(seed[k]) * frozen["orientations"][k] for k in frozen["orientations"]}
    )
    historical_normalized = pd.DataFrame(
        {
            k: causal_percentile(selected_panel[k]) * frozen["orientations"][k]
            for k in frozen["orientations"]
        }
    )
    pd.testing.assert_frame_equal(normalized, historical_normalized, check_exact=True)
    base = (
        normalized.mul(pd.Series(frozen["base_weights"]), axis=1)
        .sum(axis=1)
        .where(normalized[list(frozen["base_weights"])].notna().all(axis=1))
    )
    confirmation = (
        normalized.mul(pd.Series(frozen["confirmation_weights"]), axis=1)
        .sum(axis=1)
        .where(normalized[list(frozen["confirmation_weights"])].notna().all(axis=1))
    )
    mask = base.index.to_series().between(discovery["discovery_start"], discovery["discovery_end"])
    holding, targets = 0, []
    for value in base:
        if np.isfinite(value):
            if holding == 0 and value >= frozen["entry_threshold"]:
                holding = 1
            elif holding == 1 and value <= frozen["exit_threshold"]:
                holding = 0
        targets.append(holding)
    target = pd.Series(targets, index=base.index)
    entry_mask = target.gt(target.shift(1, fill_value=0)) & mask
    base_discovery = base.loc[mask].dropna()
    gate_discovery = confirmation.loc[entry_mask].dropna()
    assert len(base_discovery) == 689 and len(gate_discovery) == 102
    mapped, reconstructed, errors = {}, {}, {}
    for name, quantile, series in (
        ("entry_threshold", "entry_quantile", base_discovery),
        ("exit_threshold", "exit_quantile", base_discovery),
        ("confirmation_threshold", "confirmation_gate_quantile", gate_discovery),
    ):
        endpoints = [float(series.quantile(q, interpolation="linear")) for q in bounds[quantile]]
        center = float(frozen[name])
        mapped[name] = {
            "bounds": endpoints,
            "width": endpoints[1] - endpoints[0],
            "center": center,
            "original_quantile_bounds": bounds[quantile],
            "boundary_distances": [center - endpoints[0], endpoints[1] - center],
        }
        assert endpoints[0] <= center <= endpoints[1]
        reconstructed[name] = float(
            series.quantile(historical["params"][quantile], interpolation="linear")
        )
        errors[name] = abs(reconstructed[name] - center)
        assert errors[name] < 1e-14
    s013 = {
        "bull.range_window": [30, 360, 1],
        "bear.range_window": [30, 360, 1],
        "bull.entry": [0.05, 0.85, None],
        "bear.entry": [0.05, 0.985, None],
        "bull.exit": [0.5, 1.0, None],
        "bear.exit": [0.5, 1.0, None],
        "bull.max_hold": [1, 30, 1],
        "bear.max_hold": [1, 30, 1],
        "bear.acf_min": [-0.6, 0.5, None],
        "regime_window": [5, 60, 1],
        "regime_threshold": [-0.04, 0.04, None],
        "confirmation.threshold": [-0.3, 0.1, None],
        "confirmation.lookback": [40, 120, 1],
    }
    result = {
        "status": "PASS",
        "source_sha256": hashes,
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "s007": {
            "discovery_start": discovery["discovery_start"],
            "discovery_end": discovery["discovery_end"],
            "valid_base_count": len(base_discovery),
            "valid_gate_entry_count": len(gate_discovery),
            "seed_raw_matches_panel_exactly": all(v == 0 for v in panel_seed_difference.values()),
            "seed_raw_vs_panel_max_absolute_difference_per_feature": panel_seed_difference,
            "seed_normalized_scores_equal_original_panel_exactly": True,
            "mapped_threshold_domains": mapped,
            "reconstructed_original_center_thresholds": reconstructed,
            "absolute_center_reconstruction_errors": errors,
            "interpretation": "Frozen center-conditioned projection of original quantile domains; scales only. All center and perturbed thresholds remain fixed numerical coordinates, never recalibrated per perturbation.",
        },
        "s013_suggested_route_specific_historical_envelopes": s013,
        "s013_domain_notes": [
            "Route-specific bull.entry envelope ends at .85; bear-specific extension to .985 does not prove a bull search to .985.",
            "Other shared route bounds derive from the historical parent primitive search; not all values were independently searched for each adaptive route.",
            "Historical windows are sparse categorical choices; step1 interpolation is newly declared diagnostic design within existing typed contracts.",
            "ADJUSTED center confirmation.lookback120 is at its upper boundary; include asymmetric feasible directions and report conditioning.",
            "Integer half-even rounding must be followed by actual standardized distance reconciliation; retained integer move can already exceed requested radius.",
        ],
        "no_account_evaluation": True,
        "no_source_mutation": True,
    }
    OUT.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "thresholds": mapped,
                "center_reconstruction_errors": errors,
                "output": str(OUT),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
