"""EX069 scientific responsibility review, retaining the strongest counterevidence."""

from driver import ROOT, WORK, common, read, write, put, public
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    ctx = common.context(1)
    plan = read(WORK / "plan.json")
    refs = read(exp.resolve(ROOT) / "protocols/verification_references.json")
    assert read(public(refs["verification.json"]))["status"] == "PASS"
    result = read(public(refs["statistics.json"]))
    review = {
        "role": "RSCH",
        "strategy_goal_achieved": False,
        "new_hard_gates": False,
        "short_stretch4": {
            "status": "SUPPORTED",
            "judgment": "仅原真正空仓资格池4日控制后负相关符合固定假说，CI负。保留条件性入场线索，允许一个固定完整账户反证；增广MSE退化、风险不改善、2023薄组且广义下跌两亏损年均值负，因此不是一般越跌越买规律，更不是策略资格。",
        },
        "overnight_down_share4": {
            "status": "INEFFECTIVE",
            "judgment": "隔夜下跌占比越高后续恢复越好的固定正向假说被下跌状态反证：控制后return4负及downside4正，描述性区间均不跨0。停止本正向入场表达，不翻号宣称原假说成功；保留条件性风险线索，后继需要单独职责与账户验证。",
        },
        "next": "保留原C8880买入确认与退出，仅增加原空仓且eligible时4日价格回落可作为OR替代确认的固定路径，与原完整账户作一次中心对照；不扫阈值。新增lookback是有效参数，若中心通过四门才另事前声明包含该参数的标准32点与最新五项自检，不能漏扰动或把14维与旧13维混称相同。",
        "causal_warning": "新OR路径会改变后续持仓轨迹；保留原确认规则不保证旧每笔交易仍发生。信号空仓不是实际账户数量，增加机会不等于新增成交或利润。",
        "economic_targets_unchanged": True,
        "new_accounts": 0,
        "new_parameter_points": 0,
    }
    compact = {
        s: {
            label: {
                "components": b["components"],
                "models": b["walk_forward"]["aggregate_models"],
                "groups": b["walk_forward"]["aggregate_groups"],
                "yearly_groups": {y: v["groups"] for y, v in b["walk_forward"]["yearly"].items()},
            }
            for label, b in p["labels"].items()
        }
        for s, p in result["scopes"].items()
    }
    report = """# EX069：此前四天的价格伸展与下跌构成

在S013既有开发池及原预热期研究两个固定假说：4日净价格变化除以原20日波动及sqrt4，越低随后4日收益越好；4日负变动中隔夜占比越高随后恢复越好。原20controls=原14、EX061两原观察、EX068两顺序及总涨跌量。主4日净收益及配对不利变动，8日辅助。原四经济硬门保持，统计诊断不新增经济门。

## 价格回落只有条件性入场线索

|范围、4日|short_stretch控制后相关|描述性500x40块区间|
|---|---:|---|
|全池|-0.0244|[-0.0926,+0.0415]|
|过去20日下跌|-0.0644|[-0.1701,+0.0394]|
|原信号真正空仓资格|-0.2735|[-0.4440,-0.1077]|
|下跌且原空仓|-0.3138|[-0.5760,+0.0803]|

原空仓资格池4日符合事前负向假说，残差自由度124；训练分位低/高组扣费代理均值+0.9100% n23/+0.7929% n26。该子集年份可报raw相关2020—2024均负，其中2022有效控制后相关-0.2677、残差自由度11。其余年份多因控制后的自由度不足不能报告partial；2023低/高组7/9行，不能估计该年分组盈利。五个非重叠相位只有phase1控制后自由度足够，相关-0.4073，另外四相位不报partial，不择相位交易。

最强反证：原空仓4日三种增广MSE全部更差，单加stretch由0.002083594升至0.002087259；配对风险未改善。全池4/8收益和4日风险三增广均退化。广义下跌低stretch组4日2022-0.79782% n45、2023-0.15939% n40、2024+1.84937% n34；跨年平均正收益不能证明两个亏损年均正，不能一般化“越跌越买”。

研究员判断：保留有限的空仓条件性入场线索，允许一个固定完整账户反证来解决统计相关与预测误差的冲突，不把它当作新策略已合格。

## 隔夜下跌更易恢复的正向假说失败

过去20日下跌池，隔夜负变动占比4日控制后收益相关-0.10853、区间[-0.23717,-0.01240]，对应不利变动相关+0.09907、区间[+0.02194,+0.21423]，与原预设正向恢复相反。单加该观察收益MSE略降约0.134%，风险MSE变差，收益仍不如训练均值基准。低占比2022-0.25160% n37、2023+0.17371% n74，高组分别-0.91036% n40/-0.56434% n22。

停止此正向买入表达；负面风险事实完整保留，但不翻号宣布原假说成功。任何持仓风险用途都须另作职责与完整账户验证。

## 下一最小账户反证

原C8880买入确认与所有退出规则保留，仅在自身当前空仓且原entry_eligible时，允许“原确认通过 OR 完整4日历史、原波动为正且4日价格回落”入场。4日和零阈值不优化，正常成交、资金、费用、后复权和固定1%执行合同保持。OR路径会改变后续持仓轨迹，不保证原基线每笔交易仍发生；原信号资格不等于实际成交。

先比较原账户与单个新中心的四项经济门。如果中心不达标，停止此固定表达并完整报告；如果达标，再事前声明包含新增lookback有效参数的标准32点和最新五项自检。不能只扰原13参数，也不能把新增14维几何与旧13维直接称为逐点相同。原四门合格与抗扰动目标分别报告，不增加新的经济否决门。

## 验证与局限

原EX058原生序列化与公开已计价日价、原1815行后复权warmup重叠区间、原volatility20、20controls均精确核验；1635开发信号保持，原费用标签按字节复用；没有新provider。纯组件16合成/18非法拒绝、统计9合成、3942真实独立核验通过。方法/合成/计划/最终格式化源码哈希一致；Bootstrap与ridge未重新拟合复算。

本轮事前声明n-rank(design)为残差自由度，低于10时partial明确不可用，共108个薄相位如此；是可解释性诊断而非策略经济门。全部原结果保留，不改EX066—068原件。

标签仍是T+1开盘至T+1+h理想分数份额成交、两侧10bp净收益代理，后复权且不叠加分红。风险Low保留原数据局限，不能代替真实账户回撤。反复已见开发池、自适应假说与未校正选择偏差不构成封存验证。本轮账户、32点、自检、候选登记均0，稳健达标总目标尚未达成。
"""
    write(WORK / "judgment.json", review)
    write(WORK / "compact_statistics.json", compact)
    write(
        WORK / "conclusion.json",
        {
            "status": "PHASE_TWO_PRESSURE_COMPLETE",
            "goal_achieved": False,
            "economic_targets_unchanged": True,
            "new_accounts": 0,
            "next": review["next"],
        },
    )
    (WORK / "report.md").write_text(report, encoding="utf-8")
    for n in (
        "judgment.json",
        "compact_statistics.json",
        "conclusion.json",
        "report.md",
        "finish.py",
    ):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    entries = []
    for c in ("short_stretch4", "overnight_down_share4"):
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
                "此前四天的入场盈利/风险线索",
                "return4/downside4主，return8/downside8辅助",
                "T+1 Open至T+1+h Open",
                "原20controls；残差df至少10；500x40seed13；成熟训练ridge10四模型同样本",
                "当日结束后可用，T+1执行；原warmup，无历史实际发布时间复核",
                "原HFQ与费用代理，不叠加分红",
                "原开发池/过去20日下跌/原信号空仓资格，非封存",
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
            8,
            tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"]),
        ),
        d.DeliveryContent(
            payload=d.ComponentPanel(
                tuple(entries), "回落的有限条件性入场线索进入最小账户反证；隔夜恢复正向假说失败"
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
    for n, v in (
        ("delivery_reference.json", receipt.reference.to_dict()),
        ("delivery_validation.json", validation.to_dict()),
        ("final_evidence_references.json", refs),
    ):
        write(exp.resolve(ROOT) / "protocols" / n, v)
    (exp.resolve(ROOT) / "others").mkdir(exist_ok=True)
    (exp.resolve(ROOT) / "others/report.md").write_text(
        report
        + "\n## 正式证据引用\n\n"
        + "".join(
            f"- [{n}](../../../assets/deliveries/COMPONENTS/8/{EvidenceRef.from_dict(r).path})\n"
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
