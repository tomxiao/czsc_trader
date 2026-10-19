"""Locked disclosure-state description of saved account outcomes; never a trading replay.

--synthetic-check reads no research inputs. Real execution requires five published
S014 EvidenceRefs in --lock: source, design, panel, events, coverage.
"""
import argparse
import bisect
import csv
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
EVENTS_SHA = "01fc106f518f875808500493282c29856e2d006dd42db52d5563abb26569c5bc"
COVERAGE_SHA = "3640472a82e6eee59b747b3bdfa115c59539885dd028177751a144b4d3d1ff15"
DESIGN_SHA = "17c254369b87ea1fff802a9fa17e7ebf65004e87be9ed5fef938992c2ebbc4c8"
STATES = tuple(f"{outside}__STOCK_{stock}" for outside in
               ("COMMON_UP", "COMMON_NONUP", "DIVERGENT") for stock in ("UP", "NONUP"))
POSTURES = ("PLAN_BUY", "PLAN_SELL", "HOLD", "FLAT")
PRIMARY = ("PLAN_BUY", "HOLD")
METRICS = ("actual_daily_return", "buyhold_daily_return", "active_log_return")
NUMERIC = (*METRICS, "actual_pnl", "annual_open_equity", "annual_return_contribution")


def require(value, message):
    if not value:
        raise ValueError(message)


def day(value):
    return datetime.fromisoformat(str(value)).date().isoformat()


def published(value, expected=None):
    from czsc_trader.research_tools import EvidenceRef

    ref = EvidenceRef.from_dict(value)
    require(ref.experiment.strategy_id == "S014", "Only S014 evidence allowed")
    if expected is not None:
        require(ref.sha256 == expected, "Wrong fixed source SHA")
    raw = ref.resolve(ROOT).read_bytes()
    require(sha256(raw).hexdigest() == ref.sha256, "Published bytes differ")
    return raw, ref.to_dict()


def title_match(title):
    return ("股票交易" in title and ("异常波动" in title or "风险提示" in title)
            and "回复" not in title)


def notice_windows(events, sessions, real=True):
    require(len(sessions) == len(set(sessions)) and sessions == sorted(sessions),
            "Stock sessions must be unique ascending")
    require(len({e["doc_id"] for e in events}) == len(events), "Duplicate official IDs")
    require(len({e["publication_date"] for e in events}) == len(events),
            "Duplicate notice dates violate locked inventory")
    if real:
        require(len(events) == 14, "Locked inventory requires14 documents")
    windows = []
    for event in sorted(events, key=lambda e: (e["publication_date"], e["doc_id"])):
        publication = day(event["publication_date"])
        require(title_match(event["title"]), "Title outside fixed rule")
        require("2020-01-01" <= publication <= "2025-12-31", "Notice outside complete domain")
        start = bisect.bisect_right(sessions, publication)
        require(start + 1 < len(sessions), "Notice availability/execution outside calendar")
        require(event["availability"]["decision_date_15_00"] == sessions[start],
                "Notice conservative available date differs")
        require(event["availability"]["earliest_execution_date"] == sessions[start + 1],
                "Notice conservative execution date differs")
        windows.append({"doc_id": event["doc_id"], "publication_date": publication,
                        "available_D": sessions[start], "earliest_execution_E": sessions[start + 1],
                        "start_D_index": start, "end_D_index": start + 9,
                        "last_active_D": sessions[start + 9] if start + 9 < len(sessions) else None})
    # Merge intersecting closed windows only; adjacency without shared D is separate.
    episodes = []
    for window in windows:
        if episodes and window["start_D_index"] <= episodes[-1]["end_D_index"]:
            episodes[-1]["end_D_index"] = max(episodes[-1]["end_D_index"], window["end_D_index"])
            episodes[-1]["doc_ids"].append(window["doc_id"])
        else:
            episodes.append({"episode_id": len(episodes) + 1,
                             "start_D_index": window["start_D_index"],
                             "end_D_index": window["end_D_index"], "doc_ids": [window["doc_id"]]})
    for episode in episodes:
        episode["first_available_D"] = sessions[episode["start_D_index"]]
        end = episode["end_D_index"]
        episode["last_active_D"] = sessions[end] if end < len(sessions) else None
    return windows, episodes


