"""Inspect the user-selected candidate through public APIs; never freeze or deploy."""
import argparse
import json
import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import cloudpickle  # noqa: E402
from czsc_trader.application import (  # noqa: E402
    RepositoryContext, create_research_context, load_candidate, publish_evidence,
    record_research_decision, CandidateInspectionRequest, InspectionReplay, inspect_candidate,
)
from czsc_trader.research_tools import (  # noqa: E402
    ResearchBatchRef, ExperimentRef, EvaluationResources, EvidenceRef, MaterialEvidenceWrite,
)
from czsc_trader.research_tools import delivery as d  # noqa: E402
from strategy_manager import CandidateEvidence, CandidateKey, StrategyRegistry  # noqa: E402
from strategy_manager import freeze_contracts as f  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = ExperimentRef('S015', 'EX006_20261022')
EROOT = EXPERIMENT.resolve(ROOT)
REQUEST_SNAPSHOT = ROOT / 'research/S015/assets/runs/EX006_20261022/replay_requests.pkl'
CONTENT = '6a6e536c6c2f017c43d238633267c05f1f2b9d647aa22d52506d9e8e0a81d580'
ASSESSMENT = '020663f560ebd639bf0f01eeca03917e44f96f9d4f22bdf2abae64910374943f'
KEY = CandidateKey('S015', 'C0031')
RISKS = (
    '全部2025-01-02至2026-10-21信息均已见；继承阶段二1092项比较及阶段三181个配置等选择历史，不能声称独立Alpha或未来成功概率。',
    '阶段四PBO为0.785714；有效次数和DSR因零方差等条件缺失；C0031超额年化95%重抽样区间跨零（约-6.47至66.02个百分点）。',
    '32点参数检验没有改变max_days；不覆盖正负一日、额外半径、类别切换或参数与费用交叉压力。',
    '执行遵循用户认可的DAILY_RANGE_V3：按价格区间、不按成交量；日线与30分钟开盘存在容差内差异，不证明真实足量成交。',
    '约定17:30决策与公共运行20:31存在时钟差异；原pilot时钟等价证据不扩张为C0031历史17:30发布与修订链认证。',
    '信号年龄按意图而非实际成交计数；本候选使用full_available_cash周期目标，允许周期内补齐，并非逐日权益仓位再平衡。',
    '25%为历史回撤上限，并非运行止损或未来损失保证；PTE账户、调度、预警、暂停及部署须另行约定与授权。',
    'forward_start为选择截止日之后的证据分界，不是已启动前瞻观察或生产启用日期；本轮不读取2026-10-22及之后行情。',
    '正式数据、候选、决定、检验与交付资产不全在Git内，必须独立保留；本检验不代表仓库级全量回归。',
)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def context():
    repository = RepositoryContext.discover(ROOT)
    return create_research_context(repository, ResearchBatchRef('S015'),
                                   resources=EvaluationResources(1, 1, 13))


def file_ref(path):
    return CandidateEvidence(path.relative_to(ROOT).as_posix(), sha256(path.read_bytes()).hexdigest())


def material(ctx, name, path, media='application/json', suffix='json'):
    return publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), media, suffix))


