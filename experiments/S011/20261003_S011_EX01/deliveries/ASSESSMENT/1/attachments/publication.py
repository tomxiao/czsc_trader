from pathlib import Path
from hashlib import sha256
import json
from research_experiment import load_experiment_input
from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
import czsc_trader.research_tools as d

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def attach(path, name=None):
    media = "application/json" if path.suffix == ".json" else "application/octet-stream"
    return d.EvidenceFile(
        path.relative_to(REPO).as_posix(),
        d.EvidenceRef(
            "attachments/" + (name or path.name), sha256(path.read_bytes()).hexdigest(), media
        ),
    )


def closure(names):
    refs = {}

    def visit(name):
        if name in refs:
            return
        path = ROOT.parent / name / "artifacts"
        receipt = read(path / "execution_receipt.json")
        load_experiment_input(path, expected_receipt_sha256=receipt["receipt_sha256"])
        refs[name] = d.ExperimentEvidenceRef(
            name,
            path.relative_to(REPO).as_posix(),
            receipt["receipt_sha256"],
            d.ExperimentEvidenceUse.CURRENT_EVALUATION,
        )
        for prior in receipt["predecessor_receipts"]:
            visit(prior)

    for name in names:
        visit(name)
    return tuple(refs[name] for name in sorted(refs))


class Deliverable(d.ResearchDeliverable):
    def __init__(self, definition, content):
        self._definition, self.content = definition, content

    @property
    def definition(self):
        return self._definition

    def build(self):
        return self.content


