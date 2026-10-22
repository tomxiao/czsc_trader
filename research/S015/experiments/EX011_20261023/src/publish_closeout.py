"""Publish the stage-two synthesis and retain a compact public overview audit."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json

from incremental_study import ROOT, HERE, WORK, EX, OLD, context, material, read, save
from czsc_trader.application import (
    RepositoryContext,
    publish_evidence,
    assemble_delivery,
    validate_experiment,
    update_research_intent,
    ResearchIntentUpdate,
    get_research_overview,
)
from czsc_trader.research_tools import (
    EvidenceRef,
    ExperimentReportWrite,
    ExperimentOutcome,
    ExperimentValidationRequest,
    ExperimentValidationScope,
    ResearchBatchRef,
)
from czsc_trader.research_tools import delivery as d


def pct(v):
    return f"{100 * v:.3f}%"


def interval(v):
    return f"[{pct(v[0])}, {pct(v[1])}]"


def judgment(row):
    c, h, control = row["component"], row["horizon"], row["control"]
    if control == "PROther":
        return (
            "REDUNDANT",
            "相对于另一个分钟组件，未得到跨年稳定的独有增量；仅指本模型和标签下的互相替代，不能证明信息数学等价。",
        )
    if c == "afternoon":
        return (
            "INEFFECTIVE",
            "仍有反向分组关联，但收益增量主要来自2026；未支持把午后绝对收益作为稳定的独立新增职责。并非完全没有信息。",
        )
    roles = {
        1: "限定支持1日下行风险诊断；四段均改善。收益预测总体没有改善，不能作为独立收益入口。",
        2: "限定支持2日风险分层，收益仅为探索线索；两年增量为正，但前两段收益预测变差，不能宣称稳定增收。",
        3: "限定支持3日收益信息探索；四段预测小幅改善，但区间跨零、分组不单调；不支持3日风险的跨年稳定用途。",
    }
    return "SUPPORTED", roles[h] + "属于已见开发池中的相对日线控制证据，不是独立验证或策略通过。"


def report():
    result = read(HERE / "others/incremental_results.json")
    rows = result["comparisons"]
    table, opp, sensitivity = [], [], []
    for r in rows:
        s = r["summary"]
        if r["control"] == "PR":
            table.append(
                f"| {r['component']} / {r['horizon']}日 | {s['n']} | {pct(s['return_gain'])} | {pct(r['years']['2025']['return_gain'])} / {pct(r['years']['2026']['return_gain'])} | {pct(s['risk_gain'])} | {pct(r['years']['2025']['risk_gain'])} / {pct(r['years']['2026']['risk_gain'])} | {interval(r['gain_intervals']['20']['return'])} | {interval(r['gain_intervals']['20']['risk'])} |"
            )
            hi, lo = s["group_1"], s["group_-1"]
            opp.append(
                f"| {r['component']} / {r['horizon']}日 | {hi['n']} / {s['group_0']['n']} / {lo['n']} | {pct(hi['mean_label'])} / {pct(lo['mean_label'])} | {pct(hi['mean_fee_sensitive_label'])} | {pct(lo['negative_amount_fraction'])} | {pct(lo['positive_amount_fraction'])} | {pct(hi['positive_amount_fraction'])} |"
            )
        else:
            sensitivity.append(
                f"| {r['control']} | {r['component']} / {r['horizon']}日 | {pct(s['return_gain'])} | {pct(s['risk_gain'])} | {judgment(r)[0]} |"
            )
    text = (
        """# S015 新目标阶段二收口：分钟信息增量与决策用途

Status: COMPLETED

RSCH，2026-10-23。用户最新指令为“请你自主完成阶段二”。本报告完成EX010之后的必要补证和阶段判断，承接MANDATE/3及COMPONENTS/4。**阶段二目标已达成；S015完整策略的收益、回撤双优目标尚未达成。**

## 研究结论

现有数据支持保留少量、用途受限的信息，但不足以宣布找到了能够同时超越S011收益和回撤的策略。近期振幅仍是已有风险信息；分钟线增加了一些日线卖压之外的时序信息，其中“午后相对上午变化”更适合作为短期风险分层和三日收益探索线索。两个午后指标不宜当作两份独立信号叠加。

