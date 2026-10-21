"""Retained-account diagnostics and public registration of the declared candidate set."""
from datetime import date
import json

from czsc_trader.application import (RepositoryContext, diagnose_accounts,
    CandidateRegistrationRequest, register_candidate, load_candidate)
from czsc_trader.research_tools import (EvidenceRef, EvaluationIdentity, AccountRunRef,
    AccountDiagnosisRequest, EvaluationWindow)
from strategy_manager import CandidateKey
from strategy_runtime import StrategyRuntime
from run_strategy_study import ROOT, WORK, EROOT, EXPERIMENT, candidate, save
from analyze_strategy_study import rows, frontier, evidence, account_details


def main():
    all_rows=rows()
    assert len(all_rows)==84 and all('observation' in r for r in all_rows)
    selected_ids={r['candidate_id'] for r in frontier(all_rows)} | {r['candidate_id'] for r in all_rows if r['passed']}
    selected=[r for r in all_rows if r['candidate_id'] in selected_ids]
    details={r['candidate_id']:account_details(r) for r in selected}
    save(WORK/'account_diagnostics.json',details)
    repo=RepositoryContext.discover(ROOT)
    def runref(cid):
        row=next(r for r in all_rows if r['candidate_id']==cid)
        identity=evidence(row)['runs'][0]['identity']
        ident=EvaluationIdentity(CandidateKey(**identity['candidate']),**{k:v for k,v in identity.items() if k!='candidate'})
        return AccountRunRef(EvidenceRef.from_dict(row['evidence']),ident)
    diagnoses=[]
    for baseline,alternative in [('C0031','C0046'),('C0031','C0108'),('C0031','C0026')]:
        result=diagnose_accounts(repo,AccountDiagnosisRequest(runref(baseline),runref(alternative),
            EvaluationWindow('full',date(2025,1,2),date(2026,10,21))))
        diagnoses.append({'baseline':baseline,'alternative':alternative,'result':result.to_dict()})
        print('diagnosis',baseline,alternative,result.status,flush=True)
    save(WORK/'public_account_diagnoses.json',diagnoses)
    registrations=[]
    for row in selected:
        c=candidate(int(row['candidate_id'][1:]),row['parameters'])
        registration=register_candidate(repo,CandidateRegistrationRequest(c,EXPERIMENT,
            (EvidenceRef.from_dict(row['evidence']),),()))
        loaded=load_candidate(repo,registration.key)
        identified=StrategyRuntime().identify(loaded,dependencies=())
        assert identified.content_sha256==registration.content_sha256
        registrations.append({'candidate_id':row['candidate_id'],'content_sha256':registration.content_sha256,
            'registration':registration.to_dict(),'passed':row['passed'],
            'handoff':row['passed'],'frontier':row in frontier(all_rows)})
    save(EROOT/'others/registrations.json',registrations)
    print(json.dumps({'registered':len(registrations),'handoff':sum(r['handoff'] for r in registrations),
        'load_identity_check':'PASS'},ensure_ascii=False))


if __name__=='__main__':
    main()
