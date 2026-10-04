"""Opportunity mechanisms; fixed comparisons, causal annual thresholds, no strategy search."""
import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10)
LAGS = (0, 1, 2)
MECHANISMS = {
 'dip1':'单日回调修复', 'dip3':'三日回调修复',
 'trend60_dip3':'中期上涨中的三日回调', 'trend20_dip1':'短趋势中的单日回调',
 'countertrend_dip3':'下行趋势中回调的竞争解释', 'deep_discount':'偏离均线后的修复',
 'shock_volume':'放量急跌后的流动性修复', 'shock_rejection':'急跌但收回日内跌幅',
 'dip_turn':'三日弱势后的首次转强', 'breakout20':'二十日新高延续',
 'breakout_volume':'放量突破延续', 'compression_breakout':'低波动后的五日突破',
 'trend_acceleration':'上涨加速延续', 'sge_cheap':'ETF相对境内黄金便宜后的修复',
 'sge_catchup':'境内黄金上涨时ETF落后补涨', 'flow_absorption':'份额扩张伴随回调',
 'fx_dip':'人民币贬值背景下ETF回调', 'yield_dip':'实际利率下降背景下ETF回调',
 'basis_dip':'黄金期货升水扩大背景下ETF回调',
}

def features(raw, inherited):
    p=raw.assign(Date=pd.to_datetime(raw.Date)).set_index('Date').sort_index()
    f=inherited.copy().reindex(p.index)
    f['r1']=p.Close.pct_change(fill_method=None)
    f['r3']=p.Close.pct_change(3, fill_method=None)
    f['discount']=p.Close/p.Close.rolling(20).mean()-1
    f['z1']=f.r1/f.volatility_20.shift(1)
    f['volume_shock']=p.Volume/p.Volume.rolling(20).mean().shift(1)
    f['break20']=p.Close/p.High.shift(1).rolling(20).max()-1
    f['break5']=p.Close/p.High.shift(1).rolling(5).max()-1
    f['prior_r3']=f.r3.shift(1)
    f['prior_vol']=f.volatility_20.shift(1)
    return f

def signals(f):
    """Fit only on prior calendar years; all data remains the disclosed development pool."""
    out=pd.DataFrame(np.nan,index=f.index,columns=list(MECHANISMS))
    cells=pd.Series(np.nan,index=f.index)
    thresholds=[]
    for year in sorted(set(f.index.year)):
        train=f.loc[f.index.year<year]
        if len(train)<252: continue
        x=f.loc[f.index.year==year]
        q=lambda name,p: float(train[name].quantile(p))
        cuts={k:q(k,p) for k,p in [('r1',.25),('r3',.25),('discount',.2),('prior_r3',.25),
              ('prior_vol',.4),('etf_sge_deviation_20',.25),('shares_change_5',.75),
              ('fx_change_5',.75),('real_yield_change_5',.25),('basis_change_5',.75)]}
        volcuts=[q('volatility_20',1/3),q('volatility_20',2/3)]
        thresholds.append({'year':int(year),'train_n':len(train),'train_end':str(train.index[-1].date()),
                           'cuts':cuts,'r3_q75':q('r3',.75),'vol_terciles':volcuts})
        d1=x.r1<=cuts['r1']; d3=x.r3<=cuts['r3']
        cheap=x.etf_sge_deviation_20<=cuts['etf_sge_deviation_20']
        specs={
          'dip1':(d1,['r1']), 'dip3':(d3,['r3']),
          'trend60_dip3':(d3&(x.momentum_60>0),['r3','momentum_60']),
          'trend20_dip1':(d1&(x.momentum_20>0),['r1','momentum_20']),
          'countertrend_dip3':(d3&(x.momentum_60<=0),['r3','momentum_60']),
          'deep_discount':(x.discount<=cuts['discount'],['discount']),
          'shock_volume':((x.z1<=-1)&(x.volume_shock>=1.25),['z1','volume_shock']),
          'shock_rejection':((x.z1<=-1)&(x.close_location>=.5),['z1','close_location']),
          'dip_turn':((x.prior_r3<=cuts['prior_r3'])&(x.r1>0),['prior_r3','r1']),
          'breakout20':(x.break20>0,['break20']),
          'breakout_volume':((x.break20>0)&(x.volume_shock>=1.25),['break20','volume_shock']),
          'compression_breakout':((x.break5>0)&(x.prior_vol<=cuts['prior_vol']),['break5','prior_vol']),
          'trend_acceleration':((x.momentum_20>0)&(x.r3>=q('r3',.75)),['momentum_20','r3']),
          'sge_cheap':(cheap,['etf_sge_deviation_20']),
          'sge_catchup':(cheap&(x.sge_momentum_5>0),['etf_sge_deviation_20','sge_momentum_5']),
          'flow_absorption':(d3&(x.shares_change_5>=cuts['shares_change_5']),['r3','shares_change_5']),
          'fx_dip':(d3&(x.fx_change_5>=cuts['fx_change_5']),['r3','fx_change_5']),
          'yield_dip':(d3&(x.real_yield_change_5<=cuts['real_yield_change_5']),['r3','real_yield_change_5']),
          'basis_dip':(d3&(x.basis_change_5>=cuts['basis_change_5']),['r3','basis_change_5']),
        }
        for name,(mask,cols) in specs.items():
            valid=x[cols].notna().all(axis=1)
            out.loc[x.index[valid],name]=mask.loc[valid].astype(float)
        valid=x[['momentum_20','volatility_20']].notna().all(axis=1)
        cell=(year-2020)*6+(x.momentum_20>0).astype(int)*3+np.digitize(x.volatility_20,volcuts)
        cells.loc[x.index[valid]]=cell.loc[valid]
    return out,cells,thresholds

