"""Reviewed EX067 responsibility split; no strategy qualification."""

from driver import ROOT, WORK, common, read, write, put, public
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    ctx = common.context(1)
    plan = read(WORK / "plan.json")
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    verification = read(WORK / "verification.json")
    assert verification["status"] == "PASS" and verification["checks"] == 256
    result = read(public(refs["statistics.json"]))
    compact = {
        s: {
            "eligible_n": panel["eligible_n"],
            "labels": {
                label: {
                    "n": block["finite_target_n"],
                    "component": block["components"]["late_weakness"],
                    "models": block["walk_forward"]["aggregate_models"],
                    "groups": block["walk_forward"]["aggregate_groups"],
                }
                for label, block in panel["labels"].items()
            },
        }
        for s, panel in result["scopes"].items()
    }
    judgment = {
        "role": "RSCH",
        "strategy_goal_achieved": False,
        "entry_status": "INEFFECTIVE",
        "entry_judgment": "原资格池的尾盘弱势正证主要集中在持仓行。真正空仓h4/h8增量不稳，4日顺序预测误差增大；下跌空仓只有69行，单独成熟训练不足，共用原模型4日仍略差。不授予入场资格，停止尾盘弱势买入路线。",
        "held_status": "SUPPORTED",
        "held_judgment": "下跌持仓样本h4/h8控制后正相关及描述性块区间为正，配对downside负相关；同一原池预测h4误差减约2.92%。仅保留条件性恢复线索；假想fresh-entry标签不是实际继续持有收益，不据此修改退出。",
        "thin_is_not_failure": "下跌空仓组单独模型n0来自既定成熟训练样本限制，非零收益或确定无效；共用预测n40仍可提供有限反证。",
        "selection_disclosure": "已见EX066结果后拆分，开发池自适应归因非独立验证；未校正多重开发选择；原策略状态不是实际账户持仓。",
        "next": "研究日内下跌先后顺序与连续卖压，控制原14项、EX061两观察以及日内总上涨/下跌量；固定少量假说先留证验证，不再反复调旧尾盘阈值。",
        "new_hard_gates": False,
        "new_accounts": 0,
        "new_parameter_points": 0,
    }
    report = """# EX067：真正空仓机会与持仓观察拆分

本轮目标是判断EX066尾盘弱势的条件性线索能否用于新买入。原四项经济硬门保持：频率按整个开发池平均，buyhold亏损年份要求策略净收益严格正。稳健达标总目标尚未达成。

## 原资格池多数是持仓行

|原信号状态|样本数|过去20日动量负的子集|
|---|---:|---:|
|真正空仓且资格成立|147|69|
|已经持仓但资格仍成立|365|154|

原entry_eligible即使持仓也记录，confirmation_opportunity才是空仓且资格成立。全部1635信号行均独立核验其等于资格成立且前一原target_position为0；这里按原策略信号状态拆分，并非实际账户数量。原512资格行不能全部称为可新买入机会。下跌子集223行；EX066 h4有限标签和controls后约220行，缺失端点不混为不同机会来源。

## 尾盘弱势不支持新买入

|样本、期限|控制原信息后相关|描述性40session块区间|
|---|---:|---|
|真正空仓、4日|+0.0879|[-0.1221,+0.2780]|
|真正空仓、8日|-0.0034|[-0.1477,+0.1598]|
|下跌空仓、4日|+0.0889|[-0.2432,+0.3628]|
|下跌空仓、8日|-0.0010|[-0.2462,+0.3190]|
|下跌持仓、4日|+0.2344|[+0.0516,+0.3682]|
|下跌持仓、8日|+0.1742|[+0.0066,+0.3133]|

真正空仓单独逐年成熟训练，4日加入尾盘弱势后预测误差由0.002068736升至0.002089899，8日也略差。下跌空仓单独模型因历史成熟训练不足没有预测记录，不能写成零收益或确定没有机会。

为排除小组分别拟合的影响，复用EX066同一套已训练预测和训练分位阈值再按原状态拆分，不重拟合。下跌原资格池4日共同预测：空仓40行误差由0.000472272升至0.000473230，持仓123行由0.000717789降至0.000696831，改善约2.92%。8日空仓误差小幅改善约0.20%，但其控制后相关接近零、区间跨零，不足支持入场。2023下跌空仓高/低尾盘弱势组分别1/2行，不能据此估计该亏损年份的经济效果。

下跌持仓配对4/8日最大不利变动相关为-0.2322/-0.2413，描述性块区间均负。这是有限的恢复线索；标签仍是假想新买入的固定期限收益和不利变动，不等同实际持仓剩余收益，更不能直接推出放宽退出会赚钱。持仓4日模型仍不如历史均值基准。

结论：停止“尾盘越弱越买”的入场路线；保留持仓恢复线索，暂不策略化。下一路线研究日内下跌发生的先后顺序与连续卖压，控制旧信息和总涨跌量，检验是否存在新增信息。

## 验证及限制

原C8880原生序列化与公开证据精确一致，资格逐值一致，无外部provider调用；EX066原features和费用标签精确复用。6项合成检查与256项独立Spearman、预测真值/MSE、成熟训练、分组阈值/计数/均值及状态划分核验通过。500x40块诊断与ridge未重复拟合复算，区间不是经开发选择校正的独立显著性。

本轮是已见开发池的自适应职责归因，原信号状态受原策略规则影响；不能推断所有其他策略的机会数量。分数份额、理想开盘成交、两侧10bp代理未含真实限价/跳动/整手执行，不能代替完整TDR账户。本轮新账户、新32点、自检及候选登记均为0；C8880已有五项自检及0/32联合达标事实保持。技术FULL校验不等同策略经济目标达成。
"""
    write(WORK / "compact_statistics.json", compact)
    write(WORK / "judgment.json", judgment)
    write(
        WORK / "conclusion.json",
        {
            "status": "PHASE_TWO_RESPONSIBILITY_AUDIT_COMPLETE",
            "robust_strategy_goal_achieved": False,
            "economic_targets_unchanged": True,
            "new_hard_gates": False,
            "new_accounts": 0,
            "next": judgment["next"],
        },
    )
    (WORK / "report.md").write_text(report, encoding="utf-8")
    for n in (
        "compact_statistics.json",
        "judgment.json",
        "conclusion.json",
        "verification.json",
        "report.md",
        "finish.py",
    ):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    entries = []
    for state in ("entry", "held"):
        test = d.ComponentTestResult(
            "LATE-WEAKNESS-" + state.upper(),
            exp.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(judgment[state + "_status"]),
            judgment[state + "_judgment"],
            tuple(
                EvidenceRef.from_dict(refs[n])
                for n in (
                    "statistics.json",
                    "common_transfer.json",
                    "verification.json",
                    "judgment.json",
                )
            ),
        )
        entries.append(
            d.ComponentEntry(
                "LATE-WEAKNESS-" + state.upper(),
                d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["driver.py"]), "study"),
                "原策略空仓入场/持仓恢复职责归因",
                "固定4/8净收益及配对downside",
                "T+1 Open到T+1+h Open",
                "原14controls、ridge10、500x40块、共用原成熟预测拆分",
                "T8根完成、T+1可用；历史实际发布时间未独立验证",
                "原HFQ，无分红叠加，两侧10bp开盘成交代理",
                "S013已见开发池原信号状态；非封存",
                judgment[state + "_judgment"],
                (test,),
            )
        )
    public_report = (
        report
        + "\n## 正式证据引用\n\n"
        + "".join(f"- [{n}]({EvidenceRef.from_dict(r).path})\n" for n, r in refs.items())
    )
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(
            ctx.batch,
            d.DeliveryStage.COMPONENTS,
            6,
            tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"]),
        ),
        d.DeliveryContent(
            payload=d.ComponentPanel(
                tuple(entries), "尾盘弱势不支持入场；正证集中持仓，尚无新达标策略"
            ),
            status=d.DeliveryStatus.COMPLETE,
            facts=(),
            explanations=(),
            report=public_report,
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values())),
        ),
    )
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    for name, value in (
        ("delivery_validation.json", validation.to_dict()),
        ("delivery_reference.json", receipt.reference.to_dict()),
        ("final_evidence_references.json", refs),
    ):
        write(exp.resolve(ROOT) / "protocols" / name, value)
    (exp.resolve(ROOT) / "others").mkdir(exist_ok=True)
    (exp.resolve(ROOT) / "others/report.md").write_text(
        report
        + "\n## 正式证据引用\n\n"
        + "".join(
            f"- [{n}](../../../assets/deliveries/COMPONENTS/6/{EvidenceRef.from_dict(r).path})\n"
            for n, r in refs.items()
        ),
        encoding="utf-8",
    )
    assert validation.status.value == "PASS", validation.to_dict()
    assert not common.SOURCE_CALLS
    print(
        {"experiment": exp.experiment_id, "FULL": validation.status.value, "goal_achieved": False},
        flush=True,
    )


if __name__ == "__main__":
    main()
