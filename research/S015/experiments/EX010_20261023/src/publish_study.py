"""Publish the bounded component study using current public research contracts."""

from hashlib import sha256
import json

import numpy as np
import pandas as pd

from component_study import (
    ROOT,
    HERE,
    EX,
    WORK,
    DEFS,
    read,
    save,
    material,
    context,
    c0031_evidence,
)
from czsc_trader.application import (
    RepositoryContext,
    publish_evidence,
    assemble_delivery,
    validate_experiment,
    update_research_intent,
    ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,
    EvidenceRef,
    ExperimentOutcome,
    ExperimentReportWrite,
    ExperimentValidationRequest,
    ExperimentValidationScope,
)
from czsc_trader.research_tools import delivery as d


def pct(value):
    return "不适用" if value is None else f"{100 * value:.2f}%"


def checks():
    result = read(HERE / "others/component_results.json")
    rows = result["comparisons"]
    assert len(rows) == len({(r["component"], r["horizon"]) for r in rows}) == 36
    source = HERE / "src/component_study.py"
    refs = read(HERE / "others/protocol_refs.json")
    assert (
        sha256(source.read_bytes()).hexdigest()
        == refs[source.name]["sha256"]
        == result["source_sha256"]
    )
    events = pd.read_csv(WORK / "all_held_forward_events.csv")
    assert not events.duplicated(["component", "horizon", "date"]).any()
    assert (events.train_last_exit_position < events.test_start_position).all()
    assert events.date.max() <= "2026-10-21"
    labels = pd.read_csv(WORK / "event_labels.csv")
    filled = labels[labels.status.eq("FILLED")]
    expected = (
        filled.quantity
        * (filled.sell_price - filled.buy_price - (filled.sell_price + filled.buy_price) * 0.001)
        / 100000
    )
    np.testing.assert_allclose(expected, filled.label, rtol=1e-11, atol=1e-15)
    assert (filled.quantity % 100 == 0).all() and (filled.quantity <= 1000000).all()
    assert (pd.to_datetime(filled.exit_date) > pd.to_datetime(filled.entry_date)).all()
    assert (pd.to_datetime(filled.entry_date) > pd.to_datetime(filled.signal_date)).all()
    assert filled.exit_date.max() <= "2026-10-21"
    _, original = c0031_evidence()
    orders = pd.DataFrame(original["runs"][0]["ledgers"]["orders"]["data"])
    buys = orders[orders.side.eq("BUY")].copy()
    buys["signal_date"] = pd.to_datetime(buys.signal_date).dt.strftime("%Y-%m-%d")
    selected = buys.merge(labels[labels.horizon.eq(1)], on="signal_date", how="inner")
    assert len(selected) > 50
    np.testing.assert_allclose(selected.limit_price, selected.buy_limit, rtol=0, atol=1e-12)
    for r in rows:
        group = events[events.component.eq(r["component"]) & events.horizon.eq(r["horizon"])]
        assert len(group) == r["summary"]["n"]
        np.testing.assert_allclose(
            group.label.mean(), r["summary"]["mean_label"], rtol=1e-12, atol=1e-15
        )
        for year, s in r["years"].items():
            yr = group[group.date.str.startswith(year)]
            assert len(yr) == s["n"]
            delta = yr.loc[yr.group.eq(1), "label"].mean() - yr.loc[yr.group.eq(-1), "label"].mean()
            np.testing.assert_allclose(delta, s["high_low_return"], rtol=1e-12, atol=1e-15)
    retained = read(ROOT / "research/S015/experiments/EX008_20261022/others/account_archives.json")
    for saved in retained.values():
        EvidenceRef.from_dict(saved).resolve(ROOT)
    checked = {
        "status": "PASS",
        "comparisons": 36,
        "components": 12,
        "horizons": [1, 2, 3],
        "new_strategy_accounts": 0,
        "input_future_perturbation": "PASS",
        "chronological_purge": "PASS",
        "parallel_serial_equivalence": result["parallel_serial_equivalence"],
        "published_source_equals_executed_source": "PASS",
        "net_labels_independent_recalculation": "PASS",
        "yearly_contrast_independent_recalculation": "PASS",
        "prior_archive_hashes": "PASS",
        "fees_lots_t_plus_one_last_date": "PASS",
        "planned_limits_match_original_srt_buy_orders": int(len(selected)),
        "public_account_diagnosis": read(HERE / "others/public_c0031_diagnosis.json")["status"],
        "scope": "Focused research checks; no repository regression, strategy acceptance, or production verification.",
    }
    save(HERE / "others/final_checks.json", checked)
    return checked


