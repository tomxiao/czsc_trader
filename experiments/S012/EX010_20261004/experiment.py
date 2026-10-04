from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from dataflows import DataRequest,DataStatus
from research_experiment import (ResearchExperiment,ExperimentDefinition,ExperimentMode,ExperimentDataScope,
    ExperimentCapabilities,ExperimentProtocol,ExperimentStage,ExperimentResult,ExperimentOutcome,
    ExperimentPrecheckResult,ExperimentPreflightCheck,ExperimentPreflightStatus,ExperimentDependency)
from . import fx as fx_analysis
from . import gold as gold_analysis

def corrected_fx(inherited,fx):
    native=fx.assign(Date=pd.to_datetime(fx.Date)).set_index('Date').sort_index()
    features=pd.DataFrame({'fx_level':native.BidClose,'AvailableDate':native.AvailableDate})
    for h in (5,20):features[f'fx_change_{h}']=native.BidClose.pct_change(h,fill_method=None)
    aligned=gold_analysis.source_align(features,inherited.index)
    out=inherited.copy()
    for col in ('fx_level','fx_change_5','fx_change_20'):out[col]=aligned[col]
    return out

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,'EX010_20261004','S012',ExperimentMode.FORMAL,
            '保守源可用时间下，汇率回调和境外黄金错位是否仍构成收益机会？',
            '境外黄金强信号可能来自时间提前；汇率回调只有在显式可得边界后仍有增量才可保留。',
            ('更正后收益优势消失。','日历和限价约束导致机会不足。','实际历史发布时间仍不可核验。'),
            date(2026,9,30),12010,('fx.fxcm_daily','fx.usdcnh_daily','etf.unadjusted_daily'),
            ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ('EX008发生时间语义反证，EX006-007涉及同源FXCM，必须复核。',),
                ('DFLS发布AvailableDate=源日后2自然日08:00中国时间；绑定实际时间字段而非日期文字。',),
                ('保留原实验，按相同条件重算并形成机会面板，失败时间口径作为明确反证。',),
                ('14汇率条件168路径、8黄金条件96路径、252敏感性单元、36限价单元。',),
                ('只改时间口径，不根据重算结果优化阈值。','保守政策不证明供应商逐日历史发布时刻，必须披露。'),
                predecessor_experiment_ids=('EX004_20261004','EX007_20261004','EX008_20261004')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','tsfresh')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=True))

    def synthetic_precheck(self):
        d=pd.bdate_range('2020-01-01',periods=850);t=np.arange(len(d));c=100+np.sin(t/3)+t/100
        raw=pd.DataFrame({'Date':d.strftime('%Y-%m-%d'),'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':100+t%17})
        inherited=pd.DataFrame({k:np.sin(t/19)/100 for k in ('volatility_20','momentum_20','momentum_60',
            'etf_sge_deviation_20','shares_change_5','fx_change_5','real_yield_change_5','basis_change_5','sge_momentum_5','close_location')},index=d)
        inherited['volatility_20']=.01;inherited['fx_level']=7.;inherited['close_location']=.5
        xau=pd.DataFrame({'Date':d,'BidClose':1800+t,'AvailableDate':d+pd.Timedelta(days=2,hours=8)})
        fx=pd.DataFrame({'Date':d,'BidClose':7+np.sin(t/17)/10,'AvailableDate':d+pd.Timedelta(days=2,hours=8)})
        g,_,features,_=gold_analysis.build(raw,inherited,xau,fx)
        g2,_,_,_=gold_analysis.build(raw.iloc[:650],inherited.iloc[:650],xau.iloc[:650],fx.iloc[:650]);pd.testing.assert_frame_equal(g.iloc[:650],g2)
        assert pd.isna(features.source_date.iloc[1]) and features.source_date.iloc[2]==d[0]
        repaired=corrected_fx(inherited,fx);assert pd.isna(repaired.fx_level.iloc[1])
        f,_,_=fx_analysis.masks(raw,repaired);assert f.notna().any().all()
        assert (features.dropna(subset=['AvailableDate']).AvailableDate<=features.dropna(subset=['AvailableDate']).decision_time).all()
        return ExperimentPrecheckResult((ExperimentPreflightCheck('AVAILABLE_TIMESTAMP',ExperimentPreflightStatus.PASS,
            '源日后2自然日08:00边界、前缀不变、FX重建、日期隔离合成验证。'),),ExperimentResult(ExperimentOutcome.PASS,{'synthetic':True},{}))

    def execute(self,context):
        artifacts=[];data={};audit={}
        def save(name,value,kind='opportunity_corrected'):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')
            artifacts.append(context.workspace.register_artifact(name,kind))
        for name,dataset,symbol in [('xau','fx.fxcm_daily','XAUUSD.FXCM'),('fx','fx.usdcnh_daily',None)]:
            result=context.data.fetch(DataRequest(dataset,symbol,'2020-06-05','2026-09-30',None))
            assert result.status is DataStatus.READY,(name,result.status,result.error)
            data[name]=result.dataframe
            assert 'AvailableDate' in data[name]
            audit[name]={'rows':len(data[name]),'content_sha256':result.identity.content_sha256,'metadata':dict(result.identity.metadata)}
            data[name].to_parquet(context.workspace.path(f'data/{name}.parquet'),index=False)
            artifacts.append(context.workspace.register_artifact(f'data/{name}.parquet','source_data'))
        save('data_audit.json',audit)
        prior=context.predecessors['EX004_20261004'];expected={a.path:a.sha256 for a in prior.artifacts}
        root=Path(__file__).resolve().parents[1]/'EX004_20261004/artifacts/rex'
        def read(name):
            p=root/name;assert sha256(p.read_bytes()).hexdigest()==expected[name];return pd.read_parquet(p)
        raw,inherited=read('data/raw.parquet'),read('features.parquet')
        oldfx=read('data/fx.parquet').assign(Date=lambda x:pd.to_datetime(x.Date))
        newfx=data['fx'].copy();newfx.Date=pd.to_datetime(newfx.Date)
        price_columns=[c for c in oldfx.columns if c!='TickQuantity']
        pd.testing.assert_frame_equal(oldfx[price_columns].reset_index(drop=True),newfx[price_columns].reset_index(drop=True),check_dtype=False,check_exact=True)
        changed=oldfx.TickQuantity.to_numpy()!=newfx.TickQuantity.to_numpy()
        save('snapshot_revision.json',{'changed_tick_count_rows':int(changed.sum()),'records':[{'date':str(oldfx.Date.iloc[i].date()),'old':int(oldfx.TickQuantity.iloc[i]),'new':int(newfx.TickQuantity.iloc[i])} for i in np.flatnonzero(changed)],'price_columns_exact':True,'selection_history':'EX009因计数修订触发全字段断言停止，无成功回执；本轮计数不进入特征。'})
        updated=corrected_fx(inherited,data['fx']);values,signals=fx_analysis.analyze(raw,updated)
        for name,value in values.items():save('fx/'+name,value)
        signals.to_parquet(context.workspace.path('fx/signals.parquet'));artifacts.append(context.workspace.register_artifact('fx/signals.parquet','causal_signals'))
        gvalues,gfeatures,gsignals=gold_analysis.analyze(raw,updated,data['xau'],data['fx'])
        for name,value in gvalues.items():save('gold/'+name,value)
        gfeatures.to_parquet(context.workspace.path('gold/features.parquet'));artifacts.append(context.workspace.register_artifact('gold/features.parquet','causal_features'))
        gsignals.to_parquet(context.workspace.path('gold/signals.parquet'));artifacts.append(context.workspace.register_artifact('gold/signals.parquet','causal_signals'))
        repo=Path(__file__).resolve().parents[3]
        paths=('packages/dataflows/src/dataflows/contract.py','packages/dataflows/src/dataflows/tushare_strategy_data.py','packages/dataflows/src/dataflows/facade.py')
        save('platform_source_hashes.json',{p:sha256((repo/p).read_bytes()).hexdigest() for p in paths})
        return ExperimentResult(ExperimentOutcome.PASS,{'fx_paths':len(values['opportunities.json']),'gold_paths':len(gvalues['opportunities.json']),
            'sensitivity_cells':len(values['sensitivity.json']),'limit_cells':len(values['limit_events.json'])},
            {'scope':'完整开发池；保守可用时间为明确假设，历史逐日发布时间未知。旧FX价格值逐项一致，仅更新可用时间。'},tuple(artifacts))
