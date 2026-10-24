"""Read-only economic-path and allocation review of retained S015 accounts."""

import importlib.util
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
BASE = ROOT / "research/S015/experiments"
spec = importlib.util.spec_from_file_location("s015_account_audit", HERE / "src/account_audit.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def load(ex, cid):
    row = next(
        r for r in m.read(BASE / ex / "others/results.json")["rows"] if r["candidate_id"] == cid
    )
    ref = m.EvidenceRef.from_dict(row["evidence"])
    return row, ref, m.read(ref.resolve(ROOT))


def strip_identifiers(value):
    if isinstance(value, dict):
        return {
            k: strip_identifiers(v)
            for k, v in value.items()
            if not k.endswith("_id")
            and k not in ("signal_identity", "plan_identity", "opening_signal_identity")
        }
    if isinstance(value, list):
        return [strip_identifiers(v) for v in value]
    return value


def economic_table(payload):
    frame = m.frame(payload)
    frame = frame[
        [
            k
            for k in frame
            if not k.endswith("_id") and k not in ("signal_identity", "plan_identity")
        ]
    ].copy()
    for column in ("entry_cycle_before", "entry_cycle_after", "entry_cycle", "cycle_target"):
        if column in frame:
            frame[column] = frame[column].map(
                lambda s: json.dumps(strip_identifiers(json.loads(s)), sort_keys=True)
            )
    return frame


def stats(cycles):
    entry = [c["first_entry_day_net_yuan"] for c in cycles]
    recovered = [c for c in cycles if c["first_entry_day_net_yuan"] < 0 and c["net_yuan"] > 0]
    return {
        "cycle_count": len(cycles),
        "entry_loss_count": sum(v < 0 for v in entry),
        "entry_loss_yuan": -sum(v for v in entry if v < 0),
        "entry_profit_count": sum(v > 0 for v in entry),
        "entry_profit_yuan": sum(v for v in entry if v > 0),
        "entry_loss_later_profitable_count": len(recovered),
        "recovered_cycles_final_net_yuan": sum(c["net_yuan"] for c in recovered),
        "recovered_cycles_entry_net_yuan": sum(c["first_entry_day_net_yuan"] for c in recovered),
        "recovered_cycles": recovered,
    }


def main():
    out = HERE / "others/focused_review.json"
    assert not out.exists()
    audit = m.read(HERE / "others/audit.json")
    assert audit["status"] == "ARITHMETIC_CHECKS_PASS"
    result = {
        "status": "PASS",
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "new_account_simulations": 0,
        "replications": [],
        "allocation_comparisons": [],
        "limitations": [
            "IDs and nested cycle identity strings are excluded only from economic ledger equality checks; identity differences remain reported.",
            "Allocation comparison uses two complete actual account paths. No deletion of losing cycles or multiplication of a baseline return.",
            "The lower allocation does not classify entry-day losers or avoid their entry; it scales both losing and winning exposure with actual fee/lot/compounding effects.",
            "434 and 415 windows overlap and do not constitute independent validation. Stage-three center passage is not stage-four qualification.",
        ],
    }
    for newcid, oldex, oldcid in (
        ("C5807", "EX055_20261024", "C5506"),
        ("C5818", "EX053_20261024", "C5303"),
    ):
        newrow, newref, new = load(HERE.name, newcid)
        oldrow, oldref, old = load(oldex, oldcid)
        item = {
            "candidate": newcid,
            "old_candidate": oldcid,
            "new_evidence": newref.to_dict(),
            "old_evidence": oldref.to_dict(),
            "new_identity": newrow["identity"],
            "old_identity": oldrow["identity"],
            "new_parameters": newrow["parameters"],
            "old_parameters": oldrow["parameters"],
            "windows": [],
        }
        for run in new["runs"]:
            before = next(r for r in old["runs"] if r["window_id"] == run["window_id"])
            counts = {}
            for name in ("account_daily", "decisions", "fills", "orders", "trades"):
                a, b = [economic_table(r["ledgers"][name]) for r in (run, before)]
                assert set(a) == set(b), (newcid, name, "columns differ")
                pd.testing.assert_frame_equal(a, b[a.columns], check_exact=True, check_dtype=False)
                counts[name] = len(a)
            pd.testing.assert_frame_equal(
                economic_table(run["signals"]),
                economic_table(before["signals"]),
                check_exact=True,
                check_dtype=False,
            )
            item["windows"].append(
                {
                    "window": run["window_id"],
                    "economic_ledgers_equal_exactly": True,
                    "counts": counts,
                    "new_runtime_sha256": run["signal_support"]["runtime_sha256"],
                    "old_runtime_sha256": before["signal_support"]["runtime_sha256"],
                }
            )
        result["replications"].append(item)
    _, _, full = load(HERE.name, "C5807")
    _, _, reduced = load(HERE.name, "C5806")
    for left in full["runs"]:
        window = left["window_id"]
        right = next(r for r in reduced["runs"] if r["window_id"] == window)
        a, b = [m.frame(r["signals"]).drop(columns="decision_id") for r in (left, right)]
        pd.testing.assert_frame_equal(a, b, check_exact=True, check_dtype=False)
        a, b = [
            m.frame(r["ledgers"]["fills"])[
                ["signal_date", "fill_time", "side", "price", "trigger", "time_precision"]
            ]
            for r in (left, right)
        ]
        pd.testing.assert_frame_equal(a, b, check_exact=True, check_dtype=False)
        descriptions = [
            next(
                x["accounting_description"]
                for x in audit["accounts"]
                if x["candidate"] == cid and x["window"] == window
            )
            for cid in ("C5807", "C5806")
        ]
        aa, bb = [{c["entry_day"]: c for c in d["cycles"]} for d in descriptions]
        assert set(aa) == set(bb)
        pairs = [
            {
                "entry_day": k,
                "full_net_yuan": aa[k]["net_yuan"],
                "reduced_net_yuan": bb[k]["net_yuan"],
                "actual_delta_yuan": bb[k]["net_yuan"] - aa[k]["net_yuan"],
            }
            for k in sorted(aa)
        ]
        result["allocation_comparisons"].append(
            {
                "window": window,
                "full_candidate": "C5807",
                "reduced_candidate": "C5806",
                "identical_target_sequence_and_fill_dates_sides_prices": True,
                "full_metrics": {
                    k: descriptions[0][k]
                    for k in (
                        "net_return",
                        "drawdown",
                        "fees_yuan",
                        "exposure",
                        "frequency",
                        "cycle_sums",
                    )
                },
                "reduced_metrics": {
                    k: descriptions[1][k]
                    for k in (
                        "net_return",
                        "drawdown",
                        "fees_yuan",
                        "exposure",
                        "frequency",
                        "cycle_sums",
                    )
                },
                "full_entry_losses": stats(descriptions[0]["cycles"]),
                "reduced_entry_losses": stats(descriptions[1]["cycles"]),
                "sum_actual_delta_on_baseline_profitable_cycles": sum(
                    p["actual_delta_yuan"] for p in pairs if p["full_net_yuan"] > 0
                ),
                "sum_actual_delta_on_baseline_losing_cycles": sum(
                    p["actual_delta_yuan"] for p in pairs if p["full_net_yuan"] < 0
                ),
                "cycle_pairs": pairs,
            }
        )
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "replications": len(result["replications"]),
                "allocation_windows": len(result["allocation_comparisons"]),
            }
        )
    )


if __name__ == "__main__":
    main()
