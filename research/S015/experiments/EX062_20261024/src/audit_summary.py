"""Summarize authenticated stage-three account audits and serial equivalence."""

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
BASE = HERE.parent


def read(path):
    return json.loads(path.read_bytes())


def reference_fields(value):
    # Diagnosis dataclass serialization omits the reference transport type tags.
    if isinstance(value, dict):
        return {k: reference_fields(v) for k, v in value.items() if k != "type"}
    return value


def main():
    destination = HERE / "others/stage3_audit_summary.json"
    assert not destination.exists()
    rows, technical, identities, statuses = [], [], set(), Counter()
    for number in range(58, 63):
        ex = f"EX{number:03d}_20261024"
        home = BASE / ex
        result = read(home / "others/results.json")
        audit = read(home / "others/audit.json")
        assert audit["status"] == "ARITHMETIC_CHECKS_PASS"
        assert len(audit["accounts"]) == result["formal_accounts"] == 2 * len(result["rows"])
        assert all(
            a["accounting_description"]["status"] == "ARITHMETIC_CHECKS_PASS"
            for a in audit["accounts"]
        )
        statuses.update(a["public_diagnosis"]["status"] for a in audit["accounts"])
        identities.update(r["identity"]["content_sha256"] for r in result["rows"])
        for a in audit["accounts"]:
            row = next(r for r in result["rows"] if r["candidate_id"] == a["candidate"])
            assert a["public_diagnosis"]["sources"][0] == reference_fields(row["evidence"])
        count = result["technical_accounts"]
        if count:
            assert count == 2 and result["serial_equal"]
            serial = EvidenceRef.from_dict(result["serial_ref"])
            formal = EvidenceRef.from_dict(result["rows"][0]["evidence"])
            s, f = [read(ref.resolve(ROOT)) for ref in (serial, formal)]
            assert s["result_hash"] == f["result_hash"]
            assert len(s["runs"]) == len(f["runs"]) == 2
            for sr, fr in zip(s["runs"], f["runs"], strict=True):
                assert sr["window_id"] == fr["window_id"]
                assert sr["ledgers"] == fr["ledgers"]
                assert sr["identity"] == fr["identity"]
            technical.append(
                {
                    "experiment": ex,
                    "technical_accounts": 2,
                    "all_five_ledgers_exactly_equal_formal": True,
                    "serial_evidence": serial.to_dict(),
                    "formal_evidence": formal.to_dict(),
                }
            )
        rows.append(
            {
                "experiment": ex,
                "configurations": len(result["rows"]),
                "formal_accounts": len(audit["accounts"]),
                "technical_accounts": count,
                "joint_center_passes": result["center_pass_count"],
                "audit_sha256": sha256((home / "others/audit.json").read_bytes()).hexdigest(),
                "results_sha256": sha256((home / "others/results.json").read_bytes()).hexdigest(),
            }
        )
    clock = read(BASE / "EX061_20261024/others/clock_checks.json")
    rearm = read(BASE / "EX061_20261024/others/rearm_checks.json")
    assert clock["status"] == rearm["status"] == "PASS"
    assert clock["new_account_simulations"] == rearm["new_account_simulations"] == 0
    ending_windows = []
    representatives = read(BASE / "EX061_20261024/others/results.json")["rows"]
    for cid in ("C6101", "C6102", "C6104", "C6105", "C6117"):
        row = next(r for r in representatives if r["candidate_id"] == cid)
        ref = EvidenceRef.from_dict(row["evidence"])
        ev = read(ref.resolve(ROOT))
        for run in ev["runs"]:
            daily = run["ledgers"]["account_daily"]["data"]
            start = len(daily) - 252
            opening = 100000.0 if start == 0 else daily[start - 1]["equity"]
            ending_windows.append(
                {
                    "candidate": cid,
                    "window": run["window_id"],
                    "start": str(daily[start]["date"])[:10],
                    "end": str(daily[-1]["date"])[:10],
                    "net_return": daily[-1]["equity"] / opening - 1,
                    "opening_equity": opening,
                    "ending_equity": daily[-1]["equity"],
                    "evidence": ref.to_dict(),
                }
            )
    value = {
        "status": "PASS",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "experiments": rows,
        "configurations": sum(x["configurations"] for x in rows),
        "unique_declared_candidate_content_hashes": len(identities),
        "formal_accounts_independently_audited": sum(x["formal_accounts"] for x in rows),
        "technical_accounts_verified_equivalent": sum(x["technical_accounts"] for x in rows),
        "physical_accounts_in_experiments": sum(
            x["formal_accounts"] + x["technical_accounts"] for x in rows
        ),
        "joint_center_pass_configurations": sum(x["joint_center_passes"] for x in rows),
        "public_diagnosis_status_counts": dict(statuses),
        "technical_equivalence": technical,
        "representative_clock_plan_pairs": sum(c["sessions"] for c in clock["checks"]),
        "separate_period_end252_inherited_windows": ending_windows,
        "new_accounts_created_by_audit_signal_or_clock_checks": 0,
        "limitations": [
            "Candidate/configuration counts are not counts of independent strategies, mechanisms, or independent validation samples.",
            "ARITHMETIC_CHECKS_PASS is independent retained-ledger verification; public dynamic-capital diagnosis remains UNSUPPORTED.",
            "Joint center passage is not stage-four qualification: no full joint perturbation or completed qualification claim.",
            "Technical copies are included in physical account counts and verified byte-semantic five-ledger equality against audited formal controls.",
            "Clock checks compare plans on authenticated retained inputs and actual pre-states; no new fills, no independent historical availability proof.",
            "Period-end252 windows are separately labelled off-grid descriptions; they do not change the previously reported strict step21 rolling sequence.",
        ],
    }
    assert value["configurations"] == 126 and value["formal_accounts_independently_audited"] == 252
    assert value["technical_accounts_verified_equivalent"] == 6
    destination.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: value[k]
                for k in (
                    "status",
                    "configurations",
                    "formal_accounts_independently_audited",
                    "technical_accounts_verified_equivalent",
                    "joint_center_pass_configurations",
                    "public_diagnosis_status_counts",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
