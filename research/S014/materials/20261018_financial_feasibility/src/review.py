"""Independent offline receipt, scope, Decimal identity and link checks."""
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]


def read(p):
    return json.loads(p.read_bytes())


def main():
    assertions = []
    def check(name, condition):
        assertions.append({"name": name, "pass": bool(condition)})
    source_hashes = {}
    records = {}
    for number, api in enumerate(["income", "balancesheet", "cashflow", "fina_indicator", "forecast", "express"], 1):
        receipt = read(OUT / f"attempts/call_{number:02d}.json")
        spec = read(OUT / f"requests/{number:02d}_{api}.json")
        check(f"{api}_one_counted_request", receipt["http_requests"] == 1 and receipt["api"] == api)
        check(f"{api}_scope", receipt["params"] == spec["params"] == {"ts_code": "600722.SH", "start_date": "20200101", "end_date": "20261015"})
        check(f"{api}_success", receipt["http_status"] == 200 and receipt["vendor_code"] == 0)
        for label in ["response", "csv"]:
            path = ROOT / receipt[label + "_path"]
            check(f"{api}_{label}_hash", sha256(path.read_bytes()).hexdigest() == receipt[label + "_sha256"])
        t = read(ROOT / receipt["response_path"])
        rows = [dict(zip(t["fields"], r)) for r in t["items"]]
        records[api] = rows
        check(f"{api}_rows", len(rows) == receipt["rows"])
        check(f"{api}_symbol_dates", all(r["ts_code"] == "600722.SH" and "20200101" <= r["ann_date"] <= "20261015" for r in rows))
        if api in ["income", "balancesheet", "cashflow"]:
            check(f"{api}_type", all(r["report_type"] == "1" and r["comp_type"] == "1" for r in rows))
    check("exactly_six_attempts", len(list((OUT / "attempts").glob("call_*.json"))) == 6)
    for api, expected_rows, expected_periods in [("income", 37, 27), ("balancesheet", 37, 27), ("cashflow", 41, 27), ("fina_indicator", 43, 26), ("forecast", 5, 5), ("express", 0, 0)]:
        check(api + "_cardinality", len(records[api]) == expected_rows and len({r["end_date"] for r in records[api]}) == expected_periods)
    for i, row in enumerate(records["income"]):
        d = lambda k: Decimal(str(row[k]))
        check(f"decimal_profit_identity_{i}", abs(d("n_income") - d("n_income_attr_p") - d("minority_gain")) <= Decimal("0.02"))
    original = read(OUT / "others/original_checks.json")
    check("original_checks", original["status"] == "PASS" and len(original["sources"]) == 4 and len(original["checks"]) == 16)
    check("original_dates_and_amounts", all(x["amount_present"] and x["date_matches"] for x in original["checks"]))
    inv = read(OUT / "others/inventory.json")
    check("arithmetic_checks", inv["checks_passed"] == inv["checks_total"] == 53)
    check("samekey_nonnull_values", all(q["conflicting_nonnull_groups"] == 0 for q in inv["queries"]))
    check("two_null_only_groups", sum(q["null_vs_value_groups"] for q in inv["queries"]) == 2)
    ledger = read(OUT / "others/disclosure_ledger.json")
    check("ledger_source_rows", len(ledger) == sum(len(v) for v in records.values()))
    check("no_same_day_use", all(r["date_eligible"] and r["proposed_first_decision_date"] > r["public_date_anchor"] for r in ledger))
    check("time_limitations_explicit", all("NOT_CERTIFIED" in r["time_status"] for r in ledger))
    plan = read(OUT / "proposal.json")
    check("no_economic_execution", all(plan[k] == 0 for k in ["new_fits", "new_labels", "new_accounts", "new_supported_components", "new_qualified_candidates"]))
    check("boundaries", plan["platform_changed"] is False and plan["research_input_ready"] is False and plan["fees_execution_annual_targets"] == "UNCHANGED")
    for rel in ["packages/dataflows/src/dataflows/contract.py", "packages/dataflows/src/dataflows/tushare_fundamentals.py", "research/S014/experiments/EX012_20261017/protocols/report.md"]:
        source_hashes[rel] = sha256((ROOT / rel).read_bytes()).hexdigest()
    report = (OUT / "report.md").read_text(encoding="utf-8")
    for link in re.findall(r"\]\(([^)]+)\)", report):
        if link.startswith("https://"):
            continue
        target = (OUT / link).resolve()
        check("relative_link_" + link, not Path(link).is_absolute() and target.is_relative_to(ROOT) and (target.is_file() or link in ["publication.json", "others/review.json"]))
    hashes = {p.relative_to(OUT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob("*")) if p.is_file() and p.name not in ["review.json", "publication.json"] and "__pycache__" not in p.parts}
    result = {"status": "PASS" if all(x["pass"] for x in assertions) else "FAIL", "checks_total": len(assertions),
              "checks_passed": sum(x["pass"] for x in assertions), "assertions": assertions,
              "artifact_sha256": hashes, "source_sha256": source_hashes,
              "scope": "Offline data feasibility and evidence consistency only; no strategy or financial predictiveness acceptance"}
    (OUT / "others/review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["status", "checks_total", "checks_passed"]}))
    assert result["status"] == "PASS", [x["name"] for x in assertions if not x["pass"]]


if __name__ == "__main__":
    main()