def write_report(panel, comparison):
    family = read(ROOT / "artifacts/expanded_family_statistics.json")
    goals = read(ROOT / "artifacts/joint_goal_coverage.json")
    summaries = read(ROOT / "artifacts/all_summaries.json")
    coverage = read(ROOT / "artifacts/coverage_summary.json")
    metrics = {
        r.candidate.candidate_id: {x.metric.value: x.value for x in r.diagnostics}
        for r in panel.rows
    }
    ordered = sorted(
        comparison.rows, key=lambda r: (r.pareto_layer, r.rank_min, r.candidate.candidate_id)
    )
    selected = next(r for r in ordered if r.candidate.candidate_id == "S011-C0621")
    values = metrics[selected.candidate.candidate_id]
    stress = next(
        x for x in summaries if x["candidate_id"] == "S011-C0621" and x["scenario"] == "fee_20bp"
    )
    table = [
        "| 候选 | 层级 | 同层名次范围 | 净年化 | 最大回撤幅度 | 60日交易频率 | 邻域达标点 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in ordered:
        name = row.candidate.candidate_id
        v = metrics[name]
        table.append(
            f"| {name} | {row.pareto_layer} | {row.rank_min}—{row.rank_max} | {v['NET_ANNUAL_RETURN']:.2%} | {v['DRAWDOWN_MAGNITUDE']:.2%} | {v['FULL_SAMPLE_FREQUENCY']:.4f} | {goals[name]}/16 |"
        )
    pbo = "；".join(f"{x['block_count']}块：{x['pbo']:.2%}" for x in family["pbo"])
    dsr = [x for x in family["dsr"] if x["candidate_id"] == "S011-C0621"]
    dsr_text = "；".join(
        f"{x['raw_count']}次口径：{x['result']['raw']['probability']:.2%}" for x in dsr
    )
    first = "、".join(x.candidate.candidate_id for x in ordered if x.pareto_layer == 1)
    text = f"""# S011 当前契约阶段三、阶段四完整交付

状态：COMPLETE。阶段三36个中心、阶段四36中心的648个唯一账户坐标全部交付；五项自检、排序、不确定性与反证齐备。阶段五尚未执行，等待用户选择候选。

## 阶段三

[阶段三人工报告](../20261002_S011_EX59/deliveries/CANDIDATES/1/report.md)及[机器产物](../20261002_S011_EX59/deliveries/CANDIDATES/1/delivery.json)已按当前契约发布并通过公共校验。36中心保持原参数和内容哈希，当前标准账户全部满足原经济目标。6组历史搜索记录保留573条完成提议及3条失败提议，完整历史轨迹、未晋级项与反证作为历史材料保留。此次没有新增参数搜索。

## 阶段四覆盖及结论

612个标准账户包括36中心和576个邻域点；另有36个单边20bp压力账户。每中心16个原联合扰动点，五项自检分别为交易频率分布、联合参数敏感性、滚动超额收益、成本压力、利润集中度；同时交付bootstrap不确定性、研究族PBO/DSR、Pareto分层、同层名次和排序敏感性。所有声明诊断可用，覆盖缺口为零。

统一口径：159326.SZ，2025-02-06至2026-09-28共403交易日；100万元，lot_size=100，限价买入、市价卖出，标准单边10bp，显式限价BuyHold基准。原目标和排序规则保持不变，诊断没有增加硬门。

共有{coverage["layers"]}层，第一层为{first}。同层名次范围保留不可比与证据不确定性；下表只交接原36中心，扰动点不自动晋升候选。

{chr(10).join(table)}

C0621位于第{selected.pareto_layer}层，同层名次范围{selected.rank_min}—{selected.rank_max}；标准净年化{values["NET_ANNUAL_RETURN"]:.4%}、最大回撤幅度{values["DRAWDOWN_MAGNITUDE"]:.4%}，成本压力年化{stress["cagr"]:.4%}。其16个邻域点中{goals["S011-C0621"]}个满足全部原经济目标。这是需要用户知悉的局部敏感性证据，不改变原达标门槛。

C0137受原源码上限约束，lookback为110/120单侧设计，其余五轴对称；C0664保持3日持有，其余中心为2日。覆盖完整不意味着各中心可行域同构，也不代表全参数域稳健性。

## 搜索选择风险与证据边界

扩展研究族保留588次原可比提议、EX28的184次提议及512次原扩展提议，共1284次；保守1381口径另计96次错误预热提议和1次重复。错误收益排除，次数保留；本次复算不新增独立样本或搜索次数。

772份历史标准账户逐项核对原始哈希、日历、资金和整手、费用、订单类型与指标，配合512份扩展提议的当前复算形成统计输入。历史材料只作数值研究证据，平台不承诺旧数据机器复验，旧执行回执不作为当前认证。

去重后有{family["nonconstant_unique_paths"]}条非恒定收益路径。PBO（分块后训练赢家在验证部分落到后半区的比例）：{pbo}。相关结构有效试验数约{family["effective_trial_count"]:.4f}，这是相关性模型诊断，不是独立样本数。C0621的DSR（考虑多次尝试后修正的夏普证据指标）：{dsr_text}；有效次数口径为{dsr[0]["result"]["effective"]["probability"]:.2%}。不同计数口径并列披露，均不能解释为未来获利概率。

强类型FamilyReturnEvidence另交付612份当前标准账户构成的诊断子族；该子族包含重复经济行为，不替代完整搜索史。历史机制选择、反复观察同一开发池、复权数据历史发布时点未核实及局部扰动尺度限制继续存在。

## 技术失败和验证

初次邻域批次EX60—EX67中，EX60与EX66完成140账户；五组因并发登记锁冲突失败，EX61因Windows准备数据目录发布被拒绝失败。所有失败档案封存，失败组中的部分成功账户未混入正式面板。EX69由单进程完成560个候选登记或身份核验，随后EX70—EX77只读加载候选，用8进程完成其余420账户。未修改平台代码，未覆写失败实验。EX68汇总在读取历史空成交表时因数值dtype失败并封存，本后继显式转换数值类型，沿用原费用公式、容差和648账户。

交付保存于本实验deliveries/ASSESSMENT/1，公共校验结果见delivery_validation.json；逐点证据、执行回执、诊断和排名见artifacts目录与交付附件。封存后的实验不原地重跑。机器制品按仓库忽略规则在本地保存，不承诺Git包含全部大体积账本；未执行外部备份或推送。

## 阶段五交接

阶段三、四完整产物已就绪。结合本轮结果，建议由用户确认是否继续选择S011-C0621进入阶段五技术检验，并一并确认已知的邻域敏感性和选择历史限制。原用户选择作为历史背景保留，本轮未伪造新批准记录；无需因候选编号变化再次开展参数搜索。冻结及部署另需明确授权。
"""
    (ROOT / "COMPLETION_REPORT.md").write_text(text, encoding="utf-8", newline="\n")


def publish():
    import strategy_evaluator as se

    inputs = read(ROOT / "inputs.json")
    context = RepositoryContext.discover(REPO)
    mandate = d.DeliveryReceipt.from_dict(read(REPO / inputs["mandate_receipt"])).reference
    components = d.DeliveryReceipt.from_dict(read(REPO / inputs["component_receipt"])).reference
    candidates = d.DeliveryReceipt.from_dict(read(REPO / inputs["candidate_receipt"])).reference
    request = se.CandidateAssessmentRequest.from_dict(
        read(ROOT / "artifacts/assessment_request.json")
    )
    panel = se.AssessmentPanel.from_dict(read(ROOT / "artifacts/assessment_panel.json"))
    comparison_request = se.CandidateComparisonRequest.from_dict(
        read(ROOT / "artifacts/comparison_request.json")
    )
    comparison = se.CandidateComparison.from_dict(read(ROOT / "artifacts/comparison.json"))
    policy = read(ROOT / "evaluation_policy.json")
    write_report(panel, comparison)
    names = (
        "coverage_summary.json",
        "expanded_family_statistics.json",
        "joint_goal_coverage.json",
        "all_summaries.json",
        "derivation_map.json",
    )
    attachments = [attach(ROOT / "artifacts" / name) for name in names]
    attachments.extend(
        attach(ROOT / name)
        for name in (
            "inputs.json",
            "evaluation_policy.json",
            "neighborhood_protocol.json",
            "neighborhood_mapping.json",
            "centers_batch_result.json",
            "neighbors_batch_result.json",
            "recovery_batch_result.json",
            "02_design.md",
            "COMPLETION_REPORT.md",
            "family_statistics.py",
            "publication.py",
        )
    )
    attachments.append(attach(REPO / inputs["historical_audit"]))
    for number in (61, 62, 63, 64, 65, 67):
        source = ROOT.parent / f"20261002_S011_EX{number}"
        attachments.append(
            attach(source / "experiment_manifest.json", f"EX{number}_failure_manifest.json")
        )
        attachments.append(
            attach(source / "artifacts/technical_failure.txt", f"EX{number}_failure.txt")
        )
    source = ROOT.parent / "20261002_S011_EX68"
    attachments.append(attach(source / "experiment_manifest.json", "EX68_failure_manifest.json"))
    attachments.append(attach(source / "artifacts/technical_failure.txt", "EX68_failure.txt"))
    adverse = tuple(
        x.reference
        for x in attachments
        if x.reference.path.endswith(
            (
                "COMPLETION_REPORT.md",
                "expanded_family_statistics.json",
                "joint_goal_coverage.json",
                "neighbors_batch_result.json",
            )
        )
    )
    payload = d.CandidateAssessmentDelivery(
        candidates,
        mandate,
        request,
        panel,
        comparison_request,
        comparison,
        tuple(d.TargetMandateBinding.from_dict(x) for x in policy["target_bindings"]),
        policy["frequency_window_item_id"],
        policy["benchmark_mandate_item_id"],
        "阶段三与四完整就绪；建议用户结合36中心排序及C0621邻域敏感性，确认阶段五选择。无需新增搜索，当前不执行阶段五。",
        adverse,
        ("请确认是否选择S011-C0621进入阶段五技术检验；本次未新增用户批准或冻结记录。",),
    )
    content = d.DeliveryContent(
        payload,
        d.DeliveryStatus.COMPLETE,
        (),
        (
            d.Explanation(
                d.ExplanationKind.RESEARCH_JUDGMENT,
                "36中心648账户覆盖完整，所有自检、比较和不确定性可用。已见开发池、历史选择偏差、复权历史可得时点未核实及局部设计差异持续披露。",
                supporting=adverse,
            ),
        ),
        d.ReproductionSpec(
            "通过当前公共API validate_delivery核验；复算使用后继实验，不覆盖封存证据。",
            (),
            "原授权DFLS输入；历史数值由研究代码审计，不冒充当前运行认证。",
            "固定参数、协议、种子与源哈希；复算不新增独立样本。",
        ),
        (),
        tuple(attachments),
    )
    definition = d.DeliveryDefinition(
        d.ExperimentOwner("S011", ROOT.name),
        d.DeliveryStage.ASSESSMENT,
        1,
        (mandate, components, candidates),
        closure((ROOT.name,)),
    )
    receipt = assemble_delivery(context, Deliverable(definition, content))
    result = validate_delivery(context, receipt.reference)
    assert result.status is d.ValidationStatus.PASS, result
    write(ROOT / "assessment_receipt.json", receipt.to_dict())
    write(ROOT / "delivery_validation.json", result.to_dict())
    return receipt
