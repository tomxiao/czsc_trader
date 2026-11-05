from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from paper_trading_engine.channel import ChannelAccountConfig, FUTU_US_SIM_CHANNEL_ID
from paper_trading_engine.channel_accounts import DEFAULT_CHANNEL_ACCOUNT
from paper_trading_engine.cli import main
from paper_trading_engine.multichannel_runtime import build_multichannel_runtime, MultiChannelRuntime, ChannelBatchError
from paper_trading_engine.store import PaperStore


def test_cli_register_and_read_scoped_status_without_broker(tmp_path, capsys):
    definition = tmp_path / 'channel.json'
    definition.write_text(json.dumps({
        'account': {'channel_account_id':'us-test', 'channel_id':FUTU_US_SIM_CHANNEL_ID,
                    'broker_account_id':123, 'session':'RTH'}, 'capital':'1000',
        'fee_policy': {'max_variable_rate':'0.01', 'max_fixed_fee_per_order':'5', 'rounding_tolerance':'0.01'},
    }))
    database = tmp_path / 'runtime.db'
    common = ['--repo-root',str(tmp_path),'--database',str(database)]
    assert main(['channel','register',*common,'--definition',str(definition)]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered['result']['registered']
    assert main(['channel','status',*common,'--channel-account-id','us-test']) == 0
    status = json.loads(capsys.readouterr().out)['result']
    assert status['currency'] == 'USD'
    assert status['capital_pool']['registered_capital'] == '1000'
    assert status['source'] == 'PERSISTED_SNAPSHOT'
    assert len(status['accounts']) == 1  # only its zero-balance reconciliation account
    assert status['accounts'][0]['channel_id'] == FUTU_US_SIM_CHANNEL_ID
    assert main(['channel','register',*common,'--definition',str(definition)]) == 0


def test_cli_rejects_changed_fee_policy_atomically(tmp_path, capsys):
    path = tmp_path / 'definition.json'
    payload = {'account': {'channel_account_id':'us-test','channel_id':FUTU_US_SIM_CHANNEL_ID,
                          'broker_account_id':123,'session':'RTH'}, 'capital':'1000',
               'fee_policy': {'max_variable_rate':'0.01','max_fixed_fee_per_order':'5','rounding_tolerance':'0.01'}}
    path.write_text(json.dumps(payload))
    args = ['channel','register','--repo-root',str(tmp_path),'--database',str(tmp_path/'db'), '--definition',str(path)]
    assert main(args) == 0
    capsys.readouterr()
    payload['fee_policy']['max_fixed_fee_per_order'] = '500'
    path.write_text(json.dumps(payload))
    assert main(args) != 0
    store = PaperStore(tmp_path/'db')
    try:
        scoped = store.scope('us-test')
        assert json.loads(scoped.get_setting('fee_reconciliation_policy'))['max_fixed_fee_per_order'] == '5'
        with pytest.raises(KeyError):
            store.scope('unregistered')
    finally:
        store.close()


def test_runtime_keeps_console_on_original_cn_scope(tmp_path):
    store = PaperStore(tmp_path/'db')
    store.register_channel_account(ChannelAccountConfig('us-test',FUTU_US_SIM_CHANNEL_ID,123),capital=Decimal('1000'))
    args = SimpleNamespace(repo_root=tmp_path, data_dir=tmp_path/'data', asset='etf',
        symbol='588080.SH', opend_host='127.0.0.1',opend_port=11111,database=tmp_path/'db',runtime_identity={'mode':'DEV'})
    attempts = []
    def unavailable(**kwargs):
        attempts.append(kwargs['config'])
        raise ConnectionError('offline fixture')
    runtime = build_multichannel_runtime(args,store,None,gateway_factory=unavailable)
    try:
        assert runtime.console_view.store.channel_account_id == DEFAULT_CHANNEL_ACCOUNT
        assert set(runtime.channel_operations) == {DEFAULT_CHANNEL_ACCOUNT,'us-test'}
        assert runtime.status()['channels']['us-test']['market'] == 'US'
        assert runtime.status()['channels']['us-test']['currency'] == 'USD'
        assert len(attempts) == 2
        with pytest.raises(ValueError,match='cannot cross'):
            runtime.console_view.store.scope('us-test')
    finally:
        runtime.close()


def test_runtime_batch_reports_failure_after_attempting_other_channels():
    calls = []
    def fail():
        calls.append('cn')
        raise RuntimeError('unavailable')
    def succeed():
        calls.append('us')
        return {'status':'OK'}
    runtime = object.__new__(MultiChannelRuntime)
    runtime.services = {'cn':SimpleNamespace(refresh_account=fail),'us':SimpleNamespace(refresh_account=succeed)}
    with pytest.raises(ChannelBatchError,match='unavailable'):
        runtime.refresh_account()
    assert calls == ['cn','us']


def test_runtime_rejects_configuration_error_instead_of_reporting_unavailable(tmp_path):
    store = PaperStore(tmp_path/'db')
    args = SimpleNamespace(repo_root=tmp_path, data_dir=tmp_path/'data', asset='etf',
        symbol='588080.SH', opend_host='127.0.0.1',opend_port=11111,database=tmp_path/'db',runtime_identity={})
    def invalid(**kwargs):
        raise ValueError('invalid explicit configuration')
    try:
        with pytest.raises(ValueError, match='invalid explicit'):
            build_multichannel_runtime(args,store,None,gateway_factory=invalid)
    finally:
        store.close()


def test_old_account_cli_cannot_pause_foreign_channel_account(tmp_path, capsys):
    database = tmp_path/'db'
    store = PaperStore(database)
    config = ChannelAccountConfig('us-test', FUTU_US_SIM_CHANNEL_ID, 123)
    scoped = store.register_channel_account(config, capital=Decimal('1000'))
    account = scoped.create_channel_reconciliation_account()
    store.close()
    assert main(['account','pause','--repo-root',str(tmp_path),'--database',str(database),
                 '--account-id',account['account_id']]) != 0
    assert 'another channel account' in capsys.readouterr().out
