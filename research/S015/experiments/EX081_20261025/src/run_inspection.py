"""C9304 stage-five technical inspection; never freeze or touch live PTE."""
from __future__ import annotations

# ruff: noqa: E402 -- limit native threads before numerical imports
import argparse
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import cloudpickle
from czsc_trader.application import (
    RepositoryContext, create_research_context, load_candidate, publish_evidence,
    record_research_decision, describe_inspection_environment, CandidateInspectionRequest,
    InspectionReplay, InspectionProtocol, InspectionDataKind, FreezeTarget, inspect_candidate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
)
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_manager import CandidateKey, CandidateEvidence, StrategyRegistry
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRuntime, StrategyInit, TradableWindow
from strategy_runtime.inspection import InspectionControl

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX081_20261025')
HOME = EX.resolve(ROOT)
OUT = HOME / 'others'
PREVIOUS = HOME.parent / 'EX080_20261025'
CACHE = ROOT / '.tmp/s015-ex081'
KEY = CandidateKey('S015', 'C9304')
CONTENT = 'abf26e331cac4cd030c30aa5f84269e0471d3a4c31b36f5e9f8a0dbf687beda1'
PARAMETERS = dict(center_kind='median', lookback=3, allocation=1., minimum_repair_space=.0017298986606429072)
RISKS = (
    '原候选calendar_request明确拒绝2026-10-21之后的窗口；历史两目标检验不证明前瞻可运行。本轮不修改候选，暂不建议冻结或部署。',
    '预热固定从2024-09-09起，2024-12-31为第75个交易日；每个开发日要求8根完整30分钟线。',
    'PTE渠道事件是独立规定的合成事实；不证明真实券商连接、流动性、滑点或生产已启用。',
    '已见开发数据反复用于研究；技术等价不增加独立收益证据，也不验证三日观察尺度的普适性。',
)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
        resources=ExecutionResources(4, 1, 13))


def material(ctx, path):
    suffix = path.suffix[1:]
    media = {'json': 'application/json', 'py': 'text/x-python', 'md': 'text/markdown',
             'pkl': 'application/octet-stream'}[suffix]
    return publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media, suffix))


