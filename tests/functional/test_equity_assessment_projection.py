# Risk ownership: TDR-16
"""Bounded fact projection and explicit consumption of immutable closures."""
from collections import Counter
from dataclasses import replace
import json

import pytest

from czsc_trader.research_tools import equity_replay
from czsc_trader.research_tools.assessment import build_assessment_evidence
from czsc_trader.research_tools.equity_assessment import AssessmentProjection
from czsc_trader.research_tools.equity_evaluation import EquityArtifact, EquityEvaluationResult
from equity_parameter_support import equity_plan
from strategy_evaluator import project_parameter_performance


def test_materialization_defers_large_decoding_and_each_snapshot_is_isolated(account_facts, monkeypatch):
    _, result = account_facts
    counts = Counter()
    read = equity_replay._read
    artifact_bytes = {item.content: item.sha256 for item in result.artifacts}

    def counted(content):
        if content in artifact_bytes:
            counts[artifact_bytes[content]] += 1
        return read(content)

    monkeypatch.setattr(equity_replay, "_read", counted)
    view = equity_replay.materialize_equity(result)
    assert not counts
    first = view.payload
    assert set(counts.values()) == {1} and len(counts) == 3
    first["runs"]["candidate"]["account_points"].clear()
    second = view.payload
    assert second["runs"]["candidate"]["account_points"]
    assert set(counts.values()) == {2}


def test_account_projection_reads_only_the_two_recorded_accounts(account_facts, monkeypatch):
    _, result = account_facts
    read = equity_replay._read
    counts = Counter()
    artifact_bytes = {item.content: item.kind for item in result.artifacts}

    def counted(content):
        if content in artifact_bytes:
            counts[artifact_bytes[content]] += 1
        return read(content)

    monkeypatch.setattr(equity_replay, "_read", counted)
    facts, = equity_replay.build_equity_assessment(result)
    assert facts.account
    assert counts == {"equity_account": 2}


def test_detached_result_resolves_its_complete_closure(account_facts):
    _, result = account_facts
    detached = EquityEvaluationResult(result.request_hash, result.content)
    artifacts = {item.sha256: item.content for item in result.artifacts}
    resolved = []

    def resolver(reference):
        resolved.append(reference["sha256"])
        return artifacts[reference["sha256"]]

    view = equity_replay.materialize_equity(detached, resolver)
    assert set(resolved) == set(artifacts) and len(resolved) == 3
    assert view.source_content == result.content
    assert view.artifacts == result.artifacts
    assert equity_replay.build_equity_assessment(view) == equity_replay.build_equity_assessment(result)
    with pytest.raises(TypeError, match="explicit artifact resolver"):
        equity_replay.materialize_equity(detached)


def test_consumers_reject_wrong_owner_without_implicit_journal_audit(account_facts):
    _, result = account_facts
    header = result.payload
    original = next(x for x in result.artifacts if x.sha256 == header["candidate_ref"]["sha256"])
    document = json.loads(original.content)
    document["owner"]["content_sha256"] = "a" * 64
    changed = EquityArtifact(original.kind, json.dumps(document).encode())
    header["candidate_ref"] = changed.reference()
    altered = EquityEvaluationResult(result.request_hash, json.dumps(header).encode(),
        tuple(changed if x is original else x for x in result.artifacts))
    view = equity_replay.materialize_equity(altered)
    with pytest.raises(ValueError, match="owner differs"):
        view.payload
    with pytest.raises(ValueError, match="owner differs"):
        equity_replay.build_equity_assessment(view)


@pytest.mark.parametrize("drawdown_basis", ["SESSION_CLOSE", "BAR_CLOSE"])
def test_parameter_projection_matches_full_facts_without_constructing_or_recalculating_them(
        tmp_path, monkeypatch, drawdown_basis):
    from czsc_trader.research_tools import equity_assessment
    from strategy_evaluator import equity_assessment as se_equity
    import equity_test_support

    setup = equity_test_support.setup_account_research

    def with_basis(path):
        context, request, products, calls = setup(path)
        return context, replace(request, drawdown_basis=drawdown_basis), products, calls

    monkeypatch.setattr(equity_test_support, "setup_account_research", with_basis)

    with equity_plan(tmp_path) as (context, _, _, _, children, execution):
        outcome, = context.evaluation.evaluate_many((children[0],), execution=execution)
        assert outcome.result is not None, outcome.error
        full, = build_assessment_evidence(children[0], outcome.result, execution=execution)
        expected = project_parameter_performance(full)

        def forbidden(*args, **kwargs):
            raise AssertionError("numeric projection must consume saved metrics directly")

        monkeypatch.setattr(equity_assessment, "AssessmentEvidence", forbidden)
        monkeypatch.setattr(equity_assessment, "EquityAssessmentFacts", forbidden)
        monkeypatch.setattr(se_equity, "equity_performance", forbidden)
        projected, = build_assessment_evidence(children[0], outcome.result, execution=execution,
            projection=AssessmentProjection.PARAMETER_PERFORMANCE)
        assert projected == expected


def test_parameter_projection_requires_bound_derivation_and_typed_selection(account_facts):
    _, result = account_facts
    with pytest.raises(ValueError, match="bound parameter derivation"):
        equity_replay.build_equity_assessment(result, projection=AssessmentProjection.PARAMETER_PERFORMANCE)
    with pytest.raises(TypeError, match="AssessmentProjection"):
        equity_replay.build_equity_assessment(result, projection=True)