def add_warning_state(panel, windows, episodes):
    sessions = [row["date"] for row in panel]
    indices = {d: i for i, d in enumerate(sessions)}
    output = []
    for i, source in enumerate(panel):
        row = dict(source)
        d = row["D_signal_date"]
        require(not d or d < row["date"], "D must precede E")
        if i:
            require(d == sessions[i - 1], "D is not exact previous pinned stock session")
        index = indices.get(d)
        active = [] if index is None else [w for w in windows
                    if w["start_D_index"] <= index <= w["end_D_index"]]
        if row["year"] > 2025 or row["year"] < 2020:
            state = "OUT_OF_DOMAIN"
        elif index is None or index < 9:
            state = "UNKNOWN"
        else:
            state = "W1" if active else "W0"
        matched = [e for e in episodes if index is not None
                   and e["start_D_index"] <= index <= e["end_D_index"]]
        require(len(matched) <= 1, "Time-only episodes overlap after union")
        row.update(W_state=state, W_eligible=state in ("W0", "W1"),
                   D_session_index=index, active_notice_count=len(active),
                   active_notice_ids="|".join(w["doc_id"] for w in active),
                   active_notice_publication_dates="|".join(w["publication_date"] for w in active),
                   active_notice_available_dates="|".join(w["available_D"] for w in active),
                   original_time_episode_id=matched[0]["episode_id"] if matched else None)
        output.append(row)
    return output


def group(rows, annual):
    n = len(rows)
    return {"n": n, "means": {m: math.fsum(r[m] for r in rows) / n if n else None for m in METRICS},
            "observed_actual_pnl_sum": math.fsum(r["actual_pnl"] for r in rows),
            "observed_annual_contribution_pp": 100 * math.fsum(r["annual_return_contribution"] for r in rows)
                if annual else None,
            "annual_contribution_status": "SAME_ORIGINAL_YEAR_DENOMINATOR" if annual
                else "NOT_SUMMED_ACROSS_DIFFERENT_YEAR_OPENING_DENOMINATORS",
            "planned_buy_decisions": sum(r["D_posture"] == "PLAN_BUY" for r in rows),
            "original_buy_fill_days": sum(r["D_posture"] == "PLAN_BUY" and r["phase"] == "ENTRY" for r in rows),
            "original_buy_unfilled_days": sum(r["D_posture"] == "PLAN_BUY" and r["phase"] != "ENTRY" for r in rows)}


def difference(g0, g1):
    return {m: g1["means"][m] - g0["means"][m] if g0["n"] and g1["n"] else None
            for m in METRICS}


def scope_summary(rows, scope, fixed_weights=None):
    annual = scope != "ALL2020_2025"
    raw = []
    cells = []
    weights = {} if fixed_weights is None else dict(fixed_weights)
    for posture in POSTURES:
        subset = [r for r in rows if r["D_posture"] == posture]
        a = group([r for r in subset if r["W_state"] == "W0"], annual)
        b = group([r for r in subset if r["W_state"] == "W1"], annual)
        raw.append({"D_posture": posture, "primary_population": posture in PRIMARY,
                    "W0": a, "W1": b, "W1_minus_W0": difference(a, b)})
        for state in (*STATES, "UNKNOWN"):
            subset_cell = [r for r in subset if r["D_state"] == state]
            a = group([r for r in subset_cell if r["W_state"] == "W0"], annual)
            b = group([r for r in subset_cell if r["W_state"] == "W1"], annual)
            key = f"{posture}|{state}"
            if fixed_weights is None:
                weights[key] = min(a["n"], b["n"]) if state != "UNKNOWN" and posture in PRIMARY else 0
            weight = weights[key]
            status = "ORIGINAL_COMMON_CELL_SUPPORTED" if weight and a["n"] and b["n"] else (
                "MISSING_ORIGINAL_REQUIRED_GROUP" if weight else "ORIGINAL_UNSUPPORTED_OR_NOT_PRIMARY")
            cells.append({"D_posture": posture, "D_state": state,
                          "original_min_count_weight": weight, "support": status,
                          "W0": a, "W1": b, "W1_minus_W0": difference(a, b)})
    adjusted = []
    for posture_set in [(p,) for p in PRIMARY] + [PRIMARY]:
        required = [c for c in cells if c["D_posture"] in posture_set and c["original_min_count_weight"] > 0]
        missing = [f'{c["D_posture"]}|{c["D_state"]}' for c in required
                   if not c["W0"]["n"] or not c["W1"]["n"]]
        denominator = sum(c["original_min_count_weight"] for c in required)
        supported = denominator > 0 and not missing
        adjusted.append({"D_postures": list(posture_set), "original_common_weight": denominator,
                         "original_required_cells": len(required), "missing_original_required_cells": missing,
                         "status": "AVAILABLE" if supported else "MISSING_FIXED_GROUP" if missing else "NO_COMMON_SUPPORT",
                         "W1_minus_W0": {m: math.fsum(c["original_min_count_weight"] * c["W1_minus_W0"][m]
                                                     for c in required) / denominator if supported else None
                                              for m in METRICS}})
    return {"scope": scope, "raw_by_posture": raw, "all_state_posture_cells": cells,
            "fixed_common_cell_contrasts": adjusted}, weights


