from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from uuid import UUID
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, create_experiment, ExperimentRequest, publish_evidence
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparedDataRef, PriceAdjustment, ProviderConfig, SourceRef)
from strategy_runtime.equity_definition import execution_spec_from_dict

ROOT=Path.cwd(); FAMILY=ROOT/'research/S018'; EXP=d.ExperimentRef('S018','EX048_20261104')
WORK=EXP.resolve(ROOT)


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8')


def features(mu,so):
    m=np.log(mu.Close).diff(); s=np.log(so.Close).diff()
    sigma=m.rolling(20).std().shift(2)
    beta=m.rolling(60).cov(s).shift(2)/s.rolling(60).var().shift(2)
    ran=(mu.High-mu.Low)/mu.Close.shift()
    return pd.DataFrame({'signal_date':mu.Date.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d'),
        'mu_drift':m.rolling(20).sum().shift(2)/(sigma*np.sqrt(20)),
        'range_state':np.log(ran.rolling(5).mean()/ran.rolling(20).mean()),
        'mu_intraday':np.log(mu.Close/mu.Open)/sigma, 'mu_gap':np.log(mu.Open/mu.Close.shift())/sigma,
        'mu_yesterday':m.shift()/sigma,
        'sector_drift':s.rolling(20).sum().shift(2)/(s.rolling(20).std().shift(2)*np.sqrt(20)),
        'common_today':beta*s/sigma,'common_yesterday':beta*s.shift()/sigma}).set_index('signal_date')


def worker(args):
    horizon,memory,feat,events,models=args
    dataset=events[(events.horizon==horizon)&(events.status=='CLOSED')].sort_values('signal_date').join(feat,on='signal_date')
    out=[]
    for t in feat.index[(feat.index>='2022-12-30')&(feat.index<'2026-10-30')]:
        train=dataset[dataset.exit_date<=t]
        if memory=='recent126':train=train.tail(126)
        if len(train)<126:continue
        assert train.signal_date.max()<t
        assert np.isfinite(train[list(feat.columns)].to_numpy()).all()
        y=train.net_return.to_numpy(float)
        for name,columns in models.items():
            if not columns:prediction=float(y.mean())
            else:
                model=make_pipeline(StandardScaler(),Ridge(alpha=10.))
                model.fit(train[columns].to_numpy(),y)
                prediction=float(model.predict(feat.loc[[t],columns].to_numpy())[0])
            out.append({'signal_date':t,'horizon':horizon,'memory':memory,'model':name,'prediction':prediction,
                'train_n':len(train),'latest_label_exit':train.exit_date.max()})
    return out


