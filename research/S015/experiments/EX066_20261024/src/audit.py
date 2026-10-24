"""Read-only authentication and independent arithmetic of the fixed EX066 accounts.

Uses the previously published EX061 arithmetic audit without altering it.  No
strategy replay, data acquisition, account publication or causal attribution.
"""

# ruff: noqa: E402
import os

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import importlib.util
import json
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd

from czsc_trader.application import RepositoryContext, diagnose_accounts
from czsc_trader.research_tools import AccountDiagnosisRequest, AccountRunRef, EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence


ROOT = Path(__file__).resolve().parents[5]
HOME = ROOT / "research/S015/experiments/EX066_20261024"
OUT = HOME / "others"
HISTORICAL = HOME.parent / "EX063_20261024/others/centers.json"
HELPER = HOME.parent / "EX061_20261024/src/account_audit.py"
_spec = importlib.util.spec_from_file_location("s015_ex061_arithmetic", HELPER)
old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def projection_summary(projection):
    """Use the authenticated SE projection as the independent ledger comparator."""
    points = projection["account"]
    assert len(points) == 434
    sessions = [x["session"] for x in points]
    assert sessions[0] == "2025-01-02" and sessions[-1] == "2026-10-21"
    equity = np.array([projection["initial_cash"], *[x["equity"] for x in points]])
    exits = pd.Series([x["exit_session"] for x in projection["closed_cycles"]], dtype="object")
    frequency = exits.value_counts().reindex(sessions, fill_value=0).rolling(60).sum().dropna()
    return {
        "net_return": float(equity[-1] / equity[0] - 1),
        "dd": float(np.max(1 - equity / np.maximum.accumulate(equity))),
        "closed": len(projection["closed_cycles"]),
        "frequency_median": float(frequency.median()),
        "frequency_good": int((frequency >= 3).sum()),
    }


def ordinal_identity(series):
    """Retain identity equality patterns when only request identifiers change."""
    codes = {}

    def encode(value):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        key = str(value)
        if key not in codes:
            codes[key] = len(codes)
        return codes[key]

    return series.map(encode)


