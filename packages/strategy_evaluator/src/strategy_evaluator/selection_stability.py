"""Fixed-universe retrospective selection: preceding facts decide, later facts observe."""

import math
from collections import Counter, defaultdict
from statistics import median

from . import research_models as m
from .research_acceptance import _coverage, _scalar, acceptance_status
from .research_assessment import _bin
from .selection_projection import project_equity_windows  # noqa: F401 - public numeric entry point
from .selection_models import (
    SelectionAnalysisStatus, SelectionCandidateCheck, SelectionCandidateSummary, SelectionDecision,
    SelectionDirection, SelectionDistribution, SelectionNoFilter, SelectionObservation, SelectionStabilityRequest,
    SelectionStabilityResult, SelectionStatus, WindowCoverageStatus,
)


def _metrics(fact):
    return {x.metric: x for x in fact.diagnostics} if fact and fact.status is WindowCoverageStatus.COMPLETE else {}


def _value(fact, metric):
    item = _metrics(fact).get(metric)
    return None if item is None else item.value


def _checks(targets, fact, benchmark, source, rule):
    if type(targets) is SelectionNoFilter:
        return ()
    checks = []
    for target in targets.requirements:
        if type(target) is m.FrequencyCoverageTarget:
            checks.append(_coverage(target, fact, rule.frequency_window_days)
                          if fact and fact.status is WindowCoverageStatus.COMPLETE else
                          m.FrequencyCoverageCheck(target, None, m.TargetCheckStatus.INDETERMINATE,
                                                   "MISSING_FREQUENCY_COVERAGE"))
        else:
            checks.append(_scalar(target, _metrics(fact), _metrics(benchmark), source.scenario_context,
                                  rule.frequency_window_days, rule.frequency_window_days))
    return tuple(checks)


def _ordering(fact, rule):
    values = tuple(_value(fact, order.metric) for order in rule.order)
    if any(value is None for value in values):
        return None
    return tuple(_bin(value, order.bin_spec) if order.bin_spec else value
                 for value, order in zip(values, rule.order))


def _key(values, rule):
    return tuple(-value if order.direction is SelectionDirection.MAXIMIZE else value
                 for value, order in zip(values, rule.order))


def _select(pair_id, window_id, sources, facts, rule):
    # This function receives only the selected window's facts. Observation data cannot enter.
    checks = []
    for source in sources:
        fact, benchmark = facts.get(source.source_id), facts.get(source.benchmark_source_id)
        targets = _checks(rule.targets, fact, benchmark, source, rule)
        status = (m.TargetCheckStatus.PASSED if type(rule.targets) is SelectionNoFilter else
                  acceptance_status(targets))
        ordering = _ordering(fact, rule)
        reason = None
        if status is not m.TargetCheckStatus.FAILED and ordering is None:
            status, reason = m.TargetCheckStatus.INDETERMINATE, "MISSING_SELECTION_ORDERING"
        elif status is m.TargetCheckStatus.INDETERMINATE:
            reason = "INDETERMINATE_SELECTION_CONDITIONS"
        elif status is m.TargetCheckStatus.FAILED:
            reason = "SELECTION_CONDITIONS_NOT_MET"
        checks.append(SelectionCandidateCheck(source.candidate, targets, status, reason, ordering or ()))
    eligible = tuple(x.candidate for x in checks if x.status is m.TargetCheckStatus.PASSED)
    eligible_set = set(eligible)
    selected = ()
    if any(x.status is m.TargetCheckStatus.INDETERMINATE for x in checks):
        status = SelectionStatus.INSUFFICIENT_SELECTION_EVIDENCE
    elif not eligible:
        status = SelectionStatus.NO_ELIGIBLE_CANDIDATE
    else:
        status = SelectionStatus.SELECTED
        best = min(_key(x.ordering_values, rule) for x in checks if x.candidate in eligible_set)
        selected = tuple(x.candidate for x in checks
                         if x.candidate in eligible_set and _key(x.ordering_values, rule) == best)
    return SelectionDecision(pair_id, window_id, status, tuple(checks), eligible, selected)


def _difference(left, right):
    if left is None or right is None:
        return None
    value = left - right
    return value if math.isfinite(value) else None


def _distribution(observations, field):
    values = [getattr(o, field) for o in observations if getattr(o, field) is not None]
    return SelectionDistribution(len(values), len(observations), min(values) if values else None,
                                 float(median(values)) if values else None, max(values) if values else None)


