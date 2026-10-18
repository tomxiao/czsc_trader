"""Bounded, immutable official financial document retrieval for S014."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[3]
OUT = BASE / "official"
URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/", "X-Requested-With": "XMLHttpRequest"}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def relative(path):
    return path.relative_to(ROOT).as_posix()


def reserve(kind, request):
    folder = OUT / "requests" / kind
    folder.mkdir(parents=True, exist_ok=True)
    count = len(list(folder.glob("*.request.json")))
    adjustment = BASE / "retrieval_adjustment.json"
    cap = {"catalogue": 16 if adjustment.exists() else 12, "pdf": 48}[kind]
    if count >= cap:
        raise RuntimeError(f"{kind} request cap exhausted")
    path = folder / f"{count + 1:03d}"
    save(path.with_suffix(".request.json"), dict(request, reserved_at_utc=datetime.now(timezone.utc).isoformat(), auto_retry=False, allow_redirects=False))
    return path


def catalogue():
    import requests
    if (OUT / "selection.json").exists():
        raise RuntimeError("Preserve completed selection; no implicit request replay")
    seen_page_ids = set()
    for group, category, keyword in [
        ("financial", "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh;", ""),
        ("correction", "", "更正"),
        ("supplement", "", "补充"),
    ]:
        page = 1
        while True:
            params = {"pageNum": page, "pageSize": 100, "column": "sse", "tabName": "fulltext", "stock": "600722,gssh0600722", "searchkey": keyword, "secid": "", "plate": "sh", "category": category, "trade": "", "seDate": "2018-07-01~2026-10-15", "sortName": "time", "sortType": "asc", "isHLtitle": "false"}
            receipt = reserve("catalogue", {"group": group, "url": URL, "params": params})
            result = {"group": group}
            try:
                response = requests.post(URL, data=params, headers=HEADERS, timeout=45, allow_redirects=False)
                raw = OUT / "catalogues" / f"{group}_{page}.json"
                raw.parent.mkdir(parents=True, exist_ok=True)
                with raw.open("xb") as stream:
                    stream.write(response.content)
                result.update(http_status=response.status_code, bytes=len(response.content), raw_path=relative(raw), sha256=sha256(response.content).hexdigest())
                response.raise_for_status()
                body = response.json()
                rows = body.get("announcements") or []
                identities = tuple(row["announcementId"] for row in rows)
                result.update(status="RECEIVED", total=body.get("totalAnnouncement"), rows=len(rows), has_more=body.get("hasMore"))
                save(receipt.with_suffix(".result.json"), result)
                if identities in seen_page_ids:
                    raise RuntimeError("Official endpoint repeated a page despite distinct pageNum; stop without further requests")
                seen_page_ids.add(identities)
                if not body.get("hasMore"):
                    break
                page += 1
            except Exception as error:
                result.update(status="FAILED", error=type(error).__name__, detail=str(error))
                if not receipt.with_suffix(".result.json").exists():
                    save(receipt.with_suffix(".result.json"), result)
                raise
    build_selection()


def supplement():
    import requests
    if (OUT / "selection_v2.json").exists():
        raise RuntimeError("Preserve completed supplemental selection; no implicit request replay")
    adjustment = BASE / "retrieval_adjustment.json"
    assert adjustment.exists(), "Explicit new bounded request decision required"
    prior_ids = {tuple(r["announcementId"] for r in json.loads(p.read_text(encoding="utf-8")).get("announcements") or []) for p in (OUT / "catalogues").glob("*.json")}
    tasks = [
        ("financial_later_a", "2022-07-01~2023-12-31", "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh;", ""),
        ("financial_later_b", "2024-01-01~2026-10-15", "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh;", ""),
        ("correction", "2018-07-01~2026-10-15", "", "更正"),
        ("supplement", "2018-07-01~2026-10-15", "", "补充"),
    ]
    for group, date_range, category, keyword in tasks:
        params = {"pageNum": 1, "pageSize": 30, "column": "sse", "tabName": "fulltext", "stock": "600722,gssh0600722", "searchkey": keyword, "secid": "", "plate": "sh", "category": category, "trade": "", "seDate": date_range, "sortName": "time", "sortType": "asc", "isHLtitle": "false"}
        receipt = reserve("catalogue", {"group": group, "url": URL, "params": params, "adjustment": relative(adjustment)})
        result = {"group": group}
        try:
            response = requests.post(URL, data=params, headers=HEADERS, timeout=45, allow_redirects=False)
            raw = OUT / "catalogues" / f"{group}.json"
            with raw.open("xb") as stream:
                stream.write(response.content)
            result.update(http_status=response.status_code, bytes=len(response.content), raw_path=relative(raw), sha256=sha256(response.content).hexdigest())
            response.raise_for_status()
            body = response.json()
            rows = body.get("announcements") or []
            identities = tuple(r["announcementId"] for r in rows)
            result.update(status="RECEIVED", total=body.get("totalAnnouncement"), rows=len(rows), has_more=body.get("hasMore"), complete=len(rows) == body.get("totalAnnouncement"))
            if identities in prior_ids and identities:
                result["status"] = "DUPLICATE_RESPONSE_STOP"
            save(receipt.with_suffix(".result.json"), result)
            if result["status"] == "DUPLICATE_RESPONSE_STOP":
                raise RuntimeError("Distinct date/keyword query returned previously seen IDs; stop")
            prior_ids.add(identities)
        except Exception as error:
            if not receipt.with_suffix(".result.json").exists():
                result.update(status="FAILED", error=type(error).__name__, detail=str(error))
                save(receipt.with_suffix(".result.json"), result)
            raise
    build_selection(revision=True)


def build_selection(revision=False):
    records = {}
    sources = []
    for path in sorted((OUT / "catalogues").glob("*.json")):
        sources.append((path, json.loads(path.read_text(encoding="utf-8")).get("announcements") or []))
    reused = ROOT / "research/S014/experiments/EX012_20261017/others/cninfo_requests.json"
    prior = json.loads(reused.read_text(encoding="utf-8"))
    # Filter titles before reusing only financial records; do not inspect unrelated bodies.
    rows = [{"secCode": "600722", "orgId": r["org_id"], "announcementId": r["announcement_id"], "announcementTitle": r["title"], "announcementTime": r["epoch_ms"], "adjunctUrl": r["url"].removeprefix("https://static.cninfo.com.cn/")} for r in prior["catalogue"] if re.search(r"(年度报告|季度报告|年年报|年半年报|年一季报|年三季报)", r["title"]) and "业绩说明会" not in r["title"]]
    sources.append((reused, rows))
    for path, rows in sources:
        for row in rows:
            assert row["secCode"] == "600722" and row["orgId"] == "gssh0600722"
            title = re.sub("<[^>]*>", "", row["announcementTitle"])
            financial = bool(re.search(r"(年度报告|半年度报告|季度报告|年年报|年半年报|年一季报|年三季报)", title))
            if not financial or any(x in title for x in ("董事会", "监事会", "事前认可", "独立意见", "审核意见", "内部控制", "问询函")):
                continue
            year = re.search(r"(20\d{2})年", title)
            if not year:
                continue
            year = int(year.group(1))
            suffix = "0630" if ("半年" in title or "中期" in title) else "0930" if ("第三" in title or "三季" in title) else "0331" if ("第一" in title or "一季" in title) else "1231"
            period = f"{year}{suffix}"
            if not "20180630" <= period <= "20260630":
                continue
            date = datetime.fromtimestamp(row["announcementTime"] / 1000, timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            identity = row["announcementId"]
            record = {"doc_id": identity, "title": title, "period": period, "publication_date": date, "url": "https://static.cninfo.com.cn/" + row["adjunctUrl"], "catalogue_paths": [relative(path)], "version_kind": "CORRECTION_OR_REVISION" if any(x in title for x in ("更正", "修订", "补充")) else "ORIGINAL_AS_LISTED", "document_kind": "SUMMARY" if "摘要" in title else "FULL_OR_CORRECTION"}
            if identity in records:
                records[identity]["catalogue_paths"].append(relative(path))
            else:
                records[identity] = record
    all_records = sorted(records.values(), key=lambda r: (r["period"], r["publication_date"], r["doc_id"]))
    # Full reports contain the non-recurring profit field; summaries are only needed if full text lacks it.
    selected = [r for r in all_records if r["document_kind"] != "SUMMARY"]
    save(OUT / ("selection_v2.json" if revision else "selection.json"), {"all_financial_catalogue_records": all_records, "selected_documents": selected, "summary_selection": "DEFERRED_UNLESS_REQUIRED_FOR_FIELD", "selection_rule": "Financial report full texts and explicitly related corrections only; exclude general announcements and returns."})
    print(json.dumps({"all_financial": len(all_records), "selected": len(selected), "periods": len({r['period'] for r in selected}), "documents": selected}, ensure_ascii=False))


def download():
    import requests
    revision = (OUT / "selection_v2.json").exists()
    output = OUT / ("download_inventory_v2.json" if revision else "download_inventory.json")
    if output.exists():
        raise RuntimeError("Preserve download receipt; no implicit request replay")
    selection = json.loads((OUT / ("selection_v2.json" if revision else "selection.json")).read_text(encoding="utf-8"))["selected_documents"]
    previous = json.loads((OUT / "download_inventory.json").read_text(encoding="utf-8"))["documents"] if revision else []
    prior_ids = {r["doc_id"] for r in previous}
    work = []
    for item in selection:
        if item["doc_id"] in prior_ids:
            continue
        receipt = reserve("pdf", {"doc_id": item["doc_id"], "url": item["url"]})
        work.append((item, receipt))

    def one(task):
        item, receipt = task
        result = dict(item)
        try:
            response = requests.get(item["url"], headers=HEADERS, timeout=60, allow_redirects=False)
            result.update(http_status=response.status_code, bytes=len(response.content))
            if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                raise ValueError("Not a successful PDF response")
            path = OUT / "pdfs" / f"{item['period']}_{item['doc_id']}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(response.content)
            result.update(status="PDF_RECEIVED", pdf_path=relative(path), sha256=sha256(response.content).hexdigest())
        except Exception as error:
            result.update(status="FAILED", error=type(error).__name__, detail=str(error))
        save(receipt.with_suffix(".result.json"), result)
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, work))
    save(output, {"documents": previous + results})
    print(json.dumps({"selected": len(work), "received": sum(r["status"] == "PDF_RECEIVED" for r in results), "failed": [r for r in results if r["status"] != "PDF_RECEIVED"]}, ensure_ascii=False))


def extract():
    from pypdf import PdfReader
    revision = (OUT / "download_inventory_v2.json").exists()
    records = json.loads((OUT / ("download_inventory_v2.json" if revision else "download_inventory.json")).read_text(encoding="utf-8"))["documents"]
    for item in records:
        if item["status"] != "PDF_RECEIVED":
            continue
        pdf = ROOT / item["pdf_path"]
        assert sha256(pdf.read_bytes()).hexdigest() == item["sha256"]
        target = OUT / "texts" / f"{item['period']}_{item['doc_id']}.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            assert existing["pdf_sha256"] == item["sha256"]
            pages = existing["pages"]
        else:
            reader = PdfReader(pdf)
            pages = [{"page": i + 1, "text": page.extract_text() or ""} for i, page in enumerate(reader.pages)]
            save(target, {"doc_id": item["doc_id"], "pdf_sha256": item["sha256"], "extraction_library": "pypdf", "pages": pages})
        item.update(text_path=relative(target), text_sha256=sha256(target.read_bytes()).hexdigest(), page_count=len(pages), characters=sum(len(p["text"]) for p in pages))
    catalogue_results = [json.loads(p.read_text(encoding="utf-8")) for p in (OUT / "requests/catalogue").glob("*.result.json")]
    save(OUT / ("inventory_v2.json" if revision else "inventory.json"), {"documents": records, "source": "CNInfo official issuer financial disclosures", "catalogue_completeness": {"financial_category_and_title_correction_supplement_queries": catalogue_results, "limitation": "Initial 12 paginated requests repeated the first page; subsequent date-bounded queries recorded separately. Covers retrieved catalogue only; not proof of first vendor ingestion or all earlier versions outside official catalogue."}, "request_budget": {"catalogue_used": len(list((OUT / "requests/catalogue").glob("*.request.json"))), "catalogue_cap": 16 if (BASE / "retrieval_adjustment.json").exists() else 12, "pdf_used": len(list((OUT / "requests/pdf").glob("*.request.json"))), "pdf_cap": 48, "retry": False, "redirect": False}})
    print(json.dumps({"documents": len(records), "periods": len({r["period"] for r in records}), "extracted": sum("text_path" in r for r in records)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("catalogue", "supplement", "selection", "download", "extract"))
    action = parser.parse_args().action
    {"catalogue": catalogue, "supplement": supplement, "selection": build_selection, "download": download, "extract": extract}[action]()
