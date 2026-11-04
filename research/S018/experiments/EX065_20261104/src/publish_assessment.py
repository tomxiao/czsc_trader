"""Finish the authorized C9380 delivery using retained computations after DEV repair."""
# ruff: noqa: E402 -- establish workspace cache paths before importing platform modules.
from pathlib import Path
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'research/RSCH_AGENT.md').is_file())
SCRATCH = ROOT / '.tmp/s018-c9380-stage4-publication'
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / 'pycache')
os.environ['TMP'] = os.environ['TEMP'] = str(SCRATCH)

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from time import perf_counter

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    publish_evidence, assemble_delivery, validate_delivery, validate_experiment)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from strategy_evaluator import CandidatePerformanceAssessmentRequest, compare_candidates
from strategy_evaluator import research_models as m

EXP = d.ExperimentRef('S018', 'EX065_20261104')
WORK = EXP.resolve(ROOT)
OUT = WORK / 'others/delivery_01'
BATCH = d.ResearchBatchRef('S018')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def setup():
    repo = RepositoryContext.discover(ROOT)
    center = load_candidate(repo, CandidateKey('S018', 'C9380'))
    assert center.content_identity.content_sha256 == '186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a'
    context = create_research_context(repo, BATCH, providers=ProviderConfig(bindings={}, equity_bindings={}),
                                     execution_spec=center.definition.execution_spec)
    return repo, center, context


def retained():
    ref = d.EvidenceRef.from_dict(read(WORK / 'others/retained_request_ref.json'))
    request = CandidatePerformanceAssessmentRequest.from_dict(read(ref.resolve(ROOT)))
    panel = m.AssessmentPanel.from_dict(read(WORK / 'others/panel.json'))
    protocol = read(WORK / 'others/protocol.json')
    assert request.sha256 == panel.request_sha256
    return ref, request, panel, protocol


