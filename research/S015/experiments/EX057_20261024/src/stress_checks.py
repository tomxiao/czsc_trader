"""Verify doubled costs, unchanged signal sequences and the declared stress gate."""

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
spec = importlib.util.spec_from_file_location("pressure_audit", HERE / "src/account_audit.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PAIRS = (
    ("C5700", "EX053_20261024", "C5303"),
    ("C5701", "EX054_20261024", "C5404"),
    ("C5702", "EX055_20261024", "C5506"),
)


def load(experiment, candidate):
    rows = m.read(m.experiment_path(experiment) / "others/results.json")["rows"]
    row = next(r for r in rows if r["candidate_id"] == candidate)
    ref = m.EvidenceRef.from_dict(row["evidence"])
    return row, ref, m.read(ref.resolve(ROOT))


def metrics(daily):
    values = np.r_[100000.0, daily.equity.to_numpy(float)]
    return {
        "net_return": float(values[-1] / values[0] - 1),
        "cagr": float((values[-1] / values[0]) ** (252 / len(daily)) - 1),
        "drawdown": float(np.max(1 - values / np.maximum.accumulate(values))),
    }


def main():
    output = HERE / "others/stress_checks.json"
    assert not output.exists()
    results = m.read(HERE / "others/results.json")
    assert (
        results["serial_equal"]
        and results["formal_accounts"] == 6
        and results["technical_accounts"] == 2
    )
    records = []
    for candidate, experiment, control in PAIRS:
        row, ref, evidence = load(HERE.name, candidate)
        oldrow, oldref, old = load(experiment, control)
        assert evidence["request_identity"]["costs"] == [
            {"measurement_tier": "FORMAL", "one_way_cost": 0.002, "scenario_id": "double"}
        ]
        assert old["request_identity"]["costs"] == [
            {"measurement_tier": "FORMAL", "one_way_cost": 0.001, "scenario_id": "standard"}
        ]
        for run in evidence["runs"]:
            window = run["window_id"]
            before = next(x for x in old["runs"] if x["window_id"] == window)
            assert run["scenario_id"] == "double"
            assert run["signal_support"]["evaluation_fee_rate"] == 0.002
            assert (
                run["signal_support"]["execution_policy"]["settings"]["capital"]["fee_rate"]
                == 0.002
            )
            assert (
                run["signal_support"]["execution_input_identities"]
                == before["signal_support"]["execution_input_identities"]
            )
            signals = m.frame(run["signals"]).drop(columns="decision_id")
            prior_signals = m.frame(before["signals"]).drop(columns="decision_id")
            pd.testing.assert_frame_equal(
                signals, prior_signals, check_exact=True, check_dtype=False
            )
            decisions, prior_decisions = [m.frame(x["ledgers"]["decisions"]) for x in (run, before)]
            columns = [
                "signal_date",
                "valid_session",
                "target_position",
                "entry_allocation_fraction",
                "atr",
                "center_gain",
                "concentration",
                "dcenter",
                "entry_signal",
                "exit_signal",
                "feature_ready",
                "intent_age",
                "m",
                "p",
                "permission",
                "prior_positive",
                "r1",
                "r3",
                "r5",
                "up_count",
                "vol20",
            ]
            pd.testing.assert_frame_equal(
                decisions[columns], prior_decisions[columns], check_exact=True, check_dtype=False
            )
            account = metrics(m.frame(run["ledgers"]["account_daily"]))
            benchmark = metrics(m.frame(run["buyhold"]["account_daily"]))
            for value, expected in (
                (account["cagr"], row["runs"][window]["cagr"]),
                (account["drawdown"], row["runs"][window]["dd"]),
                (benchmark["cagr"], row["runs"][window]["benchmark_cagr"]),
                (benchmark["drawdown"], row["runs"][window]["benchmark_dd"]),
            ):
                m.close(value, expected)
            fills = m.frame(run["buyhold"]["fills"])
            m.close(fills.fees, fills.quantity * fills.price * 0.002)
            checks = {
                "cagr_positive": account["cagr"] > 0,
                "cagr_above_pressure_buyhold": account["cagr"] > benchmark["cagr"],
                "drawdown_below_pressure_buyhold": account["drawdown"] < benchmark["drawdown"],
                "drawdown_at_most_25pct": account["drawdown"] <= 0.25,
            }
            records.append(
                {
                    "candidate": candidate,
                    "control_candidate": control,
                    "control_experiment": experiment,
                    "window": window,
                    "evidence": ref.to_dict(),
                    "control_evidence": oldref.to_dict(),
                    "exact_signal_rows": len(signals),
                    "exact_decision_columns": columns,
                    "request_runtime_and_benchmark_fee_consistent": True,
                    "fees": row["runs"][window]["fees"],
                    "account": account,
                    "pressure_buyhold": benchmark,
                    "standard_account": oldrow["runs"][window],
                    "checks": checks,
                    "is_declared_stress_gate_window": window == "full",
                    "declared_stress_gate_pass": all(checks.values()) if window == "full" else None,
                }
            )
    value = {
        "status": "PASS",
        "formal_accounts": 6,
        "technical_accounts": 2,
        "serial_equal": True,
        "full_stress_gate_passes": sum(r["declared_stress_gate_pass"] is True for r in records),
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "accounts": records,
        "limitations": [
            "Stress gates apply to full434 only; 415-day figures are descriptive.",
            "Standard-cost S011 comparison is not a doubled-cost hard gate.",
            "Unchanged signals do not imply unchanged quantity; capital sizing recomputes fees and budgets.",
            "This focused stress check is not completed strategy qualification or a 32-point joint perturbation.",
        ],
    }
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": value["status"],
                "full_stress_gate_passes": value["full_stress_gate_passes"],
                "exact_signal_rows": sum(r["exact_signal_rows"] for r in records),
            }
        )
    )


if __name__ == "__main__":
    main()
