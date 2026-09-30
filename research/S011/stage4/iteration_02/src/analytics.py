"""Multi-dimensional diagnostics on immutable complete accounts; no acceptance gates."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import numpy as np
import pandas as pd
from strategy_evaluator import (ReturnMatrixEvidence,hash_return_matrix,cscv_pbo,
    annualized_sharpe,effective_trial_count,calculate_dsr_bundle)
from contracts import pareto_layers
from inputs import FIELDS


def bootstrap_job(task):
    cid,returns,benchmark,settings=task
    rng=np.random.default_rng(settings['seed']); n=len(returns); results=[]
    excess=np.log1p(returns)-np.log1p(benchmark)
    for block in settings['blocks']:
        starts=rng.integers(0,n,size=(settings['repetitions'],int(np.ceil(n/block))))
        index=((starts[:,:,None]+np.arange(block))%n).reshape(len(starts),-1)[:,:n]
        values=excess[index].mean(axis=1)*252
        results.append({'config_id':cid,'block':block,'lower':float(np.quantile(values,.025)),
            'median':float(np.median(values)),'upper':float(np.quantile(values,.975)),
            'positive_share':float((values>0).mean()),'repetitions':len(values)})
    return results


def analyze(data,protocol):
    table=data['evaluations']; configs={c['config_id']:c for c in data['registry']['configurations']}
    comparable=table.loc[table.scope.eq('COMPARABLE_DEVELOPMENT')].drop_duplicates('config_id').copy()
    qualified=comparable.loc[comparable.qualified.eq(True)].copy()
    diagnostics=[]; comparisons=[]; ranking=[]; periods=[]; concentration=[]; component_edges=[]
    def diag(cid,metric,value,unit,scenario='standard',status='COMPLETE',evidence=None,lower=None,upper=None):
        if value is not None and not np.isfinite(value):raise ValueError('nonfinite diagnostic')
        diagnostics.append({'config_id':cid,'metric':metric,'value':value,'unit':unit,'scenario':scenario,
            'status':status,'lower':lower,'upper':upper,'evidence':evidence or data['paths'].get(cid,'family_statistics.json')})
    # Collapse parameter-coordinate duplicates for geometry only. Source identities stay separate.
    coordinates=[]; coordinate_map={}
    for row in comparable.to_dict('records'):
        p=configs[row['config_id']]['definition']['parameters']; key=json.dumps(p,sort_keys=True)
        if key in coordinate_map:
            other=coordinate_map[key]
            if other['behavior_id']!=row['behavior_id']:raise ValueError('same-coordinate source variants have different behavior; require separate geometry groups')
        else:
            point={**p,**row}; coordinate_map[key]=point; coordinates.append(point)
    points=pd.DataFrame(coordinates); values=points[FIELDS].to_numpy(float)
    steps=np.array([protocol['neighbor_steps'][f] for f in FIELDS])
    br=data['benchmark_account'].equity.pct_change(fill_method=None).to_numpy(copy=True); br[0]=data['benchmark_account'].equity.iloc[0]/1e6-1
    tasks=[]; return_vectors={}
    for row in qualified.to_dict('records'):
        cid=row['config_id']; params=configs[cid]['definition']['parameters']
        delta=(values-np.array([params[f] for f in FIELDS]))/steps
        distance=np.abs(delta).max(axis=1); changed=np.abs(delta).gt(1e-8) if isinstance(delta,pd.DataFrame) else np.abs(delta)>1e-8
        eligible=np.flatnonzero(distance>1e-8)
        ordered=sorted(eligible,key=lambda i:(distance[i],points.iloc[i].config_id))
        near=ordered[:protocol['neighbors']['nearest_count']]
        share=float(points.iloc[near].qualified.astype(bool).mean())
        radius=float(distance[near[-1]])
        local=(distance>1e-8)&(distance<=protocol['neighbors']['local_radius']+1e-8)
        joint=local&(changed.sum(axis=1)>=2)
        diag(cid,'knn20_qualified_share',share,'fraction'); diag(cid,'knn20_radius',radius,'diagnostic_step')
        diag(cid,'local_observed_count',int(local.sum()),'configurations')
        diag(cid,'joint_observed_count',int(joint.sum()),'configurations')
        diag(cid,'joint_qualified_share',float(points.loc[joint,'qualified'].mean()) if joint.any() else None,'fraction',status='COMPLETE' if joint.any() else 'MISSING')
        for i in set(near)|set(np.flatnonzero(local)):
            other=points.iloc[i]
            comparisons.append({'config_id':cid,'other_config_id':other.config_id,'kind':'OBSERVED_PARAMETER_NEIGHBOR',
                'distance':float(distance[i]),'changed_dimensions':int(changed[i].sum()),'in_knn20':i in near,'in_local_radius':bool(local[i]),
                'other_qualified':bool(other.qualified),'cagr_delta':float(other.cagr-row['cagr']),
                'drawdown_delta':float(other.drawdown-row['drawdown']),'same_behavior':other.behavior_id==row['behavior_id'],
                'evidence':other.evidence})
            if local[i] and other.qualified:component_edges.append((cid,other.config_id))
        for f in FIELDS:
            lo,hi=protocol['search_envelope'][f]; normalized=(params[f]-lo)/(hi-lo)
            diag(cid,'boundary_distance_'+f,float(min(normalized,1-normalized)),'fraction_of_search_envelope')
        account=data['accounts'][cid]; frames=data['frames'][cid]
        eq=account.equity.to_numpy(); returns=eq/np.r_[1e6,eq[:-1]]-1; return_vectors[cid]=returns
        dates=pd.to_datetime(account.date)
        for unit,labels in [('year',dates.dt.year.astype(str)),('quarter',dates.dt.to_period('Q').astype(str))]:
            for label in labels.unique():
                mask=labels.eq(label).to_numpy(); sr=float(np.prod(1+returns[mask])-1); bh=float(np.prod(1+br[mask])-1)
                periods.append({'config_id':cid,'unit':unit,'period':label,'sessions':int(mask.sum()),'strategy_return':sr,'buyhold_return':bh,'excess':sr-bh})
                diag(cid,'period_excess',sr-bh,'return',scenario=str(label))
        sr=pd.Series(1+returns).rolling(60).apply(np.prod,raw=True).dropna()-1
        bh=pd.Series(1+br).rolling(60).apply(np.prod,raw=True).dropna()-1
        worst=float((sr-bh).min()); positive_share=float((sr>bh).mean())
        diag(cid,'worst_rolling60_excess',worst,'return');diag(cid,'rolling60_positive_excess_share',positive_share,'fraction')
        fills=frames['fills']; trades=frames['trades']
        flows=fills.quantity*fills.price*np.where(fills.side.eq('BUY'),-1,1)-fills.fees
        pnl=flows.groupby(fills.cycle_id).sum().reindex(trades.loc[trades.status.eq('CLOSED'),'cycle_id'])
        positive=pnl[pnl>0].sort_values(ascending=False)
        top3=float(positive.head(3).sum()/positive.sum()) if positive.sum()>0 else None
        diag(cid,'top3_positive_pnl_share',top3,'fraction',status='COMPLETE' if top3 is not None else 'NOT_APPLICABLE')
        concentration.append({'config_id':cid,'closed_trades':len(pnl),'wins':int(pnl.gt(0).sum()),'top3_positive_pnl_share':top3})
        for k in (1,3,5):
            changed_returns=returns.copy(); changed_returns[np.argsort(returns)[-k:]]=0
            diag(cid,f'best_{k}_days_zero_cagr',float(np.prod(1+changed_returns)**(252/len(returns))-1),'annual_return',scenario='COUNTERFACTUAL_NOT_EXECUTABLE')
        for scenario in ['standard','fee_12_5bp','fee_15bp','fee_20bp','fee_25bp','fee_30bp','fee_40bp','fee_50bp']:
            cost=data['costs'].get((cid,scenario))
            diag(cid,'cost_cagr',None if cost is None else float(cost['cagr']),'annual_return',scenario=scenario,status='MISSING' if cost is None else 'COMPLETE',evidence=data['cost_evidence'].get((cid,scenario)))
        fee20=data['costs'].get((cid,'fee_20bp'))
        loss=None if fee20 is None else row['cagr']-float(fee20['cagr'])
        ranking.append({'config_id':cid,'first_reference':configs[cid]['first_reference'],'behavior_id':row['behavior_id'],
            'cagr':row['cagr'],'drawdown_magnitude':row['drawdown_magnitude'],'closed_trades':row['closed_trades'],
            'frequency':row['frequency'],'knn20_qualified_share':share,'knn20_radius':radius,
            'joint_observed_count':int(joint.sum()),'worst_rolling60_excess':worst,'top3_positive_pnl_share':top3,'fee20_cagr_loss':loss})
        tasks.append((cid,returns,br,protocol['bootstrap']))
    with ProcessPoolExecutor(max_workers=protocol['resources']['max_workers'],mp_context=get_context('spawn')) as pool:
        boot=[row for result in pool.map(bootstrap_job,tasks) for row in result]
    for row in boot:
        diag(row['config_id'],'bootstrap_annual_log_excess_median',row['median'],'annual_log_return',scenario=f'block_{row["block"]}',lower=row['lower'],upper=row['upper'])
        diag(row['config_id'],'bootstrap_positive_share',row['positive_share'],'fraction',scenario=f'block_{row["block"]}')
    # Use all behaviors, not only winners. Constant cash paths are disclosed separately.
    distinct=comparable.drop_duplicates('behavior_id'); matrix=[]; ids=[]; excluded=[]
    for row in distinct.itertuples():
        eq=data['accounts'][row.config_id].equity.to_numpy(); r=eq/np.r_[1e6,eq[:-1]]-1
        if np.std(r,ddof=1)<=0:excluded.append(row.config_id)
        else:matrix.append(r);ids.append(row.config_id)
    matrix=np.array(matrix).T
    evidence=ReturnMatrixEvidence(tuple(data['benchmark_account'].date),tuple(ids),tuple(map(tuple,matrix)),'')
    evidence=ReturnMatrixEvidence(evidence.dates,evidence.candidate_ids,evidence.returns,hash_return_matrix(evidence))
    pbo=[cscv_pbo(evidence,n).to_dict() for n in protocol['search_bias']['pbo_blocks']]
    effective=effective_trial_count(matrix); sharpes=np.array([annualized_sharpe(matrix[:,i]) for i in range(matrix.shape[1])])
    dsr=[]
    for cid,returns in return_vectors.items():
        for count in protocol['search_bias']['dsr_counts']:
            bundle=calculate_dsr_bundle(returns,sharpes,raw_count=count,effective_count=effective).to_dict()
            dsr.append({'config_id':cid,'raw_count':count,'result':bundle})
            diag(cid,'dsr_raw_probability',bundle['raw']['probability'],'fraction',scenario=f'count_{count}')
        diag(cid,'dsr_effective_probability',bundle['effective']['probability'],'fraction')
    # Connected components are descriptive observed graphs, not stable-region certificates.
    adjacency={cid:set() for cid in qualified.config_id}
    for a,b in component_edges:
        if b in adjacency:adjacency[a].add(b);adjacency[b].add(a)
    remaining=set(adjacency); groups=[]
    while remaining:
        stack=[min(remaining)]; members=set()
        while stack:
            cid=stack.pop()
            if cid in members:continue
            members.add(cid);stack.extend(adjacency[cid]-members)
        remaining-=members;groups.append(sorted(members))
    layers=pareto_layers(ranking,protocol['ranking']['metrics'])
    sensitivity=pareto_layers(ranking,[m for m in protocol['ranking']['metrics'] if m['name']!='knn20_qualified_share'])
    family={'pbo':pbo,'effective_trial_count':effective,'dsr':dsr,'return_matrix_hash':evidence.content_hash,
        'population_config_ids':ids,'constant_return_exclusions':excluded,'observed_connected_components':groups,
        'geometric_unique_coordinates':len(points),'limitations':protocol['search_bias']['limitations'],
        'independent_validation':False,'full_joint_region_established':False}
    return {'diagnostics':pd.DataFrame(diagnostics),'comparisons':pd.DataFrame(comparisons),'ranking_metrics':pd.DataFrame(ranking),
        'period_returns':pd.DataFrame(periods),'concentration':pd.DataFrame(concentration),'bootstrap':pd.DataFrame(boot),
        'pareto':layers,'pareto_without_knn':sensitivity,'family_statistics':family,
        'returns':pd.DataFrame(matrix,index=pd.Index(evidence.dates,name='date'),columns=ids)}
