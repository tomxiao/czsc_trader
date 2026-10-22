"""Final stage-two synthesis after the richer daily-information falsification."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json

from daily_countercheck import ROOT, HERE, WORK, EX, OLD, read, save, material, context
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


def report():
    rows = read(HERE / "others/countercheck_results.json")["comparisons"]
    table, opportunities = [], []
    for r in rows:
        s = r["summary"]
        interval = r["gain_intervals"]["20"]["risk"]
        table.append(
            f"| {r['control']} | {r['component']} / {r['horizon']}日 | {pct(s['return_gain'])} | {pct(r['years']['2025']['return_gain'])} / {pct(r['years']['2026']['return_gain'])} | {pct(s['risk_gain'])} | {pct(r['years']['2025']['risk_gain'])} / {pct(r['years']['2026']['risk_gain'])} | [{pct(interval[0])}, {pct(interval[1])}] |"
        )
        if r["control"] == "AllDaily":
            hi, lo = s["group_1"], s["group_-1"]
            opportunities.append(
                f"| {r['component']} / {r['horizon']}日 | {hi['n']} / {s['group_0']['n']} / {lo['n']} | {pct(hi['mean_label'])} / {pct(lo['mean_label'])} | {pct(hi['mean_fee_sensitive_label'])} | {pct(lo['negative_amount_fraction'])} | {pct(lo['positive_amount_fraction'])} |"
            )
    text = (
        """# S015 阶段二最终收口：分钟增量依赖日线控制，未证实稳定新增价值

Status: COMPLETED

RSCH，2026-10-23。依据用户“请你自主完成阶段二”的授权，完成必要反证后收口。**阶段二任务已完成；未找到已证明稳定超越现有日线信息的新增分钟组件，S015完整策略的收益和回撤双优目标尚未达成。**

## 最终判断

保留日线卖压和近期振幅作为已有信息基础；分钟线指标保留为行情阶段相关的研究假设，暂不提升为已确认的新独立信息。以往局部支持记录原样保留，最新判断以本报告及COMPONENTS/6为准。

EX011控制了卖压与振幅，但没有控制“当日开盘到收盘涨跌”。午后及午后相对上午的变化，可能只是用分钟数据重新表达日线已经包含的开收盘变化。因此本次先直接加上body，再加入其余已研究的日线组件；该反证比继续寻找新的分钟阈值更能回答增量问题。

- **一日风险优势变得不稳。** afternoon_reversal（午后收益减上午收益）的风险预测误差改善从EX011的0.981%降至加入body后的0.314%；2025几乎为零（0.002%），四段有两段变差，20日块区间[-0.943%,1.992%]跨零。包含全部已有日线组件后为0.635%，区间[-0.279%,2.246%]仍跨零，同样有两段变差。不能继续把EX011的“四段均改善”当作对更强日线对照也成立的结论。
- **收益平均改善仍在，但依赖行情阶段。** 两种强控制下、两种分钟组件、三个期限共12项收益比较，均在2025变差、2026改善。以全部日线控制下的afternoon_reversal三日为例，总体改善1.103%，2025为-0.241%、2026为1.690%；前两段变差。其20日块区间[0.183%,2.013%]虽为正，也不能覆盖年度与时间段反证，更不是独立验证显著性。
- **不能宣称分钟完全无效或被日线完全解释。** 多项总体预测改善和正的分组差仍存在；本次没有证明信息等价。准确结论是：新增价值随控制、年度、账户状态变化，尚不足以把它作为稳定的新信息来源优先引入策略。
- **已有风险过滤也不是免费改善。** EX010振幅过滤避开40.29%的负标签金额，同时错失46.04%的正标签金额。当前全部日线控制下，afternoon_reversal两日排除低组对应避开54.58%负标签金额、错失37.89%正标签金额。指标必须放进真实账户权衡，不能从事件筛选直接推断收益增加和回撤减少。

## 研究链、数据与方法