def prepare():
    assert not OUT.exists(), 'Inspect existing publication work before resuming.'
    begun = perf_counter()
    repo, center, context = setup()
    ref, request, panel, protocol = retained()
    previous_ref = d.EvidenceRef.from_dict(read(WORK / 'report_ref.json')['report'])
    previous = read(previous_ref.resolve(ROOT))
    assert sha256(previous['report'].encode()).hexdigest() == previous['report_sha256']
    verification = read(WORK / 'others/rsch_verification.json')
    assert sha256((WORK / 'others/panel.json').read_bytes()).hexdigest() == verification['source_hashes']['panel.json']
    design, = request.baseline_request.parameter_designs
    plan_ref = d.EvidenceRef.from_dict(protocol['parameter_plan_ref'])
    plan = d.ParameterEvaluationPlan.from_dict(read(plan_ref.resolve(ROOT)))
    assert design == plan.design and len(design.space.axes) == 13 and design.point_count == 79
    assert not panel.rows[0].coverage_gaps and len(protocol['targets']['requirements']) == 10
    contract = m.DeclaredPointSetComparisonContract(design.construction_sha256,
        m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05),
            (m.ZeroCenterAbsoluteLimit('add_sector_margin', m.AbsoluteChangeLimit(.0005)),)))
    comparison_request = m.CalmarComparisonRequest(request.baseline_request.centers,
        m.ResearchTargets.from_dict(protocol['targets']), panel,
        m.ComparisonPolicy.from_dict(protocol['policy']), (design,), contract)
    comparison = compare_candidates(comparison_request)
    row, = comparison.rows
    assert row.acceptance_status.value == 'PASSED'
    check = next(x for x in row.target_checks if isinstance(x, m.DeclaredParameterPointSetCheck))
    assert (check.required_points, check.valid_points, check.minimum_joint_passes, check.joint_passes) == (79, 79, 65, 79)
    assert all(x.drawdown <= .25 for x in panel.rows[0].parameter_performances)
    save(OUT / 'previous_report_ref.json', previous_ref.to_dict())
    save(OUT / 'comparison_request.json', comparison_request.to_dict())
    save(OUT / 'comparison.json', comparison.to_dict())
    save(OUT / 'reuse_review.json', {
        'review_date': '2026-11-05', 'role': 'RSCH', 'platform_fix_commit': '848672200',
        'authorization': '切换RSCH，并继续', 'scope': ['S018-C9380'],
        'source_request': ref.to_dict(), 'request_sha256': request.sha256,
        'panel_sha256': verification['source_hashes']['panel.json'],
        'source_plan': plan_ref.to_dict(), 'design_unchanged': True,
        'reused_strategy_accounts': 81, 'reused_shared_buyhold_accounts': 2,
        'new_account_replays': 0, 'new_search_points': 0, 'assessment_recalculations': 0,
        'bootstrap_recalculations': 0, 'comparison_calculations': 1,
        'reason': 'DEV changed only comparison axis admissibility and semantic signatures. Original source, parameters, data, execution and assessment calculations are retained with their original identities. No old manifest is resumed under new engine identity.',
        'candidate_acceptance': row.acceptance_status.value,
        'comparison_status': row.status.value, 'declared_points': 79,
        'minimum_joint_passes': 65, 'joint_passes': 79,
        'all_points_drawdown_limit_passed': True,
        'unassessed_other_candidates': 492, 'stage5_authorized': False,
        'family_diagnostics': [x.to_dict() for x in panel.family_diagnostics],
        'prepare_seconds': perf_counter() - begun,
    })
    old = previous['report']
    body_start = old.index('## 目标与既有自检')
    body_end = old.index('## 接口阻断及研究建议')
    report = '''# EX065：C9380 阶段四自检完成并形成正式交付

2026-11-05续办：用户批准DEV修复后明确“切换RSCH，并继续”。复用EX064的81个策略账户、2份共享买持及EX065已保存面板和统计分析，本次仅计算正式比较并发布交付，新增账户、搜索点及bootstrap重算均为0。

C9380通过用户确认的全部适用数值硬门，五项自检研究工作完成；跨时期优势不稳定，选择偏差及独立验证缺口仍存在。正式交付为ASSESSMENT/1（schema 15），直接引用CANDIDATES/3，按用户明确选择仅评估C9380。原493个候选及其历史资格保持不变，其余492个候选未在本次阶段四评估。单候选比较不构成全研究族最优结论。

'''+old[body_start:body_end]+'''## 正式比较、复用依据与研究建议

DEV提交848672200使Calmar比较合同支持合法整数及固定分类轴，连续参数尺度不变。RSCH核对保留请求与面板哈希、13轴设计及原点绑定一致，沿用原79点、净卡玛目标和全部10项目标声明；未改变C9380定义、原账户、计算口径或历史证据。原接口阻断和原报告作为历史证据保留，本次另发报告修订与正式交付。

正式比较所有适用硬条件通过，79个有效邻点中79个联合通过，最低要求65个；全点绝对回撤门通过。未适用的压力买持零回撤条件保留其分支状态。交付完整性以INTEGRITY核验；该核验不等于重算全部历史账户或独立验证。数值核对沿用EX065已有RSCH核对，并验证本次比较与原门槛一致。

紧凑输入未提供内嵌研究族收益矩阵，SE族诊断仍为FAMILY_RETURN_MATRIX_NOT_SUPPLIED；完整族统计以独立公开接口所得证据附入，不手工填充面板。五项自检的研究报告已覆盖此项，内嵌字段缺口不应误称统计未做或诊断通过。

参数结论仅覆盖获批79点，不能外推为4373点完整笛卡尔邻域通过。8个单轴点没有改变交易经济行为，不能视为独立成功。entry_days、earliest_add、review_after、max_hold因最小整数变化超过5%而固定，add_mode类别保持固定；这些选择风险仍未被局部扰动检验。历史HFQ可得性假设、全部结果来自已反复使用开发池及短周期时序风险继续保留。

建议保持C9380参数，将其作为数值达标、仍需独立观察的候选，请用户决定是否进入阶段五技术检验；不建议继续在同一开发池微调以追求更好统计结果。阶段五仅检验候选与冻结包行为等价及隔离PTE链路可运行性，不会证明经济优势；冻结、部署及生产操作仍须另行批准。

本次阶段四目标已达成，不自动进入阶段五。[复用核对](others/delivery_01/reuse_review.json) · [正式比较](others/delivery_01/comparison.json) · [原SE面板](others/panel.json) · [原RSCH数值核对](others/rsch_verification.json) · [历史接口缺口](../../materials/c9380_stage4_completion/dev_request.md)。
'''
    (OUT / 'report_draft.md').write_text(report, encoding='utf-8')
    print('PREPARED', row.acceptance_status.value, row.status.value, flush=True)