def inputs():
    assert not (OUT / 'input_refs.json').exists(), 'Preserve prepared input evidence'
    ctx = context()
    registration = StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(KEY)
    assert registration.content_sha256 == CONTENT
    candidate = load_candidate(ctx.repository, KEY)
    assert dict(candidate.payload['parameters']) == PARAMETERS
    assert not (ROOT / 'strategies/S015/versions/v1.json').exists()
    assessment = d.DeliveryReceipt.from_dict(read(ROOT / 'research/S015/deliveries/ASSESSMENT/5/receipt.json'))
    assert assessment.reference.content_sha256 == 'e47bcc41f87541e50220ae8ce9e4cc20bde0031d153968cc6a7b72e1a6de776c'
    auth = {
        'source': 'human user message in current Codex conversation', 'received_date': '2026-10-25',
        'verbatim': '选择C9304进入阶段五，请你执行',
        'scope': 'Select C9304 and authorize technical inspection plus a concrete plan. Freeze and live deployment are not approved.',
        'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'reviewed_assessment': assessment.reference.to_dict(),
    }
    save(OUT / 'user_selection.json', auth)
    selection = record_research_decision(ctx.repository, f.ResearchDecision(
        'S015-select-C9304-20261025', 'S015', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(KEY, CONTENT, registration.record_sha256),
        CandidateEvidence((OUT / 'user_selection.json').relative_to(ROOT).as_posix(),
                          sha256((OUT / 'user_selection.json').read_bytes()).hexdigest()),
        '用户明确选择C9304进入阶段五；只执行原候选技术检验并准备精确计划，不批准冻结或生产操作。'))
    save(OUT / 'selection_ref.json', selection.to_dict())
    sources = [next(row for row in read(PREVIOUS / 'others/center_replays.json')['rows'] if row['candidate_id'] == 'C9304'),
               next(row for row in read(PREVIOUS / 'others/stress_results.json')['rows'] if row['candidate_id'] == 'C9304')]
    replays, facts = [], []
    for source, stress in zip(sources, (False, True), strict=True):
        reference = EvidenceRef.from_dict(source['evidence'])
        original = read(reference.resolve(ROOT))
        validate_evaluation_evidence(original)
        scenario, fee = ('fee_x2', .002) if stress else ('standard', .001)
        req = ctx.evaluation.prepare(EvaluationRequest(ROOT, 'EX080_20261025', candidate,
            {'candidate_id': candidate.reference_id, 'source_files': list(candidate.payload['runtime']['source_files']),
             'implementation_sha256': candidate.payload['runtime']['source_sha256']},
            '159326.SZ', 'etf', (EvaluationWindow('full', date(2025, 1, 2), date(2026, 10, 21)),),
            date(2026, 10, 21), 100000., (EvaluationCost(scenario, fee, 'STRESS' if stress else 'FORMAL'),),
            benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .001, .1, 1000000))))
        assert req.input_bindings['full'].to_dict() == original['input_bindings']['full']
        assert req.execution_data.fingerprint == original['request_identity']['data_identity']
        run, = original['runs']
        assert run['identity']['candidate'] == KEY.to_dict() and run['identity']['content_sha256'] == CONTENT
        assert run['scenario_id'] == scenario and run['window_id'] == 'full'
        baseline = d.EvaluationEvidenceRef(reference, (original['assessment_evidence'][0]['evaluation_id'],))
        replays.append(InspectionReplay(f.InspectionCoordinate('full', scenario), req.input_bindings['full'],
            req.execution_data, req.initial_cash, fee, baseline))
        facts.append({'coordinate': replays[-1].coordinate.to_dict(), 'baseline': baseline.to_dict(),
                      'execution_fingerprint': req.execution_data.fingerprint, 'sessions': 434,
                      'input_binding': req.input_bindings['full'].to_dict(), 'one_way_cost': fee,
                      'original_request_sha256': original['request_hash']})
    CACHE.mkdir(parents=True, exist_ok=True)
    snapshot = CACHE / 'replays.pkl'
    snapshot.write_bytes(cloudpickle.dumps(tuple(replays)))
    # Pure request construction: no post-cutoff market/calendar data are fetched.
    checks = []
    for day in (date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 26)):
        instance = StrategyRuntime(ctx.repository.strategy_root, dataflows=ctx.data).create(StrategyInit(
            candidate, TradableWindow(day, day), CACHE / 'boundary' / day.isoformat(), pricing=replays[0].execution_data.pricing))
        try:
            request = instance.calendar_request()
        except ValueError as error:
            checks.append({'session': day.isoformat(), 'status': 'REJECTED', 'error': str(error)})
        else:
            checks.append({'session': day.isoformat(), 'status': 'ACCEPTED_REQUEST', 'calendar_end': str(request.end)})
    assert [x['status'] for x in checks] == ['ACCEPTED_REQUEST', 'REJECTED', 'REJECTED']
    save(OUT / 'forward_boundary.json', {'status': 'FORWARD_RUNTIME_BLOCKED', 'candidate': KEY.to_dict(),
        'content_sha256': CONTENT, 'checks': checks, 'new_market_data_fetched': False,
        'interpretation': 'Historical technical pass cannot establish operation after the source LAST boundary; source remains unchanged.'})
    save(OUT / 'input_identity.json', {'candidate': KEY.to_dict(), 'content_sha256': CONTENT,
        'registration_sha256': registration.record_sha256, 'coordinates': facts,
        'scope': 'Two full434 scenarios with original baselines. No new research evaluation or optimization.'})
    refs = {p.stem: material(ctx, p).to_dict() for p in (
        OUT / 'user_selection.json', OUT / 'forward_boundary.json', OUT / 'input_identity.json', snapshot)}
    save(OUT / 'input_refs.json', refs)
    print('INPUTS_AND_SELECTION_RECORDED', 2, 'FORWARD_RUNTIME_BLOCKED', flush=True)


def replays():
    reference = EvidenceRef.from_dict(read(OUT / 'input_refs.json')['replays'])
    raw = reference.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == reference.sha256
    return cloudpickle.loads(raw)


