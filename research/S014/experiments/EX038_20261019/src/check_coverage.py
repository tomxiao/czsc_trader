"""Offline checks for the frozen 41-call EX038 census; no research labels."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import socket

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/S014/experiments/EX036_20261019/others"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def blocked(*_args, **_kwargs):
    raise RuntimeError("Frozen EX038 coverage check: no network permitted")


def table(call):
    texts = [b["text"] for b in call["result"]["content"] if b["type"] == "text"]
    if len(texts) != 1:
        raise ValueError("Expected exactly one preserved response text")
    try:
        rows = json.loads(texts[0])
    except json.JSONDecodeError:
        return None
    return rows if isinstance(rows, list) else None


def independent_status(call):
    text = "\n".join(
        b.get("text", "") for b in call["result"]["content"] if b.get("type") == "text"
    )
    low = text.lower()
    if re.search(r"automatic(?:\s+permission)?\s+approval\s+review", low):
        if any(word in low for word in ("deadline", "timed out", "timeout", "did not finish")):
            return "AUTOMATIC_APPROVAL_TIMEOUT"
        if "failed" in low or "action was not executed" in low:
            return "AUTOMATIC_APPROVAL_FAILURE"
        if "rejected" in low or "denied" in low:
            return "AUTOMATIC_APPROVAL_REJECTED"
    if "tushare" in low and "[40203]" in text:
        return "PROVIDER_PERMISSION_DENIED"
    if call["result"].get("isError"):
        return "OTHER_TECHNICAL_FAILURE"
    rows = table(call)
    return (
        "SUCCESS_NONEMPTY"
        if rows
        else "EMPTY_RETURN_PERMISSION_UNRESOLVED"
        if rows == []
        else "UNKNOWN_FORMAT_MANUAL_REVIEW"
    )


def iso(value):
    return datetime.strptime(str(value), "%Y%m%d").strftime("%Y-%m-%d")


def keyed(rows):
    identities = [(r["ts_code"], str(r["trade_date"])) for r in rows]
    assert len(identities) == len(set(identities)), "Duplicate symbol/date rows"
    return dict(zip(identities, rows, strict=True))


def field_counts(rows, field):
    vals = [Decimal(str(row[field])) for row in rows if row.get(field) is not None]
    finite = [v for v in vals if v.is_finite()]
    return {
        "zero": sum(v == 0 for v in finite),
        "positive": sum(v > 0 for v in finite),
        "negative": sum(v < 0 for v in finite),
        "null_or_missing": len(rows) - len(vals),
        "nonfinite": len(vals) - len(finite),
    }


def main():
    output = EX / "others/coverage_checks.json"
    if output.exists():
        raise FileExistsError(
            "Existing frozen coverage evidence protected; use explicit successor revision"
        )
    socket.socket.connect = blocked
    socket.create_connection = blocked
    paths = sorted((EX / "others/calls").glob("*.json"))
    calls = {read(p)["id"]: read(p) for p in paths}
    assert len(paths) == len(calls) == 41 and sorted(calls) == list(range(1, 42))
    assert all(p.stem == f"{read(p)['id']:03d}" for p in paths)
    inventory_path = EX / "others/census_inventory.json"
    inventory = read(inventory_path)
    assert inventory["mcp_budget"]["recorded_call_files"] == 41
    by_inventory_id = {r["id"]: r for r in inventory["calls"]}
    for path in paths:
        call = read(path)
        item = by_inventory_id[call["id"]]
        assert item["saved_call_sha256"] == digest(path)
        assert item["status"] == independent_status(call)
    status_counts = Counter(independent_status(c) for c in calls.values())
    assert dict(status_counts) == inventory["call_status_counts"]
    call_manifest = [
        {
            "id": read(p)["id"],
            "endpoint": read(p)["endpoint"],
            "path": relative(p),
            "sha256": digest(p),
        }
        for p in paths
    ]
    # Same filename/hash canonicalization as the reviewed direct-probe dry-run;
    # this records a snapshot, never authorizes that independent method.
    snapshot = sha256(
        json.dumps(
            [(p.name, digest(p)) for p in paths],
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    cap = read(EX / "protocols/design.json")["budget"]["max_mcp_invocations"]
    assert len(calls) <= cap == 48

    share_segments = []
    for name, fund_id, size_id in [
        ("2020_anchor", 26, 28),
        ("2023_anchor", 27, 29),
        ("recent", 36, 37),
    ]:
        left, right = calls[fund_id], calls[size_id]
        assert left["endpoint"] == "fund_share" and right["endpoint"] == "etf_share_size"
        assert left["args"]["ts_code"] == right["args"]["ts_code"] == "510300.SH"
        assert all(left["args"][k] == right["args"][k] for k in ("start_date", "end_date"))
        a, b = keyed(table(left)), keyed(table(right))
        common = sorted(a.keys() & b.keys())
        differences = [
            {
                "date": iso(key[1]),
                "fund_share_fd_share": a[key]["fd_share"],
                "etf_share_size_total_share": b[key]["total_share"],
            }
            for key in common
            if Decimal(str(a[key]["fd_share"])) != Decimal(str(b[key]["total_share"]))
        ]
        residuals = [
            abs(
                Decimal(str(b[key]["total_size"]))
                - Decimal(str(b[key]["total_share"])) * Decimal(str(b[key]["nav"]))
            )
            for key in common
        ]
        share_segments.append(
            {
                "segment": name,
                "call_ids": [fund_id, size_id],
                "start": iso(left["args"]["start_date"]),
                "end": iso(left["args"]["end_date"]),
                "fund_share_rows": len(a),
                "etf_share_size_rows": len(b),
                "common_dates": [iso(key[1]) for key in common],
                "fund_only_dates": [iso(key[1]) for key in sorted(a.keys() - b.keys())],
                "size_only_dates": [iso(key[1]) for key in sorted(b.keys() - a.keys())],
                "share_value_mismatch_count": len(differences),
                "share_value_mismatches": differences,
                "native_size_minus_share_times_nav_max_absolute_residual": str(max(residuals))
                if residuals
                else None,
                "size_identity_note": "Provider-native numeric residual only; printed precision/units not independently certified and not used as an acceptance gate",
                "status": "PASS" if not differences and a.keys() == b.keys() else "MISMATCH",
            }
        )

    market_inputs_path = OLD / "market_inputs.json"
    calendar_identity = next(
        r for r in read(market_inputs_path)["native_identities"] if r["name"] == "calendar"
    )
    calendar_path = ROOT / calendar_identity["snapshot_path"]
    assert digest(calendar_path) == calendar_identity["snapshot_sha256"]
    calendar = pd.read_csv(calendar_path)
    assert len(calendar) == calendar_identity["rows"] and not calendar.Date.duplicated().any()
    expected = sorted(
        calendar.loc[
            calendar.IsOpen.eq(1) & calendar.Date.between("2026-09-01", "2026-10-15"), "Date"
        ].tolist()
    )
    recent = []
    for call_id in (36, 37, 38):
        c = calls[call_id]
        rows = keyed(table(c))
        observed = sorted(iso(key[1]) for key in rows)
        recent.append(
            {
                "call_id": call_id,
                "endpoint": c["endpoint"],
                "rows": len(rows),
                "expected_exchange_sessions": len(expected),
                "missing_sessions": sorted(set(expected) - set(observed)),
                "unexpected_dates": sorted(set(observed) - set(expected)),
                "duplicate_symbol_date_keys": 0,
                "status": "PASS" if observed == expected else "MISMATCH",
            }
        )
    daily, size = keyed(table(calls[38])), keyed(table(calls[37]))
    close_mismatches = [
        iso(key[1])
        for key in daily.keys() & size.keys()
        if Decimal(str(daily[key]["close"])) != Decimal(str(size[key]["close"]))
    ]

    option_anchors = []
    for call_id in (33, 34, 30, 31, 35, 7):
        call = calls[call_id]
        all_rows = table(call)
        assert call["endpoint"] == "opt_daily"
        assert all(str(r["trade_date"]) == call["args"]["trade_date"] for r in all_rows)
        keyed(all_rows)
        rows = (
            [r for r in all_rows if r["ts_code"].startswith("MA")]
            if call["args"]["exchange"] == "CZCE"
            else all_rows
        )
        option_anchors.append(
            {
                "call_id": call_id,
                "exchange": call["args"]["exchange"],
                "trade_date": iso(call["args"]["trade_date"]),
                "selection": "ts_code starts MA within returned CZCE option rows"
                if call["args"]["exchange"] == "CZCE"
                else "all returned SSE option rows",
                "total_exchange_rows": len(all_rows),
                "selected_rows": len(rows),
                "vol": field_counts(rows, "vol"),
                "close": field_counts(rows, "close"),
                "oi": field_counts(rows, "oi"),
                "zero_volume_and_zero_close": sum(
                    all(
                        r.get(field) is not None
                        and Decimal(str(r[field])).is_finite()
                        and Decimal(str(r[field])) == 0
                        for field in ("vol", "close")
                    )
                    for r in rows
                ),
                "identity_limit": "Returned daily observations only; not independent full contract-universe or whole-window certification",
            }
        )

    success, denied, unresolved = [], [], []
    for endpoint in [r["endpoint"] for r in inventory["interfaces"]]:
        statuses = {independent_status(c) for c in calls.values() if c["endpoint"] == endpoint}
        if "SUCCESS_NONEMPTY" in statuses:
            success.append(endpoint)
        elif "PROVIDER_PERMISSION_DENIED" in statuses:
            denied.append(endpoint)
        else:
            unresolved.append(endpoint)
    assert len(success) + len(denied) + len(unresolved) == inventory["interfaces_total"]
    issues = [
        name
        for name, ok in [
            ("share consistency", all(s["status"] == "PASS" for s in share_segments)),
            ("recent exchange session coverage", all(s["status"] == "PASS" for s in recent)),
            ("recent daily close consistency", not close_mismatches),
        ]
        if not ok
    ]
    result = {
        "status": "PASS" if not issues else "REVIEW_MISMATCHES",
        "experiment": "EX038_20261019",
        "issues": issues,
        "snapshot": {
            "frozen_mcp_calls": 41,
            "highest_call_id": 41,
            "unique_contiguous_ids_1_through_41": True,
            "summary_sha256": snapshot,
            "summary_hash_algorithm": "sha256(json.dumps([(filename,sha256(saved_file_bytes)),...],ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')); filenames sorted",
            "budget_cap": cap,
            "unused_invocations_not_authorization_to_use": cap - len(calls),
            "http_requests": None,
            "first_call_provenance": calls[1].get("provenance"),
            "exact_wire_bytes_claimed": False,
        },
        "call_status_counts_independently_verified": dict(status_counts),
        "interface_capability_counts": {
            "nonempty_response_observed": len(success),
            "explicit_provider_denial": len(denied),
            "unresolved": len(unresolved),
        },
        "interfaces": {
            "nonempty_response_observed": success,
            "explicit_provider_denial": denied,
            "unresolved": unresolved,
        },
        "share_endpoint_consistency": share_segments,
        "share_independence_limit": "fund_share and etf_share_size are two interfaces to the same vendor; matching values are not independent-source replication or separate alpha information",
        "recent_three_interface_calendar_check": {
            "window": ["2026-09-01", "2026-10-15"],
            "expected_sessions": expected,
            "calendar_source": calendar_identity,
            "calendar_path": relative(calendar_path),
            "calendar_sha256": digest(calendar_path),
            "checks": recent,
            "daily_vs_size_close_mismatch_dates": close_mismatches,
            "scope": "Reused existing pinned EX036 SSE calendar identity; no new calendar fetch; certifies this segment's observed dates only",
        },
        "option_daily_anchors": option_anchors,
        "call_manifest": call_manifest,
        "source_bindings": [
            {"path": relative(p), "sha256": digest(p)}
            for p in [
                EX / "protocols/design.json",
                inventory_path,
                market_inputs_path,
                calendar_path,
                Path(__file__),
            ]
        ],
        "new_upstream_calls": 0,
        "new_labels": 0,
        "new_model_fits": 0,
        "new_accounts": 0,
        "limitations": [
            "Single dates and short segments do not certify 2020-2026 whole-window history",
            "Current identity/PCF rows do not establish historical constituents or actual daily portfolio trades",
            "Zero volume/close rows must not be treated as active executable option prices",
            "Availability, vendor permission and signal usefulness remain separate judgments",
            "No private credentials read and no live/public DFLS acquisition called",
        ],
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "calls": 41,
                "capability": result["interface_capability_counts"],
                "calendar_sessions_recent": len(expected),
                "share_segments": [
                    (s["segment"], s["fund_share_rows"], s["status"]) for s in share_segments
                ],
                "option_selected_rows": [
                    (
                        a["exchange"],
                        a["trade_date"],
                        a["selected_rows"],
                        a["vol"]["zero"],
                        a["close"]["zero"],
                    )
                    for a in option_anchors
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
