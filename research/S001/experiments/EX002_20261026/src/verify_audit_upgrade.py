"""RSCH verification of S001 explanation upgrades, independent of upgrade gates."""
from copy import deepcopy
from dataclasses import fields
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import cloudpickle
import pandas as pd

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_release_package
from czsc_trader.research_tools import ExperimentRef, ExecutionResources, MaterialEvidenceWrite, ResearchBatchRef
from dataflows import ProviderConfig
from strategy_runtime import (
    RuntimeContractError, SignalHistoryMode, StrategyCandidate, StrategyDefinition,
    StrategyRelease, StrategyRuntime, implementation_sha256,
)
from strategy_runtime.signal_panel import materialize_signal_panel

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'research/S015/experiments/EX085_20261026/src'))
import upgrade_batch as shared  # noqa: E402


def semantic_check(candidate, definition):
    spec = importlib.util.spec_from_file_location('s001_semantic_helpers', HOME / 'src/verify_observation_semantics.py')
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    source = candidate.source_root
    module = helpers.load(source / 'strategies/observation_s001_v4.py')
    rule = json.loads(json.dumps(dict(candidate.payload['parameters']['rule']), default=dict))
    positions = helpers.function(source / 'strategies/s001_common.py', '_positions')
    scores = pd.Series([0., rule['entry_threshold'], .5, rule['exit_threshold'],
                        rule['exit_threshold'], 0., rule['entry_threshold']],
                       index=pd.date_range('2026-01-01', periods=7))
    targets = positions(scores, enter=rule['entry_threshold'], exit_=rule['exit_threshold'],
                        confirm_days=rule['confirm_days'], min_hold_days=rule['min_hold_days'],
                        exit_confirm_days=rule['exit_confirm_days'])
    history = pd.DataFrame({'factor_score': scores, 'target_position': targets, 'regime': 'range'})
    result = module.observation_history(history, rule)
    assert result.iloc[1].obs_action == 'enter'
    assert result.iloc[3].obs_action == 'hold'
    assert result.iloc[4].obs_action == 'exit'
    evidence = [row.to_dict() for _, row in result.iterrows()]
    initial = module.observation_history(history.loc[history.target_position.eq(1)].iloc[:1], rule)
    evidence.extend(row.to_dict() for _, row in initial.iterrows())
    snapshots = [materialize_signal_panel(definition.observation.signal_panel, row).to_dict() for row in evidence]
    cases = {item['explanation']['case_key'] for item in snapshots}
    assert cases == {'enter', 'exit', 'hold', 'cash', 'initial_long', 'initial_cash'}
    missing = history.iloc[:1].copy()
    missing['factor_score'] = float('nan')
    unknown = deepcopy(evidence[0])
    unknown['obs_action'] = 'undeclared'
    for row in (module.observation_history(missing, rule).iloc[0].to_dict(), unknown):
        try:
            materialize_signal_panel(definition.observation.signal_panel, row)
        except RuntimeContractError:
            pass
        else:
            raise AssertionError('missing/unknown branch must reject explanation')
    invalid = json.loads(json.dumps(dict(candidate.payload), default=dict))
    invalid['parameters']['rule']['execution']['instrument']['symbol'] = 'INVALID'
    try:
        StrategyRuntime().describe(StrategyCandidate('S001', candidate.candidate_id, invalid, candidate.source_root))
    except RuntimeContractError as exc:
        assert 'S001 frozen symbol' in str(exc)
    else:
        raise AssertionError('invalid symbol must retain original RuntimeContractError boundary')
    return {'status': 'PASS', 'kind': 'SYNTHETIC_BRANCH_SEMANTICS', 'cases': sorted(cases),
            'observations': snapshots, 'unavailable_rejected': True, 'unknown_branch_rejected': True,
            'invalid_symbol_contract_error': True,
            'limits': 'Synthetic branch evidence tests explanation correctness, not profitability.'}


