"""US SRT adapter consumed by the normal AccountEngine and PaperStore."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING

from dataflows import TimeInterval, EquityProduct, TradingSession
from dataflows.equity_data import sessions_from_metadata
from execution_channels.daily_execution import INTERVAL_TARGET_TRIGGER
from execution_channels.execution_intervals import ExecutionInterval, execution_intervals
from execution_channels.instruments import TimeInterval as ChannelInterval
from strategy_runtime import TradableWindow
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityInputBinding
from .execution_reference import PreparedExecutionReference

if TYPE_CHECKING:
    import pandas as pd


def prepare_equity_decision(dataflows, candidate, binding, requests, interval, *, fee_rate, live=False,
                            execution_reference, execution_context=None, as_of=None, execution_interval=None):
    """Read pinned products and authenticate their identities before a normal PTE decision."""
    import pandas as pd
    from strategy_runtime.data_preparation import (
        CalendarCoverage, causal_history, fetch_prepared_products, prepare_observations,
    )
    if type(binding) is not EquityInputBinding or type(candidate) is not EquityStrategyCandidate:
        raise TypeError("equity preparation requires typed candidate and binding")
    cutoff = interval.start if as_of is None else as_of
    if type(cutoff) is not datetime or cutoff.utcoffset() is None or cutoff > interval.start:
        raise ValueError('equity observation cutoff must be aware and no later than execution start')
    if candidate.definition.contract_version != 4:
        raise ValueError('PTE equity runtime requires V4; migrate the frozen strategy and account explicitly')
    if (binding.instrument != candidate.instrument or binding.specification_hash != candidate.execution_spec_hash
            or binding.warmup_bars != candidate.warmup_bars
            or tuple(x.input for x in binding.auxiliary_inputs) != candidate.definition.auxiliary_inputs
            or tuple(x.input for x in binding.observation_bindings) != candidate.definition.observation_inputs):
        raise ValueError("equity preparation differs from candidate contract")
    identities = binding.expected_identities
    fetched = fetch_prepared_products(dataflows, binding.bind_requests(requests),
        prepared=binding.prepared, expected_identities=identities,
        calendar_coverage=(CalendarCoverage.OVERLAPPING_SESSIONS if live else CalendarCoverage.EXACT))
    products, metadata = fetched.products, fetched.metadata
    bars = products["bars"]
    if (execution_interval is None
            and candidate.definition.execution_policy.settings.get('execution_trigger') == INTERVAL_TARGET_TRIGGER):
        sessions = sessions_from_metadata(metadata['sessions'])
        frequency = candidate.definition.execution_spec.decision_clock
        execution_interval = next((cycle for cycle in execution_intervals(
            ChannelInterval(window.start, window.end) for session in sessions for window in session.bars(frequency))
            if (cycle.window.start, cycle.window.end) == (interval.start, interval.end)), None)
        if execution_interval is None:
            raise ValueError('decision has no execution interval in the prepared calendar')
    if live and candidate.definition.contract_version != 4:
        raise ValueError('live interval preparation requires native V4')
    if not live and len(bars.loc[(bars.BarStart == interval.start) & (bars.Date == interval.end)]) != 1:
        raise ValueError("decision interval absent from prepared market calendar")
    history = causal_history(bars, cutoff,
        latency_seconds=candidate.definition.execution_spec.data_latency_seconds,
        minimum_observations=candidate.warmup_bars)
    if live:
        from types import SimpleNamespace
        from strategy_runtime.equity_definition import InputBindingScope
        if binding.scope is not InputBindingScope.OBSERVATION:
            raise ValueError('live decisions require an explicitly migrated observation binding')
        if not isinstance(execution_context, Mapping) or execution_context.get('Date') != interval.start:
            raise ValueError('live decision requires the host-resolved execution context')
        if execution_context.get('PriceLimitPolicy') not in {'CHANNEL_CHECKED', 'EXPLICIT_UNBOUNDED'}:
            raise ValueError('live execution context requires an explicit channel price-limit policy')
        last = SimpleNamespace(**execution_context)
    else:
        from types import SimpleNamespace
        from .execution_inputs import resolve_live_context
        last = SimpleNamespace(**resolve_live_context(candidate, interval, products['sessions'], metadata['sessions']))
    if int(last.QuantityStep) != candidate.definition.execution_spec.quantity_step or float(last.PriceTick) != candidate.definition.execution_spec.price_tick:
        raise ValueError("prepared equity trading units differ from account rules")
    auxiliary = {}
    for item in candidate.definition.auxiliary_inputs:
        frame = products[item.data_key(EquityProduct.BARS)]
        auxiliary[item.name] = causal_history(frame, cutoff,
            latency_seconds=candidate.definition.execution_spec.data_latency_seconds)
    sessions, trading_sessions = None, ()
    if candidate.definition.session_context:
        frame = products['sessions']
        sessions = frame.loc[(frame.Date <= cutoff) & (frame.AvailableDate <= cutoff)].copy(deep=True)
        known_days = set(sessions.SessionDate)
        trading_sessions = tuple(s for s in sessions_from_metadata(metadata['sessions'])
                                 if s.session_date.isoformat() in known_days)
    replay, unlock, v4_constraint = None, None, None
    if candidate.definition.contract_version == 4:
        visible_products = products
        if live:
            # SRT's logical decision point remains the execution interval start.
            # Cap every market observation at the actual preparation time so
            # next-morning availability cannot leak into an overnight decision.
            visible_products = dict(products, bars=history)
            for item in candidate.definition.auxiliary_inputs:
                visible_products[item.data_key(EquityProduct.BARS)] = auxiliary[item.name]
            from strategy_runtime.observation_preparation import prepare_observation_tables
            from strategy_runtime.dataset_observations import InactiveObservationTable
            tables = prepare_observation_tables(candidate.definition.observation_inputs,
                products, fetched.identities, bindings=binding.observation_bindings)
            for item in candidate.definition.observation_inputs:
                table = tables[item.name]
                if type(table) is InactiveObservationTable:
                    continue
                frame = table.view(cutoff).to_frame()
                if frame.empty:
                    raise ValueError('OBSERVATION_WARMUP_INSUFFICIENT: ' + item.name)
                visible_products[item.data_key()] = frame
        replay = prepare_observations(candidate.definition, visible_products, fetched.identities,
            bindings=binding.observation_bindings, as_of=cutoff if live else None)
        v4_constraint = {"MarketRuleVersion": str(last.MarketRuleVersion),
            "MarketRuleHash": str(last.MarketRuleHash), "SellRemainderPolicy": str(last.SellRemainderPolicy),
            "PriceLimitPolicy": str(last.PriceLimitPolicy),
            "PriceLimitLower": None if pd.isna(last.PriceLimitLower) else float(last.PriceLimitLower),
            "PriceLimitUpper": None if pd.isna(last.PriceLimitUpper) else float(last.PriceLimitUpper)}
        if live:
            v4_constraint.update(Date=interval.start.isoformat(),
                AvailableDate=last.AvailableDate.isoformat(),
                QuantityStep=int(last.QuantityStep), PriceTick=float(last.PriceTick))
        unlock = last.BuySellableAt.to_pydatetime() if hasattr(last.BuySellableAt, 'to_pydatetime') else last.BuySellableAt
        if type(unlock) is not datetime or unlock.utcoffset() is None or unlock < interval.start:
            raise ValueError('V4 prepared constraint lacks a valid BuySellableAt')
    return PreparedEquityDecision(candidate, binding, history, interval, fee_rate, execution_reference,
                                  auxiliary, sessions, trading_sessions, v4_replay=replay, buy_sellable_at=unlock,
                                  v4_constraint=v4_constraint, live_interval=live, as_of=cutoff, execution_interval=execution_interval)


@dataclass(frozen=True)
class PreparedEquityDecision:
    candidate: EquityStrategyCandidate
    binding: EquityInputBinding
    history: object
    interval: TimeInterval
    fee_rate: float
    execution_reference: PreparedExecutionReference
    auxiliary_histories: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    sessions: pd.DataFrame | None = None
    trading_sessions: tuple[TradingSession, ...] = ()
    v4_constraint: Mapping | None = None
    v4_replay: object = None
    buy_sellable_at: datetime | None = None
    live_interval: bool = False
    as_of: datetime | None = None
    execution_interval: ExecutionInterval | None = None
    history_sha256: str = field(init=False)
    decision_inputs_sha256: str = field(init=False)

    def __post_init__(self):
        if self.as_of is None:
            object.__setattr__(self, 'as_of', self.interval.start)
        if type(self.as_of) is not datetime or self.as_of.utcoffset() is None or self.as_of > self.interval.start:
            raise ValueError('equity observation cutoff must be aware and no later than execution start')
        if self.execution_interval is not None and (
            type(self.execution_interval) is not ExecutionInterval
            or (self.execution_interval.window.start, self.execution_interval.window.end)
                != (self.interval.start, self.interval.end)
        ):
            raise ValueError('prepared decision differs from the execution interval')
        if type(self.live_interval) is not bool:
            raise TypeError('prepared live interval mode must be boolean')
        if type(self.execution_reference) is not PreparedExecutionReference:
            raise TypeError('prepared decision requires a separate RAW execution reference')
        if self.execution_reference.observed_through > self.as_of:
            raise ValueError('execution reference is later than the decision')
        if type(self.candidate) is not EquityStrategyCandidate or type(self.binding) is not EquityInputBinding or type(self.interval) is not TimeInterval:
            raise TypeError("prepared equity decision requires typed candidate/input/interval")
        import pandas as pd
        if not isinstance(self.history, pd.DataFrame) or self.history.empty:
            raise ValueError("prepared equity history is empty")
        ends = pd.to_datetime(self.history.Date)
        available = pd.to_datetime(self.history.AvailableDate)
        if ends.dt.tz is None or available.dt.tz is None or ends.max() > self.as_of or available.max() > self.as_of:
            raise ValueError("prepared equity decision contains future information")
        if self.execution_reference.observed_through != ends.iloc[-1]:
            raise ValueError('HFQ signal and RAW execution reference must share the completed observation time')
        self.candidate.verify()
        if not isinstance(self.auxiliary_histories, Mapping):
            raise TypeError('prepared auxiliary histories require a mapping')
        if set(self.auxiliary_histories) != {x.name for x in self.candidate.definition.auxiliary_inputs}:
            raise ValueError('prepared auxiliary coverage differs')
        for frame in self.auxiliary_histories.values():
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise ValueError('prepared auxiliary history is empty')
            ends, available = pd.to_datetime(frame.Date), pd.to_datetime(frame.AvailableDate)
            if ends.dt.tz is None or available.dt.tz is None or ends.max() > self.as_of or available.max() > self.as_of:
                raise ValueError('prepared auxiliary history contains future information')
        object.__setattr__(self, 'auxiliary_histories', MappingProxyType(
            {key: frame.copy(deep=True) for key, frame in self.auxiliary_histories.items()}))
        if self.sessions is not None:
            object.__setattr__(self, 'sessions', self.sessions.copy(deep=True))
        if type(self.trading_sessions) is not tuple or any(type(x) is not TradingSession for x in self.trading_sessions):
            raise TypeError('prepared sessions require typed calendar')
        enabled = self.candidate.definition.session_context
        if (enabled and (self.sessions is None or not self.trading_sessions)
                or not enabled and (self.sessions is not None or self.trading_sessions)):
            raise ValueError('prepared session coverage differs')
        from hashlib import sha256
        object.__setattr__(self, "history_sha256", sha256(self.history.to_json(date_format="iso").encode()).hexdigest())
        object.__setattr__(self, 'decision_inputs_sha256', self._decision_inputs_hash())
        import math
        if type(self.fee_rate) not in (int, float) or not math.isfinite(self.fee_rate) or not 0 <= self.fee_rate < 1:
            raise ValueError("equity decision requires an explicit finite fee rate")

    def _decision_inputs_hash(self):
        from strategy_runtime import canonical_sha256
        value = {
            'as_of': self.as_of.isoformat(),
            'execution_reference': self.execution_reference.to_dict(),
            'auxiliary': {key: frame.to_json(date_format='iso', date_unit='us') for key, frame in self.auxiliary_histories.items()},
            'sessions': None if self.sessions is None else self.sessions.to_json(date_format='iso', date_unit='us'),
            'calendar': [{'session_date': x.session_date.isoformat(), 'timezone': x.timezone,
                          'segments': [(s.start.isoformat(), s.end.isoformat()) for s in x.segments]}
                         for x in self.trading_sessions],
        }
        if self.candidate.definition.contract_version == 4:
            value.update(
                v4_constraint=None if self.v4_constraint is None else dict(self.v4_constraint),
                v4_replay=None if self.v4_replay is None else self.v4_replay.identity,
                buy_sellable_at=None if self.buy_sellable_at is None else self.buy_sellable_at.isoformat())
            if self.live_interval:
                value['live_interval'] = True

        return canonical_sha256(value)

    @property
    def available_through(self):
        from zoneinfo import ZoneInfo
        return self.history.Date.iloc[-1].astimezone(ZoneInfo(self.candidate.instrument.timezone)).date()

    @property
    def tradable_window(self):
        from zoneinfo import ZoneInfo
        day = self.interval.start.astimezone(ZoneInfo(self.candidate.instrument.timezone)).date()
        return TradableWindow(day, day)

    @property
    def data_identity(self):
        from strategy_runtime import canonical_sha256
        return canonical_sha256(self.data_reference)

    @property
    def data_reference(self):
        return {'strategy': self.binding.to_dict(), 'execution_reference': self.execution_reference.to_dict()}

    def validate_unchanged(self):
        """Reject mutation of the already authenticated observation and execution inputs."""
        from hashlib import sha256
        if sha256(self.history.to_json(date_format="iso").encode()).hexdigest() != self.history_sha256:
            raise ValueError("prepared equity history changed after authentication")
        if self._decision_inputs_hash() != self.decision_inputs_sha256:
            raise ValueError('prepared equity decision inputs changed after authentication')


class EquityAdviceClient:
    def __init__(self, store):
        self.store = store

    def get_decision(self, actual_quantity, available_cash, *, total_assets, trading_date,
                     portfolio_revision, state_revision, cycle_target_quantity, entry_cycle,
                     strategy_id, strategy_version, account_id, symbol, asset, prepared, replacement=None):
        if type(prepared) is not PreparedEquityDecision:
            raise TypeError("equity advice requires PreparedEquityDecision")
        prepared.validate_unchanged()
        candidate = prepared.candidate
        rules = self.store.equity_account_rules(account_id)
        account = self.store.virtual_account(account_id)
        if replacement is not None:
            from execution_channels.futu.decision_replacement import ReplacementSnapshot
            if type(replacement) is not ReplacementSnapshot or replacement.account_id != account_id:
                raise TypeError("equity rerun requires the matching EC replacement snapshot")
            account = {**account, "account_v4_json": replacement.before}
        import json
        events = {row["event_id"]:json.loads(row["payload"]) for row in self.store._connection.execute(
            "SELECT event_id,payload FROM equity_account_events WHERE account_id=?",(account_id,))}
        point = prepared.as_of
        if any(datetime.fromisoformat(fill["occurred_at"]) > point for fill in self.store.account_fills(account_id)):
            raise ValueError("confirmed equity fill is later than the requested decision point")
        if any(datetime.fromisoformat(row["occurred_at"]) > point for row in self.store._connection.execute(
                "SELECT occurred_at FROM account_ledger WHERE account_id=? AND entry_type IN (?,?)",
                (account_id, 'POSITION_ADJUSTMENT', 'SALE_SETTLEMENT'))):
            raise ValueError('confirmed account reconciliation is later than the requested decision point')
        for event in events.values():
            definition = event.get("definition")
            if definition is not None and datetime.fromisoformat(definition["effective_at"]) > point:
                raise ValueError("confirmed equity action is later than the requested decision point")
            if event.get("kind") == "RECEIVABLE" and event["paid"] and datetime.fromisoformat(event["pay_at"]) > point:
                raise ValueError("confirmed equity payment is later than the requested decision point")
        if any(e.get("kind") == "RECEIVABLE" and not e["paid"]
               and (not prepared.live_interval or e.get("recognized_kind") != "CASH_DIVIDEND")
               and datetime.fromisoformat(e["pay_at"]) <= point for e in events.values()):
            raise ValueError("due equity payments must be settled before decision")
        from .ec_boundary import execution_rules
        if (rules is None or rules.to_dict() != execution_rules(candidate.instrument, candidate.definition.execution_spec).to_dict()
                or strategy_id != candidate.strategy_id or symbol != candidate.instrument.symbol or asset != candidate.instrument.asset_class.value.lower()):
            raise ValueError("equity candidate differs from account market binding")
        if candidate.definition.contract_version != 4:
            raise ValueError('PTE equity runtime requires V4; migrate the frozen strategy and account explicitly')
        from .equity_v4_advice import account_decision
        return account_decision(self.store, prepared, account, actual_quantity, available_cash,
            trading_date, portfolio_revision, state_revision,
            through_cursor=None if replacement is None else replacement.event_cursor)
