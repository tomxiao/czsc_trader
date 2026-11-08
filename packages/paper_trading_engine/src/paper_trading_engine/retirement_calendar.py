"""Prepare execution-only calendar facts without importing a frozen strategy."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from dataflows import AssetClass, EquityDataRequest, EquityProduct, EquityQuery, InstrumentId, MarketId, PreparePolicy, SourceRef
from dataflows.equity_data import sessions_from_metadata
from execution_channels.instruments import TimeInterval
from execution_channels.futu.account_retirement import AccountRetirementStatus, RetirementSession
from execution_channels.futu.channel import channel_profile

from .data_space import EquityAdapter, _source_config


class RetirementCalendar:
    """Use persisted bindings or the explicit environment market calendar source."""

    def __init__(self, store, dataflows, config_root):
        self.store, self.dataflows = store, dataflows
        self.sources = _source_config(config_root)
        self._prepared = {}

    def _inputs(self, account):
        profile = channel_profile(account['channel_id'])
        market = MarketId(profile.market)
        binding = self.store.v4_runtime_binding(account['account_id'])
        if binding is not None:
            inputs = binding['inputs']
            if inputs['release_hash'] != account['release_hash']:
                raise ValueError('retirement input binding differs from account release')
            parameters = [p for role, p in inputs['binding']['request_bindings'] if role == 'sessions']
            if len(parameters) != 1:
                raise ValueError('retirement requires one explicit execution calendar')
            value = parameters[0]
            instrument = InstrumentId(MarketId(value['instrument']['market']),
                                      AssetClass(value['instrument']['asset_class']), value['instrument']['symbol'])
            if instrument.market is not market:
                raise ValueError('retirement calendar market differs from channel')
            return instrument, SourceRef(**value['source']), Decimal(str(inputs['fee_rate']))
        sources = [s for s in self.sources if s.market is market
                   and s.adapter in {EquityAdapter.TUSHARE_CN, EquityAdapter.FUTU_US}]
        if len(sources) != 1:
            raise ValueError('retirement requires one configured calendar source for the account market')
        payload = account['last_decision_payload']
        plan = json.loads(payload) if isinstance(payload, str) else payload
        if not plan or 'fee_rate' not in plan:
            raise ValueError('retirement requires an explicit persisted model fee rate')
        instrument = InstrumentId(market, AssetClass(account['asset_type'].upper()), account['symbol'])
        return instrument, sources[0].source, Decimal(str(plan['fee_rate']))

    def session(self, account, observed_at):
        instrument, source, fee_rate = self._inputs(account)
        day = observed_at.astimezone(ZoneInfo(instrument.timezone)).date()
        request = EquityDataRequest(instrument, source,
            EquityQuery(EquityProduct.SESSIONS, day, day + timedelta(days=14)))
        key = request.parameters
        if key not in self._prepared:
            prepared = self.dataflows.prepare((request,), policy=PreparePolicy.REUSE)
            if not prepared.ready:
                raise ValueError('retirement calendar preparation is incomplete')
            fetched = self.dataflows.fetch(request, prepared=prepared.reference)
            if not fetched.ready:
                raise ValueError('retirement calendar is unavailable')
            self._prepared[key] = fetched
        fetched = self._prepared[key]
        sessions = sessions_from_metadata(fetched.identity.metadata)
        availability = dict(zip(fetched.dataframe.SessionDate, fetched.dataframe.AvailableDate, strict=True))
        for index, session in enumerate(sessions):
            if availability[session.session_date.isoformat()] > observed_at:
                continue
            for segment in session.segments:
                if segment.end <= observed_at:
                    continue
                settlement = None
                if instrument.market is MarketId.US:
                    if index + 1 >= len(sessions):
                        raise ValueError('retirement calendar lacks the next settlement session')
                    following = sessions[index + 1]
                    if availability[following.session_date.isoformat()] > observed_at:
                        raise ValueError('retirement settlement session is not yet known')
                    settlement = following.segments[0].start
                return RetirementSession(TimeInterval(segment.start, segment.end), fee_rate, settlement)
        raise ValueError('retirement calendar contains no known upcoming trading interval')

    def prepare(self, execution, *, observed_at=None):
        point = observed_at or datetime.now(timezone.utc)
        for account in self.store.strategy_virtual_accounts():
            if account['run_state'] != 'RETIRING' or int(account['quantity']) == 0:
                continue
            account_id = account['account_id']
            try:
                execution.set_retirement_session(account_id, self.session(account, point))
            except Exception as exc:
                # A failed calendar must not reuse yesterday's session or stop broker reconciliation.
                self.store.clear_retirement_session(account_id)
                self.store.set_retirement_progress(account_id, AccountRetirementStatus.BLOCKED,
                                                   f'retirement calendar: {exc}')
