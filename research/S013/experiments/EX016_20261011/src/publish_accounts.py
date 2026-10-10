"""Publish every mechanism account and register all original-four-gate qualifiers."""
from czsc_trader.application import publish_evidence_many,register_candidate,load_candidate,CandidateRegistrationRequest
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey,CandidateDerivation,CandidateDerivationKind,CandidateEvidence
from strategy_runtime import StrategyRuntime
from common import PROTOCOLS,RUNS,CACHE,EXPERIMENT,DEPENDENCIES,context,read,write,cache_read,file_hash

def main():
    assert not (RUNS/'account_references.json').exists()
    analysis=read(RUNS/'analysis.json')
    assert analysis['status']=='PASS'
    plan=read(PROTOCOLS/'plan.json')
    ctx=context()
    pairs=[cache_read(CACHE/(cfg['label']+'.pkl.gz')) for cfg in plan['configurations']]
    outcomes=publish_evidence_many(ctx,tuple(EvaluationEvidenceWrite(EXPERIMENT,'information-mechanism-'+cfg['label'].lower(),bound,result)
        for cfg,(bound,result) in zip(plan['configurations'],pairs,strict=True)))
    assert all(o.status.value=='PUBLISHED' for o in outcomes)
    refs={cfg['label']:o.reference for cfg,o in zip(plan['configurations'],outcomes,strict=True)}
    refs.update({label:EvidenceRef.from_dict(reuse['reference']) for label,reuse in analysis['control_reuse'].items()})
    write(RUNS/'account_references.json',{label:ref.to_dict() for label,ref in refs.items()})
    registrations=[]
    parent=analysis['rows']['B0-TIME']
    for cfg,(bound,result) in zip(plan['configurations'],pairs,strict=True):
        if not analysis['rows'][cfg['label']]['qualified']:
            continue
        derivation=CandidateDerivation(CandidateKey('S013','C2132'),parent['content_sha256'],
            CandidateKey('S013',cfg['candidate_id']),cfg['content_sha256'],CandidateDerivationKind.IMPLEMENTATION,
            {'mechanism':cfg['mechanism'],'background':cfg['background']},file_hash(PROTOCOLS/'plan.json'),
            CandidateEvidence(refs['B0-TIME'].repository_path,refs['B0-TIME'].sha256))
        registered=register_candidate(ctx.repository,CandidateRegistrationRequest(bound.strategy,EXPERIMENT,
            (refs[cfg['label']],),DEPENDENCIES,derivation))
        loaded=load_candidate(ctx.repository,registered.key)
        assert StrategyRuntime().identify(loaded,dependencies=DEPENDENCIES).content_sha256==cfg['content_sha256']
        registrations.append({'label':cfg['label'],'record':registered.to_dict()})
    write(RUNS/'registration.json',{'status':'PASS','new_qualified':len(registrations),'registrations':registrations,
        'not_selection':'All four-gate qualifications retained; no formal stage-four ranking, selection, freezing or PTE activation.'})
    print({'published_new_accounts':8,'new_qualified':len(registrations),'labels':[r['label'] for r in registrations]},flush=True)

if __name__=='__main__':
    main()
