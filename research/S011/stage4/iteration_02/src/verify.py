"""Independent numerical checks of saved layers, PBO, effective count and bootstrap."""
from pathlib import Path
from hashlib import sha256
import argparse,json
import numpy as np
import pandas as pd
from scipy.stats import norm
from inputs import REPO
from build import validate,dump


def independent_sharpes(matrix):
    values=[]
    for column in matrix.T:
        mean=float(np.mean(column));std=float(np.std(column,ddof=1))
        values.append(np.sqrt(252)*mean/std if std>0 else (0.0 if mean==0 else float('nan')))
    return np.array(values)


def audit(package,output):
    if output.exists() or not output.is_relative_to(REPO/'.tmp'):raise ValueError('use fresh .tmp output')
    validate(package)
    protocol=json.loads((package/'protocol.json').read_text())
    ranking=pd.read_parquet(package/'ranking_metrics.parquet')
    pareto=json.loads((package/'pareto.json').read_text())
    metric_names=[m['name'] for m in pareto['metrics']]
    valid=ranking.dropna(subset=metric_names).copy()
    vectors=np.column_stack([np.array([round(float(v),m['decimals']) for v in valid[m['name']]])*(1 if m['direction']=='maximize' else -1) for m in pareto['metrics']])
    # Matrix relation: row i dominates column j.
    relation=(vectors[:,None,:]>=vectors[None,:,:]).all(axis=2)&(vectors[:,None,:]>vectors[None,:,:]).any(axis=2)
    for j,cid in enumerate(valid.config_id):
        assert set(valid.config_id.iloc[np.flatnonzero(relation[:,j])])==set(pareto['dominated_by'][cid])
    remaining=np.ones(len(valid),dtype=bool)
    for layer in pareto['layers']:
        front=np.flatnonzero(remaining&~relation[remaining].any(axis=0))
        assert set(valid.config_id.iloc[front])==set(layer['config_ids']);remaining[front]=False
    assert not remaining.any()
    family=json.loads((package/'family_statistics.json').read_text())
    returns=pd.read_parquet(package/'returns.parquet').set_index('date');matrix=returns.to_numpy()
    assert returns.columns.tolist()==family['population_config_ids']
    corr=np.corrcoef(matrix,rowvar=False)
    independent_effective=float(np.trace(corr)**2/(corr*corr).sum())
    assert abs(independent_effective-family['effective_trial_count'])<1e-10
    split_count=0
    for pbo in family['pbo']:
        blocks=np.array_split(np.arange(len(returns)),pbo['block_count']);adverse=0
        for split in pbo['splits']:
            tr=np.concatenate([blocks[i] for i in split['training_blocks']]);te=np.concatenate([blocks[i] for i in split['validation_blocks']])
            train=independent_sharpes(matrix[tr]);test=independent_sharpes(matrix[te])
            winner=min(np.flatnonzero(np.isfinite(train)),key=lambda i:(-train[i],returns.columns[i]))
            order=sorted(np.flatnonzero(np.isfinite(test)),key=lambda i:(-test[i],returns.columns[i]));rank=order.index(winner)+1
            percentile=(len(order)-rank)/(len(order)-1)
            assert returns.columns[winner]==split['selected_candidate'] and rank==split['validation_rank']
            assert abs(percentile-split['validation_percentile'])<1e-12
            adverse+=percentile<.5;split_count+=1
        assert abs(adverse/len(pbo['splits'])-pbo['pbo'])<1e-12
    for bundle in family['dsr']:
        for mode in ('raw','effective'):
            item=bundle['result'][mode]
            variance=1-item['skew']*item['observed_sharpe']/np.sqrt(252)+(item['pearson_kurtosis']-1)/4*(item['observed_sharpe']/np.sqrt(252))**2
            z=(item['observed_sharpe']-item['expected_max_sharpe'])/np.sqrt(252)*np.sqrt(item['observations']-1)/np.sqrt(variance)
            assert abs(norm.cdf(z)-item['probability'])<1e-12
    evaluations=pd.read_parquet(package/'evaluations.parquet')
    boot=pd.read_parquet(package/'bootstrap.parquet')
    benchmark=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX16/artifacts/benchmark_account_daily.csv.gz')
    br=benchmark.equity.to_numpy()/np.r_[1e6,benchmark.equity.to_numpy()[:-1]]-1
    checked=0
    ids=[ranking.config_id.iloc[0],ranking.config_id.iloc[len(ranking)//2],ranking.config_id.iloc[-1]]
    for cid in ids:
        path=evaluations.loc[evaluations.config_id.eq(cid)].iloc[0].evidence
        eq=pd.read_csv(REPO/path/'account_daily.csv.gz').equity.to_numpy();r=eq/np.r_[1e6,eq[:-1]]-1
        excess=np.log1p(r)-np.log1p(br);rng=np.random.default_rng(protocol['bootstrap']['seed']);n=len(r)
        for block in protocol['bootstrap']['blocks']:
            starts=rng.integers(0,n,size=(protocol['bootstrap']['repetitions'],int(np.ceil(n/block))))
            idx=np.concatenate([(starts[:,j,None]+np.arange(block))%n for j in range(starts.shape[1])],axis=1)[:,:n]
            samples=np.take(excess,idx).sum(axis=1)/n*252
            row=boot.loc[boot.config_id.eq(cid)&boot.block.eq(block)].iloc[0]
            assert np.allclose([row.lower,row['median'],row.upper,row.positive_share],[*np.quantile(samples,[.025,.5,.975]),(samples>0).mean()],rtol=0,atol=1e-12)
            checked+=1
    report={'status':'PASS','package_manifest_sha256':sha256((package/'manifest.json').read_bytes()).hexdigest(),
        'independent_dominance_matrix':True,'pbo_splits_checked':split_count,'effective_count_trace_check':True,
        'dsr_bundles_checked':len(family['dsr']),'bootstrap_cases_checked':checked,'pending_user_decision':True,
        'scope':'Statistics and package checks; prior complete-account audits retained, not independent market-data validation'}
    output.mkdir(parents=True);dump(output/'verification.json',report);print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    audit(a.package.resolve(),a.output.resolve())
