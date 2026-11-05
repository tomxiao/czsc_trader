"""Prospective typed parameter plan followed by five new bound accounts."""
from dataclasses import replace
from hashlib import sha256
from plan_context import *
from czsc_trader.research_tools import ParameterEvaluationPlan,EvaluationLineage
from strategy_evaluator import AssessmentCandidate,ParameterNeighborhoodDesign,ParameterNeighborhoodRequest,build_parameter_neighborhood_design
from strategy_manager import CandidateDerivation,CandidateDerivationKind,CandidateEvidence
from audit import compare_saved


def main():
    assert not (OUT/'bound_results.json').exists(),'bound evaluation already complete'
    context,sources,spec=frozen_context()
    jobs=[r for r in read(OUT/'jobs.json') if r['window']=='full']
    candidates=[]
    for row in jobs:
        payload=read(OUT/('definition_'+row['candidate_id']+'_full.json'))
        definition=EquityStrategyDefinition.from_dict(payload['equity_definition'])
        candidates.append(EquityStrategyCandidate('S015',row['candidate_id'],definition,HOME/'src'))
    center,*children=candidates
    old=next(r for r in read(ROOT/'research/S015/experiments/EX080_20261025/others/plan_refs.json') if r['candidate_id']=='C9304')
    olddesign=ParameterNeighborhoodDesign.from_dict(old['design'])
    mapping={'center':center.content_identity.content_sha256,'original_design':old['design'],'candidate_mapping':jobs,
             'payload_mapping':'Named axis maps to equity_definition.parameters_json object; all nonparameter definition fields identical.'}
    feasibility={'declared_points':5,'source_unchanged':True,'original_five_points_preserved':True,
                 'scope':'Finite saved standard-fee historical accounts; total quantity cap and zero-lot WAIT semantics not generalised.'}
    def req(c):
        return EquityEvaluationRequest(EXP,c,TimeInterval(at(date(2025,1,2),9,30),at(date(2026,10,21),15)),date(2024,9,9),
            sources,100000.,.001,window_id='full',scenario_id='STANDARD',measurement_tier='FORMAL',
            benchmark=EvaluationBenchmark(EquityBuyHold(spec)),drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE')
    with ResearchExecutionSession(context,experiment=EXP) as execution:
        def material(name,value):
            content=(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
            return publish_evidence(context,MaterialEvidenceWrite(EXP,name,content,'application/json','json'),execution=execution)
        mapping_ref=material('formal-parameter-mapping',mapping)
        feasibility_ref=material('formal-parameter-feasibility',feasibility)
        space=replace(olddesign.space,mapping_sha256=mapping_ref.sha256,feasibility_sha256=feasibility_ref.sha256)
        result=build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
            AssessmentCandidate('S015-C9810',center.content_identity.content_sha256),olddesign.protocol,space),feasibility=lambda values: True)
        design=result.design
        assert design is not None and design.points==olddesign.points
        central=context.evaluation.prepare(req(center),execution=execution)
        unbound=tuple(context.evaluation.prepare(req(c),execution=execution) for c in children)
        plan=ParameterEvaluationPlan.create(design,central,unbound,mapping_evidence=mapping_ref,
            feasibility_evidence=feasibility_ref,dataflows=context.data,execution=execution)
        save(OUT/'formal_parameter_plan.json',plan.to_dict())
        plan_ref=material('formal-parameter-plan',plan.to_dict())
        save(OUT/'formal_parameter_refs.json',{'mapping':mapping_ref.to_dict(),'feasibility':feasibility_ref.to_dict(),'plan':plan_ref.to_dict()})
        print('PLAN_READY',plan_ref.sha256,flush=True)
        results=[]
        for i,(child,handle,row) in enumerate(zip(children,unbound,jobs[1:],strict=True)):
            changes={v.name:v.value for v in design.points[i].values}
            derivation=CandidateDerivation(center.key,center.content_identity.content_sha256,child.key,
                child.content_identity.content_sha256,CandidateDerivationKind.PARAMETERS,changes,design.protocol.sha256,
                CandidateEvidence(plan_ref.repository_path,plan_ref.sha256))
            bound=replace(handle.request,lineage=EvaluationLineage(derivation,plan.bind_point(plan_ref,i,repository_root=ROOT)))
            prepared=context.evaluation.prepare(bound,execution=execution)
            outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
            if outcome.result is None:raise RuntimeError(str(outcome.error))
            ref=publish_evidence(context,EvaluationEvidenceWrite(EXP,'bound-'+child.candidate_id,prepared,outcome.result),execution=execution)
            item={'candidate_id':child.candidate_id,'old_candidate':row['old_candidate'],'window':'full',
                  'reference':ref.to_dict(),'old_reference':row['old_reference'],'parameter_point_index':i}
            save(OUT/('bound_result_'+child.candidate_id+'.json'),item)
            check=compare_saved(ROOT,item)
            save(OUT/('bound_comparison_'+child.candidate_id+'.json'),check)
            assert check['status']=='PASS',check
            results.append({**item,'comparison':check})
            save(OUT/'bound_progress.json',{'accounts':results})
            print('BOUND_PASS',child.candidate_id,ref.sha256,flush=True)
        save(OUT/'bound_results.json',{'accounts':results,'statistics':str(execution.equity_statistics)})
if __name__=='__main__':main()
