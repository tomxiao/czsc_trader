"""Authenticate published accounts and assess the entire stage-three handoff."""
from stage4 import (EvidenceRef, ROOT, read, validate_evaluation_evidence, m, EX,
    assert_protocol, OUT, source_rows, save, predecessor, d, np, annualized_sharpe,
    effective_trial_count, CENTERS, protocol, assess_candidates, policy,
    compare_candidates, module, HOME, Counter, json, argparse)
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

def authenticate(row):
    ref = EvidenceRef.from_dict(row['evidence'])
    assert ref.experiment.strategy_id == 'S015'
    value = read(ref.resolve(ROOT))
    validate_evaluation_evidence(value)
    for key in ('request_hash','result_hash'):
        assert value[key] == row[key]
    items = [m.AssessmentEvidence.from_dict(x) for x in value['assessment_evidence']]
    full = [x for x in items if x.window_id == 'full']
    assert len(full) == 1
    item = full[0]
    assert item.candidate.candidate_id == 'S015-'+row['candidate_id']
    assert item.initial_cash == 100000 and item.opening_quantity == 0
    assert item.frequency_window_days == 60 and len(item.account) == 434
    assert item.account[0].session == '2025-01-02' and item.account[-1].session == '2026-10-21'
    assert item.parameter_point is None
    if 'identity' in row:
        assert item.candidate.content_sha256 == row['identity']['content_sha256']
    if ref.experiment.experiment_id == EX.experiment_id:
        assert len(items) == 1 and item.scenario_id == 'fee_x2' and item.scenario_context.one_way_cost == .002
    else:
        assert len(items) == 2 and item.scenario_id == 'standard' and item.scenario_context.one_way_cost == .001
    return item, {'candidate_id':row['candidate_id'],'evidence':ref.to_dict(),
        'evaluation_id':item.evaluation_id,'request_hash':value['request_hash'],'result_hash':value['result_hash'],
        'content_sha256':item.candidate.content_sha256,'scenario':item.scenario_id,
        'context_sha256':item.context_sha256,'scenario_context':item.scenario_context.to_dict()}

def authenticate_all():
    assert_protocol()
    assert not (OUT/'authenticated_accounts.json').exists()
    rows = source_rows()+read(OUT/'stress_results.json')
    assert len(source_rows()) == 176 and len(rows) == 192
    evidence, metadata = [], []
    with ProcessPoolExecutor(max_workers=4,mp_context=get_context('spawn')) as pool:
        for index,(item,meta) in enumerate(pool.map(authenticate,rows)):
            evidence.append(item.to_dict())
            metadata.append(meta)
            if index%16 == 15:
                print('AUTHENTICATED',index+1,len(rows),flush=True)
    save(OUT/'authenticated_accounts.json',evidence)
    save(OUT/'authenticated_sources.json',metadata)

def targets():
    ref,payload = predecessor('MANDATE',3,'5563c98c1a2ed876b6d75b775437f35ec2c31777818ad0f9b67e89c90d30d90a')
    mandate = d.ResearchMandate.from_dict(payload)
    values = tuple(t for item in mandate.items if isinstance(item.requirement,d.PerformanceRequirement)
                   for t in item.requirement.targets)
    bindings = {t.target_id:item.item_id for item in mandate.items
                if isinstance(item.requirement,d.PerformanceRequirement) for t in item.requirement.targets}
    frequency = [item for item in mandate.items if isinstance(item.requirement,d.NumericRequirement)
                 and item.requirement.metric == 'frequency_window_days']
    assert len(frequency) == 1 and (frequency[0].requirement.lower,frequency[0].requirement.upper) == (60.,60.)
    benchmark = [item.item_id for item in mandate.items if isinstance(item.requirement,d.BenchmarkRequirement)]
    assert len(benchmark) == 1
    save(OUT/'target_bindings.json',{'reference':ref.to_dict(),'bindings':bindings,
        'frequency':frequency[0].item_id,'benchmark':benchmark[0]})
    return m.ResearchTargets(values,60)

