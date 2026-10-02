"""Explicit researcher-owned reuse of historical accounts, without legacy API replay."""

import json
from hashlib import sha256

import numpy as np
import pandas as pd
from strategy_evaluator import (
    ReturnMatrixEvidence,
    hash_return_matrix,
    cscv_pbo,
    annualized_sharpe,
    effective_trial_count,
    calculate_dsr_bundle,
)

LEDGERS = ("decisions", "orders", "fills", "account_daily", "trades")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_records(repo):
    table = pd.read_parquet(repo / "research/S011/stage4/iteration_02/evaluations.parquet")
    records = table.loc[table.scope.eq("COMPARABLE_DEVELOPMENT")].to_dict("records")
    assert len(records) == 588
    root = repo / "experiments/S011/20260930_S011_EX28"
    extra = pd.read_csv(root / "artifacts/completed_accounts.csv", float_precision="round_trip")
    extra = extra.loc[extra.scenario.eq("standard")]
    assert len(extra) == 184
    for row in extra.to_dict("records"):
        number = int(row["design_id"])
        folder = root / f"artifacts/trials/T{number:03}"
        records.append(
            {
                **row,
                "reference": f"EX28T{number:03}",
                "source_experiment": root.name,
                "payload_path": (folder / "payload.json").relative_to(repo).as_posix(),
                "evidence": (folder / "standard").relative_to(repo).as_posix(),
            }
        )
    return records


def historical_accounts(repo, inputs):
    vectors, audit, sessions, hashes = [], [], None, {}
    manifests = {}
    snapshot = read(repo / "research/S011/stage4/iteration_02/input_snapshot.json")
    provenance = {}

    def checked(path, ex):
        root = repo / "experiments/S011" / ex
        if ex not in manifests:
            manifests[ex] = read(root / "experiment_manifest.json")["files"]
        rel = path.relative_to(root).as_posix()
        digest = sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(repo).as_posix()
        if ex == "20260930_S011_EX28" and rel.startswith("runtime/"):
            reference = repo / "experiments/S011/20260930_S011_EX24" / rel
            assert digest == sha256(reference.read_bytes()).hexdigest()
            assert digest == snapshot[reference.relative_to(repo).as_posix()]
            provenance[relative] = "EX24 source raw hash in iteration_02 input snapshot"
        elif ex == "20260930_S011_EX28":
            assert digest == manifests[ex][rel]["sha256"], str(path)
            provenance[relative] = "EX28 original manifest raw hash"
        else:
            assert digest == snapshot[relative], str(path)
            provenance[relative] = "iteration_02 original input snapshot raw hash"
        assert digest == inputs["historical_sources"][path.relative_to(repo).as_posix()]
        hashes[path.relative_to(repo).as_posix()] = digest
        return path

    for row in source_records(repo):
        ex = row["source_experiment"]
        payload_path = repo / row["payload_path"]
        payload = read(checked(payload_path, ex))
        identity = read(checked(payload_path.parent / "identity.json", ex))
        assert payload["symbol"] == "159326.SZ"
        for name in payload["runtime"]["source_files"]:
            checked(repo / "experiments/S011" / ex / "runtime/strategy_runtime" / name, ex)
        if "data_identity" in row:
            assert all(
                identity[k] == row[k] for k in ("data_identity", "request_hash", "result_hash")
            )
        folder = repo / row["evidence"]
        frames = {
            k: pd.read_csv(checked(folder / (k + ".csv.gz"), ex), float_precision="round_trip")
            for k in LEDGERS
        }
        a, fills, orders, trades = (
            frames[k] for k in ("account_daily", "fills", "orders", "trades")
        )
        dates = tuple(a.date)
        assert len(a) == 403 and len(set(dates)) == 403
        assert dates[0] == "2025-02-06" and dates[-1] == "2026-09-28"
        if sessions is None:
            sessions = dates
        assert dates == sessions
        assert a.cash.ge(-1e-8).all() and a.quantity.mod(100).eq(0).all()
        assert np.allclose(a.cash + a.quantity * a.close, a.equity, atol=1e-8, rtol=0)
        assert fills.quantity.mod(100).eq(0).all()
        assert np.allclose(
            fills.fees.to_numpy(float),
            fills.quantity.to_numpy(float) * fills.price.to_numpy(float) * 0.001,
            rtol=0,
            atol=1e-8,
        )
        assert orders.loc[orders.side.eq("BUY"), "order_type"].eq("LIMIT").all()
        assert orders.loc[orders.side.eq("SELL"), "order_type"].eq("MARKET").all()
        eq = a.equity.to_numpy(float)
        values = {
            "cagr": (eq[-1] / 1e6) ** (252 / len(eq)) - 1,
            "drawdown": np.min(eq / np.maximum.accumulate(np.r_[1e6, eq])[1:] - 1),
            "closed_trades": int(trades.status.eq("CLOSED").sum()),
            "end_equity": eq[-1],
        }
        assert all(np.isclose(v, row[k], rtol=0, atol=1e-8) for k, v in values.items())
        returns = eq / np.r_[1e6, eq[:-1]] - 1
        assert np.isfinite(returns).all() and np.all(returns > -1)
        vectors.append((row["reference"], returns))
        audit.append(
            {
                "reference": row["reference"],
                "evidence": row["evidence"],
                "payload_path": row["payload_path"],
                "runtime_source_sha256": payload["runtime"]["source_sha256"],
                "data_identity": identity["data_identity"],
                "checks": "PASS",
                "metrics": values,
            }
        )
    return {"sessions": sessions, "vectors": vectors}, {
        "status": "PASS",
        "comparable_original": 588,
        "EX28_standard": 184,
        "method": "Original input snapshot for early accounts; EX28 manifest for later accounts; pinned raw hashes, calendar, lots, cash/equity, fees, order types and reported metrics; no legacy receipt execution.",
        "hash_provenance": provenance,
        "accounts": audit,
        "verified_raw_hashes": hashes,
        "excluded_returns": "96 EX14 wrong-warmup accounts; EX18 baseline duplicate; technically failed paths",
        "limitations": [
            "Historical reuse is researcher-audited evidence, not current platform execution certification."
        ],
    }


