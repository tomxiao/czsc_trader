"""Root reviewed EX066 scientific closeout; cannot certify robust strategy."""

from driver import ROOT, WORK, common, read, write, put, public, experiment, check_sources
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    plan = check_sources()
    exp = experiment()
    ctx = common.context(1)
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    result = read(public(refs["statistics.json"]))
    capacity = read(public(refs["supply.json"]))
    assert capacity["foresight_capacity"]["2022/h4"]["positive_nonoverlap_max_count"] == 28
    assert capacity["foresight_capacity"]["2023/h4"]["positive_nonoverlap_max_count"] == 30
    assert read(WORK / "verification.json")["status"] == "PASS"
    compact = {
        scope: {
            label: {
                "n": block["finite_target_n"],
                "components": {
                    c: {
                        "IC": v["partial_rank_ic"],
                        "CI": v["partial_block_ic95"]["ic95"],
                        "yearly": v["yearly"],
                        "phases": v["nonoverlap_phases"],
                    }
                    for c, v in block["components"].items()
                },
                "models": block["walk_forward"]["aggregate_models"],
                "groups": block["walk_forward"]["aggregate_groups"],
                "annual_groups": {
                    y: v["groups"] for y, v in block["walk_forward"]["yearly"].items()
                },
            }
            for label, block in panel["labels"].items()
        }
        for scope, panel in result["scopes"].items()
    }
    write(WORK / "compact_statistics.json", compact)
    review = {
        "status": "ROOT_REVIEWED_FIXED_HYPOTHESES",
        "new_hard_gates": False,
        "strategy_goal_achieved": False,
        "opportunity_capacity": "Foresight4day positive nonoverlap count2022=28/2023=30; mixture fullpool512, bestgrowth count353 already>=110; relaxed opening-fill diagnostics only, not a native-account guarantee.",
        "late_weakness": {
            "test_status": "SUPPORTED",
            "judgment": "仅在预声明的过去20日下跌且旧entry_eligible子集显示有限增量，h4 partialIC+.1942及描述性CI正，预测误差比原controls下降约2.37%；全池/广义下跌池失败、h8相位翻向、2023薄组且仍不如历史均值基准。保留条件性线索，暂不直接策略化。",
        },
        "early_reclaim_weakness": {
            "test_status": "INEFFECTIVE",
            "judgment": "全池及下跌池没有稳定增量；条件子集h4/8控制后相关近零、预测误差增大。停止本固定反向表达的策略化。",
        },
        "critical_scope": "entry_eligible is recorded even while signal holding; source explicitly sets confirmation_opportunity=not holding and eligible. These512 rows are not512 actual flat entry opportunities. Positive conditional subset220 may reflect held rebound instead of new entries.",
        "next": "事前留证后拆分真正空仓机会与持仓资格样本，复用原4/8净收益标签、固定旧信息及时间顺序方法，检查条件性线索来自哪里。不修改EX066原结果或冒称独立样本。",
        "controls_proxy_cost": "Fee transformation is strictly increasing in gross return, so rank correlations do not improve merely by subtracting fees; only economic mean/net-positive coverage changes.",
        "limitations": "Seen repeatedly researched development pool, future-aware capacity, fractional perfect opening-fill proxy, overlap, sparse annual groups and uncorrected selection bias; no full account ornew32.",
    }
    write(WORK / "judgment.json", review)
    report = """# EX066：扣费后做多机会供给与实际持有期限

新研究目标是找出数量足够、扣费后有盈利余量、能在当时识别的做多机会，再形成原硬门达标且抗扰动更强的策略。本轮阶段二诊断完成；稳健达标总目标尚未达成。原四门、只做多、统一后复权、费用和执行合同不变。频率按全开发池平均计算；buyhold亏损年份仍要求策略实际净收益严格正，不改为非负。

## 机会存在，但随意买入平均亏损

|年份|理想开盘成交下，4日扣费正收益非重叠机会最多笔数|8日最多笔数|全部4日标签平均毛收益|全部4日标签平均扣费收益|
|---|---:|---:|---:|---:|
|2022|28|17|−0.2874%|−0.4867%|
|2023|30|20|−0.1532%|−0.3527%|

机会计数使用未来收益挑选、固定持有1/4/8/10日、每侧10bp、交易间留一个session。全池混合期限正收益非重叠机会最多512笔；事后最优增长组合353笔，施加至少110笔约束未改变该组合。这里不存在可执行策略，不模拟限价、跳动、整手、资金预算或真实状态。它只说明这组有限期限及放宽成交假设下有正收益机会，不能证明实际策略可实现全部硬门或原目标普遍可行。

原C8880资格样本固定4日标签，2022/2023毛收益均值分别+0.0852%/+0.1308%，扣费后分别−0.1148%/−0.0692%。这支持盈利余量不足的解释，不等同完整账户的原退出结果。

## 固定反向尾盘信息有条件性线索

两项为EX061尾盘变化及早段价位收复的负号表达，不产生新信息。h4/h8为原bear4/bull8持有期限匹配，h1辅助；控制原14项信息。过去20日动量负分层事前固定，不以2022/2023年份选择规则。训练只用此前且标签已经结束的数据；2021—2026顺序测试；500×40session块诊断、seed13。

|范围、h4|尾盘弱势控制后相关|早段收复弱势控制后相关|
|---|---:|---:|
|全池|+0.0032|+0.0023|
|原资格池|+0.0628|+0.0477|
|过去20日下跌池|+0.0034|−0.0465|
|下跌且原资格池|+0.1942|−0.0140|

全池两项的1/4/8日增广模型合并预测误差全部更差，h4/h8控制后区间跨零，年度和非重叠相位不稳定。不能形成一般的“尾盘越弱越买”规则。

最强正证：下跌且资格成立子集，尾盘弱势h4描述性块区间[+0.0406,+0.3302]，h8相关+0.1301及区间[+0.0143,+0.2242]；h4顺序预测加入尾盘后误差比原controls下降约2.37%。历史训练分位高弱势组h4净标签均值+0.7879%，n53。

最强反证：该子集h4模型仍不如过去训练标签均值的基准；h8非重叠相位正负交替。2023高/低组各仅5行，不足报告年内组均值；2026样本不足。相关区间不校正反复开发选择，不能声称独立显著优势。早段收复弱势在该子集h4/h8无稳定增量，停止固定反向表达策略化。

## 新入场机会与持仓观察需要分开

源码中entry_eligible只检查位置、动量、ACF或资格恢复，即使已经持仓也记录；confirmation_opportunity才是not holding AND eligible。原512个资格样本并不全是空仓可以买入的机会。有限正证可能来自持仓后的反弹，不能立即移成入场过滤器。下一轮先事前声明真实空仓/持仓资格拆分，再决定组件职责，不改本轮已发布结果。

## 验证与研究边界

原C8880完整原生缓存与公开证据序列化精确相等；原执行价格公开转换精确重建，1636执行session及最终9月30日端点完整。原14controls逐值保持。48项合成检查通过；真实统计294项独立相关、成熟训练、分组和预测误差检查，6540条费用标签检查、35项独立贪心容量计数检查通过。Bootstrap和ridge未重复运行。

标签按下一开盘至下一开盘+h扣两侧10bp，是分数份额的成交代理，不是TDR完整账户；未叠加现金分红。期限改变可能遗漏原提前退出。已有5个30m High/Low问题保持，本组件直接复用EX061 close/volume观察；价格风险标签仍有原数据局限。已见开发池不是封存验证，历史真实发布时间和修订未独立验证。

本轮新账户、32点、自检和候选登记均为0，C8880原五项自检和0/32联合达标事实保持。声明前标准库同名导入失败、声明后Windows文件链接拒绝均保留；同EX066继续公开发布，没有重复分配实验或改动经济方法。技术FULL PASS确认材料一致性，不代表策略目标达成。
"""
    (WORK / "report.md").write_text(report, encoding="utf-8")
    conclusion = {
        "status": "PHASE_TWO_DIAGNOSTIC_COMPLETE",
        "robust_strategy_goal_achieved": False,
        "new_financial_accounts": 0,
        "new_parameter_points": 0,
        "candidate_registrations": 0,
        "next_step": review["next"],
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
    }
    write(WORK / "conclusion.json", conclusion)
    for n in (
        "compact_statistics.json",
        "judgment.json",
        "verification.json",
        "conclusion.json",
        "report.md",
        "finish.py",
    ):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    entries = []
    for component in ("late_weakness", "early_reclaim_weakness"):
        item = review[component]
        test = d.ComponentTestResult(
            component.upper() + "-fee-aware-horizon",
            exp.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(item["test_status"]),
            item["judgment"],
            tuple(
                EvidenceRef.from_dict(refs[n])
                for n in ("statistics.json", "supply.json", "verification.json", "judgment.json")
            ),
        )
        entries.append(
            d.ComponentEntry(
                component.upper(),
                d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["driver.py"]), "study"),
                "短期卖压回归线索；需辨别空仓入场及持仓恢复职责",
                "return4/8净标签主，return1辅助及配对downside",
                "T+1 Open至T+1+h Open；固定1/4/8预测，1/4/8/10机会容量",
                "原14controls、成熟训练分位、ridge10、500x40块诊断",
                "T8根30m完成，T+1可用；历史发布时间未独立验证",
                "原HFQ、无分红叠加、10bp两侧开盘成交代理；非完整账户",
                "S013已见全池与预声明资格/过去20日下跌子集，资格包含持仓行，非封存",
                item["judgment"],
                (test,),
            )
        )
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values()))
    predecessors = tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"])
    public_report = (
        report
        + "\n## 正式证据引用\n\n"
        + "".join(f"- [{n}]({EvidenceRef.from_dict(r).path})\n" for n, r in refs.items())
    )
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(ctx.batch, d.DeliveryStage.COMPONENTS, 5, predecessors),
        d.DeliveryContent(
            payload=d.ComponentPanel(
                tuple(entries),
                "机会供给存在；尾盘弱势条件性线索需真实空仓/持仓拆分；尚无新稳健策略",
            ),
            status=d.DeliveryStatus.COMPLETE,
            facts=(),
            explanations=(),
            report=public_report,
            evidence=evidence,
        ),
    )
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    write(exp.resolve(ROOT) / "protocols/delivery_validation.json", validation.to_dict())
    write(exp.resolve(ROOT) / "protocols/delivery_reference.json", receipt.reference.to_dict())
    write(exp.resolve(ROOT) / "protocols/final_evidence_references.json", refs)
    actual_report = (
        report
        + "\n## 正式证据引用\n\n"
        + "".join(
            f"- [{n}](../../../assets/deliveries/COMPONENTS/5/{EvidenceRef.from_dict(r).path})\n"
            for n, r in refs.items()
        )
    )
    (exp.resolve(ROOT) / "others").mkdir(exist_ok=True)
    (exp.resolve(ROOT) / "others/report.md").write_text(actual_report, encoding="utf-8")
    assert validation.status.value == "PASS", validation.to_dict()
    assert not common.SOURCE_CALLS
    print(
        {
            "experiment": exp.experiment_id,
            "FULL": validation.status.value,
            "strategy_goal_achieved": False,
            "new_accounts": 0,
            "receipt": receipt.reference.to_dict(),
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
