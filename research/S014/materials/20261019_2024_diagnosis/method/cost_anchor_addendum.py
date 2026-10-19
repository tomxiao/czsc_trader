"""Document root's five fixed roles; historical metadata only, zero strategy replay."""

from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


old = json.loads((OUT / "prior_mechanism_inventory.json").read_bytes())
manifest = json.loads((OUT / "search_scope_manifest.json").read_bytes())
pattern = r"stop.?loss|cost.{0,20}(?:atr|stop)|entry.{0,25}atr|atr.{0,25}(?:entry|buy|cost)|buy.{0,25}atr|实际.{0,12}(?:成本|买价).{0,15}(?:ATR|波幅)|跌.{0,12}(?:ATR|波幅)|成本锚|止损"
hits = []
for item in manifest["files"]:
    path = ROOT / item["path"]
    assert digest(path) == item["sha256"]
    for number, line in enumerate(path.read_bytes().decode("utf-8-sig").split("\n"), 1):
        if re.search(pattern, line, re.IGNORECASE):
            hits.append({"path": item["path"], "line": number, "excerpt": line.rstrip("\r")})

formal_copy_proofs = []
for record in old["existing_mechanisms"]:
    locator = record["report_locator"]
    if locator["public_ref"] is not None:
        continue
    result_path = ROOT / "research/S014/experiments" / record["experiment"] / "others/result.json"
    result = json.loads(result_path.read_bytes())
    copy = result.get("report_copy")
    if copy and copy.get("sha256") == locator["sha256"]:
        formal = ROOT / copy["formal_report"]
        assert digest(formal) == locator["sha256"]
        assert formal.read_bytes() == (ROOT / locator["path"]).read_bytes()
        formal_copy_proofs.append({"local_report_path": locator["path"], "formal_delivery_report_path": copy["formal_report"], "sha256": locator["sha256"], "bytes_exact": True, "result_record": result_path.relative_to(ROOT).as_posix(), "result_record_sha256": digest(result_path), "not_an_individual_EvidenceRef": True})

