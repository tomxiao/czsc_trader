"""Independent offline audit of EX037 sources, coverage and classifications.

Does not import the collector, coverage_before, information_math or classifier.
First-news execution verification is bound to the separate independent audit.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
from pathlib import Path
import socket

import numpy as np
import pandas as pd
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/S014/experiments/EX036_20261019"
READY = ROOT / "research/S014/materials/20261019_financial_readiness"
OUT = EX / "others"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def compact(text):
    return re.sub(r"\s+", "", text)


def days(start, end):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def chinese_number(text):
    digits = dict(zip("零一二三四五六七八九", range(10), strict=True))
    for zero in ("〇", "○", "◯", "Ｏ", "0"):
        text = text.replace(zero, "零")
    if "十" in text:
        left, right = text.split("十")
        return (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    return int("".join(str(digits[letter]) for letter in text))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-unpublished-review", action="store_true")
    args = parser.parse_args()
    def blocked(*_args, **_kwargs):
        raise RuntimeError("Independent EX037 audit is strictly offline")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    target = OUT / "independent_review.json"
    if target.exists() and not args.refresh_unpublished_review:
        raise FileExistsError("Preserve the existing independent review")
    checks = Counter()
    bound_paths = {Path(__file__).resolve()}

    def verify(condition, label):
        if not condition:
            raise AssertionError(label)
        checks[label.split(":", 1)[0]] += 1

    def bind(path, expected=None):
        path = path.resolve()
        verify(path.is_relative_to(ROOT), "path_inside_repository")
        if expected is not None:
            verify(digest(path) == expected, "bound_file_sha256:" + path.name)
        bound_paths.add(path)

    for name in ("design", "retrieval_amendment", "coverage_interpretation"):
        path = EX / f"protocols/{name}.json"
        publication = EX / f"protocols/published_{name}.json"
        published = read(publication)
        verify(path.relative_to(ROOT).as_posix() in published, "protocol_publication_exists")
        bind(path, published[path.relative_to(ROOT).as_posix()]["sha256"])
        bind(publication)
    verify(digest(EX / "protocols/design.json") ==
           "6f9ac4596b9650ec9d42cfaa7ec25106a7e858904d78ecd2ae5efe5fb21608a1",
           "original_protocol_identity")
    design = read(EX / "protocols/design.json")
    verify(design["scope"]["model_fits"] == 0, "no_model_protocol")

    catalogue = read(OUT / "catalogue_audit_v3.json")
    receipts = sorted((OUT / "official/requests/catalogue").glob("*.request.json"))
    verify(len(receipts) == 64, "catalogue_request_budget")
    scopes = []
    raw_queries = {}
    keyword_complete = 0
    for request_path in receipts:
        request = read(request_path)
        result_path = request_path.with_name(request_path.name.replace(".request.", ".result."))
        result = read(result_path)
        bind(request_path)
        bind(result_path)
        verify(request["retry"] is False and request["allow_redirects"] is False,
               "no_retry_or_redirect")
        verify(result["status"] == "RECEIVED" and result["http_status"] == 200,
               "catalogue_response_received")
        raw_path = ROOT / result["raw_path"]
        bind(raw_path, result["sha256"])
        body = read(raw_path)
        records = body.get("announcements") or []
        params = request["params"]
        start, end = params["seDate"].split("~")
        ids = [r["announcementId"] for r in records]
        verify(len(ids) == len(set(ids)), "catalogue_unique_ids")
        verify(len(ids) == result["rows"] and body["totalAnnouncement"] == result["total"],
               "catalogue_row_and_total_counts")
        metadata = []
        for r in records:
            day = datetime.fromtimestamp(r["announcementTime"] / 1000,
                                         timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            verify(r["secCode"] == "600722" and r["orgId"] == "gssh0600722",
                   "catalogue_issuer")
            verify(start <= day <= end, "catalogue_actual_date_scope")
            metadata.append({"doc_id": r["announcementId"],
                             "title": re.sub("<[^>]+>", "", r["announcementTitle"]),
                             "publication_date": day,
                             "url": "https://static.cninfo.com.cn/" + r["adjunctUrl"]})
        complete = len(ids) == body["totalAnnouncement"] and not body["hasMore"]
        verify(complete == result["complete"], "catalogue_complete_recomputed")
        scope = {"name": request["name"], "start": start, "end": end,
                 "complete": complete, "rows": len(ids), "total": body["totalAnnouncement"],
                 "raw_path": result["raw_path"], "records": metadata}
        raw_queries[request["name"]] = scope
        if request["name"].startswith("full_"):
            verify(params["searchkey"] == "" and params["category"] == "",
                   "unfiltered_issuer_date_query")
            scopes.append(scope)
        if request["name"].startswith("keyword_"):
            verify(complete, "initial_keyword_complete")
            keyword_complete += 1
    verify(keyword_complete == 8 and len(scopes) == 48, "query_type_counts")
    # Derive final leaves from strict interval containment, not the saved list.
    leaves = [s for s in scopes if not any(
        t["start"] >= s["start"] and t["end"] <= s["end"] and
        (t["start"], t["end"]) != (s["start"], s["end"]) for t in scopes)]
    leaves.sort(key=lambda row: row["start"])
    verify(len(leaves) == 40, "derived_leaf_count")
    verify({r["name"] for r in leaves} == {r["name"] for r in catalogue["leaf_scopes"]},
           "saved_leaf_identity_matches_derived")
    coverage = {}
    records = {}
    for leaf in leaves:
        for day in days(leaf["start"], leaf["end"]):
            verify(day not in coverage, "disjoint_leaf_dates")
            coverage[day] = leaf
        for record in leaf["records"]:
            verify(record["doc_id"] not in records, "disjoint_leaf_document_ids")
            records[record["doc_id"]] = record
    verify(set(coverage) == set(days("2019-01-01", "2026-10-15")), "complete_requested_date_partition")
    bad = [leaf for leaf in leaves if not leaf["complete"]]
    verify(len(bad) == 1 and bad[0]["start"] == "2026-04-01" and
           bad[0]["end"] == "2026-04-23" and bad[0]["rows"] == 30 and
           bad[0]["total"] == 35, "single_unresolved_leaf")
    verify(sum(r["total"] for r in leaves) == 605 and
           sum(r["rows"] for r in leaves) == len(records) == 600, "leaf_expected605_actual600")
    verify(catalogue["complete"] is False and set(records) == set(catalogue["all_issuer_ids"]),
           "global_incomplete_and_actual_union")
    for saved in catalogue["all_issuer_records"]:
        verify(all(saved[k] == records[saved["doc_id"]][k] for k in
                   ("doc_id", "title", "publication_date", "url")), "saved_catalogue_metadata")

    guidance = read(OUT / "guidance_facts.json")
    facts = guidance["facts"]
    verify(len(facts) == 6, "six_guidance_documents")
    guidance_titles = {r["doc_id"] for r in records.values()
                       if "业绩" in r["title"] and "说明会" not in r["title"]}
    verify(guidance_titles == {f["doc_id"] for f in facts} == set(catalogue["guidance_ids"]),
           "independent_guidance_title_scan")
    extracted = []
    page_total = 0
    for fact in facts:
        meta = records[fact["doc_id"]]
        verify(all(fact[k] == meta[k] for k in ("title", "publication_date", "url")),
               "guidance_catalogue_binding")
        bind(ROOT / fact["pdf_path"], fact["pdf_sha256"])
        bind(ROOT / fact["text_path"], fact["text_sha256"])
        pdf_pages = [page.extract_text() or "" for page in PdfReader(ROOT / fact["pdf_path"]).pages]
        saved_pages = read(ROOT / fact["text_path"])["pages"]
        verify(len(pdf_pages) == len(saved_pages) == 2, "two_pages_per_guidance")
        for actual, saved in zip(pdf_pages, saved_pages, strict=True):
            verify(compact(actual) == compact(saved["text"]), "fresh_pdf_text_equivalence")
        page_total += len(pdf_pages)
        text = compact("".join(pdf_pages))
        verify("600722" in text and "河北金牛化工股份有限公司" in text, "guidance_original_issuer")
        period = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日至(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        verify(period is not None, "guidance_explicit_ytd_period")
        nums = list(map(int, period.groups()))
        begin, end = date(*nums[:3]).isoformat(), date(*nums[3:]).isoformat()
        verify(begin == fact["period_start"] and end == fact["period_end"] and
               end.replace("-", "") == fact["period"], "guidance_ytd_period_match")
        part = text.split("（二）业绩预告情况", 1)[1].split("（三）", 1)[0]
        matches = re.findall(r"归属于上市公司股东的净利润为([\d,]+(?:\.\d+)?)万元左右", part)
        verify(len(matches) == 1, "one_current_parent_profit_approximate_amount")
        printed = matches[0]
        amount = Decimal(printed.replace(",", "")) * 10000
        decimals = len(printed.split(".")[1]) if "." in printed else 0
        quantum = Decimal(10000) * Decimal(10) ** -decimals
        verify(amount == Decimal(fact["parent_profit_low_cny"]) == Decimal(fact["parent_profit_high_cny"]),
               "guidance_amount_yuan_conversion")
        verify(quantum == Decimal(fact["printed_quantum_low_cny"]) == Decimal(fact["printed_quantum_high_cny"]),
               "guidance_printed_quantum")
        verify(compact(fact["original_amount_text"]) == printed + "万元左右", "guidance_original_amount_text")
        signature = re.search(r"([二〇○◯Ｏ零一二三四五六七八九0]{4})年([一二三四五六七八九十]+)月([一二三四五六七八九十]+)日?$", text)
        verify(signature is not None, "guidance_signature_present")
        signed = date(*(chinese_number(v) for v in signature.groups())).isoformat()
        source = max(meta["publication_date"], signed)
        verify(signed == fact["signature_date"] and source == fact["source_day"], "guidance_source_day")
        verify(fact["approximate_point"] is True and fact["has_explicit_numeric_interval"] is False and
               fact["kind"] == "FORECAST" and fact["admission_status"] == "ADMITTED" and
               fact["accounting_scope"] == "PARENT_ATTRIBUTABLE_YTD" and not fact["replacement_doc_ids"],
               "guidance_point_not_hard_interval_or_express")
        extracted.append({"doc_id": fact["doc_id"], "period": end.replace("-", ""),
                          "source_day": source, "amount_cny": str(amount), "quantum_cny": str(quantum)})
    verify(page_total == 12, "twelve_original_pages")
    corrections = guidance["catalogue_completeness"]["correction_title_review"]
    candidates = {r["doc_id"] for r in records.values() if re.search("更正|澄清|补充|修正", r["title"])}
    verify(len(corrections) == 4 and {r["doc_id"] for r in corrections} == candidates,
           "all_four_correction_titles_reviewed")
    for row in corrections:
        verify(row["title"] == records[row["doc_id"]]["title"], "correction_title_identity")
        if row["doc_id"] == "1205873807":
            bind(ROOT / row["reused_pdf_path"], row["reused_pdf_sha256"])
            bind(ROOT / row["reused_text_path"], row["reused_text_sha256"])
            body = compact("".join(p.extract_text() or "" for p in PdfReader(ROOT / row["reused_pdf_path"]).pages))
            verify("实收资本" in body and "资本公积" in body and "其他内容不变" in body and
                   row["decision"] == "NOT_GUIDANCE_REPLACEMENT", "annual_correction_not_guidance")
        else:
            verify(re.search("股份转让|补充法律意见", row["title"]) is not None and
                   row["decision"] == "EXCLUDED_BY_EXPLICIT_NON_FINANCIAL_SUBJECT",
                   "nonfinancial_correction_title_exclusion")

    accepted = read(READY / "others/accepted_financial_inputs.json")
    accepted_facts = {(f["kind"], f["period"], f["field"]): f for f in accepted["facts"]}
    formal = read(OUT / "formal_report_ledger.json")
    ledger = read(OUT / "report_information_ledger.json")
    results = read(OUT / "information_results.json")
    reports = {r["period"]: r for r in ledger["reports"]}
    verify(len(reports) == len(formal["reports"]) == 27, "all27_report_rows_retained")
    for binding in formal["input_bindings"] + formal["verified_original_files"]:
        bind(ROOT / binding["path"], binding["sha256"])
    cal_data = read(READY / "upstream/responses/trade_cal.json")
    calendar = pd.DataFrame(cal_data["items"], columns=cal_data["fields"])
    open_days = sorted(pd.to_datetime(calendar.loc[calendar.is_open.astype(int).eq(1), "cal_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"))
    def next_session(day):
        return next(d for d in open_days if d > day)
    derived = []
    unknown_periods = []
    clusters = defaultdict(list)
    for f in extracted:
        f["decision_date"] = next_session(f["source_day"])
    prefix_summaries = []
    for row in formal["reports"]:
        period = row["period"]
        saved = reports[period]
        actual = accepted_facts["income", period, "n_income_attr_p"]
        verify(Decimal(row["formal_parent_ytd_cny"]) == Decimal(str(actual["value"])) and
               row["formal_fact"]["eligible_observation_ids"] == actual["eligible_observation_ids"],
               "formal_ytd_amount_and_admitted_records")
        verify(row["source_day"] == actual["effective_date_anchor"] and
               row["decision_date"] == next_session(row["source_day"]) and
               row["entry_date"] == next_session(row["decision_date"]), "formal_strict_session_clock")
        prior = str(int(period[:4]) - 1) + period[4:]
        verify(row["prior_year_period"] == prior, "same_period_prior_year_scale")
        for kind, field, key in [("income", "n_income_attr_p", "prior_year_parent_ytd_cny"),
                                 ("balancesheet", "total_assets", "prior_year_total_assets_cny")]:
            fact = accepted_facts[kind, prior, field]
            verify(Decimal(row[key]) == Decimal(str(fact["value"])) and
                   fact["decision_available_at"][:10] <= row["decision_date"], "certified_scale_amount_and_time")
        required = days("2019-01-01", (date.fromisoformat(row["source_day"]) - timedelta(days=1)).isoformat())
        # Per-day union membership is deliberately independent of main cursor scanning.
        complete = all(d in coverage and coverage[d]["complete"] for d in required)
        verify(complete == saved["coverage_certificate"]["complete"], "prefix_complete_recomputed")
        verify(saved["coverage_certificate"]["start"] == "2019-01-01" and
               saved["coverage_certificate"]["end"] == str(required[-1]), "prefix_strict_end")
        prefix_summaries.append({"period": period, "source_day": row["source_day"], "complete": complete})
        same_period = [g for g in extracted if g["period"] == period]
        earlier = [g for g in same_period if g["source_day"] < row["source_day"] and g["decision_date"] < row["decision_date"]]
        if not complete:
            expected = "unknown"
            unknown_periods.append(period)
        elif earlier:
            # All observed admitted documents were independently proved approximate points.
            latest = max(earlier, key=lambda g: g["source_day"])
            verify(sum(g["source_day"] == latest["source_day"] for g in earlier) == 1, "unambiguous_latest_source")
            expected = "approximate_point_estimate"
            verify(saved["latest_guidance_doc_id"] == latest["doc_id"] and
                   saved["earlier_doc_ids"] == [g["doc_id"] for g in earlier], "latest_and_prior_doc_join")
            deviation = Decimal(row["formal_parent_ytd_cny"]) - Decimal(latest["amount_cny"])
            verify(Decimal(saved["actual_minus_estimate_midpoint_cny"]) == deviation and
                   Decimal(saved["point_estimation_error_cny"]) == deviation and
                   saved["signed_breakout_cny"] is None, "point_deviation_not_hard_breakout")
            verify(np.isclose(saved["actual_relative_to_estimate_midpoint"],
                              float(deviation / abs(Decimal(latest["amount_cny"])))), "point_deviation_dimensionless_scale")
        elif any(g["decision_date"] == row["decision_date"] for g in same_period):
            expected = "same_cluster_only"
        else:
            expected = "no_prior_in_scoped_catalogue"
        verify(saved["classification"] == expected, "independent_report_classification")
        verify(saved["all_same_period_doc_ids"] == [g["doc_id"] for g in same_period], "same_period_lineage_join")
        derived.append({"period": period, "classification": expected, "event_id": row["event_id"]})
        clusters[row["event_id"]].append(period)
    verify(unknown_periods == ["20251231", "20260331", "20260630"], "exact_three_unknown_periods")
    counts = dict(Counter(row["classification"] for row in derived))
    verify(counts == {"no_prior_in_scoped_catalogue": 19, "approximate_point_estimate": 5, "unknown": 3},
           "report_class_counts_19_5_3")
    verify(counts == ledger["report_class_counts"] == results["report_class_counts"], "saved_report_counts")
    verify(results["catalogue_complete"] is False and
           results["reports_with_complete_required_prefix"] == 24 and
           results["reports_with_incomplete_required_prefix"] == 3, "no_global_gap_erasure")
    panel = pd.read_csv(OUT / "information_event_panel.csv", dtype={"report_period": str})
    old_panel = pd.read_csv(OLD / "others/event_panel.csv", dtype={"report_period": str})
    verify(len(panel) == len(clusters) == 25 and set(panel.event_id) == set(old_panel.event_id), "all25_event_join")
    verify(panel.event_id.nunique() == panel.decision_date.nunique() == 25, "one_event_per_decision_cluster")
    for event_id, periods in clusters.items():
        latest = max(periods)
        selected = panel.loc[panel.event_id.eq(event_id)].iloc[0]
        verify(selected.report_period == latest and selected.classification == reports[latest]["classification"],
               "latest_period_event_without_outcome_selection")
        for period in periods:
            formal_row = next(r for r in formal["reports"] if r["period"] == period)
            verify(formal_row["is_latest_period_in_cluster"] == (period == latest), "formal_latest_flag")
    event_counts = panel.classification.value_counts().to_dict()
    verify(event_counts == {"no_prior_in_scoped_catalogue": 19, "unknown": 3, "approximate_point_estimate": 3} ==
           results["event_class_counts"], "event_counts_19_3_3")
    for column in old_panel.columns:
        left = panel.set_index("event_id", drop=False).sort_index()[column]
        right = old_panel.set_index("event_id", drop=False).sort_index()[column]
        verify((left.eq(right) | (left.isna() & right.isna())).all(), "existing_market_label_join_unchanged")
    for comparison in results["primary_comparisons"]:
        verify(comparison["first"]["events"] == comparison["second"]["events"] == 0 and
               comparison["first"]["event_ids"] == comparison["second"]["event_ids"] == [] and
               comparison["event_difference"] is None and comparison["block_difference"] is None and
               comparison["percentile95"] is None and comparison["actual_bootstrap_draws"] == 0,
               "empty_primary_groups_remain_unavailable")
    verify(len(results["primary_comparisons"]) == 2, "exactly_two_primary_tests")
    for influence in results["influence"].values():
        for item in influence["leave_one_block_out"] + influence["fixed_subsets"]:
            verify(item["first_n"] == item["covered_n"] == 0 and item["effect"] is None,
                   "empty_influence_tests_remain_unavailable")
    for group in results["fixed_group_descriptive"]:
        chosen = panel.loc[panel.classification.eq(group["class"])]
        verify(chosen.event_id.tolist() == group["event_ids"] and len(chosen) == group["events"], "descriptive_group_membership")
        for column, key in [("return20", "stock_return20_mean"),
                            ("sector_excess_return20", "sector_excess_return20_mean"),
                            ("net_position_return", "net_position_return_mean_filled_only")]:
            verify(np.isclose(chosen[column].mean(), group[key]), "descriptive_group_mean")
        verify(chosen.net_position_return.notna().sum() == group["filled_positions"] and
               chosen.execution_status.eq("NO_TRADE").sum() == group["no_trade"], "filled_only_denominator")

    first_audit = read(OUT / "first_news_audit.json")
    verify(first_audit["status"] == "PASS" and first_audit["checks"] == 148 and
           first_audit["failure_count"] == 0, "independent_first_news_audit_pass")
    for binding in first_audit["source_hashes"] + first_audit["snapshot_bindings"]:
        bind(ROOT / binding["path"], binding["sha256"])
    expected_first = []
    for row in formal["reports"]:
        earlier = [g for g in extracted if g["period"] == row["period"] and g["source_day"] < row["source_day"]]
        if earlier:
            first = min(earlier, key=lambda g: g["source_day"])
            expected_first.append((row["period"], first["doc_id"], first["source_day"]))
    verify(len(expected_first) == len(results["first_news"]) == len(first_audit["first_news"]) == 5,
           "all_five_first_news_retained")
    for period, identity, day in expected_first:
        item = next(x for x in results["first_news"] if x["period"] == period)
        audited = next(x for x in first_audit["first_news"] if x["period"] == period)
        verify(item["first_doc_ids"] == [identity] and item["source_day"] == day and
               item["required_chain_prefix_complete"] is True and
               audited["first_doc_ids"] == item["first_doc_ids"], "first_news_source_universe")
        verify(item["preformal_date"] < item["formal_source_day"], "preformal_path_strict_source_boundary")
        for key, value in audited["computed_label"].items():
            observed = item["label"][key]
            if isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?", value):
                verify(np.isclose(float(value), float(observed), rtol=1e-10, atol=1e-10), "first_news_numeric_audit_binding")
            else:
                verify(value == observed, "first_news_exact_audit_binding")
    verify(results["actual_budget"]["actual_bootstrap_draws"] == 0 and
           all(results["actual_budget"][k] == 0 for k in
               ("new_model_fits", "new_continuous_accounts", "new_candidates", "threshold_searches", "alternate_horizons")),
           "no_new_fits_accounts_search_or_bootstrap")
    for relative, expected in results["source_hashes"].items():
        bind(ROOT / relative, expected)
    for relative in ("others/information_results.json", "others/report_information_ledger.json",
                     "others/information_event_panel.csv", "others/first_news_audit.json",
                     "others/market_contract_equivalence.json", "others/method_review.json",
                     "src/analyze_information.py", "src/collect_official.py", "src/information_math.py",
                     "src/audit_first_news.py", "src/build_formal_ledger.py"):
        bind(EX / relative)
    bind(READY / "others/accepted_financial_inputs.json")
    bind(READY / "upstream/responses/trade_cal.json")
    summary = {
        "status": "PASS", "experiment": "EX037_20261019",
        "reviewer": "financial_review independent RSCH subagent",
        "checks": sum(checks.values()), "check_counts": dict(checks), "blocking_findings": [],
        "catalogue": {"requests": 64, "derived_date_leaves": 40, "expected_rows": 605,
                      "observed_unique_rows": 600, "global_complete": False,
                      "unresolved_leaf": {k: bad[0][k] for k in ("start", "end", "rows", "total")},
                      "missing_record_dates": "UNKNOWN_NOT_INFERRED_FROM_RETURNED_DATES"},
        "sources": {"guidance_originals": 6, "fresh_pdf_pages": 12,
                    "background_2018_period": 1, "evaluation_period_documents": 5,
                    "approximate_points": 6, "hard_intervals": 0, "express_documents": 0,
                    "correction_titles_reviewed": 4, "amount_unit_signature_checks": extracted},
        "prefix_coverage": {"complete_report_prefixes": 24, "incomplete_report_prefixes": 3,
                            "unknown_periods": unknown_periods, "per_report": prefix_summaries},
        "report_classes": counts, "event_classes": event_counts,
        "reports": 27, "latest_period_events": 25, "outcome_based_selection": False,
        "primary_effects": "BOTH_UNAVAILABLE_EMPTY_BREAKOUT_AND_COVERED_ARMS_NOT_ZERO_EFFECTS",
        "actual_primary_bootstrap_draws": 0,
        "first_news_audit": {"path": (OUT / "first_news_audit.json").relative_to(ROOT).as_posix(),
                             "sha256": digest(OUT / "first_news_audit.json"),
                             "independent_checks": 148, "first_news_dates": 5,
                             "execution_reused_independent_auditor_not_duplicated": True},
        "method_independence": "Fresh PDF extraction and independent unit/date parsing; raw request containment derives leaves; day-set coverage derives strict prefixes; independent report/event joins and point-error arithmetic. No main collector, coverage_before, classifier or event_label imported.",
        "limitations": [
            "The five unreturned records have unknown titles/dates; all reports whose strict earlier prefix intersects the incomplete leaf remain unknown.",
            "No detected scoped issuer guidance does not establish absent expectations or absent information in every channel.",
            "Approximate single-point estimates are descriptive, not hard-range covered or breakout observations. Both main effects are unidentifiable in this sample.",
            "Fresh text extraction and full-page text/context checks were performed; this audit does not claim a rendered visual-layout inspection.",
            "First-news labels are descriptive isolated positions on seen history, not causal attribution or continuous-account qualification.",
            "Historical supplier arrival and unobserved revision history remain uncertified."
        ],
        "source_hashes": {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(bound_paths)},
        "new_upstream_calls": 0, "new_model_fits": 0, "new_accounts": 0,
    }
    with target.open("w" if args.refresh_unpublished_review else "x",
                     encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: summary[k] for k in ("status", "checks", "report_classes", "event_classes", "primary_effects")}))


if __name__ == "__main__":
    main()
