"""Explicitly resume S014 preparation after the approved HTTP transport fix."""
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import time

import requests
from dataflows import DataRequest, Dataset, PreparePolicy, SourceNotReadyError
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
CALL_CAP = 50


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    attempt = parser.parse_args().attempt
    destination = EXPERIMENT / f"others/input_readiness_fixed_{attempt}.json"
    if destination.exists():
        raise RuntimeError("Existing attempt must be reviewed, never overwritten")
    previous = []
    if attempt == 2:
        previous = json.loads((EXPERIMENT / "others/input_readiness_fixed_1.json").read_text(encoding="utf-8"))["upstream_calls"]
    calls = []
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"))
    original = requests.sessions.Session.request

    def observed(self, method, url, **kwargs):
        if len(previous) + len(calls) >= CALL_CAP:
            raise SourceNotReadyError("S014 recovery source budget exhausted", reason="explicit_call_cap")
        time.sleep(.25)
        payload = kwargs.get("json", {})
        item = {"api": payload.get("api_name"), "parameters": payload.get("params"), "status": "STARTED"}
        calls.append(item)
        try:
            response = original(self, method, url, **kwargs)
            item.update(status="RETURNED", http_status=response.status_code)
            return response
        except requests.RequestException as exc:
            item.update(status="FAILED", exception_type=type(exc).__name__)
            raise

    records = []
    requests.sessions.Session.request = observed
    try:
        for dataset, symbol in (
            (Dataset.TRADING_CALENDAR, "SSE"), (Dataset.STOCK_OHLCV, "600722.SH"),
            (Dataset.STOCK_UNADJUSTED_DAILY, "600722.SH"),
            (Dataset.SECURITY_PRICE_LIMITS, "600722.SH"), (Dataset.SECURITY_TRADING_STATUS, "600722.SH"),
        ):
            request = DataRequest(dataset, symbol, "2020-01-01", "2026-10-15", "2026-10-15")
            prepared = context.data.prepare((request,), policy=PreparePolicy.REUSE)
            entry = {"request": asdict(request), "status": prepared.status.value,
                     "items": [{"status": item.status.value, "error": asdict(item.error) if item.error else None}
                               for item in prepared.items]}
            if prepared.ready:
                fetched = context.data.fetch(request, prepared=prepared.reference)
                if not fetched.ready:
                    raise RuntimeError("Bound input read failed")
                frame = fetched.dataframe
                entry.update(reference=asdict(prepared.reference), rows=len(frame),
                             content_sha256=fetched.identity.content_sha256, columns=list(frame.columns))
                if dataset is Dataset.TRADING_CALENDAR:
                    entry["exchange_sessions"] = int(frame.IsOpen.eq(1).sum())
                if dataset is Dataset.SECURITY_TRADING_STATUS:
                    entry["status_counts"] = frame.Status.value_counts().to_dict()
            records.append(entry)
            print(json.dumps({"dataset": dataset.value, "status": entry["status"], "rows": entry.get("rows")}), flush=True)
    finally:
        requests.sessions.Session.request = original
        result = {"symbol": "600722.SH", "start": "2020-01-01", "end": "2026-10-15",
                  "transport_fix": "824b144b", "attempt": attempt, "prior_calls": len(previous),
                  "upstream_call_cap": CALL_CAP, "upstream_calls": calls, "records": records,
                  "ready": len(records) == 5 and all(item["status"] == "READY" for item in records),
                  "strategy_evaluations": 0, "parameter_searches": 0}
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
