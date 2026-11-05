"""Typed retrospective window observations and selection decisions, not new accounts."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from functools import cached_property
import math
from zoneinfo import ZoneInfo

from . import research_models as m
from .models import ValidationError


SELECTION_METRICS = (
    m.ResearchMetric.NET_ANNUAL_RETURN, m.ResearchMetric.NET_CALMAR,
    m.ResearchMetric.DRAWDOWN_MAGNITUDE, m.ResearchMetric.FREQUENCY_MEDIAN,
    m.ResearchMetric.FREQUENCY_Q10, m.ResearchMetric.FREQUENCY_COVERAGE,
)


class UnsupportedSelectionRule(ValidationError):
    """The declared rule cannot be faithfully represented by this implementation."""


class WindowCoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SOURCE_FAILED = "SOURCE_FAILED"


class SelectionStatus(StrEnum):
    SELECTED = "SELECTED"
    NO_ELIGIBLE_CANDIDATE = "NO_ELIGIBLE_CANDIDATE"
    INSUFFICIENT_SELECTION_EVIDENCE = "INSUFFICIENT_SELECTION_EVIDENCE"


class SelectionAnalysisStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class SelectionDirection(StrEnum):
    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"


@dataclass(frozen=True)
class SelectionWindow(m.ResearchRecord):
    window_id: str
    start_session: str
    end_session: str

    def validate(self):
        date.fromisoformat(self.start_session)
        date.fromisoformat(self.end_session)
        m.require(self.start_session <= self.end_session, "reversed selection window")


@dataclass(frozen=True)
class SelectionWindowPair(m.ResearchRecord):
    pair_id: str
    selection: SelectionWindow
    observation: SelectionWindow

    def validate(self):
        m.require(self.selection.end_session < self.observation.start_session,
                  "selection must precede observation")


@dataclass(frozen=True)
class SelectionWindowPlan(m.ResearchRecord):
    calendar: tuple[str, ...]
    calendar_sha256: str
    pairs: tuple[SelectionWindowPair, ...]
    limitations: tuple[str, ...]
    mode: str = "RETROSPECTIVE_FIXED_CANDIDATES"

    def validate(self):
        m.require(self.mode == "RETROSPECTIVE_FIXED_CANDIDATES", "unsupported selection study mode")
        m.require(bool(self.calendar) and bool(self.pairs), "calendar and window pairs required")
        for session in self.calendar:
            date.fromisoformat(session)
        m.require(tuple(sorted(set(self.calendar))) == self.calendar, "calendar must be unique and ordered")
        m.require(self.calendar_sha256 == m.digest(self.calendar), "calendar digest differs")
        m.unique((x.pair_id for x in self.pairs), "selection pair")
        known = {}
        for pair in self.pairs:
            for window in (pair.selection, pair.observation):
                m.require(window.start_session in self.calendar and window.end_session in self.calendar,
                          "window boundary outside declared calendar")
                m.require(window.window_id not in known or known[window.window_id] == window,
                          "window identity conflict")
                known[window.window_id] = window

    @cached_property
    def windows(self):
        return tuple(dict.fromkeys(w for p in self.pairs for w in (p.selection, p.observation)))


@dataclass(frozen=True)
class WindowObservationTime(m.ResearchRecord):
    time: str
    session: str

    def validate(self):
        stamp = datetime.fromisoformat(self.time)
        m.require(stamp.tzinfo is not None, "observation timestamp must include timezone")
        date.fromisoformat(self.session)


@dataclass(frozen=True)
class WindowEquityPoint(m.ResearchRecord):
    time: str
    session: str
    equity: float

    def validate(self):
        WindowObservationTime(self.time, self.session)
        m.require(self.equity > 0, "window equity must be positive")


@dataclass(frozen=True)
class EquityWindowProjectionRequest(m.ResearchRecord):
    source_id: str
    market: str
    currency: str
    drawdown_basis: str
    initial_equity: float
    source_start_session: str
    observations: tuple[WindowEquityPoint, ...]
    closed_cycles: tuple[m.ClosedCycle, ...]
    expected_points: tuple[WindowObservationTime, ...]
    plan: SelectionWindowPlan
    frequency_window_days: int
    minimum_closed_cycles: int

    def validate(self):
        m.require((self.market, self.currency) in {("CN", "CNY"), ("US", "USD")},
                  "unsupported window market/currency")
        m.require(self.drawdown_basis in {"BAR_CLOSE", "SESSION_CLOSE"}, "unsupported drawdown basis")
        m.require(self.initial_equity > 0, "positive initial equity required")
        date.fromisoformat(self.source_start_session)
        m.require(self.frequency_window_days > 0 and self.minimum_closed_cycles > 0,
                  "positive frequency definition required")
        zone = ZoneInfo("Asia/Shanghai" if self.market == "CN" else "America/New_York")
        for points in (self.expected_points, self.observations):
            stamps = tuple(datetime.fromisoformat(p.time) for p in points)
            m.require(tuple(sorted(set(stamps))) == stamps, "observation timestamps must be unique and ordered")
            m.require(all(datetime.fromisoformat(p.time).astimezone(zone).date().isoformat() == p.session
                          for p in points), "observation local session differs")
        expected = {(datetime.fromisoformat(p.time), p.session) for p in self.expected_points}
        m.require(bool(self.expected_points) and self.source_start_session == self.expected_points[0].session,
                  "source start must equal first expected session")
        calendar_sessions = set(self.plan.calendar)
        m.require(all(point.session in calendar_sessions for point in self.expected_points
                      if self.plan.calendar[0] <= point.session <= self.plan.calendar[-1]),
                  "declared calendar omits known expected session")
        m.require(all((datetime.fromisoformat(p.time), p.session) in expected for p in self.observations),
                  "unexpected account observation")
        m.unique((x.cycle_id for x in self.closed_cycles), "closed cycle")


@dataclass(frozen=True)
class AccountWindowFacts(m.ResearchRecord):
    source_id: str
    window: SelectionWindow
    status: WindowCoverageStatus
    reason: str | None
    expected_sessions: int
    observed_sessions: int
    opening_equity: float | None
    ending_equity: float | None
    period_return: float | None
    diagnostics: tuple[m.DiagnosticValue, ...]
    frequency_coverage: m.FrequencyCoverageFacts | None

    def validate(self):
        m.require(self.expected_sessions > 0 and 0 <= self.observed_sessions <= self.expected_sessions,
                  "invalid window coverage count")
        m.require((self.status is WindowCoverageStatus.COMPLETE) == (self.reason is None),
                  "window coverage reason differs")
        m.unique((x.metric for x in self.diagnostics), "window metric")
        m.require(all(x.metric in SELECTION_METRICS for x in self.diagnostics), "unsupported window metric")
        m.require(all(x is None or x > 0 for x in (self.opening_equity, self.ending_equity)),
                  "window equity must be positive")
        if self.status is WindowCoverageStatus.COMPLETE:
            m.require(self.observed_sessions == self.expected_sessions
                      and self.opening_equity is not None and self.ending_equity is not None,
                      "complete window requires full equity coverage")


@dataclass(frozen=True)
class SelectionCandidateSource(m.ResearchRecord):
    candidate: m.AssessmentCandidate
    source_id: str
    benchmark_source_id: str
    context_sha256: str
    scenario_context: m.EvaluationScenarioContext


@dataclass(frozen=True)
class SelectionNoFilter(m.ResearchRecord):
    """Explicitly perform objective selection without hard filtering."""


@dataclass(frozen=True)
class SelectionMetricOrder(m.ResearchRecord):
    metric: m.ResearchMetric
    direction: SelectionDirection
    bin_spec: m.MetricBinSpec | None = None

    def validate(self):
        if self.metric not in SELECTION_METRICS:
            raise UnsupportedSelectionRule("unsupported selection ordering metric")
        m.require(self.bin_spec is None or self.bin_spec.metric is self.metric, "ordering bin metric differs")


def validate_selection_targets(targets, frequency_window_days, minimum_closed_cycles):
    if type(targets) is SelectionNoFilter:
        return
    m.require(targets.frequency_window_days == frequency_window_days, "selection frequency window differs")
    m.require(bool(targets.requirements), "use explicit SelectionNoFilter for no hard conditions")
    for target in targets.requirements:
        if type(target) is m.FrequencyCoverageTarget:
            m.require(target.minimum_closed_cycles == minimum_closed_cycles,
                      "selection minimum closed cycles differs")
        elif type(target) is not m.ResearchTarget or target.scope is not m.TargetScope.STANDARD \
                or target.metric not in SELECTION_METRICS:
            raise UnsupportedSelectionRule("selection requires supported standard performance/frequency targets")


@dataclass(frozen=True)
class SelectionRule(m.ResearchRecord):
    version: str
    source_sha256: str
    targets: m.ResearchTargets | SelectionNoFilter
    order: tuple[SelectionMetricOrder, ...]
    frequency_window_days: int = 60
    minimum_closed_cycles: int = 3

    def validate(self):
        m.require(bool(self.order), "selection ordering required")
        if self.order[0].metric not in {m.ResearchMetric.NET_ANNUAL_RETURN, m.ResearchMetric.NET_CALMAR}:
            raise UnsupportedSelectionRule("primary objective must be net annual return or net Calmar")
        m.unique((x.metric for x in self.order), "selection ordering metric")
        m.require(self.frequency_window_days > 0 and self.minimum_closed_cycles > 0,
                  "positive frequency definition required")
        validate_selection_targets(self.targets, self.frequency_window_days, self.minimum_closed_cycles)


@dataclass(frozen=True)
class SelectionStabilityRequest(m.ResearchRecord):
    plan: SelectionWindowPlan
    rule: SelectionRule
    sources: tuple[SelectionCandidateSource, ...]
    facts: tuple[AccountWindowFacts, ...]
    observation_targets: m.ResearchTargets | SelectionNoFilter | None = None

    def validate(self):
        m.require(bool(self.sources), "selection candidate universe required")
        m.unique((x.candidate.candidate_id for x in self.sources), "selection candidate")
        m.require(len({x.context_sha256 for x in self.sources}) == 1
                  and len({x.scenario_context for x in self.sources}) == 1,
                  "selection sources are not one comparable context/scenario")
        m.require(all(x.scenario_context.measurement_tier == "FORMAL" for x in self.sources),
                  "selection requires standard formal accounts")
        m.unique(((x.source_id, x.window.window_id) for x in self.facts), "source window facts")
        windows = {x.window_id: x for x in self.plan.windows}
        source_ids = {identity for x in self.sources for identity in (x.source_id, x.benchmark_source_id)}
        for fact in self.facts:
            m.require(fact.source_id in source_ids and windows.get(fact.window.window_id) == fact.window,
                      "window fact outside declared sources or plan")
            if fact.frequency_coverage is not None:
                m.require((fact.frequency_coverage.window_days, fact.frequency_coverage.minimum_closed_cycles)
                          == (self.rule.frequency_window_days, self.rule.minimum_closed_cycles),
                          "window frequency facts differ from selection rule")
        if self.observation_targets is not None:
            validate_selection_targets(self.observation_targets, self.rule.frequency_window_days,
                                       self.rule.minimum_closed_cycles)


@dataclass(frozen=True)
class SelectionCandidateCheck(m.ResearchRecord):
    candidate: m.AssessmentCandidate
    checks: tuple[m.TargetCheck | m.FrequencyCoverageCheck, ...]
    status: m.TargetCheckStatus
    reason: str | None
    ordering_values: tuple[float | int, ...]


@dataclass(frozen=True)
class SelectionDecision(m.ResearchRecord):
    pair_id: str
    selection_window_id: str
    status: SelectionStatus
    checks: tuple[SelectionCandidateCheck, ...]
    eligible: tuple[m.AssessmentCandidate, ...]
    selected: tuple[m.AssessmentCandidate, ...]


@dataclass(frozen=True)
class SelectionObservation(m.ResearchRecord):
    pair_id: str
    candidate: m.AssessmentCandidate
    observation_window_id: str
    checks: tuple[m.TargetCheck | m.FrequencyCoverageCheck, ...]
    acceptance_status: m.TargetCheckStatus
    primary_value: float | None
    benchmark_primary_value: float | None
    excess_primary: float | None
    primary_change: float | None
    rank_min: int | None
    rank_max: int | None
    reference_size: int
    rank_reason: str | None


@dataclass(frozen=True)
class SelectionCandidateSummary(m.ResearchRecord):
    candidate: m.AssessmentCandidate
    selected_windows: int
    planned_windows: int
    decided_windows: int


@dataclass(frozen=True)
class SelectionDistribution(m.ResearchRecord):
    available_observations: int
    total_observations: int
    minimum: float | None
    median: float | None
    maximum: float | None

    def validate(self):
        m.require(0 <= self.available_observations <= self.total_observations,
                  "invalid selection distribution count")
        m.require(all((value is not None) == (self.available_observations > 0)
                      for value in (self.minimum, self.median, self.maximum)),
                  "selection distribution values and count differ")


@dataclass(frozen=True)
class SelectionStabilityResult(m.ResearchRecord):
    request_sha256: str
    status: SelectionAnalysisStatus
    decisions: tuple[SelectionDecision, ...]
    observations: tuple[SelectionObservation, ...]
    candidates: tuple[SelectionCandidateSummary, ...]
    planned_windows: int
    selected_windows: int
    no_eligible_windows: int
    insufficient_selection_windows: int
    observation_incomplete_windows: int
    ranking_incomplete_windows: int
    passed_observations: int
    failed_observations: int
    indeterminate_observations: int
    primary_min: float | None
    primary_median: float | None
    primary_max: float | None
    worst_pairs: tuple[str, ...]
    limitations: tuple[str, ...]
    primary_distribution: SelectionDistribution
    excess_distribution: SelectionDistribution
    change_distribution: SelectionDistribution
    formula_version: str = "selection-stability-v1"

    def validate(self):
        m.require(self.formula_version == "selection-stability-v1", "unsupported selection result version")
        for value in (self.primary_min, self.primary_median, self.primary_max):
            m.require(value is None or math.isfinite(value), "nonfinite selection summary")
