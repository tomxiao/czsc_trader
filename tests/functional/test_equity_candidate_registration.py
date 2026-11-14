# Risk ownership: TDR-03
"""Formal equity candidate roundtrip uses the shared registration API."""
from dataclasses import replace
from equity_test_support import setup_account_research
from strategy_runtime import equity_source_hash
from czsc_trader.application.candidate_service import CandidateRegistrationRequest, register_candidate, load_candidate


def test_TDR_03_C04_equity_registration_load_and_source_snapshot(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    source = request.experiment.resolve(context.repository.root) / 'src'
    source.mkdir(exist_ok=True)
    (source / 'strategy.py').write_text('from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n'
        'def step(ctx,state):\n return AccountStepResult(AccountDecision.from_facts(1, "hold", facts={"target":1}, next_watch="next bar"),cycle_values=StateRecord())\n', encoding='utf-8')
    definition = replace(request.candidate.definition,source_sha256=equity_source_hash(source, ('strategy.py',)))
    candidate = replace(request.candidate,definition=definition,source_root=source)
    record = register_candidate(context.repository, CandidateRegistrationRequest(candidate, request.experiment, (), ()))
    loaded = load_candidate(context.repository, candidate.key)
    assert loaded.content_identity.content_sha256 == record.content_sha256
    assert loaded.source_root != source and loaded.definition == definition
    (source / 'strategy.py').unlink()
    assert load_candidate(context.repository, candidate.key).content_identity == loaded.content_identity