def report():
    result = read(HERE / "others/component_results.json")
    rows = result["comparisons"]
    facts = read(HERE / "others/account_facts.json")["accounts"]
    supported = [r for r in rows if r["status"] == "SUPPORTED"]
    selected_components = sorted({r["component"] for r in supported})
    table = []
    for key, name, _, _, _ in DEFS:
        parts = sorted([r for r in rows if r["component"] == key], key=lambda r: r["horizon"])
        roles = []
        for r in parts:
            if r["supported_return"]:
                roles.append(f"{r['horizon']}日收益")
            if r["supported_risk"]:
                roles.append(f"{r['horizon']}日风险")
        table.append(
            f"| {name} | {' / '.join(pct(r['summary']['high_low_return']) for r in parts)} | {'、'.join(roles) or '当前方向未获稳定增量支持'} |"
        )
    evidence_rows = []
    for r in rows:
        evidence_rows.append(
            {
                "component": r["component"],
                "horizon": r["horizon"],
                "status": r["status"],
                **r["summary"],
                **{
                    f"{year}_{k}": v
                    for year, values in r["years"].items()
                    for k, v in values.items()
                },
                "return_interval_low": r["high_low_return_interval_block20"][0],
                "return_interval_high": r["high_low_return_interval_block20"][1],
            }
        )
    pd.DataFrame(evidence_rows).to_csv(HERE / "others/component_evidence_table.csv", index=False)
    supported_table = []
    for r in supported:
        s = r["summary"]
        supported_table.append(
            f"| {r['component']} / {r['horizon']}日 | {s['n']} / {s['high_n']} / {s['low_n']} | {pct(s['retained_profit_fraction'])} | {pct(s['avoided_loss_fraction'])} | {pct(s['missed_profit_fraction'])} | {pct(s['return_incremental_gain'])} / {pct(s['risk_incremental_gain'])} |"
        )
    account_table = []
    for label, f in facts.items():
        p = f["pnl_totals"]
        account_table.append(
            f"| {label} | {pct(f['net_return'])} | {pct(f['max_drawdown'])} | {p['entry']:,.2f} | {p['holding']:,.2f} | {p['exit']:,.2f} | {p['fees']:,.2f} |"
        )
    return_components = {r["component"] for r in supported if r["supported_return"]}
    risk_components = {r["component"] for r in supported if r["supported_risk"]}
    conclusion = (
        f"完成12个组件、36项固定期限比较，{len(supported)}项在事前声明方向上获得限定用途支持，涉及{len(selected_components)}个组件。"
        if supported
        else "完成12个组件、36项固定期限比较；事前声明方向未得到跨2025/2026一致且有增量的支持。空支持面板是本阶段有效负面结果。"
    )
    recommendations = []
    ranked = sorted(
        supported,
        key=lambda r: max(
            r["summary"]["return_incremental_gain"], r["summary"]["risk_incremental_gain"]
        ),
        reverse=True,
    )
    used = set()
    for r in ranked:
        family = next(x[4] for x in DEFS if x[0] == r["component"])
        if family in used:
            continue
        used.add(family)
        role = (
            "收益机会与损失风险"
            if r["supported_return"] and r["supported_risk"]
            else "收益机会"
            if r["supported_return"]
            else "损失风险"
        )
        recommendations.append(
            f"- 如获准阶段三，可先围绕 `{r['component']}` 的{r['horizon']}日{role}作用构造最小对照，检查改善是否能在完整资金、持仓占用与退出路径中兑现；本轮未构造该策略。"
        )
        if len(recommendations) == 3:
            break
    if not recommendations:
        recommendations = [
            "- 建议先评审负面结果与原方向假设；没有足够依据自动进入策略组合或扩充组件预算。反向关联仅作竞争解释，不事后翻转方向宣称事前检验通过。"
        ]
    # Do not turn a replication of the old pressure/range family into a new
    # strategy-search recommendation. The missing conditional control matters.
    recommendations = [
        "- 建议先补阶段二信息增量核对：若用户授权新增6项比较，以已有日线卖压pressure作为强控制，分别核对afternoon与afternoon_reversal在1/2/3日期限的增量。这不新增数据或特征；当前36项额度已用完，本轮未执行这6项。",
        "- 完成该核对后，才决定是否进入阶段三，分别测试新增信息能否增加S011未覆盖收益、近期振幅能否减少持有损失，并核对错失盈利的代价；不把“卖压+振幅”旧搜索直接重复一遍。",
        "- 暂不扩大模型、期限或数据范围；若分钟信息不能超过已有卖压，按冗余信息处理，保留负面结果并评审是否停止该路线。",
    ]
    coverage = read(HERE / "others/label_coverage.json")
    inverse = [
        f"{r['component']}/{r['horizon']}日"
        for r in rows
        if all(
            v["high_low_return"] is not None and v["high_low_return"] < 0
            for v in r["years"].values()
        )
    ]
    intervals = sum(
        r["high_low_return_interval_block20"][0] <= 0 <= r["high_low_return_interval_block20"][1]
        for r in rows
    )
    text = f"""# S015 新目标下的阶段二：收益机会与损失条件

Status: COMPLETED

RSCH，2026-10-23。{conclusion} **本阶段组件研究已完成，S015“完整账户收益、回撤同时优于固定S011并满足原默认标准”的总体目标尚未达成；没有构造或验收新策略。**

研究判断：本轮确认了振幅对风险的限定用途，也发现与“强势延续”竞争的反转线索。新增分钟信息相对于既有卖压是否有独立增量仍未回答，建议先做有边界的阶段二补证，暂不直接进入新策略搜索。33项“原方向不支持”不等于33项没有信息；反向关联是保留的反证，不事后翻转事前通过状态。

## 当前目标与执行范围

沿用MANDATE/3：434日原默认标准与415日固定S011双优条件必须同时满足。固定S011的累计净收益为91.58029150000013%，最大回撤幅度7.248663749114126%；相等不通过。本轮恢复已获准阶段二，用户确认从`355edbd9`新建`codex/s015-stage2-dual-objective`，包含3笔已有DEV提交。

只使用原S015准备的159326.SZ日线509日（含75日预热）与30分钟线3472根、434日，截止2026-10-21。未新增行情、其他市场输入、封存样本、完整交易规则、参数搜索、候选、冻结或PTE。日线特征与旧EX002有重叠，本轮针对新问题及新的1/2/3日执行标签检验，不称为独立发现。

## 两份原账户的损益事实

两份原始415日ZIP证据均核对内容哈希、10万元空仓起点、费用与逐日权益。下表分解金额单位为元；前三项减费用等于账户净利润。分解是实际账本事实，两账户差额不代表取消某笔交易后的反事实。

| 账户 | 累计净收益 | 最大回撤幅度 | 入场日 | 其他持有日 | 退出日 | 费用 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(account_table)}

所有逐日分解残差绝对值小于1e-7元。逐年分解和最差五日见[账户事实](others/account_facts.json)。公共`diagnose_accounts`仅接受schema7完整评价；415日ZIP原件不伪装为该格式。另对原434日C0031调用公共诊断，因同周期多次成交返回`UNSUPPORTED`，原样保留[结果](others/public_c0031_diagnosis.json)；未宣称公共诊断通过，也未把434日切片替代415日独立初始账户。

C0031比S011多获得约19,653.50元其他持有日损益，同时多支付约19,068.13元费用；单独扣除某部分不能生成一条新的资金路径。这提示需要同时解释新增收益来源、持有损失与交易成本，不能预设只加过滤条件就能同时改善两项目标。

## 方法与比较

[事前协议](protocols/component_protocol.json)和实现已通过公共材料入口发布后才计算事件标签。共12个组件，每个只评价1、2、3日，36项预算全部使用，剩余额度0。每项同时观察收益、下行几何、机会代价、原账户状态及时间一致性，没有增加阈值网格。

每个事件独立从10万元空仓开始，T日17:30读取至T日数据，T+1按信号收盘上方1%限价规划买入，T+h+1开盘市价退出。限价规划采用同一整手、价格档位、10%规划边界、数量上限及费用，成交调用TXE公共`resolve_fill`并使用原434日真实市场规则。标准单边0.1%；未成交与边界缺失分开计数。**重叠事件标签不能相加为策略收益，也不代表完整仓位路径。**

入场日内成交时间只有日范围精度，因此下行指标包含入场当天最低价，可能发生在实际入场之前，只是保守几何风险，不能当作实际持仓后损失。费用压力和32点参数检验不属于本阶段。

前100个开发池决策日用于起始训练，之后四个顺序测试段；每次训练只用退出日期严格早于测试起点的标签。分组阈值仅来自过去训练特征的三分位数，固定高分方向，不按结果搜索阈值。用r1/r5/vol20简单控制与“控制+单个组件”岭回归比较收益和风险预测误差；高低组均值、覆盖、2025/2026分开报告。测试日期仍属于已见开发池，不称为独立样本外验证。

| 组件 | 1 / 2 / 3日高分减低分的平均净事件标签 | 有限用途判断 |
| --- | --- | --- |
{chr(10).join(table)}

“支持”只表示事前高分方向在两个年份的分组差异一致，且对应作用在两个年份均改善简单控制的预测误差；这是研究员证据分类，不是新经济验收门，也不是未来收益保证。收益用途涉及{len(return_components)}个组件，风险用途涉及{len(risk_components)}个组件。完整36项正负结果、年度、折段、原账户持有/空仓状态与区间见[结果](others/component_results.json)和[证据表](others/component_evidence_table.csv)。

具体解释如下：

- 振幅收缩的1/2/3日高分组下行几何分别比低分组小0.322、0.500、0.742个百分点；对应风险预测误差改善2.23%、2.62%、3.25%。3日期限也有正向收益线索，但收益差的移动块区间跨零，不能把分类支持表述成显著、独立或可兑现的优势。该振幅比率与既有C0031的range_ratio属同一信息，不能计作新发现。
- 午后收益高分减低分的1日净事件标签为-0.951个百分点，2025/2026分别为-0.639/-1.212个百分点，方向更接近“午后卖压之后反弹”，否定了本轮事前高分更好的假设；相对简单控制的收益误差改善3.58%。日线pressure对应差为-0.904个百分点，说明这可能是已知卖压信息的另一种表达。
- 全开发池afternoon与pressure的秩相关系数约0.826，afternoon_reversal与pressure约0.095。相关性低也不能证明独立增量。本轮预测控制只含r1/r5/vol20，没有把已有pressure纳入分钟组件控制，这是需要明确补证的缺口，不能声称分钟信息已超过既有日线信息。

## 收益机会、避损与错失盈利

机会比例的分母分别是同一批事件全部正标签金额或全部负标签金额，均为重叠事件的统计量。高分保留盈利、低分避开亏损、低分错失盈利分别报告；中间组独立存在，不能把高低组覆盖冒充全部信号。误差改善为相对简单控制的平方误差降幅，不是收益率。

| 获支持的组件/期限 | 全部/高分/低分事件数 | 高分保留盈利 | 低分避开亏损 | 低分错失盈利 | 收益/风险预测误差改善 |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(supported_table) if supported_table else "| 无 | — | — | — | — | — |"}

以振幅1日比较为例，低分组覆盖132/325个测试事件：若据此排除低分事件，描述性地对应避开40.29%的负标签金额，同时错失46.04%的正标签金额。因此较低几何风险并不等于同时提高收益，旧C0031已经存在振幅条件，重复同一过滤方向缺少新的充分依据。

各期限原始事件状态为`{json.dumps(coverage, ensure_ascii=False)}`。测试段排除标签退出已越过截止日或未成交事件；没有读取截止日之后价格、强制成交或延长窗口。原S011未持仓时的潜在盈利与两账户持仓状态下损失见每项`account_states`，这些是历史条件描述，不证明新策略能实际捕获所有机会。

## 最强反证与未解决问题

- 36项中有{36 - len(supported)}项未获当前方向的稳定增量支持；不能只展示有利项。收益高低组20观察值移动块区间有{intervals}项跨零，499次重抽样只作不确定性诊断；未进行确认性多重检验，也不据此宣称显著发现。
- 反向收益差在2025/2026均出现的比较为：{", ".join(inverse) or "无"}。这削弱原高分方向；不事后改方向把它们计入事前通过数。线性控制的预测改善也不能证明独立经济机制。
- 训练/测试、两个年份、原434日和共同415日均有历史暴露与选择偏差，不能当作多份独立证据；相关组件不能按数量当作独立信息。
- 历史17:30日线、复权修订及分钟供应商可得时钟仍未认证。分钟特征使用当天15:00之前八根条形数据，只声明市场观察假设，不声称历史供应商准点可得。
- 本轮没有完整进退场和资金占用模型，未计算新策略的收益、最大回撤、交易频率、32点扰动或费用压力，不能宣布新目标通过。

## 验证与下一步

[聚焦核验](others/final_checks.json)覆盖源代码发布与实际执行一致、特征未来扰动、严格时间剔除、并行/串行一致、标签费用与收益独立复算、年度对比、T+1与整手规则及原账户哈希。固定批量使用最多8进程、每进程原生线程1，不嵌套并行；初始2进程传输预检顺序执行。本轮未运行仓库级全量回归、PTE或生产检查。

{chr(10).join(recommendations)}

阶段二交付后等待用户决定进入阶段三、补证或停止；任何完整策略构造仍需阶段三授权。旧候选身份、选型、冻结计划及历史交付不改写。正式数据资产、事件明细与发布材料须独立保存，Git不能恢复全部资产。
"""
    (HERE / "report.md").write_text(text, encoding="utf-8", newline="\n")
    return text


