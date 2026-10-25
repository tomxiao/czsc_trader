"""Inspect the registered date-boundary adaptation; never freeze or deploy."""
from __future__ import annotations

# ruff: noqa: E402 -- establish worker limits before loading numerical modules
import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
import json
import os
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import cloudpickle
import adapt
from czsc_trader.application import (
    CandidateInspectionRequest, FreezeTarget, InspectionDataKind, InspectionProtocol,
    InspectionReplay, describe_inspection_environment, inspect_candidate,
)
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from paper_trading_engine.inspection import PteEnvironmentRequirement
from strategy_manager import StrategyRegistry, canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyRuntime
from strategy_runtime.inspection import InspectionControl

ROOT, HOME, OUT, EX, KEY = adapt.ROOT, adapt.HOME, adapt.OUT, adapt.EX, adapt.KEY
OLD_HOME = HOME.parent / 'EX081_20261025'
CACHE = ROOT / '.tmp/s015-ex082'
RISKS = (
    '本轮只解除源码中的研究日期上界，并以原历史数据核验等价；未取得或验证截止日之后的行情及实际前瞻收益。',
    '预热固定从2024-09-09起；每个开发日要求8根完整30分钟线。历史窗口增长后的资源与输入完整性仍需运行期保障。',
    'PTE渠道事件是独立规定的合成事实；不证明真实券商连接、流动性、滑点或生产已启用。',
    '部分撤单须阻断等待人工确认；公共检验协议不覆盖人工确认后的补买。',
    '已见开发数据反复用于研究；技术等价不增加独立收益证据，也不验证三日观察尺度的普适性。',
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def portable(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def verify_prepared():
    value = adapt.read(OUT / 'inspection_prepared.json')
    for relative, expected in value['source_hashes'].items():
        assert digest(ROOT / relative) == expected, relative
    for raw in value['references'].values():
        ref = EvidenceRef.from_dict(raw)
        assert digest(ref.resolve(ROOT)) == ref.sha256
    return value


def prepare():
    outputs = (HOME / 'protocols/inspection.json', OUT / 'pte_design.json',
               OUT / 'inspection_input_identity.json', OUT / 'inspection_prepared.json')
    assert all(not x.exists() for x in outputs), 'Preserve existing inspection preparation'
    ctx = adapt.context()
    candidate = adapt.candidate(ctx)
    identity = adapt.read(OUT / 'identity.json')
    content = identity['content_sha256']
    assert candidate.candidate_id == KEY.candidate_id == 'C9700'
    assert StrategyRuntime().identify(candidate, dependencies=()).content_sha256 == content
    assert StrategyRegistry(ctx.repository.research_registry_root).get_candidate_registration(KEY).content_sha256 == content
    assert not (ROOT / 'strategies/S015/versions/v1.json').exists()
    old_saved = adapt.read(OLD_HOME / 'protocols/inspection_v2.json')
    old_protocol = InspectionProtocol.from_dict(old_saved['protocol'])
    old_replays = adapt.old_replays()
    assert len(old_replays) == 2
    results = adapt.read(OUT / 'results.json')
    assert results['status'] == 'PASS' and len(results['rows']) == 2
    rows = results['rows']
    replays, replay_facts = [], []
    for old in old_replays:
        coordinate = old.coordinate
        matches = [x for x in rows if x['scenario_id'] == coordinate.scenario_id]
        assert len(matches) == 1, coordinate
        ref = EvidenceRef.from_dict(matches[0]['evidence'])
        evidence = adapt.read(ref.resolve(ROOT))
        validate_evaluation_evidence(evidence)
        runs = [x for x in evidence['runs'] if (x['window_id'], x['scenario_id']) ==
                (coordinate.window_id, coordinate.scenario_id)]
        assert len(runs) == 1
        run = runs[0]
        assert run['identity']['candidate'] == KEY.to_dict()
        assert run['identity']['content_sha256'] == content
        binding = adapt.rebind(ctx, candidate, old.input_binding, old.execution_data,
                               'inspection_full_' + coordinate.scenario_id)
        assert portable(binding.to_dict()) == evidence['input_bindings'][coordinate.window_id]
        assert old.execution_data.fingerprint == evidence['request_identity']['data_identity']
        evaluation_id = canonical_sha256(run['identity'])
        assert any(x['evaluation_id'] == evaluation_id for x in evidence['assessment_evidence'])
        baseline = d.EvaluationEvidenceRef(ref, (evaluation_id,))
        replays.append(InspectionReplay(coordinate, binding, old.execution_data,
                                       old.initial_cash, old.one_way_cost, baseline))
        replay_facts.append({'coordinate': coordinate.to_dict(), 'baseline': baseline.to_dict(),
            'candidate': KEY.to_dict(), 'content_sha256': content,
            'old_binding': old.input_binding.to_dict(), 'new_binding': binding.to_dict(),
            'execution_fingerprint': old.execution_data.fingerprint,
            'initial_cash': old.initial_cash, 'one_way_cost': old.one_way_cost})
    scenarios, binding_facts = [], []
    for scenario in old_protocol.pte.scenarios:
        decisions = []
        for decision in scenario.decisions:
            tag = 'inspection_pte_' + scenario.scenario_id + '_' + decision.step_id
            binding = adapt.rebind(ctx, candidate, decision.binding, old_replays[0].execution_data, tag)
            decisions.append(replace(decision, binding=binding))
            binding_facts.append({'scenario_id': scenario.scenario_id, 'step_id': decision.step_id,
                'old_binding': decision.binding.to_dict(), 'new_binding': binding.to_dict()})
        revised = replace(scenario, decisions=tuple(decisions))
        assert revised.channel_events == scenario.channel_events
        assert revised.checkpoints == scenario.checkpoints
        assert revised.restart_after == scenario.restart_after
        scenarios.append(revised)
    environment = describe_inspection_environment(ctx.repository)
    requirement = PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version)
    protocol = replace(old_protocol, pte=replace(old_protocol.pte,
        environment=requirement, scenarios=tuple(scenarios)))
    assert protocol.pte.coverage == old_protocol.pte.coverage
    assert protocol.pte.failures == old_protocol.pte.failures
    assert InspectionProtocol.from_dict(protocol.to_dict()) == protocol
    design = deepcopy(adapt.read(OLD_HOME / 'others/pte_design_v2.json'))
    design['candidate'] = candidate.reference_id
    design['content_sha256'] = content
    design['parent_binding'] = replays[0].input_binding.to_dict()
    # Former bindings remain in the authenticated predecessor design, never
    # masquerading as current candidate bindings in this successor document.
    design.pop('single_day_inputs', None)
    design['single_day_bindings'] = binding_facts
    design['source_design'] = {'path': '../EX081_20261025/others/pte_design_v2.json',
        'sha256': digest(OLD_HOME / 'others/pte_design_v2.json'),
        'candidate': old_saved['candidate'], 'content_sha256': old_saved['content_sha256']}
    design['adaptation'] = {
        'purpose': 'Remove only the research-date upper bound under a new registered content identity.',
        'expectations': 'Inherited independent arithmetic and business checkpoints are unchanged. Two actual new-identity historical evaluations establish zero-tolerance economic equivalence before this inspection.',
        'scenario_ids': 'c9304 names identify the inherited historical event path; the bound candidate is C9700.',
        'identity_changes': 'Candidate, runtime and data-plan identities are regenerated by public APIs. Reused prepared input content and original channel/checkpoint facts remain intact.',
        'new_market_data_fetched': False, 'freeze_authorized': False, 'production_touched': False,
    }
    design['limits'] = list(RISKS)
    target = FreezeTarget('v1', None,
        'C9700仅解除C9304研究日期上界；新内容身份历史等价与阶段五技术检验计划，尚未冻结或部署。',
        date(2026, 10, 21), date(2026, 10, 26))
    CACHE.mkdir(parents=True, exist_ok=True)
    snapshot = CACHE / 'inspection_replays.pkl'
    assert not snapshot.exists(), 'Preserve previous inspection input snapshot'
    snapshot.write_bytes(cloudpickle.dumps(tuple(replays)))
    adapt.save(outputs[0], {'candidate': KEY.to_dict(), 'content_sha256': content,
        'selection': adapt.read(OUT / 'selection_ref.json'), 'protocol': protocol.to_dict(),
        'target': target.to_dict(), 'data_kind': 'HISTORICAL', 'environment': environment.to_dict(),
        'resources': {'max_workers': 4, 'native_threads': 1, 'timeout_seconds': 1200.},
        'remaining_risks': RISKS, 'predecessor': {'path': '../EX081_20261025/protocols/inspection_v2.json',
            'sha256': digest(OLD_HOME / 'protocols/inspection_v2.json')},
        'stop_rule': 'Preserve all failures. Do not adjust candidate, channel facts, expectations or tolerance in response to observed inspection results.'})
    adapt.save(outputs[1], design)
    adapt.save(outputs[2], {'candidate': KEY.to_dict(), 'content_sha256': content,
        'replays': replay_facts, 'pte_bindings': binding_facts,
        'scope': 'Only authenticated S015 historical prepared inputs; no future-market acquisition.'})
    materials = [*outputs[:3], OUT / 'identity.json', OUT / 'selection_ref.json', OUT / 'results.json',
        OUT / 'prepared.json',
        OLD_HOME / 'protocols/inspection_v2.json', OLD_HOME / 'others/pte_design_v2.json',
        snapshot, *sorted((HOME / 'src').rglob('*.py'))]
    refs = {p.relative_to(ROOT).as_posix(): adapt.material(ctx, p).to_dict() for p in materials}
    adapt.save(outputs[3], {'status': 'READY', 'references': refs,
        'replays_reference': refs[snapshot.relative_to(ROOT).as_posix()],
        'source_hashes': {p.relative_to(ROOT).as_posix(): digest(p) for p in materials}})
    print('ADAPTED_INSPECTION_READY', len(replays), len(scenarios), len(protocol.pte.failures), flush=True)


def inspect():
    assert not (OUT / 'inspection_report.json').exists(), 'Preserve existing technical report'
    prepared = verify_prepared()
    saved = adapt.read(HOME / 'protocols/inspection.json')
    ctx = adapt.context()
    candidate = adapt.candidate(ctx)
    assert candidate.candidate_id == KEY.candidate_id
    assert StrategyRuntime().identify(candidate, dependencies=()).content_sha256 == saved['content_sha256']
    reference = EvidenceRef.from_dict(prepared['replays_reference'])
    replays = cloudpickle.loads(reference.resolve(ROOT).read_bytes())
    target = saved['target']
    request = CandidateInspectionRequest(KEY, f.DecisionReference.from_dict(saved['selection']), ctx, EX,
        FreezeTarget(target['version'], target['parent_version'], target['change_summary'],
            date.fromisoformat(target['selection_data_cutoff']), date.fromisoformat(target['forward_start'])),
        InspectionProtocol.from_dict(saved['protocol']), replays, InspectionDataKind.HISTORICAL,
        remaining_risks=tuple(saved['remaining_risks']))

    def progress(event):
        value = asdict(event)
        with (CACHE / 'inspection_progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        print(json.dumps(value, ensure_ascii=False), flush=True)

    report = inspect_candidate(ctx.repository, request, control=InspectionControl(
        timeout_seconds=1200., max_workers=4, on_progress=progress))
    adapt.save(OUT / 'inspection_report.json', report.to_dict())
    summary = {'candidate': KEY.to_dict(), 'content_sha256': saved['content_sha256'],
        'status': report.status.value, 'behavior_equivalence': report.behavior_equivalence.status.value,
        'pte_runtime': report.pte_runtime.status.value, 'inspection_sha256': report.sha256,
        'plan_sha256': report.plan.sha256 if report.plan else None,
        'release_sha256': report.release.release_sha256 if report.release else None,
        'package_sha256': report.release.package_sha256 if report.release else None,
        'future_market_data': 'NOT_ACQUIRED', 'freeze': 'NOT_REQUESTED', 'production': 'NOT_TOUCHED'}
    adapt.save(OUT / 'inspection_summary.json', summary)
    if report.plan:
        adapt.save(OUT / 'freeze_plan.json', report.plan.to_dict())
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'inspect'))
    args = parser.parse_args()
    {'prepare': prepare, 'inspect': inspect}[args.mode]()
