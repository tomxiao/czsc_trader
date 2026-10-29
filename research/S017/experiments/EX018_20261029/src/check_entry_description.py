"""Boundary checks for actual-entry descriptions, independent of market data."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from describe_entries import describe
from run import WORK, save


def fixture(closed):
    start, middle, end = ('2019-01-02T15:00:00+00:00', '2019-01-02T15:30:00+00:00', '2019-01-02T16:00:00+00:00')
    def decision(identifier, at, finish, side, target, held):
        return dict(decision_id=identifier, decision_at=at, execution_start=at, execution_end=finish,
            side=side, target=target, explanation={'basis': [dict(key='held', text=str(held)),
                dict(key='close', text='100'), dict(key='exit_threshold', text='101')]})
    def order(identifier, decision_id, at, finish, side):
        return dict(order_id=identifier, decision_id=decision_id, status='FILLED', side=side,
                    quantity=1, valid_start=at, valid_end=finish)
    def fill(identifier, order_id, at, finish, side, price, fees):
        return dict(fill_id=identifier, order_id=order_id, cycle_id='c', interval_start=at,
                    interval_end=finish, side=side, quantity=1, price=price, fees=fees)
    decisions = [decision('d1', start, middle, 'BUY', 1, False)]
    orders = [order('o1', 'd1', start, middle, 'BUY')]
    fills = [fill('f1', 'o1', start, middle, 'BUY', 100.5, .1005)]
    trades = []
    equity, fees = 100001.3995, .1005
    if closed:
        decisions.append(decision('d2', middle, end, 'SELL', 0, True))
        orders.append(order('o2', 'd2', middle, end, 'SELL'))
        fills.append(fill('f2', 'o2', middle, end, 'SELL', 100., .1))
        trades.append(dict(cycle_id='c', status='CLOSED', entry_at=start, exit_at=end,
                           net_pnl=-.7005, net_return=-.7005 / 100.6005))
        equity, fees = 99999.2995, .2005
    return {'request': {'initial_cash': 100000.}, 'runs': {'candidate': {
        'decisions': decisions, 'orders': orders, 'fills': fills, 'trades': trades,
        'account_points': [dict(cycle_id=None if closed else 'c', quantity=0 if closed else 1,
                               close=102., equity=equity)],
        'metrics': {'closed_cycles': int(closed), 'fees': fees}}}}


def main():
    closed, opened = describe(fixture(True)), describe(fixture(False))
    assert closed['groups']['entry_at_or_below_existing_exit']['True']['closed_cycles'] == 1
    assert closed['groups']['exit_requested_at_first_held_decision']['True']['closed_cycles'] == 1
    row = closed['cycles'][0]
    assert row['actual_entry_price'] == 100.5 and row['entry_signal_close'] == 100.
    assert opened['groups']['exit_requested_at_first_held_decision']['UNOBSERVED']['open_cycles'] == 1
    assert opened['groups']['exit_requested_at_first_held_decision']['False']['open_cycles'] == 0
    bad = deepcopy(fixture(True))
    bad['runs']['candidate']['fills'][0]['interval_end'] = '2019-01-02T15:31:00+00:00'
    try:
        describe(bad)
    except ValueError as error:
        assert 'linkage' in str(error)
    else:
        raise AssertionError('mismatched fill interval accepted')
    save(WORK / 'others/entry_description_check.json', {'status': 'PASS',
        'checks': ['signal_and_execution_price_distinct', 'first_held_exit',
                   'unobserved_open_not_false', 'open_mark_reconciles', 'bad_fill_interval_rejected'],
        'source_sha256': sha256((WORK / 'src/describe_entries.py').read_bytes()).hexdigest(),
        'check_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest()})
    print('ENTRY_DESCRIPTION PASS 5 boundaries')


if __name__ == '__main__':
    main()
