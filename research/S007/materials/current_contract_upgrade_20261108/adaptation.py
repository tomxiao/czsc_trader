"""Adapt S007 signal-only V4, preserving its frozen financial mathematics."""
from copy import deepcopy
import json
from pathlib import Path

from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
from strategy_runtime.deployment import validate_release_integrity

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
ORIGINAL_RELEASE = '5f6e27be069ab4f70650e146161b69d63ef6ab3f44e4f3b96c8bc730ec2eb179'
ORIGINAL_ROOT = ROOT / 'strategies/revisions/S007-v1' / ORIGINAL_RELEASE / 'strategies'


def build(version, candidate_id, output_root):
    if version != 'v1':
        raise ValueError('S007 adaptation supports its reviewed v1 only')
    original = validate_release_integrity(ORIGINAL_ROOT, 'S007-v1')
    if original.release.release_hash != ORIGINAL_RELEASE:
        raise ValueError('S007 historical source identity differs')
    # Deepcopy a JSON document, not the recursively frozen public runtime mapping.
    frozen = json.loads((ORIGINAL_ROOT / 'S007/versions/v1.json').read_bytes())
    definition = frozen['strategy_payload']['equity_definition']
    if not definition.pop('planning_context', False):
        raise ValueError('expected pre-adaptation planning-context contract')
    params = json.loads(definition['parameters_json'])
    policy = deepcopy(params['rule']['execution'])
    if policy['entry']['limit_parameter'] != .01 or definition['execution_spec']['buy_premium'] != .01:
        raise ValueError('S007 authorized one-percent buy premium must remain unchanged')
    policy['capital'].update(mode='target_equity_fraction', target_scope='decision', allocation_fraction=1.)
    definition.update(analysis_price='HFQ', warmup_bars=21, auxiliary_inputs=[],
        state_schema={'account_fields': [], 'cycle_fields': []}, initial_account={'values': []},
        execution_policy={'policy_type': 'FROZEN_RULE', 'settings': policy},
        source_files=['signals.py', 'strategy.py'])
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=False)
    for name in ('signals.py', 'seed.csv'):
        (destination / name).write_bytes((original.source_root / name).read_bytes())
    (destination / 'strategy.py').write_bytes((HERE / 'strategy.py').read_bytes())
    definition['source_sha256'] = equity_source_hash(destination, tuple(definition['source_files']))
    return EquityStrategyCandidate('S007', candidate_id, EquityStrategyDefinition.from_dict(definition), destination)
