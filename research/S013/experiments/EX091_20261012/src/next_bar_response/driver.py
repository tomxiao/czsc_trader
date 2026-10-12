"""Prospective EX091 same-day response interaction, zero accounts."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402

WORK=Path(__file__).resolve().parent
OUT=ROOT/'.tmp/s013-new-goal/result091'
NUMERIC=ROOT/'research/S013/experiments/EX075_20261011/src/statistics_draft_v2.py'
ORDER=ROOT/'research/S013/experiments/EX068_20261011/src/order_component.py'


def definition():
    for key in ('focused_checks.json','synthetic_checks.json','audit_statistics_checks.json','kernel_checks.json'):
        if g.read(WORK/key)['status']!='PASS':
            raise ValueError('All pure synthetic checks must pass')
    old=g.read(ROOT/'research/S013/experiments/EX090_20261012/protocols/plan.json')['input_references']
    refs75=g.read(ROOT/'research/S013/experiments/EX075_20261011/protocols/closeout_references.json')
    refs68=g.read(ROOT/'research/S013/experiments/EX068_20261011/protocols/result_references.json')
    binding=g.read(g.public(refs75['input_bindings_draft.json']))
    sources=[(WORK/name).relative_to(ROOT).as_posix() for name in
        ('kernel.py','features.py','focused_checks.py','focused_checks.json','audit_features.py',
         'synthetic_checks.py','synthetic_checks.json','audit_statistics.py','audit_statistics_checks.py',
         'audit_statistics_checks.json','kernel_checks.py','kernel_checks.json','driver.py')]
    sources += [NUMERIC.relative_to(ROOT).as_posix(),ORDER.relative_to(ROOT).as_posix(),
        '.tmp/s013-new-goal/governance.py','.tmp/s013-new-goal/gates_v2.py',
        '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',
        'research/S013/experiments/EX083_20261012/src/kernel.py','research/S013/experiments/EX083_20261012/src/audit.py']
    return {'question':'负实体bar的成交量与下一bar反应交互，是否在27既有价格/量/时间/无权响应控制之外增加h4净机会信息？',
        'basis':'EX075只测同bar负幅与量，EX068测负段顺序，EX061测端点恢复；均不足。下一bar响应×来源量是此前未直接检验的交互，不因旧失效自动反向。',
        'strongest_counter':'下一bar反弹已经发生在T日，可能不能预测T+1入场收益；量不识别主动买卖、同日7对不独立、只是旧信息新交互、既有控制已大量失效。',
        'role_of_component':'旧日内信息的新交互：下跌成交后紧接实体反应',
        'label':'原h4双边10bp后复权OPEN净标签，maturity=T+5OPEN',
        'horizon':'h4唯一；来源固定同日0..6，不跨日；过去20量时钟只控制，excludeT',
        'controls':'固定原14+EX0612+EX0684+同期负幅/量协方差/过去量时钟+来源无权反应U/来源数/来源平均负幅+过去量时钟下一响应，共27；同28有限支持配对',
        'availability':'完成T日8bar后；所有历史量profile只T-20..T-1；年度模型仅以前已成熟标签、label_end<本年首T；test可得性不依赖未来标签/数量',
        'price_basis':'S013原510500开发池HFQ固定锚/无现金分红叠加/单侧10bp原执行合同',
        'limitations':'组件价格标签不是原生账户/年度净收益/闭合交易/32点；同开发池多重研究无封存；不新增独立市场信息',
        'hypothesis':'X=S-U，固定positive→更高净收益；不按实际结果翻转、不扫bar/窗口/量阈值',
        'method':'全1635轴raw/27control partial rankIC；原轴500overlap40seed13 LINEAR95，20n/10residDF/400valid；年度2021..26同28支持trainECDFmidpoint+ridge10controls/+X，train40，不futuretestcountgate；4prediction数量与18固定clock',
        'stop_or_followup':'若控制后方向不一致及净经济增量不足，停止本固定交互，不翻向/去控制/扫参数；有明确经济余量才冻结同轮原生计划',
        'new_goal':'MANDATE/7；中心+标准32均过新版四门；年度BH盈亏只事后验收',
        'resources':{'one_statistical_study':1,'maximum_new_models':12,'new_accounts':0,'provider_calls':0},
        'input_references':{'features14.csv':old['features.csv'],'labels.csv':old['labels.csv'],
            'prices.csv':old['prices.csv'],'features75.csv':refs75['features.csv'],
            'features68.csv':refs68['features.csv'],'native_account.json':binding['native_ref']},
        'native_cache_sha256':g.digest(ROOT/'.tmp/s013-mechanism-EX058/N0.pkl.gz'),
        'source_files':{name:g.digest(ROOT/name) for name in sources}}


def frame(ref):
    f=pd.read_csv(g.public(ref),index_col='signal_date',float_precision='round_trip')
    f.index=pd.to_datetime(f.index).as_unit('ns')
    return f


def inputs(plan):
    refs=plan['input_references']
    old14,old75,old68,labels,prices=(frame(refs[k]) for k in ('features14.csv','features75.csv','features68.csv','labels.csv','prices.csv'))
    c=g.base.common()
    cache=ROOT/'.tmp/s013-mechanism-EX058/N0.pkl.gz'
    if g.digest(cache)!=plan['native_cache_sha256']:
        raise ValueError('Native cached input changed')
    bound,result=c.cache_read(cache)
    if serialize_evaluation_evidence(bound,result)!=g.read(g.public(refs['native_account.json'])):
        raise ValueError('Native cache must equal public account')
    ed=bound.execution_data
    bars=ed.execution_intraday.rename(columns={'dt':'Date','open':'Open','close':'Close','vol':'Volume'})[['Date','Open','Close','Volume']].copy()
    bars['Date']=pd.to_datetime(bars.Date).dt.as_unit('ns')
    axis=old14.index
    calendar=pd.DatetimeIndex(pd.to_datetime(ed.evaluation_sessions)).as_unit('ns').normalize()
    if len(axis)!=1635 or not axis.equals(calendar[:-1]):
        raise ValueError('Original axis/calendar required')
    if not pd.DatetimeIndex(bars.Date).normalize().unique().equals(calendar):
        raise ValueError('Exact native complete intraday calendar required')
    k=g.base.load('response_definition',WORK/'kernel.py')
    f=g.base.load('response_features',WORK/'features.py')
    new,trace=f.build(bars,axis)
    oldorder=g.base.load('response_frozen_order',ORDER).build_features(bars.set_index('Date')).loc[axis]
    for name in oldorder:
        np.testing.assert_allclose(oldorder[name],old68[name],rtol=2e-12,atol=2e-14,equal_nan=True)
    for name in k.ORIGINAL:
        pd.testing.assert_series_equal(old14[name],old75[name],check_exact=True,check_names=False)
        pd.testing.assert_series_equal(old14[name],old68[name],check_exact=True,check_names=False)
    for newname,oldname in (('negative_body_mean','mean_negative_body'),('samebar_cov','down_volume_cov'),('past_clock_samebar','past_volume_shape_projection')):
        np.testing.assert_allclose(new[newname],old75[oldname],rtol=2e-11,atol=2e-14,equal_nan=True)
    features=old14[list(k.ORIGINAL)].join(old75[['late_recovery','early_volume_reclaim']]).join(oldorder).join(new.drop(columns=['S']))
    features=features[[*k.CONTROLS,'X']]
    labels['label_end_return_4']=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    raw=prices.open.shift(-5)/prices.open.shift(-1)*(.999/1.001)-1
    ends=pd.Series(prices.index,index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4,raw.reindex(axis),rtol=2e-11,atol=2e-13,equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4,ends.reindex(axis))
    if not features.index.equals(labels.index):
        raise ValueError('Feature/label exact axis required')
    assert not c.SOURCE_CALLS
    return features,labels,bars,new,trace


def declare():
    p=definition()
    exp,p,refs=g.allocate(91,title='下跌成交后的下一bar响应增量',question=p['question'],plan=p,checks=g.read(WORK/'kernel_checks.json'))
    OUT.mkdir(parents=True,exist_ok=True)
    g.write(OUT/'declaration.json',{'experiment':exp.to_dict(),'new_accounts':0,'quota_slot':3})
    print({'experiment':exp.experiment_id,'stage':'DECLARED','new_accounts':0},flush=True)


def study():
    exp,path,p,refs=g.stage(91)
    g.write(OUT/'study_attempt.json',{'status':'STARTED','study_limit':1,'new_accounts':0})
    features,labels,bars,new,trace=inputs(p)
    k=g.base.load('response_primary',WORK/'kernel.py')
    numeric=g.base.load('response_existing_numeric',NUMERIC)
    clock=g.base.load('response_existing_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
    scores,traces=k.forecasts(features,labels,numeric)
    stats=k.analyze(features,labels,scores,traces,numeric,clock)
    for name,table in (('features.csv',features),('forecasts.csv',scores)):
        with (OUT/name).open('x',encoding='utf-8',newline='\n') as stream:
            table.to_csv(stream,index_label='signal_date',float_format='%.17g')
    g.write(OUT/'availability.json',trace.reset_index().to_json(orient='records',date_format='iso'))
    g.write(OUT/'statistics.json',stats)
    g.write(OUT/'input_checks.json',{'status':'PASS','signals':len(features),'same_native_source':'PUBLIC_EXACT',
        'old14_EX061_EX068_EX075':'EXACT_OR_ROUNDOFF_TOLERANCE','HFQ_OPEN_labels':'EXACT',
        'actual_complete_analyses':1,'actual_models':stats['new_models'],'new_accounts':0,'provider_calls':0})
    c=g.base.common()
    refs={name:g.put(c.context(1),exp,OUT/name) for name in ('features.csv','forecasts.csv','availability.json','statistics.json','input_checks.json')}
    g.write(path/'protocols/result_references.json',refs)
    print({'experiment':exp.experiment_id,'stage':'COMPLETE','new_models':stats['new_models'],'new_accounts':0},flush=True)


def audit():
    exp,path,p,refs=g.stage(91)
    features,labels,bars,new,trace=inputs(p)
    outrefs=g.read(path/'protocols/result_references.json')
    reportedfeatures=frame(outrefs['features.csv'])
    pd.testing.assert_frame_equal(features,reportedfeatures,check_exact=True)
    proof=g.base.load('response_features_oracle',WORK/'audit_features.py').verify(bars,features.index,new,trace)
    statsproof=g.base.load('response_stats_oracle',WORK/'audit_statistics.py').verify(features,labels,frame(outrefs['forecasts.csv']),g.read(g.public(outrefs['statistics.json'])),
        g.base.load('response_clock_oracle',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py'))
    g.write(OUT/'verification.json',{'status':'PASS','feature_audit':proof,'statistics_audit':statsproof,'new_accounts':0,
        'provider_calls':0,'plan_reference':refs['plan.json'],'result_references':outrefs})
    c=g.base.common()
    g.write(path/'protocols/audit_reference.json',g.put(c.context(1),exp,OUT/'verification.json'))
    print({'experiment':exp.experiment_id,'audit':'PASS','new_accounts':0},flush=True)


if __name__=='__main__':
    {'declare':declare,'study':study,'audit':audit}[sys.argv[1]]()
