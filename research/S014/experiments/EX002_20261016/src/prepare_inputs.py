"""Prepare the confirmed S014 interval through the batch-owned DFLS API."""
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import time

import requests as http_requests
from tushare.pro.client import DataApi
from dataflows import DataRequest, Dataset, PreparePolicy
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX002_20261016/input-readiness"
CALL_CAP = 100


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3, 4), default=1)
    attempt = parser.parse_args().attempt
    names = {1: "input_readiness.json", 2: "input_readiness_retry.json", 3: "input_readiness_attempt3.json",
             4: "input_readiness_attempt4.json"}
    destination = EXPERIMENT / "others" / names[attempt]
    if destination.exists():
        raise RuntimeError("Review the existing readiness result before an explicit rerun")
    prior_calls = 0
    if attempt >= 2:
        initial = json.loads((EXPERIMENT / "others/input_readiness.json").read_text(encoding="utf-8"))
        diagnostic = json.loads((EXPERIMENT / "others/source_diagnostic.json").read_text(encoding="utf-8"))
        prior_calls = len(initial["upstream_calls"]) + len(diagnostic["source_probes"])
        if attempt >= 3:
            retry = json.loads((EXPERIMENT / "others/input_readiness_retry.json").read_text(encoding="utf-8"))
            prior_calls += len(retry["upstream_calls"])
        if attempt == 4:
            last = json.loads((EXPERIMENT / "others/input_readiness_attempt3.json").read_text(encoding="utf-8"))
            exact = json.loads((EXPERIMENT / "others/source_failed_ranges.json").read_text(encoding="utf-8"))
            prior_calls += len(last["upstream_calls"]) + len(exact["source_probes"])
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"))
    requests = tuple(
        DataRequest(dataset, symbol, "2020-01-01", "2026-10-15", "2026-10-15")
        for dataset, symbol in (
            (Dataset.TRADING_CALENDAR, "SSE"),
            (Dataset.STOCK_OHLCV, "600722.SH"),
            (Dataset.STOCK_UNADJUSTED_DAILY, "600722.SH"),
            (Dataset.SECURITY_PRICE_LIMITS, "600722.SH"),
            (Dataset.SECURITY_TRADING_STATUS, "600722.SH"),
        )
    )
    calls, results = [], []
    original = DataApi.query
    original_http = http_requests.sessions.Session.request

    def counted(self, api_name, fields="", **parameters):
        if prior_calls + len(calls) >= CALL_CAP:
            raise RuntimeError("S014 readiness upstream call cap exhausted")
        record = {"api": api_name, "parameters": parameters, "status": "STARTED"}
        calls.append(record)
        try:
            frame = original(self, api_name, fields=fields, **parameters)
            record.update(status="RETURNED", rows=0 if frame is None else len(frame))
            return frame
        except Exception as exc:
            record.update(status="FAILED", error_type=type(exc).__name__)
            raise

    def counted_http(self, method, url, **kwargs):
        if prior_calls + len(calls) >= CALL_CAP:
            raise RuntimeError("S014 readiness upstream call cap exhausted")
        # Observe transport without replacing the SDK query contract.
        time.sleep(.3)
        payload = kwargs.get("json", {})
        record = {"api": payload.get("api_name"), "parameters": payload.get("params"), "status": "STARTED"}
        calls.append(record)
        response = original_http(self, method, url, **kwargs)
        record.update(status="RETURNED", http_status=response.status_code)
        return response

    run = RUN / f"attempt-{attempt}"
    run.mkdir(parents=True, exist_ok=True)
    if attempt == 4:
        http_requests.sessions.Session.request = counted_http
    else:
        DataApi.query = counted
    try:
        for request in requests:
            prepared = context.data.prepare((request,), policy=PreparePolicy.REUSE)
            item = {"request": asdict(request), "status": prepared.status.value,
                    "errors": [x.error.code for x in prepared.items if x.error is not None]}
            if prepared.ready:
                fetched = context.data.fetch(request, prepared=prepared.reference)
                if not fetched.ready:
                    raise RuntimeError(f"Bound fetch failed: {request.dataset.value}")
                frame = fetched.dataframe
                item.update(rows=len(frame), reference=asdict(prepared.reference),
                            content_sha256=fetched.identity.content_sha256,
                            columns=list(frame.columns))
                path = run / (request.dataset.value.replace(".", "_") + ".csv")
                frame.to_csv(path, index=False)
                item["data_asset_copy"] = path.relative_to(ROOT).as_posix()
                if request.dataset is Dataset.SECURITY_TRADING_STATUS:
                    item["status_counts"] = frame.Status.value_counts().to_dict()
                if "Date" in frame and len(frame):
                    item.update(first_date=str(frame.Date.min()), last_date=str(frame.Date.max()))
            results.append(item)
            print(json.dumps({key: item[key] for key in ("request", "status", "rows") if key in item},
                             default=str), flush=True)
    finally:
        DataApi.query = original
        http_requests.sessions.Session.request = original_http
        payload = {"symbol": "600722.SH", "start": "2020-01-01", "end": "2026-10-15",
                   "attempt": attempt, "prior_upstream_calls": prior_calls,
                   "upstream_call_cap": CALL_CAP, "upstream_calls": calls, "results": results,
                   "ready": len(results) == len(requests) and all(x["status"] == "READY" for x in results),
                   "source_publication_timestamp_verified": False,
                   "historical_revision_history_verified": False,
                   "strategy_evaluations": 0, "parameter_searches": 0}
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