1. **优先保留1日风险信息。** 控制近1/5日收益、20日波动、收盘相对成交均价及近期振幅后，afternoon_reversal的下行风险预测均方误差降低0.981%；2025/2026分别降低1.576%/0.792%，四段均改善。20日块探索区间为[0.063%,2.369%]。这是对保守日内低点几何的预测改善，不是账户回撤降低0.981个百分点；C0031已持仓子样本反而变差0.565%，不能直接当作持仓减仓或退出信号。
2. **三日收益只有小幅探索增量。** 同一组件的收益预测误差降低0.793%，四段均为正；20日块区间[-0.001%,1.375%]仍跨零。2日改善0.902%，但前两段变差。收益分组也不单调：2/3日中间组均优于高分组。因此保留“识别较差条件”的假设，不推断分数越高越值得买。
3. **午后绝对收益没有确立稳定独有职责。** 六项主比较中其三个收益期限都在2025变差、2026改善。再控制另一个分钟指标后，18个条件中的六项互补检验均未产生跨年稳定独有增量，风险预测全部变差；不把它们累计成两个独立收益来源。REDUNDANT仅是本模型、期限下的研究判断，不是数学等价证明。
4. **规避损失需要付出机会成本。** 以afternoon_reversal的2日标签为例，排除低分组对应避开45.25%的负标签金额，也错失30.78%的正标签金额；只保留高分组仅保留34.22%的正标签金额。近期振幅的旧1日诊断更是避开40.29%亏损同时错失46.04%盈利。不能把这些过滤理解成免费降低风险。

## 授权、方法与计数

EX010原12组件×3期限=36项已结束，本次依据自主完成阶段二的新授权，事前发布[协议](protocols/incremental_protocol.json)、授权原文及执行源码，再计算6项主比较与12项对照敏感性检查。合计18项新增成对条件，每项检验收益和风险两个结果，4个时间折；没有参数搜索或新策略账户。当前新目标阶段二合计54项条件，其中原36项、补证6项、敏感性12项，不能把共享样本的54项当作独立证据。

- 主控制PR：近1日/5日收益、20日波动、pressure（收盘相对全天成交均价的位置）、calm_range（近期振幅相对较长期振幅）。逐次只加一个分钟组件。
- 敏感性P去掉振幅控制；PROther在PR上加入另一个分钟组件，再检验待测组件。分别6项，完整保留，不只报告最优结果。
- 岭回归惩罚固定10、训练内标准化；前100个决策日训练后，依次测试第100–183、184–267、268–351、352–433日。训练标签的退出日严格早于该段首个决策日。测试有效事件为325/324/323个。
- 分组分数是分钟组件对日线控制的训练内回归残差取负；高分代表午后相对控制所预测的水平更弱。分界为训练残差三分位，不寻优。本次反向选择来自已观察的EX010，明确属于开发后选择；未改写EX010事前正向假设及其失败状态。
- 特征只用T日及以前的数据，17:30决策；30分钟线截至15:00。所有行情来自原DFLS准备，509日日线含75日预热、434日3472根30分钟线，截止2026-10-21；三份数据内容哈希与EX010一致。原事件标签通过TXE原规则重新计算一致。
- 每个事件独立以10万元开始，T+1按原1%限价入场，T+h+1市价退出，单边0.1%费用，100份整手。1/2/3日共有425/424/423个已成交标签，另各7次未成交和2/3/4个右端缺失。标签彼此重叠，不是可以同时兑现的账户收益；下行标签包含入场当天可能早于实际成交的低点，只能视作保守几何。
- 费用敏感性在同样成交价和数量上再扣单边0.1%，不重新计算数量或账户。因此它不是正式0.2%压力验收。1–3日尺度与短期交易研究相容，但信号数量不等于闭合交易，仍须由完整账户核验60日频率标准。
- 499次10/20日移动块重采样、种子13；只重采样逐日预测损失，不重复拟合模型，区间未校正多重选择。两年、时间折、删除绝对标签最大的5个事件及旧账户持仓分层全部为诊断，不新增硬验收门槛。

## 六项主比较

表内百分比均为相对控制模型的预测误差改善率，正数较好；不是策略收益率。区间为20日块探索区间。