def publish():
    begun = perf_counter()
    repo, center, context = setup()
    ref, request, panel, protocol = retained()
    review = read(OUT / 'reuse_review.json')
    assert review['request_sha256'] == request.sha256
    comparison_request = m.CalmarComparisonRequest.from_dict(read(OUT / 'comparison_request.json'))
    comparison = m.CandidateComparison.from_dict(read(OUT / 'comparison.json'))
    assert comparison_request.panel == panel
    previous_ref = d.EvidenceRef.from_dict(read(OUT / 'previous_report_ref.json'))
    previous = read(previous_ref.resolve(ROOT))
    refs = [d.EvidenceRef.from_dict(x) for x in previous['evidence']]
    selected_evidence = tuple(x for x in refs if x.name in {
        'material-time_analysis', 'material-time_summary', 'material-family_statistics',
        'material-family_matrix_manifest', 'material-family_inventory', 'material-family_current_center_check',
        'others-rsch_verification', 'others-protocol', 'others-panel'})
    def material(path, name):
        mime = {'.json': 'application/json', '.py': 'text/x-python', '.md': 'text/markdown'}[path.suffix]
        return publish_evidence(context, d.MaterialEvidenceWrite(EXP, name, path.read_bytes(), mime, path.suffix[1:]))
    own_refs = tuple(material(path, 'delivery01-' + path.stem) for path in (
        OUT / 'reuse_review.json', OUT / 'comparison_request.json', OUT / 'comparison.json', Path(__file__)))
    source_folder = ROOT / 'research/S018/assets/deliveries/CANDIDATES/3'
    source_receipt = d.DeliveryReceipt.from_dict(read(source_folder / 'receipt.json'))
    source = d.CandidateSet.from_dict(read(source_folder / 'delivery.json')['content']['payload'])
    selected, = tuple(x for x in source.candidates if x.identity.key == center.key)
    assert selected.identity.content_sha256 == center.content_identity.content_sha256
    mandate = d.DeliveryReference.from_dict(read(WORK / 'others/mandate_reference.json'))
    plan_ref = d.EvidenceRef.from_dict(protocol['parameter_plan_ref'])
    account_refs = tuple(d.EvidenceRef.from_dict(x) for x in read(WORK / 'others/account_references.json'))
    assert len(account_refs) == 81
    payload = d.CandidateAssessmentDelivery(source_receipt.reference, mandate, request, panel,
        comparison_request, comparison,
        tuple(d.TargetMandateBinding(x.target_id, 'targets') for x in comparison_request.targets.requirements),
        'frequency_days', 'benchmark',
        'C9380通过既定数值硬门，建议保持参数并由用户决定阶段五技术检验；时间稳定性与独立验证不足仍需披露，不建议同池微调。',
        selected_evidence, ('请用户决定是否选择C9380进入阶段五技术检验；本交付不授权冻结、部署或生产。',),
        parameter_plans=(plan_ref,))
    report = (OUT / 'report_draft.md').read_text(encoding='utf-8')
    stage_report = report.replace('# EX065：', '# C9380阶段四交付：', 1)
    stage_report = stage_report.replace('(../../materials/', '(../../../materials/')
    stage_report = stage_report.replace('(others/', '(../../../experiments/EX065_20261104/others/')
    evidence = tuple(dict.fromkeys((ref, previous_ref, *own_refs, *selected_evidence, *account_refs)))
    assembled = assemble_delivery(repo, d.DeliveryDefinition(BATCH, d.DeliveryStage.ASSESSMENT, 1,
        predecessors=(source_receipt.reference, mandate), schema_version=15),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=stage_report, evidence=evidence))
    assert assembled.validation.status is d.ValidationStatus.PASS
    checked = validate_delivery(repo, assembled.receipt.reference)
    assert checked.status is d.ValidationStatus.PASS and checked.scope is d.DeliveryValidationScope.INTEGRITY
    assert checked.stats.accounts_authenticated == 0 and checked.stats.recomputation_seconds == 0
    save(OUT / 'assessment_receipt.json', assembled.receipt.to_dict())
    save(OUT / 'delivery_validation.json', checked.to_dict())
    (WORK / 'report.md').write_text(report, encoding='utf-8')
    delivery_refs = tuple(material(path, 'delivery01-' + path.stem) for path in (
        OUT / 'assessment_receipt.json', OUT / 'delivery_validation.json'))
    report_ref = publish_evidence(context, d.ExperimentReportWrite(EXP,
        sha256((WORK / 'report.md').read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED,
        tuple(dict.fromkeys((*evidence, plan_ref, *delivery_refs))), previous_ref))
    artifacts = tuple(d.ExperimentArtifactRef(EXP, path.relative_to(WORK).as_posix(), sha256(path.read_bytes()).hexdigest())
                      for path in (*OUT.glob('*.json'), Path(__file__)))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(EXP,
        d.ExperimentValidationScope.REPORT_PUBLICATION, artifacts))
    assert validation.status.value == 'PASS', validation.issues
    save(OUT / 'publication_result.json', {'report': report_ref.to_dict(),
        'assessment': assembled.receipt.reference.to_dict(), 'candidates': source_receipt.reference.to_dict(),
        'report_validation': asdict(validation), 'delivery_validation': checked.to_dict(),
        'new_account_replays': 0, 'new_search_points': 0, 'publication_seconds': perf_counter() - begun})
    print('PUBLISHED', assembled.receipt.reference.content_sha256, 'INTEGRITY', checked.status.value,
          'REPORT', report_ref.sha256, validation.status.value, flush=True)


