"""Inspect saved EX038 MCP call objects; no network or provider access.

The output is a replaceable working inventory, not a published research asset.
File hashes identify saved call objects, never exact upstream transport bytes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, time, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
MARKET_DATES = ("trade_date", "nav_date", "trade_time", "time", "datetime", "date")
METADATA_ENDPOINTS = {"opt_basic", "etf_basic", "etf_index", "mkt_idx_bmk"}
NAN_TEXT = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def parse_date(value, field="date"):
    """Return an explicit calendar timestamp; never anchor clock-only strings."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d")
        if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", text):
            parsed = datetime.fromisoformat(text.replace("/", "-").replace("Z", "+00:00"))
            return (
                parsed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
                if parsed.tzinfo
                else parsed
            )
        if field in {"time", "trade_time"} and re.fullmatch(r"\d{10}|\d{13}", text):
            seconds = int(text) / (1000 if len(text) == 13 else 1)
            return (
                datetime.fromtimestamp(seconds, timezone.utc)
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .replace(tzinfo=None)
            )
    except (ValueError, OverflowError, OSError):
        return None
    return None


def response_table(result):
    texts = []
    if isinstance(result, dict):
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
    elif isinstance(result, str):
        texts.append(result)
    candidates = []
    if isinstance(result, dict) and "structuredContent" in result:
        candidates.append(result["structuredContent"])
    if isinstance(result, list):
        candidates.append(result)
    if isinstance(result, dict) and ("data" in result or "fields" in result):
        candidates.append(result)
    for text in texts:
        try:
            candidates.append(json.loads(text))
        except (json.JSONDecodeError, ValueError):
            pass
    for obj in candidates:
        nested = obj.get("data", obj) if isinstance(obj, dict) else obj
        if isinstance(nested, list) and all(isinstance(row, dict) for row in nested):
            return nested, "JSON_RECORD_ARRAY", texts, candidates
        if (
            isinstance(nested, dict)
            and isinstance(nested.get("fields"), list)
            and isinstance(nested.get("items"), list)
        ):
            fields, items = nested["fields"], nested["items"]
            if all(isinstance(row, list) and len(row) == len(fields) for row in items):
                return (
                    [dict(zip(fields, row, strict=True)) for row in items],
                    "JSON_FIELDS_ITEMS_TABLE",
                    texts,
                    candidates,
                )
    return None, "UNRECOGNIZED", texts, candidates


def classify(result, records, texts, parsed):
    text = "\n".join(texts)
    low = text.lower()
    automatic_review = bool(re.search(r"automatic(?:\s+permission)?\s+approval\s+review", low))
    if automatic_review and any(
        x in low for x in ("deadline", "timeout", "timed out", "did not finish")
    ):
        return (
            "AUTOMATIC_APPROVAL_TIMEOUT",
            "Automatic review did not finish; not an account permission conclusion",
        )
    if automatic_review and any(x in low for x in ("rejected", "denied")):
        return (
            "AUTOMATIC_APPROVAL_REJECTED",
            "Tool approval result; distinct from vendor account permission",
        )
    if automatic_review and any(
        x in low
        for x in ("failed", "could not be completed", "at capacity", "action was not executed")
    ):
        return (
            "AUTOMATIC_APPROVAL_FAILURE",
            "Automatic review failed; explicit not-executed language retained separately; no vendor permission conclusion",
        )
    provider_40203 = bool(re.search(r"tushare\s+api\s+错误\s*\[40203\]", low)) or any(
        isinstance(obj, dict) and str(obj.get("code")) == "40203" for obj in parsed
    )
    vendor_permission = bool(
        re.search(
            r"没有访问.{0,12}接口.{0,12}权限|没有接口(?:\([^\n)]{1,80}\))?访问权限|没有.{0,8}接口.{0,80}访问权限|无权访问.{0,12}接口|接口.{0,80}权限不足",
            text,
        )
    ) or bool(
        re.search(
            r"(?:no|insufficient|do not have).{0,25}permission.{0,35}(?:api|interface|tushare)|(?:api|interface|tushare).{0,35}permission denied",
            low,
        )
    )
    if provider_40203 or vendor_permission:
        return (
            "PROVIDER_PERMISSION_DENIED",
            "Explicit interface/account denial in returned text; no inference from point requirements",
        )
    failed = isinstance(result, dict) and result.get("isError") is True
    for obj in parsed:
        if isinstance(obj, dict) and obj.get("code") not in (None, 0, "0"):
            failed = True
    if failed or re.match(r"\s*(?:error\b|exception\b|traceback\b|调用失败|错误[:：])", text, re.I):
        return (
            "OTHER_TECHNICAL_FAILURE",
            "Returned error; does not establish vendor permission either way",
        )
    if records is not None:
        return (
            ("SUCCESS_NONEMPTY", "Observed data for this exact request only")
            if records
            else (
                "EMPTY_RETURN_PERMISSION_UNRESOLVED",
                "Empty table; neither permission denial nor full-history absence proved",
            )
        )
    if result is None:
        return (
            "RECORDED_ATTEMPT_WITHOUT_RESULT",
            "Call record exists but result not saved yet; budget reservation retained",
        )
    return (
        "UNKNOWN_FORMAT_MANUAL_REVIEW",
        "Unrecognized successful/plain-text shape retained for manual review; no data or permission claim",
    )


