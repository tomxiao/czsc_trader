"""Bounded S013 two-series acquisition; credentials are never serialized."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import requests
import pandas as pd
from dataflows.tushare_common import get_tushare_pro
from dataflows.config import get_tushare_token

ROOT = Path(__file__).resolve().parent
if (ROOT / "request_ledger.json").exists():
    raise RuntimeError("existing acquisition evidence must not be overwritten or silently requested again")
START, END = "20191009", "20260930"
REQUESTS = [
    ("G1", "index_dailybasic", "000905.SH", "turnover_rate_f", 3000),
    ("G2", "etf_share_size", "510500.SH", "total_share", 5000),
]
ledger = []
original_post = requests.post
secret = get_tushare_token(Path(".env"))
client = get_tushare_pro(Path(".env"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def post(url, *args, **kwargs):
    body = kwargs["json"]
    params = dict(body["params"])
    params.pop("ts_type_name", None)
    entry = {"request_number": len(ledger) + 1, "api": body["api_name"],
             "fields": body["fields"], "parameters": params,
             "requested_at_utc": datetime.now(timezone.utc).isoformat(), "is_retry": False}
    if len(ledger) >= 16:
        raise RuntimeError("request budget exhausted")
    ledger.append(entry)
    save_json(ROOT / "request_ledger.json", ledger)
    try:
        response = original_post(url, *args, **kwargs)
        entry["http_status"] = response.status_code
        safe_text = response.text.replace(secret, "[REDACTED]")
        raw = ROOT / f"response_{len(ledger):02d}.json"
        raw.write_text(safe_text, encoding="utf-8")
        entry.update({"response_path": raw.name, "response_sha256": sha(raw),
                      "response_bytes": raw.stat().st_size})
        return response
    except Exception as exc:
        entry["error_type"] = type(exc).__name__
        raise
    finally:
        save_json(ROOT / "request_ledger.json", ledger)

requests.post = post
review = {"scope": {"start": START, "end": END}, "supplier": "tushare",
          "request_budget": 16, "retry_budget": 2, "actual_retries": 0,
          "credential_loading": "existing dataflows.get_tushare_pro with explicit repository .env",
          "historical_publication_times_verified": False,
          "historical_revisions_verified": False,
          "availability_assumption": "At least one actual trading-day lag; current snapshot cannot establish historical release or revision timing",
          "series": {}}
for group, api, code, value, limit in REQUESTS:
    item = {"api": api, "ts_code": code, "value_field": value, "row_limit": limit,
            "fields_requested": ["ts_code", "trade_date", value]}
    review["series"][group] = item
    try:
        frame = client.query(api, fields=f"ts_code,trade_date,{value}", ts_code=code,
                             start_date=START, end_date=END)
        raw_csv = ROOT / f"{group}_raw.csv"
        frame.to_csv(raw_csv, index=False, lineterminator="\n")
        item.update({"raw_csv": raw_csv.name, "raw_csv_sha256": sha(raw_csv),
                     "returned_rows": len(frame), "returned_columns": list(frame.columns),
                     "request_number": len(ledger), "actual_permission": "request returned"})
        if set(frame.columns) != {"ts_code", "trade_date", value}:
            item["status"] = "UNEXPECTED_SCHEMA"
            continue
        dates = pd.to_datetime(frame.trade_date.astype(str), format="%Y%m%d", errors="coerce")
        numbers = pd.to_numeric(frame[value], errors="coerce")
        valid = dates.notna() & numbers.notna() & (numbers > 0 if group == "G2" else numbers >= 0)
        item.update({"first_date": dates.min().strftime("%Y-%m-%d") if len(frame) else None,
                     "last_date": dates.max().strftime("%Y-%m-%d") if len(frame) else None,
                     "duplicate_date_rows": int(dates.duplicated().sum()),
                     "unexpected_symbol_rows": int((frame.ts_code != code).sum()),
                     "invalid_value_or_date_rows": int((~valid).sum()),
                     "outside_range_rows": int(((dates < pd.Timestamp(START)) | (dates > pd.Timestamp(END))).sum()),
                     "potential_limit_truncation": len(frame) >= limit,
                     "status": "SNAPSHOT_READY_CONDITIONAL_AVAILABILITY" if len(frame) and valid.all() else "EMPTY_OR_INVALID"})
        clean = frame.copy()
        clean["trade_date"] = dates.dt.strftime("%Y-%m-%d")
        clean = clean.sort_values("trade_date", kind="stable")
        clean.to_csv(ROOT / f"{group}_ordered.csv", index=False, lineterminator="\n")
        item["ordered_csv_sha256"] = sha(ROOT / f"{group}_ordered.csv")
        if len(frame):
            item["value_min"] = float(numbers.min())
            item["value_max"] = float(numbers.max())
            item["yearly_rows"] = {str(k): int(v) for k, v in dates.dt.year.value_counts().sort_index().items()}
    except Exception as exc:
        item.update({"status": "REQUEST_FAILED", "error_type": type(exc).__name__,
                     "error_message": str(exc).replace(secret, "[REDACTED]")})
    finally:
        review["actual_requests"] = len(ledger)
        save_json(ROOT / "data_review.json", review)
print(json.dumps({"requests": len(ledger), "retries": 0, "series": review["series"]}, ensure_ascii=False))