def analyze(rows, episodes):
    eligible = [r for r in rows if r["W_eligible"]]
    scope_names = ["ALL2020_2025", *(str(year) for year in range(2020, 2026))]
    scopes, originals = {}, {}
    for name in scope_names:
        subset = eligible if name == "ALL2020_2025" else [r for r in eligible if r["year"] == int(name)]
        scopes[name], originals[name] = scope_summary(subset, name)
    deletions = []
    for episode in episodes:
        episode_id = episode["episode_id"]
        retained = [r for r in eligible if not (r["W_state"] == "W1"
                    and r["original_time_episode_id"] == episode_id)]
        result = {"episode_id": episode_id, "deleted_original_W1_rows": len(eligible) - len(retained),
                  "scopes": {}}
        for name in scope_names:
            subset = retained if name == "ALL2020_2025" else [r for r in retained if r["year"] == int(name)]
            result["scopes"][name], _ = scope_summary(subset, name, originals[name])
        deletions.append(result)
    status_counts = [{"year": year, "D_posture": posture, "W_state": state,
                      "n": sum(r["year"] == year and r["D_posture"] == posture and r["W_state"] == state for r in rows)}
                     for year in sorted({r["year"] for r in rows}) for posture in POSTURES
                     for state in ("W0", "W1", "UNKNOWN", "OUT_OF_DOMAIN")]
    return {"scopes": scopes, "status_population_counts": status_counts,
            "leave_one_original_time_episode_out": deletions,
            "fixed_cell_policy": "Preserve each original scope's required six-state/primary-posture cells and min(n0,n1) weights; any lost required group makes whole contrast null; never reselect"}