def classification_boundary_checks():
    """Small fixed classifier checks; no data collection or saved-call mutation."""
    cases = [
        (
            "The automatic permission approval review did not finish before its deadline.",
            True,
            None,
            "AUTOMATIC_APPROVAL_TIMEOUT",
        ),
        ("Automatic approval review timed out.", True, None, "AUTOMATIC_APPROVAL_TIMEOUT"),
        (
            "Automatic approval review failed: Selected model is at capacity. The action was not executed because automatic approval review could not be completed.",
            True,
            None,
            "AUTOMATIC_APPROVAL_FAILURE",
        ),
        (
            "Automatic approval review rejected the requested interface access.",
            True,
            None,
            "AUTOMATIC_APPROVAL_REJECTED",
        ),
        (
            "tushare API 错误 [40203]: 抱歉，您没有接口(opt_mins)访问权限",
            True,
            None,
            "PROVIDER_PERMISSION_DENIED",
        ),
        (
            "tushare API 错误 [40203]: 抱歉，您没有接口(etf_auction)访问权限",
            True,
            None,
            "PROVIDER_PERMISSION_DENIED",
        ),
        ("抱歉，您没有访问该接口的权限", True, None, "PROVIDER_PERMISSION_DENIED"),
        (
            "Automatic approval review failed. Copied diagnostic: tushare API 错误 [40203]",
            True,
            None,
            "AUTOMATIC_APPROVAL_FAILURE",
        ),
        ("PermissionError: access denied for local file", True, None, "OTHER_TECHNICAL_FAILURE"),
        ("该接口需要5000积分", False, None, "UNKNOWN_FORMAT_MANUAL_REVIEW"),
        ("[]", False, [], "EMPTY_RETURN_PERMISSION_UNRESOLVED"),
        ('[{"ts_code":"510300.SH"}]', False, [{"ts_code": "510300.SH"}], "SUCCESS_NONEMPTY"),
    ]
    for text, is_error, records, expected in cases:
        actual, _ = classify({"isError": is_error}, records, [text], [])
        assert actual == expected, (text, actual, expected)
    actual, _ = classify({"isError": True}, None, [], [{"code": 40203, "msg": "接口权限不足"}])
    assert actual == "PROVIDER_PERMISSION_DENIED"
    return {"status": "PASS", "fixed_cases": len(cases) + 1}


def column_inventory(records):
    columns = sorted({str(key) for row in records for key in row})
    result = {}
    for column in columns:
        present = [row[column] for row in records if column in row]
        finite = sum(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in present
        )
        nonfinite = sum(isinstance(v, float) and not math.isfinite(v) for v in present)
        text_nonfinite = sum(isinstance(v, str) and v.strip().lower() in NAN_TEXT for v in present)
        result[column] = {
            "types": dict(Counter(type(v).__name__ for v in present)),
            "missing_key_count": len(records) - len(present),
            "explicit_null_count": sum(v is None for v in present),
            "empty_string_count": sum(isinstance(v, str) and not v.strip() for v in present),
            "finite_numeric_count": finite,
            "nonfinite_numeric_count": nonfinite,
            "nonfinite_text_count": text_nonfinite,
            "nonfinite_policy": "Reported for every column, including names/codes; never assume a nonnumeric column cannot contain NaN",
        }
    return result