| 组件 / 期限 | 有效事件 | 收益改善 | 2025 / 2026收益改善 | 风险改善 | 2025 / 2026风险改善 | 收益区间 | 风险区间 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
"""
        + "\n".join(table)
        + """

## 盈亏机会与费用敏感性

高、中、低都是事件分组；排除低分组的“避开亏损/错失盈利”只是重叠标签金额占比。没有模拟删单、复利、资金冲突或实际账户回撤。

| 组件 / 期限 | 高/中/低事件数 | 高/低平均净标签 | 高分额外费用后标签 | 排除低组避开负金额 | 同时错失正金额 | 高组保留正金额 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
"""
        + "\n".join(opp)
        + """

afternoon_reversal高分1日平均标签只有0.110%，额外费用后变成-0.087%；2/3日分别只剩0.038%/0.065%。这解释了为何有预测信息也不必然有可兑现利润。高分2/3日平均净标签0.236%/0.263%，分别低于中间组0.296%/0.495%，不能按单调排序直接下注。

## 对照、反证和状态依赖

| 控制 | 组件 / 期限 | 收益改善 | 风险改善 | 研究分类 |
| --- | --- | ---: | ---: | --- |
"""
        + "\n".join(sensitivity)
        + """

- 去掉五个绝对标签最大的事件后，afternoon_reversal的1日风险改善仍为1.069%，3日收益仍为0.854%。结果不完全依赖这五个极端标签，但这不能排除其他选择偏差或行情阶段影响。
- S011在T收盘为空仓时，afternoon_reversal的2日收益预测改善为-0.062%，3日为0.363%；处于持仓时对应4.449%/2.670%，但只有46个事件。不能因此宣称在S011空仓时已找到稳定互补收益，也不能将旧账户状态当作因果对照。
- C0031处于持仓时，afternoon_reversal的1日风险预测变差0.565%，高低组收益差也轻微反转；处于空仓时风险改善2.028%。这主要支持入场前条件诊断，不能直接转用为已有仓位的止损、提前退出或减仓信号。当前阶段没有运行这类策略。
- 原36项中趋势、日内强势延续等正向假设未得到足够支持；反向关联另立本次后继试验，不将原失败改写为事前成功。已有卖压和振幅的作用不能重复包装为新发现。
- 供应商历史发布时钟、调整价历史可得性、成交量约束、入场日低点时序等原限制保留。全部窗口已见，2025/2026分层不是独立验证。本轮未读取新行情、外部指数或其他研究批次。

## 阶段二最终面板与停止依据

面板保留原12个定义和36项结果，追加18项后继检验。SUPPORTED只指报告说明的有限用途：afternoon_reversal的1日风险、2日风险及3日收益探索，相对日线控制P/PR各自获得有限支持；两套控制不是独立复制。afternoon在P/PR下未建立稳定独有职责，标为INEFFECTIVE；互相加入的PROther条件标为REDUNDANT。这些是研究判断，不改变策略验收标准，也不抹除有利数字。

停止继续组件搜索的理由是：主要增量缺口已完成直接对照；相近分钟指标表现互相替代；剩余关键不确定性来自交易状态、持仓占用、费用和收益/回撤联合权衡，继续同类分组不能代替完整策略检验。阶段二可以据此收口，而非为了扩大正面结果继续增加组件或移动窗口。

建议阶段三最多考虑以下三条可证伪方向，当前仅为提案：

1. 优先检验“日线机会信息＋一个分钟风险组件”的有限用途，保留日线单独对照，直接核对减少的亏损与错失的盈利；不把C0031预设为最终策略，也不把风险改善推断为持仓退出能力。
2. 次选检验2–3日持有尺度与分钟时序信息的匹配，特别核对中间组优于极端组、费用空间及同一资金占用；不把独立事件均值累计为账户回报。
3. 若阶段三有真实账户证据显示上述方向不能保留足够收益并降低回撤，应停止该输入集合内的重复搜索；是否扩展信息来源或窗口另提明确方案，不自动扩展。

完整目标继续以MANDATE/3为准：共同415日独立账户净收益严格高于0.9158029150000013、最大回撤幅度严格小于0.07248663749114126，且原434日默认收益、回撤、频率、32点扰动和费用压力全部通过。本轮没有新完整账户或候选，不能声明这些目标已经满足。旧C0031历史资格与冻结计划不变，当前选定候选为空；无平台、冻结、PTE或生产变更。

