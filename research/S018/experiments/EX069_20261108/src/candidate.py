"""Build the new candidate without modifying the frozen C9380 identity."""
from pathlib import Path
import json

from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash

ROOT = Path(__file__).resolve().parents[5]
SOURCE = Path(__file__).resolve().parent
CANDIDATE_ID = 'C9396'


def build_candidate():
    original = json.loads((ROOT/'strategies/S018/versions/v1.json').read_text(encoding='utf-8'))
    definition = original['strategy_payload']['equity_definition']
    definition['analysis_price'] = 'HFQ'
    definition['auxiliary_inputs'] = [x for x in definition['auxiliary_inputs'] if x['name'] == 'soxx_hfq']
    definition['auxiliary_inputs'][0]['source'] = {
        'provider': 'futu', 'revision': 's018-hfq-target-repack-20261108-v1'}
    definition['execution_policy'] = {'policy_type': 'TARGET_POSITION',
                                      'settings': {'capital_mode': 'target_equity_fraction'}}
    definition['source_sha256'] = equity_source_hash(SOURCE, ('strategy.py',))
    definition['state_schema'] = {'account_fields': [], 'cycle_fields': [
        {'key': key, 'value_type': kind, 'nullable': False} for key, kind in (
            ('anchor', 'float'), ('sector_anchor', 'float'), ('allocation', 'float'),
            ('promoted', 'bool'), ('exiting', 'bool'))]}
    return EquityStrategyCandidate('S018', CANDIDATE_ID,
                                   EquityStrategyDefinition.from_dict(definition), SOURCE)
