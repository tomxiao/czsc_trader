"""EX051 compact readback report. Only serialized evidence; no account simulation."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

import build_ex049_checkpoint as helpers


ROOT = Path.cwd().resolve()
BASE = ROOT / ".tmp/s012-stage3-native-20261006/delivery-prep"
EXP = ROOT / "experiments/S012/EX051_20261006"
REX = EXP / "artifacts/rex"
helpers.REX = REX
read, ref, pct, rank = helpers.read, helpers.ref, helpers.pct, helpers.rank


def save(name, data):
    (BASE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def row_summary(row, search_reference):
    return {"proposal_id": row["proposal_id"], "trial_number": row["trial_number"],
        "parameters": row["parameters"], "parameter_sha256": row["parameter_sha256"], "scope": row["scope"],
        "metrics": {key: row["metrics"][key] for key in ("net_cagr", "max_drawdown", "closed_trades", "frequency",
            "final_equity", "final_quantity", "total_fees", "exposure", "orders", "fills", "goals")},
        "original_row": {**search_reference, "selector": {"proposal_id": row["proposal_id"], "trial_number": row["trial_number"]}},
        "candidate": None, "formal_FULL": False}


def table(row, name):
    reference = row["raw_ledgers"][name]
    path = (REX / reference["path"]).resolve()
    path.relative_to(REX.resolve())
    compressed = path.read_bytes()
    assert sha256(compressed).hexdigest() == reference["sha256"]
    raw = gzip.decompress(compressed)
    assert sha256(raw).hexdigest() == reference["uncompressed_sha256"]
    return json.loads(raw)["data"]


def first_buys(fills):
    first = {}
    for fill in fills:
        if fill["side"] == "BUY":
            first.setdefault(fill["cycle_id"], fill)
    return first


def main():
    analysis_path = ROOT / ".tmp/s012-stage3-native-20261006/complete51_analysis.json"
    if (EXP / "artifacts/checkpoint_analysis.json").exists():
        analysis_path = EXP / "artifacts/checkpoint_analysis.json"
    analysis, search = read(analysis_path), read(REX / "search.json")
    receipt, binding = read(REX / "execution_receipt.json"), read(EXP / "experiment_binding.json")
    search_reference = ref(REX / "search.json")
    assert analysis["raw_search"] == search_reference
    assert analysis["receipt_sha256"] == receipt["receipt_sha256"]
    assert receipt["source_sha256"] == binding["source_sha256"]
    assert analysis["verified_raw_files"] == 1365 and analysis["status_counts"] == {"COMPLETE": 195}
    rows = search["proposals"]
    assert len(rows) == 195 and not analysis["qualified"] and not receipt["trace"]["evaluations"]
    assert all(row["candidate"] is None and row["status"] == "COMPLETE" and not row["passed_all"] for row in rows)
    ranked = sorted(rows, key=rank)
    feasible = [row for row in ranked if row["metrics"]["goals"][1] and row["metrics"]["goals"][2]]
    best, best_feasible = ranked[0], feasible[0]
    assert best["proposal_id"] == analysis["best_return"]["proposal_id"] == "OPTUNA_0187"
    assert best_feasible["proposal_id"] == analysis["best_frequency_drawdown_feasible"]["proposal_id"] == "OPTUNA_0081"
    original_path = ROOT / "experiments/S012/EX049_20261006/artifacts/rex/search.json"
    original = read(original_path)
    original_index = {row["parameter_sha256"]: row for row in original["proposals"]}
    controls = []
    fields = ("implementation_sha256", "feature_sha256", "execution_data_fingerprint", "economic_protocol_sha256", "execution_policy_sha256")
    for row in rows:
        old = original_index.get(row["parameter_sha256"])
        if old is None:
            continue
        assert row["parameters"] == old["parameters"] and row["metrics"] == old["metrics"]
        assert row["behavior_sha256"] == old["behavior_sha256"]
        assert all(row["scope"][field] == old["scope"][field] for field in fields)
        assert all(reference["uncompressed_sha256"] == old["raw_ledgers"][name]["uncompressed_sha256"]
                   for name, reference in row["raw_ledgers"].items())
        controls.append({"current_proposal_id": row["proposal_id"], "original_proposal_id": old["proposal_id"],
            "literal_parameters_equal": True, "metrics_equal": True, "ledger_content_hashes_equal": True,
            "scope_except_domain_gate_equal": True})
    assert len(controls) == 14
    premium_rows = sorted([row for row in rows if row["parameters"]["opportunity"] == "momentum"
        and row["parameters"]["momentum_lookback"] == 10 and row["parameters"]["hold_days"] == 6],
        key=lambda row: row["parameters"]["entry_premium"])
    assert len(premium_rows) == 6
    signals = table(premium_rows[0], "signals")
    planned_cycles = len({item["planned_cycle_id"] for item in signals if item["planned_cycle_id"] > 0})
    assert planned_cycles == 164
    ledger_tables = {}
    premium_summaries = []
    for row in premium_rows:
        assert table(row, "signals") == signals
        fills, orders = table(row, "fills"), table(row, "orders")
        accounts, decisions = table(row, "account_daily"), table(row, "decisions")
        ledger_tables[row["parameters"]["entry_premium"]] = {"fills": fills, "orders": orders,
            "accounts": accounts, "decisions": decisions}
        premium_summaries.append({"row": row_summary(row, search_reference), "plan_signals_exactly_equal": True,
            "planned_cycles": planned_cycles, "order_status_counts": dict(Counter(item["status"] for item in orders)),
            "buy_fill_count": sum(item["side"] == "BUY" for item in fills),
            "buy_trigger_counts": dict(Counter(item["trigger"] for item in fills if item["side"] == "BUY")),
            "gross_fill_amount": sum(item["quantity"] * item["price"] for item in fills),
            "ledger_references": [{"path": (REX / reference["path"]).relative_to(ROOT).as_posix(),
                "sha256": reference["sha256"], "uncompressed_sha256": reference["uncompressed_sha256"]}
                for reference in row["raw_ledgers"].values()]})
    left, right = ledger_tables[.01], ledger_tables[.02]
    a, b = first_buys(left["fills"]), first_buys(right["fills"])
    assert set(a) == set(b) and len(a) == 164
    differences = {"matched_actual_entry_cycles": 164,
        "first_buy_time_changed": sum(a[key]["fill_time"] != b[key]["fill_time"] for key in a),
        "first_buy_price_changed": sum(a[key]["price"] != b[key]["price"] for key in a),
        "first_buy_quantity_changed": sum(a[key]["quantity"] != b[key]["quantity"] for key in a),
        "final_equity_delta": best_feasible["metrics"]["final_equity"] - original_index[premium_rows[1]["parameter_sha256"]]["metrics"]["final_equity"],
        "net_cagr_improvement_percentage_points": 100 * (best_feasible["metrics"]["net_cagr"] - premium_rows[1]["metrics"]["net_cagr"]),
        "total_fees_delta": best_feasible["metrics"]["total_fees"] - premium_rows[1]["metrics"]["total_fees"]}
    first_example = []
    for premium in (.01, .02):
        data = ledger_tables[premium]
        fill = first_buys(data["fills"])[1]
        order = next(item for item in data["orders"] if item["side"] == "BUY" and item["cycle_id"] == 1)
        account = next(item for item in data["accounts"] if str(item["date"])[:10] == str(fill["fill_time"])[:10])
        first_example.append({"premium": premium, "buy_order": order, "actual_fill": fill,
            "cash_before": account["cash_before"], "cash_after": account["cash"], "quantity_after": account["quantity"]})
    readbacks = [helpers.ledger_readback(row) for row in (best, best_feasible)]
    witness_path = ROOT / "experiments/S012/EX050_20261006/witness_plan.json"
    witness = read(witness_path)
    pending = next(row for row in witness if row["candidate_id"] == "C4603")
    assert pending["parameters"] == best_feasible["parameters"] and pending["parameter_sha256"] == best_feasible["parameter_sha256"]
    analysis_reference = ref(analysis_path)
    analysis_reference["path"] = "experiments/S012/EX051_20261006/artifacts/checkpoint_analysis.json"
    source_path = ROOT / ".tmp/s012_analyze_complete51.py"
    source_reference = ref(source_path)
    source_reference["path"] = "experiments/S012/EX051_20261006/artifacts/supplementary/s012_analyze_complete51.py"
    evidence = [search_reference, ref(EXP / "experiment_binding.json"), ref(EXP / "artifacts/preflight.json"),
        ref(REX / "execution_receipt.json"), ref(original_path), ref(witness_path), ref(EXP / "s012_accelerator.py"),
        analysis_reference, source_reference]
    scope_limit = "Declared 195 conditional dense fixed/no-risk/no-confirmation proposals; no FULL result or independent holdout."
    payload = {"schema_version": 1, "experiment_id": EXP.name, "receipt_sha256": receipt["receipt_sha256"],
        "bound_source_sha256": binding["source_sha256"], "technical_REX_complete": True,
        "screening_status_counts": analysis["status_counts"], "raw_files_verified_by_existing_analysis": 1365,
        "unique_parameters": 195, "overlap_controls": controls, "new_parameter_count_vs_EX049": 181,
        "mode": search["mode"], "qualified": [], "formal_FULL_evaluations": 0, "stage_three_complete": False,
        "pass_counts": {name: sum(row["metrics"]["goals"][index] for row in rows)
            for index, name in enumerate(("return", "drawdown", "frequency"))},
        "drawdown_frequency_feasible": len(feasible), "all_window_seen": True,
        "best_return": row_summary(best, search_reference), "best_feasible": row_summary(best_feasible, search_reference),
        "premium_neighbors": premium_summaries, "premium_01_to_02_actual_differences": differences,
        "first_buy_reservation_example": first_example, "frontier_ledger_readbacks": readbacks,
        "FULL_coverage": {"status": "PENDING_EX050_COMPLETE_AND_AUDIT", "matched_planned_candidate": "C4603",
            "parameters_exactly_equal": True, "parameter_sha256": pending["parameter_sha256"], "witness_plan": ref(witness_path)},
        "scope_limit": scope_limit, "evidence": evidence}
    save("EX051_checkpoint_diagnosis.json", payload)
    lines = ["# EX051 阶段三密集邻域检查点结论", "",
        "完整REX技术执行成功，195/195 COMPLETE、0 FAIL、0经济达标、0正式FULL。实际分析已核对1365个原件SHA；阶段三仍在进行，有限邻域完成不构成收口。", "",
        "原三门同时要求：净年化≥21.4300%、回撤幅度严格<30.2906%、闭合周期×60/1535≥5。收益门0/195、回撤门171/195、频率门114/195，同时回撤＋频率可行100项。优先按净年化、较小回撤、真实频率排序；诊断不新增经济否决门。", "",
        "## 收益与可行前沿", "",
        "全局收益第一OPTUNA_0187（n09_m05，持有40天、溢价0.5%）净年化18.0374%、回撤18.5154%、26闭合、频率1.0163，期末30800股且一周期OPEN。它与EX049 OPTUNA_0999字面参数、经济结果及账本内容完全一致；收益及频率仍未过，重复控制不计为新收益发现。", "",
        f"回撤＋频率可行收益第一OPTUNA_0081（momentum10，持有6天、溢价2%）净年化{pct(best_feasible['metrics']['net_cagr'])}、回撤{pct(abs(best_feasible['metrics']['max_drawdown']))}、164闭合、频率6.4104。较旧EX049 OPTUNA_0278仅改善{differences['net_cagr_improvement_percentage_points']:.7f}个百分点，距收益门仍差{100*(1.5*best_feasible['metrics']['benchmark']['cagr']-best_feasible['metrics']['net_cagr']):.4f}个百分点。它与EX050计划C4603精确匹配；EX050完整回执及独立核对尚待完成，不能声明FULL覆盖通过。", "",
        "## 溢价相邻原账本：计划相同，执行改变", "",
        "momentum10/持有6天的六档溢价产生完全相同的1534行信号序列、164个计划周期；实际闭合均164。不能把政策身份不同、唯一hash计数解释为六个不同收益机会。", "",
        "|溢价|原行|净年化|终值/元|闭合|订单/成交|未成交|实际费用/元|持仓会话比|买入触发|",
        "|---:|---|---:|---:|---:|---|---:|---:|---:|---|"]
    for neighbor in premium_summaries:
        row, metrics = neighbor["row"], neighbor["row"]["metrics"]
        lines.append(f"|{pct(row['parameters']['entry_premium'])}|{row['proposal_id']}|{pct(metrics['net_cagr'])}|{metrics['final_equity']:.2f}|{metrics['closed_trades']}|{metrics['orders']}/{metrics['fills']}|{neighbor['order_status_counts'].get('UNFILLED',0)}|{metrics['total_fees']:.2f}|{pct(metrics['exposure'])}|{json.dumps(neighbor['buy_trigger_counts'],sort_keys=True)}|")
    lines += ["", "限价溢价同时参与成交条件和整手资金预留：limit按上日参考收盘×(1+premium)并按0.001元向下取整、受涨停保护；可买整手数按cash/[limit×(1+0.001)×100]向下取整，进入周期后目标数量固定。实际开盘成交价可能低于limit，因此更高limit即使同价成交也可能减少持仓数量并增加剩余现金。", "",
        "首周期2020-06-22：溢价1%与2%均以3.919元OPEN成交，分别买25300/25000股、费用99.1507/97.9750元。这提供整手预留机制的直接账本证据，不能仅归因限价更宽。", "",
        f"1%→2%的164个实际首入场周期中，首次成交时间改变{differences['first_buy_time_changed']}个、首次成交价格改变{differences['first_buy_price_changed']}个、首次数量改变{differences['first_buy_quantity_changed']}个。终值增量{differences['final_equity_delta']:.2f}元，费用变化{differences['total_fees_delta']:.2f}元；这是复合执行与后续现金路径变化，不是单一价差贡献的独立分解。", "",
        "2%是当前可行最高点，3%与5%进一步放宽并未继续提高净年化；提高溢价并非单调改善。持仓会话比描述数量大于0的会话比例，不等于资金加权仓位。费用不能直接加回终值作为假设零成本收益。", "",
        "## 字面重复控制", "",
        "与EX049重叠14个参数：8个动量控制、6个n09_m05控制。14/14字面参数、经济汇总、行为hash、6类账本未压缩内容hash、源码/feature/市场/经济协议/政策范围均一致，仅新域gate不同。其余181为本邻域新增参数，不将重复计为新经济发现。", "",
        "|本轮原行|EX049原行|字面/汇总/账本内容|", "|---|---|---|"]
    for control in controls:
        lines.append(f"|{control['current_proposal_id']}|{control['original_proposal_id']}|一致|")
    lines += ["", "## 连续年度账户", "",
        "年度按上年实际收盘权益连续归因；2026仅至9月30日。所有窗口已观察，不声明样本外。", ""]
    for readback in readbacks:
        lines += [readback["proposal_id"], "", "|年度|期间净收益|权益增量/元|期末权益/元|持仓会话比|", "|---:|---:|---:|---:|---:|"]
        for annual in readback["annual"]:
            lines.append(f"|{annual['year']}|{pct(annual['net_period_return'])}|{annual['equity_increment']:.2f}|{annual['ending_equity']:.2f}|{pct(annual['time_in_market'])}|")
        lines += [""]
    lines += ["## 下一研究问题", "",
        "收益主线保留全局长持前沿及短持约束可行前沿。等待EX050原前沿、溢价邻居与退出/风险控制完整FULL结果，再用最小冷却与unknown政策对照解释计划周期、实际成交和有效域；固定原门槛、数据范围、账户模型和选择历史。", "",
        "本轮180项动量密邻域＋15项n09_m05密邻域仅覆盖固定退出、无风控、无确认、满仓、冷却0。结果提示收益改善有限；没有自动新否决门，亦不按195项完成自动收口。保留高溢价不改善、长持频率不足和重叠重复全部证据。", "",
        "后继达标项须全覆盖真实FULL，已选前沿必须有自己的完整回执；仍需边界/域依据、完整SearchRecord及选择链、全部达标handoff和CandidateSet交付。", "",
        "## 原件与复算引用", ""]
    for reference in evidence:
        lines.append(f"- `{reference['path']}`，SHA256 `{reference['sha256']}`。")
    (BASE / "EX051_04_conclusion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    copies = [(analysis_path, EXP / "artifacts/checkpoint_analysis.json"),
        (source_path, EXP / "artifacts/supplementary/s012_analyze_complete51.py"),
        (BASE / "EX051_checkpoint_diagnosis.json", EXP / "artifacts/checkpoint_diagnosis.json"),
        (BASE / "EX051_04_conclusion.md", EXP / "04_conclusion.md"),
        (BASE / "build_ex051_checkpoint.py", EXP / "artifacts/supplementary/build_ex051_checkpoint.py"),
        (BASE / "build_ex049_checkpoint.py", EXP / "artifacts/supplementary/build_ex049_checkpoint.py")]
    save("EX051_seal_recipe.json", {"schema_version": 1, "experiment_id": EXP.name,
        "execute_by_root_only": True, "already_executed": False, "candidate_registrations": 0,
        "stage_advance": False, "stage_three_complete": False,
        "copies": [{"from": source.relative_to(ROOT).as_posix(), "to": target.relative_to(ROOT).as_posix(),
                    "sha256": ref(source)["sha256"]} for source, target in copies],
        "pinned_originals": [ref(EXP / name) for name in binding["source_files"]] + evidence[:4],
        "manifest_metadata": {"experiment_id": EXP.name, "strategy_id": "S012", "symbol": "518850.SH",
            "development_cutoff": "2026-09-30", "outcome": "PASS", "economic_outcome": "NO_QUALIFIED",
            "source_sha256": binding["source_sha256"], "complete_rex": True, "receipt_sha256": receipt["receipt_sha256"],
            "screening_complete": 195, "screening_failed": 0, "qualified": 0, "formal_FULL_evaluations": 0,
            "stage_three_complete": False, "proof_sha256": analysis_reference["sha256"]},
        "steps": ["核对原binding/source/preflight/receipt与全部引用SHA，保持原search/gzip大账本和选择历史",
            "拷贝真实analysis及复算源码/只读账本诊断/人工结论，补充目录不进入已冻结source闭包",
            "公开build_experiment_manifest与validate_experiment_archive；如EX050后续完成，独立证据另有引用，不回写本轮筛选记录",
            "0经济达标且0FULL，不登记候选、不推进阶段；保持全部反面证据"]})
    print(json.dumps({"experiment_id": EXP.name, "diagnosis_bytes": (BASE / "EX051_checkpoint_diagnosis.json").stat().st_size,
        "controls": len(controls), "pass_counts": payload["pass_counts"], "feasible": len(feasible),
        "premium_differences": differences, "analysis_sha256": analysis_reference["sha256"]}))


if __name__ == "__main__":
    main()
