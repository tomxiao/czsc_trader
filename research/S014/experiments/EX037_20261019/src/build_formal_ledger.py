"""Offline EX037 formal-report YTD ledger, pinned public DFLS reads only."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import socket
from uuid import UUID

import pandas as pd

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import (
    DataRequest,
    Dataset,
    FinancialDisclosureParameters,
    FinancialReportKind,
    PreparedDataRef,
    ProviderConfig,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
READY = ROOT / "research/S014/materials/20261019_financial_readiness"
PREVIOUS = ROOT / "research/S014/experiments/EX036_20261019"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def reference(raw):
    return PreparedDataRef(
        UUID(raw["space_id"]), UUID(raw["preparation_id"]), raw["manifest_sha256"]
    )


def blocked(*_args, **_kwargs):
    raise RuntimeError("EX037 formal ledger: strictly offline; no network permitted")


def main():
    output = EX / "others/formal_report_ledger.json"
    if output.exists():
        raise FileExistsError("Preserve existing formal ledger; choose a new revision explicitly")
    socket.socket.connect = blocked
    socket.create_connection = blocked
    protocol = EX / "protocols/design.json"
    publication = EX / "protocols/published_design.json"
    assert read(publication)[relative(protocol)]["sha256"] == digest(protocol)
    accepted_path = READY / "others/accepted_financial_inputs.json"
    accepted = read(accepted_path)
    original_audit_path = ROOT / accepted["original_audit_path"]
    assert digest(original_audit_path) == accepted["original_audit_sha256"]
    original_audit = read(original_audit_path)
    preparation_path = READY / "others/preparation.json"
    assert digest(preparation_path) == accepted["source_preparation_sha256"]
    preparation = read(preparation_path)
    facts = {(f["kind"], f["period"], f["field"]): f for f in accepted["facts"]}
    context = create_research_context(
        RepositoryContext.discover(ROOT),
        ResearchBatchRef("S014"),
        providers=ProviderConfig(bindings={}),
    )
    expected_periods = tuple(
        pd.period_range("2018Q2", "2026Q2", freq="Q-DEC").end_time.strftime("%Y-%m-%d")
    )
    frames = {}
    fetch_checks = []
    for kind in (FinancialReportKind.INCOME, FinancialReportKind.BALANCE_SHEET):
        query = DataRequest(
            Dataset.COMPANY_FINANCIAL_DISCLOSURES,
            "600722.SH",
            "2018-07-01",
            "2026-10-15",
            None,
            frequency="event",
            parameters=FinancialDisclosureParameters(
                kind, "2018-06-30", "2026-06-30", expected_periods=expected_periods
            ),
        )
        result = context.data.fetch(query, prepared=reference(accepted["preparation_reference"]))
        assert result.ready, result.error
        prepared_item = next(x for x in preparation["items"] if x["kind"] == kind.value)
        assert result.identity.content_sha256 == prepared_item["content_sha256"]
        frames[kind.value] = result.dataframe.set_index("RecordId", drop=False)
        fetch_checks.append(
            {
                "kind": kind.value,
                "rows": len(result.dataframe),
                "content_sha256": result.identity.content_sha256,
                "status": "PASS",
            }
        )

    verified_files = {}
    unknown = []

    def verify_fact(kind, period, field, decision):
        fact = facts.get((kind, period, field))
        if not fact or fact["state"] != "PUBLIC_ORIGINAL_VALUE_RECONCILED" or fact["value"] is None:
            unknown.append(
                {
                    "kind": kind,
                    "period": period,
                    "field": field,
                    "reason": "NO_CERTIFIED_ORIGINAL_FACT",
                }
            )
            return {"status": "UNKNOWN", "period": period, "value_cny": None}
        assert fact["decision_available_at"] <= decision
        rows = frames[kind].loc[fact["eligible_observation_ids"]]
        assert rows[field].notna().all()
        assert set(rows.end_date.astype(str)) == {period}
        assert all(Decimal(str(v)) == Decimal(str(fact["value"])) for v in rows[field])
        source = fact["original_source"]
        for path, expected_hash in [
            (ROOT / source["pdf_path"], source["pdf_sha256"]),
            (READY / f"official/texts/{period}_{source['doc_id']}.json", source["text_sha256"]),
        ]:
            if relative(path) not in verified_files:
                assert digest(path) == expected_hash
                verified_files[relative(path)] = expected_hash
            assert verified_files[relative(path)] == expected_hash
        check = next(
            c
            for c in original_audit["checks"]
            if (c["kind"], c["period"], c["field"]) == (kind, period, field)
        )
        matches = [
            c
            for c in check["original_candidates"]
            if c["doc_id"] == source["doc_id"]
            and c["page"] == source["page"]
            and c["context_verified"]
            and Decimal(c["value_cny"]) == Decimal(str(fact["value"]))
        ]
        assert matches
        assert (
            source["scope"] == "CONSOLIDATED"
            and source["currency"] == "CNY"
            and source["unit"] == "yuan"
        )
        assert source["period_basis"] == (
            "YEAR_TO_DATE_CUMULATIVE" if kind == "income" else "PERIOD_END_BALANCE"
        )
        return {
            "status": "CERTIFIED_PUBLIC_ORIGINAL_RECONCILED",
            "kind": kind,
            "field": field,
            "period": period,
            "value_cny": str(Decimal(str(fact["value"]))),
            "eligible_observation_ids": fact["eligible_observation_ids"],
            "source_day": fact["effective_date_anchor"],
            "public_support_date_in_scoped_corpus": fact["public_support_date_in_scoped_corpus"],
            "decision_available_at": fact["decision_available_at"],
            "earliest_execution_session": fact["earliest_execution_session"],
            "original_source": source,
            "original_raw_line": matches[0]["raw_line"],
            "original_column_header_context": matches[0]["column_header_context"],
            "prepared_rows": [
                {
                    "RecordId": row.RecordId,
                    "ann_date": row.ann_date,
                    "f_ann_date": row.f_ann_date,
                    "update_flag": row.update_flag,
                    "AvailableDate": str(row.AvailableDate),
                }
                for row in rows.itertuples()
            ],
        }

    feature_path = PREVIOUS / "others/financial_features.csv"
    with feature_path.open(encoding="utf-8-sig", newline="") as stream:
        prior_features = list(csv.DictReader(stream))
    report_to_feature = {}
    for row in prior_features:
        for period in row["joint_report_periods"].split("|"):
            assert period not in report_to_feature
            report_to_feature[period] = row
    assert len(report_to_feature) == 27 and len(prior_features) == 25
    periods = sorted(
        period
        for kind, period, field in facts
        if kind == "income" and field == "n_income_attr_p" and period >= "20191231"
    )
    assert len(periods) == 27
    clusters = defaultdict(list)
    reports = []
    for period in periods:
        fact = facts[("income", period, "n_income_attr_p")]
        decision = fact["decision_available_at"]
        formal = verify_fact("income", period, "n_income_attr_p", decision)
        assert formal["status"] != "UNKNOWN"
        previous_year = str(int(period[:4]) - 1) + period[4:]
        prior_parent = verify_fact("income", previous_year, "n_income_attr_p", decision)
        prior_assets = verify_fact("balancesheet", previous_year, "total_assets", decision)
        feature = report_to_feature[period]
        assert feature["decision_available_at"] == decision
        assert formal["source_day"] == formal["original_source"]["publication_date"]
        decision_date = decision[:10]
        event_id = "FIN_" + decision_date.replace("-", "")
        clusters[event_id].append(period)
        reports.append(
            {
                "period": period,
                "formal_parent_ytd_cny": formal["value_cny"],
                "source_day": formal["source_day"],
                "decision_available_at": decision,
                "decision_date": decision_date,
                "entry_date": formal["earliest_execution_session"],
                "event_id": event_id,
                "feature_event_id": feature["event_id"],
                "latest_period_in_cluster": feature["report_period"],
                "is_latest_period_in_cluster": period == feature["report_period"],
                "formal_fact": formal,
                "prior_year_period": previous_year,
                "prior_year_parent_ytd_cny": prior_parent["value_cny"],
                "prior_year_parent_status": prior_parent["status"],
                "prior_year_parent_fact": prior_parent,
                "prior_year_total_assets_cny": prior_assets["value_cny"],
                "prior_year_assets_status": prior_assets["status"],
                "prior_year_assets_fact": prior_assets,
                "profit_scale_status": "KNOWN_NONZERO"
                if prior_parent["value_cny"] is not None and Decimal(prior_parent["value_cny"]) != 0
                else "UNKNOWN_OR_ZERO_UNUSABLE",
                "asset_scale_status": "KNOWN_POSITIVE"
                if prior_assets["value_cny"] is not None and Decimal(prior_assets["value_cny"]) > 0
                else "UNKNOWN_OR_NONPOSITIVE_UNUSABLE",
            }
        )
    assert len(clusters) == 25
    for event_id, jointly_published in clusters.items():
        group = [r for r in reports if r["event_id"] == event_id]
        assert all(r["latest_period_in_cluster"] == max(jointly_published) for r in group)
        assert sum(r["is_latest_period_in_cluster"] for r in group) == 1

    market_path = PREVIOUS / "others/market_inputs.json"
    market = read(market_path)
    market_checks = []
    assert len(market["native_identities"]) == 7
    for item in market["native_identities"]:
        query = DataRequest(
            Dataset(item["request"]["dataset"]),
            item["request"]["symbol"],
            item["request"]["start"],
            item["request"]["end"],
            item["request"]["required_cutoff"],
        )
        result = context.data.fetch(query, prepared=reference(item["prepared"]))
        assert result.ready, (item["name"], result.error)
        assert result.identity.content_sha256 == item["content_sha256"]
        assert len(result.dataframe) == item["rows"]
        snapshot = ROOT / item["snapshot_path"]
        assert digest(snapshot) == item["snapshot_sha256"]
        market_checks.append({**item, "status": "PUBLIC_DFLS_PINNED_FETCH_AND_SNAPSHOT_HASH_PASS"})
    result = {
        "status": "PASS",
        "experiment": "EX037_20261019",
        "report_count": len(reports),
        "event_count": len(clusters),
        "reports": reports,
        "same_decision_clusters": [
            {"event_id": event_id, "periods": group, "latest_period": max(group)}
            for event_id, group in sorted(clusters.items())
        ],
        "financial_preparation_reference": accepted["preparation_reference"],
        "financial_pinned_fetch_checks": fetch_checks,
        "market_pinned_inputs": market_checks,
        "unknown_items": unknown,
        "profit_scale_status_counts": dict(Counter(r["profit_scale_status"] for r in reports)),
        "asset_scale_status_counts": dict(Counter(r["asset_scale_status"] for r in reports)),
        "verified_original_files": [
            {"path": p, "sha256": h} for p, h in sorted(verified_files.items())
        ],
        "input_bindings": [
            {"path": relative(p), "sha256": digest(p)}
            for p in [
                protocol,
                publication,
                accepted_path,
                original_audit_path,
                preparation_path,
                feature_path,
                market_path,
                Path(__file__),
            ]
        ],
        "financial_amount_basis": "Certified original year-to-date consolidated parent-attributable net profit; never quarter differencing. Previous-year scaling uses identical MMDD prior-year YTD profit and prior-year period-end total assets.",
        "source_clock_basis": "Existing accepted financial effective_date_anchor, verified equal to supporting official publication date. Original files/hash and prior certification reused; signature dates not newly reparsed here. Earliest SSE decision/execution copied from admitted as-of contract.",
        "network": "socket.socket.connect and socket.create_connection blocked; ProviderConfig(bindings={}); public fetch only, no prepare",
        "new_api_calls": 0,
        "model_fits": 0,
        "new_labels": 0,
        "new_accounts": 0,
        "history": "Only approved EX036 financial features and seven input identities/snapshots reused; no old return-label files read",
        "limitations": [
            "Historical vendor arrivals and complete revision vintages remain unverified",
            "Seven pinned input identities prove reusable data coverage, not that every potential early-guidance date has a full future price path",
            "Headline YTD parent profit does not establish what revenue, margin, cashflow or notes were known earlier",
        ],
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": "PASS",
                "reports": len(reports),
                "events": len(clusters),
                "unknown_items": len(unknown),
                "financial_fetches": len(fetch_checks),
                "market_fetches": len(market_checks),
                "new_api_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