[EX010](../EX010_20261023/report.md)完成12组件×3期限的36项初始比较；[EX011](../EX011_20261023/report.md)增加6项主比较和12项控制敏感性；本次EX012追加6项直接body反证和6项全部日线控制敏感性。合计66项成对条件，均保留正负结果，不能视为66份独立证据。最后12项在看到EX011结果后提出，先发布[反证协议](protocols/daily_countercheck.json)及执行源码，再计算；没有事后伪装成原始事前发现。

- PRBody：EX011的近1日/5日收益、20日波动、日线卖压、振幅，再加body=log(Close/Open)。
- AllDaily：PRBody再加20日趋势位置、收盘区间位置、下影、五日有向效率，覆盖EX010已有的全部8种日线定义；trend5与base_r5完全相同，只纳入一次。增加控制维度本身也改变岭回归的正则化行为，不作因果归因。
- 只读取已正式发布且哈希核对通过的EX011特征矩阵和EX010事件标签；没有新行情请求。原数据为509日日线含75日预热、434日3472根30分钟线，截止2026-10-21；现有供应商历史发布时钟与调整价可得性限制保留。
- 沿用原固定岭回归alpha=10、训练内标准化、4段向前检验及严格退出日剔除，分组为训练内负残差三分位，无参数或阈值搜索。每期限有效测试事件325/324/323个。本次3888行预测，单进程、单原生线程。
- 每个事件独立10万元，T17:30决策、T+1按收盘上方1%限价买、T+h+1市价卖，单边0.1%、100份整手；不同时承接重叠机会。原425/424/423个可成交标签、各7次买入未成交及2/3/4次右端缺失不变；无法知道精确成交后的低点，风险标签是含入场日的保守价格几何。
- 原收益/风险标签、控制增量、年度、四段、旧账户状态、删除五个最大绝对标签、10/20日块各499次重采样均保留。区间只重采样预测损失，不重新拟合，不校正开发选择及多重比较。年份一致性与区间是研究证据，不新增硬验收门槛。

## 完整反证结果

改善率=(控制均方误差−新增组件均方误差)/控制均方误差。正数预测较好；不是账户收益率，也不是最大回撤的变化。

| 控制 | 组件 / 期限 | 收益改善 | 2025 / 2026收益改善 | 风险改善 | 2025 / 2026风险改善 | 风险20日块区间 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
"""
        + "\n".join(table)
        + """

全部12项在“相对更强日线对照，获得稳定新增职责”的问题上分类为INEFFECTIVE，表示该用途未得到充分支持；没有否定表中的平均改善，也没有重写EX011的局部SUPPORTED。当前面板保留原定义及全部66项检验，更新两个分钟组件的综合判断。

## 盈亏机会和可兑现性

下表为AllDaily控制后的事件分组。额外费用指在原成交量和价格上再扣单边0.1%，并未重新计算数量或实际账户，不能替代正式费用压力验收。

| 组件 / 期限 | 高/中/低事件数 | 高/低平均净标签 | 高组额外费用后标签 | 排除低组避开负金额 | 同时错失正金额 |
| --- | ---: | ---: | ---: | ---: | ---: |
"""
        + "\n".join(opportunities)
        + """

高分只表示午后相对已知日线信息更弱，不是最终买入规则。虽然部分高组费用后平均标签仍为正，但标签重叠、资金被占用、不能同日卖出、未成交和真实退出都会改变可兑现结果。1–3日标签尺度与短期研究相容，不能据此声称60日闭合交易频率满足目标。分组随控制改变，本身也是模型依赖的证据。

EX011的账户分层反证继续有效：原C0031已持仓时，一日风险增量变差；S011空仓时，两日收益预测没有改善。这里没有运行减仓、删单或反事实账户，不将分层差异归因于某交易规则。

## 最终面板与下一步

阶段二保留的结论是：已有卖压存在短期反向关联，振幅提供风险状态信息，但过滤会牺牲收益；分钟特征有阶段性关联，尚未建立稳定超越已有日线信息的新职责。趋势与强势延续等原假设的负面结果仍保留。没有新增被确认的独立分钟信息，不等于现有全部信息不可能构造出更好的策略。

