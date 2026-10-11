"""Review existing compact EX061 statistics only; no market input or account execution."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "compact_statistics.json"
data = json.loads(SOURCE.read_text(encoding="utf-8"))


def mse_change(model, control):
    value, base = model.get("mse"), control.get("mse")
    return None if value is None or base in (None, 0) else 100 * (value / base - 1)


def diagnostics(block):
    control = block["models"]["controls"]
    models = {name: {**value, "mse_change_pct_vs_controls": mse_change(value, control)}
              for name, value in block["models"].items()}
    annual = {}
    for year, model_block in block["annual_models"].items():
        annual[year] = {
            name: {**value, "mse_change_pct_vs_controls": mse_change(value, model_block["controls"])}
            for name, value in model_block.items()
        }
    groups = {}
    for name, value in block["groups"].items():
        diff = value.get("high_minus_low")
        groups[name] = {**value, "high_minus_low_percentage_points": None if diff is None else diff * 100}
    return {"components": block["components"], "models": models,
            "groups": groups, "annual_models": annual,
            "annual_groups": block["annual_groups"]}


out = {
    "experiment": "S013_EX061",
    "review_role": "RSCH independent read-only component review",
    "source": ".tmp/s013-next-research/compact_statistics.json",
    "scope": "Only completed EX061 compact statistics; no market data, other research family, accounts, parameter search or platform modification.",
    "decision": {
        "positive_hypothesis": "STOP_POSITIVE_STRATEGY_TRANSLATION",
        "meaning": "没有足够增量支持‘尾盘收复越强，T+1买入后收益越高’策略。现有结果不能授予新策略资格。",
        "not_a_hard_gate": "区间跨零仅表示不确定性，不新增统计硬门；判断同时依据方向、控制后衰减、年度与相位不稳定、模型增量大小及风险取舍。",
        "forbidden_rescue": "不得在 EX061 内倒方向、扫尾盘时间窗、扫分组阈值或换持有期救回本正向假说。",
        "reverse_clue": "可保留为单独前瞻反假说线索，必须明确其方向来自本批事后观察；不能把同池复用当独立证据。",
        "broader_claim": "本次正向组件失败不证明所有新策略表达不可能。"
    },
    "strongest_positive_evidence": [
        "对原正向假说：全池3日 late_recovery 控制后相关约 +0.0284，四个非重叠相位均正；加入该项模型 MSE 比 controls 下降约0.0333%，两项合模下降约0.0051%。这是有限、幅度极小的正证，不能省略。",
        "对反向线索：机会池1日低组平均毛收益 late +0.3443%、reclaim +0.3859%，高组两者约 -0.1056%；高减低分别 -0.4500/-0.4917 个百分点。3日也反向。",
        "机会池1日模型 MSE 比 controls 下降 late 0.6213%、reclaim 0.2178%、合模0.6639%；合模在2021..2026六年中五年改善，但2025恶化2.1338%。这支持继续询问短期回归机制，不足以直接交易。",
        "机会池1日 late 的两个非重叠控制后相位均负，反向线索不只来自单个相位；reclaim 一个负、一个近零。"
    ],
    "strongest_counterevidence": [
        "机会池分组收益方向与预声明正向假说相反。控制后1日相关 late -0.0591、reclaim -0.0481，两者区间均跨零；不能声称稳定的独立增量。",
        "旧日线控制可以解释相当部分表象：全池1日 late 原相关 -0.0669 控制后 +0.0119；reclaim -0.1000 控制后 -0.0199。弱化后的反向信号可能是 BODY/收盘位置等旧信息的重述。",
        "全池1日三个增广模型均比 controls 差；5日也均退化。全池3日仅有极小增量，且不能把全池弱正证移植为机会池买入正证。",
        "机会池3/5日非重叠相位正负混杂，分年方向也不统一；2022的1/3日组差反向但5日翻为正。",
        "2023机会池组差无法计算：late 低/高仅15/11、reclaim19/21；reclaim低组不足。不得把这些年解释为正向或反向已验证。2021/2025及2026也有薄分组，明细完整附录。",
        "反向低组的1日毛收益优势伴随更高1日最大不利幅度：late 约多0.01585个百分点、reclaim约多0.06672个百分点；1日风险增广模型全部退化，不能预设更好的绝对回撤。",
        "这些是固定标签的毛收益/风险，不含公共账户成交、费用、持仓重叠、复利或参数扰动；不能推导原四门与32点联合达标率已经改善。"
    ],
    "novelty_and_old_information": {
        "algebraic": "late=log(C8/C6)不是 daily BODY 或 daily close_location 的数学恒等式；早6柱成交量加权收复也能在固定日线终点、不同早段量分配下变化。信息不同不等于有盈利增量。",
        "empirical": "控制后衰减强、区间宽，现有统计不能排除只是旧 BODY/close_location 的重复；同时也不足以证明完全等同。",
        "ties": "reclaim 位于[-1,1]，+1具有并列值。Q75=1时高组由上端原子构成，人数不会等于25%样本。在此原子，C8高于所有正成交量早6柱Close，成交量权重不影响得分；不能将高组收益差全部归因成交量分配。",
        "group_overlap": "现有年度组记录 overlap_n 均为0；没有高低组重叠。但无重叠不代表均衡四分位或同等样本量。"
    },
    "year_2022_2023": {
        "2022": {
            "opportunity_counts": "late low/high=38/38；reclaim=39/37；1/3/5日相同分组计数。",
            "return_1_hl_pp": {"late_recovery": -0.2704875013381458, "early_volume_reclaim": -0.6787330164425315},
            "return_3_hl_pp": {"late_recovery": -0.6120561629330419, "early_volume_reclaim": -0.4154828207531444},
            "return_5_hl_pp": {"late_recovery": 0.0537172627516712, "early_volume_reclaim": 0.08683915087750399},
            "meaning": "短持有反向、5日正向，不能据此选最漂亮持有期。"
        },
        "2023": {
            "test_n": 89,
            "opportunity_counts": "late=15/11；reclaim=19/21。",
            "high_minus_low": None,
            "reason": "INSUFFICIENT_GROUP_SAMPLE for low or both groups",
            "meaning": "三种持有期均无可报告组差。年度整体偏相关仍可报告，但不能代替不存在的分组均值。"
        }
    },
    "prospective_reverse_hypothesis": {
        "status": "CLUE_ONLY_NO_STRATEGY_ELIGIBILITY",
        "falsifiable_statement": "在预先固定的原买入机会池内，较弱的尾盘相对价格表现可能包含暂时卖压，T+1开盘后短期回归；其收益增量必须超出相同日线BODY/收盘位置所能解释的部分。",
        "strongest_alternative": "旧日线超跌回归、收盘位置、机会池筛选和端点并列值已足够解释，并不需要尾盘时序或成交量分配。",
        "necessary_comparison": "若继续，先冻结新的反假说并做同日期、同样本、同执行口径的旧daily BODY/close_location反向对照；明确reclaim端点价格原子与量权重增量的差别。禁止通过扫描新时间窗、阈值或多个持有期选赢家。",
        "stop": "如果新反假说的增量由旧日线对照解释，或仍仅依赖少数年度/并列值而缺少可交易的条件增量，则停止策略化；这不是新增统计硬门。",
        "future_account_requirement": "组件线索通过有限对照后，仍需另行前瞻声明、公共SRT原执行口径及原四门/标准32扰动评价；报告绝对Q10收益、Q90回撤。当前未执行这些。"
    },
    "diagnostic_appendix": {scope: {label: diagnostics(block) for label, block in value.items()}
                            for scope, value in data.items()},
    "derivation": "附录直接复制已完成compact统计；仅将组差转为百分点、计算MSE相对controls百分比便于解读。没有新增市场统计或实验。"
}

target = BASE / "judgment.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
checked = json.loads(target.read_text(encoding="utf-8"))
print(json.dumps({"written": str(target), "decision": checked["decision"]["positive_hypothesis"],
                  "scopes": list(checked["diagnostic_appendix"]),
                  "labels": {s: list(v) for s, v in checked["diagnostic_appendix"].items()}}, ensure_ascii=False))
