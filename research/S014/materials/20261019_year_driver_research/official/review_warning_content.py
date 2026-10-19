"""Reproduce a source-only manual content review; never opens return/W files."""
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
INVENTORY = OUT / "events_2020_2025.json"
INVENTORY_SHA = "01fc106f518f875808500493282c29856e2d006dd42db52d5563abb26569c5bc"
MAIN_PAGES = {
    "1209265667": None, "1209270106": 2, "1209284985": 2, "1209290294": 2,
    "1209295967": 2, "1209337725": 2, "1211095274": 2, "1211164972": 2,
    "1213137037": 2, "1219998013": 2, "1221919496": 2, "1223888518": 2,
    "1223900435": 1, "1223910887": 2,
}
EXTRA_QUOTES = {
    "1211095274": [(1, "公司本次非公开发行相关工作正在持续推进，相关审计、评估等工作尚未完成。")],
    "1211164972": [(1, "公司本次非公开发行相关工作正在持续推进，相关审计、评估等工作尚未完成。")],
    "1213137037": [(1, "在公司原甲醇主营业务基础上，进入玻璃纤维行业"),
                   (2, "本次非公开发行股票相关事项尚需中国证监会核准方可实施。")],
}


def require(value, message):
    if not value:
        raise ValueError(message)


def normalize(text):
    return re.sub(r"\s+", "", text)


def quote(pages, page, text):
    normalized = normalize(pages[page])
    query = normalize(text)
    require(query in normalized, f"Manual quotation not found on page {page}: {query}")
    start = normalized.index(query)
    return {"page": page, "company_statement_normalized_quote": query,
            "normalized_start": start, "normalized_end": start + len(query),
            "normalization": "Unicode whitespace removal only; punctuation unchanged",
            "original_page_text_utf8_sha256": sha256(pages[page].encode("utf-8")).hexdigest()}


