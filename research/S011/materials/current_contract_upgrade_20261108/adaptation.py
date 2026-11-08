"""S011 current-equity target adapter; original causal signal math is unchanged."""
from pathlib import Path
import json
import shutil

from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
ORIGINAL_STRATEGIES = ROOT / 'strategies/revisions/S011-v1/f981c2b7dc9f5eed40c95d83067f991016b5fab39fe3d858ea53dd9f5745853a/strategies'


def build(version, candidate_id, output_root):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=False)
    frozen = ORIGINAL_STRATEGIES / 'S011/releases' / version / 'src/strategy_runtime'
    definition = json.loads((ORIGINAL_STRATEGIES / 'S011/versions' / (version + '.json')).read_bytes())['strategy_payload']['equity_definition']
    shutil.copyfile(frozen / 'signal_math.py', output_root / 'signal_math.py')
    shutil.copyfile(HERE / 'strategy.py', output_root / 'strategy.py')
    definition.pop('planning_context', None)
    definition.pop('initial_account', None)
    definition['analysis_price'] = 'HFQ'
    definition['auxiliary_inputs'] = [x for x in definition['auxiliary_inputs'] if x['name'] != 'hfq']
    definition['state_schema'] = {'account_fields': [], 'cycle_fields': []}
    parameters = json.loads(definition['parameters_json'])
    definition['execution_policy'] = {'policy_type': 'FROZEN_RULE', 'settings': {
        'capital': {'mode': 'target_equity_fraction', 'target_scope': 'decision', 'allocation_fraction': 1, 'fee_rate': .001},
        'entry': {'order_type': 'LIMIT', 'limit_parameter': parameters['premium']},
        'exit': {'order_type': 'MARKET', 'limit_ratio': .1},
        'instrument': {'lot_size': 100, 'maximum_order_quantity': 1000000, 'price_limit_ratio': .1, 'price_tick': .001}}}
    definition['source_files'] = ['signal_math.py', 'strategy.py']
    definition['source_sha256'] = equity_source_hash(output_root, tuple(definition['source_files']))
    return EquityStrategyCandidate('S011', candidate_id, EquityStrategyDefinition.from_dict(definition), output_root)
