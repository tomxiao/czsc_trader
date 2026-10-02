"""Focused S011 migration acceptance; no execution, mutation of evidence or new search."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input
from strategy_manager import CandidateKey
from strategy_runtime import StrategyRuntime, ImplementationDependency
from strategy_evaluator import research_models as m
from czsc_trader.application import RepositoryContext, load_candidate, validate_delivery, validate_archives
from czsc_trader.research_tools import delivery as d
from dataclasses import replace
import argparse

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
CTX=RepositoryContext.discover(REPO)
EXP=ROOT
COMP=REPO/'experiments/S011/20261002_S011_EX34'
HIST=REPO/'research/S011/historical_deliveries/revision_01'
def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def delivery_path(reference):
    if isinstance(reference.owner,d.MandateOwner):
        return REPO/f'research/S011/mandates/{reference.revision}/delivery.json'
    return REPO/f'experiments/S011/{reference.owner.experiment_id}/deliveries/{reference.stage.value}/{reference.revision}/delivery.json'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sealed',action='store_true')
    args=parser.parse_args()

    sources=read(HIST/'sources.json')
    for name,digest in sources.items():
        assert sha256((REPO/name).read_bytes()).hexdigest()==digest,name
    if args.sealed:
        for path in (EXP,COMP):
            assert validate_archives(CTX,archive=path).status=='PASS'
    component_receipt=read(COMP/'artifacts/execution_receipt.json')
    load_experiment_input(COMP/'artifacts',expected_receipt_sha256=component_receipt['receipt_sha256'])
    summary=read(COMP/'artifacts/summary.json')
    assert (summary['definition_count'],summary['role_tests'],summary['folds'],summary['leave_month_paths'])==(9,63,189,945)
    for name,digest in read(COMP/'historical_sources.json').items():
        assert sha256((REPO/name).read_bytes()).hexdigest()==digest,name
    receipt=read(EXP/'artifacts/execution_receipt.json')
    load_experiment_input(EXP/'artifacts',expected_receipt_sha256=receipt['receipt_sha256'])
    attempts=receipt['trace']['evaluations']
    assert len(attempts)==100 and all(x['status']=='SUCCEEDED' for x in attempts)
    assert sum(len(x['evaluation_ids']) for x in attempts)==135
    comparisons=[row for p in (EXP/'artifacts/comparison').glob('*.json') for row in read(p)]
    assert len(comparisons)==135 and all(x['status']=='EQUIVALENT' and len(x['ledgers'])==5 for x in comparisons)
    assert all(x['benchmark']['status']=='EQUIVALENT' and len(x['benchmark']['ledgers'])==5 for x in comparisons)
    standard=[x for x in comparisons if x['scenario']=='standard']
    assert all(x['benchmark']['quantity']==938000 and abs(x['benchmark']['end_equity']-1461437.844)<1e-8 for x in standard)
    mapping=read(ROOT/'identity_mapping.json')
    deps=tuple(ImplementationDependency(**x) for x in read(EXP/'inputs.json')['dependencies'])
    for item in mapping:
        raw=item['candidate']['key']
        key=CandidateKey(raw['strategy_id'],raw['candidate_id'])
        loaded=load_candidate(CTX,key)
        assert StrategyRuntime().identify(loaded,dependencies=deps).content_sha256==item['candidate']['content_sha256']
    neighbors=read(EXP/'inputs.json')['neighbors']
    for item in neighbors:
        registered=read(EXP/'artifacts/registrations'/(item['candidate_id']+'.json'))
        historical_record=read(REPO/'research/registrations/S011/candidates'/(item['historical_candidate_id']+'.json'))['record']
        assert registered['content_sha256']==historical_record['content_sha256']
        assert registered['schema_version']==2
        loaded=load_candidate(CTX,CandidateKey('S011',item['candidate_id']))
        assert StrategyRuntime().identify(loaded,dependencies=deps).content_sha256==registered['content_sha256']
    validation={}
    index=read(ROOT/'delivery_index.json')
    complete=index['status']=='PUBLISHED_WITH_DISCLOSED_LIMITATIONS'
    references=tuple(d.DeliveryReference.from_dict(value) for value in index['references'])
    final=next(x for x in references if x.stage is d.DeliveryStage.ASSESSMENT)
    checked=validate_delivery(CTX,final)  # recursively authenticates every predecessor
    assert checked.status is d.ValidationStatus.PASS,checked
    closure=set()
    def visit(reference):
        if reference in closure:
            return
        closure.add(reference)
        document=read(delivery_path(reference))
        assert document["definition"]["schema_version"]==4
        for value in document['definition']['predecessors']:
            visit(d.DeliveryReference.from_dict(value))
    visit(final)
    assert set(references).issubset(closure)
    for reference in references:
        validation[reference.stage.value]=checked.status.value
        print(json.dumps({'validated':reference.stage.value,'method':'authenticated stage-four predecessor closure'}),flush=True)
    comparison=m.CandidateComparison.from_dict(read(ROOT/'comparison.json'))
    assert len(comparison.rows)==36
    checks=Counter(x.status.value for row in comparison.rows for x in row.target_checks)
    assert checks==({'PASSED':108,'NOT_APPLICABLE':72} if complete else
                    {'PASSED':107,'FAILED':1,'NOT_APPLICABLE':72}),checks
    if not complete:
        assert [x.candidate.candidate_id for x in comparison.rows if x.status is m.ComparisonStatus.TARGET_NOT_MET]==['S011-CFG000244']
    assert sum(x.status is m.ComparisonStatus.PARTIALLY_ORDERED for x in comparison.rows)==15
    assert sum(x.relation is m.PairwiseRelation.INCOMPARABLE for x in comparison.pairs)==9
    panel=m.AssessmentPanel.from_dict(read(ROOT/'assessment_panel.json'))
    missing={metric.value:sum(next(x for x in row.diagnostics if x.metric is metric).value is None for row in panel.rows)
        for metric in (m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,m.ResearchMetric.STRESS_ANNUAL_LOSS)}
    assert missing=={'PARAMETER_RETURN_DEGRADATION':32,'STRESS_ANNUAL_LOSS':1},missing
    old=read(HIST/'stage4/rankings.json')
    idmap={'S011-'+x['candidate']['key']['candidate_id']:x['config_id'] for x in mapping}
    names=dict(zip(('cagr','drawdown_magnitude','parameter_cagr_loss','parameter_drawdown_increase',
        'rolling60_excess_q10','pressure_cagr_loss','top10pct_positive_pnl_share'),m.RANKING_METRICS))
    maximum_difference=0.
    for row in panel.rows:
        history=next(x for x in old if x['config_id']==idmap[row.candidate.candidate_id])
        for field,metric in names.items():
            actual=next(x.value for x in row.diagnostics if x.metric is metric)
            expected=history[field]
            if expected is None:
                assert actual is None
            else:
                difference=abs(actual-expected)
                if complete or metric is not m.ResearchMetric.ROLLING_EXCESS_Q10:
                    assert difference<1e-10,(history['config_id'],field,actual,expected)
                maximum_difference=max(maximum_difference,difference)
    sensitivity=read(REPO/'research/S011/stage4/iteration_04/ranking_sensitivity.json')
    for variant in comparison.sensitivities:
        lookup={x['config_id']:x for x in sensitivity[variant.name]['rankings']}
        for row in variant.rows:
            prior=lookup[idmap[row.candidate.candidate_id]]
            if complete:
                assert (row.pareto_layer,row.rank_min,row.rank_max,row.rank_in_layer)==(
                    prior['pareto_layer'],prior['rank_min'],prior['rank_max'],prior['recommendation_rank'])
    search=read(EXP/'deliveries/CANDIDATES/1/delivery.json')['content']['payload']['searches']
    states=Counter(t['status'] for record in search for t in record['trials'])
    assert states=={'COMPLETE':573,'FAILED':3},states
    selected=next(x for x in mapping if x['config_id']=='S011-CFG-000621')
    assert selected['config_id']=='S011-CFG-000621'
    failed_records=[read(p) for p in (REPO/'experiments/S011/20261001_S011_EX30/artifacts/evaluations').glob('*/record.json')]
    assert len(failed_records)==1 and len(failed_records[0]['evaluation_ids'])==2
    report={'status':'PASS' if complete else 'AVAILABLE_DELIVERIES_PASS_STAGE4_BLOCKED',
        'stage4_comparison_is_formal':complete,'historical_sources_unchanged':len(sources),'candidate_registrations':len(mapping),
        'managed_calls':100,'account_evaluations':135,'equivalent_ledger_tables':675,'equivalent_benchmark_ledger_tables':675,'deliveries':validation,
        'registered_perturbations':len(neighbors),'preserved_failed_experiment':'20261001_S011_EX30',
        'EX30_completed_calls_before_comparison_failure':1,'EX30_completed_accounts':2,
        'historical_search_states':dict(states),'target_checks':dict(checks),'coverage_gaps':missing,
        'historical_pareto_layers':16,'current_diagnostic_layers':max(x.pareto_layer or 0 for x in comparison.rows),
        'incomparable_pairs':9,'partial_candidates':15,'sensitivity_variants':10,
        'maximum_metric_difference':maximum_difference,'selected':selected['candidate'],
        'component_definitions':9,'component_tests':63,'component_folds':189,'component_leave_month_paths':945,'new_parameter_proposals':0,'new_independent_samples':0,'stage_five_started':False}
    historical_mapping=read(REPO/'research/S011/formal_migration/revision_02/identity_mapping.json')
    old_by_id={item['config_id']:item for item in historical_mapping}
    for item in mapping:
        assert item['candidate']['content_sha256']==old_by_id[item['config_id']]['candidate']['content_sha256']
    wrong=replace(final,content_sha256='0'*64)
    rejected=validate_delivery(CTX,wrong)
    assert rejected.status is d.ValidationStatus.FAIL
    report['candidate_content_unchanged']=True
    report['wrong_delivery_hash_rejected']=True
    report['sealed_archives_verified']=args.sealed
    destination=REPO/'.tmp/s011-regeneration-postseal.json' if args.sealed else ROOT/'focused_verification.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