def assess_selection_stability(request: SelectionStabilityRequest) -> SelectionStabilityResult:
    """Compute a report only; never certify stability, read accounts or rerun research."""
    m.require(type(request) is SelectionStabilityRequest, "typed selection request required")
    sources = tuple(sorted(request.sources, key=lambda x: x.candidate.candidate_id))
    bindings = {s.candidate: s for s in sources}
    facts = {(x.source_id, x.window.window_id): x for x in request.facts}
    by_window = defaultdict(dict)
    for fact in request.facts:
        by_window[fact.window.window_id][fact.source_id] = fact
    decisions, observations = [], []
    primary = request.rule.order[0].metric
    targets = request.observation_targets if request.observation_targets is not None else request.rule.targets
    for pair in request.plan.pairs:
        selection_facts = by_window[pair.selection.window_id]
        decision = _select(pair.pair_id, pair.selection.window_id, sources, selection_facts, request.rule)
        decisions.append(decision)
        if not decision.selected:
            continue
        observed = {c: facts.get((bindings[c].source_id, pair.observation.window_id)) for c in decision.eligible}
        orderings = {c: _ordering(fact, request.rule) for c, fact in observed.items()}
        rank_reason = ("SINGLE_ELIGIBLE_CANDIDATE" if len(decision.eligible) == 1 else
                       "INCOMPLETE_OBSERVATION_REFERENCE" if any(x is None for x in orderings.values()) else None)
        ranks = {}
        if rank_reason is None:
            counts = Counter(_key(x, request.rule) for x in orderings.values())
            before = 0
            for key in sorted(counts):
                ranks[key] = (before + 1, before + counts[key])
                before += counts[key]
        for candidate in decision.selected:
            source, fact = bindings[candidate], observed[candidate]
            benchmark = facts.get((source.benchmark_source_id, pair.observation.window_id))
            checks = _checks(targets, fact, benchmark, source, request.rule)
            value, bench = _value(fact, primary), _value(benchmark, primary)
            status = (m.TargetCheckStatus.PASSED if value is not None else m.TargetCheckStatus.INDETERMINATE
                      ) if type(targets) is SelectionNoFilter else acceptance_status(checks)
            rank_min, rank_max = ranks[_key(orderings[candidate], request.rule)] if rank_reason is None else (None, None)
            observations.append(SelectionObservation(
                pair.pair_id, candidate, pair.observation.window_id, checks, status,
                value, bench, _difference(value, bench),
                _difference(value, _value(selection_facts.get(source.source_id), primary)),
                rank_min, rank_max, len(decision.eligible), rank_reason,
            ))
    planned = len(decisions)
    insufficient = sum(d.status is SelectionStatus.INSUFFICIENT_SELECTION_EVIDENCE for d in decisions)
    selected = sum(d.status is SelectionStatus.SELECTED for d in decisions)
    incomplete = len({o.pair_id for o in observations if o.acceptance_status is m.TargetCheckStatus.INDETERMINATE
                      or o.primary_value is None
                      or (bindings[o.candidate].benchmark_source_id is not None and o.benchmark_primary_value is None)})
    rank_incomplete = len({o.pair_id for o in observations if o.rank_reason == "INCOMPLETE_OBSERVATION_REFERENCE"})
    values = [o.primary_value for o in observations if o.primary_value is not None]
    worst = (min(values) if request.rule.order[0].direction is SelectionDirection.MAXIMIZE else max(values)) if values else None
    limitations = tuple(dict.fromkeys((*request.plan.limitations,
        "RETROSPECTIVE_FIXED_CANDIDATES_NOT_INDEPENDENT_SEARCH_VALIDATION",
        "OVERLAPPING_WINDOWS_ARE_NOT_INDEPENDENT_SAMPLES")))
    selected_counts = Counter(c for d in decisions for c in d.selected)
    return SelectionStabilityResult(
        request.sha256, SelectionAnalysisStatus.PARTIAL if insufficient or incomplete or rank_incomplete else SelectionAnalysisStatus.COMPLETE,
        tuple(decisions), tuple(observations),
        tuple(SelectionCandidateSummary(s.candidate, selected_counts[s.candidate],
                                        planned, planned - insufficient) for s in sources),
        planned, selected, sum(d.status is SelectionStatus.NO_ELIGIBLE_CANDIDATE for d in decisions),
        insufficient, incomplete, rank_incomplete,
        sum(o.acceptance_status is m.TargetCheckStatus.PASSED for o in observations),
        sum(o.acceptance_status is m.TargetCheckStatus.FAILED for o in observations),
        sum(o.acceptance_status is m.TargetCheckStatus.INDETERMINATE for o in observations),
        min(values) if values else None, float(median(values)) if values else None, max(values) if values else None,
        tuple(dict.fromkeys(o.pair_id for o in observations if worst is not None and o.primary_value == worst)),
        limitations,
        _distribution(observations, "primary_value"), _distribution(observations, "excess_primary"),
        _distribution(observations, "primary_change"),
    )
