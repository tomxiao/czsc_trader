"""Offline source feasibility inventory. No price outcomes, fits or signals."""
from hashlib import sha256
from pathlib import Path
import io
import json

import pandas as pd

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]
CORE = {
    "income": ["revenue", "oper_cost", "n_income", "n_income_attr_p", "minority_gain"],
    "balancesheet": ["total_assets", "total_liab", "accounts_receiv", "inventories"],
    "cashflow": ["n_cashflow_act", "c_fr_sale_sg", "c_paid_goods_s"],
    "fina_indicator": ["profit_dedt", "q_dtprofit", "grossprofit_margin"],
    "forecast": ["net_profit_min", "net_profit_max", "first_ann_date"],
    "express": ["revenue", "n_income"],
}


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    inventory = read(ROOT / "research/S014/materials/20261018_action_value_method_review/inventory.json")
    cal_key = "research/S014/experiments/EX033_20261018/others/calendar.csv"
    cal_ref = EvidenceRef.from_dict(inventory["sources"][cal_key]["public_ref"])
    raw = cal_ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == cal_ref.sha256
    sessions = pd.read_csv(io.BytesIO(raw)).date.str.replace("-", "").tolist()
    assert len(sessions) == 1642 and len(set(sessions)) == 1642
    def available(day):
        return next((s for s in sessions if s > day), None)

    expected = [f"{y}{q}" for y in range(2020, 2027) for q in ["0331", "0630", "0930", "1231"] if f"{y}{q}" <= "20260630"]
    results, frames, ledger, conflicts, checks = [], {}, [], [], []
    receipts = sorted((OUT / "attempts").glob("call_*.json"))
    assert len(receipts) == 6
    for f in receipts:
        r = read(f)
        assert r["http_requests"] == 1
        api = r["api"]
        result = {"api": api, "status": r["status"], "http_status": r.get("http_status"), "vendor_code": r.get("vendor_code")}
        if "response_path" not in r:
            results.append(result)
            continue
        raw_path = ROOT / r["response_path"]
        assert sha256(raw_path.read_bytes()).hexdigest() == r["response_sha256"]
        table = read(raw_path)
        d = pd.DataFrame(table["items"], columns=table["fields"])
        frames[api] = d
        assert set(d.ts_code) <= {"600722.SH"}
        keys = [c for c in ["ts_code", "end_date", "ann_date", "f_ann_date", "report_type", "comp_type"] if c in d]
        vals = [c for c in d if c not in keys + ["update_flag"]]
        null_only, numeric_conflicts, duplicate_groups = 0, 0, 0
        for key, g in d.groupby(keys, dropna=False):
            duplicate_groups += int(len(g) > 1)
            differing = [c for c in vals if g[c].nunique(dropna=False) > 1]
            numeric_differing = [c for c in vals if g[c].nunique(dropna=True) > 1]
            if differing:
                record = {"api": api, "key": dict(zip(keys, key)), "differing_fields": differing,
                          "non_null_value_conflicts": numeric_differing,
                          "rows": json.loads(g.to_json(orient="records"))}
                conflicts.append(record)
                null_only += int(not numeric_differing)
                numeric_conflicts += int(bool(numeric_differing))
        for idx, row in d.iterrows():
            ds = [str(row[c]) for c in ["ann_date", "f_ann_date"] if c in d and pd.notna(row[c])]
            valid_dates = bool(ds) and all(len(x) == 8 and x.isdigit() for x in ds)
            anchor = max(ds) if valid_dates else None
            in_scope = bool(valid_dates and "20200101" <= anchor <= "20261015" and str(row.end_date) <= anchor)
            ledger.append({"api": api, "raw_row": int(idx), "report_period": row.end_date,
                           "ann_date": row.ann_date, "f_ann_date": row.get("f_ann_date"),
                           "report_type": row.get("report_type"), "update_flag": row.get("update_flag"),
                           "date_eligible": in_scope, "public_date_anchor": anchor,
                           "proposed_first_decision_date": available(anchor) if in_scope else None,
                           "proposed_decision_time": "15:00 Asia/Shanghai",
                           "time_status": "DATE_POLICY_ONLY_NOT_CERTIFIED_HISTORICAL_VERSION_OR_VENDOR_ARRIVAL",
                           "source_response_sha256": r["response_sha256"]})
        result.update(rows=len(d), unique_periods=int(d.end_date.nunique()), unique_ann_dates=int(d.ann_date.nunique()),
                      period_range=[d.end_date.min(), d.end_date.max()] if len(d) else None,
                      ann_range=[d.ann_date.min(), d.ann_date.max()] if len(d) else None,
                      missing_expected_2020Q1_2026Q2=sorted(set(expected) - set(d.end_date)),
                      missing_values={c: int(d[c].isna().sum()) for c in d if d[c].isna().any()},
                      duplicate_key_groups=duplicate_groups, null_vs_value_groups=null_only,
                      conflicting_nonnull_groups=numeric_conflicts,
                      complete_core_rows=int(d[CORE[api]].notna().all(axis=1).sum()),
                      periods_with_any_complete_core_row=int(d.loc[d[CORE[api]].notna().all(axis=1), "end_date"].nunique()))
        # 100 is deliberately conservative for statement/indicator truncation screening.
        result["at_conservative_row_cap"] = len(d) >= (100 if api in CORE and api not in ["forecast", "express"] else 2000)
        result["all_versions_complete"] = "UNVERIFIED"
        results.append(result)

    inc = frames["income"].drop_duplicates(subset=[c for c in frames["income"] if c != "update_flag"])
    for _, row in inc.iterrows():
        delta = float(row.n_income) - float(row.n_income_attr_p) - float(row.minority_gain)
        checks.append({"name": "consolidated_profit_equals_parent_plus_minority", "period": row.end_date,
                       "difference_yuan": delta, "pass": abs(delta) <= 0.02})
    # Core checks do not select update_flag=1 as historically correct.
    margin = frames["fina_indicator"][["end_date", "ann_date", "grossprofit_margin"]].drop_duplicates()
    for _, row in inc.iterrows():
        same = margin[(margin.end_date == row.end_date) & (margin.ann_date == row.ann_date)]
        if len(same) == 1:
            computed = (float(row.revenue) - float(row.oper_cost)) / float(row.revenue) * 100
            diff = computed - float(same.iloc[0].grossprofit_margin)
            checks.append({"name": "ytd_gross_margin_recomputed", "period": row.end_date,
                           "difference_percentage_points": diff, "pass": abs(diff) <= 0.011})
    common = sorted(set.intersection(*(set(frames[a].end_date) for a in ["income", "balancesheet", "cashflow", "fina_indicator"])))
    summary = {"status": "FEASIBILITY_COMPLETE_RESEARCH_INPUT_NOT_READY", "actual_http_calls": 6,
               "failed_calls": sum(r["status"] == "FAILED" for r in results), "empty_calls": sum(r["status"] == "EMPTY" for r in results),
               "nonempty_successes": sum(r["status"] == "RECEIVED" for r in results),
               "calendar_evidence": cal_ref.to_dict(), "queries": results, "same_key_value_differences": conflicts,
               "common_report_periods": common, "common_report_period_count": len(common),
               "income_distinct_disclosure_dates": sorted(set(inc.ann_date)),
               "checks": checks, "checks_passed": sum(c["pass"] for c in checks), "checks_total": len(checks),
               "no_pre2020_disclosure_request": True, "no_price_returns_loaded": True,
               "new_models": 0, "new_account_experiments": 0, "new_return_labels": 0,
               "limitations": ["No independent source proves all original historical versions",
                               "Same-date missing/value alternatives have no revision timestamps",
                               "2019 prewindow and 2019 annual indicators not requested",
                               "Empty express is not evidence of complete absence of issuer express announcements",
                               "No daily row multiplication constitutes new independent evidence"]}
    write(OUT / "others/inventory.json", summary)
    write(OUT / "others/disclosure_ledger.json", ledger)
    print(json.dumps({k: summary[k] for k in ["status", "actual_http_calls", "nonempty_successes", "empty_calls", "common_report_period_count", "checks_passed", "checks_total"]}))


if __name__ == "__main__":
    main()
