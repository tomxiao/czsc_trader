"""Pure signal transitions for two fixed S013 contracts; no execution or cash."""
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite


class SignalKind(str, Enum):
    ORIGINAL_TIME = 'ORIGINAL_TIME'
    MEAN_BEAR_TIME_BELOW_CLOSE = 'MEAN_BEAR_TIME_BELOW_CLOSE'


ROUTES = ('bull', 'bear')
EXIT_REASONS = ('range', 'time', 'regime')
CATEGORIES = ('BELOW', 'EQUAL', 'ABOVE')


def _finite(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(name + ' must be a finite number')
    if positive and value <= 0:
        raise ValueError(name + ' must be positive')


@dataclass(frozen=True)
class RouteRule:
    entry: float
    exit: float
    max_hold: int
    acf_min: float | None = None

    def __post_init__(self):
        _finite(self.entry, 'entry')
        _finite(self.exit, 'exit')
        if not 0 <= self.entry < self.exit <= 1:
            raise ValueError('0 <= entry < exit <= 1 required')
        if type(self.max_hold) is not int or not 1 <= self.max_hold <= 60:
            raise ValueError('max_hold must be integer 1..60')
        if self.acf_min is not None:
            _finite(self.acf_min, 'acf_min')


@dataclass(frozen=True)
class Feature:
    raw_route: str
    signal_close: float
    previous_signal_close: float
    bull_range_position: float
    bear_range_position: float
    bull_acf_value: float
    bear_acf_value: float
    confirmation_score: float
    confirmation_threshold: float
    bull_rule: RouteRule
    bear_rule: RouteRule

    def __post_init__(self):
        if self.raw_route not in ROUTES:
            raise ValueError('raw_route must be bull or bear')
        if not isinstance(self.bull_rule, RouteRule) or not isinstance(self.bear_rule, RouteRule):
            raise TypeError('typed RouteRule required')
        for name in ('signal_close', 'previous_signal_close'):
            _finite(getattr(self, name), name, positive=True)
        for name in ('bull_range_position', 'bear_range_position', 'bull_acf_value', 'bear_acf_value',
                     'confirmation_score', 'confirmation_threshold'):
            _finite(getattr(self, name), name)

    def route_inputs(self, route):
        if route not in ROUTES:
            raise ValueError('route must be bull or bear')
        return (getattr(self, route + '_rule'), getattr(self, route + '_range_position'),
                getattr(self, route + '_acf_value'))


@dataclass(frozen=True)
class SignalState:
    holding: bool = False
    route: str | None = None
    age: int = 0
    entry_anchor: float | None = None
    last_exit_reason: str | None = None
    last_exit_route: str | None = None
    last_exit_category: str | None = None

    def __post_init__(self):
        if type(self.holding) is not bool or type(self.age) is not int or self.age < 0:
            raise ValueError('holding bool and nonnegative integer age required')
        if self.holding:
            if self.route not in ROUTES:
                raise ValueError('held route required')
            if any(value is not None for value in (self.last_exit_reason, self.last_exit_route, self.last_exit_category)):
                raise ValueError('entry must consume all exit context')
            if self.entry_anchor is not None:
                _finite(self.entry_anchor, 'entry_anchor', positive=True)
        else:
            if self.route is not None or self.age != 0 or self.entry_anchor is not None:
                raise ValueError('flat route/anchor inactive and age canonical zero required')
            if self.last_exit_reason is None:
                if self.last_exit_route is not None or self.last_exit_category is not None:
                    raise ValueError('empty exit reason requires empty route/category')
            else:
                if self.last_exit_reason not in EXIT_REASONS or self.last_exit_route not in ROUTES:
                    raise ValueError('complete supported final exit context required')
                bear_time = self.last_exit_reason == 'time' and self.last_exit_route == 'bear'
                if bear_time and self.last_exit_category not in CATEGORIES:
                    raise ValueError('bear TIME requires strict price category')
                if not bear_time and self.last_exit_category is not None:
                    raise ValueError('only final bear TIME has price category')

    @property
    def physical(self):
        return self.holding, self.route, self.age


@dataclass(frozen=True)
class Decision:
    target: int
    reason: str
    next_state: SignalState

    def __post_init__(self):
        if type(self.target) is not int or self.target not in (0, 1):
            raise ValueError('binary integer target required')
        if self.reason not in ('flat', 'entry', 'hold', 'range', 'time', 'regime',
                               'entry_direction_rejected', 'confirmation_rejected'):
            raise ValueError('unsupported final reason')
        if not isinstance(self.next_state, SignalState) or self.target != int(self.next_state.holding):
            raise ValueError('target and typed next state disagree')

    def outcome(self, mode):
        if mode == 'target':
            return self.target
        if mode == 'target_reason':
            return self.target, self.reason
        raise ValueError('target or target_reason outcome required')


def validate_parameters(kind: SignalKind, parameters: Mapping):
    """Reject contracts whose rules are absent from this intentionally small kernel."""
    if not isinstance(kind, SignalKind) or not isinstance(parameters, Mapping):
        raise TypeError('SignalKind and parameter mapping required')
    if parameters['exit_on_regime_change'] is not True:
        raise ValueError('original immediate raw-regime exit required')
    confirmation, context = parameters['confirmation'], parameters['context']
    if confirmation['enabled'] is not True or confirmation['profile'] != 'all' or confirmation['scope'] != 'both':
        raise ValueError('enabled/all/both confirmation required')
    if context['entry_gate'] != 'all':
        raise ValueError('confirmation entry_gate all required')
    mechanism = parameters.get('mechanism')
    if (kind == SignalKind.ORIGINAL_TIME and mechanism is not None or
            kind == SignalKind.MEAN_BEAR_TIME_BELOW_CLOSE and mechanism != kind.value):
        raise ValueError('exact fixed mechanism required')
    rules = []
    for route in ROUTES:
        rp = parameters[route]
        if any(rp[name] is not None for name in ('stop_loss', 'trailing_stop', 'momentum_min')):
            raise ValueError('stop/trail/momentum filters must be null')
        if type(rp['cooldown']) is not int or rp['cooldown'] != 0:
            raise ValueError('zero cooldown required')
        rules.append(RouteRule(rp['entry'], rp['exit'], rp['max_hold'], rp['acf_min']))
    return tuple(rules)


def step(kind: SignalKind, state: SignalState, feature: Feature) -> Decision:
    if not isinstance(kind, SignalKind) or not isinstance(state, SignalState) or not isinstance(feature, Feature):
        raise TypeError('typed SignalKind/SignalState/Feature required')
    is_new = kind == SignalKind.MEAN_BEAR_TIME_BELOW_CLOSE
    if not is_new and any(value is not None for value in
                          (state.entry_anchor, state.last_exit_reason, state.last_exit_route, state.last_exit_category)):
        raise ValueError('original decision state has no anchor/exit memory')
    if is_new and state.holding and state.entry_anchor is None:
        raise ValueError('new holding state requires its own positive signal entry anchor')
    if state.holding:
        rule, position, _ = feature.route_inputs(state.route)
        age = state.age + 1
        reason = ('range' if position >= rule.exit else 'time' if age >= rule.max_hold else
                  'regime' if feature.raw_route != state.route else None)
        if reason is None:
            return Decision(1, 'hold', SignalState(True, state.route, age, state.entry_anchor))
        if not is_new:
            return Decision(0, reason, SignalState())
        category = None
        if reason == 'time' and state.route == 'bear':
            category = ('BELOW' if feature.signal_close < state.entry_anchor else
                        'ABOVE' if feature.signal_close > state.entry_anchor else 'EQUAL')
        return Decision(0, reason, SignalState(last_exit_reason=reason,
            last_exit_route=state.route, last_exit_category=category))
    rule, position, acf = feature.route_inputs(feature.raw_route)
    eligible = position <= rule.entry and (rule.acf_min is None or acf >= rule.acf_min)
    if not eligible:
        return Decision(0, 'flat', state)
    gate = (is_new and feature.raw_route == 'bear' and state.last_exit_reason == 'time'
            and state.last_exit_route == 'bear' and state.last_exit_category == 'BELOW')
    if gate and feature.signal_close <= feature.previous_signal_close:
        return Decision(0, 'entry_direction_rejected', state)
    if feature.confirmation_score < feature.confirmation_threshold:
        return Decision(0, 'confirmation_rejected', state)
    return Decision(1, 'entry', SignalState(True, feature.raw_route, 0,
        feature.signal_close if is_new else None))


def _date(value, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        if value.utcoffset() is not None:
            raise ValueError('naive native date required')
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value).isoformat()
    raise TypeError('native date/date ISO string required')


@dataclass(frozen=True)
class Trace:
    kind: SignalKind
    features: tuple[Feature, ...]
    before: tuple[SignalState, ...]
    after: tuple[SignalState, ...]
    decisions: tuple[Decision, ...]
    signal_dates: tuple[str, ...]
    execution_dates: tuple[str | None, ...]

    @property
    def tail_state(self):
        return self.after[-1]


def trace(kind: SignalKind, features: Sequence[Feature], certified_targets: Sequence,
          reasons: Sequence[str], signal_dates: Sequence, execution_dates: Sequence) -> Trace:
    """Replay signal state only; certify every own target and final reason exactly."""
    features = tuple(features)
    signals = tuple(_date(value) for value in signal_dates)
    executions = tuple(_date(value, nullable=True) for value in execution_dates)
    size = len(features)
    if not size or any(len(values) != size for values in (certified_targets, reasons, signals, executions)):
        raise ValueError('nonempty complete native signal arrays required')
    if list(signals) != sorted(set(signals)):
        raise ValueError('all native signal dates unique/ordered required')
    valid = [value for value in executions if value is not None]
    if valid != sorted(set(valid)):
        raise ValueError('valid execution dates unique/ordered required')
    if any(execution is not None and execution <= signal
           for signal, execution in zip(signals, executions, strict=True)):
        raise ValueError('execution session must strictly follow its signal date')
    state = SignalState()
    before, after, decisions = [], [], []
    for index, feature in enumerate(features):
        before.append(state)
        decision = step(kind, state, feature)
        wanted = certified_targets[index]
        _finite(wanted, 'certified target')
        if wanted not in (0, 1) or decision.target != wanted or decision.reason != reasons[index]:
            raise ValueError('own native target/reason mismatch at signal ' + signals[index])
        decisions.append(decision)
        state = decision.next_state
        after.append(state)
    return Trace(kind, features, tuple(before), tuple(after), tuple(decisions), signals, executions)


def state_dict(state: SignalState):
    if not isinstance(state, SignalState):
        raise TypeError('typed SignalState required')
    return asdict(state)
