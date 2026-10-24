"""Descriptive arithmetic on authenticated projections; no new acceptance gates."""
from stage4 import OUT, CENTERS, read, save, m, np, source_rows


def performance(item):
    e = np.array([p.equity for p in item.account])
    b = np.array(item.benchmark_equity)
    return {'net_return':float(e[-1]/item.initial_cash-1),
            'annual_return':float((e[-1]/item.initial_cash)**(252/len(e))-1),
            'drawdown':float(1-np.min(e/np.maximum.accumulate(np.r_[item.initial_cash,e])[1:])),
            'benchmark_annual_return':float((b[-1]/item.initial_cash)**(252/len(b))-1),
            'benchmark_drawdown':float(1-np.min(b/np.maximum.accumulate(np.r_[item.initial_cash,b])[1:])),
            'fees':float(sum(x.fees for x in item.fills)),'closed_cycles':len(item.closed_cycles)}


def windows(item):
    e = np.r_[item.initial_cash,[p.equity for p in item.account]]
    b = np.r_[item.initial_cash,item.benchmark_equity]
    result = []
    for start in range(0,len(item.account)-252+1,21):
        end = start+252
        result.append({'start':item.account[start].session,'end':item.account[end-1].session,
                       'return':float(e[end]/e[start]-1),'benchmark_return':float(b[end]/b[start]-1)})
    return result


def main():
    assert not (OUT/'descriptive_checks.json').exists()
    items = [m.AssessmentEvidence.from_dict(v) for v in read(OUT/'authenticated_accounts.json')]
    lookup = {(x.candidate.candidate_id.removeprefix('S015-'),x.scenario_id):x for x in items}
    rows=[]
    for cid in CENTERS:
        item = lookup[cid,'standard']
        years=[]
        equity = np.r_[item.initial_cash,[p.equity for p in item.account]]
        for year in ('2025','2026'):
            indices=[i for i,p in enumerate(item.account) if p.session.startswith(year)]
            years.append({'year':year,'return':float(equity[indices[-1]+1]/equity[indices[0]]-1)})
        rolling=windows(item)
        winner=[]
        for cycle in item.closed_cycles:
            fills=[f for f in item.fills if f.cycle_id==cycle.cycle_id]
            pnl=sum((1 if f.side.value=='SELL' else -1)*f.price*f.quantity-f.fees for f in fills)
            if pnl>0:
                winner.append(pnl)
        count=int(np.ceil(.1*len(winner)))
        std,stress=performance(item),performance(lookup[cid,'fee_x2'])
        passed=(stress['annual_return']>max(0,stress['benchmark_annual_return'])
                and stress['drawdown']<stress['benchmark_drawdown'] and stress['drawdown']<=.25)
        rows.append({'candidate_id':cid,'standard':std,'stress':stress,'pressure_targets_pass':bool(passed),
            'annualized_pressure_loss':std['annual_return']-stress['annual_return'],
            'years':years,'rolling252_step21':rolling,
            'rolling_excess_positive_count':sum(v['return']>v['benchmark_return'] for v in rolling),
            'rolling_excess_q10':float(np.quantile([v['return']-v['benchmark_return'] for v in rolling],.1)),
            'terminal252_return':float(equity[-1]/equity[-253]-1),
            'winning_cycles':len(winner),'top_decile_count':count,
            'top_decile_profit_share':float(sum(sorted(winner)[-count:])/sum(winner)),
            'top5_profit_share':float(sum(sorted(winner)[-5:])/sum(winner))})
    historical=source_rows()
    controls=[]
    for cid in ('C6118','C6105','C6120','C6124','C6126'):
        row=next(r for r in historical if r['candidate_id']==cid)
        controls.append({key:row[key] for key in ('candidate_id','parameters','runs','evidence')})
    mainwindows=windows(lookup['C6105','standard'])
    basewindows=windows(lookup['C6102','standard'])
    for a,b in zip(mainwindows,basewindows,strict=True):
        assert (a['start'],a['end'])==(b['start'],b['end'])
    summary={'status':'DESCRIPTIVE_CHECKS_COMPLETE','new_accounts':0,'rows':rows,
        'existing_discrete_controls':controls,'main_versus_immediate':[
            {'start':a['start'],'end':a['end'],'main_return':a['return'],
             'immediate_return':b['return'],'difference':a['return']-b['return']}
            for a,b in zip(mainwindows,basewindows,strict=True)],
        'interpretation':'Descriptive inherited-account windows and previously seen controls; not new independent samples, not prescribed parameter points, no causal subtraction or new thresholds.'}
    assert len(rows)==16 and all(len(r['rolling252_step21'])==9 for r in rows)
    save(OUT/'descriptive_checks.json',summary)
    print({'pressure_passes':sum(r['pressure_targets_pass'] for r in rows),'rows':len(rows)})


if __name__=='__main__':
    main()
