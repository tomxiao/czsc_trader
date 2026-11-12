"""Causal V4 planning shared by historical replay and durable account services.

Planning proposes state; only the calling account transaction may commit it.
Prepared market inputs never form part of a durable account's state binding.
"""
from contextlib import nullcontext
from functools import partial
from dataclasses import dataclass
from datetime import datetime
import math

from dataflows import BarFrequency, TimeInterval

from .account_strategy import (AccountDecision, AccountStepContext, AccountStepResult,
    AccountStrategyState, BatchAccountContext, BatchObservation, DecisionHistory, DecisionTable, PositionFeedback)
from .equity import DecisionPoint, EquityPortfolio, equity_hash
from .equity_definition import EquityStrategyCandidate
from .equity_replay import PreparedObservations, StateRecord, _FeatureEvaluator, _Visibility
from .market_features import _market_feature
from .replay_contracts import (AccountSnapshot, ExecutionPrecision,
    ReplayPoint, StrategyComputation)


@dataclass(frozen=True, slots=True)
class AccountDecisionProposal:
    proposal: AccountStepResult
    point: ReplayPoint
    next_event_cursor: int
    suppressed: bool = False

    def __post_init__(self):
        if type(self.proposal) is not AccountStepResult or type(self.point) is not ReplayPoint:
            raise TypeError('account proposal requires typed strategy state and decision point')
        if type(self.suppressed) is not bool:
            raise TypeError('strategy proposal suppression requires bool')
        if type(self.next_event_cursor) is not int or self.next_event_cursor < 0:
            raise ValueError('account proposal requires a nonnegative event cursor')


@dataclass(frozen=True, slots=True)
class AccountBatchConsistency:
    checked_points: int
    differing_points: tuple[datetime, ...]

    def __post_init__(self):
        if type(self.checked_points) is not int or self.checked_points < 0:
            raise ValueError('batch comparison requires a nonnegative observation count')
        if (type(self.differing_points) is not tuple or len(self.differing_points) > self.checked_points
                or any(type(point) is not datetime or point.tzinfo is None for point in self.differing_points)
                or any(a >= b for a, b in zip(self.differing_points, self.differing_points[1:]))):
            raise ValueError('batch comparison requires ordered aware difference points')

    @property
    def consistent(self):
        return not self.differing_points


def check_account_batch_consistency(candidate, prepared, *, start, end):
    """Explicit stage-five check of batch versus online observations in a window.

    Batch implementations may use the observations sequence itself, so singleton
    equivalence is never assumed. This check does not run accounts, does not
    change the historical batch contract and is never part of routine planning.
    Its conclusion covers only the supplied observations.
    """
    if (type(start) is not datetime or type(end) is not datetime or start.tzinfo is None
            or end.tzinfo is None or start >= end):
        raise ValueError('batch comparison requires an aware positive window')
    engine = AccountDecisionEngine(candidate, prepared)
    if candidate.definition.computation is not StrategyComputation.BATCH_HISTORY:
        raise ValueError('batch comparison requires BATCH_HISTORY')
    ticks = tuple((a, b) for a, b in zip(prepared._data.starts, prepared._data.ends)
                  if a >= start and b <= end)
    if not ticks or ticks[0][0] != start or ticks[-1][1] != end:
        raise ValueError('batch comparison window must align with complete observations')
    observations = []
    for a, b in ticks:
        observation = engine.observation(TimeInterval(a, b))
        if not observation[-1]:
            observations.append(BatchObservation(*engine._decision_inputs(observation)))
    from .equity_source_runtime import active_invocation
    scope = nullcontext() if active_invocation(candidate) is not None else candidate.bind_replay()
    with scope:
        batch = candidate.calculate_account_batch(BatchAccountContext(tuple(observations), candidate.definition.parameters))
        differing = []
        for observation, expected in zip(observations, batch, strict=True):
            actual, = candidate.calculate_account_batch(BatchAccountContext((observation,), candidate.definition.parameters))
            if actual != expected:
                differing.append(observation.point.decision_at)
    return AccountBatchConsistency(len(observations), tuple(differing))


