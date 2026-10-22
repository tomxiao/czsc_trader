"""Publish current-contract account evidence and the independent repair candidate."""
from datetime import date
from repair import ROOT, EROOT, RESULTS, EXPERIMENT_ID, candidate, frozen_hashes, save
from czsc_trader.application import (RepositoryContext, create_research_context,
    publish_evidence, register_candidate, CandidateRegistrationRequest)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvaluationResources,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
    EvaluationEvidenceWrite)


def main():
    before = frozen_hashes()
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef('S011'), resources=EvaluationResources(1, 1, 13))
    c = candidate()
    exp = ExperimentRef('S011', EXPERIMENT_ID)
    request = EvaluationRequest(ROOT, EXPERIMENT_ID, c, {
        'candidate_id': c.reference_id, 'source_files': list(c.payload['runtime']['source_files']),
        'implementation_sha256': c.payload['runtime']['source_sha256']}, '159326.SZ', 'etf',
        (EvaluationWindow('restored', date(2025, 2, 6), date(2026, 10, 21)),), date(2026, 10, 21), 100000.,
        (EvaluationCost('standard', .001),), benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .001, .1, 1000000)))
    request = ctx.evaluation.prepare(request)
    print('PREPARED', flush=True)
    result = ctx.evaluation.evaluate(request)
    run = result.runs[0]
    # Reconcile this formal evaluation with the separately requested TDR account.
    import pandas as pd
    from repair import read
    saved = ROOT / read(RESULTS / 'backtest_2025-02-06.json')['data']['output_dir']
    actual = run.execution.account_daily
    expected = pd.read_csv(saved / 'account_daily.csv', float_precision='round_trip')
    assert len(actual) == len(expected)
    for col in ('cash', 'quantity', 'equity'):
        pd.testing.assert_series_equal(actual[col].reset_index(drop=True), expected[col],
                                       check_names=False, check_dtype=False, check_exact=True)
    assert frozen_hashes() == before
    ref = publish_evidence(ctx, EvaluationEvidenceWrite(exp, 'restored_account', request, result))
    save(EROOT / 'others/account_evidence.json', ref.to_dict())
    registration = register_candidate(repo, CandidateRegistrationRequest(c, exp, (ref,), ()))
    save(EROOT / 'others/registration.json', registration.to_dict())
    save(RESULTS / 'formal_evaluation.json', {'evidence': ref.to_dict(),
        'request_hash': result.request_hash, 'result_hash': result.result_hash,
        'observation': run.observation.to_dict(), 'sessions': len(actual),
        'tdr_account_cash_quantity_equity_exact': True, 'frozen_files_unchanged': True})
    print('REGISTERED', c.reference_id, flush=True)


if __name__ == '__main__':
    main()
