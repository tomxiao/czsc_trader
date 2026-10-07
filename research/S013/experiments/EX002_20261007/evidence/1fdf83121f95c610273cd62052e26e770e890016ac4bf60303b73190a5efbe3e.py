"""Disclosed adaptive incremental/ablation checks; no strategy search."""
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
from prepare_data import ROOT, WORK, save

ACF='tsfresh20_autocorrelation__lag_1'
PRIMARY=['range_position_60',ACF,'turnover_ratio_20','range_compression_5_20','pullback_x_trend']

def correlation(x,y):
    return float(spearmanr(x,y).statistic)

def feature_check(task):
    name, dataset = task
    data = dataset.dropna(subset=[name,'return_10','downside_20']).copy()
    result = {'year_centered':{},'year_shift_null':{},'nonoverlapping_phases':{},'conditional':{}}
    for label in ('return_10','downside_20'):
        centered_x = data[name] - data.groupby(data.Date.dt.year)[name].transform('mean')
        centered_y = data[label] - data.groupby(data.Date.dt.year)[label].transform('mean')
        observed = correlation(centered_x,centered_y)
        rng = np.random.default_rng(31)
        null=[]
        # Preserve each year's time dependence and sample size; descriptive null,
        # circular boundaries and post-selection are explicitly disclosed.
        groups = [g for _,g in data.groupby(data.Date.dt.year)]
        for _ in range(300):
            values=np.concatenate([np.roll(g[label].to_numpy(),int(rng.integers(25,len(g)-25)))
                                   - float(g[label].mean()) for g in groups])
            null.append(correlation(centered_x,values))
        result['year_centered'][label]=observed
        result['year_shift_null'][label]={'two_sided_fraction':float((1+sum(abs(x)>=abs(observed) for x in null))/301),
            'interval95':list(map(float,np.quantile(null,[.025,.975]))), 'replicates':300,
            'multiplicity_adjusted':False}
        phase_ics=[]
        step=11 if label=='return_10' else 20
        for offset in range(step):
            selected=data.iloc[offset::step]
            phase_ics.append(correlation(selected[name],selected[label]))
        result['nonoverlapping_phases'][label]={'spacing_sessions':step,'ics':phase_ics,
            'min':min(phase_ics),'max':max(phase_ics),'median':float(np.median(phase_ics))}
    for group_name,mask in [('positive_momentum20',data.momentum_20>0),('nonpositive_momentum20',data.momentum_20<=0)]:
        g=data.loc[mask]
        result['conditional'][group_name]={'n':len(g),'return10_ic':correlation(g[name],g.return_10),
                                          'downside20_ic':correlation(g[name],g.downside_20)}
    # Use prior-only rolling relative volatility state; no current/year quantile fitted on future data.
    rolling_median=dataset.volatility_20.shift(1).rolling(60,min_periods=60).median()
    for group_name,mask in [('relative_high_volatility',dataset.volatility_20>rolling_median),
                           ('relative_low_volatility',dataset.volatility_20<=rolling_median)]:
        g=dataset.loc[mask].dropna(subset=[name,'return_10','downside_20'])
        result['conditional'][group_name]={'n':len(g),'return10_ic':correlation(g[name],g.return_10),
                                          'downside20_ic':correlation(g[name],g.downside_20)}
    return name,result

def empirical_rank(train,test):
    ordered=np.sort(train)
    return np.searchsorted(ordered,test,side='right')/len(ordered)-.5

def regression_task(task):
    model_name,feature_names,label,data=task
    end='end_10' if label=='return_10' else 'end_downside_20'
    rows=[]
    predictions=[]
    for year in range(2021,2027):
        boundary=pd.Timestamp(year,1,1)
        train=data.loc[(data.Date<boundary)&(data[end]<boundary)].dropna(subset=feature_names+[label])
        test=data.loc[data.Date.dt.year.eq(year)].dropna(subset=feature_names+[label])
        xt=np.column_stack([empirical_rank(train[col].to_numpy(),train[col].to_numpy()) for col in feature_names])
        xv=np.column_stack([empirical_rank(train[col].to_numpy(),test[col].to_numpy()) for col in feature_names])
        mean=float(train[label].mean())
        beta=np.linalg.solve(xt.T@xt+np.eye(len(feature_names))*10.0,xt.T@(train[label].to_numpy()-mean))
        pred=mean+xv@beta
        y=test[label].to_numpy()
        ic=correlation(pred,y)
        q25,q75=np.quantile(pred,[.25,.75])
        high_mean=float(np.mean(y[pred>=q75])); low_mean=float(np.mean(y[pred<=q25]))
        rows.append({'year':year,'train_n':len(train),'test_n':len(test),'prediction_ic':ic,
            'mse':float(np.mean((pred-y)**2)),'prior_mean_mse':float(np.mean((mean-y)**2)),
            'high_minus_low':high_mean-low_mean,'high_mean':high_mean,'low_mean':low_mean,
            'coefficients':dict(zip(feature_names,map(float,beta)))})
        predictions.extend({'Date':str(t),'model':model_name,'label':label,'prediction':float(p),'actual':float(a)}
                           for t,p,a in zip(test.Date,pred,y))
    return model_name,{'label':label,'features':feature_names,'ridge_lambda':10.0,'years':rows},predictions

