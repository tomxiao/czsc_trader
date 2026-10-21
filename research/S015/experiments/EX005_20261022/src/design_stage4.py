"""Publish the complete stage-four policy and all geometry before any new accounts."""
from common import ROOT,EROOT,WORK,EXPERIMENT,context,read,save,family_rows,request,account
from parameter_map import coordinates,materialize
from parameter_constraints import feasible
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from strategy_evaluator import (AssessmentCandidate,ParameterSpace,ParameterPerturbationProtocol,
    ParameterDesignRequest,build_parameter_perturbation_design)
from strategy_runtime import StrategyRuntime


def main():
    ctx=context()
    delivery=read(ROOT/'research/S015/assets/deliveries/CANDIDATES/2/delivery.json')
    allowed={r['candidate_id'] for r in delivery['content']['payload']['handoff']}
    rows=sorted((r for r in family_rows() if r['candidate_id'] in allowed),key=lambda r:r['candidate_id'])
    assert len(rows)==len(allowed)==98
    save(WORK/'centers.json',rows)
    mapping=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'parameter_mapping',(EROOT/'src/parameter_map.py').read_bytes(),'text/x-python','py'))
    constraints=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'parameter_constraints',(EROOT/'src/parameter_constraints.py').read_bytes(),'text/x-python','py'))
    protocol=ParameterPerturbationProtocol()
    inventory=[]
    for ordinal,row in enumerate(rows):
        cid=row['candidate_id']
        center=request(row).strategy
        identity=StrategyRuntime().identify(center,dependencies=())
        actual=account(row)
        assert identity.content_sha256==actual['request_identity']['content_sha256']
        space=ParameterSpace(coordinates(row['parameters']),mapping.sha256,constraints.sha256)
        if cid in ('C0030','C0062'):
            result={'status':'NOT_APPLICABLE','reason':'At max_days=1 exit is inactive; disabled range_cap is categorical. A one-day integer move needs 1/19 > .05, so the feasible shell has only one active continuous coordinate and at most two distinct points, not 32.',
                    'space':space.to_dict(),'design_result':None}
        else:
            design_result=build_parameter_perturbation_design(ParameterDesignRequest(
                AssessmentCandidate(center.reference_id,identity.content_sha256),protocol,space),
                feasibility=lambda values:feasible(tuple(x.name for x in space.coordinates),values))
            assert design_result.status.value=='COMPLETE',design_result
            design=design_result.design
            parameters=[materialize(row['parameters'],space,p.coordinates) for p in design.points]
            assert all(p['max_days']==row['parameters']['max_days'] for p in parameters)
            result={'status':'COMPLETE','design':design.to_dict(),'design_result':design_result.to_dict(),
                    'children':[{'candidate_id':f'C{1000+ordinal*32+i:04d}','parameters':p} for i,p in enumerate(parameters)]}
        save(WORK/'designs'/f'{cid}.json',result)
        inventory.append({'candidate_id':cid,**result})
    policy={'version':'S015-EX005-standard-v1','scope':'98 source handoff centers; original center accounts reused only after exact request identity verification; no cross-candidate or cross-source substitution',
        'parameter_protocol':protocol.to_dict(),'domains':{'entry':[0,.03],'exit':[0,.02],'max_days':[1,20],'relative_threshold':[0,4],'absolute_threshold':[0,2/9],'low_weight':[0,1]},
        'domain_basis':'entry/exit from the actual EX003 expansion range; holding age from existing 1..20 implementation bound; relative ratio algebraic upper bound4; absolute2/9 is a nominal +/-10% no-tick-rounding amplitude scale, not a strict market bound; equity weights have natural0..1 bounds.',
        'inactive_parameters':'range_cap0 is disabled structure; cycle threshold/weight are fixed contract; constant threshold/reverse inactive; sizing/reverse fixed categories; h1 exit removed. No clipping, dead coordinates or result-driven domains.',
        'integer_limit':'1/19>.05: max_days does not move at this radius for any center; no claim of +/-1day robustness. No extra-radius or discrete tests authorized.',
        'not_applicable':['C0030','C0062'],'new_accounts':{'parameters':3072,'stress':98,'total':3170},
        'resources':{'max_workers':8,'native_threads':1,'seed':13},
        'protocol':{'rolling_window_days':252,'rolling_step_days':21,'quantile_method':'LINEAR','minimum_rolling_windows':1,'bootstrap_repetitions':2000,'bootstrap_block_length':10,'seed':13,'reconciliation_tolerance':1e-7,'pbo_blocks':10,'frequency_window_days':60,'frequency_min_closed_cycles':3,'standard_scenario':'standard','stress_scenario':'fee_x2','standard_cost':.001,'stress_cost':.002},
        'comparison':{'version':'S015-EX005-standard-v1','pareto_basis':'RAW','missing_evidence_policy':'REQUIRE_COMPLETE','rounding':'FLOOR','origin':0,'rate_resolution':.001,'concentration_resolution':.01,'rolling_frequency_median_resolution':1,'sensitivities':['bins_half','bins_double','adjacent_swap_0','adjacent_swap_1','adjacent_swap_2','adjacent_swap_3','adjacent_swap_4']},
        'family_selection_bias':'181 retained executable search configurations from EX00384+EX00497; each account once; feature/label1092 comparisons remain selection history outside this homogeneous return matrix. No independence or complete historical trial count claim; do not add unlike trial units.',
        'geometry':inventory,'mapping':mapping.to_dict(),'constraints':constraints.to_dict(),
        'stop':'Complete all prescribed feasible points and center stress, retain not-applicable and negative results. No stage5 selection/freeze/PTE authority.'}
    save(EROOT/'protocols/stage4.json',policy)
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'stage4_protocol',(EROOT/'protocols/stage4.json').read_bytes(),'application/json','json'))
    save(EROOT/'others/protocol_ref.json',ref.to_dict())
    save(EROOT/'others/mapping_refs.json',{'mapping':mapping.to_dict(),'constraints':constraints.to_dict()})
    print({'centers':len(rows),'complete_designs':sum(x['status']=='COMPLETE' for x in inventory),'protocol':ref.sha256})


if __name__=='__main__':
    main()