value = {
    "status": "ROOT_FIVE_ARM_DEFINITION_RECORDED_BEFORE_NEW_SOURCE_OR_ACCOUNTS",
    "supersedes": "The earlier inventory's provisional four-cell recommendation is extended by one orthogonal single cost-stop arm. All historical evidence/earlier recommendation retained byte-identical.",
    "root_decision": "Root explicitly chose NET plus inclusive >=, rather than the reviewer's earlier gross strict> suggestion, before any new cost-stop coverage calculation/source/account. No choice made from target feature values or account outcomes.",
    "prior_inventory_path": (OUT / "prior_mechanism_inventory.json").relative_to(ROOT).as_posix(),
    "prior_inventory_sha256": digest(OUT / "prior_mechanism_inventory.json"),
    "bounded_search_pattern": pattern,
    "bounded_search_file_count": len(manifest["files"]),
    "search_hits": hits,
    "prior_exact_cost_stop": "No complete actual-entry-net-cost loss >= current priorATR20 fixed action found in the reviewed476 source/report/design files. Keyword absence alone is not universal proof; inspected related implementations confirm different action definitions.",
    "nearest_prior_rules_and_differences": [
        {"prior": "EX005 true-range/ATR amplitude prediction", "difference": "Forecasts magnitude; explicitly no stop guarantee or buy/sell action."},
        {"prior": "EX007 current mark/Closepeak giveback/ATR holding features", "difference": "One-time midpoint conditional prediction, no fixed net-cost1ATR policy; model negative/limited results retained."},
        {"prior": "EX014 -3% adverse diagnostic", "difference": "Explicit loss-description line, not a tested stop order or cost-anchor policy."},
        {"prior": "EX024 N first supportbreak nonpositive P", "difference": "Needs a first S5 break and freezes one decision; a losing actual cost while rollingS5 still intact is outside that rule."},
        {"prior": "EX043 PROFIT_GIVEBACK", "difference": "Needs actual observed Closepeak netgain >=2ATR then gross peakdrawdown>=1ATR; direct post-buy loss without a prior profitable runup is not covered."},
        {"prior": "EX043 SHOCK_PROFIT", "difference": "Requires current double-fee netP>0; cannot handle any existing loss even if Z>2."},
    ],
    "fixed_five_cells": [
        {"index": 0, "entry_guard": "OFF", "exit_domain": "PROFIT_ONLY", "cost_stop": "OFF", "role": "fresh source strict economic control against EX043run004 ENTRY_GRACE/SHOCK_PROFIT"},
        {"index": 1, "entry_guard": "ON", "exit_domain": "PROFIT_ONLY", "cost_stop": "OFF", "role": "same Z used on candidateD before entry"},
        {"index": 2, "entry_guard": "OFF", "exit_domain": "ANY_P", "cost_stop": "OFF", "role": "same held Z removes current-profit restriction"},
        {"index": 3, "entry_guard": "ON", "exit_domain": "ANY_P", "cost_stop": "OFF", "role": "actual combined Z roles, no summing independent wealth differences"},
        {"index": 4, "entry_guard": "OFF", "exit_domain": "PROFIT_ONLY", "cost_stop": "CURRENT_ATR1", "role": "baseline plus cost anchor stop only, not combined with new Z roles"},
    ],
    "cost_stop_definition": {
        "formula": "lossprice_D = actual_entry_fill*(1+0.001) - C_D*(1-0.001); trigger when lossprice_D >= ATR20_prior_D",
        "scale": "same runtime HFQ price units for actual fill, Close, ATR; source ledger fill projected back by original anchor5.892 if auditing ledger values",
        "ATR": "original in-window arithmetic mean20 true ranges endingD-1, recomputed eachD; finite positive scale required; no entry-time volatility freeze",
        "eligible": "actualheld afterD fills, no inherited pendingSELL, before mandatory deadline, ATR known positive",
        "priority": "inherited pending/deadline > costrisk and existing shockrisk > ENTRY_GRACE support protection; retain original reservation/deadline anchors",
        "entryD": "May plan next-session SELL if newly filled entry already breaches this net-cost threshold; never same-day SELL and never execution at an already observed threshold price",
        "interpretation": "Falling ATR may create a trigger without a new price fall. This is a close-based exit signal, not an intraday price stop or guaranteed currency loss cap.",
        "fees": "Trigger includes buy and hypothetical marked sale costs; actual sale still uses original TXE future execution price and real per-side fees, so marked P is not realized profit.",
        "overlap_diagnostics": "Distinguish costrisk already coincident with baseline support/mandatory sale, costrisk that overrides grace, and costrisk truly new when baseline would continue. Count actualcycle once; no count inflation from multiple pendingD observations.",
    },
    "entry_guard_contract": "Gate acts at each original flat candidateD, vetoes new intent/accepted/target without an order, failedBUY or new anchor/reservation. Every later D re-evaluates original eligibility plus same gate; it is not cancel-one-then-permanently-wait.",
    "shared_D_known_and_missing_contract": "exact prior EX043 Z/ATR masks and in-window history; observed D Close only, actual fill cost, real held/pending/reservation; raw unknown remains null and finite knownflag; unknown cannot satisfy a new guard/exit, no fallback/provider call",
    "economic_scope": "all five full original chronological funded paths; evaluate2020..2025 own-opening yearly goals and original frequency,2026 technical tail only. All years already seen; no blind-validation claim, no per-year branch.",
    "current_stage": "method only; wait root source/design/protocol review then new experiment implementation and pure synthetic checks; no realaccount dispatch authorized by this file",
    "formal_delivery_report_copy_proofs": formal_copy_proofs,
    "cost_review_source_sha256": digest(Path(__file__)),
    "new_market_reads": 0,
    "new_state_PnL_calculations": 0,
    "new_strategy_replays": 0,
    "new_account_dispatches": 0,
    "new_fits": 0,
}
write("cost_anchor_addendum.json", value)
print("COST_METHOD_WRITTEN", len(hits), "historical keyword hits; exact fixed policy not found")