def describe(group):
    y=group.net_return.to_numpy(float)
    return {'n':len(y),'mean':float(y.mean()) if len(y) else None,
        'p05':float(np.quantile(y,.05)) if len(y) else None,'win_rate':float((y>0).mean()) if len(y) else None}


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    old=read(FAMILY/'experiments/EX025_20261104/others/results.json')['accounts']['C6300']
    ctx=create_research_context(RepositoryContext.discover(ROOT),d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={},equity_bindings={}),execution_spec=execution_spec_from_dict(old['definition']['execution_spec']))
    if not WORK.exists():
        assert create_experiment(ctx,ExperimentRequest('Sector incremental information','行业共同项在连续幅度模型中能否提供MU自身信息以外的机会预测？',date(2026,11,4)))==EXP
    assert not (WORK/'report_ref.json').exists()
    (WORK/'src/run.py').write_bytes(Path(__file__).read_bytes())
    models={'mean':[], 'mu_only':['mu_drift','range_state','mu_intraday','mu_gap','mu_yesterday'],
        'sector_only':['sector_drift','common_today','common_yesterday']}
    models['joint']=models['mu_only']+models['sector_only']
    protocol={'question':'EX045至47的粗分组与持有检验后，行业连续幅度信息是否仍有增量预测用途？',
        'phase':2,'round':15,'remaining_after':15,
        'hypothesis':'回落的共同强度及行业背景可能与个股变化共同决定近期修复价值，简单符号分组会遗漏强度。',
        'alternatives':['新增信息不改善均值预测或收益排序','收益排序仅限局部年份和短期限，不足以形成稳定入口'],
        'models':models,'memories':['expanding','recent126'],'horizons':[1,3,6],
        'ridge_alpha':10,'minimum_mature_events':126,'scaler':'fit training only','label':'EX039 formal CLOSED net returns, exit_date<=signal_date',
        'selection_history':'已见开发池；模型类型/alpha/126记忆承接EX040/42，行业特征源于EX044至47；不搜索参数。',
        'decision':'比较相同预测日期上的误差、正负预测分组及分年方向。只有行业信息体现可解释增量才进入正式账户，不把事件预测表注入策略，不增加研究硬门。',
        'workers':4,'threads_each':1,'versions':{name:version(name) for name in ('numpy','pandas','scikit-learn')}}
    save(WORK/'others/protocol.json',protocol)
    refs=[publish_evidence(ctx,d.MaterialEvidenceWrite(EXP,'protocol',(WORK/'others/protocol.json').read_bytes(),'application/json','json'))]
    r=read(FAMILY/'experiments/EX045_20261104/others/data_preparation.json')['reference']
    prepared=PreparedDataRef(UUID(r['space_id']),UUID(r['preparation_id']),r['manifest_sha256'])
    source=SourceRef('futu','s018-mu-soxx-hfq-research-20261104-v1')
    frames=[]; identities=[]
    for symbol,asset in [('MU',AssetClass.STOCK),('SOXX',AssetClass.ETF)]:
        request=EquityDataRequest(InstrumentId(MarketId.US,asset,symbol),source,
            EquityQuery(EquityProduct.BARS,date(2022,1,3),date(2026,10,30),BarFrequency.DAILY,PriceAdjustment.BACKWARD))
        result=ctx.data.fetch(request,prepared=prepared)
        assert result.ready,result.error
        frames.append(result.dataframe)
        identities.append({'symbol':symbol,'content_sha256':result.identity.content_sha256})
    mu,so=frames
    assert mu.Date.tolist()==so.Date.tolist()
    feat=features(mu,so)
    for end in range(251,len(mu),31):
        pd.testing.assert_series_equal(features(mu.iloc[:end+1],so.iloc[:end+1]).iloc[-1],feat.iloc[end])
    label_path=FAMILY/'experiments/EX039_20261104/others/analysis_events_enriched.json'
    events=pd.read_json(label_path)
    assert not events.duplicated(['horizon','signal_date']).any()
    save(WORK/'others/analysis_inputs.json',{'prepared':asdict(prepared),'identities':identities,
        'label_source':'../EX039_20261104/others/analysis_events_enriched.json','label_sha256':sha256(label_path.read_bytes()).hexdigest(),
        'feature_checks':f'{len(range(251,len(mu),31))} physical prefixes exactly equal full-frame historical rows'})
    with ProcessPoolExecutor(max_workers=4) as pool:
        chunks=list(pool.map(worker,[(h,m,feat,events,models) for h in (1,3,6) for m in ('expanding','recent126')]))
    forecasts=pd.DataFrame([row for chunk in chunks for row in chunk])
    assert (forecasts.latest_label_exit<=forecasts.signal_date).all()
    merged=forecasts.merge(events,on=['horizon','signal_date'],how='left',validate='many_to_one')
    metrics={}
    for (h,m,name),g in merged.groupby(['horizon','memory','model']):
        g=g[g.status=='CLOSED'].copy()
        baseline=merged[(merged.horizon==h)&(merged.memory==m)&(merged.model=='mean')][['signal_date','prediction']].rename(columns={'prediction':'baseline'})
        own=merged[(merged.horizon==h)&(merged.memory==m)&(merged.model=='mu_only')][['signal_date','prediction']].rename(columns={'prediction':'own'})
        g=g.merge(baseline,on='signal_date',validate='one_to_one').merge(own,on='signal_date',validate='one_to_one')
        error=float(((g.prediction-g.net_return)**2).mean())
        positive=g.prediction>0
        metrics[f'{h}:{m}:{name}']={'n':len(g),
            'mse_improvement_vs_mean':1-error/float(((g.baseline-g.net_return)**2).mean()),
            'mse_improvement_vs_mu':1-error/float(((g.own-g.net_return)**2).mean()),
            'positive':describe(g[positive]),'nonpositive':describe(g[~positive]),
            'years':{str(year):{'positive':describe(g[positive & g.signal_date.str.startswith(str(year))]),
                'nonpositive':describe(g[~positive & g.signal_date.str.startswith(str(year))])} for year in (2023,2024,2025,2026)}}
    forecasts.to_json(WORK/'others/analysis_forecasts.json',orient='records',force_ascii=False,indent=2,double_precision=15)
    save(WORK/'others/analysis_metrics.json',{'metrics':metrics,'new_accounts':0,'forecasts':len(forecasts),
        'limits':'因果日期顺序不恢复已见样本独立性；重叠事件不是可加总账户；模型不能直接通过原完整账户硬门。'})
    for path in (WORK/'others').glob('analysis_*.json'):
        refs.append(publish_evidence(ctx,d.MaterialEvidenceWrite(EXP,path.stem,path.read_bytes(),'application/json','json')))
    save(WORK/'others/evidence_refs.json',[r.to_dict() for r in refs])
    for key,m in metrics.items():
        print(key,round(m['mse_improvement_vs_mean'],4),round(m['mse_improvement_vs_mu'],4),m['positive'],m['nonpositive'],flush=True)


if __name__=='__main__':main()
