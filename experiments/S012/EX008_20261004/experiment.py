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
from .analysis import analyze,build,labels

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,'EX008_20261004','S012',ExperimentMode.FORMAL,
            '已授权Tushare/FXCM境外黄金信息能否补足收益机会，开盘后还有补涨空间吗？',
            '海外人民币黄金价格与前日ETF价格错位可能提供开盘后延续或修复；开盘消化信息构成竞争解释。',
            ('来源不提供该品种或历史不足。','开盘已消化信息，开盘后不再有净增量。','依赖时间错配或少数年份。'),
            date(2026,9,30),12008,('fx.fxcm_daily','etf.unadjusted_daily'),
            ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ('EX006-007仅发现低频汇率回调线索；新增同供应商境外金价进行竞争解释检验。',),
                ('已授权DFLS fx.fxcm_daily符号XAUUSD.FXCM；不增加供应商或依赖。',),
                ('核验数据可得性；如READY则按已声明8条件开展1/3/5/10日、0/1/2滞后研究。',),
                ('来源状态、覆盖、源日约束、净收益、匹配增量、年度、事件容量、平移q。',),
                ('开盘前08:45决策，ETF只用前日及此前数据，GMT数据必须严格早于入场日。',
                 '标签从当日开盘起，不将隔夜跳空收益算作可获取收益。','数据不可用形成明确不足结论，不以空统计冒充有效研究。'),
                predecessor_experiment_ids=('EX004_20261004','EX007_20261004')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','tsfresh')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=True))

    def synthetic_precheck(self):
        d=pd.bdate_range('2020-01-01',periods=850);t=np.arange(len(d));c=100+np.sin(t/3)+t/100
        raw=pd.DataFrame({'Date':d.strftime('%Y-%m-%d'),'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':100+t%17})
        inherited=pd.DataFrame({'momentum_20':np.sin(t/9)/100,'volatility_20':.01},index=d)
        xau=pd.DataFrame({'Date':d.strftime('%Y-%m-%d'),'BidClose':1800+t+np.sin(t/5)*10})
        fx=pd.DataFrame({'Date':d.strftime('%Y-%m-%d'),'BidClose':7+np.sin(t/7)/10})
        a,_,f,_=build(raw,inherited,xau,fx)
        b,_,_,_=build(raw.iloc[:650],inherited.iloc[:650],xau.iloc[:650],fx.iloc[:650])
        pd.testing.assert_frame_equal(a.iloc[:650],b)
        assert np.isclose(labels(raw,3).gross.iloc[0],c[3]/c[0]-1)
        assert f.r1.iloc[2]==c[1]/c[0]-1 and f.source_date.iloc[1]==d[0]
        return ExperimentPrecheckResult((ExperimentPreflightCheck('PREOPEN_GOLD',ExperimentPreflightStatus.PASS,
            'GMT严格前日、ETF前收盘、前缀不变、当日开盘标签合成核验。'),),ExperimentResult(ExperimentOutcome.PASS,{'synthetic':True},{}))

    def execute(self,context):
        result=context.data.fetch(DataRequest('fx.fxcm_daily','XAUUSD.FXCM','2020-06-05','2026-09-30',None))
        artifacts=[];audit={'dataset':'fx.fxcm_daily','symbol':'XAUUSD.FXCM','status':result.status.value,'warnings':list(result.warnings)}
        def save(name,value,kind='cross_market_evidence'):
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8',newline='\n')
            artifacts.append(context.workspace.register_artifact(name,kind))
        if result.status is not DataStatus.READY:
            audit['error']={'code':result.error.code,'message':result.error.message};save('data_audit.json',audit)
            return ExperimentResult(ExperimentOutcome.PASS,{'data_ready':False,'test_paths':0},
                {'research_status':'INSUFFICIENT_DATA','meaning':'数据获取诊断执行完成；没有收益证据。'},tuple(artifacts))
        xau=result.dataframe;ident=result.identity
        audit.update(rows=len(xau),first=str(xau.Date.min()),last=str(xau.Date.max()),identity={'content_sha256':ident.content_sha256,'metadata':dict(ident.metadata)})
        save('data_audit.json',audit)
        xau.to_parquet(context.workspace.path('data/xau.parquet'),index=False);artifacts.append(context.workspace.register_artifact('data/xau.parquet','source_data'))
        prior=context.predecessors['EX004_20261004'];expected={a.path:a.sha256 for a in prior.artifacts}
        root=Path(__file__).resolve().parents[1]/'EX004_20261004/artifacts/rex'
        def read(name):
            p=root/name;assert sha256(p.read_bytes()).hexdigest()==expected[name];return pd.read_parquet(p)
        values,f,m=analyze(read('data/raw.parquet'),read('features.parquet'),xau,read('data/fx.parquet'))
        for name,value in values.items():save(name,value)
        for name,frame in [('features.parquet',f),('signals.parquet',m)]:
            frame.to_parquet(context.workspace.path(name));artifacts.append(context.workspace.register_artifact(name,'causal_features'))
        assert len(values['opportunities.json'])==96
        return ExperimentResult(ExperimentOutcome.PASS,{'data_ready':True,'rows':len(xau),'test_paths':96},
            {'scope':'全部开发池，开盘前信息；不含入场之前跳空收益。'},tuple(artifacts))
