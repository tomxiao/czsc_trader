"""Batch projection of immutable V4 sources; no execution or strategy selection."""
from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from dataflows import BarFrequency
from dataflows.equity_data import sessions_from_metadata
from strategy_evaluator.research_models import ClosedCycle, EvaluationScenarioContext
from strategy_evaluator.selection_models import (
    EquityWindowProjectionRequest, SelectionCandidateSource,
    WindowEquityPoint, WindowObservationTime,
)
from strategy_evaluator.selection_stability import project_equity_windows
from strategy_runtime import canonical_sha256

from ..research_tools.selection_stability import (
    SelectionProjectionStats, SelectionProjectionStatus, SelectionSourceFailure,
    SelectionWindowFactsRequest, SelectionWindowFactsResult,
)
from .context import RepositoryContext
from .selection_source_reader import SelectionSourceBudgetError, SelectionSourceReader


def _projection(source, run, source_id, request, expected):
    saved = source.header["request"]
    market = saved["instrument"]["market"]
    zone = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
    # Missing/stale valuations are coverage gaps, not genuine equity observations.
    if type(run) is not dict or any(type(run.get(name)) is not list
            or any(type(row) is not dict for row in run[name]) for name in ("account_points", "trades")):
        raise ValueError("saved account observations and trades require arrays of objects")
    rows = run["account_points"]
    points = tuple(WindowEquityPoint(r["time"], r["session"], float(r["equity"]))
                   for r in rows if r.get("bar_status", "OBSERVED") != "MISSING"
                   and not r.get("valuation_stale", False))
    cycles = tuple(ClosedCycle(r["cycle_id"],
                   datetime.fromisoformat(r["exit_at"]).astimezone(zone).date().isoformat())
                   for r in run["trades"])
    return EquityWindowProjectionRequest(
        source_id, market, saved["specification"]["account"]["currency"],
        saved["drawdown_basis"], float(saved["initial_cash"]),
        expected[0].session, points, cycles, expected, request.plan,
        request.frequency_window_days, request.minimum_closed_cycles)


def _expected(source):
    saved = source.header["request"]
    start, end = (datetime.fromisoformat(saved["window"][k]) for k in ("start", "end"))
    sessions = sessions_from_metadata(source.inputs["data"]["sessions"]["metadata"])
    frequency = BarFrequency(saved["specification"]["decision_clock"])
    expected = tuple(WindowObservationTime(bar.end.isoformat(), session.session_date.isoformat())
                     for session in sessions for bar in session.bars(frequency)
                     if bar.start >= start and bar.end <= end)
    if not expected:
        raise ValueError("saved source has no declared observation intervals")
    return expected


def _binding(source, declared, request):
    saved = source.header["request"]
    identity = f'{saved["experiment"]["strategy_id"]}-{saved["candidate_id"]}'
    if (identity, saved["content_sha256"]) != (
            declared.candidate.candidate_id, declared.candidate.content_sha256):
        raise ValueError("evaluation differs from declared candidate identity")
    evaluation = source.header["evaluation_identity"]
    if (evaluation["candidate"] != {"strategy_id": saved["experiment"]["strategy_id"],
                                    "candidate_id": saved["candidate_id"]}
            or evaluation["content_sha256"] != declared.candidate.content_sha256):
        raise ValueError("saved account owner differs from declared candidate identity")
    if saved["measurement_tier"] != "FORMAL" or saved["scenario_id"] != "STANDARD":
        raise ValueError("selection projection requires a standard formal source")
    context = canonical_sha256({
        "primary_input": source.primary_input_sha256,
        **{key: saved[key] for key in ("instrument", "specification", "window", "history_start",
            "initial_cash", "benchmark_sha256", "fee_rate", "drawdown_basis", "engine_sources",
            "python_version", "pandas_version")},
        "calendar": request.plan.calendar_sha256,
        "frequency_window_days": request.frequency_window_days,
        "minimum_closed_cycles": request.minimum_closed_cycles,
    })
    benchmark_id = source.header["benchmark_ref"]["sha256"]
    return SelectionCandidateSource(declared.candidate, declared.evaluation.sha256,
        benchmark_id, context, EvaluationScenarioContext(float(saved["fee_rate"]),
        saved["measurement_tier"], saved["benchmark"]["benchmark_id"],
        saved["benchmark"]["kind"], saved["benchmark_sha256"]))


