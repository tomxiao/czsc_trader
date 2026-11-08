"""Build an approved frozen signal on current HFQ/target-weight V4 contracts."""
from copy import deepcopy
import json
from pathlib import Path
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
from strategy_runtime.deployment import validate_release_integrity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FAMILY = HERE.parents[1].name
ORIGINAL_ROOTS = {
    'v1': ROOT / 'strategies/revisions/S001-v1/4d6d0d1c23a0d526e3b016d82bf0d0cbf0aadb3a25948cd5041494a5c0c62583/strategies',
    'v2': ROOT / 'strategies/revisions/S001-v2/a8e5059f8e81eb322ca288d239bab5812e87f31a9d12014fc157211b36e6c7cd/strategies',
}


def build(version, candidate_id, output_root):
    if version not in ({'v1', 'v2'} if FAMILY == 'S001' else {'v1'}):
        raise ValueError('unsupported frozen version')
    original_root = ORIGINAL_ROOTS[version]
    original = validate_release_integrity(original_root, f'{FAMILY}-{version}')
    raw = json.loads((original_root / FAMILY / 'versions' / f'{version}.json').read_bytes())
    definition = deepcopy(raw['strategy_payload']['equity_definition'])
    output = Path(output_root).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('candidate source must remain inside the repository')
    output.mkdir(parents=True, exist_ok=False)
    for name, data in (
        ('signal_math.py', (original.source_root / 'signal_math.py').read_bytes()),
        ('strategy.py', (HERE / 'strategy.py').read_bytes()),
    ):
        (output / name).write_bytes(data)
    files = ('signal_math.py', 'strategy.py')
    definition.pop('planning_context', None)
    definition.pop('initial_account', None)
    definition['analysis_price'] = 'HFQ'
    definition['source_files'] = list(files)
    definition['source_sha256'] = equity_source_hash(output, files)
    definition['state_schema'] = {'account_fields': [], 'cycle_fields': []}
    execution = deepcopy(json.loads(definition['parameters_json'])['rule']['execution'])
    execution['capital'].update(mode='target_equity_fraction', target_scope='decision', allocation_fraction=1)
    definition['execution_policy'] = {'policy_type': 'FROZEN_RULE', 'settings': execution}
    candidate = EquityStrategyCandidate(FAMILY, candidate_id, EquityStrategyDefinition.from_dict(definition), output)
    candidate.verify()
    return candidate
