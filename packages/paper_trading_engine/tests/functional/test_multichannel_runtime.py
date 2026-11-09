from decimal import Decimal
from types import SimpleNamespace

import pytest

from execution_channels.futu.channel import ChannelAccountConfig, FUTU_US_SIM_CHANNEL_ID
from execution_channels.futu.channel_accounts import DEFAULT_CHANNEL_ACCOUNT
from paper_trading_engine.multichannel_runtime import (
    build_multichannel_runtime, MultiChannelRuntime, ChannelBatchError,
)


# Independent risk: PTE10; responsibility-level assertions.
def test_PTE10_C01_runtime_keeps_console_on_original_cn_scope(tmp_path, new_store):
    store = new_store(tmp_path/'db')
    store.register_channel_account(ChannelAccountConfig('us-test',FUTU_US_SIM_CHANNEL_ID,123),capital=Decimal('1000'))
    args = SimpleNamespace(repo_root=tmp_path, config_root=tmp_path, data_dir=tmp_path/'data', asset='etf',
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


# Independent risk: PTE10; responsibility-level assertions.
def test_PTE10_C02_runtime_batch_reports_failure_after_attempting_other_channels():
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


# Independent risk: PTE10; responsibility-level assertions.
def test_PTE10_C03_runtime_rejects_configuration_error_instead_of_reporting_unavailable(tmp_path, new_store):
    store = new_store(tmp_path/'db')
    args = SimpleNamespace(repo_root=tmp_path, config_root=tmp_path, data_dir=tmp_path/'data', asset='etf',
        symbol='588080.SH', opend_host='127.0.0.1',opend_port=11111,database=tmp_path/'db',runtime_identity={})
    def invalid(**kwargs):
        raise ValueError('invalid explicit configuration')
    try:
        with pytest.raises(ValueError, match='invalid explicit'):
            build_multichannel_runtime(args,store,None,gateway_factory=invalid)
    finally:
        store.close()