def key_inventory(endpoint, records, columns):
    lower = {name.lower(): name for name in columns}
    keys = []
    for option in ("ts_code", "symbol", "code"):
        if option in lower:
            keys.append(lower[option])
            break
    for option in ("trade_time", "datetime", "trade_date", "nav_date", "date", "time"):
        if option in lower:
            keys.append(lower[option])
            break
    partial = False
    if endpoint in {"etf_sh_cons", "etf_sz_cons"}:
        component = next(
            (
                lower[k]
                for k in ("con_code", "cons_code", "stk_code", "component_code")
                if k in lower
            ),
            None,
        )
        if component:
            keys.append(component)
        else:
            partial = True
    if not keys and endpoint in {"etf_index", "mkt_idx_bmk"}:
        keys = [lower[k] for k in ("index_code", "bmk_code", "market") if k in lower]
    counts = (
        Counter(canonical([row.get(k) for k in keys]) for row in records) if keys else Counter()
    )
    return {
        "candidate_key_columns": keys,
        "partial_key_warning": partial,
        "rows_missing_any_key": sum(any(row.get(k) is None for k in keys) for row in records)
        if keys
        else None,
        "duplicate_key_excess_rows": sum(v - 1 for v in counts.values() if v > 1) if keys else None,
        "duplicate_key_groups": sum(v > 1 for v in counts.values()) if keys else None,
        "exact_duplicate_excess_rows": len(records) - len({canonical(row) for row in records}),
        "interpretation": "Inferred diagnostic keys, not a certified interface primary-key contract; repeats can represent revisions or incomplete keys",
    }


def temporal_inventory(endpoint, args, records, columns, historical_window):
    lower = {name.lower(): name for name in columns}
    realtime = endpoint.startswith("rt_")
    metadata = endpoint in METADATA_ENDPOINTS
    candidates = [lower[k] for k in MARKET_DATES if k in lower] if not metadata else []
    dates = []
    unparsed = Counter()
    for row in records:
        for column in candidates:
            value = row.get(column)
            parsed = parse_date(value, column.lower())
            if parsed is not None:
                dates.append((parsed, column))
            elif value is not None and str(value).strip():
                unparsed[column] += 1
    request_lower = request_upper = None
    for name in ("start_time", "start_date", "start"):
        if args.get(name) is not None:
            request_lower = parse_date(args[name])
            break
    for name in ("end_time", "end_date", "end"):
        if args.get(name) is not None:
            value = args[name]
            request_upper = parse_date(value)
            if request_upper and len(str(value).strip()) in {8, 10}:
                request_upper = datetime.combine(request_upper.date(), time.max)
            break
    for name in ("trade_date", "nav_date"):
        if args.get(name):
            exact = parse_date(args[name])
            if exact:
                request_lower = exact
                request_upper = datetime.combine(exact.date(), time.max)
            break
    bounds = [parse_date(value) for value in historical_window]
    protocol_end = datetime.combine(bounds[1].date(), time.max)
    timestamps = [d for d, _ in dates]
    out_request = [
        d.isoformat()
        for d in timestamps
        if (request_lower and d < request_lower) or (request_upper and d > request_upper)
    ]
    out_protocol = [d.isoformat() for d in timestamps if d < bounds[0] or d > protocol_end]
    return {
        "mode": "REALTIME_CAPABILITY_ONLY"
        if realtime
        else "CURRENT_IDENTITY_METADATA_ONLY"
        if metadata
        else "OBSERVED_MARKET_OR_NAV_DATES",
        "market_date_columns": candidates,
        "metadata_date_columns_excluded": [
            c
            for c in columns
            if c.lower()
            in {"list_date", "delist_date", "maturity_date", "found_date", "due_date", "issue_date"}
        ],
        "first_observed_market_datetime": min(timestamps).isoformat() if timestamps else None,
        "last_observed_market_datetime": max(timestamps).isoformat() if timestamps else None,
        "unique_observed_market_dates": sorted({d.date().isoformat() for d in timestamps}),
        "parsed_timestamp_cells": len(timestamps),
        "unparsed_nonempty_date_cells": dict(unparsed),
        "request_start": request_lower.isoformat() if request_lower else None,
        "request_end": request_upper.isoformat() if request_upper else None,
        "outside_requested_window_cells": len(out_request),
        "outside_requested_window_examples": out_request[:5],
        "outside_historical_protocol_window_cells": len(out_protocol),
        "outside_historical_protocol_window_examples": out_protocol[:5],
        "historical_coverage_admissible": not realtime and not metadata,
        "historical_coverage_claim": "Observed request anchors/short segments only; not full-window or point-in-time certification"
        if not realtime and not metadata
        else "Excluded from historical market-coverage evidence",
        "timezone_rule": "Explicit timezone/epoch converted to Asia/Shanghai; naive supplied timestamps retained; clock-only values never assigned an invented date",
    }


