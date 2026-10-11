"""S013 fixed tail-recovery component experiment; no financial evaluations."""
# ruff: noqa: E402
from datetime import date
from dataclasses import fields
from hashlib import sha256
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-next-research'
sys.path.insert(0,str(ROOT/'research/S013/experiments/EX058_20261011/src'))
import common
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from opportunity_statistics import analyze, METHOD, CONTROLS, COMPONENTS, HORIZONS
from late_recovery_component import build_features


def save(name,value):
    common.write(WORK/name,value)


def put(ctx,exp,name,filename):
    f=WORK/filename
    ref=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,f.read_bytes(),
        'text/x-python' if f.suffix=='.py' else 'text/csv' if f.suffix=='.csv' else 'application/json',f.suffix[1:]))
    ref.resolve(ROOT)
    return ref.to_dict()


def declare():
    assert not (WORK/'experiment.json').exists()
    assert common.read(WORK/'late_recovery_focused.json')['status']=='PASS'
    assert common.read(WORK/'statistics_checks.json')['status']=='PASS'
    ctx=common.context(1)
    exp=create_experiment(ctx,ExperimentRequest('尾盘收复是否提供独立盈利机会',
        '控制日线方向、位置、量能、波动和原确认后，最后60分钟及早段成交价位收复能否带来下一开盘之后的增量收益？',date(2026,10,11)))
    plan={'experiment':exp.to_dict(),'role':'RSCH','stage':2,
        'authorization':'我的要求已经说很清楚了，请给你自己定个目标，然后开始研究吧；用户允许自主设计验证并回到阶段二',
        'objective':'原四门中心达标，抗扰动更强；提高32点联合及逐项达标率、提高净CAGR Q10及降低全区间DD Q90。最好标准扰动仍达标；不把32/32新增为硬门。',
        'boundaries':'仅S013固定510500.SH数据至2026-09-30和原warmup；不外部取数、不封存验证、不跨族、不平台DEV、不冻结/PTE/生产/推送/合并',
        'branch':'codex/s013-mechanism-robustness already authorized; reuse',
        'hypothesis':'尾盘回升及收复早段成交量集中close代理价位，提供全天BODY、日量确认和无序能量之外的新盈利信息；是待证假说',
        'fixed_components':{'late_recovery':'log(C8/C6), last two30m bars; no time-window optimization',
            'early_volume_reclaim':'sum(Vj*sign(C8-Cj),j1..6)/sum(Vj,j1..6); proxy close levels, not VWAP or order flow'},
        'controls':list(CONTROLS),'additional_control_definition':{
            'daily_close_location':'(2Close-High-Low)/(High-Low), trusted daily OHLC',
            'turnover20':'Amount/rolling20mean(Amount)', 'volume_ratio20':'Volume/rolling20mean(Volume)'},
        'labels':{label:'T signal, entry Open[T+1], exit Open[T+1+h]; downside uses Low[T+1:T+h], max(0,1-minLow/entryOpen)' for label in HORIZONS},
        'primary':'return3/5 after next open, paired 1/3/5-day risk; return1 is declared auxiliary to detect only short-lived effect; never treat next open gap as tradable return',
        'signal_grid':['2020-01-02','2026-09-29',1635], 'account_acceptance_grid':['2020-01-02','2026-09-30',1636],
        'price_basis':'Original HFQ_RESEARCH/2019-12-31 anchor0.2803; no cash dividend overlay; public conversion exact-checked',
        'availability':'all eight T30m bars complete, original dailyT17 policy; no independently verified historical publication/revision times',
        'warmup':'New two components available each full day; old energy20 controls have first19 missing as published, not filled',
        'opportunity':'C8880 entry_eligible original state-dependent ex-ante subset for auxiliary within-scope tests; main test is full pool',
        'statistics':METHOD,
        'stop':'No stable incremental post-open return evidence: stop these fixed components. No inverted direction/time-window/threshold search to rescue failed hypothesis. Positive local evidence is retained.',
        'next_policy':'Only sufficient incremental evidence permits new independent opportunity expression with public binary SRT and full account validation; no trade deletion inference',
        'limitations':'Seen development pool, annual chronological prediction not sealed validation; overlaps and group ties disclosed; labels not fees-inclusive or executable account profit',
        'source_hashes':{n:sha256((WORK/n).read_bytes()).hexdigest() for n in
            ('late_recovery_component.py','late_recovery_focused.py','opportunity_statistics.py','statistics_checks.py','run_opportunity_study.py')}}
    save('plan.json',plan)
    refs={}
    for n in ('plan.json','hypothesis_review.json','late_recovery_method.json','late_recovery_focused.json','statistics_checks.json'):
        refs[n]=put(ctx,exp,n.split('.')[0].replace('_','-'),n)
    for n in plan['source_hashes']:
        refs[n]=put(ctx,exp,n.split('.')[0].replace('_','-'),n)
        (exp.resolve(ROOT)/'src'/n).write_bytes((WORK/n).read_bytes())
    common.write(exp.resolve(ROOT)/'protocols/plan.json',plan)
    common.write(exp.resolve(ROOT)/'protocols/method_references.json',refs)
    save('experiment.json',exp.to_dict())
    print({'declared':exp.experiment_id,'components':list(COMPONENTS),'controls':len(CONTROLS),'new_accounts':0},flush=True)


