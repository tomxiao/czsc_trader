"""Scientific review of EX068 fixed intraday-order hypotheses."""

from driver import ROOT, WORK, common, read, write, put, public
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    ctx = common.context(1)
    refs = read(exp.resolve(ROOT) / "protocols/verification_references.json")
    assert read(public(refs["verification.json"]))["status"] == "PASS"
    result = read(public(refs["statistics.json"]))
    compact = {
        s: {
            label: {
                "n": b["finite_target_n"],
                "components": b["components"],
                "models": b["walk_forward"]["aggregate_models"],
                "groups": b["walk_forward"]["aggregate_groups"],
                "yearly_groups": {y: v["groups"] for y, v in b["walk_forward"]["yearly"].items()},
            }
            for label, b in panel["labels"].items()
        }
        for s, panel in result["scopes"].items()
    }
    review = {
        "role": "RSCH",
        "strategy_goal_achieved": False,
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
        "early_down_share": {
            "status": "INEFFECTIVE",
            "judgment": "固定早盘下跌占比正向h4假说不支持：全池/下跌池控制后负且区间跨零，空仓模型增广退化；不逆转方向救援，停止本表达策略化。",
        },
        "max_down_run_share": {
            "status": "INEFFECTIVE",
            "judgment": "全池与原空仓资格无稳定新增收益信息。保留下跌池低连续段h4净均值+.1712%及收益MSE改善约.215%的局部事实；2022低组仍-.8215%，2023+.3091%，风险MSE变差、控制后区间跨零、8日退化。不足以修复两个亏损年份或证明账户改善，停止本组策略化。",
        },
        "thin_rank_warning": "18项controls加截距，20行薄相位的残差自由度可仅1，出现±1不代表强证据。原研究原件保持，主判断不用薄相位作正证。后继预声明按n-rank(design)报告df，至少10残差自由度才解释partial相关；是统计可解释性口径，非经济硬门。",
        "next": "转向此前四天的价格伸展与隔夜/盘中下跌构成，两固定假说控制全部旧信息和新顺序信息，原4/8净收益与配对风险标签保持；先声明和合成再统计。",
        "new_accounts": 0,
        "new_parameter_points": 0,
    }
    report = """# EX068：日内下跌顺序与连续段对照

本轮从原尾盘入场路线转向新增顺序信息。固定两个观察：前4根30分钟负收益占全天负收益的比例；最大连续严格负收益段的累计跌幅占全天负收益的比例。零/正变动中断连续段，没有负变动时比例0仅代表无下跌。控制原14项、EX061两原观察和总上涨/下跌量，共18项；不是重排旧评分或搜索阈值。主4日净收益和途中不利变动，8日辅助。

## 入场增量不足

|范围、4日|早段下跌占比控制后相关|最大连续段占比控制后相关|收益预测|
|---|---:|---:|---|
|全开发池|-0.0261|-0.0086|三种增广均更差|
|过去20日下跌|-0.0112|-0.0464|仅连续段略改善|
|原信号真正空仓资格|+0.0294|-0.0123|三种增广均更差|
|下跌且原空仓|-0.0338|-0.0697|成熟训练及分年测试样本不足|

上述控制后描述性块区间均跨零。全池4日三种增广模型及8日三种均退化；空仓4/8同样如此。早盘先跌后稳的正向固定假说未得到支持，不将负向结果翻号后宣布成功。

## 连续卖压有局部线索，但不能解决两个亏损年份

过去20日下跌池，按此前成熟训练Q25/Q75，连续段低组4日扣费代理均值+0.17119%，n184；高组-0.33359%，n159。单加连续段MSE由0.00089735249降到0.00089541904，改善约0.215%，仍不如过去训练均值基准0.00089291259。配对4日风险MSE却由0.00044605532升到0.00044668757。

|年份|低连续段组4日扣费均值|样本|高组均值|样本|
|---|---:|---:|---:|---:|
|2022|-0.82148%|48|-1.44547%|35|
|2023|+0.30906%|42|-0.41629%|30|
|2024|+0.37390%|36|+0.25520%|29|
|2025|+0.97621%|22|-0.42836%|23|

不能把跨年份平均正收益当作每个buyhold亏损年份均盈利。2022低组仍大幅负，8日预测退化，原空仓增量未成立。结论是保留局部正面事实，停止本组直接策略化；未运行账户验证，不宣称账户或参数扰动已改善。

## 薄相位及价格代理限制

18项controls加截距，当薄相位仅20行时残差空间可能只剩一个维度，相关±1不构成强证据。本轮原统计完整保留；判断不依赖这些薄相位。后继将事前声明残差自由度口径，避免解释自由度不足的partial相关，不新增策略经济门。下跌且原空仓69行、有效约67，逐年模型/分组样本不足；不能称作零收益或2023已经验证。

原EX058原生序列化、既有公开30分钟计价、EX061两原观察的源码重算/公开列/EX066负号列、原14controls均精确核对。纯组件20项合成检查、25项非法输入拒绝，统计7项合成检查及224项独立真实核验通过；没有新增provider或账户。Bootstrap与ridge未重复拟合复算。全池1635行，过去20日下跌757行，原空仓资格147行、其中下跌69行；该空仓是原策略信号状态，非实际账户数量。

固定净收益标签使用下一开盘至下一开盘+h、两侧10bp、分数份额理想成交，原后复权且不叠加分红。风险标签的Low保留已有数据问题，不能代替真实最大回撤。开发池已反复见过，区间未校正开发选择，非独立封存验证。原四项硬门和最新五项自检定义保持，新账户、新32点、自检及候选登记均0，稳健达标总目标尚未达成。

下一路线研究此前四天的价格伸展，以及负变动主要来自隔夜还是盘中；固定少量假说，控制旧信息与本轮顺序信息后检验增量。
"""
    write(WORK / "compact_statistics.json", compact)
    write(WORK / "judgment.json", review)
    write(
        WORK / "conclusion.json",
        {
            "status": "PHASE_TWO_ORDER_STUDY_COMPLETE",
            "goal_achieved": False,
            "economic_targets_unchanged": True,
            "new_accounts": 0,
            "next": review["next"],
        },
    )
    (WORK / "report.md").write_text(report, encoding="utf-8")
    for n in (
        "compact_statistics.json",
        "judgment.json",
        "conclusion.json",
        "report.md",
        "finish.py",
    ):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    entries = []
    for c in ("early_down_share", "max_down_run_share"):
        j = review[c]
        test = d.ComponentTestResult(
            c.upper() + "-H4",
            exp.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(j["status"]),
            j["judgment"],
            tuple(
                EvidenceRef.from_dict(refs[n])
                for n in ("statistics.json", "verification.json", "judgment.json")
            ),
        )
        entries.append(
            d.ComponentEntry(
                c.upper(),
                d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["driver.py"]), "study"),
                "日内下跌顺序与连续段的新入场增量",
                "return4/downside4主，return8/downside8辅",
                "T+1开盘至T+1+h开盘",
                "18controls；500x40块seed13；成熟顺序训练ridge10，四模型同样本",
                "T8根30m完成，T+1可用；历史实际发布时间未独立验证",
                "原HFQ，两侧10bp开盘代理，无分红叠加",
                "S013已见全池/过去20日下跌/原信号空仓资格，非封存",
                j["judgment"],
                (test,),
            )
        )
    links = "\n## 正式证据引用\n\n" + "".join(
        f"- [{n}]({EvidenceRef.from_dict(r).path})\n" for n, r in refs.items()
    )
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(
            ctx.batch,
            d.DeliveryStage.COMPONENTS,
            7,
            tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"]),
        ),
        d.DeliveryContent(
            payload=d.ComponentPanel(
                tuple(entries), "日内顺序增量不足；局部收益事实不等于亏损年份达标"
            ),
            status=d.DeliveryStatus.COMPLETE,
            facts=(),
            explanations=(),
            report=report + links,
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values())),
        ),
    )
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    for n, value in (
        ("delivery_reference.json", receipt.reference.to_dict()),
        ("delivery_validation.json", validation.to_dict()),
        ("final_evidence_references.json", refs),
    ):
        write(exp.resolve(ROOT) / "protocols" / n, value)
    (exp.resolve(ROOT) / "others").mkdir(exist_ok=True)
    (exp.resolve(ROOT) / "others/report.md").write_text(
        report
        + "\n## 正式证据引用\n\n"
        + "".join(
            f"- [{n}](../../../assets/deliveries/COMPONENTS/7/{EvidenceRef.from_dict(r).path})\n"
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
