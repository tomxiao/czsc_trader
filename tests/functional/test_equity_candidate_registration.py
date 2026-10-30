"""Formal equity candidate roundtrip uses the shared registration API."""
from dataclasses import replace
import pytest
from equity_test_support import setup_equity
from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, equity_source_hash
from czsc_trader.application.candidate_service import CandidateRegistrationRequest, register_candidate, load_candidate


def test_equity_registration_load_and_source_snapshot(tmp_path):
    context, request, _, _ = setup_equity(tmp_path)
    source = request.experiment.resolve(context.repository.root) / 'src'
    source.mkdir(exist_ok=True)
    (source / 'strategy.py').write_text('from strategy_runtime import EquityDecision\n'
        'def decide(ctx):\n return EquityDecision.from_facts(1, "hold", facts={"close": ctx.history.Close.iloc[-1]}, next_watch="next bar")\n', encoding='utf-8')
    definition = EquityStrategyDefinition(request.candidate.instrument, context.execution_spec, 1,
        'strategy:decide', ('strategy.py',), equity_source_hash(source, ('strategy.py',)))
    candidate = EquityStrategyCandidate(request.experiment.strategy_id, 'C0001', definition, source)
    record = register_candidate(context.repository, CandidateRegistrationRequest(candidate, request.experiment, (), ()))
    loaded = load_candidate(context.repository, candidate.key)
    assert loaded.content_identity.content_sha256 == record.content_sha256
    assert loaded.source_root != source and loaded.definition == definition
    (source / 'strategy.py').write_text('changed', encoding='utf-8')
    assert load_candidate(context.repository, candidate.key).content_identity == loaded.content_identity
    with pytest.raises(ValueError, match='closure changed'):
        replace(candidate)
