"""Close the remaining low-threshold improvement and record saturated upper limits."""
import json
import numpy as np
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,MaterialEvidenceWrite
from run_supplement import ROOT,EROOT,WORK,EXPERIMENT,save
from analyze_supplement import load_evidence,table


def main():
    rows=json.loads((WORK/'initial_results.json').read_text(encoding='utf-8'))+json.loads((WORK/'followup_results.json').read_text(encoding='utf-8'))
    details=json.loads((WORK/'account_diagnostics.json').read_text(encoding='utf-8'))
    by_id={r['candidate_id']:r for r in rows}
    additions=[]
    comparisons=[]
    def add(p):
        cid=f'C{400+len(additions):04d}'
        additions.append(p)
        return cid
    for cid in ('C0307','C0323'):
        p=by_id[cid]['parameters']
        mean=details[cid]['target_mean_intent_active_days']
        base={**p,'sizing':'constant','threshold':0.,'reverse':False}
        comparisons.append({'source':cid,'reverse':add({**p,'reverse':True}),
            'matched_constant':add({**base,'low_weight':mean}),
            'reverse_matched_constant':add({**base,'low_weight':1+p['low_weight']-mean}),
            'lower_neighbor':add({**p,'threshold':.5})})
    saturation=[]
    for cid in ('C0201','C0230'):
        decisions=table(load_evidence(by_id[cid]),'decisions')
        active=decisions.intent_age>0
        for field in ('range_ratio','range5'):
            values=decisions.loc[active,field].to_numpy(float)
            # Strict > means threshold==observed maximum already produces all-full weights.
            maximum=float(values.max())
            assert not np.any(values>maximum)
            saturation.append({'control':cid,'feature':field,'active_min':float(values.min()),
                'active_max':maximum,'upper_saturation_threshold':maximum,
                'result':'threshold at or above active maximum is the recorded full-weight signal; same equity policy',
                'scope':'signal-level deterministic equality in this seen pool; no new account claimed'})
    d={'configurations':additions,'count':len(additions),'comparisons':comparisons,'upper_saturation':saturation,
       'reason':'relative .75/low_weight .5 contains a new passing risk frontier for entry0; match/reverse both anchors and test .5 lower neighbor before stopping',
       'timing':'after89 completed configurations, before these8 accounts',
       'scope':'diagnostic extension, not stage-four perturbations or cost stress'}
    save(EROOT/'protocols/boundary.json',d)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'))
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'boundary_design',(EROOT/'protocols/boundary.json').read_bytes(),'application/json','json'))
    save(EROOT/'others/boundary_ref.json',ref.to_dict())
    print(json.dumps(d,ensure_ascii=False))


if __name__=='__main__':
    main()
