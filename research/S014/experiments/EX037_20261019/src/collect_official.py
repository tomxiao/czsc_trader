"""Immutable bounded CNInfo guidance catalogue and original fact collection."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OUT = EX / "others"
OFFICIAL = OUT / "official"
URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/", "X-Requested-With": "XMLHttpRequest"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def relative(path):
    return path.relative_to(ROOT).as_posix()


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def reserve(kind, request):
    folder = OFFICIAL / "requests" / kind
    folder.mkdir(parents=True, exist_ok=True)
    n = len(list(folder.glob("*.request.json"))) + 1
    catalogue_cap = 64 if (EX / "protocols/retrieval_amendment.json").exists() else 16
    assert n <= {"catalogue": catalogue_cap, "pdf": 48}[kind], "Request budget exhausted"
    path = folder / f"{n:03d}"
    save(path.with_suffix(".request.json"), dict(request, reserved_utc=datetime.now(timezone.utc).isoformat(), retry=False, allow_redirects=False))
    return path


def request_catalogue(name, start, end, keyword, category):
    import requests
    params = {"pageNum": 1, "pageSize": 30, "column": "sse", "tabName": "fulltext", "stock": "600722,gssh0600722", "searchkey": keyword, "secid": "", "plate": "sh", "category": category, "trade": "", "seDate": start + "~" + end, "sortName": "time", "sortType": "asc", "isHLtitle": "false"}
    receipt = reserve("catalogue", {"name": name, "url": URL, "params": params})
    result = {"name": name, "start": start, "end": end, "keyword": keyword, "category": category}
    try:
        response = requests.post(URL, data=params, headers=HEADERS, timeout=45, allow_redirects=False)
        path = OFFICIAL / "catalogues" / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(response.content)
        result.update(http_status=response.status_code, bytes=len(response.content), raw_path=relative(path), sha256=digest(path))
        response.raise_for_status()
        body = response.json()
        rows = body.get("announcements") or []
        ids = [r["announcementId"] for r in rows]
        dates = [datetime.fromtimestamp(r["announcementTime"] / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d") for r in rows]
        valid = all(r["secCode"] == "600722" and r["orgId"] == "gssh0600722" for r in rows) and all(start <= d <= end for d in dates)
        complete = valid and len(ids) == len(set(ids)) == body.get("totalAnnouncement") and not body.get("hasMore")
        result.update(status="RECEIVED", rows=len(rows), total=body.get("totalAnnouncement"), has_more=body.get("hasMore"), unique_ids=len(set(ids)), issuer_date_valid=valid, complete=complete)
        assert valid and len(ids) == len(set(ids)), "Invalid catalogue issuer/date/duplicate"
    except Exception as error:
        result.update(status="FAILED", error=type(error).__name__, detail=str(error), complete=False)
    save(receipt.with_suffix(".result.json"), result)
    return result


def catalogue():
    assert not (OFFICIAL / "selection.json").exists(), "Preserve completed catalogue; no implicit replay"
    assert digest(EX / "protocols/design.json") == "6f9ac4596b9650ec9d42cfaa7ec25106a7e858904d78ecd2ae5efe5fb21608a1"
    assert (EX / "protocols/published_design.json").exists()
    results = []
    for year in range(2019, 2027):
        results.append(request_catalogue(f"keyword_{year}", f"{year}-01-01", "2026-10-15" if year == 2026 else f"{year}-12-31", "业绩", ""))
    for year in (2019, 2021, 2023, 2025):
        results.append(request_catalogue(f"category_{year}_{year+1}", f"{year}-01-01", "2026-10-15" if year == 2025 else f"{year+1}-12-31", "", "category_yjyg_szsh;category_yjkb_szsh;"))
    # Only truncated scopes may consume the final four calls, with distinct date halves.
    resolved = {}
    for result in results:
        if result["status"] != "RECEIVED" or result["complete"]:
            continue
        start = datetime.fromisoformat(result["start"])
        end = datetime.fromisoformat(result["end"])
        midpoint = start + (end - start) // 2
        partitions = [(start, midpoint), (midpoint + timedelta(days=1), end)]
        children = []
        if len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))) + 2 > 16:
            continue
        for i, (left, right) in enumerate(partitions):
            children.append(request_catalogue(result["name"] + f"_split{i+1}", left.strftime("%Y-%m-%d"), right.strftime("%Y-%m-%d"), result["keyword"], result["category"]))
        resolved[result["name"]] = all(c["complete"] for c in children)
        results.extend(children)
    records = {}
    for result in results:
        if result["status"] != "RECEIVED":
            continue
        for row in read(ROOT / result["raw_path"]).get("announcements") or []:
            title = re.sub(r"<[^>]*>", "", row["announcementTitle"])
            if not re.search(r"业绩(?:预告|快报|预增|预减|预亏|预盈|预报)", title):
                continue
            day = datetime.fromtimestamp(row["announcementTime"] / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            item = {"doc_id": row["announcementId"], "title": title, "publication_date": day, "url": "https://static.cninfo.com.cn/" + row["adjunctUrl"], "catalogue_paths": [result["raw_path"]], "document_kind": "EXPRESS" if "快报" in title else "FORECAST", "version_kind": "CORRECTION_OR_SUPPLEMENT" if any(x in title for x in ("更正", "修正", "补充")) else "ORIGINAL_AS_LISTED"}
            if item["doc_id"] in records:
                records[item["doc_id"]]["catalogue_paths"].append(result["raw_path"])
            else:
                records[item["doc_id"]] = item
    documents = sorted(records.values(), key=lambda r: (r["publication_date"], r["doc_id"]))
    complete = all(r["complete"] or resolved.get(r["name"], False) for r in results)
    save(OFFICIAL / "selection.json", {"documents": documents})
    save(OUT / "catalogue_audit.json", {"status": "COMPLETE_SCOPED_CATALOGUE" if complete else "INCOMPLETE_SCOPED_CATALOGUE", "initial_queries": 12, "requests_used": len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))), "requests_cap": 16, "queries": results, "resolved_by_date_partitions": resolved, "admitted_documents": len(documents), "document_ids": [r["doc_id"] for r in documents], "scope": "2019-01-01..2026-10-15 CNInfo issuer600722 keyword业绩 and forecast/express categories, all matching corrections/supplements retained", "limitation": "No inference about unrelated titles or unavailable vendor vintages; empty old Tushare express or partial forecasts are not completeness evidence."})
    print(json.dumps({"catalogue_complete": complete, "documents": len(documents), "requests": len(results)}, ensure_ascii=True))


def download():
    import requests
    assert not (OFFICIAL / "download_inventory.json").exists(), "No implicit download replay"
    selected = read(OFFICIAL / "selection.json")["documents"]
    work = [(r, reserve("pdf", {"doc_id": r["doc_id"], "url": r["url"]})) for r in selected]
    def one(task):
        record, receipt = task
        result = dict(record)
        try:
            response = requests.get(record["url"], headers=HEADERS, timeout=60, allow_redirects=False)
            result.update(http_status=response.status_code, bytes=len(response.content))
            if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                raise ValueError("Not a successful PDF response")
            path = OFFICIAL / "pdfs" / (record["doc_id"] + ".pdf")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(response.content)
            result.update(status="PDF_RECEIVED", pdf_path=relative(path), pdf_sha256=digest(path))
        except Exception as error:
            result.update(status="FAILED", error=type(error).__name__, detail=str(error))
        save(receipt.with_suffix(".result.json"), result)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        documents = list(pool.map(one, work))
    save(OFFICIAL / "download_inventory.json", {"documents": documents})
    print(json.dumps({"documents": len(documents), "downloaded": sum(d["status"] == "PDF_RECEIVED" for d in documents)}, ensure_ascii=True))


def supplement():
    amendment = EX / "protocols/retrieval_amendment.json"
    assert digest(amendment) == "25c8328d9d7b3c51359114f63342b8802ab123f976c2f5d87f6ade912b51ab64"
    assert not (OUT / "catalogue_audit_v2.json").exists(), "Preserve supplemental audit"
    queries = []
    leaves = []
    for year in range(2019, 2027):
        for quarter in range(1, 5):
            start = datetime(year, 3 * quarter - 2, 1)
            end = datetime(year + (quarter == 4), 1 if quarter == 4 else 3 * quarter + 1, 1) - timedelta(days=1)
            end = min(end, datetime(2026, 10, 15))
            result = request_catalogue(f"full_{year}Q{quarter}", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), "", "")
            queries.append(result)
            if result["complete"] or result["status"] != "RECEIVED":
                leaves.append(result)
                continue
            if len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))) + 2 > 64:
                leaves.append(result)
                continue
            midpoint = start + (end - start) // 2
            for i, (left, right) in enumerate(((start, midpoint), (midpoint + timedelta(days=1), end))):
                child = request_catalogue(f"full_{year}Q{quarter}_split{i+1}", left.strftime("%Y-%m-%d"), right.strftime("%Y-%m-%d"), "", "")
                queries.append(child)
                leaves.append(child)
    all_records = {}
    for result in queries:
        if result["status"] != "RECEIVED":
            continue
        for row in read(ROOT / result["raw_path"]).get("announcements") or []:
            title = re.sub(r"<[^>]*>", "", row["announcementTitle"])
            item = {"doc_id": row["announcementId"], "title": title, "publication_date": datetime.fromtimestamp(row["announcementTime"] / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d"), "url": "https://static.cninfo.com.cn/" + row["adjunctUrl"], "catalogue_paths": [result["raw_path"]]}
            if item["doc_id"] in all_records:
                all_records[item["doc_id"]]["catalogue_paths"].append(result["raw_path"])
            else:
                all_records[item["doc_id"]] = item
    guidance = []
    candidates = []
    exclusions = []
    for item in all_records.values():
        title = item["title"]
        direct = bool(re.search(r"业绩(?:预告|快报|预增|预减|预亏|预盈|预报)", title))
        correction = any(word in title for word in ("更正", "修正", "澄清", "补充"))
        if direct:
            item.update(document_kind="EXPRESS" if "快报" in title else "FORECAST", version_kind="CORRECTION_OR_SUPPLEMENT" if correction else "ORIGINAL_AS_LISTED")
            guidance.append(item)
        elif correction:
            candidates.append(item)
        else:
            exclusions.append({"doc_id": item["doc_id"], "title": title, "reason": "No guidance/express or correction/clarification/supplement title; ordinary issuer metadata retained, body not read."})
    complete = all(r["complete"] for r in leaves)
    save(OFFICIAL / "selection_v2.json", {"documents": sorted(guidance, key=lambda r: (r["publication_date"], r["doc_id"])), "correction_title_candidates_pending_review": candidates})
    save(OUT / "catalogue_audit_v2.json", {"status": "COMPLETE_SCOPED_CATALOGUE" if complete else "INCOMPLETE_SCOPED_CATALOGUE", "complete": complete, "queries": queries, "requests_used": len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))), "requests_cap": 64, "leaf_scopes": [{k:r.get(k) for k in ("name", "start", "end", "complete", "raw_path", "rows", "unique_ids", "total", "has_more")} for r in leaves], "all_issuer_records": sorted(all_records.values(), key=lambda r: (r["publication_date"], r["doc_id"])), "all_issuer_ids": sorted(all_records), "title_review_exclusions": exclusions, "correction_title_candidates_pending_review": candidates, "guidance_ids": [r["doc_id"] for r in guidance], "limitations": ["Complete means actual issuer catalogue leaves under fixed coverage; not historical vendor snapshot completeness", "Correction/clarification/supplement title candidates require body review before no-prior-guidance certification"]})
    print(json.dumps({"complete": complete, "all_issuer_records": len(all_records), "guidance": len(guidance), "correction_title_candidates": candidates, "catalogue_requests_used": len(list((OFFICIAL / "requests/catalogue").glob("*.request.json")))}, ensure_ascii=True))


def extract():
    from pypdf import PdfReader
    records = read(OFFICIAL / "download_inventory.json")["documents"]
    for record in records:
        if record["status"] != "PDF_RECEIVED":
            continue
        source = ROOT / record["pdf_path"]
        assert digest(source) == record["pdf_sha256"]
        reader = PdfReader(source)
        pages = [{"page": i + 1, "text": page.extract_text() or ""} for i, page in enumerate(reader.pages)]
        target = OFFICIAL / "texts" / (record["doc_id"] + ".json")
        save(target, {"doc_id": record["doc_id"], "pdf_sha256": record["pdf_sha256"], "pages": pages})
        record.update(text_path=relative(target), text_sha256=digest(target), pages=len(pages), characters=sum(len(p["text"]) for p in pages))
    save(OFFICIAL / "inventory.json", {"documents": records, "catalogue_calls": len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))), "pdf_calls": len(list((OFFICIAL / "requests/pdf").glob("*.request.json"))), "retry": False, "redirect": False})
    print(json.dumps({"extracted": sum("text_path" in d for d in records), "documents": len(records)}, ensure_ascii=True))


def final_repair():
    """Use the six remaining allowed date splits, retaining prior audit snapshots."""
    previous = read(OUT / "catalogue_audit_v2.json")
    assert previous["requests_used"] == 58
    assert not (OUT / "catalogue_audit_v3.json").exists()
    queries = list(previous["queries"])
    leaves = []
    new_queries = []
    for leaf in previous["leaf_scopes"]:
        if leaf["complete"]:
            leaves.append(leaf)
            continue
        start = datetime.fromisoformat(leaf["start"])
        end = datetime.fromisoformat(leaf["end"])
        midpoint = start + (end - start) // 2
        for i, (left, right) in enumerate(((start, midpoint), (midpoint + timedelta(days=1), end))):
            result = request_catalogue(leaf["name"] + f"_split{i+1}", left.strftime("%Y-%m-%d"), right.strftime("%Y-%m-%d"), "", "")
            queries.append(result)
            new_queries.append(result)
            leaves.append(result)
    records = {r["doc_id"]: r for r in previous["all_issuer_records"]}
    for result in new_queries:
        if result["status"] != "RECEIVED":
            continue
        for row in read(ROOT / result["raw_path"]).get("announcements") or []:
            item = {"doc_id": row["announcementId"], "title": re.sub(r"<[^>]*>", "", row["announcementTitle"]), "publication_date": datetime.fromtimestamp(row["announcementTime"] / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d"), "url": "https://static.cninfo.com.cn/" + row["adjunctUrl"], "catalogue_paths": [result["raw_path"]]}
            if item["doc_id"] in records:
                records[item["doc_id"]]["catalogue_paths"].append(result["raw_path"])
            else:
                records[item["doc_id"]] = item
    guidance, review, exclusions = [], [], []
    for item in records.values():
        title = item["title"]
        if re.search(r"业绩(?:预告|快报|预增|预减|预亏|预盈|预报)", title):
            item.update(document_kind="EXPRESS" if "快报" in title else "FORECAST", version_kind="CORRECTION_OR_SUPPLEMENT" if any(w in title for w in ("更正", "修正", "补充", "澄清")) else "ORIGINAL_AS_LISTED")
            guidance.append(item)
        elif any(w in title for w in ("更正", "修正", "澄清", "补充")):
            review.append(item)
        else:
            exclusions.append({"doc_id": item["doc_id"], "title": title, "reason": "Ordinary issuer title without guidance/express or correction/clarification/supplement; metadata retained, no body expansion."})
    complete = all(r["complete"] for r in leaves)
    save(OFFICIAL / "selection_v3.json", {"documents": sorted(guidance, key=lambda r: (r["publication_date"], r["doc_id"])), "correction_title_candidates_pending_review": review})
    save(OUT / "catalogue_audit_v3.json", {"status": "COMPLETE_SCOPED_CATALOGUE" if complete else "INCOMPLETE_SCOPED_CATALOGUE", "complete": complete, "queries": queries, "requests_used": len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))), "requests_cap": 64, "leaf_scopes": leaves, "all_issuer_records": sorted(records.values(), key=lambda r: (r["publication_date"], r["doc_id"])), "all_issuer_ids": sorted(records), "title_review_exclusions": exclusions, "correction_title_candidates_pending_review": review, "guidance_ids": sorted(r["doc_id"] for r in guidance), "limitations": ["Full issuer date-leaf catalogue completeness, not unavailable historical vendor snapshots", "Correction titles reviewed in separate guidance_facts.json before no-prior-guidance claim"]})
    print(json.dumps({"complete": complete, "records": len(records), "guidance": len(guidance), "review_candidates": review, "incomplete_leaves": [r for r in leaves if not r["complete"]]}, ensure_ascii=True))


def facts():
    """Source-verified transcriptions; no outcome classification or market calculations."""
    inventory = read(OFFICIAL / "inventory.json")
    catalogue = read(OUT / "catalogue_audit_v3.json")
    # These transcriptions must match the actual detailed numbered forecast sentence.
    transcriptions = {
        "1205806238": ("20181231", "5,800.00", "2019-01-29", "二〇一九年一月二十九日"),
        "1209202480": ("20201231", "1,000", "2021-01-28", "二〇二一年一月二十八日"),
        "1212276492": ("20211231", "4,832.43", "2022-01-26", "二〇二二年一月二十六"),
        "1212897267": ("20220331", "1,230.57", "2022-04-13", "二〇二二年四月十三日"),
        "1214822760": ("20220930", "3,760.91", "2022-10-19", "二〇二二年十月十九日"),
        "1222379567": ("20241231", "5,719.80", "2025-01-21", "二〇二五年一月二十一日"),
    }
    result = []
    for document in inventory["documents"]:
        assert document["status"] == "PDF_RECEIVED"
        assert digest(ROOT / document["pdf_path"]) == document["pdf_sha256"]
        assert digest(ROOT / document["text_path"]) == document["text_sha256"]
        pages = read(ROOT / document["text_path"])["pages"]
        period, amount, signature, signature_text = transcriptions[document["doc_id"]]
        compact_pages = [re.sub(r"\s+", "", p["text"]) for p in pages]
        period_phrase = f"{period[:4]}年1月1日至{period[:4]}年{int(period[4:6])}月{int(period[6:])}日"
        assert any(period_phrase in text for text in compact_pages), (document["doc_id"], "YTD period not reconciled")
        number = amount.replace(",", "")
        phrase = "归属于上市公司股东的净利润为" + number + "万元左右"
        candidates = [i for i, text in enumerate(compact_pages) if phrase in text.replace(",", "")]
        assert candidates, (document["doc_id"], "Numeric accounting scope not found")
        # Chinese zero is sometimes encoded as〇/○/零; retain the actual text in the evidence.
        normalized_signature = signature_text.translate(str.maketrans({"〇": "零", "○": "零", "O": "零", "0": "零"}))
        signature_found = any(normalized_signature in text.translate(str.maketrans({"〇": "零", "○": "零", "O": "零", "0": "零"})) for text in compact_pages)
        assert signature_found, (document["doc_id"], "Signature not reconciled")
        index = candidates[0]
        text = compact_pages[index]
        text.replace(",", "").index(phrase)
        # Store both the complete original page and a whitespace-normalized literal accounting snippet.
        snippets = [{"page": pages[index]["page"], "text": pages[index]["text"], "selection": "Full original page retains numbered period, current parent profit, unit and approximate qualifier"}, {"page": pages[-1]["page"], "text": pages[-1]["text"][-400:], "selection": "Original signature and formal-report caveat"}]
        value = Decimal(number) * Decimal(10000)
        quantum = Decimal(10) ** Decimal(Decimal(number).as_tuple().exponent) * Decimal(10000)
        result.append({"doc_id": document["doc_id"], "period": period, "kind": document["document_kind"], "source_day": max(document["publication_date"], signature), "publication_date": document["publication_date"], "signature_date": signature, "signature_date_text": signature_text, "title": document["title"], "url": document["url"], "pdf_path": document["pdf_path"], "pdf_sha256": document["pdf_sha256"], "text_path": document["text_path"], "text_sha256": document["text_sha256"], "pages": [p["page"] for p in pages], "parent_profit_low_cny": format(value, "f"), "parent_profit_high_cny": format(value, "f"), "printed_quantum_low_cny": format(quantum, "f"), "printed_quantum_high_cny": format(quantum, "f"), "approximate_point": True, "has_explicit_numeric_interval": False, "admission_status": "ADMITTED", "replacement_doc_ids": [], "replacement_relation": "NONE_STATED; no same-period replacement stated in retrieved scoped records; global catalogue gap explicit", "accounting_scope": "PARENT_ATTRIBUTABLE_YTD", "currency": "CNY", "unit": "万元", "original_amount_text": amount + "万元左右", "printed_precision_basis": "Detailed numbered current-period parent-attributable profit sentence; not prior-year, deducted-profit or prominent rounded headline", "uncertainty": "Approximate single point; low/high equality stores numeric point only, not a hard guidance interval", "period_start": period[:4] + "-01-01", "period_end": period[:4] + "-" + period[4:6] + "-" + period[6:], "snippets": snippets, "unknown_reasons": []})
    assert set(transcriptions) == {r["doc_id"] for r in inventory["documents"]}
    review = []
    for candidate in catalogue["correction_title_candidates_pending_review"]:
        if candidate["doc_id"] == "1205873807":
            existing = read(ROOT / "research/S014/materials/20261019_financial_readiness/official/inventory_v2.json")
            doc = next(r for r in existing["documents"] if r["doc_id"] == candidate["doc_id"])
            assert digest(ROOT / doc["pdf_path"]) == doc["sha256"]
            content = read(ROOT / doc["text_path"])
            text = "".join(p["text"] for p in content["pages"])
            assert "股本" in text and "资本公积" in text
            review.append(dict(candidate, decision="NOT_GUIDANCE_REPLACEMENT", reason="2018 annual report omitted share capital and capital reserve; original/readiness verification shows no change to9 core profit/cash/asset fields; not an earnings forecast revision", reused_pdf_path=doc["pdf_path"], reused_pdf_sha256=doc["sha256"], reused_text_path=doc["text_path"], reused_text_sha256=doc["text_sha256"], text_snippets=[{"page": p["page"], "text": p["text"]} for p in content["pages"]]))
        elif any(word in candidate["title"] for word in ("股份转让", "法律意见书", "表决权委托")):
            review.append(dict(candidate, decision="EXCLUDED_BY_EXPLICIT_NON_FINANCIAL_SUBJECT", reason="Title explicitly addresses share transfer/control/legal acquisition procedure; not guidance/profit/financial amount correction. No unrelated body accessed."))
        else:
            review.append(dict(candidate, decision="UNKNOWN_REQUIRES_ORIGINAL_REVIEW", reason="Ambiguous correction title"))
    complete = catalogue["complete"] and all(r["decision"] != "UNKNOWN_REQUIRES_ORIGINAL_REVIEW" for r in review)
    save(OUT / "guidance_facts.json", {"status": "ADMITTED_SOURCE_FACTS_WITH_APPROXIMATE_POINT_LIMITS", "facts": result, "catalogue_completeness": {"complete": complete, "audit_path": relative(OUT / "catalogue_audit_v3.json"), "audit_sha256": digest(OUT / "catalogue_audit_v3.json"), "original_incomplete_audit_preserved": relative(OUT / "catalogue_audit.json"), "correction_title_review": review}, "fact_counts": {"documents": len(result), "admitted": sum(r["admission_status"] == "ADMITTED" for r in result), "approximate_points": sum(r["approximate_point"] for r in result), "explicit_numeric_intervals": sum(r["has_explicit_numeric_interval"] for r in result), "express": sum(r["kind"] == "EXPRESS" for r in result)}, "budget": {"catalogue_used": len(list((OFFICIAL / "requests/catalogue").glob("*.request.json"))), "catalogue_cap": 64, "pdf_used": len(list((OFFICIAL / "requests/pdf").glob("*.request.json"))), "pdf_cap": 48, "new_tushare_calls": 0, "retry": False, "redirect": False}, "limitations": ["All six amounts explicitly say左右; never convert point estimates into hard guidance bounds", "No full historical vendor vintage certification", "Complete official catalogue is scoped to issuer/window and does not prove analyst or other news expectations absent", "One2018annual guidance predates evaluation report periods, retained as corpus context, not silently discarded"]})
    print(json.dumps({"facts": len(result), "complete": complete, "approximate_points": len(result), "explicit_intervals": 0, "correction_reviews": len(review)}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("catalogue", "supplement", "final_repair", "download", "extract", "facts"))
    {"catalogue": catalogue, "supplement": supplement, "final_repair": final_repair, "download": download, "extract": extract, "facts": facts}[parser.parse_args().action]()
