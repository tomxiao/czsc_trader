"""Explicit S013 pinned-asset subset materialization; no financial evaluation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import time_ns
from uuid import UUID

import pandas as pd
from dataflows import (DataCoverageRequirement, DataRequest, Dataset, NoParameters,
    PreparePolicy, PreparedDataRef, ProviderBinding, ProviderConfig, canonical_frame_sha256)
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvaluationResources, ResearchBatchRef
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_runtime import StrategyCandidate
import driver

ROOT = driver.draft.ROOT
OUT = ROOT / ".tmp/s013-robust-center/priming"
DATASETS = (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
            Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def record(request):
    return {"dataset": str(request.dataset), "symbol": request.symbol,
        "start": request.start, "end": request.end, "required_cutoff": request.required_cutoff,
        "frequency": request.frequency, "parameters": asdict(request.parameters),
        "coverage": asdict(request.coverage) if request.coverage is not None else None}


def request_from(value):
    if value["parameters"] != {}:
        raise ValueError("Only frozen S013 NoParameters selectors are supported")
    coverage = DataCoverageRequirement(**value["coverage"]) if value["coverage"] else None
    return DataRequest(Dataset(value["dataset"]), value["symbol"], value["start"], value["end"],
        value["required_cutoff"], value["frequency"], NoParameters(), coverage)


def select_sources():
    """Metadata only, and only the S013-owned database; never inspect other spaces."""
    path = ROOT / "research/S013/assets/data/assets.sqlite3"
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        space = connection.execute("select space_id from space_metadata").fetchone()[0]
        chosen = {}
        for pid, hashed, manifest in connection.execute("select preparation_id,manifest_sha256,manifest from preparations"):
            if sha256(manifest.encode()).hexdigest() != hashed:
                raise ValueError("Stored public preparation manifest hash differs")
            for entry in json.loads(manifest):
                value = entry["request"]
                dataset = value["dataset"]
                if entry.get("data_contract_version") != 1 or dataset not in set(map(str, DATASETS)):
                    continue
                if value["parameters"] != {} or value["end"] < ("2026-09-29" if dataset == str(Dataset.ETF_OHLCV) else "2026-09-30"):
                    continue
                expected = "SSE" if dataset == str(Dataset.TRADING_CALENDAR) else "510500.SH"
                if value["symbol"] != expected:
                    continue
                if dataset not in chosen or value["start"] < chosen[dataset]["request"]["start"]:
                    chosen[dataset] = {"request": value, "asset_id": entry["asset_id"],
                        "prepared": {"space_id": space, "preparation_id": pid, "manifest_sha256": hashed}}
        if set(chosen) != set(map(str, DATASETS)):
            raise ValueError("All four explicit existing source series must be present")
        return chosen
    finally:
        connection.close()


def reference(source):
    value = source["prepared"]
    return PreparedDataRef(UUID(value["space_id"]), UUID(value["preparation_id"]), value["manifest_sha256"])


def pinned_fetch(ctx, request, sources):
    source = sources[str(request.dataset)]
    declared = source["request"]
    if (request.symbol, request.frequency, asdict(request.parameters)) != (declared["symbol"], declared["frequency"], declared["parameters"]):
        raise ValueError("Dataset/symbol/frequency/parameter selector drift")
    if request.start < declared["start"] or request.end > declared["end"]:
        raise ValueError("Request extends outside explicitly pinned source")
    result = ctx.data.fetch(request, prepared=reference(source))
    if not result.ready or result.identity.content_sha256 != canonical_frame_sha256(result.dataframe):
        raise ValueError("Pinned existing subset is missing, invalid or hash-drifted: " + str(result.error))
    return result


def bounded_requests(ctx, method, sources):
    """Derive only the frozen297 roles using public definitions and frozen source scope formula."""
    _, coordinates, config, _ = driver.draft.metadata_queue()
    payload = config["payload"]
    root = driver.draft.EX058 / "src" / config["source_directory"]
    calendar_request = request_from(sources[str(Dataset.TRADING_CALENDAR)]["request"])
    calendar = pinned_fetch(ctx, calendar_request, sources)
    opened = tuple(pd.to_datetime(calendar.dataframe.loc[calendar.dataframe.IsOpen.eq(1), "Date"]).dt.date)
    start, end = date(2020, 1, 2), date(2026, 9, 30)
    trading = tuple(day for day in opened if start <= day <= end)
    if not trading or trading[0] != start or trading[-1] != end:
        raise ValueError("Existing calendar lacks actual window endpoints")
    signal_first = max(day for day in opened if day < start)
    signal_last = max(day for day in opened if day < end)
    available = tuple(day for day in opened if day <= signal_first)
    requests, roles, unique_payloads = {}, [], set()
    for index, row in enumerate(method["queue"]):
        parameters = row["parameters"]
        candidate_id = row["existing_candidate"] or f"C{591+index-3:04}"
        center_payload = driver.draft.plain(payload)
        center_payload["parameters"] = parameters
        center = StrategyCandidate("S013", candidate_id, center_payload, root)
        identity = ctx.runtime.identify(center, dependencies=driver.legacy_pickle_support().DEPENDENCIES)
        dummy_mapping = type("Evidence", (), {"sha256": "1"*64})()
        dummy_feasibility = type("Evidence", (), {"sha256": "2"*64})()
        design = driver.draft.design_for(center, identity, coordinates, dummy_mapping, dummy_feasibility)
        variants = [("center", parameters)] + [(f"P{point.index:02}", driver.draft.materialize(parameters, coordinates, point.coordinates)) for point in design.points]
        for suffix, values in variants:
            unique_payloads.add(driver.canonical_parameters(values))
            typed = driver.draft.plain(payload)
            typed["parameters"] = values
            definition = ctx.runtime.describe(StrategyCandidate("S013", "C0000", typed, root))
            warmup = max(item.lookback_sessions for item in definition.inputs.requirements)
            calendar_start = (start - timedelta(days=max(45, warmup*2))).isoformat()
            calendar_req = DataRequest(Dataset.TRADING_CALENDAR, "SSE", calendar_start, end.isoformat(), end.isoformat())
            # Frozen scope sees only the request's calendar range, never a wider effective warmup.
            role_available = tuple(day for day in available if day.isoformat() >= calendar_start)
            selected = [calendar_req]
            for item in definition.inputs.requirements:
                if item.dataset == str(Dataset.TRADING_CALENDAR):
                    continue
                depth = max(1, item.lookback_sessions)
                if len(role_available) < depth:
                    raise ValueError("Original warmup requirement is not covered")
                coverage = DataCoverageRequirement(maximum_start_lag_days=None, minimum_observations=depth,
                    minimum_sessions=depth, observations_through=signal_first.isoformat())
                selected.append(DataRequest(Dataset(item.dataset), item.subject, role_available[-depth].isoformat(),
                    signal_last.isoformat(), signal_last.isoformat(), item.frequency, coverage=coverage))
            keys = []
            for item in selected:
                key = json.dumps(record(item), sort_keys=True)
                requests[key] = item
                keys.append(sha256(key.encode()).hexdigest())
            roles.append({"role": row["label"]+":"+suffix, "warmup": warmup, "requests": keys})
    # Execution requests are fixed inherited input assets, not additional numerical search.
    for dataset in (Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY):
        request = request_from(sources[str(dataset)]["request"])
        requests[json.dumps(record(request), sort_keys=True)] = request
    if len(roles) != 297 or len(unique_payloads) != 294:
        raise ValueError("Frozen finite role/design counts differ")
    return requests, roles


def coverage(method_ref, sources=None):
    method = driver.draft.require_frozen_method(method_ref)
    ctx = driver.draft.existing_only_context(method_ref, 1)
    sources = sources or select_sources()
    requests, roles = bounded_requests(ctx, method, sources)
    rows = []
    for key, request in requests.items():
        value = pinned_fetch(ctx, request, sources)
        metadata = dict(value.identity.metadata)
        price_contract = {name: item for name, item in metadata.items()
                          if any(token in name.lower() for token in ("adjust", "basis", "anchor", "factor"))}
        rows.append({"request": record(request), "request_sha256": sha256(key.encode()).hexdigest(),
            "source_prepared": sources[str(request.dataset)]["prepared"], "source_asset_id": sources[str(request.dataset)]["asset_id"],
            "content_sha256": value.identity.content_sha256, "columns": list(value.dataframe.columns),
            "observations": len(value.dataframe), "price_contract": price_contract})
    failure = driver.WORK / "failure.json"
    output = {"status": "READONLY_COVERAGE_PASS", "method_reference": method_ref.to_dict(),
        "source_sha256": digest(__file__), "sources": sources, "roles": roles, "requests": rows,
        "role_count": 297, "standard_unique_configurations": 294,
        "unique_exact_requests": len(rows), "failed_declare_sha256": digest(failure),
        "public_contracts": {str(path.relative_to(ROOT)): digest(path) for path in (
            ROOT/'packages/dataflows/src/dataflows/facade.py', ROOT/'packages/dataflows/src/dataflows/contract.py',
            driver.draft.EX058/'src/strategy_runtime/strategies/range_reversion.py')},
        "new_account_evaluations": 0, "preparations": 0, "external_provider_calls": 0,
        "limits": "Read-only existing pinned data; no price normalization, repair, new sample or changed warmup/domain. Priming is separately root-invoked."}
    driver.write(OUT / "coverage.json", output)
    return output


def prime(method_ref, expected_coverage_sha):
    path = OUT / "coverage.json"
    if digest(path) != expected_coverage_sha:
        raise ValueError("Root-reviewed coverage SHA differs")
    proof = driver.read(path)
    if proof["status"] != "READONLY_COVERAGE_PASS" or proof["source_sha256"] != digest(__file__):
        raise ValueError("Coverage/source proof differs")
    old = driver.draft.existing_only_context(method_ref, 1)
    calls, refs = [], []
    def provider(request):
        result = pinned_fetch(old, request, proof["sources"])
        calls.append({"request": record(request), "content_sha256": result.identity.content_sha256})
        return result.dataframe.copy(deep=True), dict(result.identity.metadata)
    bindings = {dataset: ProviderBinding(str(dataset), "S013-EX062-existing-only", provider) for dataset in DATASETS}
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S013"),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(1,1,13))
    for row in proof["requests"]:
        request = request_from(row["request"])
        prepared = ctx.data.prepare((request,), policy=PreparePolicy.REUSE)
        if not prepared.ready:
            raise ValueError("Pinned subset materialization failed: " + str(prepared.items))
        actual = ctx.data.fetch(request, prepared=prepared.reference)
        original = pinned_fetch(old, request, proof["sources"])
        pd.testing.assert_frame_equal(actual.dataframe, original.dataframe, check_exact=True)
        if actual.identity.content_sha256 != row["content_sha256"]:
            raise ValueError("Materialization changed selected original frame content")
        for name, expected in row["price_contract"].items():
            if actual.identity.metadata.get(name) != expected:
                raise ValueError("Price basis/adjustment anchor drift: " + name)
        refs.append({"request": row["request"], "prepared": {"space_id": str(prepared.reference.space_id),
            "preparation_id": str(prepared.reference.preparation_id), "manifest_sha256": prepared.reference.manifest_sha256},
            "content_sha256": actual.identity.content_sha256, "original_frame_exact": True})
        driver.write(OUT / "priming_progress.json", {"status": "PARTIAL", "completed": refs,
            "local_pinned_provider_calls": calls, "new_account_evaluations": 0, "external_provider_calls": 0})
    driver.write(OUT / "priming.json", {"status": "PASS", "coverage_sha256": expected_coverage_sha,
        "source_sha256": digest(__file__), "completed": refs, "local_pinned_provider_calls": calls,
        "new_account_evaluations": 0, "external_provider_calls": 0, "financial_driver_provider_still_forbidden": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("coverage", "prime"))
    parser.add_argument("--method-reference", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--coverage-sha256")
    args = parser.parse_args()
    if digest(__file__) != args.source_sha256:
        parser.error("Source differs from reviewed source")
    method_ref = EvidenceRef.from_dict(driver.read(args.method_reference))
    if args.action == "coverage":
        output = coverage(method_ref)
        print({"status": output["status"], "roles": 297, "requests": output["unique_exact_requests"]})
    else:
        if not args.coverage_sha256:
            parser.error("Priming requires exact root-reviewed coverage SHA")
        prime(method_ref, args.coverage_sha256)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        driver.write(OUT / f"failure-{time_ns()}.json", {"status": "FAILED", "source_sha256": digest(__file__),
            "error": {"type": type(exc).__name__, "message": str(exc)}, "new_account_evaluations": 0})
        raise
