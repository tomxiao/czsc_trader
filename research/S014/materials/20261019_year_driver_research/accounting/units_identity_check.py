"""Existing account price/quantity declaration and inherited ret20 identity only."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()

def load(value):
    ref = EvidenceRef.from_dict(value)
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    return raw

def run(target):
    folder = ROOT / 'research/S014/experiments'
    record = json.loads((folder / 'EX023_20261018/others/account_results.json').read_bytes())['records'][0]
    account = json.loads(load(record['evidence']))
    source_path = folder / 'EX032_20261018/others/inputs.csv'
    h = sha256(source_path.read_bytes()).hexdigest()
    declared = json.loads((folder / 'EX032_20261018/others/result.json').read_bytes())['evidence']
    refs = [x for x in declared.values() if isinstance(x, dict) and x.get('sha256') == h]
    assert refs
    raw = load(refs[0])
    assert raw == source_path.read_bytes()
    old = pd.read_csv(BytesIO(raw))
    daily = pd.DataFrame(account['runs'][0]['ledgers']['account_daily']['data'])
    daily['date'] = pd.to_datetime(daily.date).dt.normalize()
    old['date'] = pd.to_datetime(old.date).dt.normalize()
    joint = daily[['date', 'close']].merge(old[['date', 'hfq_close_T', 'ret20']], on='date', validate='one_to_one')
    assert len(joint) == 1642
    pricing = account['request_identity']['pricing']
    assert pricing == {'anchor_date': '2019-12-31', 'anchor_factor': 5.892,
                       'basis': 'HFQ_RESEARCH', 'quantity_unit': 'RESEARCH_UNIT'}
    error = np.abs(joint.close - joint.hfq_close_T / pricing['anchor_factor'])
    assert error.max() < 1e-12
    ret20 = joint.close / joint.close.shift(20) - 1
    valid = ret20.notna() & joint.ret20.notna()
    difference = np.abs(ret20[valid] - joint.loc[valid, 'ret20'])
    assert valid.sum() == 1622 and difference.max() < 1e-12
    result = {'status': 'VERIFIED_EXISTING_UNITS_AND_RET20_IDENTITY',
              'account_evidence': record['evidence'], 'inherited_inputs_evidence': refs[0],
              'declared_pricing': pricing, 'price_rows': len(joint),
              'anchor_price_max_absolute_error': float(error.max()),
              'ret20_rows': int(valid.sum()), 'simple_ret20_max_absolute_error': float(difference.max()),
              'interpretation': ['Ledger prices are declared anchored HFQ research prices and quantities are research units; do not label ledger price directly as raw execution price.',
                                 'Ledger quantity times ledger price is the existing cash-unit exposure; support_floor uses unnormalized HFQ and must not be directly compared with ledger.close.',
                                 'Inherited ret20 is close/close_20_sessions_ago-1, a simple return, not a log return.',
                                 'These are identity checks only; no state-outcome grouping or new forward return labels.'],
              'new_fits': 0, 'new_return_labels': 0, 'new_accounts': 0, 'new_market_data_calls': 0}
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'sha256': sha256(target.read_bytes()).hexdigest()}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New file only')
    run(parser.parse_args().output)