到此停止阶段二扩搜：核心竞争解释已有弱控制、强控制、互补消融和时序/状态反证；继续变更阈值或组件以追求正结果会加剧开发选择。余下问题是完整交易机制能否在机会损失、费用、资金占用及回撤之间取得可接受权衡，需要阶段三的可执行账户回答。

建议用户批准一个有界阶段三，而不是直接认可分钟信号：

1. 以已有日线机会和风险信息构建简单对照，研究真实入场、持仓与退出的职责，分别运行434日及415日独立账户；不预设沿用C0031，不修改S011固定基线。
2. 分钟信息最多作为一个备选增量对照，与日线对照同预算核对；不能将两个午后信号累计为独立来源，也不能以事件预测改善代替账户收益和回撤。
3. 若完整账户不能兼顾保留收益与减少损失，报告失败并受限停止；是否新增来源或扩大窗口另行提出明确方案，不自动扩展。

目标继续严格沿用MANDATE/3：共同415日账户净收益>0.9158029150000013且最大回撤幅度<0.07248663749114126，并同时通过原434日收益、回撤、频率、32点扰动及费用压力标准。本阶段没有新策略账户或候选，不能声称双优已经达成。阶段三尚未启动，当前选定候选为空；旧候选资格、历史冻结计划、PTE及生产均未变更。

## 验证、交付与保留

[聚焦检查](others/final_checks.json)通过输入引用哈希、发布源码身份、3888行唯一性、训练标签时间边界、预测损失独立复算、未来标签隔离及重复日线列检验；前序EX011另有5832行独立输出复核。没有仓库全量回归或完整策略验收。

经公共API发布COMPONENTS/6，保留COMPONENTS/5及其全部祖先；装配与REPORT_PUBLICATION结果见others/delivery_validation.json。公共研究概览的最终核对记录于others/overview_closeout.json；EX011阶段的读取因本次反证取代收口状态而中止，没有假报成功或回写旧报告。