def validate_coverage(coverage, events):
    require(coverage["complete_2020_2025_leaf_count"] == 30
            and coverage["scope_is_all_issuer_announcement_classes"] is True,
            "Incomplete fixed official catalogue")
    records = {}
    leaf_refs = []
    for proof in coverage["leaf_proofs"]:
        raw, ref = published(proof["original_evidence_ref"])
        request_raw, request_ref = published(proof["request_original_evidence_ref"])
        body, request = json.loads(raw), json.loads(request_raw)
        params = request["params"]
        require(params == proof["query_params"], "Original query params differ")
        require(params["category"] == params["searchkey"] == ""
                and params["stock"] == "600722,gssh0600722", "Query is not complete issuer classes")
        rows = body.get("announcements") or []
        require(proof["complete_within_current_source"] is True and body["hasMore"] is False
                and len(rows) == body["totalAnnouncement"] == proof["total"] == proof["rows"],
                "Truncated original date leaf")
        for record in rows:
            record_day = datetime.fromtimestamp(record["announcementTime"] / 1000, tz=timezone.utc).astimezone(
                timezone(timedelta(hours=8))).date().isoformat()
            require(record["secCode"] == "600722" and proof["start"] <= record_day <= proof["end"],
                    "Issuer or disclosure date outside original query")
            doc_id = record["announcementId"]
            require(doc_id not in records, "Overlapping/duplicate original date-leaf records")
            records[doc_id] = {"date": record_day, "title": record["announcementTitle"],
                               "url": "https://static.cninfo.com.cn/" + record["adjunctUrl"]}
        leaf_refs.append({"catalogue": ref, "request": request_ref})
    for year in range(2020, 2026):
        cursor = date(year, 1, 1)
        for proof in sorted((p for p in coverage["leaf_proofs"] if p["start"][:4] == str(year)), key=lambda p: p["start"]):
            require(date.fromisoformat(proof["start"]) == cursor, "Official date range gap")
            cursor = date.fromisoformat(proof["end"]) + timedelta(days=1)
        require(cursor == date(year + 1, 1, 1), "Incomplete original calendar-year catalogue")
    matched = {key for key, value in records.items() if title_match(value["title"])}
    require(matched == {e["doc_id"] for e in events} and len(matched) == 14,
            "Fixed title universe differs from original whole catalogue")
    for event in events:
        original = records[event["doc_id"]]
        require(original == {"date": event["publication_date"], "title": event["title"], "url": event["url"]},
                "Event changed original official date/title/URL")
    return {"records_verified": len(records), "original_date_leaf_refs": leaf_refs}


def load_inputs(lock_path):
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    require(set(lock) == {"source", "design", "panel", "events", "coverage"}, "Lock requires exactly five references")
    source, source_ref = published(lock["source"])
    require(source == Path(__file__).read_bytes(), "Running source differs from locked published bytes")
    design_raw, design_ref = published(lock["design"], DESIGN_SHA)
    design = json.loads(design_raw)
    require("fixed_official_warning_contrast" in design, "Warning design missing")
    panel_raw, panel_ref = published(lock["panel"])
    event_raw, event_ref = published(lock["events"], EVENTS_SHA)
    coverage_raw, coverage_ref = published(lock["coverage"], COVERAGE_SHA)
    events = json.loads(event_raw)["events"]
    audit = validate_coverage(json.loads(coverage_raw), events)
    reader = csv.DictReader(StringIO(panel_raw.decode("utf-8")))
    required = ("date", "D_signal_date", "D_state", "D_posture", "phase", "year", "month", *NUMERIC)
    require(set(required) <= set(reader.fieldnames or []), "Panel schema missing declared fields")
    panel = []
    for raw in reader:
        row = {key: raw[key] for key in required}
        row["date"] = day(row["date"])
        row["D_signal_date"] = day(row["D_signal_date"]) if row["D_signal_date"] else ""
        row["year"] = int(row["year"])
        require(row["year"] == int(row["date"][:4]) and row["month"] == row["date"][:7], "Year/month identity differs")
        require(row["D_state"] in (*STATES, "UNKNOWN") and row["D_posture"] in POSTURES, "Unknown panel classification")
        require(row["phase"] in ("ENTRY", "HOLD", "EXIT", "FLAT"), "Unknown original fill phase")
        for key in NUMERIC:
            row[key] = float(row[key])
            require(math.isfinite(row[key]), "Missing/nonfinite original economic field")
        require(row["actual_daily_return"] > -1 and row["buyhold_daily_return"] > -1
                and row["annual_open_equity"] > 0, "Invalid original NAV return/equity")
        require(abs(math.log1p(row["actual_daily_return"]) - math.log1p(row["buyhold_daily_return"])
                    - row["active_log_return"]) < 1e-10, "Original active-log identity differs")
        require(abs(row["actual_pnl"] / row["annual_open_equity"] - row["annual_return_contribution"]) < 1e-10,
                "Original annual contribution identity differs")
        panel.append(row)
    sessions = [row["date"] for row in panel]
    require(len(panel) == 1642 and sessions[0] == "2020-01-02" and sessions[-1] == "2026-10-15",
            "Wrong fixed panel calendar domain")
    windows, episodes = notice_windows(events, sessions)
    refs = {"source": source_ref, "design": design_ref, "panel": panel_ref,
            "events": event_ref, "coverage": coverage_ref}
    return panel, windows, episodes, refs, audit