def finish_report():
    """Resume only report publication after observing an intact stage delivery."""
    begun = perf_counter()
    repo, _, context = setup()
    receipt = d.DeliveryReceipt.from_dict(read(OUT / 'assessment_receipt.json'))
    checked = validate_delivery(repo, receipt.reference)
    assert checked.status is d.ValidationStatus.PASS
    previous_ref = d.EvidenceRef.from_dict(read(OUT / 'previous_report_ref.json'))
    assert d.EvidenceRef.from_dict(read(WORK / 'report_ref.json')['report']) == previous_ref
    document = read(ROOT / 'research/S018/assets/deliveries/ASSESSMENT/1/delivery.json')
    refs = [d.EvidenceRef.from_dict(x) for x in document['content']['evidence']]
    refs.append(d.EvidenceRef.from_dict(document['content']['payload']['parameter_plans'][0]))
    save(OUT / 'report_recovery.json', {
        'observed_phase': 'REPORT_PREPARE', 'reason': 'Explicit previous report reference required',
        'previous_pointer_unchanged': True, 'assessment_integrity': checked.to_dict(),
        'action': 'Publish report successor only; do not repeat assessment publication or calculations',
    })
    for path in (OUT / 'assessment_receipt.json', OUT / 'delivery_validation.json',
                 OUT / 'report_recovery.json', Path(__file__)):
        mime = 'text/x-python' if path.suffix == '.py' else 'application/json'
        refs.append(publish_evidence(context, d.MaterialEvidenceWrite(EXP,
            'delivery01-final-' + path.stem, path.read_bytes(), mime, path.suffix[1:])))
    report_ref = publish_evidence(context, d.ExperimentReportWrite(EXP,
        sha256((WORK / 'report.md').read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED,
        tuple(dict.fromkeys(refs)), previous_ref))
    artifacts = tuple(d.ExperimentArtifactRef(EXP, path.relative_to(WORK).as_posix(), sha256(path.read_bytes()).hexdigest())
                      for path in (*OUT.glob('*.json'), Path(__file__)))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(EXP,
        d.ExperimentValidationScope.REPORT_PUBLICATION, artifacts))
    assert validation.status.value == 'PASS', validation.issues
    save(OUT / 'publication_result.json', {'report': report_ref.to_dict(),
        'assessment': receipt.reference.to_dict(),
        'candidates': document['content']['payload']['source_candidates'],
        'report_validation': asdict(validation), 'delivery_validation': checked.to_dict(),
        'new_account_replays': 0, 'new_search_points': 0, 'report_closeout_seconds': perf_counter() - begun})
    print('REPORT_FINALIZED', report_ref.sha256, validation.status.value, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'publish', 'finish-report'))
    args = parser.parse_args()
    {'prepare': prepare, 'publish': publish, 'finish-report': finish_report}[args.action]()