def prepare(ctx):
    if (EROOT / 'others/prepared.json').exists():
        raise RuntimeError('Preparation already retained; do not overwrite')
    reg = StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(KEY)
    assert reg.content_sha256 == CONTENT
    receipt_path = ROOT / 'research/S015/deliveries/ASSESSMENT/1/receipt.json'
    receipt = d.DeliveryReceipt.from_dict(read(receipt_path))
    assert receipt.reference.content_sha256 == ASSESSMENT
    assert not (ROOT / 'strategies/S015').exists(), 'Version availability must be reviewed'
    original = next(row for row in read(ROOT / 'research/S015/assets/runs/EX003_20261021/strategy_study/grid_results.json')
                    if row['candidate_id'] == 'C0031')
    stress = next(row for row in read(ROOT / 'research/S015/assets/runs/EX005_20261022/assessment/results/C0031.json')
                  if row['kind'] == 'stress')
    # Reuse the exact publicly prepared requests from phase four, including immutable data references.
    cached = cloudpickle.loads((ROOT / '.tmp/s015_stage4/requests/C0031.pkl').read_bytes())
    candidate = load_candidate(ctx.repository, KEY)
    requests, references = [], []
    for name, row in (('center', original), ('stress', stress)):
        req = replace(cached[name], strategy=candidate, workers=1)
        ref = EvidenceRef.from_dict(row['evidence'])
        baseline = read(ref.resolve(ROOT))
        identity = baseline['request_identity']
        assert identity['content_sha256'] == CONTENT
        assert req.experiment_id == identity['experiment_id']
        assert req.execution_data.fingerprint == identity['data_identity']
        assert {k: v.to_dict() for k, v in req.input_bindings.items()} == identity['input_bindings']
        assert req.costs[0].scenario_id == identity['costs'][0]['scenario_id']
        assert req.costs[0].one_way_cost == identity['costs'][0]['one_way_cost']
        assert req.costs[0].measurement_tier == identity['costs'][0]['measurement_tier']
        ctx.evaluation.prepare(req)
        requests.append(req)
        references.append(d.EvaluationEvidenceRef(ref, (row['evaluation_id'],)))
    snapshot = REQUEST_SNAPSHOT
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(cloudpickle.dumps(tuple(requests)))
    authorization = {
        'source': 'human user message in current Codex conversation',
        'received_date': '2026-10-22',
        'verbatim': '1、我理解从因果关系来解释，信号质量是因，多档位是果。只有提升了信号的区分度，多档位才能体现价值\n2、认同你的选择\n确认选择C0031进入阶段五，请你主导执行',
        'interpretation': 'Select only S015-C0031 from ASSESSMENT/1; authorize phase-five inspection and freeze-plan preparation. Exact freeze approval remains pending.',
        'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'source_assessment': receipt.reference.to_dict(),
    }
    save(EROOT / 'others/user_selection.json', authorization)
    protocol = {
        'purpose': 'Technical delivery inspection, not a new search or independent validation sample',
        'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'protocol': f.InspectionProtocol((f.InspectionCoordinate('full', 'standard'),
                                        f.InspectionCoordinate('full', 'fee_x2')), 0.0).to_dict(),
        'references': [ref.to_dict() for ref in references],
        'scope': 'Original 434-session full window, standard and doubled costs; original bound data only; candidate and prospective release replay.',
        'version': 'v1', 'parent_version': None,
        'selection_data_cutoff': '2026-10-21', 'forward_start': '2026-10-22',
        'forward_boundary_meaning': 'Earliest post-selection data boundary only, not PTE or production activation.',
        'request_snapshot_sha256': sha256(snapshot.read_bytes()).hexdigest(),
        'resources': {'max_workers': 1, 'native_threads': 1, 'seed': 13},
        'remaining_risks': RISKS,
        'stop_rule': 'Preserve failures or incomplete checks; never alter candidate or data to make inspection pass.',
    }
    save(EROOT / 'protocols/inspection.json', protocol)
    refs = {
        'authorization': material(ctx, 'user_selection', EROOT / 'others/user_selection.json').to_dict(),
        'protocol': material(ctx, 'inspection_protocol', EROOT / 'protocols/inspection.json').to_dict(),
        'replay_requests': material(ctx, 'replay_requests', snapshot, 'application/octet-stream', 'pkl').to_dict(),
    }
    save(EROOT / 'others/prepared.json', {'status': 'PASS', 'references': refs})
    print(json.dumps({'preparation': 'PASS', 'coordinates': 2, 'version': 'v1'}), flush=True)


def select(ctx):
    if (EROOT / 'others/selection_ref.json').exists():
        raise RuntimeError('Selection is already recorded')
    assert read(EROOT / 'others/prepared.json')['status'] == 'PASS'
    result = record_research_decision(ctx.repository, f.ResearchDecision(
        'S015-select-C0031-20261022', 'S015', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(file_ref(ROOT / 'research/S015/deliveries/ASSESSMENT/1/receipt.json'), KEY, CONTENT),
        file_ref(EROOT / 'others/user_selection.json'),
        '用户明确选择C0031进入阶段五；本决定仅确认选型，不批准冻结或部署。'))
    save(EROOT / 'others/selection_ref.json', result.to_dict())
    print(json.dumps({'selection': result.to_dict()}, ensure_ascii=False), flush=True)


def inspect(ctx):
    if (EROOT / 'others/inspection_report.json').exists():
        raise RuntimeError('Inspection already retained; do not overwrite')
    protocol = read(EROOT / 'protocols/inspection.json')
    snapshot = REQUEST_SNAPSHOT
    assert sha256(snapshot.read_bytes()).hexdigest() == protocol['request_snapshot_sha256']
    requests = cloudpickle.loads(snapshot.read_bytes())
    replays = tuple(InspectionReplay(d.EvaluationEvidenceRef.from_dict(ref), req)
                   for ref, req in zip(protocol['references'], requests, strict=True))
    report = inspect_candidate(ctx.repository, CandidateInspectionRequest(
        KEY, f.DecisionReference.from_dict(read(EROOT / 'others/selection_ref.json')),
        f.InspectionProtocol.from_dict(protocol['protocol']), ctx, EXPERIMENT, replays,
        'v1', None, '首次冻结计划：保留用户选定C0031原始源码、参数和周期资金合同。',
        '2026-10-21', '2026-10-22', remaining_risks=RISKS))
    save(EROOT / 'others/inspection_report.json', report.to_dict())
    if report.plan is not None:
        save(EROOT / 'others/freeze_plan.json', report.plan.to_dict())
    save(EROOT / 'others/inspection_summary.json', {
        'status': report.status.value, 'content_sha256': report.origin.content_sha256,
        'inspection_sha256': report.sha256, 'plan_sha256': None if report.plan is None else report.plan.sha256,
        'checks': [{'check': c.check.value, 'status': c.status.value, 'detail': c.detail} for c in report.checks],
        'freeze': 'NOT_REQUESTED', 'deployment': 'NOT_REQUESTED',
    })
    print(json.dumps(read(EROOT / 'others/inspection_summary.json'), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'select', 'inspect'))
    args = parser.parse_args()
    {'prepare': prepare, 'select': select, 'inspect': inspect}[args.mode](context())
