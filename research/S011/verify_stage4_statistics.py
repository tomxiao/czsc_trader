"""Recompute EX26 diagnostics from sealed ledgers without reevaluating strategies."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/'experiments/S011/20260930_S011_EX26/artifacts'


def main():
    catalog=pd.read_csv(ROOT/'parameter_catalog.csv')
    directions=pd.read_csv(ROOT/'neighborhood_directions.csv').fillna('')
    summary=pd.read_csv(ROOT/'neighborhood_summary.csv')
    steps={'tail_weight':.025,'spx_weight':.025,'entry':.005,'exit':.025,'max_days':1,'lookback':10,'premium':.0005}
    fields=list(steps); qualified=catalog.loc[catalog.qualified]
    for center in qualified.itertuples():
        delta=(catalog[fields]-pd.Series({f:getattr(center,f) for f in fields}))/pd.Series(steps)
        changed=delta.abs().gt(1e-9); near=delta.abs().le(1+1e-9).all(axis=1)&changed.any(axis=1)
        sides=[]
        for field in fields:
            for sign in ('-','+'):
                mask=near&changed.sum(axis=1).eq(1)&(delta[field].lt(0) if sign=='-' else delta[field].gt(0))
                neighbors=catalog.loc[mask]
                row=directions.loc[directions.center.eq(center.reference)&directions.parameter.eq(field)&directions.side.eq(sign)].iloc[0]
                assert row.tested==len(neighbors) and row.qualified==neighbors.qualified.sum()
                assert row.neighbor_references=='|'.join(neighbors.reference)
                sides.append(bool(len(neighbors)))
        row=summary.loc[summary.reference.eq(center.reference)].iloc[0]
        assert row.covered_sides==sum(sides)
        assert row.two_sided_dimensions==sum(sides[i] and sides[i+1] for i in range(0,14,2))
        assert row.joint_tested==near.sum() and row.joint_qualified==catalog.loc[near,'qualified'].sum()
    benchmark=pd.read_csv(ROOT/'accounts/EX16BH/standard/account_daily.csv.gz')
    br=benchmark.equity.div(benchmark.equity.shift(1,fill_value=1e6))-1
    dates=pd.to_datetime(benchmark.date)
    periods=pd.read_csv(ROOT/'period_returns.csv'); concentrations=pd.read_csv(ROOT/'concentration.csv')
    rolling=pd.read_csv(ROOT/'rolling60_returns.csv'); bootstrap=pd.read_csv(ROOT/'block_bootstrap.csv')
    rng=np.random.default_rng(2026093026); indices={}
    for length in (10,20):
        starts=rng.integers(0,403,size=(2000,int(np.ceil(403/length))))
        indices[length]=np.concatenate([(starts[:,i,None]+np.arange(length))%403 for i in range(starts.shape[1])],axis=1)[:,:403]
    for ref in qualified.reference:
        folder=ROOT/f'accounts/{ref}/standard'
        account=pd.read_csv(folder/'account_daily.csv.gz'); fills=pd.read_csv(folder/'fills.csv.gz'); trades=pd.read_csv(folder/'trades.csv.gz')
        returns=account.equity.div(account.equity.shift(1,fill_value=1e6))-1
        assert account.date.equals(benchmark.date)
        for row in periods.loc[periods.reference.eq(ref)].itertuples():
            labels=dates.dt.year.astype(str) if row.unit=='year' else dates.dt.to_period('Q').astype(str)
            mask=labels.eq(row.period)
            assert mask.sum()==row.sessions
            assert np.allclose([(1+returns[mask]).prod()-1,(1+br[mask]).prod()-1],[row.strategy_return,row.buyhold_return],rtol=0,atol=1e-12)
        sr=(1+returns).rolling(60).apply(np.prod,raw=True).dropna()-1
        bh=(1+br).rolling(60).apply(np.prod,raw=True).dropna()-1
        obs=rolling.loc[rolling.reference.eq(ref)]
        assert np.allclose(obs.strategy_return,sr,rtol=0,atol=1e-12)
        assert np.allclose(obs.buyhold_return,bh,rtol=0,atol=1e-12)
        net=fills.quantity*fills.price*np.where(fills.side.eq('BUY'),-1,1)-fills.fees
        pnl=net.groupby(fills.cycle_id).sum().reindex(trades.loc[trades.status.eq('CLOSED'),'cycle_id'])
        positive=pnl[pnl>0].sort_values(ascending=False); c=concentrations.loc[concentrations.reference.eq(ref)].iloc[0]
        assert c.closed_trades==len(pnl) and c.wins==(pnl>0).sum()
        assert np.allclose([c.top3_positive_pnl_share,c.rolling60_positive_excess_share,c.worst_rolling60_excess],[positive.head(3).sum()/positive.sum(),(sr>bh).mean(),(sr-bh).min()],rtol=0,atol=1e-12)
        for k in (1,3,5):
            altered=returns.copy(); altered.loc[returns.nlargest(k).index]=0
            assert abs(c[f'best_{k}_days_zero_cagr']-((1+altered).prod()**(252/403)-1))<1e-12
        excess=(np.log1p(returns)-np.log1p(br)).to_numpy()
        for row in bootstrap.loc[bootstrap.reference.eq(ref)].itertuples():
            values=excess[indices[row.block]].mean(axis=1)*252
            assert row.resamples==2000
            assert np.allclose([row.annual_log_excess_p025,row.annual_log_excess_median,row.annual_log_excess_p975,row.positive_resample_share],[*np.quantile(values,[.025,.5,.975]),(values>0).mean()],rtol=0,atol=1e-12)
    report={'status':'PASS','qualified_configurations':26,'neighborhood_directions':len(directions),'periods':len(periods),'rolling_windows':len(rolling),'bootstrap_cases':len(bootstrap),'development_only':True,'selection_bias_corrected':False}
    output=REPO/'.tmp/s011-stage4-statistics-verification'; output.mkdir(exist_ok=True,parents=True)
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
