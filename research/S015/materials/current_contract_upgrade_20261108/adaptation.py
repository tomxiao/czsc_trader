"""S015 HFQ-only adapter; preserve the center/repair signal and allocation."""
from pathlib import Path
import json
import shutil

from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
ORIGINAL_STRATEGIES = ROOT / 'strategies/revisions/S015-v1/92f1f09d87e8e1b871f786d3433278e32c6b9c2779bceab11c1cc767b14421d1/strategies'


def build(version, candidate_id, output_root):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=False)
    frozen = ORIGINAL_STRATEGIES / 'S015/releases' / version / 'src/strategy_runtime'
    definition = json.loads((ORIGINAL_STRATEGIES / 'S015/versions' / (version + '.json')).read_bytes())['strategy_payload']['equity_definition']
    source = (frozen / 'signal_math.py').read_text(encoding='utf-8')
    replacements = {
        'def causal_features(market, execution, intraday,': 'def causal_features(market, intraday,',
        '(("market", market), ("execution", execution), ("intraday", intraday))': '(("market", market), ("intraday", intraday))',
        'adj, raw, bars = frames': 'adj, bars = frames',
        'not adj.Date.equals(raw.Date)\n        or len(adj) < 75': 'len(adj) < 75',
        'centers.append(center + float(np.log(adj.Close.iloc[pos + 75] / raw.Close.iloc[pos + 75])))': 'centers.append(center)',
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise ValueError('original S015 source differs from reviewed adaptation: ' + old)
        source = source.replace(old, new)
    (output_root / 'signal_math.py').write_text(source, encoding='utf-8', newline='\n')
    shutil.copyfile(HERE / 'strategy.py', output_root / 'strategy.py')
    definition.pop('planning_context', None)
    definition.pop('initial_account', None)
    definition['analysis_price'] = 'HFQ'
    definition['auxiliary_inputs'] = [dict(x, analysis_price='HFQ') for x in definition['auxiliary_inputs'] if x['name'] != 'hfq']
    definition['state_schema'] = {'account_fields': [], 'cycle_fields': []}
    definition['execution_policy'] = {'policy_type': 'FROZEN_RULE', 'settings': {
        'capital': {'mode': 'target_equity_fraction', 'target_scope': 'decision', 'allocation_fraction': 1, 'fee_rate': .001},
        'entry': {'order_type': 'LIMIT', 'limit_parameter': .01},
        'exit': {'order_type': 'MARKET', 'limit_ratio': .1},
        'instrument': {'lot_size': 100, 'maximum_order_quantity': 1000000, 'price_limit_ratio': .1, 'price_tick': .001}}}
    definition['source_files'] = ['signal_math.py', 'strategy.py']
    definition['source_sha256'] = equity_source_hash(output_root, tuple(definition['source_files']))
    return EquityStrategyCandidate('S015', candidate_id, EquityStrategyDefinition.from_dict(definition), output_root)