class AccountDecisionEngine:
    """One prepared history, monotonic causal observations, no account mutations.

    Online batch calls contain a single observation with its complete visible
    history. Stage-five callers explicitly check batch/online consistency before
    accepting implementations that depend on a sequence of batch observations.
    """

    def __init__(self, candidate, prepared, *, performance=None):
        if type(candidate) is not EquityStrategyCandidate or type(prepared) is not PreparedObservations:
            raise TypeError('account planning requires typed candidate and prepared inputs')
        definition, spec = candidate.definition, candidate.definition.execution_spec
        if definition.contract_version != 4 or spec.decision_clock not in (BarFrequency.DAILY, BarFrequency.M30):
            raise ValueError('account planning requires V4 with an explicit decision clock')
        if prepared.frequency is not spec.decision_clock:
            raise ValueError('prepared decision clock differs from strategy')
        if definition.feature_graph != prepared.graph or spec.data_latency_seconds != prepared._data.latency_seconds:
            raise ValueError('prepared feature/visibility contract differs')
        if not prepared._sessions or not prepared._calendar_intervals:
            raise ValueError('account planning requires explicit session evidence')
        self.candidate, self.prepared = candidate, prepared
        self._performance = performance
        self._market_features = {item.name: item for item in definition.market_features}
        self._visibility = _Visibility(prepared._data)
        feature_args = (prepared._data, prepared.graph, self._visibility)
        self._features = (_FeatureEvaluator(*feature_args) if performance is None else
                          performance.graph(_FeatureEvaluator, *feature_args))
        self._auxiliary = {name: (_Visibility(data), data) for name, data in prepared._auxiliary}
        self._tables = dict(prepared._observations)
        self._table_cache = None
        if set(self._tables) != {item.name for item in definition.observation_inputs}:
            raise ValueError('prepared table observations differ from declaration')
        self._intervals = dict(prepared._calendar_intervals)
        self._observed_at = None
        self._observation_cache = None

    def _market_feature(self, history, views, tables, session, name):
        if name not in self._market_features:
            raise ValueError('undeclared market feature: ' + name)
        args = (self.candidate, self.prepared, self._market_features[name], history, views, tables, session)
        return _market_feature(*args) if self._performance is None else self._performance.feature(_market_feature, *args)

    def _decision_inputs(self, observation):
        point, features, history, views, session, available, _ = observation
        tables = self.table_views(point.decision_at)
        provider = partial(self._market_feature, history, views, tables, session) if self._market_features else None
        expose_session = self.candidate.definition.session_context
        return (point, features, DecisionHistory._from_history(history),
                {name: DecisionHistory._from_history(view) for name, view in views.items()},
                session if expose_session else None, available if expose_session else None,
                {name: DecisionTable._from_table(view) for name, view in tables.items()}, provider)

    def table_views(self, when):
        import pandas as pd
        from types import MappingProxyType
        from .dataset_observations import TableObservationStatus
        if self._table_cache is not None and self._table_cache[0] == when:
            return self._table_cache[1]
        views = {}
        for declaration in self.candidate.definition.observation_inputs:
            view = self._tables[declaration.name].view(when)
            if view.status is TableObservationStatus.INACTIVE:
                views[declaration.name] = view
                continue
            if (view.observation_count < declaration.coverage.minimum_observations
                    or view.session_count < declaration.coverage.minimum_sessions):
                raise ValueError('OBSERVATION_WARMUP_INSUFFICIENT: ' + declaration.name)
            if declaration.max_staleness_days is not None:
                latest = view.latest_session
                zone = self._tables[declaration.name].source_timezone
                if latest is None or (pd.Timestamp(when).tz_convert(zone).date() - latest).days > declaration.max_staleness_days:
                    raise ValueError('OBSERVATION_INPUT_STALE: ' + declaration.name)
            views[declaration.name] = view
        result = MappingProxyType(views)
        self._table_cache = (when, result)
        return result

    def state_binding(self, owner, fee_rate):
        self._validate_owner_fee(owner, fee_rate)
        return equity_hash({'owner': owner, 'implementation': self.candidate.implementation_hash,
                           'specification': self.candidate.definition.execution_spec.fingerprint,
                           'fee_rate': fee_rate})

    @staticmethod
    def _validate_owner_fee(owner, fee_rate):
        if type(owner) is not str or not owner:
            raise TypeError('account planning requires an owner identity')
        if type(fee_rate) not in (float, int) or not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise ValueError('account fee must be finite in [0,1)')

    def observation(self, interval, *, decision_at=None):
        if type(interval) is not TimeInterval:
            raise TypeError('account observation requires TimeInterval')
        key = interval.start, interval.end
        if key not in self._intervals:
            raise ValueError('execution interval absent from declared calendar or input grid')
        when = interval.start if decision_at is None else decision_at
        if type(when) is not datetime or when.utcoffset() is None or when > interval.start:
            raise ValueError('decision cutoff must be aware and no later than submission start')
        cache_key = key, when
        if self._observed_at is not None and when < self._observed_at:
            raise ValueError('account observations must be requested in causal time order')
        if self._observation_cache is not None and self._observation_cache[0] == cache_key:
            observation = self._observation_cache[1]
            return (*observation[:3], dict(observation[3]), *observation[4:])
        self._observed_at = when
        definition, data, visibility = self.candidate.definition, self.prepared._data, self._visibility
        visibility.advance(when)
        if visibility.count < definition.warmup_bars:
            raise ValueError('WARMUP_INSUFFICIENT: visible observed history')
        point = DecisionPoint(data.ends[visibility.row(0)], when, interval)
        views = {}
        for declaration in definition.auxiliary_inputs:
            if declaration.name not in self._auxiliary:
                raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: ' + declaration.name)
            indexer, item = self._auxiliary[declaration.name]
            indexer.advance(when)
            if indexer.count < declaration.warmup_bars:
                raise ValueError('AUXILIARY_WARMUP_INSUFFICIENT: ' + declaration.name)
            latest = indexer.row(0)
            if not item.observed[indexer.latest_completed] or float(item.rows[latest]['Volume']) <= 0:
                raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: ' + declaration.name)
            if (when - item.ends[latest]).total_seconds() > declaration.max_age_seconds:
                raise ValueError('AUXILIARY_INPUT_STALE: ' + declaration.name)
            views[declaration.name] = indexer.history_view(when)
        session, available = self.prepared._sessions[self._intervals[key]]
        if session.timezone != self.candidate.instrument.timezone:
            raise ValueError('prepared session timezone differs from instrument')
        if available > when:
            raise ValueError('session calendar is not yet available')
        features = (self._features.at(when) if self._performance is None else
                    self._performance.graph(self._features.at, when))
        observation = (point, features, visibility.history_view(when),
                       views, session, available, not data.observed[visibility.latest_completed])
        self._observation_cache = cache_key, observation
        return (*observation[:3], dict(views), *observation[4:])

    def propose(self, interval, portfolio, account, state, position, *, owner, fee_rate,
             budget=None, events=(), next_event_cursor=None, binding=None, decision_at=None):
        observation = self.observation(interval, decision_at=decision_at)
        return self._propose_observation(observation, portfolio, account, state, position,
            owner=owner, fee_rate=fee_rate, budget=budget, events=events,
            next_event_cursor=next_event_cursor, binding=binding)

    def _propose_observation(self, observation, portfolio, account, state, position, *, owner,
                          fee_rate, budget=None, events=(),
                          next_event_cursor=None, binding=None):
        definition, spec = self.candidate.definition, self.candidate.definition.execution_spec
        if binding is None:
            binding = self.state_binding(owner, fee_rate)
        else:
            self._validate_owner_fee(owner, fee_rate)
        if type(binding) is not str or not binding:
            raise ValueError('account planning requires an explicit state binding')
        if type(state) is not AccountStrategyState or type(portfolio) is not EquityPortfolio:
            raise TypeError('account planning requires typed state and portfolio')
        if type(account) is not AccountSnapshot or type(position) is not PositionFeedback:
            raise TypeError('account planning requires typed account and position feedback')
        if account.instrument != self.candidate.instrument or account.currency != spec.account.currency:
            raise ValueError('account market binding differs from strategy')
        if state.binding not in (None, binding) or (state.revision > 0 and state.binding is None):
            raise ValueError('strategy state belongs to another account')
        definition.state_schema.validate_record(state.account, scope='account')
        if state.cycle is not None:
            definition.state_schema.validate_record(state.cycle.values, scope='cycle')
        if portfolio.revision != state.revision or bool(portfolio.quantity) != (state.cycle is not None):
            raise ValueError('strategy state differs from confirmed execution')
        if state.cycle is not None and (state.cycle.entry_at != portfolio.cycle_entry
                or position.active is None or state.cycle.cycle_id != position.active.cycle_id
                or position.active.quantity != portfolio.quantity):
            raise ValueError('strategy cycle differs from confirmed fills')
        if not portfolio.quantity and position.active is not None:
            raise ValueError('flat portfolio cannot carry an active position')
        point, _, _, _, session, _, suppressed = observation
        replay_point = ReplayPoint(point.observed_through, point.decision_at,
            point.execution_interval.start, point.execution_interval.end,
            session.session_date.isoformat(), ExecutionPrecision.BAR_INTERVAL)
        decision_inputs = self._decision_inputs(observation)
        cursor = state.event_cursor + len(events) if next_event_cursor is None else next_event_cursor
        if type(cursor) is not int or cursor < state.event_cursor + len(events):
            raise ValueError('recognized account event cursor cannot regress')
        if suppressed:
            proposal = AccountStepResult(AccountDecision.from_facts(float(portfolio.quantity > 0),
                'unobserved input', facts={'suppressed': True}, next_watch='next observed bar'),
                state.account, state.cycle.values if state.cycle else None)
            return AccountDecisionProposal(proposal, replay_point, state.event_cursor, True)
        from .equity_source_runtime import active_invocation
        scope = nullcontext() if active_invocation(self.candidate) is not None else self.candidate.bind_replay()
        with scope:
            if definition.computation is StrategyComputation.BATCH_HISTORY:
                batch_decision, = self.candidate.calculate_account_batch(
                    BatchAccountContext((BatchObservation(*decision_inputs),), definition.parameters))
                proposal = AccountStepResult(batch_decision, state.account, StateRecord())
            else:
                _, features, history, views, session, available, tables, provider = decision_inputs
                context = AccountStepContext(point, portfolio, account, position, definition.parameters,
                    features, history, budget=budget, events=events, auxiliary_histories=views,
                    session=session, session_available_at=available, observations=tables,
                    _market_feature_provider=provider)
                proposal = self.candidate.account_step(context, state)
        if (portfolio.quantity or proposal.decision.target) and proposal.cycle_values is None:
            raise ValueError('holding/entry requires typed cycle state')
        return AccountDecisionProposal(proposal, replay_point, cursor)
