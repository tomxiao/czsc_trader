"""Pure projections of an inherited account onto explicitly declared session windows."""

from collections import Counter, defaultdict
from datetime import datetime
import math

import numpy as np

from . import research_models as m
from .research_acceptance import _calmar_value
from .selection_models import (
    AccountWindowFacts, EquityWindowProjectionRequest, SELECTION_METRICS, WindowCoverageStatus,
)


def _diagnostic(source_id, metric, value, reason):
    return m.DiagnosticValue(
        metric,
        m.MetricUnit.CLOSED_CYCLES_PER_WINDOW if metric in m.FREQUENCY_METRICS
        and metric is not m.ResearchMetric.FREQUENCY_COVERAGE else m.MetricUnit.RATIO,
        m.DiagnosticStatus.AVAILABLE if value is not None else m.DiagnosticStatus.INSUFFICIENT_DATA,
        value, None if value is not None else reason, (source_id,),
    )


def project_equity_windows(request: EquityWindowProjectionRequest) -> tuple[AccountWindowFacts, ...]:
    """Project recorded equity once; never execute a strategy or create an account."""
    m.require(type(request) is EquityWindowProjectionRequest, "typed equity projection request required")
    expected, observed = defaultdict(list), defaultdict(list)
    for point in request.expected_points:
        expected[point.session].append(datetime.fromisoformat(point.time))
    for point in request.observations:
        observed[point.session].append((datetime.fromisoformat(point.time), point.equity))
    calendar = request.plan.calendar
    indexes = {session: i for i, session in enumerate(calendar)}
    source_sessions = sorted(set(expected) | set(calendar))
    predecessors = dict(zip(source_sessions[1:], source_sessions[:-1]))
    close_complete = {
        session: bool(expected[session]) and bool(observed[session])
        and observed[session][-1][0] == expected[session][-1]
        for session in source_sessions
    }
    complete = {
        session: bool(expected[session])
        and ([time for time, _ in observed[session]] == expected[session]
             if request.drawdown_basis == "BAR_CLOSE" else close_complete[session])
        for session in source_sessions
    }
    exits = Counter(c.exit_session for c in request.closed_cycles)
    prefix = np.concatenate(([0], np.cumsum([exits[s] for s in calendar], dtype=np.int64)))
    result = []
    for window in request.plan.windows:
        start, stop = indexes[window.start_session], indexes[window.end_session] + 1
        sessions = calendar[start:stop]
        n = len(sessions)
        count = sum(complete[s] for s in sessions)
        previous = predecessors.get(window.start_session)
        opening = (request.initial_equity if window.start_session == request.source_start_session else
                   observed[previous][-1][1] if previous and close_complete[previous] else None)
        reason = "INCOMPLETE_WINDOW_OBSERVATIONS" if count != n else (
            "MISSING_PREVIOUS_SESSION_CLOSE" if opening is None else None)
        if reason:
            result.append(AccountWindowFacts(
                request.source_id, window, WindowCoverageStatus.INSUFFICIENT_DATA, reason,
                n, count, opening, None, None,
                tuple(_diagnostic(request.source_id, metric, None, reason) for metric in SELECTION_METRICS),
                None,
            ))
            continue
        path = [opening]
        for session in sessions:
            values = [equity for _, equity in observed[session]]
            path.extend(values if request.drawdown_basis == "BAR_CLOSE" else values[-1:])
        ending = path[-1]
        period = ending / opening - 1.0
        try:
            annual = math.expm1((math.log(ending) - math.log(opening)) * 252 / n)
        except OverflowError:
            annual = None
        values = np.asarray(path)
        drawdown = float(np.max(1 - values / np.maximum.accumulate(values)))
        days = request.frequency_window_days
        counts = prefix[start + days:stop + 1] - prefix[start:stop - days + 1] if n >= days else np.array([])
        total = len(counts)
        covered = int(np.sum(counts >= request.minimum_closed_cycles))
        numbers = (annual, _calmar_value(annual, drawdown), drawdown,
                   float(np.median(counts)) if total else None,
                   float(np.quantile(counts, .1, method="linear")) if total else None,
                   covered / total if total else None)
        result.append(AccountWindowFacts(
            request.source_id, window, WindowCoverageStatus.COMPLETE, None, n, count,
            opening, ending, period if math.isfinite(period) else None,
            tuple(_diagnostic(request.source_id, metric, value,
                              "INSUFFICIENT_FREQUENCY_WINDOW" if metric in (
                                  *m.FREQUENCY_METRICS, m.ResearchMetric.FREQUENCY_COVERAGE)
                              else "CALMAR_UNAVAILABLE" if metric is m.ResearchMetric.NET_CALMAR
                              else "NONFINITE_ANNUAL_RETURN")
                  for metric, value in zip(SELECTION_METRICS, numbers)),
            m.FrequencyCoverageFacts(days, request.minimum_closed_cycles, total, covered, (request.source_id,)),
        ))
    return tuple(result)
