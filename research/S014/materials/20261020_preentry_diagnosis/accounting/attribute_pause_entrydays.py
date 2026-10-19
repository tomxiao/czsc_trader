"""Own-population actual entry/hold/sell/fee yearly wealth bridge, 2020-25."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX046_20261020'
CHECKS = Counter()
MAX_ERROR = 0.


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def equal(name, actual, expected):
    global MAX_ERROR
    error = abs(actual - expected)
    MAX_ERROR = max(MAX_ERROR, error)
    check(name, error <= 1e-7)


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    output = []
    sources = []
    for index in range(3):
        receipt = json.loads((EX / f'others/accounts/run-{index:03d}.json').read_bytes())
        report = json.loads((OUT / f'pause_account_{index:03d}_independent_review.json').read_bytes())
        evidence = EvidenceRef.from_dict(receipt['evidence'])
        content = evidence.resolve(ROOT).read_bytes()
        check('formal exact successfully audited own account', sha256(content).hexdigest() == evidence.sha256 and report['status'] == 'PASS' and report['account_ref'] == receipt['evidence'])
        account = json.loads(content)
        profile = receipt['parameters']['pause_profile']
        ledgers = account['runs'][0]['ledgers']
        daily = [r for r in ledgers['account_daily']['data'] if r['date'][:10] <= '2025-12-31']
        fills = {r['fill_time'][:10]: r for r in ledgers['fills']['data'] if r['fill_time'][:10] <= '2025-12-31'}
        check('same1455 economic dates per own policy', len(daily) == 1455)
        groups = defaultdict(lambda: defaultdict(float))
        previous_wealth, previous_close = 100000., None
        for row in daily:
            E = row['date'][:10]
            year = int(E[:4])
            group = groups[year]
            if 'opening_equity' not in group:
                group['opening_equity'] = previous_wealth
            entry = holding = sale = buy_fee = sell_fee = 0.
            fill = fills.get(E)
            if fill and fill['side'] == 'BUY':
                check('entry from own actual flat capital', row['quantity_before'] == 0 and row['quantity'] == fill['quantity'])
                entry = fill['quantity'] * (row['close'] - fill['price'])
                buy_fee = fill['fees']
                group['actual_entry_count'] += 1
            elif fill:
                check('actual original inventory sale', fill['side'] == 'SELL' and row['quantity_before'] == fill['quantity'] and row['quantity'] == 0)
                sale = fill['quantity'] * (fill['price'] - previous_close)
                sell_fee = fill['fees']
                group['actual_exit_count'] += 1
            elif row['quantity_before']:
                holding = row['quantity_before'] * (row['close'] - previous_close)
            net = entry + holding + sale - buy_fee - sell_fee
            equal('daily actual phase and fees wealth bridge', net, row['equity'] - previous_wealth)
            for key, value in [('entryday_gross', entry), ('entry_BUYfees', buy_fee), ('entryday_net', entry - buy_fee),
                               ('continued_hold_gross', holding), ('exit_to_actual_fill_gross', sale), ('exit_SELLfees', sell_fee),
                               ('postentry_residual_net', holding + sale - sell_fee), ('year_net_pnl', net)]:
                group[key] += value
            group['closing_equity'] = row['equity']
            previous_wealth, previous_close = row['equity'], row['close']
        annual = {r['year']: r for r in report['original_annual_goal_audit']}
        for year, values in groups.items():
            equal('annual net money exact bridge', values['entryday_net'] + values['postentry_residual_net'], values['closing_equity'] - values['opening_equity'])
            equal('own year opening existing independent audit', values['opening_equity'], annual[year]['opening_equity'])
            equal('own year closing existing independent audit', values['closing_equity'], annual[year]['closing_equity'])
            result = {'pause_profile': profile, 'year': year, **values}
            for key in ['entryday_gross', 'entry_BUYfees', 'entryday_net', 'continued_hold_gross', 'exit_to_actual_fill_gross', 'exit_SELLfees', 'postentry_residual_net', 'year_net_pnl']:
                result[key + '_annual_contribution_pp'] = 100 * values[key] / values['opening_equity']
            output.append(result)
        sources.append({'pause_profile': profile, 'account_ref': receipt['evidence'], 'result_hash': receipt['result_hash'], 'independent_audit': ref(OUT / f'pause_account_{index:03d}_independent_review.json')})
    base = {r['year']: r for r in output if r['pause_profile'] == 'BASE'}
    for row in output:
        original = base[row['year']]
        for key in ['entryday_net', 'postentry_residual_net', 'year_net_pnl']:
            row['difference_vs_BASE_' + key + '_pp'] = row[key + '_annual_contribution_pp'] - original[key + '_annual_contribution_pp']
        equal('crosspolicy annual difference partition', row['difference_vs_BASE_entryday_net_pp'] + row['difference_vs_BASE_postentry_residual_net_pp'], row['difference_vs_BASE_year_net_pnl_pp'])
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(output[0]))
    writer.writeheader()
    writer.writerows(output)
    destination = OUT / 'pause_entryday_yearly_attribution.csv'
    with destination.open('xb') as target:
        target.write(stream.getvalue().encode('utf-8'))
    report = {'status': 'PASS', 'output': {**ref(destination), 'rows': len(output)}, 'sources': sources,
              'implementation': ref(Path(__file__).resolve()), 'checks': dict(CHECKS), 'check_count': sum(CHECKS.values()), 'max_money_bridge_error': MAX_ERROR,
              'definitions': {'actual_entryday_net': 'Actual quantity*(E ledger Close - actual BUY fill)-actual BUYfee, E belongs to its natural year.',
                              'postentry_residual_net': 'Actual no-fill-held close-to-close marks + SELLfill-prevledgerClose marks - actual SELLfees. Includes calendar-year carry correctly.',
                              'annual_pp': 'Each own policy uses its own actual year-opening equity.',
                              'difference_partition': 'Entryday net contribution difference + residual net contribution difference = annual return difference. Accounting attribution, not a causal intervention decomposition.'},
              'no_counterfactual_labels': True, 'new_accounts': 0, 'fits': 0, 'market_calls': 0, 'scope': '2020-25; no2026 outcome selection'}
    report_path = OUT / 'pause_entryday_attribution_review.json'
    with report_path.open('x', encoding='utf-8', newline='\n') as target:
        json.dump(report, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({'review': ref(report_path), 'output': ref(destination), 'checks': report['check_count'], '2024': [r for r in output if r['year'] == 2024]}))


if __name__ == '__main__':
    main()
