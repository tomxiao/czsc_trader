"""Reuse public TDR/SE tools for stage-four uncertainty and selection diagnostics."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s019-stage4/statistics"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(SCRATCH), TMP=str(SCRATCH), PYTHONDONTWRITEBYTECODE="1",
                  OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
sys.dont_write_bytecode = True

from collections import defaultdict  # noqa: E402
from dataclasses import asdict  # noqa: E402
from hashlib import sha256  # noqa: E402
import json  # noqa: E402
from time import perf_counter  # noqa: E402
import numpy as np  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import RepositoryContext, project_selection_window_facts  # noqa: E402
from czsc_trader.research_tools.equity_replay import build_equity_assessment  # noqa: E402
import strategy_evaluator as se  # noqa: E402
from strategy_evaluator.audit_models import ReturnMatrixEvidence  # noqa: E402
from strategy_runtime import canonical_sha256  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def source(ref):
    typed = d.EvidenceRef.from_dict(ref)
    path = typed.resolve(ROOT)
    content = path.read_bytes()
    assert sha256(content).hexdigest() == typed.sha256
    return path, content, json.loads(content)


def inventory():
    """Use the independently collected immutable-publication inventory, no account replay."""
    existing = ROOT / ".tmp/s019-stage4/statistics_inventory.json"
    inv = read(existing)
    assert inv["count"] == 238
    # Dates, costs and source definitions are checked again as each account is extracted.
    groups = defaultdict(list)
    for row in inv["rows"]:
        groups[row["implementation_sha256"]].append(row)
    representatives = []
    for implementation, rows in groups.items():
        primary = next((row for row in rows if row["candidate_id"] in ("C0135", "C0224")), rows[0])
        representatives.append({**primary, "aliases": [r for r in rows if r is not primary]})
    centers = read(WORK / "protocols/centers.json")
    for center in centers:
        member = next(r for r in representatives if r["candidate_id"] == center["id"])
        assert member["reference"] == center["account_ref"] and member["content_sha256"] == center["content_hash"]
    result = {"scope": "All published S019 EX005..EX038 formal standard accounts; stage-four perturbations excluded",
        "published_account_count": len(inv["rows"]), "unique_implementations": len(representatives),
        "exact_definition_repeats": len(inv["rows"])-len(representatives),
        "header_context_groups": inv["contexts"], "candidate_source_bytes": inv["candidate_bytes"],
        "rows": representatives, "inventory_source_sha256": sha256(existing.read_bytes()).hexdigest(),
        "context_note": "Header data identity includes auxiliary observations. Formal selection compatibility uses TDR primary-input/economic context; actual TDR groups are preserved."}
    save(WORK / "others/statistics_inventory.json", result)
    protocol = {"version": "S019-stage-four-statistics-v1", "centers": [c["id"] for c in centers],
        "inventory_sha256": sha256((WORK / "others/statistics_inventory.json").read_bytes()).hexdigest(),
        "sample": {"start": "2022-01-03", "end": "2026-10-30", "sessions": 1212,
                   "status": "SEEN_DEVELOPMENT_HISTORY"},
        "bootstrap": {"method": "SE paired_stationary_bootstrap", "repetitions": 10000,
            "mean_block_length": 21, "seed": 20261110, "interval": "percentile_95",
            "comparisons": ["C0135-minus-MU_BUY_HOLD", "C0224-minus-MU_BUY_HOLD", "C0135-minus-C0224"],
            "metrics": ["NAR", "MDD", "Calmar"], "mdd_sign": "SE returns negative maximum drawdown; positive difference means smaller drawdown magnitude"},
        "selection": {"method": "TDR project_selection_window_facts then SE assess_selection_stability",
            "windows": ["2022->2023", "2023->2024", "2024->2025", "2025->2026_through_10_30"],
            "rule": "All six original center gates in selection year, then unrounded NAR descending; ties all retained",
            "observation": "Lock the selection-period eligible set; evaluate following-year target status without reselecting",
            "source_grouping": "Separate by exact TDR context/scenario when needed; no fabricated common identity",
            "max_window_facts": 10000, "max_source_bytes": 25000000000, "max_shared_bytes": 5000000000},
        "search_bias_proxy": {"method": "SE cscv_pbo and deflated_sharpe_ratio", "objective": "SHARPE_PROXY",
            "blocks": 10, "split_count": 252, "raw_trial_count": "actual published standard account evaluations in compatible group, repeats included",
            "effective_trials": "SE return-correlation eigenvalue participation ratio",
            "target_selection_bias_status": "NOT_ESTIMATED_FOR_NAR_WITH_HARD_GATES_AND_ADAPTIVE_HUMAN_SELECTION"},
        "resources": {"processes": 1, "native_threads": 1, "new_strategy_accounts": 0},
        "limitations": ["Protocols fixed after center results were known, before these statistical diagnostics.",
            "Fixed researched candidates and previously seen history; no independent or prospective validation.",
            "Four following-year observations are few; 2026 is incomplete.",
            "Full-window center eligibility remains empty; user-authorized frontier comparison preserves that fact.",
            "Sharpe PBO and DSR are auxiliary diagnostics, not NAR/Calmar selection-error or future failure probabilities.",
            "Search controls and exact reruns are counted explicitly; no count is asserted to be independent trials.",
            "Calendar block resampling changes chronology; results are conditional diagnostic intervals, not guarantees."]}
    save(WORK / "protocols/statistics_protocol.json", protocol)
    print("STATISTICS_DESIGN", len(inv["rows"]), len(representatives), flush=True)
    return result, protocol


def center_targets():
    m = se.ResearchMetric
    return se.ResearchTargets((
        se.ResearchTarget("center-nar", m.NET_ANNUAL_RETURN, lower=se.ConstantBound(.55, True)),
        se.ResearchTarget("center-calmar", m.NET_CALMAR, lower=se.ConstantBound(5., True)),
        se.ResearchTarget("center-risk", m.DRAWDOWN_MAGNITUDE, upper=se.ConstantBound(.25, True)),
        se.ResearchTarget("center-relative-risk", m.DRAWDOWN_MAGNITUDE, upper=se.BenchmarkBound(.8, True)),
        se.ResearchTarget("center-frequency", m.FREQUENCY_MEDIAN, lower=se.ConstantBound(6., True)),
        se.FrequencyCoverageTarget("center-coverage", 60, 3, 9, 10)), 60)


def calendar_and_plan(protocol):
    sys.path.insert(0, str(WORK.parent / "EX003_20261110/src"))
    from data_window import load
    from dataflows import BarFrequency, EquityProduct
    from dataflows.equity_data import sessions_from_metadata
    _, metadata = load()
    key = next(key for key in metadata if key[0].symbol == "MU" and
               key[1] is BarFrequency.DAILY and key[2] is EquityProduct.SESSIONS)
    sessions = sessions_from_metadata(metadata[key])
    days = tuple(s.session_date.isoformat() for s in sessions
                 if protocol["sample"]["start"] <= s.session_date.isoformat() <= protocol["sample"]["end"])
    assert len(days) == 1212
    windows = {str(y): se.SelectionWindow(str(y), next(d for d in days if d.startswith(str(y))),
                next(d for d in reversed(days) if d.startswith(str(y)))) for y in range(2022, 2027)}
    pairs = tuple(se.SelectionWindowPair(f"{y}-to-{y+1}", windows[str(y)], windows[str(y+1)]) for y in range(2022, 2026))
    return se.SelectionWindowPlan(days, canonical_sha256(days), pairs, tuple(protocol["limitations"]))


def selection(inv, protocol):
    path = WORK / "others/statistics_selection_projection.json"
    if path.exists():
        projection = d.SelectionWindowFactsResult.from_dict(read(path))
    else:
        plan = calendar_and_plan(protocol)
        request = d.SelectionWindowFactsRequest(tuple(d.SelectionWindowSource(
            se.AssessmentCandidate("S019-" + r["candidate_id"], r["content_sha256"]),
            d.EvidenceRef.from_dict(r["reference"])) for r in inv["rows"]),
            plan, 60, 3, d.SelectionProjectionBudget(10000, 25000000000, 5000000000))
        save(WORK / "protocols/statistics_selection_request.json", request.to_dict())
        projection = project_selection_window_facts(RepositoryContext.discover(ROOT), request)
        save(path, projection.to_dict())
    assert not projection.failures, "Repair explicit source failures; do not shrink declared universe"
    groups = defaultdict(list)
    for binding in projection.sources:
        groups[(binding.context_sha256, canonical_sha256(binding.scenario_context.to_dict()))].append(binding)
    rule = se.SelectionRule("S019-original-center-gates-NAR-v1",
        sha256((ROOT / "research/S019/materials/stage1_agreement.md").read_bytes()).hexdigest(),
        center_targets(), (se.SelectionMetricOrder(se.ResearchMetric.NET_ANNUAL_RETURN, se.SelectionDirection.MAXIMIZE),))
    results = []
    for group, bindings in groups.items():
        ids = {x for b in bindings for x in (b.source_id, b.benchmark_source_id)}
        request = se.SelectionStabilityRequest(projection.request.plan, rule, tuple(bindings),
            tuple(f for f in projection.facts if f.source_id in ids), center_targets())
        result = se.assess_selection_stability(request)
        results.append({"context": group, "members": [b.candidate.candidate_id for b in bindings],
            "request": request.to_dict(), "result": result.to_dict()})
    save(WORK / "others/statistics_selection.json", {"groups": results,
        "projection_stats": projection.stats.to_dict(), "scope": "Objective-aligned retrospective selection stability; no estimate of actual adaptive selection bias."})
    print("SELECTION_COMPLETE", len(projection.sources), len(groups), flush=True)
    return projection


def extract(row, protocol):
    """Public cold projection, then a compact independently keyed research checkpoint."""
    cache = SCRATCH / (row["reference"]["sha256"] + ".json")
    psha = sha256((WORK / "protocols/statistics_protocol.json").read_bytes()).hexdigest()
    if cache.exists():
        value = read(cache)
        assert value["protocol_sha256"] == psha and value["reference"] == row["reference"]
        return value
    path, raw, header = source(row["reference"])
    req = header["request"]
    assert req["content_sha256"] == row["content_sha256"]
    assert canonical_sha256(req["candidate_definition"]) == row["implementation_sha256"]
    assert req["fee_rate"] == .001 and req["drawdown_basis"] == "SESSION_CLOSE"
    evidence, = build_equity_assessment(raw, lambda r: path.with_name(r["sha256"] + ".json").read_bytes())
    sessions = tuple(p.session for p in evidence.account)
    assert len(sessions) == 1212 and sessions[0] == protocol["sample"]["start"] and sessions[-1] == protocol["sample"]["end"]
    equity = np.asarray([p.equity for p in evidence.account])
    bh = np.asarray(evidence.benchmark_equity)
    returns = equity / np.r_[evidence.initial_cash, equity[:-1]] - 1
    bh_returns = bh / np.r_[evidence.initial_cash, bh[:-1]] - 1
    assert np.isfinite(returns).all() and (returns > -1).all()
    value = {"candidate_id": row["candidate_id"], "content_sha256": row["content_sha256"],
        "implementation_sha256": row["implementation_sha256"], "reference": row["reference"],
        "protocol_sha256": psha, "context_sha256": evidence.context_sha256,
        "scenario_context": evidence.scenario_context.to_dict(), "metric_version": evidence.metric_version,
        "sessions": sessions, "returns": returns.tolist(), "benchmark_returns": bh_returns.tolist()}
    save(cache, value)
    return value


def uncertainty(inv, protocol, projection):
    started = perf_counter()
    values = {}
    # Produce center statistics first, then complete the full historical research universe.
    ordered = sorted(inv["rows"], key=lambda r: (r["candidate_id"] not in protocol["centers"], r["candidate_id"]))
    for i, row in enumerate(ordered):
        value = extract(row, protocol)
        for alias in row["aliases"]:
            other = extract(alias, protocol)
            assert all(other[k] == value[k] for k in ("sessions", "returns", "benchmark_returns", "context_sha256", "scenario_context")), "Exact implementation rerun differs"
        values[row["candidate_id"]] = value
        if i == 1:
            bootstrap(values, protocol)
        if (i + 1) % 10 == 0:
            print("STATISTICS_READ", i+1, len(ordered), round(perf_counter()-started, 1), flush=True)
    save(WORK / "others/statistics_returns.json", {"protocol_sha256": sha256((WORK / "protocols/statistics_protocol.json").read_bytes()).hexdigest(),
        "members": list(values.values()), "scope": "All unique pre-selfcheck implementations; exact reruns checked and retained as inventory aliases"})
    groups = defaultdict(list)
    for binding in projection.sources:
        groups[(binding.context_sha256, canonical_sha256(binding.scenario_context.to_dict()))].append(binding)
    outcomes = []
    for group, bindings in groups.items():
        ids = [b.candidate.candidate_id.removeprefix("S019-") for b in bindings]
        reference = values[ids[0]]
        assert all(values[c]["sessions"] == reference["sessions"] and values[c]["benchmark_returns"] == reference["benchmark_returns"] for c in ids)
        matrix = np.column_stack([values[c]["returns"] for c in ids])
        digest = sha256(matrix.astype("<f8", copy=False).tobytes()).hexdigest()
        record = {"context": group, "members": ids, "matrix_sha256": digest,
            "raw_trials": sum(1+len(r["aliases"]) for r in inv["rows"] if r["candidate_id"] in ids),
            "unique_implementations": len(ids), "diagnostics": {}}
        data = ReturnMatrixEvidence(tuple(reference["sessions"]), tuple(ids), tuple(tuple(float(x) for x in r) for r in matrix), digest)
        try:
            pbo = se.cscv_pbo(data, block_count=10)
            record["diagnostics"]["PBO_SHARPE_PROXY"] = {"status": "AVAILABLE", **pbo.to_dict()}
        except (ValueError, FloatingPointError, ZeroDivisionError) as error:
            record["diagnostics"]["PBO_SHARPE_PROXY"] = {"status": "INSUFFICIENT_DATA", "reason": str(error)}
        sharpes = np.asarray([se.annualized_sharpe(matrix[:,i]) for i in range(matrix.shape[1])])
        assert np.isfinite(sharpes).all(), "No implicit removal of nonfinite trial statistics"
        effective = None
        try:
            effective = se.effective_trial_count(matrix)
            record["diagnostics"]["EFFECTIVE_TRIAL_COUNT"] = {"status": "AVAILABLE", "value": effective}
        except (ValueError, FloatingPointError, ZeroDivisionError) as error:
            record["diagnostics"]["EFFECTIVE_TRIAL_COUNT"] = {"status": "INSUFFICIENT_DATA", "reason": str(error)}
        for cid in protocol["centers"]:
            if cid not in ids:
                continue
            dsr = {}
            for label, count in (("RAW", record["raw_trials"]), ("EFFECTIVE", effective)):
                if count is None:
                    dsr[label] = {"status": "INSUFFICIENT_DATA", "reason": "Effective trial count unavailable"}
                    continue
                try:
                    dsr[label] = {"status": "AVAILABLE", **asdict(se.deflated_sharpe_ratio(matrix[:,ids.index(cid)], sharpes, float(count)))}
                except (ValueError, FloatingPointError, ZeroDivisionError) as error:
                    dsr[label] = {"status": "INSUFFICIENT_DATA", "reason": str(error)}
            record["diagnostics"]["DSR_SHARPE_PROXY_"+cid] = dsr
        outcomes.append(record)
    save(WORK / "others/statistics_search_bias.json", {"groups": outcomes,
        "published_evaluations": inv["published_account_count"], "unique_implementations": inv["unique_implementations"],
        "actual_nar_gated_adaptive_selection_bias": "NOT_ESTIMATED",
        "limitations": protocol["limitations"], "new_strategy_accounts": 0})
    print("SEARCH_BIAS_PROXY_COMPLETE", len(outcomes), flush=True)


def bootstrap(values, protocol):
    settings = protocol["bootstrap"]
    a, b = values["C0135"], values["C0224"]
    assert a["sessions"] == b["sessions"] and a["benchmark_returns"] == b["benchmark_returns"]
    results = []
    for left, right, x, y in (("C0135", "MU_BUY_HOLD", a["returns"], a["benchmark_returns"]),
        ("C0224", "MU_BUY_HOLD", b["returns"], b["benchmark_returns"]),
        ("C0135", "C0224", a["returns"], b["returns"])):
        result = se.paired_stationary_bootstrap(np.asarray(x), np.asarray(y), champion_id=left, comparator_id=right,
            repetitions=settings["repetitions"], mean_block_length=settings["mean_block_length"], seed=settings["seed"])
        results.append(result.to_dict())
    save(WORK / "others/statistics_bootstrap.json", {"protocol": settings, "comparisons": results,
        "source_references": [a["reference"], b["reference"]], "limitations": protocol["limitations"]})
    print("BOOTSTRAP_COMPLETE",flush=True)


def main():
    started = perf_counter()
    if (WORK / "protocols/statistics_protocol.json").exists():
        inv, protocol = read(WORK / "others/statistics_inventory.json"), read(WORK / "protocols/statistics_protocol.json")
        assert sha256((WORK / "others/statistics_inventory.json").read_bytes()).hexdigest() == protocol["inventory_sha256"]
    else:
        inv, protocol = inventory()
    print("STATISTICS_STARTED",flush=True)
    projection = selection(inv, protocol)
    uncertainty(inv, protocol, projection)
    save(WORK / "others/statistics_completion.json", {"status": "COMPLETE", "elapsed_seconds": perf_counter()-started,
        "published_accounts": inv["published_account_count"], "unique_implementations": inv["unique_implementations"],
        "new_strategy_accounts": 0, "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": sha256((WORK / "protocols/statistics_protocol.json").read_bytes()).hexdigest()})
    print("STATISTICS_COMPLETE", round(perf_counter()-started,1),flush=True)


if __name__ == "__main__":
    main()