def expanded_family_statistics(repo, historical, new_returns):
    assert len(new_returns) == 512
    # Deduplicate return paths only for statistics. Preserve all identities in the mapping.
    all_vectors = historical["vectors"] + new_returns
    ids, vectors, mapping, excluded = [], [], [], []
    for name, values in all_vectors:
        if np.std(values, ddof=1) <= 0:
            excluded.append(name)
            continue
        match = next(
            (
                i
                for i, other in enumerate(vectors)
                if np.allclose(values, other, rtol=0, atol=1e-14)
            ),
            None,
        )
        if match is None:
            match = len(ids)
            ids.append(name)
            vectors.append(values)
        mapping.append({"proposal": name, "statistical_path": ids[match]})
    matrix = np.column_stack(vectors)
    evidence = ReturnMatrixEvidence(
        historical["sessions"], tuple(ids), tuple(map(tuple, matrix)), ""
    )
    evidence = ReturnMatrixEvidence(
        evidence.dates, evidence.candidate_ids, evidence.returns, hash_return_matrix(evidence)
    )
    effective = effective_trial_count(matrix)
    sharpes = np.array([annualized_sharpe(x) for x in vectors])
    old = read(repo / "experiments/S011/20261002_S011_EX33/inputs.json")
    dsr = []
    for center in old["centers"]:
        item = read(
            repo
            / "experiments/S011/20261002_S011_EX33/artifacts/assessment"
            / (center["candidate_id"] + ".json")
        )
        standard = next(x for x in item if x["scenario_id"] == "standard")
        eq = np.array([x["equity"] for x in standard["account"]])
        returns = eq / np.r_[1e6, eq[:-1]] - 1
        for count in (1284, 1381):
            dsr.append(
                {
                    "candidate_id": "S011-" + center["candidate_id"],
                    "raw_count": count,
                    "result": calculate_dsr_bundle(
                        returns, sharpes, raw_count=count, effective_count=effective
                    ).to_dict(),
                }
            )
    return {
        "scope": "588 original comparable proposals + 184 EX28 fixed proposals + 512 EX36 fixed joint proposals",
        "raw_counts": [1284, 1381],
        "count_interpretation": "1381 additionally retains 96 wrong-warmup proposals and one repeated EX18 baseline; EX33 replay and stress scenarios do not add search proposals.",
        "sessions": len(evidence.dates),
        "nonconstant_unique_paths": len(ids),
        "return_equality_absolute_tolerance": 1e-14,
        "mapping": mapping,
        "constant_exclusions": excluded,
        "matrix_sha256": evidence.content_hash,
        "pbo": [cscv_pbo(evidence, n).to_dict() for n in (8, 10)],
        "effective_trial_count": effective,
        "dsr": dsr,
        "limitations": [
            "All observations are reused development data; no independent validation.",
            "Adaptive mechanism selection before this finite family remains outside the correction.",
            "PBO selects Sharpe winners, not the original constrained multiobjective selection.",
            "Effective trial count is a correlation-model diagnostic, not an independent sample count.",
        ],
    }
