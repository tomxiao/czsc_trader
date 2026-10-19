"""Read local contracts and frozen S014 metadata; no price loads or strategy runs."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads((ROOT / path).read_bytes())


def identity(path):
    data = (ROOT / path).read_bytes()
    return {"path": path, "sha256": sha256(data).hexdigest(), "bytes": len(data)}


def locate(path, anchor):
    record = identity(path)
    lines = (ROOT / path).read_bytes().split(b"\n")
    hits = [(i + 1, line.decode("utf-8").rstrip("\r")) for i, line in enumerate(lines) if anchor in line.decode("utf-8")]
    assert hits, (path, anchor)
    record.update(anchor=anchor, line=hits[0][0], excerpt=hits[0][1], line_basis="LF-delimited bytes")
    return record


def write(name, value):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    srt = "packages/strategy_runtime/src/strategy_runtime/"
    source = "research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py"
    clock = "research/S014/experiments/EX045_20261019/src/strategy_runtime/strategies/blocked_clock_review.py"
    evidence = [
        locate(srt + "algorithm.py", "def calculate_history("),
        locate(srt + "strategy.py", "for name, value in row.items():"),
        locate(srt + "strategy.py", "build_execution_plan("),
        locate(srt + "execution_rules.py", "def _target_plan("),
        locate(srt + "execution_rules.py", 'execution_reference_price * (1 + float(entry["limit_parameter"]))'),
        locate(srt + "execution_rules.py", "price = min(requested, upper_guard) * request.price_scale"),
        locate(srt + "contracts.py", "class ExecutionState:"),
        locate(srt + "contracts.py", "class PortfolioSnapshot:"),
        locate(srt + "data.py", "def price_reference("),
        locate("src/czsc_trader/backtesting/benchmark_contracts.py", "class LimitBuyHold:"),
        locate(source, '"entry": {"order_type": "LIMIT", "limit_parameter": 0.01}'),
        locate(source, "OrderSpec(\"BUY\", \"LIMIT\", 100, intent[\"limit\"])"),
        locate(source, "cost_loss_price = entry_fill_price * (1 + 0.001) - close * (1 - 0.001)"),
        locate(source, "eligible and feature.atr_positive and cost_loss_price >= feature.atr20_prior"),
        locate(source, "if inherited or expired or risk_exit or ordinary_support:"),
        locate(clock, "reservation = i + 11"),
        locate("research/S014/experiments/EX022_20261018/protocols/account_report.md", "只改变首次可决策日"),
        locate("research/S014/experiments/EX029_20261018/protocols/account_report.md", "首次严格早于E+9收盘的破坏时"),
        locate("research/S014/experiments/EX007_20261017/protocols/report.md", "未组合为连续停止策略"),
    ]
    implementation = ast.parse((ROOT / (srt + "algorithm.py")).read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(implementation) if isinstance(node, ast.FunctionDef) and node.name == "calculate_history")
    assert [arg.arg for arg in method.args.args] == ["self", "inputs", "sessions"]
    patterns = {
        "explicit_loss_memory": r"loss.?streak|losing.?streak|consecutive.?loss|last_trade|last_exit|stop.?after|pause_after|cooldown|cool_down|连续亏|连亏|连败|亏损后|累计亏|重复亏",
    }
    scanned, hits = [], []
    for path in sorted((ROOT / "research/S014/experiments").glob("EX*/**/*")):
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file() or not (("/src/" in rel and path.suffix == ".py") or ("/protocols/" in rel and path.suffix in {".md", ".json"})):
            continue
        scanned.append(identity(rel))
        for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if re.search(patterns["explicit_loss_memory"], line, re.I):
                hits.append({"path": rel, "line": i, "excerpt": line[:1000]})
    search = {"scope": "S014 EX001..EX045 src Python and protocol Markdown/JSON only; no assets, prices, other batches or memories", "file_count": len(scanned), "files": scanned, "patterns": patterns, "hits": hits,
              "interpretation": "No exact complete funded policy using consecutive actually completed net-loss cycles plus finite pause/restart found in this bounded source/protocol review. String absence alone does not prove semantic absence; earlier manual inventory and explicit clock/profit definitions were also reviewed.",
              "manual_prior_inventory": identity("research/S014/materials/20261019_2024_diagnosis/method/prior_mechanism_inventory.json")}
    write("historical_loss_memory_search.json", search)
    index = read("research/S014/experiments/EX044_20261019/others/accounts_index.json")
    cost = index["records"][4]
    assert cost["parameters"] == {"entry_guard": "BASE", "exit_domain": "POSITIVE_P", "cost_stop": "NET_LOSS_1ATR"}
    findings = read("research/S014/materials/20261019_2024_diagnosis/accounting/ex044_research_findings.json")
    facts = findings["five_policy_facts"]
    result = {
        "status": "COMPLETE_READONLY_METHOD_REVIEW_NO_EXECUTION_AUTHORIZED_HERE",
        "role": "RSCH", "verified_branch": "codex/s014-jinniu-research", "verified_clean_HEAD": "b83da6805cab70205a49af8e3873ce4f038f97a1",
        "evidence_locators": evidence,
        "price_ceiling_feasibility": {
            "under_original_contract": "NO: the existing FROZEN_RULE planner derives BUY price from the authenticated reference, immutable entry.limit_parameter=.01, tick and price-limit guard. calculate_history exposes target plus observation/evidence; custom limit columns do not become orders.",
            "D_close_cap": "A constant premium=0 can generally express a tick-rounded close ceiling with the existing planner, but that changes the strategy execution policy and its identity. It is not an authorized original-1%-contract experiment. Original LimitBuyHold benchmark must not be silently changed; comparability and user-approved amended contract would need an explicit decision.",
            "dynamic_support_cap": "No per-D support-price argument is passed from strategy signal evidence into this public FROZEN_RULE order algorithm. A dynamic cap requires an explicit supported execution-policy capability/contract review; no monkeypatch, invented reference, adjusted input data, custom hidden executor or private-plan override is admissible here.",
            "fully_contract_preserving": ["Gate or postpone original BUY intent using D-known price/market/own realized-loss state; every accepted BUY still uses original1% planner.", "Keep original cost-stop, fees, actual-entry anchors, mandatory exits and original reservation; separately lock any added waiting semantics.", "Describe saved actual fills versus their prior D-close/S5 and next-session gap for attribution only; this is not the value of an unexecuted lower-limit order."],
            "not_equivalent": "A D-known entry filter can change which original orders are submitted. It cannot ensure a future E fill is below D close/S5, and cannot by itself identify signal quality separately from chasing-price execution.",
            "do_not_peek": "E open/low/close, whether an E order would fill and completed future return are unavailable at D. Reclassifying or cancelling with those facts is retrospective labeling, not an executable D filter."
        },
        "EX044_cost_baseline": {
            "source": identity(source), "account_ref": cost["evidence"], "result_hash": cost["result_hash"],
            "source_ref": cost["published_source_ref"], "public_final_ref": read("research/S014/experiments/EX044_20261019/others/final_verification_ref.json"),
            "formula": "actual_entry_fill*1.001 - C_D*.999 >= ATR20priorD; actual held, no inherited SELL pending, before deadline; risk precedes grace/support. ATR updates every D, not frozen at entry.",
            "actual_known_results_only": {"cost_annual_returns_percent": facts[4]["annual_returns_percent"], "frozen_annual_returns_percent": facts[0]["annual_returns_percent"], "cost_2025_terminal_equity": facts[4]["terminal2025_equity"], "cost_attribution": findings["cost_action_attribution"]},
            "scope": "Cost-stop reduced2024 loss from-21.1573% to-12.3725%; all6 annual drawdown targets and5/6 return targets pass,2024 still fails. It reacts after actual BUY damage and can trigger from ATR shrink; not a maximum-loss guarantee or new pre-entry gate. It has no completed-cycle loss memory and changes neither order price nor premium."
        },
        "completed_loss_pause": {
            "historical_status": "NOT_FOUND_AS_EXACT_COMPLETE_POLICY_IN_BOUNDED_REVIEW; not a proven new edge",
            "old_mechanisms_not_same": {"EX007": "Mature outcome-label model and single midpoint holding/exit probes, not own actually closed-trade losing streak.", "EX022": "One initial startup delay only; no recurring pause after losses.", "EX023": "Reservation tied to actual entry H10 regardless of realized profit.", "EX029": "P measured/frozen at current-cycle first support break chooses waiting; not net realized completed loss.", "EX043": "Current positive mark-to-market profit exits, grace and actual-entry close-peak memory; not across completed trades.", "EX044": "Cost drawdown within the current held trade; no cross-trade outcome memory.", "EX045": "Reservation consumes a blocked high-Z planned opportunity; explicitly may have no fill, therefore not a completed losing trade."},
            "D_known_state": ["Actual positive-quantity BUY fill date/time/price/quantity/fee, matching actual SELL fill(s), and completed-cycle net cash PnL after both-side fees.", "Increment loss streak only after actual completed full-position SELL; an unfilled order, failed BUY reset, blocked virtual slot or still-pending SELL is not a completed loss.", "D close may use a SELL already executed on D, then decide a later valid-session BUY; no same-session retroactive cancellation or sale.", "A zero-PnL convention, positive-trade reset, finite pause duration/unit, pause start, restart condition and interaction with original reservation must all be fixed before execution.", "Carry state continuously across years. Do not select losing streaks using future realized returns or reset each January.", "Waiting only blocks new flat BUY intents; no phantom entry/deadline/cost/reservation, no interruption of pending/mandatory exits. Whether pause expiry is a calendar wait or skipped opportunity slot is a separate causal clock choice, as EX045 demonstrated."],
            "implementation_boundary": "calculate_history(inputs,sessions) receives input market datasets, not authoritative portfolio/fills/trade history. PortfolioSnapshot and ExecutionState are passed to the SRT planner, not to the strategy's history method; ExecutionState carries only revision/as_of/cycle_target_quantity. Public completed result ledgers are available for ex-post audit, never a future-input source for D.",
            "research_layer_possible_with_condition": "A causal full-history state machine may reconstruct fills using the unchanged public planner/resolve_fill and original fees/limits/status/lot/cash rules, without a platform change. It must use actual funded quantity/cash, not merely assume the existing100-unit shadow fill happened in the account. Require fresh-control exact economics, every-D actual funded-state/filled flags and completed net-PnL alignment before interpreting a new account. This is an unimplemented feasibility route, not proof of live authoritative fill feedback.",
            "raw_states_available_in_existing_history": ["held_at_close,buy_filled_today,sell_filled_today,failed_buy_reset", "entry_fill_price,entry_index,deadline_index,reservation_index,exit_pending,pending_inherited", "net_profit is current mark-to-market net estimate, not a completed realized loss", "raw features may be null when unknown; numeric series need explicit finite known flags"],
            "public_result_fields_for_audit": ["run.ledgers.fills: side,quantity,price,fees,cycle_id,order_id,fill_time,signal_date", "run.ledgers.orders: side,status,reason,execution_date,signal_date,decision_id", "run.ledgers.account_daily: cash,cash_before,quantity,quantity_before,equity,date", "run.ledgers.trades: cycle_id,entry_date,entry_price,exit_date,exit_price,quantity,status,net_return; exact fees come from linked fills, not a trades fee column. Do not seed strategy state from this future-complete table."],
            "unit_constraint": "All runtime prices use HFQ_RESEARCH; account ledger anchoredHFQ/RESEARCH_UNIT uses anchor5.892. Compare cash PnL and prices only in matching units; fees must equal original ledger."
        },
        "minimal_next_design_recommendation_not_locked": "If root selects own completed-loss memory, compare one unchanged cost baseline and one date-free finite pause rule, fixing count/duration/restart/reservation and source-specific NOOP first. Do not combine new Z guards or price-policy changes; prior Z entry/exit roles and retry/planned-slot clocks are already tested. No threshold scan and no claim of unseen other-year validation: all2020..2025 have already been seen.",
        "resources": {"new_experiments": 0, "new_account_dispatches": 0, "new_strategy_runs": 0, "new_fits": 0, "new_market_reads": 0, "new_data_calls": 0, "platform_or_execution_contract_changes": 0},
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()
    }
    write("interface_and_loss_pause_review.json", result)
    print(json.dumps({"status": result["status"], "historical_files": len(scanned), "text_hits": len(hits), "output_sha256": sha256((OUT / "interface_and_loss_pause_review.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