def build_family(evidence):
    standard = [x for x in evidence if x.scenario_id == 'standard']
    assert len(standard) == 176
    sessions = tuple(x.session for x in standard[0].account)
    assert all(tuple(x.session for x in item.account) == sessions for item in standard)
    assert len({(x.context_sha256,x.metric_version,x.scenario_context) for x in standard}) == 1
    returns = []
    for item in standard:
        equity = np.array([x.equity for x in item.account])
        returns.append(equity/np.r_[item.initial_cash,equity[:-1]]-1)
    matrix = np.array(returns).T
    sharpes = np.array([annualized_sharpe(x) for x in matrix.T])
    assert np.isfinite(sharpes).all()
    selected = int(np.argmax(sharpes))
    limitations = (
        '176 columns retain all50 standard configurations EX052..056 plus126 EX058..062, including duplicated paths and failed targets; these are not176 independent hypotheses.',
        'Earlier S015 feature, component, funding and strategy searches, including EX051 signal survey, influenced this family. Their nonhomogeneous paths and adaptive decisions are outside this matrix.176 is a measured subset, not complete historical trials.',
        'All434 observations and overlapping415 sessions are repeatedly seen development data; no independent test sample or future success probability.',
        'Highest full-sample Sharpe selects the DSR diagnostic only, not a recommended candidate. Formal comparison requires complete evidence.',
        'Missing parameter designs remain missing; bootstrap/DSR/PBO and annual diagnostics neither substitute for them nor add acceptance thresholds.')
    family = m.FamilyReturnEvidence(tuple(x.candidate for x in standard),sessions,
        tuple(tuple(float(v) for v in row) for row in matrix),standard[selected].candidate,176,limitations)
    try:
        effective = {'status':'AVAILABLE','value':effective_trial_count(matrix)}
    except (ValueError,FloatingPointError,ZeroDivisionError) as error:
        effective = {'status':'INSUFFICIENT_DATA','value':None,'reason':str(error)}
    save(OUT/'family_summary.json',{'raw_trial_count':176,'distinct_exact_return_paths':len({x.tobytes() for x in matrix.T}),
        'effective_trial_count':effective,'selected_for_dsr':standard[selected].candidate.to_dict(),
        'zero_variance_columns':int(np.sum(np.std(matrix,axis=0,ddof=1)==0)),'limitations':list(limitations)})
    return family

def build():
    assert_protocol()
    evidence = tuple(m.AssessmentEvidence.from_dict(x) for x in read(OUT/'authenticated_accounts.json'))
    byid = {x.candidate.candidate_id.removeprefix('S015-'):x for x in evidence if x.scenario_id=='standard'}
    centers = tuple(byid[cid].candidate for cid in CENTERS)
    for cid in CENTERS:
        pressure = [x for x in evidence if x.candidate == byid[cid].candidate and x.scenario_id == 'fee_x2']
        assert len(pressure) == 1
    family = build_family(evidence)
    request = m.CandidateAssessmentRequest(centers,protocol(),(),evidence,family_returns=family,parameter_designs=())
    save(OUT/'assessment_request.json',request.to_dict())
    panel = assess_candidates(request)
    save(OUT/'assessment_panel.json',panel.to_dict())
    comparison_request = m.CandidateComparisonRequest(centers,targets(),panel,policy())
    save(OUT/'comparison_request.json',comparison_request.to_dict())
    comparison = compare_candidates(comparison_request)
    save(OUT/'comparison.json',comparison.to_dict())
    historical = module(HOME.parent/'EX005_20261022/src/build_assessment.py','historical_assessment_functions')
    summary = {'centers':16,'new_formal_stress_accounts':16,'new_serial_technical_accounts':1,
        'authenticated_full_account_projections':192,'parameter_design_count':0,'parameter_accounts':0,
        'status_counts':dict(Counter(x.status.value for x in comparison.rows)),
        'acceptance_counts':dict(Counter(x.acceptance_status.value for x in comparison.rows)),
        'family_diagnostics':[x.to_dict() for x in panel.family_diagnostics],
        'rows':historical.concise_rows(panel,comparison),
        'sensitivities':[{'name':v.name,'rows':[{'candidate_id':x.candidate.candidate_id,'status':x.status.value,
            'rank_min':x.rank_min,'rank_max':x.rank_max} for x in v.rows]} for v in comparison.sensitivities]}
    assert not any(x.acceptance_status.value == 'PASSED' for x in comparison.rows)
    assert not any(x.status.value in ('RANKED','TIED','PARTIALLY_ORDERED') for x in comparison.rows)
    save(OUT/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('centers','status_counts','acceptance_counts')},ensure_ascii=False),flush=True)

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('authenticate','build'))
    {'authenticate':authenticate_all,'build':build}[parser.parse_args().action]()
