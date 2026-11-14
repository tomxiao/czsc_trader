"""Causal account planning shared by historical replay and durable account services.

Planning proposes state; only the calling account transaction may commit it.
Prepared market inputs never form part of a durable account's state binding.
"""
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
import math

from dataflows import BarFrequency, TimeInterval

from .account_strategy import (AccountDecision, AccountStepContext, AccountStepResult,
    AccountStrategyState, PositionFeedback)
from .equity import DecisionPoint, EquityPortfolio, equity_hash
from .equity_definition import EquityStrategyCandidate
from .equity_replay import PreparedObservations, _Visibility
from .step_data import STEP_DATA_CONTRACT, StepData, StepDataRead
from .replay_contracts import AccountSnapshot, ExecutionPrecision, ReplayPoint


@dataclass(frozen=True, slots=True)
class AccountDecisionProposal:
    proposal: AccountStepResult
    point: ReplayPoint
    next_event_cursor: int
    suppressed: bool = False
    data_reads: tuple[StepDataRead, ...] = ()

    def __post_init__(self):
        if type(self.proposal) is not AccountStepResult or type(self.point) is not ReplayPoint:
            raise TypeError('account proposal requires typed strategy state and decision point')
        if type(self.suppressed) is not bool:
            raise TypeError('strategy proposal suppression requires bool')
        if type(self.next_event_cursor) is not int or self.next_event_cursor < 0:
            raise ValueError('account proposal requires a nonnegative event cursor')
        if type(self.data_reads) is not tuple or any(type(read) is not StepDataRead for read in self.data_reads):
            raise TypeError('account proposal requires typed DFLS read receipts')


class AccountDecisionEngine:
    """Derive a causal decision point from host execution inputs and invoke one step."""

    def __init__(self, candidate, prepared, *, step_data_load=None, data_cutoff=None, performance=None):
        if type(candidate) is not EquityStrategyCandidate or type(prepared) is not PreparedObservations:
            raise TypeError('account planning requires typed candidate and prepared inputs')
        definition, spec = candidate.definition, candidate.definition.execution_spec
        if definition.contract_version != STEP_DATA_CONTRACT or spec.decision_clock not in (BarFrequency.DAILY, BarFrequency.M30):
            raise ValueError('account planning requires the V5 DFLS step contract')
        if step_data_load is not None and not callable(step_data_load):
            raise TypeError('strategy data requires a host loader')
        if definition.step_data_inputs and step_data_load is None:
            raise ValueError('strategy data requires a host loader')
        if data_cutoff is not None and (type(data_cutoff) is not datetime or data_cutoff.utcoffset() is None):
            raise ValueError('strategy data cutoff must be timezone-aware')
        if prepared.frequency is not spec.decision_clock:
            raise ValueError('prepared decision clock differs from strategy')
        if definition.feature_graph != prepared.graph or spec.data_latency_seconds != prepared._data.latency_seconds:
            raise ValueError('prepared feature/visibility contract differs')
        if not prepared._sessions or not prepared._calendar_intervals:
            raise ValueError('account planning requires explicit session evidence')
        self.candidate, self.prepared = candidate, prepared
        self._performance = performance
        self._step_data_load = step_data_load
        self._data_cutoff = data_cutoff
        self._visibility = _Visibility(prepared._data)
        if prepared._observations or prepared._auxiliary:
            raise ValueError('V5 account planning does not accept preloaded strategy data')
        self._intervals = dict(prepared._calendar_intervals)
        self._observed_at = None
        self._observation_cache = None

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
            return self._observation_cache[1]
        self._observed_at = when
        definition, data, visibility = self.candidate.definition, self.prepared._data, self._visibility
        visibility.advance(when)
        if visibility.count < definition.warmup_bars:
            raise ValueError('WARMUP_INSUFFICIENT: visible observed history')
        point = DecisionPoint(data.ends[visibility.row(0)], when, interval)
        session, available = self.prepared._sessions[self._intervals[key]]
        if session.timezone != self.candidate.instrument.timezone:
            raise ValueError('prepared session timezone differs from instrument')
        if available > when:
            raise ValueError('session calendar is not yet available')
        observation = (point, float(data.rows[visibility.row(0)]['Close']),
                       session, available, not data.observed[visibility.latest_completed])
        self._observation_cache = cache_key, observation
        return observation

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
        point, _, session, available, suppressed = observation
        replay_point = ReplayPoint(point.observed_through, point.decision_at,
            point.execution_interval.start, point.execution_interval.end,
            session.session_date.isoformat(), ExecutionPrecision.BAR_INTERVAL)
        cursor = state.event_cursor + len(events) if next_event_cursor is None else next_event_cursor
        if type(cursor) is not int or cursor < state.event_cursor + len(events):
            raise ValueError('recognized account event cursor cannot regress')
        if suppressed:
            proposal = AccountStepResult(AccountDecision.from_facts(float(portfolio.quantity > 0),
                'unobserved input', facts={'suppressed': True}, next_watch='next observed bar'),
                state.account, state.cycle.values if state.cycle else None)
            return AccountDecisionProposal(proposal, replay_point, state.event_cursor, True)
        from .equity_source_runtime import active_invocation
        scope = (nullcontext() if active_invocation(self.candidate) is not None
                 else self.candidate.bind_replay(performance=self._performance))
        data_cutoff = point.decision_at if self._data_cutoff is None else min(point.decision_at, self._data_cutoff)
        data = StepData(definition.step_data_inputs, as_of=data_cutoff,
                        observed_through=point.observed_through, load=self._step_data_load,
                        source_root=self.candidate.source_root,
                        equity_latency_seconds=spec.data_latency_seconds)
        try:
            with scope:
                context = AccountStepContext(point, portfolio, account, position, definition.parameters,
                    data, budget=budget, events=events,
                    session=session if definition.session_context else None,
                    session_available_at=available if definition.session_context else None)
                proposal = self.candidate.account_step(context, state)
            receipts = data.receipts()
        finally:
            data.close()
        if (portfolio.quantity or proposal.decision.target) and proposal.cycle_values is None:
            raise ValueError('holding/entry requires typed cycle state')
        return AccountDecisionProposal(proposal, replay_point, cursor, data_reads=receipts)