def normalized_state(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    payload = json.loads(value) if isinstance(value, str) else dict(value)
    if payload is None:
        return None
    # These two keys identify a cycle/signal; every budget, quantity, fee and
    # state transition is still compared, without rounding or type conversion.
    return {k: v for k, v in payload.items() if k not in ("cycle_id", "opening_signal_identity")}


def compare_center_ledgers(current, historical):
    allowed_identifiers = {
        "decision_id",
        "order_id",
        "fill_id",
        "cycle_id",
        "entry_cycle_id",
        "plan_identity",
        "signal_identity",
    }
    states = {"entry_cycle", "entry_cycle_before", "entry_cycle_after"}
    changes = []
    for name in ("account_daily", "decisions", "orders", "fills", "trades"):
        left = old.frame(historical["ledgers"][name])
        right = old.frame(current["ledgers"][name])
        assert list(left.columns) == list(right.columns), (name, "column contract changed")
        assert len(left) == len(right), (name, "row count changed")
        for column in left.columns:
            try:
                pd.testing.assert_series_equal(left[column], right[column], check_exact=True)
            except AssertionError:
                if column in allowed_identifiers:
                    pd.testing.assert_series_equal(
                        ordinal_identity(left[column]),
                        ordinal_identity(right[column]),
                        check_exact=True,
                    )
                elif column in states:
                    assert list(left[column].map(normalized_state)) == list(
                        right[column].map(normalized_state)
                    ), (name, column)
                else:
                    raise
                changes.append(
                    {
                        "ledger": name,
                        "column": column,
                        "treatment": "identity-only normalization; equality pattern or all state economics retained",
                    }
                )
    return {"status": "FIVE_LEDGER_ECONOMIC_EQUIVALENCE_PASS", "identity_only_differences": changes}


def audit_one(job):
    row, historical_row = job
    ref = EvidenceRef.from_dict(row["evidence"])
    assert ref.experiment.strategy_id == "S015" and ref.experiment.experiment_id == "EX066_20261024"
    payload = read(ref.resolve(ROOT))
    validate_evaluation_evidence(payload)
    for key in ("request_hash", "result_hash"):
        assert payload[key] == row[key]
    assert payload["schema_version"] == 8
    assert len(payload["runs"]) == len(payload["assessment_evidence"]) == 1
    run, projection = payload["runs"][0], payload["assessment_evidence"][0]
    assert (run["window_id"], run["scenario_id"]) == ("full", "standard")
    assert projection["candidate"]["candidate_id"] == "S015-" + row["candidate_id"]
    assert projection["initial_cash"] == projection["opening_cash"] == 100000
    assert projection["opening_quantity"] == 0
    assert projection["scenario_context"]["one_way_cost"] == 0.001
    assert projection["scenario_context"]["measurement_tier"] == "FORMAL"
    assert payload["request_identity"]["price_basis"] == "HFQ_RESEARCH"
    assert (projection["parameter_point"] is None) == (row.get("parent_candidate_id") is None)
    summary = projection_summary(projection)
    arithmetic = old.describe(run, summary)
    # The complete calculations above include every cycle.  Keep compact audit
    # totals and distributions; the immutable source still retains each ledger.
    arithmetic.pop("cycles")
    diagnosis = diagnose_accounts(
        RepositoryContext.discover(ROOT),
        AccountDiagnosisRequest(AccountRunRef(ref, old.identity(run)), None, old.WINDOWS["full"]),
    )
    assert diagnosis.status.value not in ("INVALID_EVIDENCE", "INCOMPARABLE"), diagnosis.issues
    item = {
        "candidate_id": row["candidate_id"],
        "parent_candidate_id": row.get("parent_candidate_id"),
        "evidence": ref.to_dict(),
        "request_hash": row["request_hash"],
        "result_hash": row["result_hash"],
        "status": "ARITHMETIC_CHECKS_PASS",
        "summary": summary,
        "accounting_description": arithmetic,
        "public_diagnosis": diagnosis.to_dict(),
    }
    if historical_row is not None:
        assert historical_row["candidate_id"] == row["candidate_id"]
        oldref = EvidenceRef.from_dict(historical_row["evidence"])
        previous = read(oldref.resolve(ROOT))
        validate_evaluation_evidence(previous)
        for key in ("request_hash", "result_hash"):
            assert previous[key] == historical_row[key]
        oldrun = [
            x
            for x in previous["runs"]
            if x["window_id"] == "full" and x["scenario_id"] == "standard"
        ]
        assert len(oldrun) == 1
        assert (
            projection["candidate"]["content_sha256"]
            == historical_row["identity"]["content_sha256"]
        )
        for key, value in summary.items():
            old.close(value, historical_row["runs"]["full"][key])
        item["historical_center"] = {
            "evidence": oldref.to_dict(),
            **compare_center_ledgers(run, oldrun[0]),
        }
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    assert 1 <= args.workers <= 8
    output = OUT / "audit.json"
    assert not output.exists(), "Preserve completed audit evidence; do not overwrite audit.json"
    raw = read(OUT / "results.json")
    rows = raw["rows"] if isinstance(raw, dict) else raw
    history = {x["candidate_id"]: x for x in read(HISTORICAL)}
    assert len(rows) == len({x["candidate_id"] for x in rows}) == 40
    assert {x["candidate_id"] for x in rows if x.get("parent_candidate_id") is None} == set(history)
    assert sum(x.get("parent_candidate_id") is not None for x in rows) == 24
    assert all(
        x.get("parent_candidate_id") in history
        for x in rows
        if x.get("parent_candidate_id") is not None
    )
    result = {
        "experiment": "EX066_20261024",
        "status": "PENDING",
        "accounts": [],
        "inputs": {
            str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
            for p in (OUT / "results.json", HISTORICAL, HELPER, Path(__file__))
        },
        "limitations": [
            "Every new account is authenticated and checked independently against its retained five ledgers and SE projection.",
            "Official diagnosis statuses are preserved verbatim. UNSUPPORTED remains UNSUPPORTED; arithmetic does not supply causal attribution.",
            "Historical center equality covers all five ledgers. Any normalized identity columns are named; budget, quantity, prices, fees and decisions remain checked.",
            "No new research accounts, external data, optimization, filtering, or publication are performed by this audit.",
        ],
    }
    jobs = [
        (row, history.get(row["candidate_id"]) if row.get("parent_candidate_id") is None else None)
        for row in rows
    ]
    try:
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=get_context("spawn")) as pool:
            for item in pool.map(audit_one, jobs):
                result["accounts"].append(item)
                if len(result["accounts"]) % 16 == 0:
                    print("AUDITED", len(result["accounts"]), len(rows), flush=True)
        result["status"] = "PASS"
        result["center_equivalence_count"] = sum(
            "historical_center" in x for x in result["accounts"]
        )
        result["official_diagnosis_statuses"] = sorted(
            {x["public_diagnosis"]["status"] for x in result["accounts"]}
        )
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        save(OUT / "audit_failure.json", result)
        raise
    save(output, result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("status", "center_equivalence_count", "official_diagnosis_statuses")
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