def inspect_call(path, design):
    call = read(path)
    endpoint = call.get("endpoint", "UNKNOWN_ENDPOINT")
    args = call.get("args", {})
    result = call.get("result")
    records, parser, texts, parsed = response_table(result)
    status, reason = classify(result, records, texts, parsed)
    record_rows = records if records is not None else []
    columns = column_inventory(record_rows)
    requested = args.get("fields", [])
    requested = (
        [x.strip() for x in requested.split(",") if x.strip()]
        if isinstance(requested, str)
        else requested
    )
    truncation = []
    if (
        isinstance(args.get("limit"), (int, float))
        and records is not None
        and len(records) >= args["limit"]
    ):
        truncation.append("ROW_COUNT_REACHES_REQUESTED_LIMIT_NOT_COMPLETENESS_PROOF")
    for obj in parsed:
        if isinstance(obj, dict):
            if obj.get("hasMore") is True or obj.get("has_more") is True:
                truncation.append("RESPONSE_DECLARES_MORE_ROWS")
            if (
                isinstance(obj.get("total"), (int, float))
                and records is not None
                and obj["total"] > len(records)
            ):
                truncation.append("RESPONSE_TOTAL_EXCEEDS_SAVED_ROWS")
    return {
        "id": call.get("id"),
        "endpoint": endpoint,
        "args": args,
        "status": status,
        "status_reason": reason,
        "action_execution_status": "NOT_EXECUTED"
        if status.startswith("AUTOMATIC_APPROVAL_")
        and "action was not executed" in "\n".join(texts).lower()
        else "UNKNOWN_FROM_SAVED_RESULT",
        "rows": len(records) if records is not None else None,
        "parser": parser,
        "isError": result.get("isError") if isinstance(result, dict) else None,
        "started_at": call.get("started_at"),
        "finished_at": call.get("finished_at"),
        "saved_call_path": relative(path),
        "saved_call_sha256": digest(path),
        "provenance": call.get("provenance"),
        "transport_bytes_verified": False,
        "observed_columns": list(columns),
        "requested_columns_missing_from_nonempty_table": sorted(set(requested or []) - set(columns))
        if records
        else [],
        "columns": columns,
        "keys": key_inventory(endpoint, record_rows, columns),
        "time": temporal_inventory(
            endpoint, args, record_rows, columns, design["scope"]["historical_window"]
        ),
        "truncation_warnings": truncation,
        "response_text_for_review": "\n".join(texts)[:6000]
        if status not in {"SUCCESS_NONEMPTY", "EMPTY_RETURN_PERMISSION_UNRESOLVED"}
        else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=relative(EX / "others/census_inventory.json"),
        help="Replaceable working JSON path, within EX038 or .tmp",
    )
    args = parser.parse_args()
    output = Path(args.output)
    output = (output if output.is_absolute() else ROOT / output).resolve()
    if not (output.is_relative_to(EX) or output.is_relative_to(ROOT / ".tmp")):
        raise ValueError("Output must remain in the authorized EX038 or .tmp write scope")
    design_path = EX / "protocols/design.json"
    design = read(design_path)
    endpoints = [*design["interfaces"]["core"], *design["interfaces"]["related"]]
    assert endpoints and len(endpoints) == len(set(endpoints)), (
        "Protocol interface names must be nonempty and unique"
    )
    boundary_checks = classification_boundary_checks()
    paths = sorted((EX / "others/calls").glob("*.json"))
    calls = [inspect_call(path, design) for path in paths]
    calls.sort(key=lambda row: (row["id"] is None, row["id"] or 0, row["saved_call_path"]))
    inventory = []
    for endpoint in endpoints:
        chosen = [row for row in calls if row["endpoint"] == endpoint]
        counts = Counter(row["status"] for row in chosen)
        valid_dates = [
            day
            for row in chosen
            if row["status"] == "SUCCESS_NONEMPTY" and row["time"]["historical_coverage_admissible"]
            for day in row["time"]["unique_observed_market_dates"]
        ]
        inventory.append(
            {
                "endpoint": endpoint,
                "mcp_calls_recorded": len(chosen),
                "call_ids": [row["id"] for row in chosen],
                "status": "UNTESTED"
                if not chosen
                else "NONEMPTY_RESPONSE_OBSERVED"
                if counts["SUCCESS_NONEMPTY"]
                else "NO_NONEMPTY_RESPONSE_OBSERVED",
                "call_status_counts": dict(counts),
                "nonempty_success_calls": counts["SUCCESS_NONEMPTY"],
                "successful_observed_rows_including_repeat_calls": sum(
                    row["rows"] for row in chosen if row["status"] == "SUCCESS_NONEMPTY"
                ),
                "observed_columns": sorted({c for row in chosen for c in row["observed_columns"]}),
                "first_observed_historical_date": min(valid_dates) if valid_dates else None,
                "last_observed_historical_date": max(valid_dates) if valid_dates else None,
                "unique_observed_historical_dates": sorted(set(valid_dates)),
                "permission_conclusion": "Successful exact requests establish only observed current response capability"
                if counts["SUCCESS_NONEMPTY"]
                else "Explicit denial observed; retain request-level scope"
                if counts["PROVIDER_PERMISSION_DENIED"]
                else "UNRESOLVED_NO_PERMISSION_CONCLUSION",
                "coverage_limit": "Single or multiple anchors/short segments are not full historical coverage; metadata and real-time rows excluded",
            }
        )
    ids = [row["id"] for row in calls if isinstance(row["id"], int)]
    cap = design["budget"]["max_mcp_invocations"]
    maximum = max(ids, default=0)
    result = {
        "status": "WORKING_SAVED_CALL_INVENTORY_NOT_PUBLISHED",
        "experiment": "EX038_20261019",
        "design_path": relative(design_path),
        "design_sha256": digest(design_path),
        "script_sha256": digest(Path(__file__)),
        "classification_boundary_checks": boundary_checks,
        "interfaces_total": len(endpoints),
        "interfaces_tested": sum(row["mcp_calls_recorded"] > 0 for row in inventory),
        "interfaces_untested": [
            row["endpoint"] for row in inventory if not row["mcp_calls_recorded"]
        ],
        "mcp_budget": {
            "cap": cap,
            "recorded_call_files": len(calls),
            "recorded_unique_integer_ids": len(set(ids)),
            "highest_call_id": maximum,
            "missing_ids_to_highest": sorted(set(range(1, maximum + 1)) - set(ids)),
            "duplicate_call_ids": [i for i, n in Counter(ids).items() if n > 1],
            "remaining_by_recorded_files": cap - len(calls),
            "cap_exceeded_by_recorded_files": len(calls) > cap,
            "http_request_count": None,
            "http_count_note": "MCP invocation records do not establish upstream HTTP request count",
        },
        "call_status_counts": dict(Counter(row["status"] for row in calls)),
        "interfaces": inventory,
        "calls": calls,
        "unknown_endpoints_outside_protocol": sorted(
            {row["endpoint"] for row in calls} - set(endpoints)
        ),
        "limitations": [
            "Saved MCP JSON objects are not claimed exact transport bytes; initial same-thread imported object retains its provenance",
            "Automatic approval timeout is not evidence that the action is unsafe or the vendor account lacks permission",
            "Empty returns and point requirements do not prove account permission status",
            "Plain-text/unrecognized successful formats remain pending manual review",
            "No full historical coverage, immutable data preparation, signal efficacy, future returns or strict historical arrival certified by this inventory",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": relative(output),
                "calls": len(calls),
                "highest_call_id": maximum,
                "interfaces_tested": result["interfaces_tested"],
                "interfaces_untested": len(result["interfaces_untested"]),
                "statuses": result["call_status_counts"],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
