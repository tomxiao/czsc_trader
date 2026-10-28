"""US SRT adapter consumed by the normal AccountEngine and PaperStore."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

from dataflows import TimeInterval, EquityProduct, TradingSession
from dataflows.equity_data import sessions_from_metadata
from strategy_runtime import EquityPortfolio, StrategyRuntime, TradableWindow
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityInputBinding
from .contracts import AdviceDecision, OrderSpec

if TYPE_CHECKING:
    import pandas as pd


def prepare_equity_decision(dataflows, candidate, binding, requests, interval, *, fee_rate):
    """Read pinned products and authenticate their identities before a normal PTE decision."""
    import pandas as pd
    if type(binding) is not EquityInputBinding or type(candidate) is not EquityStrategyCandidate:
        raise TypeError("equity preparation requires typed candidate and binding")
    if (binding.instrument != candidate.instrument or binding.specification_hash != candidate.execution_spec_hash
            or binding.warmup_bars != candidate.warmup_bars
            or tuple(x.input for x in binding.auxiliary_inputs) != candidate.definition.auxiliary_inputs):
        raise ValueError("equity preparation differs from candidate contract")
    identities = binding.expected_identities
    products = {}
    calendars = {}
    metadata = {}
    for request in requests:
        name = binding.request_key(request)
        fetched = dataflows.fetch(request, prepared=binding.prepared)
        if not fetched.ready or name in products or fetched.identity.content_sha256 != identities.get(name):
            raise ValueError("equity preparation product identity differs")
        role = name.rsplit(':', 1)[0] if name.startswith('auxiliary:') else 'primary'
        calendar = fetched.identity.metadata["sessions"]
        if role in calendars and calendars[role] != calendar:
            raise ValueError("equity preparation calendars differ")
        calendars[role] = calendar
        metadata[name] = fetched.identity.metadata
        products[name] = fetched.dataframe
    if set(products) != set(identities):
        raise ValueError("equity preparation lacks required products")
    bars = products["bars"]
    if len(bars.loc[(bars.BarStart == interval.start) & (bars.Date == interval.end)]) != 1:
        raise ValueError("decision interval absent from prepared market calendar")
    delay = pd.Timedelta(seconds=candidate.definition.execution_spec.data_latency_seconds)
    history = bars.loc[(bars.Date <= interval.start) & (bars.AvailableDate + delay <= interval.start)].copy(deep=True)
    if len(history) < candidate.warmup_bars:
        raise ValueError("insufficient causal equity warmup")
    constraints = products["constraints"]
    known = constraints.loc[(constraints.Date == interval.start) & (constraints.AvailableDate <= interval.start)]
    if len(known) != 1 or not bool(known.iloc[0].Tradable):
        raise ValueError("no known tradable equity constraint for this decision")
    last = known.iloc[-1]
    if int(last.QuantityStep) != candidate.definition.execution_spec.quantity_step or float(last.PriceTick) != candidate.definition.execution_spec.price_tick:
        raise ValueError("prepared equity trading units differ from account rules")
    scale = 1.
    actions = products["actions"]
    for row in actions.itertuples():
        if row.Kind == "SPLIT" and history.Date.iloc[-1] <= row.Date <= interval.start and row.AvailableDate <= interval.start:
            scale /= float(row.Ratio)
    required = tuple((str(row.EventId), identities["actions"]) for row in actions.itertuples()
                     if row.Kind != "NONE" and row.Date <= interval.start and row.AvailableDate <= interval.start)
    auxiliary = {}
    for item in candidate.definition.auxiliary_inputs:
        frame = products[item.data_key(EquityProduct.BARS)]
        auxiliary[item.name] = frame.loc[(frame.Date <= interval.start) & (frame.AvailableDate + delay <= interval.start)].copy(deep=True)
    sessions, trading_sessions = None, ()
    if candidate.definition.session_context:
        frame = products['sessions']
        sessions = frame.loc[(frame.Date <= interval.start) & (frame.AvailableDate <= interval.start)].copy(deep=True)
        known_days = set(sessions.SessionDate)
        trading_sessions = tuple(s for s in sessions_from_metadata(metadata['sessions'])
                                 if s.session_date.isoformat() in known_days)
    return PreparedEquityDecision(candidate, binding, history, interval, fee_rate, scale, required,
                                  auxiliary, sessions, trading_sessions)


@dataclass(frozen=True)
class PreparedEquityDecision:
    candidate: EquityStrategyCandidate
    binding: EquityInputBinding
    history: object
    interval: TimeInterval
    fee_rate: float
    reference_price_scale: float = 1.
    required_actions: tuple[tuple[str, str], ...] = ()
    auxiliary_histories: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    sessions: pd.DataFrame | None = None
    trading_sessions: tuple[TradingSession, ...] = ()
    history_sha256: str = field(init=False)
    decision_inputs_sha256: str = field(init=False)

    def __post_init__(self):
        if type(self.candidate) is not EquityStrategyCandidate or type(self.binding) is not EquityInputBinding or type(self.interval) is not TimeInterval:
            raise TypeError("prepared equity decision requires typed candidate/input/interval")
        import pandas as pd
        if not isinstance(self.history, pd.DataFrame) or self.history.empty:
            raise ValueError("prepared equity history is empty")
        ends = pd.to_datetime(self.history.Date)
        available = pd.to_datetime(self.history.AvailableDate)
        if ends.dt.tz is None or available.dt.tz is None or ends.max() > self.interval.start or available.max() > self.interval.start:
            raise ValueError("prepared equity decision contains future information")
        self.candidate.verify()
        if not isinstance(self.auxiliary_histories, Mapping):
            raise TypeError('prepared auxiliary histories require a mapping')
        if set(self.auxiliary_histories) != {x.name for x in self.candidate.definition.auxiliary_inputs}:
            raise ValueError('prepared auxiliary coverage differs')
        for frame in self.auxiliary_histories.values():
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise ValueError('prepared auxiliary history is empty')
            ends, available = pd.to_datetime(frame.Date), pd.to_datetime(frame.AvailableDate)
            if ends.dt.tz is None or available.dt.tz is None or ends.max() > self.interval.start or available.max() > self.interval.start:
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
        return canonical_sha256({
            'auxiliary': {key: frame.to_json(date_format='iso', date_unit='us') for key, frame in self.auxiliary_histories.items()},
            'sessions': None if self.sessions is None else self.sessions.to_json(date_format='iso', date_unit='us'),
            'calendar': [{'session_date': x.session_date.isoformat(), 'timezone': x.timezone,
                          'segments': [(s.start.isoformat(), s.end.isoformat()) for s in x.segments]}
                         for x in self.trading_sessions],
        })

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
        return canonical_sha256(self.binding.to_dict())

    @property
    def data_reference(self):
        return self.binding.to_dict()


class EquityAdviceClient:
    def __init__(self, store):
        self.store = store

    def get_decision(self, actual_quantity, available_cash, *, total_assets, trading_date,
                     portfolio_revision, state_revision, cycle_target_quantity, entry_cycle,
                     strategy_id, strategy_version, account_id, symbol, asset, prepared):
        if type(prepared) is not PreparedEquityDecision:
            raise TypeError("equity advice requires PreparedEquityDecision")
        from hashlib import sha256
        if sha256(prepared.history.to_json(date_format="iso").encode()).hexdigest() != prepared.history_sha256:
            raise ValueError("prepared equity history changed after authentication")
        if prepared._decision_inputs_hash() != prepared.decision_inputs_sha256:
            raise ValueError('prepared equity decision inputs changed after authentication')
        candidate = prepared.candidate
        rules = self.store.equity_account_rules(account_id)
        account = self.store.virtual_account(account_id)
        import json
        events = {row["event_id"]:json.loads(row["payload"]) for row in self.store._connection.execute(
            "SELECT event_id,payload FROM equity_account_events WHERE account_id=?",(account_id,))}
        point = prepared.interval.start
        if any(datetime.fromisoformat(fill["occurred_at"]) > point for fill in self.store.account_fills(account_id)):
            raise ValueError("confirmed equity fill is later than the requested decision point")
        for event in events.values():
            definition = event.get("definition")
            if definition is not None and datetime.fromisoformat(definition["effective_at"]) > point:
                raise ValueError("confirmed equity action is later than the requested decision point")
            if event.get("kind") == "RECEIVABLE" and event["paid"] and datetime.fromisoformat(event["pay_at"]) > point:
                raise ValueError("confirmed equity payment is later than the requested decision point")
        for event_id, source_hash in prepared.required_actions:
            if events.get(event_id,{}).get("definition",{}).get("source_sha256") != source_hash:
                raise ValueError("prepared equity action must be applied before decision")
        if any(e.get("kind") == "RECEIVABLE" and not e["paid"] and datetime.fromisoformat(e["pay_at"]) <= prepared.interval.start for e in events.values()):
            raise ValueError("due equity payments must be settled before decision")
        if (rules is None or rules.execution != candidate.definition.execution_spec or rules.instrument != candidate.instrument
                or strategy_id != candidate.strategy_id or symbol != candidate.instrument.symbol or asset != "stock"):
            raise ValueError("equity candidate differs from account market binding")
        cost = float(Decimal(account["average_cost"]) * actual_quantity)
        records = self.store._connection.execute("SELECT occurred_at,quantity_after FROM account_ledger WHERE account_id=? ORDER BY rowid", (account_id,)).fetchall()
        opened = None
        for row in records:
            if int(row["quantity_after"]) == 0:
                opened = None
            elif opened is None:
                opened = datetime.fromisoformat(row["occurred_at"])
        portfolio = EquityPortfolio(available_cash, actual_quantity, float(account["receivable"]),
                                    portfolio_revision, cycle_entry=opened, cycle_cost=cost,
                                    feedback_source="CONFIRMED_EXECUTION", reference_price_scale=prepared.reference_price_scale)
        runtime = StrategyRuntime(execution_spec=rules.execution)
        instance = runtime.create(candidate)
        plan = instance.plan(prepared.history, prepared.interval, portfolio, fee_rate=prepared.fee_rate,
                             auxiliary_histories=prepared.auxiliary_histories, sessions=prepared.sessions,
                             trading_sessions=prepared.trading_sessions)
        target = actual_quantity + (plan.quantity if plan.side == "BUY" else -plan.quantity if plan.side == "SELL" else 0)
        price = plan.limit_price if plan.limit_price is not None else plan.reference_price
        orders = (() if not plan.quantity else (OrderSpec(plan.side, plan.quantity,
            "LIMIT" if plan.side == "BUY" else "MARKET", price, "DAY"),))
        fee = prepared.fee_rate
        estimate = 0 if plan.side != "BUY" else price * plan.quantity * (1 + fee)
        return AdviceDecision("advice.equity.v1", plan.plan_id, symbol, prepared.available_through,
            trading_date, actual_quantity, target, target, target - actual_quantity, plan.side,
            {"strategy_id": strategy_id, "version": strategy_version, "release_hash": account["release_hash"]},
            plan.reference_price, plan.reference_price, prepared.available_through,
            orders[0] if orders else None, plan.plan_id, plan.plan_id, portfolio_revision, state_revision,
            orders=orders, available_cash=available_cash, fee_rate=fee, estimated_order_cost=estimate,
            unallocated_cash=available_cash - estimate, strategy_output={"explanation": plan.explanation},
            equity_execution_interval={"start": prepared.interval.start.isoformat(), "end": prepared.interval.end.isoformat()},
            equity_observed_through=plan.point.observed_through.isoformat())
