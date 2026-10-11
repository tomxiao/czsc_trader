"""Root interpretation of the single verified fixed study; no fitting or replays."""

from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-vol-concentration-result"


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


plan = read(WORK / "plan.json")
protocols = ROOT / "research/S013/experiments" / plan["experiment"]["experiment_id"] / "protocols"
refs = {
    **read(protocols / "method_references.json"),
    **read(protocols / "result_references.json"),
    **read(protocols / "audit_references.json"),
}
if read(WORK / "verification.json")["status"] != "PASS":
    raise ValueError("Independent PASS required before scientific review")
stats = read(WORK / "statistics.json")
panel = stats["scopes"]["actual_signal_continue"]
roles = {}
summary = {}
for label, block in panel["labels"].items():
    signal = block["components"]["vol_concentration"]
    models = block["walk_forward"]["aggregate_models"]
    old, new = models["controls"], models["controls+concentration"]
    summary[label] = {
        "finite_target_n": block["finite_target_n"],
        "partial_rank_ic": signal["partial_rank_ic"],
        "partial_ic95": signal["partial_block_ic95"],
        "pseudo_oos_n": new["n"],
        "mse_increase_vs_controls_pct": 100 * (new["mse"] / old["mse"] - 1),
        "mse_increase_vs_training_mean_pct": 100 * (new["mse"] / new["baseline_mse"] - 1),
        "aggregate_groups": block["walk_forward"]["aggregate_groups"],
        "yearly": signal["yearly"],
        "phases": signal["nonoverlap_phases"],
        "yearly_models": {
            year: row["models"] for year, row in block["walk_forward"]["yearly"].items()
        },
    }
    ci = signal["partial_block_ic95"]["ic95"]
    if (
        ci is None
        or not (ci[0] < 0 < ci[1])
        or not (new["mse"] > old["mse"] and new["mse"] > new["baseline_mse"])
    ):
        raise ValueError("This reviewed negative-result wording does not match actual data")
    roles[label] = {
        "status": "INEFFECTIVE",
        "judgment": (
            "固定负向h4继续收益信息未获支持：partial IC区间跨零，成熟伪样本外新增组件误差高于原24控制及训练均值。不能证明按此退出提高净收益。"
            if label == "return_4"
            else "固定正向h4观察风险信息未获支持：全组partial IC为负且区间跨零，年度与相位方向冲突，新增组件成熟伪样本外误差高于两基准；不反转方向继续搜索。"
        ),
    }
