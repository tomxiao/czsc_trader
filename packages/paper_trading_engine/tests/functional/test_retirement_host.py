"""Retirement admission must stop strategy work and report asynchronous progress."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from threading import Thread
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from execution_channels.futu.account_retirement import AccountRetirementResult, AccountRetirementStatus
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.cli import _strategy_deployments
from paper_trading_engine.equity_runtime import EquityRuntimeAdviceClient
from paper_trading_engine.multichannel_runtime import MultiChannelRuntime
from paper_trading_engine.web import create_server


# Independent risk: PTE11; responsibility-level assertions.
@pytest.mark.parametrize('state', [
    'RETIRING',
], ids=['PTE11-C01'])
def test_inactive_accounts_never_load_or_prepare_strategy(state):
    account = {'account_id': 'old', 'run_state': state, 'channel_account_id': 'cn'}
    store = SimpleNamespace(virtual_account=lambda _: account)
    cycle = AccountStrategyCycle(None, None, store)
    with pytest.raises(ValueError, match='inactive'):
        cycle.run_latest('old', observed_at=datetime.now(timezone.utc))
    client = object.__new__(EquityRuntimeAdviceClient)
    client.store = store
    with pytest.raises(ValueError, match='inactive'):
        client._account_release('old')
    assert _strategy_deployments(None, [account]) == {}
    runtime = object.__new__(MultiChannelRuntime)
    runtime.store = store
    runtime.services = {'cn': SimpleNamespace(store=store)}
    with pytest.raises(ValueError, match='inactive'):
        runtime.drive_virtual_account_decision('old')
    with pytest.raises(ValueError, match='inactive'):
        runtime.resume_virtual('old')


# Independent risk: PTE11, PTE12; responsibility-level assertions.
@pytest.mark.parametrize('state,code', [
    (AccountRetirementStatus.WAITING_MARKET, 202),
], ids=['PTE11-C05'])
def test_retirement_http_reports_acceptance_separately_from_completion(state, code):
    result = AccountRetirementResult(state, 'one', Decimal('0'), 1, 100, 'waiting')
    operations = SimpleNamespace(system_status=lambda: {}, retire_account=lambda _: result)
    server = create_server(operations, port=0, control_token='token')
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f'http://127.0.0.1:{server.server_address[1]}/api/virtual-accounts/one/retire',
            data=json.dumps({'expected_release_hash': 'a' * 64, 'actor': 'test', 'reason': 'stop'}).encode(),
            headers={'Content-Type': 'application/json', 'X-PTE-Control-Token': 'token'},
        )
        with urlopen(request, timeout=10) as response:
            assert response.status == code
            assert json.load(response)['status'] == state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


# Independent risk: PTE11; responsibility-level assertions.
@pytest.mark.parametrize('market,timezone_name,symbol,segments,point,expected_start,expected_end', [
    ('CN', 'Asia/Shanghai', '510500.SH', [('09:30', '11:30'), ('13:00', '15:00')],
     '2026-11-27T12:00:00+08:00', '2026-11-27T13:00:00+08:00', '2026-11-27T15:00:00+08:00'),
    ('US', 'America/New_York', 'MU', [('09:30', '13:00')],
     '2026-11-27T12:00:00-05:00', '2026-11-27T09:30:00-05:00', '2026-11-27T13:00:00-05:00'),
], ids=['PTE11-C02', 'PTE11-C03'])
def test_retirement_calendar_uses_exchange_segments_and_actual_next_session(
        tmp_path, market, timezone_name, symbol, segments, point, expected_start, expected_end):
    import pandas as pd
    from paper_trading_engine.retirement_calendar import RetirementCalendar
    offset = '+08:00' if market == 'CN' else '-05:00'
    sessions = [{'session_date': day, 'timezone': timezone_name, 'segments': [
        {'start': f'{day}T{start}:00{offset}', 'end': f'{day}T{end}:00{offset}'}
        for start, end in periods]} for day, periods in [
            ('2026-11-27', segments), ('2026-11-30', [('09:30', '16:00' if market == 'US' else '15:00')])]]
    fetched = SimpleNamespace(ready=True, identity=SimpleNamespace(metadata={'sessions': sessions}),
        dataframe=pd.DataFrame({'SessionDate': ['2026-11-27', '2026-11-30'],
                                'AvailableDate': [datetime(2026, 1, 1, tzinfo=timezone.utc)] * 2}))
    calls = []
    def prepare(requests, **kwargs):
        calls.extend(requests)
        return SimpleNamespace(ready=True, reference='prepared')
    dataflows = SimpleNamespace(prepare=prepare, fetch=lambda *_, **__: fetched)
    (tmp_path / 'equity-sources.json').write_text(json.dumps({'schema_version': 2, 'sources': [{
        'market': market, 'provider': 'calendar', 'revision': 'v1',
        'adapter': 'TUSHARE_CN' if market == 'CN' else 'FUTU_US'}]}))
    store = SimpleNamespace(v4_runtime_binding=lambda _: None)
    calendar = RetirementCalendar(store, dataflows, tmp_path)
    account = {'account_id': 'old', 'channel_id': 'futu_simulate_cn' if market == 'CN' else 'futu_US_sim_channel',
               'asset_type': 'etf' if market == 'CN' else 'stock', 'symbol': symbol,
               'last_decision_payload': json.dumps({'fee_rate': '0.001'})}
    session = calendar.session(account, datetime.fromisoformat(point))
    assert session.interval.start == datetime.fromisoformat(expected_start)
    assert session.interval.end == datetime.fromisoformat(expected_end)
    assert session.fee_rate == Decimal('0.001')
    assert session.settlement_at == (datetime.fromisoformat('2026-11-30T09:30:00-05:00') if market == 'US' else None)
    assert len(calls) == 1


# Independent risk: PTE11; responsibility-level assertions.
def test_PTE11_C04_calendar_failure_clears_stale_session_without_stopping_reconciliation(tmp_path):
    from paper_trading_engine.multichannel_runtime import ChannelServices
    from paper_trading_engine.retirement_calendar import RetirementCalendar
    calls = []
    store = SimpleNamespace(
        strategy_virtual_accounts=lambda: [{'account_id': 'old', 'run_state': 'RETIRING', 'quantity': 100,
                                           'channel_id': 'futu_simulate_cn'}],
        v4_runtime_binding=lambda _: None,
        clear_retirement_session=lambda account: calls.append(('clear', account)),
        set_retirement_progress=lambda *args: calls.append(('blocked', args)),
    )
    execution = SimpleNamespace(set_retirement_session=lambda *_: pytest.fail('missing calendar'),
                                refresh_orders=lambda: calls.append(('orders',)),
                                submit_pending=lambda **_: calls.append(('pending',)))
    calendar = RetirementCalendar(store, None, tmp_path)
    services = ChannelServices(store, None, execution, None, None, calendar)
    services.refresh_orders()
    assert [item[0] for item in calls] == ['clear', 'blocked', 'orders', 'pending']
    assert calls[1][1][1] == AccountRetirementStatus.BLOCKED
    assert 'configured calendar source' in calls[1][1][2]


# Independent risk: PTE11; responsibility-level assertions.