def run(reference):
    item = shared.ITEMS[reference]
    experiment = ExperimentRef.from_dict(item['experiment'])
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S001'),
        resources=ExecutionResources(2, 1, 42), providers=ProviderConfig(bindings={}))
    source = ROOT / item['source']
    manifest, binding, original_source = validate_release_package(ctx.repository, reference)
    assert manifest['strategy_version_hash'] == item['original']['release_hash']
    payload = json.loads(json.dumps(item['original']['strategy_payload']))
    payload['runtime']['source_files'] = list(dict.fromkeys(
        payload['runtime']['source_files'] + binding['install_files'] + ['strategies/observation_s001_v4.py']))
    payload['runtime']['source_sha256'] = implementation_sha256(tuple(payload['runtime']['source_files']), source_root=source)
    candidate = StrategyCandidate('S001', item['candidate_id'], payload, source)
    original = StrategyRelease.from_mapping(item['original'])
    runtime = StrategyRuntime(ctx.repository.strategy_root)
    before, after = runtime.describe(original), runtime.describe(candidate)
    for field in fields(StrategyDefinition):
        if field.name != 'observation':
            assert getattr(before, field.name) == getattr(after, field.name), field.name
    assert before.observation.series == after.observation.series
    assert before.observation.facts == after.observation.facts
    for name in binding['install_files']:
        if not name.endswith(reference.lower().replace('-', '_') + '.py'):
            assert (source / name).read_bytes() == (original_source / name).read_bytes(), name
    out = HOME / 'others' / reference / 'audit_replay_v2'
    out.mkdir(parents=True, exist_ok=False)
    shared.save(out / 'candidate_payload.json', payload)
    shared.save(out / 'semantics.json', semantic_check(candidate, after))
    q = cloudpickle.loads((shared.WORK / (reference + '-baseline.pkl')).read_bytes())
    pairs = [shared.bind(ctx, obj, q, reference + '-' + tag) for obj, tag in ((original, 'old'), (candidate, 'new'))]
    instances, bindings = zip(*pairs, strict=True)
    for tag, bound in zip(('old', 'new'), bindings, strict=True):
        shared.save(out / (tag + '_binding.json'), bound.to_dict())
    modes = {}
    for mode in SignalHistoryMode:
        histories = [obj.inspect_signals(history_mode=mode) for obj in instances]
        clean = []
        for history, obj in zip(histories, instances, strict=True):
            panel = obj.definition.observation.signal_panel
            allowed = set(panel.evidence_fields) if panel else set()
            assert all(name in allowed for name in history if name.startswith('obs_'))
            clean.append(history.drop(columns=list(allowed & set(history))))
        shared.equal_frame(*clean, {})
        for tag, history in zip(('old', 'new'), histories, strict=True):
            history.to_csv(out / f'{tag}_{mode.value}_signals.csv')
        results = [shared.run_account(obj, bound, q.execution_data, mode) for obj, bound in pairs]
        for left, right in zip(results[0][1], results[1][1], strict=True):
            assert left['series'] == right['series'] and left['facts'] == right['facts']
        shared.save(out / f'new_{mode.value}_observations.json', results[1][1])
        mapping, checks = {}, []
        for name in shared.NAMES:
            frames = [getattr(result[0], name) for result in results]
            for tag, frame in zip(('old', 'new'), frames, strict=True):
                frame.to_csv(out / f'{tag}_{mode.value}_{name}.csv', index=False)
            compare = [frame.drop(columns=[col for col in frame if col.startswith('obs_')])
                       if name == 'decisions' else frame for frame in frames]
            shared.equal_frame(*compare, mapping)
            checks.append({'name': name, 'rows': len(frames[1]), 'comparison': 'EXACT_VALUES_ZERO_TOLERANCE'})
        shared.save(out / f'{mode.value}_nonzero_probes.json', shared.probes(instances, bindings, q.execution_data, mode))
        modes[mode.value] = {'status': 'PASS', 'signals': len(histories[1]), 'ledgers': checks,
                            'fills': len(results[1][0].fills)}
        print(reference, mode.value, 'PASS', modes[mode.value], flush=True)
    result = {'status': 'PASS', 'reference': reference, 'candidate_id': candidate.candidate_id,
              'source_sha256': payload['runtime']['source_sha256'],
              'scope': 'Real authenticated original inputs, public SRT/TXE, unchanged trade definition and five ledgers.',
              'window': shared.plain(bindings[0].plan.tradable_window), 'modes': modes,
              'new_data': False, 'search_trials': 0, 'semantics': 'six branches and unavailable/unknown boundaries PASS'}
    shared.save(out / 'result.json', result)
    published = {}
    for path in sorted(out.iterdir()):
        evidence = publish_evidence(ctx, MaterialEvidenceWrite(experiment, 's001_audit_' + path.stem,
            path.read_bytes(), 'application/json' if path.suffix == '.json' else 'text/csv', path.suffix[1:]))
        published[path.name] = evidence.to_dict()
    shared.save(out / 'published.json', published)
    print(reference, 'PUBLISHED', sha256((out / 'result.json').read_bytes()).hexdigest(), flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