def synthetic_check():
    # Explicit holiday jump, not a weekday-generated substitute for real stock sessions.
    sessions = ["2021-02-08", "2021-02-09", "2021-02-10", "2021-02-18", "2021-02-19",
                "2021-02-22", "2021-02-23", "2021-02-24", "2021-02-25", "2021-02-26",
                "2021-03-01", "2021-03-02", "2021-03-03", "2021-03-04", "2021-03-05",
                "2021-03-08", "2021-03-09"]
    event = {"doc_id": "SYNTHETIC", "title": "股票交易异常波动公告", "publication_date": "2021-02-10",
             "availability": {"decision_date_15_00": "2021-02-18", "earliest_execution_date": "2021-02-19"}}
    windows, episodes = notice_windows([event], sessions, real=False)
    require(windows[0]["start_D_index"] == 3 and windows[0]["end_D_index"] == 12, "Holiday/strict-after window differs")
    panel = [{"date": d, "D_signal_date": sessions[i-1] if i else "", "year": 2021,
              "D_state": STATES[0], "D_posture": "HOLD", "phase": "HOLD",
              **{m: .01 for m in METRICS}, "actual_pnl": 1., "annual_open_equity": 100.,
              "annual_return_contribution": .01} for i, d in enumerate(sessions)]
    rows = add_warning_state(panel, windows, episodes)
    require(all(r["W_state"] == "UNKNOWN" for r in rows[:10]), "First nine in-window D or missing D became W0")
    require(rows[13]["D_session_index"] == 12 and rows[13]["W_state"] == "W1", "Inclusive D+9 boundary omitted")
    require(rows[14]["D_session_index"] == 13 and rows[14]["W_state"] == "W0", "D+10 boundary retained")
    late = dict(panel[-1], date="2026-01-05", D_signal_date=sessions[-1], year=2026)
    require(add_warning_state(panel+[late], windows, episodes)[-1]["W_state"] == "OUT_OF_DOMAIN", "2026 became W0")
    duplicate = dict(event)
    try:
        notice_windows([event, duplicate], sessions, real=False)
    except ValueError:
        pass
    else:
        raise ValueError("Duplicate official event accepted")
    future_notice = dict(event, doc_id="AFTER", publication_date=sessions[14],
                         availability={"decision_date_15_00": sessions[15], "earliest_execution_date": sessions[16]})
    w2, e2 = notice_windows([future_notice], sessions, real=False)
    require(add_warning_state(panel, w2, e2)[14]["W_state"] == "W0", "Outcome-day disclosure leaked into D")
    adjacent = dict(event, doc_id="ADJACENT", publication_date=sessions[12],
                    availability={"decision_date_15_00": sessions[13], "earliest_execution_date": sessions[14]})
    _, adjacent_episodes = notice_windows([event, adjacent], sessions, real=False)
    require(len(adjacent_episodes) == 2, "Adjacent nonoverlapping windows incorrectly merged")
    overlap = dict(event, doc_id="OVERLAP", publication_date=sessions[11],
                   availability={"decision_date_15_00": sessions[12], "earliest_execution_date": sessions[13]})
    _, merged = notice_windows([event, overlap], sessions, real=False)
    require(len(merged) == 1, "Inclusive overlap not transitively joined")
    comparison = []
    for state in STATES[:2]:
        for warning, value in [("W0", 0.), ("W1", .02)]:
            comparison.append(dict(panel[0], D_state=state, W_state=warning, W_eligible=True,
                                   actual_daily_return=value, original_time_episode_id=1 if warning == "W1" else None))
    base, weights = scope_summary(comparison, "ALL2020_2025")
    require(base["fixed_common_cell_contrasts"][1]["W1_minus_W0"]["actual_daily_return"] == .02, "Fixed weighted contrast differs")
    deleted, after_weights = scope_summary(comparison[:-1], "ALL2020_2025", weights)
    require(after_weights == weights and deleted["fixed_common_cell_contrasts"][1]["status"] == "MISSING_FIXED_GROUP"
            and deleted["fixed_common_cell_contrasts"][1]["W1_minus_W0"]["actual_daily_return"] is None,
            "Deletion reselected fixed cells or suppressed missing group")
    require(base["raw_by_posture"][2]["W1"]["observed_annual_contribution_pp"] is None,
            "Pooled annual denominators were summed")
    annual, _ = scope_summary(comparison, "2021")
    require(annual["raw_by_posture"][2]["W1"]["observed_annual_contribution_pp"] == 2., "Same-year contribution omitted")
    result = analyze(comparison, [{"episode_id": 1}])
    require(result["leave_one_original_time_episode_out"][0]["deleted_original_W1_rows"] == 2,
            "Episode deletion did not remove all original W1 rows")
    checks = ["strict next-stock-session holiday clock", "explicit next execution clock", "inclusive D+9 and excluded D+10",
              "missing/incomplete initial D remains UNKNOWN", "2026 OUT_OF_DOMAIN", "outcome-day disclosure cannot affect D",
              "duplicate events rejected", "overlapping windows union and adjacency distinction", "fixed six-state/posture means",
              "missing original required group null", "episode deletion preserves original weights/cells",
              "entire original W1 episode deleted", "pooled annual contribution withheld", "same-year annual contribution retained"]
    print(json.dumps({"status": "PASS_SYNTHETIC_ONLY", "checks": checks,
                      "real_research_inputs_read": False, "real_W_or_outcomes_joined": False,
                      "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--synthetic-check", action="store_true")
    args = parser.parse_args()
    if args.synthetic_check:
        require(args.lock is None, "Synthetic checks cannot read real lock")
        synthetic_check()
        return
    require(args.lock is not None, "Published source/design/panel/events/coverage lock required")
    row_path, result_path = OUT/"warning_state_rows.csv", OUT/"warning_state_results.json"
    require(not row_path.exists() and not result_path.exists(), "Preserve existing outputs; rerun prohibited")
    panel, windows, episodes, refs, audit = load_inputs(args.lock)
    rows = add_warning_state(panel, windows, episodes)
    result = {"status": "COMPLETE_FIXED_OBSERVED_DISCLOSURE_STATE_ONLY", "source_references": refs,
              "source_coverage_audit": audit, "notice_windows": windows, "time_only_original_episodes": episodes,
              "primary_outcome": "Observed next-E original account daily NAV return, PLAN_BUY/HOLD separately",
              "secondary_outcomes": "Original same-E benchmark daily NAV return, active-log return and original fill counts",
              "W_clock": "Original official catalogue date -> strictly later pinned stock session close; trailing0..9 D sessions; first9 D unknown;2026 outside domain",
              "deletion": "Remove only original W1 rows belonging to one whole fixed time episode; preserve all original fixed common cells and weights",
              "limits": ["Date-only conservative availability, not authenticated first public/vendor arrival",
                         "Disclosure marks abnormal trading or risk warning, not uniformly negative news or future reversal",
                         "All history seen,2025 June company text reviewed before adaptive design; not untouched validation",
                         "Observed outcomes depend on original policy and realized fills; no cancel-order/sell action value or filtered account",
                         "Common price states/postures do not balance years, holding age or floating PnL",
                         "Annual contribution only reported within the same original year; pooled pp sums withheld",
                         "No bootstrap or automatic component/account acceptance"],
              "resources": {"new_source_calls": 0, "new_fits": 0, "new_return_labels": 0, "new_accounts": 0},
              **analyze(rows, episodes)}
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    row_bytes = buffer.getvalue().encode("utf-8")
    result["rows_sha256"] = sha256(row_bytes).hexdigest()
    json_bytes = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8")
    with row_path.open("xb") as f:
        f.write(row_bytes)
    with result_path.open("xb") as f:
        f.write(json_bytes)
    print(json.dumps({"status": result["status"], "rows": len(rows), "rows_sha256": result["rows_sha256"],
                      "results_sha256": sha256(json_bytes).hexdigest()}))


if __name__ == "__main__":
    def blocked(*args, **kwargs):
        raise RuntimeError("Network/source calls prohibited")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    main()
