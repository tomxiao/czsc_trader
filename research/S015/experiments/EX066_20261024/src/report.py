"""Render the verified stage-four findings without changing research eligibility."""

from collections import defaultdict
import csv
import numpy as np
from stage4 import HOME, OUT, read, save
from strategy_evaluator.parameter_neighborhood import ParameterNeighborhoodDesign


def main():
    summary = read(OUT / "summary.json")
    groups = read(OUT / "group_summary.json")
    panel = read(OUT / "assessment_panel.json")
    family = read(OUT / "family_summary.json")
    audit = read(OUT / "audit.json")
    assert audit["status"] == "PASS" and summary["qualified_count"] == 16
    assert len(groups["groups"]) == 11 and sum(len(g["centers"]) for g in groups["groups"]) == 16
    assert all(r["status"] in ("RANKED", "TIED") for g in groups["groups"] for r in g["rows"])
    byid = {r["candidate_id"]: r for r in summary["rows"]}
    centers = {r["candidate_id"]: r for r in read(OUT / "centers.json")}
    grouped = {
        r["candidate_id"]: (i, r) for i, g in enumerate(groups["groups"], 1) for r in g["rows"]
    }
    inventory = []
    for plan in read(OUT / "plan_refs.json"):
        design = ParameterNeighborhoodDesign.from_dict(plan["design"])
        inventory.append(
            {
                "candidate_id": plan["candidate_id"],
                "active_axes": [x.to_dict() for x in design.axis_applicability],
                "points": [[x.to_dict() for x in p.values] for p in design.points],
                "fixed_structure": {
                    k: v
                    for k, v in centers[plan["candidate_id"]]["parameters"].items()
                    if k not in {a.name for a in design.space.axes}
                },
                "scope": "Mean-center-below entry: concentration unused. Fixed/confirmed_guard exits: max_hold and failure_buffer unused. confirmation included for confirmed_guard even when only jointly effective. mode/exit/center_kind/rearm structure fixed; start is evaluation boundary.",
            }
        )
    save(OUT / "parameter_inventory.json", inventory)
    sources = read(OUT / "assessment_request.json")["evidence"]
    timelines = []
    for cid in centers:
        item = next(
            x
            for x in sources
            if x["candidate"]["candidate_id"] == "S015-" + cid and x["scenario_id"] == "standard"
        )
        equity = np.r_[item["initial_cash"], [x["equity"] for x in item["account"]]]
        benchmark = np.r_[item["initial_cash"], item["benchmark_equity"]]
        dates = [x["session"] for x in item["account"]]
        years = []
        for year in sorted({x[:4] for x in dates}):
            indices = [i for i, x in enumerate(dates) if x.startswith(year)]
            start, end = indices[0], indices[-1] + 1
            years.append(
                {
                    "year": year,
                    "sessions": len(indices),
                    "net_return": float(equity[end] / equity[start] - 1),
                    "benchmark_return": float(benchmark[end] / benchmark[start] - 1),
                    "partial_year": True,
                }
            )
        streak = longest = 0
        for less in equity[1:] < benchmark[1:]:
            streak = streak + 1 if less else 0
            longest = max(longest, streak)
        timelines.append(
            {
                "candidate_id": cid,
                "annual_slices": years,
                "longest_wealth_below_benchmark": longest,
                "meaning": "Calendar slices inherit original cash/positions; both years incomplete, not independent restart accounts. Wealth comparison uses original initial capital.",
            }
        )
    save(OUT / "time_slices.json", timelines)
    behavior = defaultdict(list)
    for r in panel["rows"]:
        behavior[r["behavior_sha256"]].append(r["candidate"]["candidate_id"].removeprefix("S015-"))
    save(
        OUT / "center_behavior_groups.json",
        {
            "method": "Official assessment behavior_sha256; no replacement of candidate identity",
            "groups": dict(behavior),
        },
    )
    sensitivity = []
    for i, g in enumerate(groups["groups"], 1):
        baseline = {
            r["candidate_id"]: (r["pareto_layer"], r["rank_min"], r["rank_max"]) for r in g["rows"]
        }
        for variant in g["sensitivities"]:
            changed = [
                r["candidate_id"]
                for r in variant["rows"]
                if (r["rank_min"], r["rank_max"]) != baseline[r["candidate_id"]][1:]
            ]
            sensitivity.append(
                {"group": i, "variant": variant["name"], "changed_rank_candidates": changed}
            )
    save(OUT / "ranking_sensitivity_summary.json", sensitivity)
    table = []
    for cid, r in byid.items():
        diag = r["diagnostics"]
        group, rank = grouped[cid]
        table.append(
            {
                "candidate_id": cid,
                "qualified": r["all_authorized_targets_pass"],
                "net_return_434": centers[cid]["runs"]["full"]["net_return"],
                "annual_return": diag["NET_ANNUAL_RETURN"]["value"],
                "drawdown": diag["DRAWDOWN_MAGNITUDE"]["value"],
                "net_return_415": r["common_415"]["net_return"],
                "drawdown_415": r["common_415"]["drawdown"],
                "parameter_points": r["parameter"]["required_points"],
                "parameter_passes": r["parameter"]["joint_passes"],
                "parameter_Q10": diag["PARAMETER_RETURN_Q10"]["value"],
                "rolling_excess_Q10": diag["ROLLING_EXCESS_Q10"]["value"],
                "group": group,
                "within_group_pareto_layer": rank["pareto_layer"],
                "within_layer_rank_min": rank["rank_min"],
                "within_layer_rank_max": rank["rank_max"],
            }
        )
    with (OUT / "candidate_panel.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=table[0].keys())
        writer.writeheader()
        writer.writerows(table)
    lines = [
        "# S015 EX066：阶段四限幅参数自检与扩展选择历史",
        "",
        "Status: COMPLETED",
        "",
        "**阶段四执行完成：16个候选全部满足MANDATE/5的适用硬条件，24个参数邻域点全部通过。** 新结果不改变任何策略源码、中心参数或中心绩效；资格变化来自用户批准的局部扰动适用范围调整。旧ASSESSMENT/3的失败结论保持原样，新增ASSESSMENT/4独立留证。",
        "正式全体比较为16个INCOMPARABLE（PARAMETER_METHODS_DIFFER），不能宣布总体第一；11个同形组已各自完成正式比较。数值合格与总体排序可比性分别表达。",
        "",
        "## 范围与方法",
        "",
        "用户授权“有意义就好。请继续自主完成阶段四”。承接[CANDIDATES/7](../../deliveries/CANDIDATES/7/report.md)和[MANDATE/5](../../deliveries/MANDATE/5/report.md)。本轮无阶段三参数搜索，不提升邻点为候选，不接入新数据。",
        "全部16中心先固定具名完整邻域，再运行：16个中心标准复算、24个正式邻点、2个串行技术账户；复用16份同身份费用翻倍账户与原415日中心评价。最大8账户进程、每进程原生线程1。439份原始账户来源逐一认证，评估请求保留423份全窗口投影（替换16个旧中心）。",
        "窗口仍为2025-01-02至2026-10-21的434个交易日、原415日共同窗口；各账户初始10万元、空仓、原数据与执行契约、标准单边0.1%费用。434/415高度重叠且已反复参与开发，没有新的独立验证样本。",
        "参数限制为相对中心5%（不是5个百分点）。观察期3日、持有期3日、确认期2/3日的最近合法变化都超限，固定中心；投入比例连续域(0,1]使用合法±5%端点，越界不裁剪。8中心各1点、8中心各2点，共24点；全部仅改变投入比例。每中心至少ceil(13N/16)联合通过且所有点回撤≤25%，原内层收益/回撤门槛保留。",
        "没有整项参数不适用，因此本次未触发最低排序得分政策；参数通过仅支持所检验的投入比例范围，不能解释为观察期、持有期也已稳健。见[适用性清单](others/parameter_inventory.json)、[逐点结果](others/neighborhood_points.csv)。",
        "",
        "## 全部候选结果",
        "",
        "|候选|434净收益|434年化|434回撤|415净收益|415回撤|参数通过/N|组/层/层内名次|",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for t in table:
        lines.append(
            f"|{t['candidate_id']}|{t['net_return_434']:.4%}|{t['annual_return']:.4%}|{t['drawdown']:.4%}|{t['net_return_415']:.4%}|{t['drawdown_415']:.4%}|{t['parameter_passes']}/{t['parameter_points']}|{t['group']}/{t['within_group_pareto_layer']}/{t['within_layer_rank_min']}–{t['within_layer_rank_max']}|"
        )
    c = byid["C6105"]
    stress = next(r for r in panel["rows"] if r["candidate"]["candidate_id"] == "S015-C6105")[
        "stress_performance"
    ]
    time = next(x for x in timelines if x["candidate_id"] == "C6105")
    lines += [
        "",
        "## 稳健性解释",
        "",
        f"C6105投入从100%降至95%时，参数邻域年化{c['parameter']['min_annual_return']:.4%}、回撤{c['parameter']['max_drawdown']:.4%}，通过既定门槛。单边费用翻倍至0.2%时，年化{stress['annual_return']:.4%}、回撤{stress['drawdown']:.4%}；同场景基准年化{stress['benchmark_return']:.4%}、回撤{stress['benchmark_drawdown']:.4%}，压力条件通过。",
        f"时间稳定性仍有弱点：C6105的滚动252日超额收益Q10为{c['diagnostics']['ROLLING_EXCESS_Q10']['value']:.4%}，按相同初始财富累计比较曾连续{time['longest_wealth_below_benchmark']}个交易日落后基准。完整年度切片见[时间分布](others/time_slices.json)，首尾年份均保留但标记不完整，切片继承账户资金和持仓。",
        f"收益集中性：C6105前4个盈利周期占全部正利润{c['diagnostics']['PROFIT_CONCENTRATION']['value']:.4%}；年化超额收益区块重采样95%区间为{c['uncertainty']['lower_95']:.4%}至{c['uncertainty']['upper_95']:.4%}，包含0。这些诊断反映时点依赖和不确定性，不是新增硬门，也不是未来收益保证。",
        "原阶段三对即时再入场对照C6102的负面证据继续保留：C6105曾连续295交易日财富落后该对照，固定起点的9个252日网格窗口全部落后，期末另列窗口才反超。这里的295日比较对象是C6102，不能与上文买入持有基准的34日混淆。原EX064超限联合扰动失败与EX065满仓时间网格仅3日/3日达标也继续有效。此次局部豁免不消除时间尺度选择风险，不要求额外实验才能取得豁免。",
        "",
        "## 选择历史与统计不确定性",
        "",
        f"原176列加EX065的207个实际配置，核验并排除{len(family['excluded_previous_identities'])}个与历史相同内容或仅失活字段不同的复算后，保留{family['raw_trial_count']}列；17次重复Optuna提议不另加列。共有{family['distinct_exact_return_paths']}条逐位不同收益路径，有效试验数估计{family['effective_trial_count']['value']:.6f}。原176列内部相关与重复路径仍如实保留，372列不等于372个独立机会。早期组件、机制、标签等不同口径选择历史仍不完整，不能据有效数宣称整个研究只试了约2次。",
        "10块组合切分PBO为69.44%（此前58.33%）：在相应历史切分中，训练部分选出的配置在对应留出部分落入较差半区的比例较高。它不是未来亏损概率。这种切分不能把已见样本恢复成独立验证。",
        "DSR按原始计数为0.1435，按相关性有效数为0.7769；用于诊断的配置仍是C5902。两种数值均报告，不能择有利者采用，也不解读为策略成功概率。与旧值变化同时受到研究族分布和试验计数影响，不能理解为增加搜索提高了证据可信度。见[选择历史范围](others/family_summary.json)与[完整面板](others/summary.json)。",
        "",
        "## 排序、推荐与边界",
        "",
        "保留原始收益/回撤帕累托分层、六项层内顺序及原分箱精度；完成半/双精度及5项相邻优先级交换。平台按参数名称、单位、域、变化量、完整形状和约束身份区分可比性；不同投入中心的相对5%对应不同绝对变化量，加上单侧边界、确认轴有无，形成11组。不能改写comparison_sha256来合并，跨组不输出总名次。单成员组的第一名不代表总体最佳。",
        f"11个组的敏感性变体中，有{sum(bool(x['changed_rank_candidates']) for x in sensitivity)}个组/变体组合改变层内名次。见[分组排名](others/group_summary.json)、[排序敏感性](others/ranking_sensitivity_summary.json)、[行为分组](others/center_behavior_groups.json)。行为相同不合并源码身份。",
        "**研究员建议：优先将C6105提交用户选型。** 它的中心434日收益处于本轮16个候选最高水平，415日收益和回撤均满足对照目标，费用压力及可适用参数自检通过；采用固定退出，规则比同路径的确认保护候选更直接。这是明示取舍的研究推荐，不是跨11组正式排名第一，也不新增复杂度排序规则。C6201/6202/6104/6203提供较低投入、较低回撤与较低收益的取舍，全部保留。",
        "建议用户明确选择C6105后进入阶段五技术检验。阶段五检验执行与最终包等价性，不会自动补出新的独立市场样本；冻结必须另批精确计划。当前未选型、未冻结、未操作PTE或生产。",
        "",
        "## 技术核验与保存",
        "",
        "40份新账户现金、数量、费用、预算锁与闭合交易算术检查全部通过；16中心新旧五表经济一致；2个串并行对照五表完全一致。官方账户因果归因能力状态仍为UNSUPPORTED，不把独立算术核验称为因果识别。",
        "研究源码静态检查通过；本轮无平台代码修改，不重复仓库全回归。公开交付状态以发布回执的REPORT_PUBLICATION/FULL校验为准。协议、源账户身份、完整计划与材料显式关联，历史交付保持不可变；Git本身不能替代完整研究assets备份。",
    ]
    (HOME / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("REPORT_READY", len(table), len(groups["groups"]), len(behavior))


if __name__ == "__main__":
    main()