def numerical(frame):
    rename={'Date':'dt','Open':'open','High':'high','Low':'low','Close':'close','Volume':'vol','Amount':'amount'}
    converted=frame.rename(columns=rename).loc[:,list(rename.values())].copy()
    converted.dt=pd.to_datetime(converted.dt)
    converted.attrs={}
    return converted


def study():
    exp=ExperimentRef.from_dict(common.read(WORK/'experiment.json'))
    path=exp.resolve(ROOT)
    plan=common.read(WORK/'plan.json')
    for n,digest in plan['source_hashes'].items():
        assert sha256((WORK/n).read_bytes()).hexdigest()==digest
    assert not (WORK/'statistics.json').exists()
    ctx=common.context(1)
    bound,result=common.cache_read(common.CACHE/'N0.pkl.gz')
    native_ref=EvidenceRef.from_dict(common.read(common.RUNS/'account_references.json')['N0'])
    assert serialize_evaluation_evidence(bound,result)==common.read(native_ref.resolve(ROOT))
    ed=bound.execution_data
    data,identities={},{}
    for name in ('adjusted_daily','execution_daily','execution_30m','trading_calendar'):
        fetched=ctx.data.fetch(ed.requests[name],prepared=ed.prepared)
        assert fetched.ready
        data[name]=fetched.dataframe.copy()
        identities[name]={'content_sha256':fetched.identity.content_sha256,'request':str(ed.requests[name])}
    daily_binding=bound.input_bindings['full']
    fetched=ctx.data.fetch(daily_binding.plan.requests['daily'],prepared=daily_binding.prepared)
    assert fetched.ready
    daily_input=fetched.dataframe.copy()
    identities['srt_daily']={'content_sha256':fetched.identity.content_sha256,'request':str(daily_binding.plan.requests['daily'])}
    adjusted,raw,intra_raw=(numerical(data[k]) for k in ('adjusted_daily','execution_daily','execution_30m'))
    intra=ed.pricing.apply(intra_raw,raw_daily=raw,adjusted_daily=adjusted)
    daily=ed.pricing.apply(raw,raw_daily=raw,adjusted_daily=adjusted)
    for left,right in ((daily,ed.execution_daily),(intra,ed.execution_intraday)):
        a,b=left.copy().reset_index(drop=True),right.copy().reset_index(drop=True)
        a.attrs,b.attrs={},{}
        pd.testing.assert_frame_equal(a,b,check_exact=True)
    sessions=pd.DatetimeIndex(pd.to_datetime(ed.evaluation_sessions)).normalize().as_unit('ns')
    calendar=data['trading_calendar']
    assert calendar.IsOpen.isin([0,1]).all()
    opens=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),'Date'])).as_unit('ns')
    pd.testing.assert_index_equal(opens,sessions,check_names=False)
    bars=intra.rename(columns={'open':'Open','close':'Close','vol':'Volume'}).set_index('dt')[['Open','Close','Volume']]
    bars.index=bars.index.as_unit('ns')
    tail=build_features(bars)
    pd.testing.assert_index_equal(tail.index.as_unit('ns'),sessions,check_names=False)
    priorrefs=common.read(ROOT/'research/S013/experiments/EX060_20261011/protocols/result_references.json')
    base_ref=EvidenceRef.from_dict(priorrefs['features.csv'])
    base=pd.read_csv(base_ref.resolve(ROOT),float_precision='round_trip',index_col='signal_date')
    base.index=pd.to_datetime(base.index).as_unit('ns')
    assert len(base)==1635 and base.index[-1]==pd.Timestamp('2026-09-29')
    feature=base.join(tail[list(COMPONENTS)])
    daily_input.index=pd.DatetimeIndex(pd.to_datetime(daily_input.Date)).as_unit('ns')
    assert (daily_input.High>daily_input.Low).all()
    feature['daily_close_location']=((2*daily_input.Close-daily_input.High-daily_input.Low)/(daily_input.High-daily_input.Low)).reindex(feature.index)
    feature['turnover20']=(daily_input.Amount/daily_input.Amount.rolling(20).mean()).reindex(feature.index)
    feature['volume_ratio20']=(daily_input.Volume/daily_input.Volume.rolling(20).mean()).reindex(feature.index)
    feature=feature.loc[:,[*CONTROLS,*COMPONENTS]]
    assert feature[list(COMPONENTS)].notna().all().all()
    priced=daily.set_index('dt')
    priced.index=priced.index.as_unit('ns')
    labels=pd.DataFrame(index=feature.index)
    for label,h in HORIZONS.items():
        value=pd.Series(np.nan,index=priced.index)
        maturity=pd.Series(pd.NaT,index=priced.index,dtype='datetime64[ns]')
        for i in range(len(priced)-h-1):
            entry=priced.open.iloc[i+1]
            value.iloc[i]=priced.open.iloc[i+h+1]/entry-1 if label.startswith('return') else max(0.,1-priced.low.iloc[i+1:i+h+1].min()/entry)
            maturity.iloc[i]=priced.index[i+h+1]
        labels[label]=value.reindex(feature.index)
        labels['label_end_'+label]=maturity.reindex(feature.index)
    priorlabelref=EvidenceRef.from_dict(priorrefs['labels.csv'])
    oldlabels=pd.read_csv(priorlabelref.resolve(ROOT),index_col='signal_date',float_precision='round_trip')
    oldlabels.index=pd.to_datetime(oldlabels.index).as_unit('ns')
    for name in ('return_3','return_5','downside_3','downside_5'):
        np.testing.assert_array_equal(labels[name],oldlabels[name])
    opportunity_ref=EvidenceRef.from_dict(priorrefs['opportunity.csv'])
    opportunity=pd.read_csv(opportunity_ref.resolve(ROOT),index_col='signal_date').iloc[:,0]
    opportunity.index=pd.to_datetime(opportunity.index).as_unit('ns')
    assert opportunity.dtype==bool
    assert not common.SOURCE_CALLS
    save('input_checks.json',{'status':'PASS','identities':identities,'pricing':ed.pricing.to_dict(),
        'prepared':{f.name:str(getattr(ed.prepared,f.name)) for f in fields(ed.prepared)},
        'signal_n':len(feature),'execution_session_n':len(sessions),'new_components_no_missing':True,
        'old_labels_exact':True,'old_features_reference':base_ref.to_dict(),'old_native_account_reference':native_ref.to_dict(),
        'old_native_cache_serialized':'EXACT_EQUAL','reconverted_execution_frames':'EXACT_EQUAL','calendar':'EXACT_EQUAL',
        'source_calls':common.SOURCE_CALLS,'feature_missing':feature.isna().sum().to_dict(),
        'label_valid_n':{name:int(labels[name].notna().sum()) for name in HORIZONS}})
    feature.to_csv(WORK/'features.csv',index_label='signal_date',float_format='%.17g')
    labels.to_csv(WORK/'labels.csv',index_label='signal_date',float_format='%.17g')
    opportunity.to_csv(WORK/'opportunity.csv',index_label='signal_date')
    tail.to_csv(WORK/'tail_observations.csv',index_label='Date',float_format='%.17g')
    refs=common.read(path/'protocols/method_references.json')
    for name in ('input_checks.json','features.csv','labels.csv','opportunity.csv','tail_observations.csv'):
        refs[name]=put(ctx,exp,name.split('.')[0].replace('_','-'),name)
    common.write(path/'protocols/input_references.json',refs)
    print({'inputs_published':exp.experiment_id,'features':feature.shape,'opportunity_n':int(opportunity.sum())},flush=True)
    save('statistics.json',analyze(feature,labels,opportunity))
    refs['statistics.json']=put(ctx,exp,'fixed-tail-recovery-statistics','statistics.json')
    common.write(path/'protocols/result_references.json',refs)
    print({'study':'COMPLETE','experiment':exp.experiment_id,'new_accounts':0},flush=True)


if __name__=='__main__':
    {'declare':declare,'study':study}[sys.argv[1]]()
