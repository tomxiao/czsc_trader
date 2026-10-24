"""Diagnose exit/re-entry confounding using retained signals and ledger facts.

Synthetic intentions below are deterministic signal checks, not new accounts.
"""

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
spec = importlib.util.spec_from_file_location("audit", HERE / "src/account_audit.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def load(cid):
    row = next(x for x in m.read(HERE / "others/results.json")["rows"] if x["candidate_id"] == cid)
    ref = m.EvidenceRef.from_dict(row["evidence"])
    return row, ref, m.read(ref.resolve(ROOT))


def independent_intentions(features, hold, confirmation, rearm):
    age, armed, bad = 0, True, 0
    records = []
    for day, row in features.iterrows():
        permit = (
            bool(row.feature_ready)
            and day.date().isoformat() >= "2025-01-02"
            and row.center_gain > 0
            and row.p < row.m
        )
        before_age = age
        failed = row.dcenter < 0 and row.p < row.m
        exited = entered = blocked = False
        if age:
            bad = bad + 1 if failed else 0
            exited = age >= hold or (confirmation is not None and bad >= confirmation)
            if exited:
                age, armed = 0, False
            else:
                age += 1
        else:
            if row.dcenter > 0:
                armed = True
            blocked = permit and rearm and not armed
            if permit and (armed or not rearm):
                age, bad, entered = 1, 0, True
        records.append(
            {
                "signal_date": day.strftime("%Y-%m-%d"),
                "target_position": float(age > 0),
                "intent_age": age,
                "permission": float(permit),
                "entry_signal": float(entered),
                "exit_signal": float(exited),
                "age_before": before_age,
                "failed_streak": bad,
                "blocked_by_rearm": bool(blocked),
                "early_exit": bool(exited and before_age < hold),
            }
        )
    return pd.DataFrame(records).set_index("signal_date")


def main():
    output = HERE / "others/mechanism_review.json"
    assert not output.exists()
    source = HERE / "src/strategy_runtime/strategies/price_process.py"
    refs = m.read(HERE / "others/protocol_refs.json")
    source_ref = m.EvidenceRef.from_dict(refs[str(source.relative_to(ROOT))])
    assert source_ref.resolve(ROOT).read_bytes() == source.read_bytes()
    audit = m.read(HERE / "others/audit.json")
    assert audit["status"] == "ARITHMETIC_CHECKS_PASS"
    loaded = {cid: load(cid) for cid in ("C5918", "C5901", "C5902")}
    full_fixed = next(r for r in loaded["C5918"][2]["runs"] if r["window_id"] == "full")
    features = m.frame(full_fixed["ledgers"]["decisions"])
    features.index = pd.DatetimeIndex(pd.to_datetime(features.signal_date))
    specs = {"C5918": (None, False), "C5901": (2, True), "C5902": (3, True)}
    checks = []
    synthesized = {}
    for cid, (confirmation, rearm) in specs.items():
        signal = independent_intentions(features, 3, confirmation, rearm)
        synthesized[cid] = signal
        row, ref, evidence = loaded[cid]
        for run in evidence["runs"]:
            actual = m.frame(run["ledgers"]["decisions"])
            dates = actual.signal_date.str[:10]
            for column in (
                "target_position",
                "intent_age",
                "permission",
                "entry_signal",
                "exit_signal",
            ):
                m.close(actual[column], signal.loc[dates, column])
        early = signal[signal.early_exit]
        blocked = signal[signal.blocked_by_rearm]
        checks.append(
            {
                "candidate": cid,
                "evidence": ref.to_dict(),
                "parameters": row["parameters"],
                "independent_signal_reconstruction_matches_both_windows": True,
                "full_intended_entries": int(signal.entry_signal.sum()),
                "full_intended_exits": int(signal.exit_signal.sum()),
                "early_exit_signal_dates": early.reset_index().to_dict("records"),
                "blocked_reentry_signal_dates": blocked.reset_index().to_dict("records"),
            }
        )
    fixed_positive_rearm = independent_intentions(features, 3, None, True)
    columns = ["target_position", "intent_age", "permission", "entry_signal", "exit_signal"]
    pd.testing.assert_frame_equal(
        fixed_positive_rearm[columns], synthesized["C5902"][columns], check_exact=True
    )
    for confirmation in (3, 4, 5, 10):
        check = independent_intentions(features, 3, confirmation, True)
        pd.testing.assert_frame_equal(
            check[columns], fixed_positive_rearm[columns], check_exact=True
        )
    comparisons = []
    for cid in ("C5901", "C5902"):
        for window in m.WINDOWS:
            a, b = [
                next(
                    x["accounting_description"]
                    for x in audit["accounts"]
                    if x["candidate"] == candidate and x["window"] == window
                )
                for candidate in ("C5918", cid)
            ]
            left, right = [{c["entry_day"]: c for c in d["cycles"]} for d in (a, b)]
            common = sorted(set(left) & set(right))
            comparisons.append(
                {
                    "candidate": cid,
                    "control": "C5918",
                    "window": window,
                    "control_metrics": {
                        k: a[k]
                        for k in (
                            "net_return",
                            "drawdown",
                            "fees_yuan",
                            "frequency",
                            "exposure",
                            "cycle_sums",
                        )
                    },
                    "candidate_metrics": {
                        k: b[k]
                        for k in (
                            "net_return",
                            "drawdown",
                            "fees_yuan",
                            "frequency",
                            "exposure",
                            "cycle_sums",
                        )
                    },
                    "common_actual_entry_dates": len(common),
                    "common_entry_equal_exit_dates": sum(
                        left[k]["exit_day"] == right[k]["exit_day"] for k in common
                    ),
                    "common_actual_paths": [
                        {"entry_day": k, "control": left[k], "candidate": right[k]} for k in common
                    ],
                    "control_only_actual_cycles": [left[k] for k in sorted(set(left) - set(right))],
                    "candidate_only_actual_cycles": [
                        right[k] for k in sorted(set(right) - set(left))
                    ],
                }
            )
    result = {
        "status": "PASS",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime_source": source_ref.to_dict(),
        "new_account_simulations": 0,
        "checks": checks,
        "comparisons": comparisons,
        "fixed_hold3_positive_step_rearm_equals_confirmation3": True,
        "additional_signal_only_confirmation_values_checked": [3, 4, 5, 10],
        "proof": "On entry age=1 and failed_streak=0. At each following holding decision failed_streak<=age; if confirmation>=hold, the failed-streak condition cannot exit earlier than age>=hold. The only difference from legacy fixed mode is its bypass of the armed/rearm requirement after exiting.",
        "rearm_semantics": "Exit resets armed=False. Only a subsequent flat-state day with dcenter>0 re-arms. Once re-armed it stays latched until the next exit; entry does not require dcenter>0 on the entry day. A positive step on the exit day itself does not re-arm.",
        "limitations": [
            "C5902 must not be attributed to earlier detection of holding-value failure; its guard cannot trigger earlier than the fixed cap.",
            "C5901 includes both possible early exits and the inherited rearm change, so its total-account difference is confounded.",
            "Matched entry-date cycle differences describe actual separate accounts and quantities, not same-capital causal attribution.",
            "Synthetic signal checks add no account simulation and do not establish an economic counterfactual for other values.",
            "An explicit rearm-by-exit factorial is needed to isolate the economic effects; no new strategy account was created here.",
        ],
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "checks": [
                    {
                        "candidate": c["candidate"],
                        "early": len(c["early_exit_signal_dates"]),
                        "blocked": len(c["blocked_reentry_signal_dates"]),
                    }
                    for c in checks
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