ret = summary["return_4"]
risk = summary["downside_4"]
rows = "\n".join(
    f"| {'继续4日收益' if label == 'return_4' else '未来4日观察下行风险'} | {item['partial_rank_ic']['value']:.6f} | [{item['partial_ic95']['ic95'][0]:.6f}, {item['partial_ic95']['ic95'][1]:.6f}] | +{item['mse_increase_vs_controls_pct']:.4f}% | +{item['mse_increase_vs_training_mean_pct']:.4f}% |"
    for label, item in summary.items()
)
report = f"""# EX078：最近波动变大，能否帮助决定提前退出

本轮固定4日/20日波动比，检验原C8880已经实际持仓、而T当天原策略仍计划继续的样本。两个预定用途均未获支持；没有启动任何新账户、费用压力或32点扰动。

## 目标保持

原四项经济要求与只做多、不加杠杆保持：整体收益、逐年回撤、全开发区间平均每60日不少于4笔闭合交易，以及buyhold亏损年份策略严格正收益。最终改善偏好仍是标准32点扰动收益Q10更高、回撤Q90更低，并报告逐项/联合达标率；不新增32/32硬门。

此项是阶段二信息检验，不能证明账户达标或抗扰动改善。原510500.SH开发区间、2019预热、后复权计价、固定1%执行合同保持；无分红重复计入，无新增数据源。

## 做了什么

固定std4(logCloseReturn,ddof0)/std20(logCloseReturn,ddof0)。控制原EX07122项、恢复late_recovery并加入log-return std20本身，共24项。未来收益比较明早卖出与继续4个完整交易日后卖出：两端同一SELL费用抵消，不错误扣一个新BUY费用；风险只观察同期Open/Close，不等于实际账户最大回撤。

原1635信号日不删日期，唯一因果持仓池{panel["eligible_n"]}日；388日未来标签已成熟，379日全部特征完整。区间采用500次40日全日期块重抽样；相位在原全日期轴固定。2021—2025年合计316日进入严格标签成熟后的逐年伪样本外预测；2026年只有11日，不满足20日测试样本最低数，按不可用保留，未补零或移除年份。

| 标签 | 控制后秩相关 | 描述性95%区间 | 新组件预测误差相对原控制 | 相对仅用历史均值 |
| --- | ---: | ---: | ---: | ---: |
{rows}

两项区间均跨过零，两个新增模型整体误差也都更高。按预定方向，将此固定组件记为未支持用途，并停止邻近窗口、翻符号和退出阈值救援。

## 正面线索与反证一起保留

- 收益模型在2021、2022、2025相对原控制有局部改善，但均未超过训练历史均值；2023及2024加入组件更差，不能只挑改善年份。
- 风险模型在2023、2025同时好于原控制与训练均值，这是有限正面线索；2022仅好于控制却差于均值，2021/2024加入组件更差，全组仍差于两基准。
- 2022年按事前训练分位切出的高波动集中组，平均继续收益约+0.2351%，低组约−0.0633%，与“高集中应更早卖”的收益方向相反。两组平均观察风险也为高组1.2887%、低组1.7467%，不是高集中风险更大。这里只是条件价格标签，绝不当作真实交易收益。
- 合并成熟年份的高集中组继续收益约+0.6808%、低组约+1.3473%；高组收益较低仍为正，不能据此认定提前退出有盈利优势。2023等年度分位组人数不足20，均值明确不可用，未把薄组当零。
- 五相位及年度符号不一致；完整数值、缺失理由和独立复算均保留。

## 判断与下一步

当前已检验的价格确认、恢复、压力和退出表达，尚未形成可靠的抗扰动改善依据。这不是全部价格信息无效，也没有证明三个约束不能兼容。EX066的事后正收益机会供给只说明历史有机会，未证明可提前识别并按真实限价、费用和足够交易次数兑现。

保留原候选与历史资格；C8880仍是此前六项复核对照中的参考基准，不能称已解决稳健目标。EX077整策略已在总收益与频率门失败，不用本轮组件改装救援。当前族停止无新依据的连续改窗、加过滤与提前退出账户。

最值得继续的问题是“什么事前信息能可靠区分扣费后值得做的反弹与无效交易”，并验证有足够数量与盈利余量兼顾频率和下跌年份。当前没有足够证据推荐下一个具体因子。后续应从新的、可解释且可证伪的机制依据出发，而非因本轮失败机械添加因子；原目标尚未达成。

## 验证范围

主方法已在真实统计前公开固定；唯一main统计。人工因果/边界检查PASS，原native完整序列化与公开证据完全一致，独立组件/持仓/标签/相关/重抽样/成熟预测复核PASS；0新账户、0provider调用。区间与伪样本外均来自已见开发池，不是封存验证，未纠正反复研究选择偏差。完整账户/五项自检/32点未运行，不填结果。
"""
review = {
    "status": "ROOT_REVIEWED",
    "reviewed_utc": datetime.now(timezone.utc).isoformat(),
    "experiment": plan["experiment"],
    "evidence_references": {
        key: refs[key] for key in ("plan.json", "statistics.json", "verification.json")
    },
    "roles": roles,
    "summary": summary,
    "judgment": "固定4/20波动集中在原实际持仓且计划继续池，没有形成可靠新增h4观察风险或继续收益信息；止步该固定用途，0账户。当前价格确认/压力/退出组件族收口，整体硬门与抗扰动目标尚未达成。",
    "objective_achieved": False,
    "original_four_hard_gates_changed": False,
    "new_hard_gates": False,
    "new_accounts": 0,
    "new_standard_perturbations": 0,
    "provider_calls": 0,
    "report_markdown": report,
}
with (WORK / "root_review.json").open("x", encoding="utf-8") as stream:
    json.dump(review, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write("\n")
print(
    {
        "status": "ROOT_REVIEWED",
        "summary": {
            label: {
                key: value
                for key, value in item.items()
                if key
                in (
                    "pseudo_oos_n",
                    "mse_increase_vs_controls_pct",
                    "mse_increase_vs_training_mean_pct",
                )
            }
            for label, item in summary.items()
        },
        "objective_achieved": False,
    }
)
