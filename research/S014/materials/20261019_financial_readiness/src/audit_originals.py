"""Offline financial original-document reconciliation; never selects vendor vintages.

Reads all preserved observations and official page extractions. Only explicitly
identified consolidated statements/current cumulative columns are eligible.
Missing/ambiguous rows remain unverified; no zero imputation or API calls.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BASE = Path(__file__).resolve().parents[1]
MONEY = re.compile(r"(?<![\d.])[-−－]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)")
SPECS = {
    "income": {
        "revenue": r"^(?:[一二三四五六七八九十]+[、.]|其中[:：])?营业收入",
        "oper_cost": r"^(?:[一二三四五六七八九十]+[、.]|其中[:：])?营业成本",
        "n_income": r"^[一二三四五六七八九十]+[、.]净利润",
        "n_income_attr_p": r"^(?:[（(]?\d[）).、]?)?归属于母公司(?:所有者|股东)的?净利润",
    },
    "balancesheet": {
        "total_assets": r"^资产总计",
        "accounts_receiv": r"^应收账款",
        "inventories": r"^存货",
    },
    "cashflow": {"n_cashflow_act": r"^经营活动产生的现金流量净额"},
    "fina_indicator": {
        "profit_dedt": r"^归属于上市公司股东的扣除非经常性损益的净利润",
    },
}
HEADINGS = {
    "合并资产负债表": "balancesheet",
    "母公司资产负债表": "parent",
    "合并利润表": "income",
    "母公司利润表": "parent",
    "合并现金流量表": "cashflow",
    "母公司现金流量表": "parent",
    "合并所有者权益变动表": "end",
    "母公司所有者权益变动表": "end",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(s: str) -> str:
    return re.sub(r"\s+", "", s)


def dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value).replace(",", "").replace("−", "-").replace("－", "-"))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def statement_sections(pages):
    sections = []
    current = None
    for pg in pages:
        for line in pg["text"].splitlines():
            short = compact(line)
            stripped = re.sub(r"^\d+[、.．]", "", short)
            if stripped in HEADINGS:
                current = {"kind": HEADINGS[stripped], "heading": stripped, "page": pg["page"], "lines": []}
                sections.append(current)
            if current is not None:
                current["lines"].append((pg["page"], line))
    return sections


def find_rows(lines, pattern):
    """Join wrapped labels only until the first monetary cell (max 5 lines)."""
    out = []
    for i, (page, line) in enumerate(lines):
        combined = line
        end = i
        for j in range(i + 1, min(i + 5, len(lines))):
            if MONEY.search(combined):
                break
            combined += " " + lines[j][1]
            end = j
        if not re.search(pattern, compact(combined)):
            continue
        cells = list(MONEY.finditer(combined))
        if not cells:
            continue
        prefix = compact(combined[: cells[0].start()])
        # Must match the label, rather than a following unrelated table row.
        if not re.search(pattern, prefix):
            continue
        out.append({"page": page, "last_page": lines[end][0], "raw_line": combined.strip(), "values": [m.group(0) for m in cells], "line_index": i})
    return out


def extract_document(doc):
    period = doc["period"]
    text_path = BASE / "official/texts" / f"{period}_{doc['doc_id']}.json"
    if not text_path.exists():
        return []
    pages_doc = read(text_path)
    pdf_path = ROOT / doc["pdf_path"]
    pdf_hash = sha(pdf_path)
    assert pdf_hash == doc["sha256"] == pages_doc["pdf_sha256"], doc["doc_id"]
    pages = pages_doc["pages"]
    candidates = []
    seen_main_statements = set()
    for section in statement_sections(pages):
        kind = section["kind"]
        if kind not in SPECS or kind == "fina_indicator":
            continue
        # Later notes can repeat the same heading for an opening-balance
        # accounting-policy adjustment. Only the first complete main statement
        # of each kind represents this report's current-period table.
        if kind in seen_main_statements:
            continue
        seen_main_statements.add(kind)
        header = "\n".join(x[1] for x in section["lines"][:30])
        normalized_header = compact(header)
        # All supported originals explicitly state RMB/yuan. Do not infer units.
        unit_verified = bool(re.search(r"单位[:：]元", normalized_header)) and "人民币" in normalized_header
        year_verified = period[:4] in header
        if kind == "balancesheet":
            cumulative_verified = "期末" in header or f"{period[:4]}年{int(period[4:6])}月" in normalized_header
            col = 0
        else:
            cumulative_verified = bool(re.search(r"1[—－–-]" + str(int(period[4:6])), normalized_header)) or "年度" in normalized_header or "年初至" in normalized_header or period.endswith("1231") or period.endswith("0331")
            # Pre-2021 Q3 statements expose both quarter and cumulative columns.
            four_columns = (period.endswith("0930") and bool(re.search(r"7[—－–-]9", normalized_header)))
            col = 2 if four_columns else 0
        patterns = dict(SPECS[kind])
        if kind == "balancesheet":
            patterns["accounts_receiv_combined"] = r"^应收票据及应收账款"
        for field, pattern in patterns.items():
            for row in find_rows(section["lines"], pattern):
                if col >= len(row["values"]):
                    continue
                candidates.append({
                    "period": period, "kind": kind, "field": field,
                    "value_cny": str(dec(row["values"][col])),
                    "pdf_path": doc["pdf_path"], "pdf_sha256": pdf_hash,
                    "doc_id": doc["doc_id"], "publication_date": doc["publication_date"],
                    "url": doc["url"], "version_kind": doc["version_kind"],
                    "title": doc["title"], "page": row["page"], "last_page": row["last_page"],
                    "raw_line": row["raw_line"], "raw_numeric_cells": row["values"],
                    "selected_numeric_column_1based": col + 1,
                    "section_heading": section["heading"], "section_start_page": section["page"],
                    "column_header_context": header, "currency": "CNY", "unit": "yuan",
                    "period_basis": "PERIOD_END_BALANCE" if kind == "balancesheet" else "YEAR_TO_DATE_CUMULATIVE",
                    "scope": "CONSOLIDATED",
                    "context_verified": unit_verified and year_verified and cumulative_verified,
                    "text_path": relative(text_path), "text_sha256": sha(text_path),
                })
    # The deducted attributable profit is reported in the issuer's key-accounting
    # table, not the statement of consolidated net income. Keep that distinction.
    summary_lines = [(pg["page"], line) for pg in pages[:10] for line in pg["text"].splitlines()]
    for row in find_rows(summary_lines, SPECS["fina_indicator"]["profit_dedt"]):
        idx = row["line_index"]
        context = "\n".join(line for _, line in summary_lines[max(0, idx - 25):idx + 4])
        col = 2 if period.endswith("0930") and "本报告期" in context and "年初至报告期末" in compact(context) and len(row["values"]) >= 4 and int(period[:4]) >= 2021 else 0
        candidates.append({
            "period": period, "kind": "fina_indicator", "field": "profit_dedt",
            "value_cny": str(dec(row["values"][col])),
            "pdf_path": doc["pdf_path"], "pdf_sha256": pdf_hash,
            "doc_id": doc["doc_id"], "publication_date": doc["publication_date"],
            "url": doc["url"], "version_kind": doc["version_kind"], "title": doc["title"],
            "page": row["page"], "last_page": row["last_page"], "raw_line": row["raw_line"],
            "raw_numeric_cells": row["values"], "selected_numeric_column_1based": col + 1,
            "section_heading": "主要会计数据和财务指标", "column_header_context": context,
            "currency": "CNY", "unit": "yuan", "scope": "ATTRIBUTABLE_TO_LISTED_COMPANY_SHAREHOLDERS",
            "period_basis": "YEAR_TO_DATE_CUMULATIVE",
            "context_verified": "人民币" in context and bool(re.search(r"单位[:：]元", compact(context))) and ("年初至" in compact(context) or "本报告期" in context or period[:4]+"年" in compact(context)),
            "text_path": relative(text_path), "text_sha256": sha(text_path),
        })
    return candidates


def main():
    preparation = read(BASE / "others/preparation.json")
    inventory_path = BASE / "official/download_inventory_v2.json"
    inventory = read(inventory_path)
    candidates = []
    for doc in inventory["documents"]:
        if doc.get("status") in {"PDF_RECEIVED", "EXTRACTED"}:
            candidates.extend(extract_document(doc))
    by_key = defaultdict(list)
    for item in candidates:
        by_key[(item["period"], item["kind"], item["field"])].append(item)
    sources = {}
    prepared_record_bindings = defaultdict(list)
    for item in preparation["items"]:
        csv_path = ROOT / item["csv_path"]
        assert sha(csv_path) == item["csv_sha256"], item["kind"]
        with csv_path.open(encoding="utf-8", newline="") as stream:
            for prepared in csv.DictReader(stream):
                payload = json.loads(prepared["RawRecord"])
                record_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
                prepared_record_bindings[(item["kind"], record_hash)].append({"record_id": prepared["RecordId"], "available_date": prepared["AvailableDate"], "date": prepared["Date"]})
    periods = set()
    for kind in SPECS:
        path = BASE / f"upstream/responses/{kind}.json"
        table = read(path)
        rows = [dict(zip(table["fields"], row, strict=True)) for row in table["items"]]
        sources[kind] = rows
        periods.update(row["end_date"] for row in rows)
    checks = []
    for period in sorted(periods):
        for kind, fields in SPECS.items():
            rows = [dict(row, source_row_ordinal=i) for i, row in enumerate(sources[kind], 1) if row["end_date"] == period]
            for field in fields:
                possible = by_key[(period, kind, field)]
                good = [x for x in possible if x["context_verified"]]
                observations = []
                for row in rows:
                    matches = [x for x in good if dec(row[field]) is not None and abs(dec(row[field]) - dec(x["value_cny"])) <= Decimal("0.01")]
                    matches.sort(key=lambda x: (x["publication_date"], x["doc_id"], x["page"]))
                    record_hash = hashlib.sha256(json.dumps({k: v for k, v in row.items() if k != "source_row_ordinal"}, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
                    bindings = prepared_record_bindings[(kind, record_hash)]
                    assert bindings, (kind, row["source_row_ordinal"])
                    observations.append({
                        "source_row_ordinal": row["source_row_ordinal"], "value": row[field],
                        "ann_date": row["ann_date"], "f_ann_date": row.get("f_ann_date"),
                        "update_flag": row.get("update_flag"), "report_type": row.get("report_type"),
                        "raw_record_sha256": record_hash, "prepared_record_bindings": bindings,
                        "status": "PUBLIC_ORIGINAL_RECONCILED" if matches else "SOURCE_NULL" if row[field] is None else "VALUE_OR_CONTEXT_UNVERIFIED",
                        "matches": matches,
                        "first_matching_publication": matches[0]["publication_date"] if matches else None,
                        "ann_date_precedes_matching_original": bool(matches and row["ann_date"] < matches[0]["publication_date"].replace("-", "")),
                    })
                status = "PUBLIC_ORIGINAL_RECONCILED" if observations and all(x["status"] == "PUBLIC_ORIGINAL_RECONCILED" for x in observations) else "PARTIAL_OBSERVATIONS_RECONCILED" if any(x["status"] == "PUBLIC_ORIGINAL_RECONCILED" for x in observations) else "ORIGINAL_OR_CONTEXT_UNVERIFIED"
                scope_evidence = by_key[(period, kind, "accounts_receiv_combined")] if field == "accounts_receiv" else []
                if scope_evidence and all(row[field] is None for row in rows):
                    status = "NOT_SEPARATELY_DISCLOSED_SCOPE"
                checks.append({"period": period, "kind": kind, "field": field, "status": status,
                               "observed_row_count": len(rows), "observed_values": list(dict.fromkeys(row[field] for row in rows)),
                               "observations": observations, "original_candidates": possible,
                               "scope_evidence": scope_evidence,
                               "limitation": "Combined notes and accounts receivable 156417885.43; not separable, no zero filling." if status == "NOT_SEPARATELY_DISCLOSED_SCOPE" else None})
    fully = [p for p in sorted(periods) if all(c["status"] == "PUBLIC_ORIGINAL_RECONCILED" for c in checks if c["period"] == p)]
    nonnull_reconciled = [p for p in sorted(periods) if all(any(o["status"] == "PUBLIC_ORIGINAL_RECONCILED" for o in c["observations"]) for c in checks if c["period"] == p)]
    version_comparison = []
    for check in checks:
        if check["period"] != "20181231":
            continue
        original = [x for x in check["original_candidates"] if x["doc_id"] == "1205826933" and x["context_verified"]]
        revised = [x for x in check["original_candidates"] if x["doc_id"] == "1205873809" and x["context_verified"]]
        version_comparison.append({"kind": check["kind"], "field": check["field"], "original_values": sorted(set(x["value_cny"] for x in original)), "revised_values": sorted(set(x["value_cny"] for x in revised)), "equal": bool(original and revised and set(x["value_cny"] for x in original) == set(x["value_cny"] for x in revised))})
    correction = next(doc for doc in inventory["documents"] if doc["doc_id"] == "1205873807")
    correction_text = BASE / "official/texts/20181231_1205873807.json"
    result = {
        "status": "OFFLINE_ORIGINAL_RECONCILIATION", "preparation_reference": preparation["reference"],
        "official_inventory_path": relative(inventory_path), "official_inventory_sha256": sha(inventory_path),
        "source_manifest": [{"kind": k, "path": relative(BASE / f"upstream/responses/{k}.json"), "sha256": sha(BASE / f"upstream/responses/{k}.json"), "rows": len(v)} for k, v in sources.items()],
        "checks_total": len(checks), "periods_total": len(periods),
        "status_counts": dict(Counter(c["status"] for c in checks)), "fully_reconciled_periods": fully,
        "periods_with_at_least_one_nonnull_match_for_each_field": nonnull_reconciled,
        "observation_status_counts": dict(Counter(o["status"] for c in checks for o in c["observations"])),
        "version_policy": "ALL_OBSERVED_ROWS_PRESERVED_NO_UPDATE_FLAG_SELECTION; per-value first matching issuer publication; selected catalogue scope is not exhaustive revision-history proof",
        "historical_vendor_pit": "FULL_VENDOR_PIT_UNVERIFIED",
        "currency": "CNY", "amount_tolerance_cny": "0.01",
        "method": "Match explicit financial row inside consolidated statement/current YTD column and RMB-yuan header; profit_dedt uses attributed key accounting table; preserve page/context/hash and every observed row.",
        "prohibitions": "No number-only full-text acceptance; no original backdating from revised documents; no null imputation; no vendor arrival claims.",
        "original_revision_comparison": {"period": "20181231", "original_doc_id": "1205826933", "original_publication": "2019-02-13", "revised_doc_id": "1205873809", "revised_publication": "2019-03-05", "nine_fields": version_comparison, "correction_notice": {"doc_id": correction["doc_id"], "pdf_path": correction["pdf_path"], "pdf_sha256": correction["sha256"], "publication_date": correction["publication_date"], "pages": [1, 2], "text_path": relative(correction_text), "text_sha256": sha(correction_text), "change_scope": "Omitted consolidated paid-in capital and capital reserve rows restored; notice states other report contents unchanged", "all_nine_core_fields_unchanged": all(x["equal"] for x in version_comparison)}, "initial_state_note": "Both publications precede 2019Q3 initial state. No changed audited core value is backdated; wider historical vendor revision coverage remains unverified."},
        "visual_review": {"scope": "Six complete pages rendered and visually inspected to resolve combined receivable scope, old four-column Q3 cumulative layout, modern Q3 amount/change columns, and 2025H1 null-vs-value", "pages": [{"doc_id": "1205505410", "period": "20180930", "pages": [9, 13, 14, 15]}, {"doc_id": "1218170801", "period": "20230930", "pages": [1]}, {"doc_id": "1224606149", "period": "20250630", "pages": [5]}], "preview_location": ".tmp/s014-original-audit", "limitation": "Other rows were reconciled using complete extracted page text plus statement/column context; this is not manual visual inspection of every PDF page."},
        "checks": checks,
    }
    out = BASE / "others/original_acceptance.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k in {"checks_total", "periods_total", "status_counts", "fully_reconciled_periods", "observation_status_counts"}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