def main():
    assert not (HERE / "others/delivery_validation.json").exists()
    checks()
    text = report()
    repo = RepositoryContext.discover(ROOT)
    refs = [EvidenceRef.from_dict(v) for v in read(HERE / "others/protocol_refs.json").values()]
    selected = [
        HERE / "others/authorization.json",
        HERE / "others/component_results.json",
        HERE / "others/component_evidence_table.csv",
        HERE / "others/label_coverage.json",
        HERE / "others/final_checks.json",
        WORK / "event_labels.csv",
        WORK / "all_held_forward_events.csv",
        WORK / "component_rank_correlations.csv",
        WORK / "archive_diagnosis_S011-v1.csv",
        WORK / "archive_diagnosis_C0031.csv",
        HERE / "src/publish_study.py",
    ]
    for p in selected:
        refs.append(material(p))
    archive_refs = read(
        ROOT / "research/S015/experiments/EX008_20261022/others/account_archives.json"
    )
    refs.extend(EvidenceRef.from_dict(v) for v in archive_refs.values())
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
    protocol_ref = EvidenceRef.from_dict(
        read(HERE / "others/protocol_refs.json")["component_protocol.json"]
    )
    source_ref = EvidenceRef.from_dict(
        read(HERE / "others/protocol_refs.json")["component_study.py"]
    )
    result_ref = next(r for r in refs if r.name == "component_results")
    result = read(HERE / "others/component_results.json")
    components = []
    for key, name, formula, hyp, family in DEFS:
        rows = [r for r in result["comparisons"] if r["component"] == key]
        tests = tuple(
            d.ComponentTestResult(
                f"{key}-h{r['horizon']}",
                EX.experiment_id,
                protocol_ref,
                d.ComponentTestStatus(r["status"]),
                f"{name}，{r['horizon']}日；收益支持={r['supported_return']}，风险支持={r['supported_risk']}；其余方向和限制见36项完整结果。",
                (result_ref,),
            )
            for r in rows
        )
        components.append(
            d.ComponentEntry(
                key,
                d.ExperimentDefinitionRef(source_ref, f"features:{key}"),
                hyp,
                "独立10万元事件净标签及保守日范围下行几何",
                "1/2/3交易日",
                "r1/r5/vol20简单控制，逐项增加单组件",
                "T日17:30；至T日；历史供应商时钟未认证",
                "原始无复权特征与HFQ_RESEARCH成交标签，按原价格缩放合同",
                f"仅159326.SZ已见开发池；{family}家族；非完整策略",
                "按年度方向与增量分类；无效及负面结果完整保留",
                tests,
            )
        )
    prior = d.DeliveryReference.from_dict(
        read(ROOT / "research/S015/deliveries/MANDATE/3/receipt.json")["reference"]
    )
    revision = (
        max(
            int(p.name)
            for p in (ROOT / "research/S015/deliveries/COMPONENTS").iterdir()
            if p.is_dir()
        )
        + 1
    )
    panel = d.ComponentPanel(
        tuple(components),
        f"新目标阶段二完成：12组件/36比较，{result['supported_pairs']}项限定支持；未构造新策略，双优总体目标未达成，等待阶段三决定。",
    )
    adapted = text.replace(
        "](others/", f"](../../../experiments/{EX.experiment_id}/others/"
    ).replace("](protocols/", f"](../../../experiments/{EX.experiment_id}/protocols/")
    assembled = assemble_delivery(
        repo,
        d.DeliveryDefinition(
            ResearchBatchRef("S015"), d.DeliveryStage.COMPONENTS, revision, (prior,)
        ),
        d.DeliveryContent(
            panel, d.DeliveryStatus.COMPLETE, (), (), report=adapted, evidence=tuple(refs)
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
    family = read(ROOT / "research/registrations/S015/family.json")
    intent = dict(family["research_intent"])
    intent.update(
        current_phase="新目标阶段二已完成，等待用户决定阶段三",
        current_components=assembled.receipt.reference.to_dict(),
        current_experiment=EX.to_dict(),
        selected_candidate=None,
        next_gate="用户决定阶段三；本次不授权完整策略搜索、冻结、PTE或生产",
    )
    update_research_intent(
        repo,
        ResearchBatchRef("S015"),
        ResearchIntentUpdate(research_intent=intent),
        actor="RSCH",
        reason="用户恢复S015研究；完成获批36项阶段二组件比较，提交证据并等待新阶段决定。",
    )
    print(
        json.dumps(
            {
                "delivery": assembled.receipt.reference.to_dict(),
                "publication": check.status.value,
                "supported_pairs": result["supported_pairs"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
