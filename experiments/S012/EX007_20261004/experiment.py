from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research_experiment import (ResearchExperiment,ExperimentDefinition,ExperimentMode,ExperimentDataScope,
    ExperimentCapabilities,ExperimentProtocol,ExperimentStage,ExperimentResult,ExperimentOutcome,
    ExperimentPrecheckResult,ExperimentPreflightCheck,ExperimentPreflightStatus,ExperimentDependency)
from .analysis import analyze,masks,limit_events,NAMES
from .base import labels

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,'EX007_20261004','S012',ExperimentMode.FORMAL,
            '汇率支持下的回调是否具有独立机会信息，触发宽度和限价可达性如何影响收益与频率？',
            '汇率偏强与ETF回调的错位可能提供数日修复机会；放宽条件可以增加容量但可能稀释增量。',
            ('只由汇率或ETF弱势主效应解释。','放宽触发后增量消失。','限价可成交事件偏向亏损。','依赖少数极值或特定年度。'),
            date(2026,9,30),12007,('etf.unadjusted_daily',),
            ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ('EX006的fx_dip为主要机会线索，q约0.82且频率约2次/60日；结果后选择必须披露。',),
                ('14项固定竞争/宽度/时间尺度/互补对照；全部1/3/5/10日及0/1/2滞后。',),
                ('明确可进入后续策略设计的机会职责与最强反证，修正EX006辅助MFE单位。',),
                ('净事件收益、匹配增量、2x2交互、极值剔除、逐年、固定相位、限价可达性与完整日历频率。',),
                ('固定对照不做最优阈值搜索；全部方案和费用压力公开。','全期开发池，继承EX004-006选择历史。','限价仅为独立事件诊断，不是策略账户回测。'),
                predecessor_experiment_ids=('EX004_20261004','EX006_20261004')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','tsfresh')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=True))

    def synthetic_precheck(self):
        d=pd.bdate_range('2020-01-01',periods=850);t=np.arange(len(d));c=100+np.sin(t/3)+t/100
        raw=pd.DataFrame({'Date':d.strftime('%Y-%m-%d'),'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':100+t%17})
        inherited=pd.DataFrame({k:np.sin(t/19)/100 for k in ('volatility_20','momentum_20','momentum_60',
            'etf_sge_deviation_20','shares_change_5','fx_change_5','real_yield_change_5','basis_change_5','sge_momentum_5','close_location')},index=d)
        inherited['volatility_20']=.01; inherited['close_location']=.5; inherited['fx_level']=7+np.sin(t/17)/10
        a,_,_=masks(raw,inherited);b,_,_=masks(raw.iloc[:650],inherited.iloc[:650]);pd.testing.assert_frame_equal(a.iloc[:650],b)
        flat=raw.assign(Open=100.,High=101.,Low=99.,Close=100.)
        lab=labels(flat,5);assert np.allclose(lab.mfe.dropna(),.01) and np.allclose(lab.mae.dropna(),.01)
        signal=pd.Series(1.,index=d)
        r=limit_events(flat,signal,5,0.);assert r['fill_rate']==1 and np.isclose(r['net20'],.999/1.001-1)
        missed=flat.assign(Open=102.,High=103.,Low=101.)
        r=limit_events(missed,signal,5,0.);assert r['filled']==0 and r['dedup_filled']==0
        assert len(a.columns)==14
        return ExperimentPrecheckResult((ExperimentPreflightCheck('OPPORTUNITY_ATTRIBUTION',ExperimentPreflightStatus.PASS,
            '前缀不变、字符串日期、MFE/MAE比例、限价全成交与零成交、费用和窗口边界。'),),ExperimentResult(ExperimentOutcome.PASS,{'synthetic':True},{}))

    def execute(self,context):
        prior=context.predecessors['EX004_20261004'];expected={a.path:a.sha256 for a in prior.artifacts}
        root=Path(__file__).resolve().parents[1]/'EX004_20261004/artifacts/rex'
        def read(name):
            p=root/name;assert sha256(p.read_bytes()).hexdigest()==expected[name];return pd.read_parquet(p)
        results,m=analyze(read('data/raw.parquet'),read('features.parquet'));artifacts=[]
        for name,value in results.items():
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
            artifacts.append(context.workspace.register_artifact(name,'opportunity_robustness'))
        m.to_parquet(context.workspace.path('signals.parquet'));artifacts.append(context.workspace.register_artifact('signals.parquet','opportunity_signals'))
        return ExperimentResult(ExperimentOutcome.PASS,{'mechanisms':len(NAMES),'test_paths':len(results['opportunities.json']),
            'sensitivity_cells':len(results['sensitivity.json']),'limit_cells':len(results['limit_events.json'])},
            {'selection_history':'EX006结果后选择；开发池。独立事件不等于账户绩效。'},tuple(artifacts))
