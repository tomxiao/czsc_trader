"""Verify complete first-center seven diagnostics before the rest of the batch."""
from strategy_evaluator import CandidateAssessmentRequest, SelfCheckProtocol, PerturbationLink, assess_candidates, CandidateComparisonRequest, ResearchTargets, ComparisonPolicy, compare_candidates
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.delivery import PerformanceRequirement
from common import PROTOCOLS, RUNS, CACHE, centers, facts, read, write, source
from assess import independent_checks

def main():
    if (RUNS/'se_precheck.json').exists():
        assert read(RUNS/'se_precheck.json')['status']=='PASS'
        return
    plan=read(PROTOCOLS/'plan.json')
    center=centers()[0]
    base=facts(center.evaluations[0].evidence)[0]
    children={c['candidate_id'] for c in plan['cases'] if c['kind']=='PARAMETERS' and c['parent']==center.identity.to_dict()}
    evidence=[base]
    for row in read(RUNS/'rows.json')['rows']:
        if (row['kind']=='PARAMETERS' and row['candidate_id'] in children) or (row['kind']=='STRESS' and row['candidate_id']==center.identity.key.candidate_id):
            evidence.extend(facts(EvidenceRef.from_dict(row['reference'])))
    assert len(evidence)==11
    links=tuple(PerturbationLink(e.parent,e.candidate,1.,e.derivation_sha256) for e in evidence[1:] if e.candidate.candidate_id[5:] in children)
    req=CandidateAssessmentRequest((base.candidate,),SelfCheckProtocol.from_dict(plan['protocol']),links,tuple(evidence))
    panel=assess_candidates(req)
    checks=independent_checks(req,panel,[],expected_centers=1)
    targets=tuple(t for i in source('MANDATE',5).payload.items if isinstance(i.requirement,PerformanceRequirement) for t in i.requirement.targets)
    comparison=compare_candidates(CandidateComparisonRequest((base.candidate,),ResearchTargets(targets,60),panel,ComparisonPolicy.from_dict(plan['comparison_policy'])))
    write(RUNS/'se_precheck.json',{'status':'PASS','scope':'first fully evaluated center; seven metrics, all 11 account reconciliation, paired bootstrap and same standard comparison',
        'checks':checks,'panel':panel.to_dict(),'comparison':comparison.to_dict(),'family':'full79-family diagnostic deferred to complete assessment'})
    print({'se_precheck':'PASS','center':base.candidate.candidate_id},flush=True)
    if (CACHE/'scheduler_checkpoint.json').exists():
        print({'checkpoint':'COMPLETE_BATCH_AND_SE_PRECHECK','next':'same-plan four-process end-to-end scheduler'},flush=True)
        raise SystemExit(0)

if __name__=='__main__':
    main()
