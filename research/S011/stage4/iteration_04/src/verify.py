"""Independent grid, Pareto and exhaustive within-layer position checks.

Does not import production ranking/build implementations. Writes no sealed files.
"""
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
from itertools import combinations,permutations
from hashlib import sha256
import json
import argparse
import pandas as pd
import numpy as np

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def hashed(p):return sha256(p.read_bytes()).hexdigest()
def cell(v,m):return int(((Decimal(str(v))-Decimal(m['origin']))/Decimal(m['resolution'])).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def verify(package):
    manifest=read(package/'manifest.json')
    for p,h in manifest['files'].items():assert hashed(package/p)==h,p
    for p,h in manifest['inputs'].items():assert hashed(ROOT/p)==h,p
    frame=pd.read_parquet(package/'rankings.parquet');rows={r['config_id']:r for r in frame.to_dict('records')}
    policy=read(package/'ranking_policy.json');spec=policy['pareto_metrics'];order=policy['recommendation_order']
    original=pd.read_parquet(ROOT/'research/S011/stage4/iteration_03/ranking_metrics.parquet')
    assert len(rows)==36 and set(rows)==set(original.config_id)
    qualified=read(package/'qualified_configurations.json')['configurations']
    assert len(qualified)==36 and all(v['return_pass'] and v['drawdown_pass'] and v['frequency_pass'] for v in qualified)
    assert frame.frequency.between(4,6).all()
    vectors={cid:tuple(cell(r[m['name']],m)*(1 if m['direction']=='maximize' else -1) for m in spec) for cid,r in rows.items()}
    left=set(rows);layers=[]
    while left:
        front=sorted(a for a in left if not any(b!=a and all(x>=y for x,y in zip(vectors[b],vectors[a])) and vectors[b]!=vectors[a] for b in left))
        assert front;layers.append(front);left.difference_update(front)
    assert layers==[v['config_ids'] for v in read(package/'pareto.json')['layers']]
    saved={(p['config_a'],p['config_b']):p for p in read(package/'ranking_explanations.json')['pairs']}
    permutation_count=0;unknown_count=0
    for depth,ids in enumerate(layers,1):
        precedes=[]
        for a,b in combinations(ids,2):
            winner=None;relation='TIE';first=None
            for m in order:
                x,y=rows[a][m['name']],rows[b][m['name']]
                if pd.isna(x) or pd.isna(y):relation='INCOMPARABLE';first=m['name'];break
                ca,cb=cell(x,m),cell(y,m)
                if ca!=cb:
                    winner=a if ((ca>cb)==(m['direction']=='maximize')) else b
                    relation='A_BEFORE_B' if winner==a else 'B_BEFORE_A';first=m['name'];break
            s=saved[a,b];assert (s['winner'],s['relation'],s['decisive_metric'])==(winner,relation,first)
            unknown_count+=relation=='INCOMPARABLE'
            if winner:precedes.append((winner,b if winner==a else a))
        valid=[]
        for p in permutations(ids):
            positions={cid:i+1 for i,cid in enumerate(p)}
            if all(positions[a]<positions[b] for a,b in precedes):valid.append(positions)
        assert valid;permutation_count+=len(valid)
        for cid in ids:
            positions=[v[cid] for v in valid]
            assert (rows[cid]['rank_min'],rows[cid]['rank_max'])==(min(positions),max(positions))
            assert rows[cid]['pareto_layer']==depth
    # Different independent path for 60-day simple cumulative excess and closed PnL.
    bh=pd.read_csv(ROOT/'experiments/S011/20260930_S011_EX16/artifacts/benchmark_account_daily.csv.gz',float_precision='round_trip').equity.to_numpy()
    q=[];con=[]
    for cid,r in rows.items():
        folder=ROOT/r['standard_evidence'];account=pd.read_csv(folder/'account_daily.csv.gz',float_precision='round_trip')
        equity=np.r_[1e6,account.equity.to_numpy()];benchmark=np.r_[1e6,bh]
        excess=equity[60:]/equity[:-60]-benchmark[60:]/benchmark[:-60]
        assert np.isclose(np.quantile(excess,.1),r['rolling60_excess_q10'],atol=1e-12,rtol=0)
        q.append(cid)
        fills=pd.read_csv(folder/'fills.csv.gz',float_precision='round_trip');trades=pd.read_csv(folder/'trades.csv.gz')
        profits=[]
        for cycle in trades.loc[trades.status.eq('CLOSED'),'cycle_id']:
            z=fills[fills.cycle_id.eq(cycle)]
            profits.append(float(sum((v.quantity*v.price*(1 if v.side=='SELL' else -1)-v.fees) for v in z.itertuples())))
        wins=sorted((v for v in profits if v>0),reverse=True);n=(len(wins)+9)//10
        assert np.isclose(sum(wins[:n])/sum(wins),r['top10pct_positive_pnl_share'],atol=1e-12,rtol=0)
        con.append(cid)
    for file in ('family_statistics.json','legacy_diagnostics.parquet'):
        old='iteration_02' if file=='family_statistics.json' else 'iteration_03'
        filename='diagnostics.parquet' if file.startswith('legacy') else file
        assert hashed(package/file)==hashed(ROOT/f'research/S011/stage4/{old}/{filename}')
    pd.testing.assert_frame_equal(pd.read_parquet(package/'bootstrap.parquet'),pd.read_parquet(ROOT/'research/S011/stage4/iteration_02/bootstrap.parquet'))
    assert set(pd.read_parquet(package/'diagnostics.parquet').domain)=={'PARAMETER','TIME','CONCENTRATION','EXECUTION','STATISTICAL'}
    front=frame[frame.pareto_layer.eq(1)].sort_values('recommendation_rank').config_id.tolist()
    assert front==['S011-CFG-000618','S011-CFG-000624','S011-CFG-000621','S011-CFG-000628']
    design=pd.read_parquet(ROOT/'research/S011/stage4/perturbation_01/design_positions.parquet')
    for cid in front:
        x=design[design.center_config_id.eq(cid)&design.kind.eq('JOINT_HOLD2')&design.scenario.eq('standard')]
        assert len(x)==16
        loss=max(0.,rows[cid]['cagr']-np.quantile(x.cagr,.1))
        risk=max(0.,np.quantile(-x.drawdown,.9)-rows[cid]['drawdown_magnitude'])
        assert np.isclose(loss,rows[cid]['parameter_cagr_loss'],atol=1e-12,rtol=0)
        assert np.isclose(risk,rows[cid]['parameter_drawdown_increase'],atol=1e-12,rtol=0)
    d=read(package/'decision.json');assert d['status']=='PENDING_USER_DECISION' and not d['stage_five_started']
    return {'status':'PASS','configs':len(rows),'layer_sizes':list(map(len,layers)),
        'independent_pair_checks':len(saved),'incomparable_pairs':unknown_count,'valid_linear_extensions_checked':permutation_count,
        'independent_rolling_configs':len(q),'independent_concentration_configs':len(con),
        'legacy_statistics_preserved':True,'five_domains_present':True,'parameter_quantile_configs':4,
        'first_layer_order':front,'new_backtests':0}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True,type=Path);args=parser.parse_args()
    print(json.dumps(verify(args.package.resolve()),ensure_ascii=False,indent=2))
