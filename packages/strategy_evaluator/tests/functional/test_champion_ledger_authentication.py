"""SE authenticates champion statistics against a complete two-fill ledger."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from strategy_evaluator import (
    AuditStatus, ReplayEvidence, audit_provisional_champion, audit_replay,
    hash_audit_data, hash_execution_evidence, hash_return_matrix,
)
from test_strategy_evaluator import _complete_audit_request


def _request():
    # Independent fixed synthetic evidence, originally obtained from a valid TXE
    # buy/sell replay. It requires neither TDR nor Dataflows to audit in SE.
    execution = _replay()
    execution = replace(execution, content_hash=hash_execution_evidence(execution))
    assert audit_replay(execution).status is AuditStatus.PASS
    original = _complete_audit_request()
    equity = np.asarray([row['equity'] for row in execution.account_daily])
    returns = equity / np.concatenate(([execution.initial_cash], equity[:-1])) - 1
    matrices = []
    for matrix in (original.search_returns, original.comparison_returns):
        index = matrix.candidate_ids.index(original.champion_id)
        values = np.asarray(matrix.returns).copy()
        values[:, index] = returns
        changed = replace(matrix, dates=execution.evaluation_sessions,
            returns=tuple(tuple(map(float, row)) for row in values))
        matrices.append(replace(changed, content_hash=hash_return_matrix(changed)))
    search, comparison = matrices
    return replace(original, execution=execution, search_returns=search,
        comparison_returns=comparison, identity=replace(original.identity,
        data_hash=hash_audit_data(search, comparison)))


@pytest.mark.parametrize('corruption', ['authenticated_returns', 'fill_fees'])
def test_public_champion_audit_rejects_ledger_inconsistency(corruption):
    request = _request()
    assert audit_provisional_champion(request).status is AuditStatus.PASS
    if corruption == 'authenticated_returns':
        comparison = request.comparison_returns
        values = [list(row) for row in comparison.returns]
        values[0][comparison.candidate_ids.index(request.champion_id)] += .01
        changed = replace(comparison, returns=tuple(tuple(row) for row in values))
        changed = replace(changed, content_hash=hash_return_matrix(changed))
        request = replace(request, comparison_returns=changed,
            identity=replace(request.identity, data_hash=hash_audit_data(request.search_returns, changed)))
        result = audit_provisional_champion(request)
        assert result.status is AuditStatus.INSUFFICIENT
        assert result.reason_codes == ('CHAMPION_LEDGER_RETURN_MISMATCH',)
    else:
        execution = request.execution
        execution = replace(execution, fills=({**execution.fills[0], 'fees': 999.}, *execution.fills[1:]))
        execution = replace(execution, content_hash=hash_execution_evidence(execution))
        result = audit_provisional_champion(replace(request, execution=execution))
        assert result.status is AuditStatus.FAIL
        finding = next(item for item in result.findings if item.audit_id == 'execution')
        assert finding.status is AuditStatus.FAIL
        assert 'FEE_MISMATCH' in finding.reason_codes


def _replay():
    """A fixed complete ledger: buy 99,900 at 1, then sell at 1; each fee is 99.9."""
    dates = tuple(str(day.date()) for day in pd.bdate_range('2026-09-15', periods=30))
    previous = ('2026-09-14', *dates[:-1])
    target = (0., 1., 1., *([0.] * 27))
    decisions = tuple(dict(decision_id=f'd{i}', signal_date=before, valid_session=day,
        target_position=target[i], plan_mode='NONE', action=('BUY' if i == 1 else 'SELL' if i == 3 else 'HOLD'))
        for i, (before, day) in enumerate(zip(previous, dates)))
    orders = tuple(dict(order_id=side, decision_id=f'd{i}', cycle_id='roundtrip',
        signal_date=previous[i], execution_date=dates[i], side=side.upper(), quantity=99900,
        order_type=kind, limit_price=1., status='FILLED')
        for side, i, kind in (('buy', 1, 'LIMIT'), ('sell', 3, 'MARKET')))
    fills = tuple(dict(fill_id=order['order_id']+'fill', order_id=order['order_id'],
        decision_id=order['decision_id'], cycle_id='roundtrip', signal_date=order['signal_date'],
        fill_time=order['execution_date'], side=order['side'], quantity=99900, price=1., fees=99.9,
        trigger='OPEN' if order['side']=='BUY' else 'OPEN_MARKET') for order in orders)
    cash = (100000., .10000000000582077, .10000000000582077, *([99800.20000000001] * 27))
    quantity = (0, 99900, 99900, *([0] * 27))
    account = tuple(dict(date=day, signal_date=previous[i], target_position=target[i],
        cash_before=100000. if i==0 else cash[i-1], quantity_before=0 if i==0 else quantity[i-1],
        cash=cash[i], quantity=quantity[i], close=1., equity=cash[i]+quantity[i])
        for i, day in enumerate(dates))
    trades = (dict(cycle_id='roundtrip', status='CLOSED', entry_date=dates[1], exit_date=dates[3],
        quantity=99900, entry_price=1., exit_price=1., net_return=-.0019980019980019303),)
    return ReplayEvidence('a'*64, 'b'*64, 100000., dates,
        {'decision_coverage': 'COMPLETE', 'entry_limit_parameter': 0., 'exit_limit_ratio': .1,
         'entry_order_type': 'LIMIT', 'exit_order_type': 'MARKET', 'fee_rate': .001,
         'capital_mode': 'full_available_cash', 'allocation_fraction': 1.,
         'instrument': {'lot_size': 100, 'price_tick': .001, 'price_limit_ratio': .1,
                        'maximum_order_quantity': 1000000}},
        decisions, orders, fills, account, trades,
        {'max_drawdown': -.0019979999999998332, 'calmar': -8.338166133149992,
         'win_loss_ratio': None, 'win_loss_ratio_status': 'NO_WINS',
         'return': -.0019979999999998332, 'sharpe': -4.171330164821948,
         'closed_trades': 1, 'win_rate': 0.},
        tuple(dict(date=day, open=1., close=1.) for day in ('2026-09-14', *dates)), ())