def main():
    data=pd.read_csv(WORK/'component_observations.csv',float_precision='round_trip',parse_dates=['Date','end_5','end_10','end_20','end_downside_20'])
    plan={'adaptive':True,'trigger':'首轮29项结果已观察；range60与acf1年度方向较一致，需排除趋势/波动重复及重叠标签解释。',
        'selected_features':PRIMARY,'checks':['逐年去中心后相关、逐年循环移位描述性零假设',
            '所有非重叠相位取样、正负趋势和过去60日相对波动分层',
            '逐年向前、隔离已完成标签的固定岭回归增量与消融'],
        'models':'历史分位秩、固定ridge_lambda=10，不优化模型参数；过去年份拟合，当前年测试',
        'limitations':'选择了开发池首轮表现较强项；数据和方法存在选择复用；本检验无独立封存样本，无研究族显著性或经济达标判断。',
        'null':'每年标签保持顺序但随机循环位移25至n-25，300次；保留序列依赖但循环边界为近似；未作多重比较校正'}
    repository=RepositoryContext.discover(ROOT)
    research=create_research_context(repository,ResearchBatchRef('S013'),
        resources=EvaluationResources(max_workers=8,native_threads_per_worker=1,random_seed=13))
    experiment=ExperimentRef('S013','EX002_20261007')
    reference=publish_evidence(research,MaterialEvidenceWrite(experiment,'adaptive-incremental-check-design',
        json.dumps(plan,ensure_ascii=False,indent=2).encode(),'application/json','json'))
    save('followup_protocol.json',plan); save('followup_protocol_reference.json',reference.to_dict())
    base=['momentum_20','volatility_20']
    models=[('controls',base,'return_10'),('controls_range60',base+['range_position_60'],'return_10'),
        ('controls_acf1',base+[ACF],'return_10'),('controls_range60_acf1',base+['range_position_60',ACF],'return_10'),
        ('plus_turnover',base+['range_position_60',ACF,'turnover_ratio_20'],'return_10'),
        ('plus_range',base+['range_position_60',ACF,'range_compression_5_20'],'return_10'),
        ('risk_controls',base,'downside_20'),('risk_pullback',base+['pullback_x_trend'],'downside_20'),
        ('risk_skewness',base+['tsfresh20_skewness'],'downside_20')]
    with ProcessPoolExecutor(max_workers=8,mp_context=multiprocessing.get_context('spawn')) as executor:
        checks=dict(executor.map(feature_check,[(x,data) for x in PRIMARY]))
        evaluated=list(executor.map(regression_task,[(name,columns,label,data) for name,columns,label in models]))
    correlations=pd.read_csv(WORK/'component_correlations.csv',index_col=0)
    redundancy={'volatility20_vs_tsfresh_std':float(correlations.loc['volatility_20','tsfresh20_standard_deviation']),
                'range60_vs_momentum60':float(correlations.loc['range_position_60','momentum_60']),
                'range60_vs_acf1':float(correlations.loc['range_position_60',ACF]),
                'turnover_vs_volume_ratio':float(correlations.loc['turnover_ratio_20','volume_ratio_5_20'])}
    save('followup_results.json',{'checks':checks,'models':{k:v for k,v,_ in evaluated},'redundancy':redundancy})
    pd.DataFrame([item for _,_,items in evaluated for item in items]).to_csv(WORK/'model_predictions.csv',index=False,float_format='%.17g',lineterminator='\n')
    print(json.dumps({'redundancy':redundancy,'checks':{k:{'centered':v['year_centered'],
        'null_fraction':v['year_shift_null']['return_10']['two_sided_fraction'],
        'return_phase_minmax':[v['nonoverlapping_phases']['return_10']['min'],v['nonoverlapping_phases']['return_10']['max']]} for k,v in checks.items()}},ensure_ascii=False,indent=2))
    for name,values,_ in evaluated:
        print(json.dumps({'model':name,'year_ics':[round(row['prediction_ic'],4) for row in values['years']],
            'year_spreads_pp':[round(row['high_minus_low']*100,2) for row in values['years']],
            'mse_better_than_prior_mean':sum(row['mse']<row['prior_mean_mse'] for row in values['years'])},ensure_ascii=False))

if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
