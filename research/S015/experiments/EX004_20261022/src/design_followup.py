"""Fix counterexamples and boundary neighbors before evaluating them."""
import json
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,MaterialEvidenceWrite
from run_supplement import ROOT,EROOT,WORK,EXPERIMENT,save


def main():
    rows=json.loads((WORK/'initial_results.json').read_text(encoding='utf-8'))
    diagnostics=json.loads((WORK/'account_diagnostics.json').read_text(encoding='utf-8'))
    assert len(rows)==58
    def key(p):
        return json.dumps(p,sort_keys=True)
    known={key(r['parameters']):r['candidate_id'] for r in rows}
    additions=[]
    reasons=[]
    def add(parameters,reason):
        signature=key(parameters)
        if signature not in known:
            known[signature]=f'C{300+len(additions):04d}'
            additions.append(parameters)
        return {'candidate_id':known[signature],'reason':reason}
    representatives=[]
    for entry in (0.,.0025):
        for sizing,limits,neighbors in [('relative',(1.,1.5),(.75,2.)),('absolute',(.02,.04),(.01,.05))]:
            group=[r for r in rows if r['parameters']['entry']==entry and r['parameters']['sizing']==sizing]
            varying=[r for r in group if 0<diagnostics[r['candidate_id']]['high_amplitude_active_days']<diagnostics[r['candidate_id']]['intent_active_days']]
            if not varying:
                reasons.append({'entry':entry,'sizing':sizing,'reason':'all mappings have constant states; no information counterexample'})
                continue
            representative=sorted(varying,key=lambda r:(-r['observation']['net_cagr'],abs(r['observation']['max_drawdown']),r['candidate_id']))[0]
            p=representative['parameters']
            mean=diagnostics[representative['candidate_id']]['target_mean_intent_active_days']
            reverse_mean=1+p['low_weight']-mean
            const={**p,'sizing':'constant','threshold':0.,'reverse':False}
            comparisons={
                'source':representative['candidate_id'],
                'reverse':add({**p,'reverse':True},'same threshold and weights, reversed amplitude direction'),
                'matched_constant':add({**const,'low_weight':mean},'full-pool active-intent mean target; post-selection diagnostic'),
                'reverse_matched_constant':add({**const,'low_weight':reverse_mean},'reverse mapping own mean target'),
                'active_mean':mean,'reverse_active_mean':reverse_mean}
            representatives.append(comparisons)
            passed=[r for r in varying if r['passed']]
            boundary_reps=[representative]
            if passed:
                boundary_reps.append(min(passed,key=lambda r:(abs(r['observation']['max_drawdown']),-r['observation']['net_cagr'],r['candidate_id'])))
            for risk in boundary_reps[1:]:
                if risk['candidate_id']==representative['candidate_id']:
                    continue
                q=risk['parameters']
                risk_mean=diagnostics[risk['candidate_id']]['target_mean_intent_active_days']
                reversed_mean=1+q['low_weight']-risk_mean
                base={**q,'sizing':'constant','threshold':0.,'reverse':False}
                representatives.append({'source':risk['candidate_id'],'selection':'minimum drawdown among initial center passes',
                    'reverse':add({**q,'reverse':True},'risk frontier direction counterexample'),
                    'matched_constant':add({**base,'low_weight':risk_mean},'risk frontier active mean'),
                    'reverse_matched_constant':add({**base,'low_weight':reversed_mean},'risk frontier reverse active mean'),
                    'active_mean':risk_mean,'reverse_active_mean':reversed_mean})
            for r in boundary_reps:
                threshold=r['parameters']['threshold']
                if threshold in limits:
                    neighbor=neighbors[limits.index(threshold)]
                    reasons.append({'source':r['candidate_id'],**add({**r['parameters'],'threshold':neighbor},'boundary neighbor for highest-return or lowest-drawdown passing representative')})
    prior=EROOT/'others/followup_ref.json'
    if prior.exists():
        save(EROOT/'others/followup_prior_ref.json',json.loads(prior.read_text(encoding='utf-8')))
        save(EROOT/'protocols/followup_prior.json',json.loads((EROOT/'protocols/followup.json').read_text(encoding='utf-8')))
    design={'configurations':additions,'count':len(additions),'representatives':representatives,'boundary_checks':reasons,
        'design_revision':'补齐最小回撤达标代表的匹配/反向对照；原19点设计尚未执行。预留24点为软预算，风险解释需与收益代表同样辨别，因此调整。',
        'selection_timing':'After all58 initial accounts; no followup account observed at design publication',
        'limits':'Matching target means does not match realized exposure exactly; compare residuals and fees. No independent validation claim.',
        'next':'Inspect boundary outcomes before stopping; further extension only when mechanism question remains.'}
    save(EROOT/'protocols/followup.json',design)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'))
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'followup_design',(EROOT/'protocols/followup.json').read_bytes(),'application/json','json'))
    save(EROOT/'others/followup_ref.json',ref.to_dict())
    print(json.dumps({'count':len(additions),'representatives':representatives,'boundaries':reasons},ensure_ascii=False))


if __name__=='__main__':
    main()
