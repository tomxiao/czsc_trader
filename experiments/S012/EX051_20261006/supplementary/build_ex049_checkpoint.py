"""EX049 serialized-screening diagnostics; no simulation, fetching or governance."""
from collections import Counter
import gzip
from hashlib import sha256
import json
from math import isclose
from pathlib import Path


ROOT = Path.cwd().resolve()
BASE = ROOT / ".tmp/s012-stage3-native-20261006/delivery-prep"
EXP = ROOT / "experiments/S012/EX049_20261006"
REX = EXP / "artifacts/rex"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ref(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}


def save(name, value):
    (BASE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def rank(row):
    return (-row["metrics"]["net_cagr"], abs(row["metrics"]["max_drawdown"]), -row["metrics"]["frequency"], row["proposal_id"])


def pct(value):
    return f"{100 * value:.4f}%"


def compact(row, search_reference, config):
    parameters = row["parameters"]
    boundaries = {}
    for field in ("hold_days", "entry_premium", "momentum_lookback"):
        choices = config["domains"][field]["choices"]
        if field == "momentum_lookback" and row["conditional_block"] == "OTHER_COMPONENTS":
            choices = [3]
        boundaries[field] = {"value": parameters[field], "tested_min": min(choices), "tested_max": max(choices),
            "position": "FIXED" if len(choices) == 1 else "LOWER" if parameters[field] == min(choices)
            else "UPPER" if parameters[field] == max(choices) else "INTERIOR"}
    return {"proposal_id": row["proposal_id"], "trial_number": row["trial_number"],
        "parameters": parameters, "parameter_sha256": row["parameter_sha256"], "scope": row["scope"],
        "metrics": {key: row["metrics"][key] for key in ("net_cagr", "max_drawdown", "closed_trades",
            "frequency", "final_equity", "final_quantity", "total_fees", "exposure", "orders", "fills", "goals")},
        "boundaries": boundaries, "candidate": None, "formal_FULL": False,
        "original_row": {**search_reference, "selector": {"proposal_id": row["proposal_id"],
            "trial_number": row["trial_number"]}}}


def ledger_readback(row):
    references = []
    tables = {}
    for name in ("account_daily", "fills", "orders", "trades"):
        original = row["raw_ledgers"][name]
        path = (REX / original["path"]).resolve()
        path.relative_to(REX.resolve())
        compressed = path.read_bytes()
        assert sha256(compressed).hexdigest() == original["sha256"]
        raw = gzip.decompress(compressed)
        assert sha256(raw).hexdigest() == original["uncompressed_sha256"]
        tables[name] = json.loads(raw)["data"]
        assert len(tables[name]) == original["rows"]
        references.append({**ref(path), "uncompressed_sha256": original["uncompressed_sha256"]})
    account, fills, trades = tables["account_daily"], tables["fills"], tables["trades"]
    assert len(account) == 1534 and str(account[0]["date"]).startswith("2020-06-08")
    assert str(account[-1]["date"]).startswith("2026-09-30")
    for item in account:
        assert isclose(item["equity"], item["cash"] + item["quantity"] * item["close"], abs_tol=1e-7, rel_tol=1e-10)
        assert item["cash"] >= -1e-7 and item["quantity"] >= 0
    for fill in fills:
        assert fill["quantity"] > 0 and fill["quantity"] % 100 == 0
        assert isclose(fill["fees"], fill["quantity"] * fill["price"] * .001, abs_tol=1e-8)
    annual, previous = [], 100000.
    for year in range(2020, 2027):
        selected = [item for item in account if str(item["date"]).startswith(str(year))]
        ending = selected[-1]["equity"]
        annual.append({"year": year, "sessions": len(selected), "net_period_return": ending / previous - 1,
            "equity_increment": ending - previous, "ending_equity": ending,
            "time_in_market": sum(item["quantity"] > 0 for item in selected) / len(selected)})
        previous = ending
    assert sum(item["status"] == "CLOSED" for item in trades) == row["metrics"]["closed_trades"]
    assert isclose(sum(fill["fees"] for fill in fills), row["metrics"]["total_fees"], abs_tol=1e-7)
    assert isclose(sum(item["quantity"] > 0 for item in account) / 1534, row["metrics"]["exposure"], abs_tol=1e-12)
    return {"proposal_id": row["proposal_id"], "checks": "SERIALIZED_ACCOUNT_READBACK_PASS",
        "annual": annual, "gross_fill_amount": sum(fill["price"] * fill["quantity"] for fill in fills),
        "total_fees": sum(fill["fees"] for fill in fills), "time_in_market": row["metrics"]["exposure"],
        "final_cash": account[-1]["cash"], "final_quantity": account[-1]["quantity"],
        "open_cycles": sum(item["status"] == "OPEN" for item in trades),
        "order_status_counts": dict(Counter(item["status"] for item in tables["orders"])),
        "raw_evidence": references}


def main():
    analysis_path = ROOT / ".tmp/s012-stage3-native-20261006/complete49_analysis.json"
    if (EXP / "artifacts/checkpoint_analysis.json").exists():
        analysis_path = EXP / "artifacts/checkpoint_analysis.json"
    analysis, search = read(analysis_path), read(REX / "search.json")
    receipt, binding = read(REX / "execution_receipt.json"), read(EXP / "experiment_binding.json")
    search_reference = ref(REX / "search.json")
    assert analysis["raw_search"] == search_reference
    assert analysis["receipt_sha256"] == receipt["receipt_sha256"]
    assert receipt["source_sha256"] == binding["source_sha256"]
    rows = search["proposals"]
    assert len(rows) == 1040 and analysis["verified_raw_files"] == 7280
    assert analysis["status_counts"] == {"COMPLETE": 1040} and not analysis["qualified"]
    assert all(row["status"] == "COMPLETE" and row["candidate"] is None for row in rows)
    assert not receipt["trace"]["evaluations"]
    ranked = sorted(rows, key=rank)
    feasible = [row for row in ranked if row["metrics"]["goals"][1] and row["metrics"]["goals"][2]]
    assert ranked[0]["proposal_id"] == analysis["best_return"]["proposal_id"] == "OPTUNA_0999"
    assert feasible[0]["proposal_id"] == analysis["best_frequency_drawdown_feasible"]["proposal_id"] == "OPTUNA_0278"
    bests = [ranked[0], feasible[0]]
    route_best = []
    for route in search["domains"]["opportunity"]["choices"]:
        selected = [row for row in ranked if row["parameters"]["opportunity"] == route]
        route_best.append({"route": route, "proposals": len(selected),
            "drawdown_frequency_feasible": sum(row["metrics"]["goals"][1] and row["metrics"]["goals"][2] for row in selected),
            "best": compact(selected[0], search_reference, search)})
    neighborhoods = []
    for best in bests:
        for field in ("hold_days", "entry_premium", "momentum_lookback"):
            choices = search["domains"][field]["choices"]
            index = choices.index(best["parameters"][field])
            for value in choices[max(0, index-1):index+2]:
                parameters = {**best["parameters"], field: value}
                matching = [row for row in rows if row["parameters"] == parameters]
                if matching:
                    assert len(matching) == 1
                    neighborhoods.append({"anchor": best["proposal_id"], "changed_field": field,
                        "tested_value": value, "row": compact(matching[0], search_reference, search)})
    readbacks = [ledger_readback(row) for row in bests]
    analysis_reference = ref(analysis_path)
    analysis_reference["path"] = "experiments/S012/EX049_20261006/artifacts/checkpoint_analysis.json"
    source_path = ROOT / ".tmp/s012_analyze_complete49.py"
    source_reference = ref(source_path)
    source_reference["path"] = "experiments/S012/EX049_20261006/artifacts/supplementary/s012_analyze_complete49.py"
    evidence = [search_reference, ref(EXP / "experiment_binding.json"), ref(EXP / "artifacts/preflight.json"),
                ref(REX / "execution_receipt.json"), ref(REX / "gate_evidence/gate.json"), analysis_reference, source_reference]
    payload = {"schema_version": 1, "experiment_id": EXP.name, "receipt_sha256": receipt["receipt_sha256"],
        "bound_source_sha256": binding["source_sha256"], "technical_REX_complete": True,
        "screening_status_counts": analysis["status_counts"], "hash_checks_existing_analysis": 7280,
        "unique_parameters": 1040, "unique_behaviors": analysis["unique_trade_behavior_count"],
        "unique_signal_policies": analysis["unique_signal_policy_count"], "formal_FULL_evaluations": 0,
        "mode": search["mode"], "qualified": [], "stage_three_complete": False,
        "pass_counts": {name: sum(row["metrics"]["goals"][index] for row in rows)
            for index, name in enumerate(("return", "drawdown", "frequency"))},
        "drawdown_frequency_feasible": len(feasible), "all_window_seen": True,
        "return_priority": ["net_cagr descending", "absolute MDD ascending", "real closed frequency descending"],
        "best_return": compact(bests[0], search_reference, search),
        "best_drawdown_frequency_feasible": compact(bests[1], search_reference, search),
        "routes": route_best, "one_parameter_neighbors": neighborhoods, "frontier_ledger_readbacks": readbacks,
        "scope_limit": "Finite conditional fixed-exit/no-risk/no-confirmation grid only; no adaptive search, no FULL qualification.",
        "evidence": evidence}
    save("EX049_checkpoint_diagnosis.json", payload)
    threshold = ranked[0]["metrics"]["benchmark"]["cagr"] * 1.5
    lines = ["# EX049 阶段三研究检查点结论", "",
        "完整REX执行链成功，1040/1040研究筛选提案COMPLETE、0 FAIL、0经济达标。正式FULL评价数为0，未登记候选，阶段三尚未完成。REX成功表示技术筛选成功，不表示账户已获FULL资格。", "",
        "实际分析已核对7280个原件SHA。全部提案、交易行为和信号政策均为1040项唯一值；原始search和gzip账本留在artifacts，不复制到诊断摘要。", "",
        f"原三硬门同时要求净年化≥{pct(threshold)}、回撤幅度严格<30.2906%、闭合周期×60/1535≥5（至少128）。收益门0/1040，回撤门616/1040，频率门413/1040，回撤与频率同时可行174项。按净年化优先，再较小回撤、真实频率排序；三门不能互相替代。", "",
        "## 收益前沿与约束可行前沿", ""]
    for best, readback in zip(bests, readbacks):
        metrics = best["metrics"]
        lines += [f"{best['proposal_id']}：`{json.dumps(best['parameters'], ensure_ascii=False, sort_keys=True)}`。", "",
            f"净年化{pct(metrics['net_cagr'])}、回撤幅度{pct(abs(metrics['max_drawdown']))}、{metrics['closed_trades']}闭合周期、频率{metrics['frequency']:.4f}；距收益硬门{100*(threshold-metrics['net_cagr']):.4f}个百分点。费用{metrics['total_fees']:.2f}元、持仓会话比{pct(metrics['exposure'])}。期末数量{metrics['final_quantity']}，未闭合周期{readback['open_cycles']}个，未闭合持仓不计频率。", "",
            "|年度|实际期间净收益|权益增量/元|年末权益/元|持仓会话比|", "|---:|---:|---:|---:|---:|"]
        for annual in readback["annual"]:
            lines.append(f"|{annual['year']}|{pct(annual['net_period_return'])}|{annual['equity_increment']:.2f}|{annual['ending_equity']:.2f}|{pct(annual['time_in_market'])}|")
        lines += [""]
    lines += ["0999为全局收益第一，收益和频率未过；0278为回撤＋频率可行项中的收益第一，只有收益门未过。两项均来自已经观察的开发池选择，需后继真实FULL复核；不能把加速等价gate或筛选回执当作这两项的FULL结果。持仓会话比不等于资金加权仓位；2026为截至9月30日的实际期间收益。", "",
        "## 逐路线最高收益与边界", "",
        "|路线|提案数|收益最高项|观察长度/持有天/溢价|净年化|回撤幅度|频率|回撤＋频率可行数|",
        "|---|---:|---|---|---:|---:|---:|---:|"]
    for route in route_best:
        row, p = route["best"], route["best"]["parameters"]
        m = row["metrics"]
        lines.append(f"|{route['route']}|{route['proposals']}|{row['proposal_id']}|{p['momentum_lookback']}/{p['hold_days']}/{pct(p['entry_premium'])}|{pct(m['net_cagr'])}|{pct(abs(m['max_drawdown']))}|{m['frequency']:.4f}|{route['drawdown_frequency_feasible']}|")
    lines += ["", "1040是条件网格：两条动量路线×6观察长度×13持有期×4溢价=624，其他8路线固定观察长度3×13×4=416。并非所有全参数组合；退出固定、风控关闭、确认关闭、配置100%、冷却0、最少持有1。Optuna仅固定enqueue/ask/tell，adaptive预算0，不声明完成自适应优化。", "",
        "0999的40天持有、0.5%溢价均为已测内部点，没有这两维贴边的证据。0278的10日观察与6天持有为内部点，1%溢价触及已测上界。momentum_union、o01_m05、all_union、always、o01路线的收益最好项持有60天触及上界；其中低频仍是硬约束缺口。o01_m05/all_union的-0.5%溢价处于下界；触边只提供后继问题，不能自动视作扩边有收益。", "",
        "## 同源码单参数相邻证据", "",
        "所有相邻行仅改变所列参数，指标来自实际已存筛选账户；这些是开发池内诊断，不是独立验证。", "",
        "|锚点|变化参数|测试值|原行|净年化|回撤幅度|闭合/频率|", "|---|---|---|---|---:|---:|---:|"]
    for nearby in neighborhoods:
        row, m = nearby["row"], nearby["row"]["metrics"]
        lines.append(f"|{nearby['anchor']}|{nearby['changed_field']}|{nearby['tested_value']}|{row['proposal_id']}|{pct(m['net_cagr'])}|{pct(abs(m['max_drawdown']))}|{m['closed_trades']}/{m['frequency']:.4f}|")
    lines += ["", "## 针对性后继与反证", "",
        "0999的持有期从40改为30或60天，净年化分别降至13.0655%和15.5659%；60天回撤31.8373%超基准。溢价从0.5%改至0或1%也降至16.6099%和17.6447%，当前证据支持内部峰附近细化，不支持收益单调随持有或溢价扩边。", "",
        "0278在持有5/6/8天的净年化为2.1121%/14.9244%/3.8587%，观察5/10/20日为3.9322%/14.9244%/-1.7014%，局部峰很尖。先真实FULL确认并做较密邻域反证，再解释机制或稳健性。溢价0.5%至1%收益升1.2082个百分点，但闭合数均164，无法解释为新增交易频率；应核对成交价格、数量和订单选择。", "",
        "0999的2025权益增量97,761.67元，占全窗净权益增量较大；0278的2025与2026贡献主要增量。0278实际手续费43,231.67元，0999为8,518.06元，保留成本与持仓暴露作为利润机制解释，不能把手续费直接加回终值构造零成本成绩。", "",
        "1. 先对0999收益前沿与0278可行前沿做后继真实FULL，保持source、features、市场、政策和经济协议身份可追溯。所有筛选达标项仍须全部FULL；本批达标集合为空，不据此停止研究。", "",
        "2. 收益主线保留n09_m05长持有利润机制；围绕短中持有与实际退出研究收益/密度冲突，严禁人为拆分闭合。可行主线保留momentum10短持有，检验上界溢价到底改善成交覆盖还是只改变订单成交选择；扩边必须声明新域并保留相邻及不利结果。", "",
        "3. 后继应单独声明机会失效退出/最少持有、风险有效域/未知值政策、确认开关及必要交互；当前固定退出、无风控、无确认网格未覆盖这些职责。always作为具体执行机制对照，最佳仍为13.3942%且回撤30.5278%超基准、频率0.9772，保留反面证据。o01最佳亦回撤超基准，不以组件有效性替代账户目标。", "",
        "4. 保持已观察的全开发池和原频率分母。仍需完整搜索状态及选择链、新域的适用等价gate、边界/扩边依据、全部选中前沿真实FULL、全达标handoff、CandidateSet和人工研究交付；1040固定提案完成是检查点，不是阶段三收口。", "",
        "## 原件引用", ""]
    for reference in evidence:
        lines.append(f"- `{reference['path']}`，SHA256 `{reference['sha256']}`。")
    (BASE / "EX049_04_conclusion.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    original_evidence = [ref(EXP / name) for name in binding["source_files"]]
    original_evidence += [ref(EXP / "experiment_binding.json"), ref(EXP / "artifacts/preflight.json"),
                          ref(REX / "execution_receipt.json"), ref(REX / "search.json")]
    manifest_metadata = {"experiment_id": EXP.name, "strategy_id": "S012", "symbol": "518850.SH",
        "development_cutoff": "2026-09-30", "outcome": "PASS", "economic_outcome": "NO_QUALIFIED",
        "purpose": "SCREENING_CHECKPOINT_NOT_STAGE_THREE_CLOSURE", "source_sha256": binding["source_sha256"],
        "complete_rex": True, "receipt_sha256": receipt["receipt_sha256"], "screening_complete": 1040,
        "screening_failed": 0, "qualified": 0, "formal_FULL_evaluations": 0, "candidate_registrations": 0,
        "stage_three_complete": False, "analysis_sha256": analysis_reference["sha256"]}
    recipe = {"schema_version": 1, "experiment_id": EXP.name, "execute_by_root_only": True,
        "already_executed": False, "technical_REX_complete": True, "research_outcome": "CHECKPOINT_NO_QUALIFIED",
        "formal_FULL_evaluations": 0, "candidate_registrations": 0, "stage_advance": False, "stage_three_complete": False,
        "receipt_sha256": receipt["receipt_sha256"], "source_sha256": binding["source_sha256"],
        "source_evidence": evidence, "pinned_originals": original_evidence,
        "manifest_metadata": manifest_metadata,
        "copies": [{"from": analysis_path.relative_to(ROOT).as_posix(), "to": analysis_reference["path"], "sha256": analysis_reference["sha256"]},
            {"from": source_path.relative_to(ROOT).as_posix(), "to": source_reference["path"], "sha256": source_reference["sha256"]},
            {"from": ".tmp/s012-stage3-native-20261006/delivery-prep/EX049_checkpoint_diagnosis.json", "to": "experiments/S012/EX049_20261006/artifacts/checkpoint_diagnosis.json"},
            {"from": ".tmp/s012-stage3-native-20261006/delivery-prep/EX049_04_conclusion.md", "to": "experiments/S012/EX049_20261006/04_conclusion.md"},
            {"from": ".tmp/s012-stage3-native-20261006/delivery-prep/build_ex049_checkpoint.py", "to": "experiments/S012/EX049_20261006/artifacts/supplementary/build_ex049_checkpoint.py"}],
        "steps": ["执行前核对原binding/source/preflight/完整receipt与分析原件SHA不变；保持gzip大账本在artifacts",
            "只添加上述补充分析/复算源码/诊断与结论，完整分析不冒充FULL账户审计",
            "公开build_experiment_manifest并validate_experiment_archive，metadata同时注明技术筛选成功、0经济达标、0FULL、阶段三未完成",
            "不登记候选，不推进阶段，不改写原search选择历史；后继选择另有SHA固定sidecar与真正FULL回执"]}
    for copy in recipe["copies"]:
        copy["sha256"] = ref(ROOT / copy["from"])["sha256"]
    save("EX049_seal_recipe.json", recipe)
    print(json.dumps({"experiment_id": EXP.name, "diagnosis_bytes": (BASE / "EX049_checkpoint_diagnosis.json").stat().st_size,
        "pass_counts": payload["pass_counts"], "drawdown_frequency_feasible": len(feasible),
        "frontier_readbacks": [{"proposal": r["proposal_id"], "fees": r["total_fees"], "open_cycles": r["open_cycles"],
            "annual_returns": [round(y["net_period_return"], 6) for y in r["annual"]]} for r in readbacks]}))


if __name__ == "__main__":
    main()
