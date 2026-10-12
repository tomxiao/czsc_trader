"""EX090 mature-pool estimator clock change, no new feature or native account."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402

WORK=Path(__file__).resolve().parent
OUT=ROOT/'.tmp/s013-new-goal/result090'
PROB=ROOT/'research/S013/experiments/EX084_20261012/src/kernel.py'
GAIN=ROOT/'research/S013/experiments/EX086_20261012/src/kernel.py'


def plan():
    prior=g.read(ROOT/'research/S013/experiments/EX089_20261012/protocols/plan.json')
    old=g.read(ROOT/'research/S013/experiments/EX086_20261012/protocols/plan.json')
    checks=g.read(WORK/'focused_checks.json')
    if checks['status']!='PASS' or g.read(WORK/'audit_checks.json')['status']!='PASS':
        raise ValueError('Synthetic parallel and independent audit PASS first')
    for name,sha in checks['files'].items():
        if g.digest(WORK/name)!=sha:
            raise ValueError('Checked source drift')
    names=['kernel.py','audit.py','focused_checks.py','focused_checks.json','focused_checks_serial_v1.json',
           'worker.py','parallel_checks.json','audit_checks.py','audit_checks.json','driver.py']
    sources=[(WORK/name).relative_to(ROOT).as_posix() for name in names]
    sources+=['.tmp/s013-new-goal/governance.py','.tmp/s013-new-goal/gates_v2.py',
              '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',
              PROB.relative_to(ROOT).as_posix(),GAIN.relative_to(ROOT).as_posix(),
              'research/S013/experiments/EX083_20261012/src/kernel.py','research/S013/experiments/EX083_20261012/src/audit.py']
    return {'question':'同一原PG赚幅信息，改为标签真正成熟后逐T更新能否修正年度冻结滞后并改善下跌年净选择？',
       'basis':'EX089简单加最近误差使MSE恶化且2023/2026更差，停止20窗口校准。EX0842022历史盈利结构过于乐观，EX087赚幅局部增量，尚未区分原年更新与实际成熟信息更新。',
       'strongest_counter':'每日扩展训练仍以旧历史为主，不增加新市场信息；重叠标签和极端大赚影响估计，不保证适应新环境；年度冻结不是已经证明的唯一失败原因。',
       'fixed_design':'原14/确认列8，两族原110年PG精确不变。2021起每T用2020起完整原14、signal<T且label_end<=T成熟池；n40且盈利/非正各20，跨年不重置。旧logit及正赚幅原函数/alpha10/100Newton40Armijo/gradient1e-10不改；loss用成熟非正幅度均值，不恢复条件亏幅。',
       'role_of_component':'估计更新时间职责；原收益概率及赚幅与成熟损幅均值的净机会选择',
       'label':'原h4扣费HFQ OPEN价格收益，正y与非正y(含0)分类',
       'horizon':'h4固定；扩展成熟训练，未引入遗忘窗口/阈值/alpha搜索',
       'controls':'各族historical原年度q、matched完整daily支持原q、当T扩展training_mean、onlinePG；48所有钟/年度/五相位，原历史钟与EX087精确一致',
       'availability':'旧年度q当时已发行；新模型只取signal<T且label_end<=T的完整成熟原14，当前features缺失NA；不取未来test数量、不年重置',
       'price_basis':'原510500HFQ锚/无现金分红叠加/原1m整手100单侧10bp及1percent执行',
       'limitations':'估计更新不是新信息；同开发池反复选择无封存；价格代理非真实账户/年度收益/闭合次数',
       'quantities':['每族净MSE改善相对matched与training_mean、新正选择均值及相对两控制差、greedy均值相对matched差共12项'],
       'bootstrap':'500x40原轴seed13,固定实际预测和选择不重拟合,20/400minimum,LINEAR95,非标准32',
       'resources':{'family_fit_processes':2,'blas_threads_each':1,'new_models':'4 per validdailyT,actualcount fromtrace','native_accounts':0,'provider_calls':0},
       'input_references':{**prior['input_references'],'features.csv':old['input_references']['features.csv']},
       'source_files':{name:g.digest(ROOT/name) for name in sources},
       'new_goal':'MANDATE/7 v2;center andstandard32 all passnew4;allpoolfrequency diagnosticonly',
       'stop_or_followup':'净增量及经济余量不足则停止固定扩展每日PG，不扫窗口/正则/相位；存在明确新经济依据才另冻结原生中心计划',
       'objective_achieved':False}


def inputs(frozen):
    def frame(key):
        f=pd.read_csv(g.public(frozen['input_references'][key]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    features,labels,prices,scores=(frame(k) for k in ('features.csv','labels.csv','prices.csv','scores.csv'))
    labels['label_end_return_4']=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    kernel=g.base.load('online_pg_input_definition',WORK/'kernel.py')
    if not set(kernel.FEATURES).issubset(features.columns) or len(scores)!=1635 or not scores.index.equals(prices.index[1:-1]):
        raise ValueError('Original features/axis identity required')
    features=features.loc[:,list(kernel.FEATURES)]
    raw=prices['open'].shift(-5)/prices['open'].shift(-1)*(.999/1.001)-1
    ends=pd.Series(prices.index,index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4,raw.reindex(scores.index),atol=2e-13,rtol=2e-11,equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4.to_numpy(),ends.reindex(scores.index).to_numpy())
    old_scores=scores.loc[:,list(kernel.INPUTS)]
    kernel.validate(features,labels,old_scores)
    return features,labels,old_scores


def declare():
    frozen=plan()
    exp,frozen,refs=g.allocate(90,title='成熟标签驱动的扩展概率赚幅更新',question=frozen['question'],plan=frozen,checks=g.read(WORK/'focused_checks.json'))
    OUT.mkdir(parents=True,exist_ok=True)
    g.write(OUT/'declaration.json',{'experiment':exp.to_dict(),'slot':2,'new_accounts':0})
    print({'experiment':exp.experiment_id,'slot':2,'new_accounts':0},flush=True)


def study():
    exp,path,frozen,refs=g.stage(90)
    g.write(OUT/'study_attempt.json',{'status':'STARTED','actual_complete_analyses_maximum':1,'processes':2,'new_accounts':0})
    features,labels,old=inputs(frozen)
    kernel=g.base.load('online_pg_primary',WORK/'kernel.py')
    worker=g.base.load('online_pg_parallel_worker',WORK/'worker.py')
    scores,traces=worker.runner(features,labels,old,PROB,GAIN)
    clock=g.base.load('online_pg_frozen_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
    result=kernel.summarize(scores,labels,traces,clock)
    previous=g.read(g.public(frozen['input_references']['prior_statistics.json']))
    for family in kernel.FAMILIES:
        if result['schedules'][family+'_historical']!=previous['schedules'][family+'_110']:
            raise ValueError('Original historical schedules must equal EX087')
    with (OUT/'forecasts.csv').open('x',encoding='utf-8',newline='\n') as stream:
        scores.to_csv(stream,index_label='signal_date',float_format='%.17g')
    g.write(OUT/'statistics.json',result)
    g.write(OUT/'input_checks.json',{'status':'PASS','signals':len(features),'HFQ_OPEN_labels':'EXACT','frozen_original14_and_PG':'EXACT',
           'historical_schedules':'EX087_EXACT','model_fit_processes':2,'blas_threads_each':1,
           'actual_completed_analyses':1,'actual_models':result['new_daily_models'],'new_accounts':0,'provider_calls':0})
    c=g.base.common()
    outrefs={name:g.put(c.context(1),exp,OUT/name) for name in ('forecasts.csv','statistics.json','input_checks.json')}
    g.write(path/'protocols/result_references.json',outrefs)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'study':'COMPLETE','actual_models':result['new_daily_models'],'new_accounts':0},flush=True)


def audit():
    exp,path,frozen,refs=g.stage(90)
    outrefs=g.read(path/'protocols/result_references.json')
    features,labels,old=inputs(frozen)
    scores=pd.read_csv(g.public(outrefs['forecasts.csv']),index_col='signal_date',float_precision='round_trip')
    scores.index=pd.to_datetime(scores.index).as_unit('ns')
    oracle=g.base.load('online_pg_independent',WORK/'audit.py')
    clock=g.base.load('online_pg_independent_clock',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
    proof=oracle.verify(features,labels,old,scores,g.read(g.public(outrefs['statistics.json'])),clock)
    proof['result_references']=outrefs
    proof['plan_reference']=refs['plan.json']
    proof['new_accounts']=0
    g.write(OUT/'verification.json',proof)
    c=g.base.common()
    ref=g.put(c.context(1),exp,OUT/'verification.json')
    g.write(path/'protocols/audit_reference.json',ref)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'audit':proof['status'],'new_accounts':0},flush=True)


if __name__=='__main__':
    {'declare':declare,'study':study,'audit':audit}[sys.argv[1]]()
