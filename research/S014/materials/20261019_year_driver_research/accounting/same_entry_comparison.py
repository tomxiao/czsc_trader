"""Read saved R/B/P trade sequences and fee units; no new labels or account replay."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()

def block(*args, **kwargs):
    raise RuntimeError('Network calls forbidden')

socket.socket.connect = block
socket.create_connection = block

def run(target):
    output = []
    for experiment, candidate, name in [('EX023_20261018', 'S014-C0056', 'R'),
                                        ('EX023_20261018', 'S014-C0034', 'B'),
                                        ('EX024_20261018', 'S014-C0057', 'P')]:
        index = ROOT / 'research/S014/experiments' / experiment / 'others/comparison_accounts.json'
        record = next(x for x in json.loads(index.read_bytes())['records'] if x['candidate'] == candidate)
        ref = EvidenceRef.from_dict(record['evidence'])
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        account = json.loads(raw)
        assert account['result_hash'] == record['result_hash'] and len(account['runs']) == 1
        run = account['runs'][0]
        trades = run['ledgers']['trades']['data']
        selected = [x for x in trades if ('2025-05-25' <= x['entry_date'][:10] <= '2025-06-30')
                    or ('2024-09-01' <= x['entry_date'][:10] <= '2024-10-31')]
        fills = [x for x in run['ledgers']['fills']['data'] if x['cycle_id'] in {t['cycle_id'] for t in selected}]
        for fill in fills:
            assert abs(fill['fees'] - fill['price'] * fill['quantity'] * .001) < 1e-7
        output.append({'candidate': candidate, 'variant': name, 'account_evidence': ref.to_dict(),
                       'result_hash': record['result_hash'], 'pricing': account['request_identity']['pricing'],
                       'trades': selected, 'fills': fills,
                       'june_orders': [x for x in run['ledgers']['orders']['data']
                                       if '2025-06-01' <= x['execution_date'][:10] <= '2025-06-30']})
    # Actual entries shared by all three accounts in the two described sequences.
    same_entry_dates = ['2024-09-13', '2024-10-09', '2024-10-24', '2025-05-30', '2025-06-19']
    for day in same_entry_dates:
        same = [next(x for x in account['trades'] if x['entry_date'][:10] == day) for account in output]
        assert max(x['entry_price'] for x in same) - min(x['entry_price'] for x in same) < 1e-12
    assert all(x['pricing'] == output[0]['pricing'] for x in output)
    report = {'status': 'EXISTING_SAME_ENTRY_AND_FEE_IDENTITY_VERIFIED', 'accounts': output,
              'common_entry_dates': same_entry_dates,
              'limits': ['Prices use account-declared HFQ_RESEARCH anchored at 2019-12-31, factor 5.892; quantities are RESEARCH_UNIT.',
                         'Same entry price, representation and fee rate do not imply identical quantity, capital or subsequent exit.',
                         'June 19 2025 late entry is common to R/B/P, not unique evidence against R reservation.',
                         'No removal-of-reservation counterfactual, new action outcome label or continuous account was constructed.',
                         'Selected episodes are already observed descriptive cases, not independent confirmation.'],
              'new_fits': 0, 'new_accounts': 0, 'new_return_labels': 0, 'new_market_data_calls': 0}
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'output': str(target), 'sha256': sha256(target.read_bytes()).hexdigest()}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New output file only, existing files are never overwritten')
    run(parser.parse_args().output)
