"""Apply the latest public five diagnostics to retained S013 accounts only."""
import importlib.util
import sys

from strategy_evaluator import AssessmentEvidence
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
import s013_existing_candidate_review as base


def main():
    source = base.ROOT/'research/S013/experiments/EX074_20261011/src/economics_reference.py'
    spec = importlib.util.spec_from_file_location('review_five_economics', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    centres = {r['candidate_id']:r for r in base.read(base.OUT/'centres.json')['rows'] if r['status']=='CURRENT_CONTRACT'}
    stresses = {}
    for ref in base.read(base.OUT/'account_reference_index.json'):
        if not any(w in ref['name'] for w in ('fee','stress')):
            continue
        ev = base.read(base.ref_path(ref))
        validate_evaluation_evidence(ev)
        a = ev['assessment_evidence'][0]
        cid = a['candidate']['candidate_id'].removeprefix('S013-')
        if cid in centres and a['scenario_context']['one_way_cost']==.002 and a['scenario_context']['benchmark_contract_sha256']==base.CONTRACT:
            assert a['candidate']['content_sha256']==centres[cid]['content_sha256']
            stresses[cid]=(ref,AssessmentEvidence.from_dict(a))
    output=[]
    for p in base.read(base.OUT/'standard32.json')['rows']:
        cid=p['candidate_id']
        centre=base.read(base.ROOT/centres[cid]['source'])['assessment_evidence'][0]
        points=tuple(AssessmentEvidence.from_dict(base.read(base.ref_path(r['reference']))['assessment_evidence'][0]) for r in p['points'])
        plan=read_parameter_plan(EvidenceRef.from_dict(p['plan_reference']),repository_root=base.ROOT)
        checked=module.assess_facts(center=AssessmentEvidence.from_dict(centre),points=points,design=plan.design,
                                   stress=stresses[cid][1] if cid in stresses else None)
        row=checked.panel.to_dict()['rows'][0]
        output.append({'candidate_id':cid,'panel_row':row,'protocol':module.protocol(plan.design).to_dict(),
              'absolute_q10_cagr':checked.economics['absolute_q10_cagr'],
              'absolute_q90_drawdown':checked.economics['absolute_q90_drawdown'],
              'stress_reference':stresses[cid][0] if cid in stresses else None,
              'fee_evidence_status':'AVAILABLE' if cid in stresses else 'CURRENT_FORMAL_STRESS_ACCOUNT_NOT_IN_DECLARED_CANDIDATE_EVIDENCE',
              'stress_economics':checked.economics['stress'], 'limitations':checked.limitations})
        print(cid,'latest five diagnostics computed; fee',cid in stresses,flush=True)
    base.save('latest_five_diagnostics.json',{'status':'COMPLETE_WITH_EXPLICIT_FEE_AND_FAMILY_GAPS',
               'helper_source_sha256':base.digest(source),'rows':output,'new_account_evaluations':0,
               'new_parameter_designs':0,'new_models':0})


if __name__=='__main__':
    main()
