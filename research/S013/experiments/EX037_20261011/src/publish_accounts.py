"""Retain both full accounts; register only original-four-gate qualifiers."""
from czsc_trader.application import publish_evidence,register_candidate,load_candidate,CandidateRegistrationRequest
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey,CandidateDerivation,CandidateDerivationKind,CandidateEvidence
from strategy_runtime import StrategyRuntime
from common import ROOT,PROTOCOLS,RUNS,CACHE,EXPERIMENT,DEPENDENCIES,context,read,write,cache_read,file_hash


def main():
    assert not (RUNS/'account_references.json').exists()
    analysis=read(RUNS/'analysis.json')
    plan=read(PROTOCOLS/'plan.json')
    assert analysis['status']=='PASS'
    ctx=context(1)
    refs={label:EvidenceRef.from_dict(value['reference']) for label,value in analysis['control_reuse'].items()}
    origin=analysis['rows']['B0-TIME']
    original_ref=refs['B0-TIME']
    assert origin['qualified']
    registrations=[]
    for cfg in plan['configurations']:
        label=cfg['label']
        bound,result=cache_read(CACHE/(label+'.pkl.gz'))
        ref=publish_evidence(ctx,EvaluationEvidenceWrite(EXPERIMENT,'adverse-tr-'+label.lower(),bound,result))
        refs[label]=ref
        if analysis['rows'][label]['qualified']:
            parent=refs[cfg['parent_control']]
            assert file_hash(parent.resolve(ROOT))==parent.sha256
            derivation=CandidateDerivation(CandidateKey('S013',origin['candidate_id']),origin['content_sha256'],
                CandidateKey('S013',cfg['candidate_id']),cfg['content_sha256'],CandidateDerivationKind.IMPLEMENTATION,
                {'mechanism':{'before':'original raw bear ACF entry and TIME exits',
                    'after':cfg['mechanism'],'intermediate_unqualified_background_reference':parent.to_dict(),
                    'risk_exit':'held bear adverse HFQ entry displacement >= strictlypast20TR mean; no wait'},
                    'numeric_coordinates':'all13 original numeric values and H units preserved; ACF baseline/optionalBODY and risk constants disclosed'},
                file_hash(PROTOCOLS/'plan.json'),CandidateEvidence(original_ref.repository_path,original_ref.sha256))
            record=register_candidate(ctx.repository,CandidateRegistrationRequest(bound.strategy,EXPERIMENT,(ref,),DEPENDENCIES,derivation))
            assert StrategyRuntime().identify(load_candidate(ctx.repository,record.key),dependencies=DEPENDENCIES).content_sha256==cfg['content_sha256']
            registrations.append(record.to_dict())
    write(RUNS/'account_references.json',{label:ref.to_dict() for label,ref in refs.items()})
    write(RUNS/'registration.json',{'status':'PASS','new_qualified':len(registrations),'registrations':registrations,
        'not_selection':'No formal stage4 handoff, freeze, PTE or production.'})
    print({'published_new_accounts':2,'new_qualified':len(registrations)},flush=True)


if __name__=='__main__':
    main()
