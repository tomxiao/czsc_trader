from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research_experiment import (ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult, ExperimentOutcome,
    ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentDependency)
from .analysis import analyze, features, signals, labels, dedup, MECHANISMS

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2,'EX006_20261004','S012',ExperimentMode.FORMAL,
            '哪些因果可得状态提供扣费后的收益机会，相对同年趋势波动状态有多少增量及可用频率？',
            '短期回调、流动性冲击、突破延续及黄金相对价格修复存在竞争解释，必须由事件经济证据区分。',
            ('净事件收益不能覆盖成本。','相对同年趋势波动对照无增量。','仅少数年度或极低频事件有效。','增加可得延迟后效果消失。'),
            date(2026,9,30),12006,('etf.unadjusted_daily',),
            ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ('EX004-005风险信息强、机会信息弱；用户要求机会优先。',),
                ('19项固定机制及竞争解释；1/3/5/10日标签；额外0/1/2日延迟。',),
                ('收益机会幅度、持续期、频率和反证；不执行完整策略。',),
                ('净事件均值、同年趋势波动匹配增量、去重事件密度、年度/延迟/成本压力。',),
                ('所有历史均为开发池；既有结果影响假设选择。','阈值仅在上一年底数据拟合；检验对照组事后统计不用于交易。',
                 '不进行参数最优化；完整公开全部固定条件与结果。'),
                predecessor_experiment_ids=('EX004_20261004','EX005_20261004')),
            ExperimentDataScope.DEVELOPMENT,subjects=('518850.SH',),
            dependencies=tuple(ExperimentDependency(p,version(p)) for p in ('numpy','pandas','tsfresh')),
            capabilities=ExperimentCapabilities(reads_real_returns=True,selects_parameters=True))

    def synthetic_precheck(self):
        dates=pd.bdate_range('2020-01-01',periods=850); t=np.arange(len(dates)); c=100+np.sin(t/3)+t/100
        raw=pd.DataFrame({'Date':dates.strftime('%Y-%m-%d'),'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':100+t%17})
        inherited=pd.DataFrame({col:np.sin(t/19)/100 for col in
            ('volatility_20','momentum_20','momentum_60','etf_sge_deviation_20','shares_change_5','fx_change_5',
             'real_yield_change_5','basis_change_5','sge_momentum_5','close_location')},index=dates)
        inherited['volatility_20']=.01; inherited['close_location']=.5
        f=features(raw,inherited); a,_,_=signals(f); b,_,_=signals(features(raw.iloc[:650],inherited.iloc[:650]))
        pd.testing.assert_frame_equal(a.iloc[:650],b)
        lab=labels(raw,3); assert lab.index.equals(dates) and np.isclose(lab.gross.iloc[0],c[4]/c[1]-1)
        assert lab.gross.iloc[-4:].isna().all()
        assert dedup(np.array([0,1,3,4,8]),3).tolist()==[0,4,8]
        assert len(a.columns)==len(MECHANISMS) and a.notna().any().all()
        return ExperimentPrecheckResult((ExperimentPreflightCheck('CAUSAL_OPPORTUNITY',ExperimentPreflightStatus.PASS,
            '真实构造函数字符串日期、标签边界、年度阈值前缀不变、机会去重验证。'),),ExperimentResult(ExperimentOutcome.PASS,{'synthetic':True},{}))

    def execute(self,context):
        prior=context.predecessors['EX004_20261004']; expected={a.path:a.sha256 for a in prior.artifacts}
        root=Path(__file__).resolve().parents[1]/'EX004_20261004/artifacts/rex'
        def read(name):
            p=root/name; assert sha256(p.read_bytes()).hexdigest()==expected[name]; return pd.read_parquet(p)
        metrics,years,thresholds,masks=analyze(read('data/raw.parquet'),read('features.parquet'))
        artifacts=[]
        for name,value in [('opportunities.json',metrics),('annual.json',years),('thresholds.json',thresholds)]:
            context.workspace.path(name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
            artifacts.append(context.workspace.register_artifact(name,'opportunity_evidence'))
        masks.to_parquet(context.workspace.path('signals.parquet')); artifacts.append(context.workspace.register_artifact('signals.parquet','causal_signals'))
        return ExperimentResult(ExperimentOutcome.PASS,{'mechanisms':len(MECHANISMS),'test_paths':len(metrics),'annual_cells':len(years)},
            {'scope':'开发池，固定机制比较；事件不等于策略账户或实际限价成交。','predecessor':prior.receipt_sha256},tuple(artifacts))