def project_selection_window_facts(repository: RepositoryContext,
                                   request: SelectionWindowFactsRequest) -> SelectionWindowFactsResult:
    """Read the explicit universe once and project all unique windows per account.

    Source failures remain explicit and prohibit constructing a reduced-universe
    analysis through result.analysis_request. Coverage gaps remain per-window facts.
    """
    if type(repository) is not RepositoryContext or type(request) is not SelectionWindowFactsRequest:
        raise TypeError("selection projection requires RepositoryContext and SelectionWindowFactsRequest")
    started = perf_counter()
    windows = request.plan.windows
    if len(request.sources) * len(windows) > request.budget.max_window_facts:
        raise ValueError("selection window fact budget exceeded")
    sources, facts, failures = [], [], []
    projected = set()
    calendars = {}
    projection_seconds = 0.0
    observation_points = window_point_visits = frequency_subwindows = 0
    with SelectionSourceReader(repository.root, max_source_bytes=request.budget.max_source_bytes,
                               max_shared_bytes=request.budget.max_shared_bytes) as reader:
        reader.prepare(tuple(item.evaluation for item in request.sources))
        if (len(request.sources) + reader.unique_benchmark_count) * len(windows) > request.budget.max_window_facts:
            raise ValueError("selection window fact budget exceeded (including unique benchmarks)")
        for declared in request.sources:
            try:
                source = reader.read(declared.evaluation)
                binding = _binding(source, declared, request)
                saved = source.header["request"]
                calendar_key = (source.primary_input_sha256, saved["window"]["start"],
                                saved["window"]["end"], saved["specification"]["decision_clock"])
                if calendar_key not in calendars:
                    calendars[calendar_key] = _expected(source)
                expected = calendars[calendar_key]
                pending = []
                elapsed = perf_counter()
                for source_id, run in ((binding.source_id, source.candidate_run),
                                       (binding.benchmark_source_id, source.benchmark_run)):
                    if source_id in projected:
                        continue
                    projection = _projection(source, run, source_id, request, expected)
                    account_facts = project_equity_windows(projection)
                    pending.append((source_id, account_facts))
                    observation_points += len(projection.observations)
                    for window in windows:
                        window_point_visits += sum(window.start_session <= p.session <= window.end_session
                                                   for p in projection.observations)
                        days = sum(window.start_session <= d <= window.end_session for d in request.plan.calendar)
                        frequency_subwindows += max(0, days - request.frequency_window_days + 1)
                projection_seconds += perf_counter() - elapsed
                for source_id, account_facts in pending:
                    facts.extend(account_facts)
                    projected.add(source_id)
                sources.append(binding)
                del source
            except SelectionSourceBudgetError:
                raise
            except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
                failures.append(SelectionSourceFailure(declared, f"{type(exc).__name__}: {exc}"))
        stats = reader.stats
    measured = SelectionProjectionStats(stats.source_bytes, stats.shared_bytes, stats.read_count,
        stats.decode_count, stats.read_seconds, stats.decode_seconds, float(projection_seconds),
        float(perf_counter() - started), len(projected), len(facts), observation_points,
        window_point_visits, frequency_subwindows)
    return SelectionWindowFactsResult(request,
        SelectionProjectionStatus.SOURCE_FAILED if failures else SelectionProjectionStatus.COMPLETE,
        tuple(sources), tuple(facts), tuple(failures), measured)
