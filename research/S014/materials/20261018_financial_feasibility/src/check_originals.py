"""Reconcile four pre-existing official summaries with the bounded probe."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    refs = read(ROOT / "research/S014/experiments/EX012_20261017/others/result.json")["evidence"]
    docs = read(ROOT / "research/S014/experiments/EX012_20261017/protocols/annotations.json")["documents"]
    tables = {}
    for number, api in [(1, "income"), (3, "cashflow"), (4, "fina_indicator")]:
        t = read(OUT / f"responses/call_{number:02d}.json")
        tables[api] = [dict(zip(t["fields"], r)) for r in t["items"]]
    checks = []
    sources = {}
    for doc, period in [("D06", "20240630"), ("D12", "20241231"), ("D41", "20250630"), ("D57", "20260630")]:
        tr = EvidenceRef.from_dict(refs[f"ex012-texts-{doc}-json"])
        pr = EvidenceRef.from_dict(refs[f"ex012-originals-{doc}-pdf"])
        raw = tr.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == tr.sha256
        assert sha256(pr.resolve(ROOT).read_bytes()).hexdigest() == pr.sha256
        text = json.loads(raw)
        assert text["pdf_sha256"] == pr.sha256
        annotation = next(d for d in docs if d["doc_id"] == doc)
        sources[doc] = {"pdf": pr.to_dict(), "text": tr.to_dict(), "url": annotation["cninfo_url"], "date": annotation["date"]}
        for api, field in [("income", "revenue"), ("income", "n_income_attr_p"),
                           ("cashflow", "n_cashflow_act"), ("fina_indicator", "profit_dedt")]:
            selected = [r for r in tables[api] if r["end_date"] == period]
            values = sorted(set(r[field] for r in selected if r[field] is not None))
            assert len(values) == 1
            number = format(values[0], ",.2f")
            pages = [p["page"] for p in text["pages"] if number in p["text"]]
            dates = sorted(set(r["ann_date"] for r in selected))
            checks.append({"doc_id": doc, "report_period": period, "api": api, "field": field,
                           "amount_yuan": values[0], "formatted_amount": number, "matching_pages": pages,
                           "official_disclosure_date": annotation["date"], "vendor_ann_dates": dates,
                           "amount_present": bool(pages),
                           "date_matches": dates == [annotation["date"].replace("-", "")]})
    result = {"status": "PASS" if all(c["amount_present"] and c["date_matches"] for c in checks) else "FAIL",
              "sources": sources, "checks": checks,
              "scope": "Four already-held summaries; 16 amount/date comparisons. Exact amount presence plus page inspection, not full report audit.",
              "limitation": "Does not certify other periods, missing historical versions or vendor arrival times. Null-to-value changes remain unresolved except that D41 shows the 2025H1 deducted-profit amount publicly.",
              "new_upstream_calls": 0}
    (OUT / "others/original_checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "reports": 4, "amount_date_checks": len(checks)}))


if __name__ == "__main__":
    main()