def main():
    output = OUT / "warning_content_review.json"
    require(not output.exists(), "Preserve existing review; no overwrite")
    raw = INVENTORY.read_bytes()
    require(sha256(raw).hexdigest() == INVENTORY_SHA, "Reviewed official inventory changed")
    inventory = json.loads(raw)
    events = inventory["events"]
    require(len(events) == 14 and {e["doc_id"] for e in events} == set(MAIN_PAGES), "Wrong review population")
    records = []
    for event in events:
        identity = event["original_body"]
        pdf_path, text_path = ROOT / identity["pdf_path"], ROOT / identity["text_path"]
        pdf_raw, text_raw = pdf_path.read_bytes(), text_path.read_bytes()
        require(len(pdf_raw) == identity["bytes"] and sha256(pdf_raw).hexdigest() == identity["sha256"],
                "Original PDF byte identity differs")
        require(pdf_raw.startswith(b"%PDF"), "Original body is not a PDF")
        require(sha256(text_raw).hexdigest() == identity["text_sha256"], "Extracted text byte identity differs")
        text = json.loads(text_raw)
        require(text["doc_id"] == event["doc_id"], "Text/announcement identity differs")
        pages = {p["page"]: p["text"] for p in text["pages"]}
        require(sorted(pages) == list(range(1, identity["pages"] + 1)), "Page inventory differs")
        whole = "".join(normalize(pages[p]) for p in sorted(pages))
        page = MAIN_PAGES[event["doc_id"]]
        if page is None:
            main_status = "MAIN_BUSINESS_CHANGE_NOT_EXPLICITLY_STATED_IN_THIS_DOCUMENT"
            main_quotes = [quote(pages, 1, "经公司自查，公司目前生产经营活动正常。市场环境或行业政策没有发生重大调整、内部生产经营秩序正常。")]
            main_limit = "只明确生产经营正常及市场/行业政策无重大调整；不能补写成原文明确声明主营未变化。"
        else:
            main_status = "COMPANY_STATES_NO_MAJOR_CHANGE_TO_MAIN_BUSINESS_AND_NORMAL_OPERATIONS"
            main_quotes = [quote(pages, page, "主营业务未发生重大变化"),
                           quote(pages, page, "目前生产经营活动正常"),
                           quote(pages, page, "公司主营业务为甲醇的生产和销售，产能为20万吨/年")]
            main_limit = "公司关于主营和经营秩序的陈述；不等于所有基本面、利润、业务计划或股价驱动均无变化。"
        sales_category = "NOT_STATED"
        sales_quotes = []
        market_context = []
        if event["doc_id"] == "1209270106":
            market_context = [quote(pages, 2, "2021年初，甲醇市场价格有所回落，近期没有出现上涨趋势。")]
        elif event["doc_id"] in ("1223900435", "1223910887"):
            sales_category = "NO_LARGE_RECENT_CHANGE_COMPANY_STATEMENT"
            sales_quotes = [quote(pages, page, "近期公司甲醇销售价格没有较大变化。")]
            market_context = [quote(pages, page, "公司认为目前甲醇市场生产装置开工率较高，市场供给较为充足，而下游甲醇需求未发生重大变化")]
        if sales_category == "NOT_STATED":
            require("公司甲醇销售价格" not in whole, "Unreviewed explicit company-sales-price statement")
        prices = []
        for number, page_text in pages.items():
            prices.extend({"page": number, "normalized_text": m.group()}
                          for m in re.finditer(r"甲醇[^。；]{0,12}价格[^。；]{0,90}", normalize(page_text)))
        expected_price_mentions = 1 if event["doc_id"] in ("1209270106", "1223900435", "1223910887") else 0
        require(len(prices) == expected_price_mentions, "Unexpected methanol-price text needs manual review")
        extra = [quote(pages, p, q) for p, q in EXTRA_QUOTES.get(event["doc_id"], [])]
        records.append({
            "doc_id": event["doc_id"], "title": event["title"],
            "official_catalogue_publication_date": event["publication_date"], "url": event["url"],
            "catalogue_evidence_ref": event["catalogue_evidence_ref"],
            "body_identity": {"pdf_path": identity["pdf_path"], "pdf_bytes": len(pdf_raw), "pdf_sha256": identity["sha256"],
                              "text_path": identity["text_path"], "text_bytes": len(text_raw), "text_sha256": identity["text_sha256"],
                              "pages": identity["pages"],
                              "all_page_text_sha256": {str(p): sha256(pages[p].encode("utf-8")).hexdigest() for p in pages}},
            "issuer_main_business_and_operations_statement": {"status": main_status, "source_quotes": main_quotes,
                                                             "reviewer_scope_limit": main_limit},
            "issuer_recent_company_methanol_sales_price_statement": {"category": sales_category, "source_quotes": sales_quotes,
                "reviewer_scope_limit": "公司销售价与甲醇期货价、全市场价不是同一变量；未说明不等于价格没有变化。"},
            "issuer_methanol_market_context": {"source_quotes": market_context,
                "meaning": ("2021年初市场价格回落、近期无上涨趋势；不是公司实现销售价。" if event["doc_id"] == "1209270106"
                            else "公司对市场供需的判断，不是RSCH独立验证。") if market_context else None},
            "other_existing_disclosed_plans_that_limit_no_change_interpretation": extra,
            "reviewer_inference": "原文陈述本身不能证明公告导致任何股价或账户收益；本次不赋交易标签、不加入收益组。",
            "full_document_text_reviewed_for_these_two_questions": True,
            "all_methanol_price_mentions_context_check": prices,
        })
    summary = {
        "status": "COMPLETE_SOURCE_ONLY_QUALITATIVE_ADVERSARIAL_REVIEW",
        "source_inventory": {"path": INVENTORY.relative_to(ROOT).as_posix(), "sha256": INVENTORY_SHA, "bytes": len(raw)},
        "review_code": {"path": Path(__file__).relative_to(ROOT).as_posix(), "sha256": sha256(Path(__file__).read_bytes()).hexdigest()},
        "review_population": "All 14 existing 2020-2025 issuer abnormal-trading/risk-warning originals; no return-based selection",
        "records": records,
        "source_only_counts": {"documents": 14, "explicit_main_business_no_major_change": sum(MAIN_PAGES[x] is not None for x in MAIN_PAGES),
                               "recent_company_sales_price_no_large_change": 2, "company_sales_price_not_stated": 12,
                               "separate_market_price_decline_no_recent_uptrend_statement": 1},
        "reviewer_conclusions_distinct_from_issuer_statements": [
            "2021与2025原文均有主营未发生重大变化/生产经营正常的声明，不能预设2021盈利由经营改善而2025损失由炒作驱动。",
            "2021-02-18还称年初甲醇市场价格有所回落、近期无上涨趋势；这不是公司销售价格的陈述。",
            "2025-06-18及06-19明确近期公司甲醇销售价格没有较大变化；这是公司陈述，未独立核验实际销售合同或利润。",
            "2021年9月两份公告仍披露既存非公开发行计划推进；2022公告具体说明拟进军玻纤且待核准，不能把主营未变扩大为无任何公司事项。",
            "相似风险措辞可对应不同后续价格路径；仅凭这些原文不能识别2021与2025账户差异的因果来源。",
        ],
        "limitations": ["只审既有14份原文及其抽取文本中的两项内容，非公司全历史公告或基本面审计。",
                        "披露日沿用已核官方目录，不将PDF签署日或网页日期推定为历史首次公开/供应商到达时刻。",
                        "字节哈希确认原PDF与抽取文本身份；本次没有重新渲染逐页图像或认证OCR准确率。",
                        "无warning状态/收益文件读取，无账户/损益联结，无新效果估计、规则、模型、外部调用。"],
        "resources": {"new_W_flags": 0, "new_effect_estimates": 0, "new_source_calls": 0,
                      "new_accounts": 0, "new_fits": 0, "new_return_labels": 0},
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": summary["status"], "source_only_counts": summary["source_only_counts"],
                      "output_sha256": sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
