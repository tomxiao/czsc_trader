"""Publish the complete contrast; register only original-four-gate qualifier."""
from czsc_trader.application import publish_evidence, register_candidate, load_candidate, CandidateRegistrationRequest
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import StrategyRuntime
from run_parameters import authenticate_refresh_parent
from common import PROTOCOLS, RUNS, CACHE, EXPERIMENT, DEPENDENCIES, context, read, write, cache_read, file_hash


def main():
    assert not (RUNS/'account_references.json').exists()
    a=read(RUNS/'analysis.json')
    plan=read(PROTOCOLS/'plan.json')
    assert a['status']=='PASS'
    cfg=plan['configurations'][0]
    ctx=context(1)
    bound,result=cache_read(CACHE/'N0.pkl.gz')
    newref=publish_evidence(ctx,EvaluationEvidenceWrite(EXPERIMENT,'information-mechanism-n0',bound,result))
    oldrefs={label:EvidenceRef.from_dict(value['reference']) for label,value in a['control_reuse'].items()}
    proof=authenticate_refresh_parent(ctx,cfg,plan,{label:ref.to_dict() for label,ref in oldrefs.items()})
    write(RUNS/'implementation_parent.json',proof)
    oldref=oldrefs['C0-RANGE_REFRESH']
    write(RUNS/'account_references.json',{'N0':newref.to_dict(),**{label:ref.to_dict() for label,ref in oldrefs.items()}})
    registered=[]
    if a['rows']['N0']['qualified']:
        parent=a['rows']['C0-RANGE_REFRESH']
        derivation=CandidateDerivation(CandidateKey('S013',parent['candidate_id']),parent['content_sha256'],
            CandidateKey('S013',cfg['candidate_id']),cfg['content_sha256'],CandidateDerivationKind.IMPLEMENTATION,
            {'entry_refresh':{'before':'EX034 pending clears at flat rawroute!=bear or bear range>entry',
                              'after':'Same arming; flat release additionally when enabled original bear ACF/momentum strictly below threshold; equality retains; score excluded; all13 original numeric values and H units unchanged'},
             'mechanism':cfg['mechanism']},file_hash(PROTOCOLS/'plan.json'),CandidateEvidence(oldref.repository_path,oldref.sha256))
        record=register_candidate(ctx.repository,CandidateRegistrationRequest(bound.strategy,EXPERIMENT,(newref,),DEPENDENCIES,derivation))
        assert StrategyRuntime().identify(load_candidate(ctx.repository,record.key),dependencies=DEPENDENCIES).content_sha256==cfg['content_sha256']
        registered.append(record.to_dict())
    write(RUNS/'registration.json',{'status':'PASS','new_qualified':len(registered),'registrations':registered,
        'not_selection':'No formal stage4 ranking/handoff, freezing or PTE activation.'})
    print({'published_new_accounts':1,'new_qualified':len(registered)},flush=True)


if __name__=='__main__':
    main()
