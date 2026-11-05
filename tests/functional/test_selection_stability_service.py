"""Source association, budgets and coverage using one shared real V4 fixture."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from dataflows import BarFrequency, MarketId
from strategy_evaluator import (
    SelectionDirection, SelectionMetricOrder, SelectionNoFilter, SelectionRule,
    SelectionStatus, SelectionWindow, SelectionWindowPair, SelectionWindowPlan,
    WindowCoverageStatus, assess_selection_stability,
)
from strategy_evaluator import research_models as m
from strategy_runtime import canonical_sha256
from czsc_trader.application import project_selection_window_facts
from czsc_trader.research_tools import (
    SelectionProjectionBudget, SelectionProjectionStatus,
    SelectionWindowFactsRequest, SelectionWindowSource,
)
from test_selection_stability_delivery import _accounts


@pytest.fixture(scope="module")
def saved_selection_accounts(tmp_path_factory):
    """Replay two small accounts once; every test mutation creates separate bytes."""
    root = tmp_path_factory.mktemp("selection-service-sources")
    context, prepared, refs, facts = _accounts(root, MarketId.US, BarFrequency.M30,
        drawdown_basis="SESSION_CLOSE")
    calendar = tuple(f"2026-10-{day}" for day in range(27, 31))
    plan = SelectionWindowPlan(calendar, canonical_sha256(calendar), (
        SelectionWindowPair("pair", SelectionWindow("selection", calendar[0], calendar[1]),
            SelectionWindow("observation", calendar[2], calendar[3])),),
        ("Synthetic four-session source/coverage acceptance",))
    request = SelectionWindowFactsRequest(tuple(SelectionWindowSource(f.candidate, ref)
        for f, ref in zip(facts, refs, strict=True)), plan, 2, 1,
        SelectionProjectionBudget(6, 20_000_000, 20_000_000))
    rule = SelectionRule("fixture-v1", "a" * 64, SelectionNoFilter(), (
        SelectionMetricOrder(m.ResearchMetric.NET_ANNUAL_RETURN, SelectionDirection.MAXIMIZE),), 2, 1)
    return context.repository, request, rule


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _write_header(repository, source, header):
    """Create a hash-valid new source without replacing any original fixture."""
    raw = _encoded(header)
    digest = sha256(raw).hexdigest()
    reference = replace(source.evaluation, sha256=digest, evidence_id=digest + ".json")
    (repository.root / reference.repository_path).write_bytes(raw)
    assert reference.resolve(repository.root).read_bytes() == raw
    return replace(source, evaluation=reference)


def _changed_source(repository, source, field):
    header = json.loads(source.evaluation.resolve(repository.root).read_bytes())
    if field == "request.candidate_id":
        header["request"]["candidate_id"] = "C9999"
    elif field == "request.content_sha256":
        header["request"]["content_sha256"] = "0" * 64
    elif field == "evaluation_identity.candidate":
        header["evaluation_identity"]["candidate"]["candidate_id"] = "C9999"
    else:
        header["evaluation_identity"]["content_sha256"] = "0" * 64
    return _write_header(repository, source, header)


@pytest.mark.parametrize("field", [
    "request.candidate_id", "request.content_sha256",
    "evaluation_identity.candidate", "evaluation_identity.content_sha256",
])
def test_hash_valid_header_with_wrong_candidate_association_is_source_failed(saved_selection_accounts, field):
    repository, original, rule = saved_selection_accounts
    source = _changed_source(repository, original.sources[0], field)
    request = replace(original, sources=(source,))
    result = project_selection_window_facts(repository, request)
    assert result.status is SelectionProjectionStatus.SOURCE_FAILED
    assert result.sources == result.facts == ()
    assert len(result.failures) == 1
    assert result.failures[0].source == source
    with pytest.raises(ValueError, match="SOURCE_FAILED"):
        result.analysis_request(rule)


def test_failed_and_healthy_sources_preserve_facts_without_reducing_selection_universe(saved_selection_accounts):
    repository, original, rule = saved_selection_accounts
    broken = _changed_source(repository, original.sources[0], "evaluation_identity.content_sha256")
    result = project_selection_window_facts(repository,
        replace(original, sources=(broken, original.sources[1])))
    assert result.status is SelectionProjectionStatus.SOURCE_FAILED
    assert len(result.failures) == 1
    assert len(result.sources) == 1
    assert result.sources[0].candidate == original.sources[1].candidate
    assert len(result.facts) == 4  # Healthy candidate and shared benchmark, two windows each.
    assert all(f.status is WindowCoverageStatus.COMPLETE for f in result.facts)
    assert result.request.sources == (broken, original.sources[1])
    with pytest.raises(ValueError, match="SOURCE_FAILED"):
        result.analysis_request(rule)


def test_malformed_account_point_is_a_source_failure_not_a_batch_exception(saved_selection_accounts):
    repository, request, rule = saved_selection_accounts
    source = request.sources[0]
    header = json.loads(source.evaluation.resolve(repository.root).read_bytes())
    parent = (repository.root / source.evaluation.repository_path).parent
    account = json.loads((parent / (header["candidate_ref"]["sha256"] + ".json")).read_bytes())
    account["run"]["account_points"][0] = "bad"
    raw = _encoded(account)
    digest = sha256(raw).hexdigest()
    (parent / (digest + ".json")).write_bytes(raw)
    header["candidate_ref"]["sha256"] = digest
    broken = _write_header(repository, source, header)
    result = project_selection_window_facts(repository,
        replace(request, sources=(broken, request.sources[1])))
    assert result.status is SelectionProjectionStatus.SOURCE_FAILED
    assert len(result.failures) == 1
    assert result.failures[0].source == broken
    assert len(result.sources) == 1
    assert result.sources[0].candidate == request.sources[1].candidate
    assert len(result.facts) == 4
    with pytest.raises(ValueError, match="SOURCE_FAILED"):
        result.analysis_request(rule)


def test_shared_benchmark_exact_fact_budget_accepts_six_and_rejects_five(saved_selection_accounts):
    repository, request, _ = saved_selection_accounts
    result = project_selection_window_facts(repository, request)
    assert result.status is SelectionProjectionStatus.COMPLETE
    assert result.stats.projected_accounts == 3
    assert result.stats.projected_windows == len(result.facts) == 6
    assert len({s.benchmark_source_id for s in result.sources}) == 1
    with pytest.raises(ValueError, match="fact budget"):
        project_selection_window_facts(repository,
            replace(request, budget=replace(request.budget, max_window_facts=5)))


@pytest.mark.parametrize("budget_field, stats_field, message", [
    ("max_source_bytes", "source_bytes", "source byte budget"),
    ("max_shared_bytes", "shared_bytes", "shared byte budget"),
])
def test_byte_budget_rejects_complete_workload_instead_of_truncating(
        saved_selection_accounts, budget_field, stats_field, message):
    repository, request, _ = saved_selection_accounts
    baseline = project_selection_window_facts(repository, request)
    required = getattr(baseline.stats, stats_field)
    assert required > 1
    limited = replace(request, budget=replace(request.budget, **{budget_field: required - 1}))
    with pytest.raises(ValueError, match=message):
        project_selection_window_facts(repository, limited)


def _omit_account_point(repository, source, *, last):
    header = json.loads(source.evaluation.resolve(repository.root).read_bytes())
    parent = (repository.root / source.evaluation.repository_path).parent
    account = json.loads((parent / (header["candidate_ref"]["sha256"] + ".json")).read_bytes())
    points = account["run"]["account_points"]
    indices = [i for i, point in enumerate(points) if point["session"] == "2026-10-27"]
    assert len(indices) == 13  # Real synthetic US regular-session M30 account.
    del points[indices[-1] if last else indices[3]]
    raw = _encoded(account)
    digest = sha256(raw).hexdigest()
    (parent / (digest + ".json")).write_bytes(raw)
    header["candidate_ref"]["sha256"] = digest
    return _write_header(repository, source, header)


@pytest.mark.parametrize("last", [False, True], ids=["missing-middle-bar", "missing-session-close"])
def test_session_close_coverage_requires_close_not_every_intraday_point(saved_selection_accounts, last):
    repository, request, rule = saved_selection_accounts
    changed = _omit_account_point(repository, request.sources[0], last=last)
    result = project_selection_window_facts(repository,
        replace(request, sources=(changed, request.sources[1])))
    assert result.status is SelectionProjectionStatus.COMPLETE, result.failures
    facts = {f.window.window_id: f for f in result.facts if f.source_id == changed.evaluation.sha256}
    assert facts["observation"].status is WindowCoverageStatus.COMPLETE
    analysis = assess_selection_stability(result.analysis_request(rule))
    if last:
        assert facts["selection"].status is WindowCoverageStatus.INSUFFICIENT_DATA
        assert analysis.decisions[0].status is SelectionStatus.INSUFFICIENT_SELECTION_EVIDENCE
    else:
        assert facts["selection"].status is WindowCoverageStatus.COMPLETE
        baseline = project_selection_window_facts(repository, request)
        original = next(f for f in baseline.facts
            if f.source_id == request.sources[0].evaluation.sha256 and f.window.window_id == "selection")
        assert facts["selection"].opening_equity == original.opening_equity
        assert facts["selection"].ending_equity == original.ending_equity
        assert tuple((d.metric, d.value) for d in facts["selection"].diagnostics) == tuple(
            (d.metric, d.value) for d in original.diagnostics)
        assert analysis.decisions[0].status is SelectionStatus.SELECTED