def prepare():
    from pte_protocol import build_protocol
    assert not (OUT / 'prepared.json').exists(), 'Preserve declared technical protocol'
    ctx = context()
    replay, _ = replays()
    candidate = load_candidate(ctx.repository, KEY)
    environment = describe_inspection_environment(ctx.repository)
    pte, reasoning = build_protocol(ctx, candidate, replay.execution_data, replay.input_binding, environment)
    save(OUT / 'pte_design.json', reasoning)
    protocol = InspectionProtocol('candidate-inspection-v2', 'ECONOMIC_V1', 0., pte)
    target = FreezeTarget('v1', None, 'C9304原样候选技术检验包；保留价格修复与周期预算，前瞻日期限制待处理，尚不建议冻结。',
                          date(2026, 10, 21), date(2026, 10, 22))
    save(HOME / 'protocols/inspection.json', {
        'candidate': KEY.to_dict(), 'content_sha256': CONTENT, 'selection': read(OUT / 'selection_ref.json'),
        'protocol': protocol.to_dict(), 'target': target.to_dict(), 'data_kind': 'HISTORICAL',
        'environment': environment.to_dict(), 'input_refs': read(OUT / 'input_refs.json'),
        'resources': {'max_workers': 4, 'native_threads': 1, 'timeout_seconds': 1200.},
        'remaining_risks': RISKS,
        'stop_rule': 'Preserve formal failures and incomplete facts. Never adjust candidate, tolerance or scenario expectations to observed PTE results.',
    })
    paths = [HOME / 'protocols/inspection.json', OUT / 'pte_design.json', *sorted((HOME / 'src').glob('*.py'))]
    refs = {p.relative_to(ROOT).as_posix(): material(ctx, p).to_dict() for p in paths}
    save(OUT / 'prepared.json', {'status': 'READY', 'references': refs,
        'source_hashes': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}})
    print('PROTOCOL_READY', len(pte.scenarios), len(pte.failures), flush=True)


def inspect():
    assert not (OUT / 'inspection_report.json').exists(), 'Retain existing technical report'
    ctx = context()
    prepared = read(OUT / 'prepared.json')
    for path, expected in prepared['source_hashes'].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    saved = read(HOME / 'protocols/inspection.json')
    target = saved['target']
    request = CandidateInspectionRequest(KEY, f.DecisionReference.from_dict(saved['selection']), ctx, EX,
        FreezeTarget(target['version'], target['parent_version'], target['change_summary'],
                     date.fromisoformat(target['selection_data_cutoff']), date.fromisoformat(target['forward_start'])),
        InspectionProtocol.from_dict(saved['protocol']), replays(), InspectionDataKind.HISTORICAL,
        remaining_risks=tuple(saved['remaining_risks']))

    def progress(event):
        value = asdict(event)
        with (CACHE / 'progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(json.dumps(value, ensure_ascii=False), flush=True)

    report = inspect_candidate(ctx.repository, request, control=InspectionControl(
        timeout_seconds=1200., max_workers=4, on_progress=progress))
    save(OUT / 'inspection_report.json', report.to_dict())
    summary = {'status': report.status.value, 'behavior_equivalence': report.behavior_equivalence.status.value,
        'pte_runtime': report.pte_runtime.status.value, 'inspection_sha256': report.sha256,
        'plan_sha256': report.plan.sha256 if report.plan else None,
        'release_sha256': report.release.release_sha256 if report.release else None,
        'package_sha256': report.release.package_sha256 if report.release else None,
        'forward_runtime': 'BLOCKED_BY_CANDIDATE_SOURCE', 'freeze': 'NOT_REQUESTED', 'production': 'NOT_TOUCHED'}
    save(OUT / 'inspection_summary.json', summary)
    if report.plan:
        save(OUT / 'freeze_plan.json', report.plan.to_dict())
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inputs', 'prepare', 'inspect'))
    args = parser.parse_args()
    {'inputs': inputs, 'prepare': prepare, 'inspect': inspect}[args.mode]()