Git保存报告、协议、脚本、结果及正式引用；assets/runs/EX012_20261023/、assets/evidence/EX012_20261023/、assets/deliveries/COMPONENTS/6/和其引用的EX010/EX011及更早资产需独立保留。下一步由用户决定是否进入阶段三。
"""
    )
    (HERE / "report.md").write_text(text, encoding="utf-8", newline="\n")
    return text


def publish():
    assert not (HERE / "others/delivery_validation.json").exists()
    assert read(HERE / "others/final_checks.json")["status"] == "PASS"
    text = report()
    refs = [EvidenceRef.from_dict(v) for v in read(HERE / "others/protocol_refs.json").values()]
    refs.extend(
        EvidenceRef.from_dict(v) for v in read(OLD / "others/published_refs.json")["references"]
    )
    for p in (
        HERE / "others/countercheck_results.json",
        HERE / "others/final_checks.json",
        HERE / "src/publish_final.py",
        WORK / "forward_predictions.csv",
    ):
        refs.append(material(p))
    refs = list(dict.fromkeys(refs))
    refs.append(
        publish_evidence(
            context(),
            ExperimentReportWrite(
                EX,
                sha256((HERE / "report.md").read_bytes()).hexdigest(),
                ExperimentOutcome.COMPLETED,
                tuple(refs),
            ),
        )
    )
    save(HERE / "others/published_refs.json", {"references": [v.to_dict() for v in refs]})
    receipt = read(ROOT / "research/S015/deliveries/COMPONENTS/5/receipt.json")
    prior_path = ROOT / "research/S015/assets/deliveries/COMPONENTS/5/delivery.json"
    assert sha256(prior_path.read_bytes()).hexdigest() == next(
        v["sha256"] for v in receipt["files"] if v["path"] == "delivery.json"
    )
    panel = d.ComponentPanel.from_dict(read(prior_path)["content"]["payload"])
    protocol = next(
        r
        for r in refs
        if r.experiment == EX
        and r.name == "daily_countercheck"
        and r.media_type == "application/json"
    )
    evidence = next(r for r in refs if r.experiment == EX and r.name == "countercheck_results")
    entries = []
    for entry in panel.components:
        tests = list(entry.tests)
        for r in read(HERE / "others/countercheck_results.json")["comparisons"]:
            if r["component"] == entry.component_id:
                tests.append(
                    d.ComponentTestResult(
                        f"ex012-{r['component']}-{r['control']}-h{r['horizon']}",
                        EX.experiment_id,
                        protocol,
                        d.ComponentTestStatus.INEFFECTIVE,
                        f"控制{r['control']}，{r['horizon']}日：总体有平均改善，但年度、时间段及区间证据未建立稳定新增职责；不等于信息完全无效。",
                        (evidence,),
                    )
                )
        if len(tests) > len(entry.tests):
            entry = replace(
                entry,
                tests=tuple(tests),
                control=entry.control + "；EX012增补PRBody及AllDaily",
                judgment="最新综合判断：更强日线控制下未证实稳定新增价值；EX011局部支持保留为历史条件性结果，分钟组件只作待验证假设。",
            )
        entries.append(entry)
    final_panel = d.ComponentPanel(
        tuple(entries),
        "阶段二最终完成：12组件/66条件；保留已有日线信息，未证实分钟组件稳定新增价值。双优策略目标尚未达成，建议有界阶段三，待用户决定。",
    )
    adapted = (
        text.replace("](others/", f"](../../../experiments/{EX.experiment_id}/others/")
        .replace("](protocols/", f"](../../../experiments/{EX.experiment_id}/protocols/")
        .replace("](../EX", "](../../../experiments/EX")
    )
    repo = RepositoryContext.discover(ROOT)
    assembled = assemble_delivery(
        repo,
        d.DeliveryDefinition(
            ResearchBatchRef("S015"),
            d.DeliveryStage.COMPONENTS,
            6,
            (d.DeliveryReference.from_dict(receipt["reference"]),),
        ),
        d.DeliveryContent(
            final_panel, d.DeliveryStatus.COMPLETE, (), (), report=adapted, evidence=tuple(refs)
        ),
    )
    assert assembled.validation.status.value == "PASS", assembled.validation.issues
    check = validate_experiment(
        repo, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION)
    )
    assert check.status.value == "PASS", check.issues
    save(
        HERE / "others/delivery_validation.json",
        {
            "delivery": assembled.receipt.reference.to_dict(),
            "assembly_validation": assembled.validation.to_dict(),
            "experiment_publication": check.to_dict(),
        },
    )
    intent = dict(read(ROOT / "research/registrations/S015/family.json")["research_intent"])
    intent.update(
        current_phase="新目标阶段二最终收口；分钟新增价值未证实，等待用户决定阶段三",
        current_components=assembled.receipt.reference.to_dict(),
        current_experiment=EX.to_dict(),
        selected_candidate=None,
        next_gate="用户决定有界阶段三；双优目标尚未达成，不自动增加数据、冻结或执行PTE/生产",
    )
    update_research_intent(
        repo,
        ResearchBatchRef("S015"),
        ResearchIntentUpdate(research_intent=intent),
        actor="RSCH",
        reason="自主完成阶段二：新增开收盘及全部日线控制反证，收紧分钟信息判断，保留全部历史结果并正式收口。",
    )
    print(
        json.dumps(
            {
                "delivery": assembled.receipt.reference.to_dict(),
                "validation": assembled.validation.status.value,
                "report": check.status.value,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def overview():
    observed = get_research_overview(RepositoryContext.discover(ROOT), ResearchBatchRef("S015"))
    save(ROOT / ".tmp/s015_ex012_overview_full.json", observed.to_dict())
    compact = {
        "status": "COMPLETED",
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
        v.reference.stage == d.DeliveryStage.COMPONENTS and v.reference.revision == 6
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
                "current_components": 6,
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
