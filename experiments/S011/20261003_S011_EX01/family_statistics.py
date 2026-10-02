"""Research-owned numerical reuse of pinned historical ledgers; no legacy runtime replay."""

from hashlib import sha256
import json
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


def expanded_statistics(repo, audit_path, current, extensions):
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    for relative, digest in audit["verified_raw_hashes"].items():
        assert sha256((repo / relative).read_bytes()).hexdigest() == digest, relative
    vectors = []
    sessions = None
    for row in audit["accounts"]:
        folder = repo / row["evidence"]
        frames = {
            name: pd.read_csv(folder / (name + ".csv.gz"), float_precision="round_trip")
            for name in ("account_daily", "fills", "orders", "trades")
        }
        a, f, o, t = (frames[k] for k in ("account_daily", "fills", "orders", "trades"))
        dates = tuple(a.date)
        if sessions is None:
            sessions = dates
        assert dates == sessions and len(dates) == 403
        assert dates[0] == "2025-02-06" and dates[-1] == "2026-09-28"
        assert a.cash.ge(-1e-8).all() and a.quantity.mod(100).eq(0).all()
        assert np.allclose(a.cash + a.quantity * a.close, a.equity, rtol=0, atol=1e-8)
        assert f.quantity.mod(100).eq(0).all()
        assert np.allclose(
            f.fees.to_numpy(float),
            f.quantity.to_numpy(float) * f.price.to_numpy(float) * 0.001,
            rtol=0,
            atol=1e-8,
        )
        assert o.loc[o.side.eq("BUY"), "order_type"].eq("LIMIT").all()
        assert o.loc[o.side.eq("SELL"), "order_type"].eq("MARKET").all()
        equity = a.equity.to_numpy(float)
        assert abs(float(equity[-1]) - row["metrics"]["end_equity"]) <= 1e-6
        assert int(t.status.eq("CLOSED").sum()) == row["metrics"]["closed_trades"]
        vectors.append((row["reference"], equity / np.r_[1e6, equity[:-1]] - 1))
    assert len(vectors) == 772
    by_candidate = {x.candidate.candidate_id: x for x in current}
    for name in extensions:
        x = by_candidate[name]
        assert tuple(a.session for a in x.account) == sessions
        equity = np.array([a.equity for a in x.account])
        vectors.append((name, equity / np.r_[x.initial_cash, equity[:-1]] - 1))
    assert len(extensions) == 512 and len(vectors) == 1284
    ids = []
    unique = []
    mapping = []
    excluded = []
    for name, values in vectors:
        if np.std(values, ddof=1) <= 0:
            excluded.append(name)
            continue
        match = next(
            (i for i, other in enumerate(unique) if np.allclose(values, other, rtol=0, atol=1e-14)),
            None,
        )
        if match is None:
            match = len(ids)
            ids.append(name)
            unique.append(values)
        mapping.append(dict(proposal=name, statistical_path=ids[match]))
    matrix = np.column_stack(unique)
    evidence = ReturnMatrixEvidence(
        sessions, tuple(ids), tuple(tuple(float(v) for v in row) for row in matrix), ""
    )
    evidence = ReturnMatrixEvidence(
        evidence.dates, evidence.candidate_ids, evidence.returns, hash_return_matrix(evidence)
    )
    effective = effective_trial_count(matrix)
    sharpes = np.array([annualized_sharpe(x) for x in unique])
    dsr = []
    for item in current:
        if item.parent is not None:
            continue
        equity = np.array([a.equity for a in item.account])
        returns = equity / np.r_[item.initial_cash, equity[:-1]] - 1
        for count in (1284, 1381):
            dsr.append(
                dict(
                    candidate_id=item.candidate.candidate_id,
                    raw_count=count,
                    result=calculate_dsr_bundle(
                        returns, sharpes, raw_count=count, effective_count=effective
                    ).to_dict(),
                )
            )
    return dict(
        scope="772 pinned historical standard accounts plus 512 current replays of the historical extension",
        historical_hash_count=len(audit["verified_raw_hashes"]),
        historical_accounts=772,
        current_extension_accounts=512,
        raw_counts=[1284, 1381],
        new_search_trials=0,
        nonconstant_unique_paths=len(ids),
        constant_exclusions=excluded,
        matrix_sha256=evidence.content_hash,
        mapping=mapping,
        effective_trial_count=effective,
        pbo=[cscv_pbo(evidence, n).to_dict() for n in (8, 10)],
        dsr=dsr,
        limitations=[
            "Historical numeric ledgers are source evidence, not current runtime certifications.",
            "1381 counts retain 96 wrong-warmup proposals and one repeated EX18 baseline; those returns remain excluded.",
            "Repeated evaluation does not increase proposal counts or independent samples.",
            "Prior mechanism selection and repeated development-sample observation remain outside the correction.",
            "PBO uses Sharpe winners; effective counts are model diagnostics, not independent sample counts.",
            "Neither PBO nor DSR is a future profit probability.",
        ],
    )