def labels(raw,h):
    p=raw.assign(Date=pd.to_datetime(raw.Date)).set_index('Date').sort_index()
    entry=p.Open.shift(-1)
    return pd.DataFrame({'gross':p.Open.shift(-h-1)/entry-1,
        'mae':1-pd.concat([p.Low.shift(-j) for j in range(1,h+1)],axis=1).min(axis=1,skipna=False)/entry,
        'mfe':pd.concat([p.High.shift(-j) for j in range(1,h+1)],axis=1).max(axis=1,skipna=False)/entry})

def dedup(positions,h):
    keep=[]; last=-100000
    for p in positions:
        if p>=last+h+1: keep.append(p); last=p
    return np.asarray(keep,dtype=int)

def net(y,cost=.001): return (1+y)*(1-cost)/(1+cost)-1

def effect(y,s,c):
    counts=np.bincount(c,minlength=64)
    means=np.bincount(c,weights=y,minlength=64)/np.maximum(counts,1)
    return float(np.mean(y[s]-means[c[s]])) if s.any() else np.nan

def diagnostics(frame,seed):
    y=frame.gross.to_numpy(); s=frame.signal.to_numpy().astype(bool); c=frame.cell.to_numpy().astype(int)
    observed=effect(y,s,c); rng=np.random.default_rng(seed); n=len(y)
    blocks=60; reps=499; boots=[]; null=[]
    yeargroups=[np.flatnonzero(frame.index.year==year) for year in sorted(set(frame.index.year))]
    for _ in range(reps):
        ix=((rng.integers(0,n,int(np.ceil(n/blocks)))[:,None]+np.arange(blocks))%n).ravel()[:n]
        if s[ix].sum()>=5: boots.append(effect(y[ix],s[ix],c[ix]))
        sy=s.copy()
        for g in yeargroups:
            if len(g)>40: sy[g]=np.roll(s[g],rng.integers(20,len(g)-19))
        null.append(effect(y,sy,c))
    return {'block60_increment_ci':np.quantile(boots,[.025,.975]).tolist() if boots else None,
            'shift_p':float((1+np.sum(np.asarray(null)>=observed))/(reps+1))}

def summarize(frame,h,positions):
    chosen=frame.loc[frame.signal==1]
    if len(chosen)==0: return {'n':0,'eligible_n':len(frame)}
    y=frame.gross.to_numpy(); s=(frame.signal.to_numpy()==1); c=frame.cell.to_numpy().astype(int)
    inc=effect(y,s,c); chosenpos=positions.loc[chosen.index].to_numpy()
    selectedpos=dedup(chosenpos,h); non=chosen.loc[positions.loc[chosen.index].isin(selectedpos)]
    return {'n':len(chosen),'eligible_n':len(frame),'gross_mean':float(chosen.gross.mean()),
       'net20':float(net(chosen.gross).mean()),'net40':float(net(chosen.gross,.002).mean()),
       'unconditional_gross':float(frame.gross.mean()),'unconditional_increment':float(chosen.gross.mean()-frame.gross.mean()),
       'matched_increment':inc, 'matched_gross':float(chosen.gross.mean()-inc),
       'surplus_after20':float(net(chosen.gross).mean()-chosen.gross.mean()+inc),
       'net_win_rate':float((net(chosen.gross)>0).mean()),'mae_mean':float(chosen.mae.mean()),
       'mfe_mean':float(chosen.mfe.mean()),'nonoverlap_n':len(non),
       'nonoverlap_per60':float(len(non)*60/len(frame)), 'nonoverlap_net20':float(net(non.gross).mean()),
       'first':str(frame.index[0].date()),'last':str(frame.index[-1].date())}

def analyze(raw,inherited):
    f=features(raw,inherited); masks,cells,thresholds=signals(f)
    positions=pd.Series(np.arange(len(f)),index=f.index)
    metrics=[]; years=[]
    for name in MECHANISMS:
        for h in HORIZONS:
            for lag in LAGS:
                frame=pd.concat([labels(raw,h),masks[name].shift(lag).rename('signal'),cells.rename('cell')],axis=1).dropna()
                base={'mechanism':name,'horizon':h,'lag':lag}
                summary=summarize(frame,h,positions)
                summary.update(base)
                if summary['n']>=10 and lag==0: summary.update(diagnostics(frame,12006+h))
                for year in sorted(set(frame.index.year)):
                    group=frame.loc[frame.index.year==year]
                    row=summarize(group,h,positions); row.update(base,year=int(year)); years.append(row)
                if summary['n']:
                    leave=[]
                    for year in sorted(set(frame.index.year)):
                        group=frame.loc[frame.index.year!=year]
                        if (group.signal==1).sum(): leave.append(summarize(group,h,positions)['matched_increment'])
                    summary['leave_year_increments']=leave
                    metrics.append(summary)
    primary=[r for r in metrics if 'shift_p' in r]
    order=np.argsort([r['shift_p'] for r in primary]); last=1.
    for rank in range(len(order)-1,-1,-1):
        r=primary[order[rank]]; last=min(last,r['shift_p']*len(order)/(rank+1)); r['shift_q']=last
    assert len(metrics)>0 and len(primary)>0
    return metrics,years,thresholds,pd.concat([masks,cells.rename('cell')],axis=1)
