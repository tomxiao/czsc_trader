"""Short synthetic signal/fill paths only; never load a retained account."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from anchor_diagnosis_v2 import CATEGORIES, diagnose_account, price_category


def fixture(actions=None, execution_dates=None):
    actions = actions or [('entry', 'bear', 100.), ('time', 'bear', 99.),
        ('entry_direction_rejected', 'bear', 99.), ('flat', 'bull', 100.),
        ('entry', 'bull', 101.), ('time', 'bull', 102.),
        ('entry', 'bear', 100.), ('time', 'bear', 100.),
        ('confirmation_rejected', 'bear', 101.), ('entry', 'bear', 102.),
        ('time', 'bear', 103.), ('flat', 'bear', 103.),
        ('entry_direction_rejected', 'bear', 102.), ('entry', 'bear', 104.), ('hold', 'bear', 104.)]
    valid = pd.bdate_range('2020-12-21', periods=len(actions)) if execution_dates is None else execution_dates
    dates = pd.DatetimeIndex([valid[0] - pd.offsets.BDay(1), *valid[:-1]])
    records, fills, accounts, cycle_statuses = [], [], [], {}
    holding, route, age, previous, actual_quantity, cycle = False, None, 0, 100., 0, 0
    cash = 1_000_000.
    for i, (reason, raw_route, close) in enumerate(actions):
        entry = reason == 'entry'
        opportunity = not holding and reason != 'flat'
        score_pass = reason != 'confirmation_rejected'
        record = {'raw_route': raw_route, 'active_route': route if holding else raw_route,
            'holding_before': holding, 'route_before': route, 'age_before': age if holding else 0,
            'eligible': reason != 'flat', 'opportunity': opportunity, 'score_pass': score_pass,
            'entry': entry, 'signal_reason': reason, 'valid_session': valid[i],
            'signal_close': close, 'signal_open': close, 'previous_signal_close': previous,
            'close_up': close > previous, 'body_up': False}
        if holding:
            age += 1
            if reason != 'hold':
                holding, route = False, None
        elif entry:
            holding, route, age = True, raw_route, 0
        record['target'] = float(holding)
        records.append(record)
        mark = close + .5
        if entry:
            cycle += 1
            quantity, price, side = 100, mark + .1, 'BUY'
            actual_quantity += quantity
            cash -= quantity * price + 1.
            cycle_statuses[cycle] = 'OPEN'
        elif reason in ('time', 'range', 'loss', 'trailing', 'regime'):
            quantity, price, side = actual_quantity, mark - .1, 'SELL'
            actual_quantity = 0
            cash += quantity * price - 1.
            cycle_statuses[cycle] = 'CLOSED'
        else:
            side = None
        if side:
            fills.append({'fill_id': f'f-{i}', 'cycle_id': cycle, 'decision_id': f'd-{i}',
                'side': side, 'quantity': quantity, 'price': price, 'fees': 1.,
                'fill_time': valid[i] + pd.Timedelta(hours=15), 'signal_date': dates[i]})
        accounts.append({'date': valid[i], 'quantity': actual_quantity, 'cash': cash,
                         'close': mark, 'equity': cash + actual_quantity * mark})
        previous = close
    values = pd.DataFrame(records, index=dates)
    values['route_before'] = pd.Series([record['route_before'] for record in records], index=dates, dtype=object)
    decisions = pd.DataFrame({'decision_id': [f'd-{i}' for i in range(len(records))],
        'signal_date': dates, 'valid_session': valid, 'signal_reason': [row['signal_reason'] for row in records],
        'target_position': [row['target'] for row in records]})
    execution = SimpleNamespace(decisions=decisions,
        account_daily=pd.DataFrame(accounts),
        fills=pd.DataFrame(fills, columns=('fill_id', 'cycle_id', 'decision_id', 'side', 'quantity',
                                        'price', 'fees', 'fill_time', 'signal_date')),
        trades=pd.DataFrame([{'cycle_id': key, 'status': value} for key, value in cycle_statuses.items()],
                            columns=('cycle_id', 'status')))
    return values, execution


def main():
    values, execution = fixture()
    result = diagnose_account(values, execution)
    assert result['summary']['bear_time_categories'] == {'BELOW': 1, 'EQUAL': 1, 'ABOVE': 1, 'NONE': 0}
    assert result['summary']['all_time_exits'] == 4
    days = result['all_native_days']
    assert [days[i]['pre_context'] for i in (2, 3, 4)] == ['BELOW'] * 3
    assert days[4]['holding_source_context_after'] == 'BELOW' and days[4]['post_context'] == 'NONE'
    assert days[5]['holding_source_context_before'] == 'BELOW'
    assert days[6]['pre_context'] == 'NONE'
    assert days[8]['pre_context'] == days[9]['pre_context'] == 'EQUAL'
    assert days[9]['post_context'] == 'NONE'
    assert days[11]['pre_context'] == days[12]['pre_context'] == days[13]['pre_context'] == 'ABOVE'
    assert result['summary']['signal_tail']['holding'] and result['summary']['signal_tail']['route'] == 'bear'
    assert result['summary']['signal_tail']['entry_anchor_signal_close'] == 104.
    below = result['exit_events'][0]
    assert below['next_any_entry']['raw_route'] == 'bull' and below['next_any_entry']['signal_index'] == 4
    assert below['next_bear_opportunity']['signal_index'] == 2
    assert below['next_direction_rejection']['signal_index'] == 2
    assert len(result['cycles']) == 5 and result['cycles'][-1]['status'] == 'OPEN'
    assert [cycle['source_category'] for cycle in result['cycles']] == ['NONE', 'BELOW', 'NONE', 'EQUAL', 'ABOVE']
    assert result['summary']['actual_buy_fill_source_disagreements'] == 0
    assert {year['year'] for year in result['annual_cash']} == {'ALL', '2020', '2021'}
    for year in result['annual_cash']:
        assert [group['category'] for group in year['groups']] == list(CATEGORIES)
        for key in ('pre_context_net_equity_change', 'holding_source_net_equity_change'):
            assert abs(sum(group[key] for group in year['groups']) - year['net_equity_change']) < 1e-6
        for key in ('pre_context_fees', 'holding_source_fees'):
            assert abs(sum(group[key] for group in year['groups']) - year['fees']) < 1e-6
    assert len(result['all_execution_days']) == len(values)
    # The comparison is strict: no epsilon merges distinct floating prices.
    assert price_category(np.nextafter(100., -np.inf), 100.) == 'BELOW'
    assert price_category(100., 100.) == 'EQUAL'
    assert price_category(np.nextafter(100., np.inf), 100.) == 'ABOVE'
    # Endpoint exits lack future entry explicitly; do not discard them.
    short_values, short_execution = fixture([('entry', 'bear', 100.), ('time', 'bear', 99.)])
    short = diagnose_account(short_values, short_execution)
    assert short['exit_events'][0]['next_any_entry'] is None
    assert short['exit_events'][0]['next_bear_opportunity'] is None
    assert short['exit_events'][0]['no_subsequent_entry']
    assert short['summary']['signal_tail']['unconsumed_exit_context'] == 'BELOW'
    # No trades/no exits still retains every day/year/category with finite zero cash totals.
    flat_values, flat_execution = fixture([('flat', 'bear', 100.), ('flat', 'bull', 100.)])
    flat = diagnose_account(flat_values, flat_execution)
    assert not flat['cycles'] and not flat['exit_events']
    assert flat['annual_cash'][0]['net_equity_change'] == 0.
    # A 2019 signal attached to a2020 valid session belongs to different time axes.
    v, e = fixture([('entry', 'bear', 100.), ('time', 'bear', 99.)], pd.bdate_range('2020-01-01', periods=2))
    crossed = diagnose_account(v, e)
    assert {row['year'] for row in crossed['statistics']} == {'ALL', '2019', '2020'}
    assert {row['year'] for row in crossed['annual_cash']} == {'ALL', '2020'}
    rejected = 0
    for name, bad_value in (('holding_before', True), ('route_before', 'bear'), ('age_before', 1),
                            ('target', np.nan), ('signal_close', np.nan), ('signal_open', np.inf),
                            ('previous_signal_close', 0.), ('close_up', True)):
        broken = values.copy()
        broken.loc[broken.index[0], name] = bad_value
        try:
            diagnose_account(broken, execution)
        except (AssertionError, ValueError):
            rejected += 1
        else:
            raise AssertionError('Invalid state/price accepted: ' + name)
    altered = SimpleNamespace(**vars(execution))
    altered.account_daily = execution.account_daily.copy()
    altered.account_daily.loc[2, 'equity'] += 10.
    try:
        diagnose_account(values, altered)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError('Broken cash ledger accepted')
    broken = values.astype({'score_pass': object}).copy()
    broken.loc[broken.index[0], 'score_pass'] = np.nan
    try:
        diagnose_account(broken, execution)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError('Nonboolean certified predicate accepted')
    json.dumps(result, allow_nan=False)
    outcome = {'status': 'PURE_PASS', 'new_account_evaluations': 0, 'retained_account_reads': 0,
        'checks': {'full_signal_and_cash_days': len(values), 'bear_time_sign_categories': 3,
                   'cash_years_plus_ALL': len(result['annual_cash']), 'actual_cycles_including_OPEN': len(result['cycles']),
                   'endpoint_paths': 2, 'signal_vs_execution_years': 1, 'invalid_state_price_cash_rejections': rejected},
        'source_sha256': hashlib.sha256(Path(__file__).with_name('anchor_diagnosis_v2.py').read_bytes()).hexdigest()}
    target = Path('.tmp/ex042-diagnosis/focused_v2.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(outcome, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(outcome, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
