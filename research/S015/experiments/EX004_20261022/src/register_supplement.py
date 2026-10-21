"""Register every passing configuration and the descriptive return/drawdown frontier."""
import json
from czsc_trader.application import RepositoryContext,CandidateRegistrationRequest,register_candidate,load_candidate
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import StrategyRuntime
from run_supplement import ROOT,EROOT,WORK,EXPERIMENT,candidate,save
from analyze_supplement import frontier


def main():
    analysis=json.loads((WORK/'analysis.json').read_text(encoding='utf-8'))
    assert analysis['published_snapshot_complete']
    rows=[]
    for phase in ('initial','followup','boundary'):
        rows+=json.loads((WORK/f'{phase}_results.json').read_text(encoding='utf-8'))
    fronts={r['candidate_id'] for r in frontier(rows)}
    selected=[r for r in rows if r['passed'] or r['candidate_id'] in fronts]
    repo=RepositoryContext.discover(ROOT)
    records=[]
    for r in selected:
        c=candidate(int(r['candidate_id'][1:]),r['parameters'])
        reg=register_candidate(repo,CandidateRegistrationRequest(c,EXPERIMENT,(EvidenceRef.from_dict(r['evidence']),),()))
        loaded=load_candidate(repo,reg.key)
        identity=StrategyRuntime().identify(loaded,dependencies=())
        assert identity.content_sha256==reg.content_sha256
        records.append({'candidate_id':r['candidate_id'],'content_sha256':reg.content_sha256,
            'registration':reg.to_dict(),'passed':r['passed'],'handoff':r['passed'],'frontier':r['candidate_id'] in fronts})
    save(EROOT/'others/registrations.json',records)
    print(json.dumps({'registered':len(records),'handoff':sum(r['passed'] for r in records),'identity':'PASS'},ensure_ascii=False))


if __name__=='__main__':
    main()
