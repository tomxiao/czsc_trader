"""Authenticate the observation selection and prepare a reviewable upgrade inspection."""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
import argparse
import cloudpickle

import verify_upgrade as v
from czsc_trader.application import (
    record_research_decision, CandidateInspectionRequest, FreezeTarget, InspectionDataKind,
    InspectionProtocol, InspectionReplay, describe_inspection_environment, inspect_candidate,
)
from czsc_trader.research_tools import EvidenceRef, MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_manager import freeze_contracts as f, canonical_sha256
from strategy_runtime.inspection import InspectionControl
from paper_trading_engine.inspection import PteEnvironmentRequirement

REVISION = ''


def reference(raw):
    ref = EvidenceRef.from_dict(raw)
    return f.ResearchEvidenceRef(f.ResearchEvidenceOwner('S015', v.EX.experiment_id), ref.evidence_id, ref.sha256)


def select():
    ctx = v.context()
    original = v.read(v.ROOT / 'strategies/S015/versions/v1.json')
    package = v.read(v.ROOT / 'strategies/S015/releases/v1/release_manifest.json')
    original_ref = f.FrozenVersionReference('S015', 'v1', original['release_hash'], package['package_hash'])
    refs = v.read(v.OUT / 'equivalence_refs.json')
    subject = f.FrozenObservationUpgradeSelectionSubject(original_ref, v.KEY,
        v.read(v.OUT / 'identity.json')['content_sha256'], tuple(reference(refs[k]) for k in ('manifest', 'case')))
    protocol = v.HOME / 'protocols/observation_upgrade_final.json'
    auth = v.publish_evidence(ctx, MaterialEvidenceWrite(v.EX, 'observation_upgrade_authorization',
        protocol.read_bytes(), 'application/json', 'json'))
    selection = record_research_decision(ctx.repository, f.ResearchDecision(
        'S015-observation-upgrade-C9800-20261025', 'S015', f.DecisionAction.APPROVE, subject,
        reference(auth.to_dict()), '用户授权RSCH策略观察升级；原交易代码与真实双模式经济路径均保持不变。此选择仅供技术检验，冻结与部署仍待精确批准。'))
    v.save(v.OUT / 'selection_ref.json', selection.to_dict())
    print('OBSERVATION_SELECTION_AUTHENTICATED', selection.sha256, flush=True)


def prepare():
    ctx = v.context()
    _, child = v.sources()
    old_home = v.HOME.parent / 'EX082_20261025'
    previous = v.read(old_home / 'protocols/inspection.json')
    protocol = InspectionProtocol.from_dict(previous['protocol'])
    saved = v.read(old_home / 'others/inspection_prepared.json')
    prior = cloudpickle.loads(EvidenceRef.from_dict(saved['replays_reference']).resolve(v.ROOT).read_bytes())
    evidence = [EvidenceRef.from_dict(raw) for raw in v.read(v.OUT / 'account_evaluation_refs.json')]
    replays = []
    for old in prior:
        ref = next(ref for ref in evidence if v.read(ref.resolve(v.ROOT))['runs'][0]['scenario_id'] == old.coordinate.scenario_id)
        run, = v.read(ref.resolve(v.ROOT))['runs']
        request = SimpleNamespace(input_bindings={'full': old.input_binding}, execution_data=old.execution_data)
        _, binding = v.bind(ctx, child, request, 'inspection-' + old.coordinate.scenario_id)
        baseline = d.EvaluationEvidenceRef(ref, (canonical_sha256(run['identity']),))
        replays.append(InspectionReplay(old.coordinate, binding, old.execution_data,
                                       old.initial_cash, old.one_way_cost, baseline))
    scenarios = []
    for scenario in protocol.pte.scenarios:
        decisions = []
        for decision in scenario.decisions:
            request = SimpleNamespace(input_bindings={'full': decision.binding}, execution_data=prior[0].execution_data)
            _, binding = v.bind(ctx, child, request, 'pte-' + scenario.scenario_id + '-' + decision.step_id)
            decisions.append(replace(decision, binding=binding))
        scenarios.append(replace(scenario, decisions=tuple(decisions)))
    environment = describe_inspection_environment(ctx.repository)
    requirement = PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version)
    protocol = replace(protocol, pte=replace(protocol.pte, scenarios=tuple(scenarios), environment=requirement))
    target = FreezeTarget('v1', None, 'S015-v1仅升级信号区观察声明及显示事实，保留交易算法、参数、日期与资金规则。',
                          date(2026, 10, 21), date(2026, 10, 26))
    v.save(v.HOME / f'protocols/inspection{REVISION}.json', {
        'protocol': protocol.to_dict(), 'target': target.to_dict(), 'environment': environment.to_dict(),
        'selection': v.read(v.OUT / 'selection_ref.json'),
        'limits': ['仅技术历史复验，不新增收益/稳健性证据；没有使用新数据或扩大研究目标。',
                   '渠道故障为独立规定的合成事件，不是生产实际交易。',
                   'C9800仅为观察升级候选，精确冻结和生产改绑未获执行批准。'],
        'stop': 'Preserve all original failure outcomes. No economic tolerance adjustment.'})
    snapshot = v.CACHE / f'inspection_replays{REVISION}.pkl'
    snapshot.write_bytes(cloudpickle.dumps(tuple(replays)))
    ref = v.publish_evidence(ctx, MaterialEvidenceWrite(v.EX, 'inspection_replays', snapshot.read_bytes(),
                                                       'application/octet-stream', 'pkl'))
    v.save(v.OUT / f'inspection_prepared{REVISION}.json', {'replays_reference': ref.to_dict()})
    print('INSPECTION_PREPARED', len(replays), len(scenarios), flush=True)


def inspect():
    ctx = v.context()
    saved = v.read(v.HOME / f'protocols/inspection{REVISION}.json')
    raw = v.read(v.OUT / f'inspection_prepared{REVISION}.json')['replays_reference']
    replays = cloudpickle.loads(EvidenceRef.from_dict(raw).resolve(v.ROOT).read_bytes())
    target = saved['target']
    request = CandidateInspectionRequest(v.KEY, f.DecisionReference.from_dict(saved['selection']), ctx, v.EX,
        FreezeTarget(target['version'], target['parent_version'], target['change_summary'],
            date.fromisoformat(target['selection_data_cutoff']), date.fromisoformat(target['forward_start'])),
        InspectionProtocol.from_dict(saved['protocol']), replays, InspectionDataKind.HISTORICAL,
        remaining_risks=tuple(saved['limits']))
    report = inspect_candidate(ctx.repository, request, control=InspectionControl(timeout_seconds=1200., max_workers=2))
    v.save(v.OUT / f'inspection_report{REVISION}.json', report.to_dict())
    if report.plan:
        v.save(v.OUT / f'freeze_plan{REVISION}.json', report.plan.to_dict())
    print('INSPECTION_RESULT', report.status.value, report.sha256, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('select', 'prepare', 'inspect'))
    parser.add_argument('--revision', choices=('', '_v2'), default='')
    args = parser.parse_args()
    REVISION = args.revision
    {'select': select, 'prepare': prepare, 'inspect': inspect}[args.mode]()
