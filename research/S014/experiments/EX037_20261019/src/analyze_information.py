"""Join the full issuer disclosure chain before fixed information comparisons."""
import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from czsc_trader.research_tools import EvidenceRef
from information_math import compare_amount, descriptive_comparison, event_label

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/S014/experiments/EX036_20261019"


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def coverage_before(leaves, source_day):
    """Certify only the strict earlier-source prefix required by this report."""
    begin = date(2019, 1, 1)
    end = date.fromisoformat(source_day) - timedelta(days=1)
    cursor = begin
    issues = []
    for leaf in sorted(leaves, key=lambda x: x["start"]):
        left, right = map(date.fromisoformat, (leaf["start"], leaf["end"]))
        if right < cursor or left > end:
            continue
        if left > cursor:
            issues.append({"reason": "UNCOVERED_DATE_RANGE", "start": str(cursor),
                           "end": str(min(end, left-timedelta(days=1)))})
        if not leaf["complete"]:
            issues.append({"reason": "INCOMPLETE_LEAF", "name": leaf["name"],
                           "start": str(max(cursor, left)), "end": str(min(end, right)),
                           "rows": leaf["rows"], "total": leaf["total"]})
        cursor = max(cursor, right + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        issues.append({"reason": "UNCOVERED_DATE_RANGE", "start": str(cursor), "end": str(end)})
    return {"complete": not issues, "start": str(begin), "end": str(end), "issues": issues}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue-audit", required=True)
    args = parser.parse_args()
    audit_path = (ROOT / args.catalogue_audit).resolve()
    assert audit_path.is_relative_to(EX)
    assert not (EX / "others/information_results.json").exists()
    for name in ("published_design", "published_retrieval_amendment", "published_coverage_interpretation"):
        for path, payload in read(EX / f"protocols/{name}.json").items():
            assert EvidenceRef.from_dict(payload).resolve(ROOT).read_bytes() == (ROOT / path).read_bytes()
    contract = read(EX / "others/market_contract_equivalence.json")
    assert contract["status"] == "PASS"
    for path, expected in contract["source_sha256"].items():
        assert digest(ROOT / path) == expected, path
    audit = read(audit_path)
    complete = audit["complete"]
    assert type(complete) is bool
    formal = read(EX / "others/formal_report_ledger.json")
    sources = read(EX / "others/guidance_facts.json")
    facts = sources["facts"]
    assert len({x["doc_id"] for x in facts}) == len(facts)
    frames = {}
    for item in read(OLD / "others/market_inputs.json")["native_identities"]:
        path = ROOT / item["snapshot_path"]
        assert digest(path) == item["snapshot_sha256"]
        frames[item["name"]] = pd.read_csv(path).set_index("Date")
    calendar_sessions = frames["calendar"].loc[frames["calendar"].IsOpen.eq(1)].index.tolist()
    sessions = [d for d in calendar_sessions if "2020-01-01" <= d <= "2026-10-15"]
    assert sessions == frames["stock_raw"].index.tolist()

    def decision(source_day):
        return next((d for d in calendar_sessions if d > source_day), None)

    for fact in facts:
        for kind in ("pdf", "text"):
            path = fact[kind + "_path"]
            if path is None:
                assert fact["admission_status"] == "UNKNOWN"
            else:
                assert digest(ROOT / path) == fact[kind + "_sha256"]
        fact["decision_date"] = decision(fact["source_day"])
    classifications = []
    first_news = []
    for report in formal["reports"]:
        period = report["period"]
        prefix_coverage = coverage_before(audit["leaf_scopes"], report["source_day"])
        same_period = [f for f in facts if f["period"] == period]
        earlier_day = [f for f in same_period if f["source_day"] < report["source_day"]]
        prior = [f for f in earlier_day if f["decision_date"] and f["decision_date"] < report["decision_date"]]
        same_cluster = [f for f in same_period if f["decision_date"] == report["decision_date"]]
        row = {k: report[k] for k in ("period", "formal_parent_ytd_cny", "source_day", "decision_date",
                                     "entry_date", "event_id", "latest_period_in_cluster", "is_latest_period_in_cluster")}
        row.update(all_same_period_doc_ids=[f["doc_id"] for f in same_period],
                   earlier_doc_ids=[f["doc_id"] for f in prior],
                   same_cluster_doc_ids=[f["doc_id"] for f in same_cluster],
                   latest_guidance_doc_id=None, source_type=None, coverage_certificate=prefix_coverage)
        if not prefix_coverage["complete"]:
            row.update(classification="unknown", reason="REQUIRED_EARLIER_ISSUER_CATALOGUE_PREFIX_INCOMPLETE")
        elif prior:
            latest_day = max(f["source_day"] for f in prior)
            latest = [f for f in prior if f["source_day"] == latest_day]
            replaced = {identity for fact in latest for identity in fact["replacement_doc_ids"]}
            latest = [f for f in latest if f["doc_id"] not in replaced]
            if len(latest) != 1:
                row.update(classification="unknown", reason="LATEST_SAME_DAY_VERSION_ORDER_UNRESOLVED")
            else:
                fact = latest[0]
                row.update(latest_guidance_doc_id=fact["doc_id"], source_type=fact["kind"],
                           latest_source_day=fact["source_day"], latest_guidance_decision_date=fact["decision_date"],
                           source_url=fact["url"], source_amount_text=fact["original_amount_text"])
                if fact["admission_status"] != "ADMITTED" or fact["accounting_scope"] != "PARENT_ATTRIBUTABLE_YTD":
                    row.update(classification="unknown", reason="LATEST_AMOUNT_OR_BASIS_NOT_ADMITTED")
                else:
                    comparison = compare_amount(report["formal_parent_ytd_cny"], fact["parent_profit_low_cny"],
                                                fact["parent_profit_high_cny"], fact["printed_quantum_low_cny"],
                                                fact["printed_quantum_high_cny"], fact["approximate_point"])
                    row.update(comparison)
                    estimate = (Decimal(fact["parent_profit_low_cny"]) + Decimal(fact["parent_profit_high_cny"])) / 2
                    deviation = Decimal(report["formal_parent_ytd_cny"]) - estimate
                    row["estimate_midpoint_cny"] = str(estimate)
                    row["actual_minus_estimate_midpoint_cny"] = str(deviation)
                    row["actual_relative_to_estimate_midpoint"] = float(deviation / abs(estimate)) if estimate else None
                    prior_profit = report["prior_year_parent_ytd_cny"]
                    prior_assets = report["prior_year_total_assets_cny"]
                    distance = row["signed_breakout_cny"]
                    row["signed_breakout_scaled_prior_year_parent"] = (
                        float(Decimal(distance) / abs(Decimal(prior_profit))) if distance is not None and prior_profit and Decimal(prior_profit) else None)
                    row["signed_breakout_scaled_prior_year_assets"] = (
                        float(Decimal(distance) / Decimal(prior_assets)) if distance is not None and prior_assets and Decimal(prior_assets) else None)
        elif same_cluster:
            row.update(classification="same_cluster_only", reason="NO_SEPARATELY_EARLIER_TRADABLE_GUIDANCE_CLUSTER")
        else:
            row.update(classification="no_prior_in_scoped_catalogue", reason="NO_EARLIER_SAME_PERIOD_ISSUER_GUIDANCE_FOUND_IN_COMPLETE_SCOPED_CATALOGUE")
        classifications.append(row)
        # Earliest issued same-period guidance; never choose dates by ensuing returns.
        if earlier_day:
            first_day = min(f["source_day"] for f in earlier_day)
            first = [f for f in earlier_day if f["source_day"] == first_day]
            first_decision = decision(first_day)
            label = event_label(frames, sessions, first_decision) if first_decision else {"status": "NO_LATER_CALENDAR_SESSION"}
            item = {"period": period, "first_doc_ids": [f["doc_id"] for f in first],
                    "source_day": first_day, "formal_source_day": report["source_day"],
                    "first_source_urls": [f["url"] for f in first], "formal_event_id": report["event_id"],
                    "label": label, "source_accounting_admitted": all(f["admission_status"] == "ADMITTED" for f in first),
                    "required_chain_prefix_complete": prefix_coverage["complete"]}
            if first_decision in frames["stock_hfq"].index and report["decision_date"] in sessions:
                before_formal = max((d for d in sessions if d < report["source_day"]), default=None)
                if before_formal is not None and before_formal >= first_decision:
                    stock_move = float(frames["stock_hfq"].loc[before_formal, "Close"] / frames["stock_hfq"].loc[first_decision, "Close"] - 1)
                    sector_move = float(frames["sector"].loc[before_formal, "Close"] / frames["sector"].loc[first_decision, "Close"] - 1)
                    item.update(guidance_decision_close_to_preformal_close_stock_return=stock_move,
                                guidance_decision_close_to_preformal_close_sector_excess=stock_move-sector_move,
                                preformal_date=before_formal)
            first_news.append(item)
    assert len(classifications) == 27
    latest = [r for r in classifications if r["is_latest_period_in_cluster"]]
    assert len(latest) == 25 and len({r["event_id"] for r in latest}) == 25
    old_panel = pd.read_csv(OLD / "others/event_panel.csv", dtype={"report_period": str})
    select = pd.DataFrame(latest).rename(columns={"period": "report_period", "source_day": "formal_source_day"})
    shared = set(select) & set(old_panel)
    join = select.drop(columns=sorted(shared - {"event_id", "report_period"})).merge(
        old_panel, on=["event_id", "report_period"], how="outer", validate="one_to_one", indicator=True)
    assert len(join) == 25 and join["_merge"].eq("both").all()
    join = join.drop(columns="_merge").sort_values("decision_date").reset_index(drop=True)
    blocks = read(OLD / "others/statistics.json")["dependency_blocks"]
    primary = []
    for identity, arm, direction in (("NEW_POSITIVE_VS_COVERED", "positive_new", "positive"),
                                     ("NEW_NEGATIVE_VS_COVERED", "negative_new", "negative")):
        effect = descriptive_comparison(join, arm, "covered", blocks)
        effect.update(id=identity, declared_direction=direction)
        primary.append(effect)
    influence = {}
    for effect in primary:
        arm = effect["first"]["class"]
        entries = []
        for block in blocks:
            reduced = join.loc[~join.event_id.isin(block["event_ids"])]
            a = reduced.loc[reduced.classification.eq(arm), "sector_excess_return20"]
            b = reduced.loc[reduced.classification.eq("covered"), "sector_excess_return20"]
            entries.append({"removed_block": block["id"], "first_n": len(a), "covered_n": len(b),
                            "effect": float(a.mean()-b.mean()) if len(a) and len(b) else None})
        subsets = []
        for count in (1, 3):
            ordered = join.assign(_abs=join.sector_excess_return20.abs()).sort_values(["_abs", "decision_date"], ascending=[False, True])
            subsets.append((f"remove_top_abs_target_{count}", join.loc[~join.event_id.isin(ordered.head(count).event_id)]))
        subsets.append(("exclude2026_complete_endpoints", join.loc[join.dependency_endpoint_date.le("2025-12-31")]))
        subsets.extend((str(year), subset) for year, subset in join.groupby(join.decision_date.str[:4]))
        descriptions = []
        for name, subset in subsets:
            a = subset.loc[subset.classification.eq(arm), "sector_excess_return20"]
            b = subset.loc[subset.classification.eq("covered"), "sector_excess_return20"]
            descriptions.append({"subset": name, "first_n": len(a), "covered_n": len(b),
                                 "effect": float(a.mean()-b.mean()) if len(a) and len(b) else None})
        influence[effect["id"]] = {"leave_one_block_out": entries, "fixed_subsets": descriptions}
    join.to_csv(EX / "others/information_event_panel.csv", index=False, lineterminator="\n")
    write(EX / "others/report_information_ledger.json", {
        "reports": classifications, "report_class_counts": dict(Counter(r["classification"] for r in classifications)),
        "catalogue_complete": complete, "first_news": first_news,
    })
    groups = []
    for name, subset in join.groupby("classification", sort=True):
        groups.append({"class": name, "events": len(subset), "event_ids": subset.event_id.tolist(),
                       "stock_return20_mean": float(subset.return20.mean()),
                       "sector_excess_return20_mean": float(subset.sector_excess_return20.mean()),
                       "net_position_return_mean_filled_only": float(subset.net_position_return.mean()) if subset.net_position_return.notna().any() else None,
                       "filled_positions": int(subset.net_position_return.notna().sum()),
                       "no_trade": int(subset.execution_status.eq("NO_TRADE").sum())})
    counts = Counter(r["classification"] for r in classifications)
    result = {"status": "FIXED_INFORMATION_CHAIN_ANALYSIS_COMPLETE", "reports": 27, "events": 25,
              "catalogue_complete": complete, "report_class_counts": dict(counts),
              "reports_with_complete_required_prefix": sum(r["coverage_certificate"]["complete"] for r in classifications),
              "reports_with_incomplete_required_prefix": sum(not r["coverage_certificate"]["complete"] for r in classifications),
              "event_class_counts": {str(k): int(v) for k, v in join.classification.value_counts().items()},
              "primary_comparisons": primary, "influence": influence, "fixed_group_descriptive": groups,
              "first_news": first_news,
              "main_claim_limit": "Covered is a prior-headline numerical-boundary statement, not no new financial information; no observed issuer preview is not absence of market expectations.",
              "point_express_limitation": "The preregistered inner interval is empty for any point-valued express with positive printed quantum; exact point consistency remains boundary overlap. No post-result relaxation.",
              "actual_budget": {"new_model_fits": 0, "new_continuous_accounts": 0, "new_candidates": 0,
                                "threshold_searches": 0, "alternate_horizons": 0,
                                "primary_contrasts": 2, "actual_bootstrap_draws": sum(x["actual_bootstrap_draws"] for x in primary),
                                "first_news_labels": len(first_news)},
              "source_hashes": {p.relative_to(ROOT).as_posix(): digest(p) for p in (
                  Path(__file__), EX / "src/information_math.py", EX / "others/formal_report_ledger.json",
                  EX / "others/guidance_facts.json", audit_path, OLD / "others/event_panel.csv",
                  OLD / "others/statistics.json", OLD / "others/market_inputs.json")}}
    write(EX / "others/information_results.json", result)
    print(json.dumps({"reports": 27, "events": 25, "classes": result["report_class_counts"],
                      "primary": [{"id": x["id"], "effect": x["event_difference"], "status": x["status"]} for x in primary]}))


if __name__ == "__main__":
    main()