## 证据与验证

[完整结果](others/incremental_results.json)、[执行检查](others/final_checks.json)、[独立输出复核](others/independent_audit.json)及[协议](protocols/incremental_protocol.json)保留全部正负证据。5832行向前预测和54个分组计数已核对；独立复算净标签、预测损失、年度改善率通过，未来标签扰动不改变更早段预测，原账户归档哈希通过。执行源码与事前发布哈希相等，单进程、单原生线程，可重复结果一致。未执行仓库级全量回归或完整策略验收。

正式交付通过公共发布、装配及实验报告检查；验证回执单独保存于others/delivery_validation.json。装配校验仅证明交付与引用契约成立。阶段收口后另以公共研究概览核对登记状态、当前组件、报告、候选与未知计数，记录于others/overview_closeout.json。

Git仅保存协议、报告、代码、结果摘要与引用；完整明细和内容寻址证据须连同assets/runs/EX011_20261023/、assets/evidence/EX011_20261023/、assets/deliveries/COMPONENTS/5/及其历史依赖独立保留。下一步由用户决定是否进入阶段三。
"""
    )
    (HERE / "report.md").write_text(text, encoding="utf-8", newline="\n")
    return text


def publish():
    assert not (HERE / "others/delivery_validation.json").exists()
    assert read(HERE / "others/final_checks.json")["status"] == "PASS"
    assert read(HERE / "others/independent_audit.json")["status"] == "PASS"
    text = report()
    repo = RepositoryContext.discover(ROOT)
    refs = [EvidenceRef.from_dict(v) for v in read(HERE / "others/protocol_refs.json").values()]
    refs.extend(
        EvidenceRef.from_dict(v) for v in read(OLD / "others/published_refs.json")["references"]
    )
    for path in (
        HERE / "others/incremental_results.json",
        HERE / "others/input_facts.json",
        HERE / "others/final_checks.json",
        HERE / "others/independent_audit.json",
        HERE / "src/audit_study.py",
        HERE / "src/publish_closeout.py",
        WORK / "features_reconstructed.csv",
        WORK / "forward_predictions.csv",
    ):
        refs.append(material(path))
    refs = list(dict.fromkeys(refs))
    report_ref = publish_evidence(
        context(),
        ExperimentReportWrite(
            EX,
            sha256((HERE / "report.md").read_bytes()).hexdigest(),
            ExperimentOutcome.COMPLETED,
            tuple(refs),
        ),
    )
    refs.append(report_ref)
    save(HERE / "others/published_refs.json", {"references": [r.to_dict() for r in refs]})
    receipt = read(ROOT / "research/S015/deliveries/COMPONENTS/4/receipt.json")
    prior_path = ROOT / "research/S015/assets/deliveries/COMPONENTS/4/delivery.json"
    assert sha256(prior_path.read_bytes()).hexdigest() == next(
        v["sha256"] for v in receipt["files"] if v["path"] == "delivery.json"
    )
    old_payload = read(prior_path)["content"]["payload"]
    old_panel = d.ComponentPanel.from_dict(old_payload)
    protocol_ref = next(r for r in refs if r.experiment == EX and r.name == "incremental_protocol")
    results_ref = next(r for r in refs if r.experiment == EX and r.name == "incremental_results")
    entries = []
    for entry in old_panel.components:
        tests = list(entry.tests)
        for row in read(HERE / "others/incremental_results.json")["comparisons"]:
            if row["component"] != entry.component_id:
                continue
            status, explanation = judgment(row)
            tests.append(
                d.ComponentTestResult(
                    f"ex011-{row['component']}-{row['control']}-h{row['horizon']}",
                    EX.experiment_id,
                    protocol_ref,
                    d.ComponentTestStatus(status),
                    f"控制{row['control']}，{row['horizon']}日；{explanation}",
                    (results_ref,),
                )
            )
        if len(tests) > len(entry.tests):
            entries.append(
                replace(
                    entry,
                    control="EX010保留r1/r5/vol20；EX011分别用P、PR、PROther控制，见协议及逐项说明",
                    judgment="保留EX010正向失败；EX011反向残差为后继开发选择，有限用途及重复信息分别说明",
                    tests=tuple(tests),
                )
            )
        else:
            entries.append(entry)
    panel = d.ComponentPanel(
        tuple(entries),
        "阶段二已收口：保留12组件原36项并补18项控制比较；分钟时序仅有有限风险/收益用途，两个午后组件互相替代，完整策略双优尚未达成，等待用户决定阶段三。",
    )
    prior = d.DeliveryReference.from_dict(receipt["reference"])
    adapted = text.replace(
        "](others/", f"](../../../experiments/{EX.experiment_id}/others/"
    ).replace("](protocols/", f"](../../../experiments/{EX.experiment_id}/protocols/")
    assembled = assemble_delivery(
        repo,
        d.DeliveryDefinition(ResearchBatchRef("S015"), d.DeliveryStage.COMPONENTS, 5, (prior,)),
        d.DeliveryContent(
            panel, d.DeliveryStatus.COMPLETE, (), (), report=adapted, evidence=tuple(refs)
        ),
    )
    assert assembled.validation.status.value == "PASS", assembled.validation.issues
    checked = validate_experiment(
        repo, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION)
    )
    assert checked.status.value == "PASS", checked.issues
    save(
        HERE / "others/delivery_validation.json",
        {
            "delivery": assembled.receipt.reference.to_dict(),
            "assembly_validation": assembled.validation.to_dict(),
            "experiment_publication": checked.to_dict(),
        },
    )
    family = read(ROOT / "research/registrations/S015/family.json")
    intent = dict(family["research_intent"])
    intent.update(
        current_phase="新目标阶段二自主补证及收口完成，等待用户决定阶段三",
        current_components=assembled.receipt.reference.to_dict(),
        current_experiment=EX.to_dict(),
        selected_candidate=None,
        next_gate="用户决定是否进入阶段三；完整策略目标尚未达成，本轮未授权冻结、PTE或生产",
    )
    update_research_intent(
        repo,
        ResearchBatchRef("S015"),
        ResearchIntentUpdate(research_intent=intent),
        actor="RSCH",
        reason="用户授权自主完成阶段二；六项主比较和十二项控制敏感性补证完成，发布限制、反证及阶段收口判断。",
    )
    print(
        json.dumps(
            {
                "delivery": assembled.receipt.reference.to_dict(),
                "validation": assembled.validation.status.value,
                "report": checked.status.value,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def overview():
    observed = get_research_overview(RepositoryContext.discover(ROOT), ResearchBatchRef("S015"))
    value = observed.to_dict()
    # Keep the potentially large source inventory out of console output.
    save(ROOT / ".tmp/s015_ex011_overview_full.json", value)
    compact = {
        "batch": observed.batch.to_dict(),
        "snapshot_sha256": observed.snapshot.content_sha256,
        "observed_at": observed.snapshot.observed_at,
        "source_count": len(observed.snapshot.sources),
        "registered_state": observed.registered_state.value,
        "deliveries": [v.to_dict() for v in observed.deliveries],
        "experiments": [v.to_dict() for v in observed.experiments],
        "candidate_count": len(observed.candidates),
        "counts": [v.to_dict() for v in observed.counts],
        "limitations": [v.to_dict() for v in observed.limitations],
    }
    assert any(
        v.reference.stage == d.DeliveryStage.COMPONENTS and v.reference.revision == 5
        for v in observed.deliveries
    )
    assert (
        next(v for v in observed.experiments if v.experiment == EX).report_state.value
        == "PUBLISHED"
    )
    save(HERE / "others/overview_closeout.json", compact)
    ref = material(HERE / "others/overview_closeout.json")
    save(HERE / "others/overview_ref.json", ref.to_dict())
    print(
        json.dumps(
            {
                "snapshot": observed.snapshot.content_sha256,
                "candidate_count": len(observed.candidates),
                "current_report": "PUBLISHED",
                "current_components": 5,
                "limitations": len(observed.limitations),
                "counts": compact["counts"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("report", "publish", "overview"))
    args = parser.parse_args()
    {"report": report, "publish": publish, "overview": overview}[args.mode]()
