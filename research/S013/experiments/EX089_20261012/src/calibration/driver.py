"""EX089 fixed mature forecast calibration: freeze, declare, study, independent audit."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
sys.path.insert(0,str(ROOT/'.tmp/s013-new-goal'))
import governance as g  # noqa: E402

WORK=Path(__file__).resolve().parent
OUT=ROOT/'.tmp/s013-new-goal/result089'
NUMBER=89


def frozen_plan():
    previous=g.read(ROOT/'research/S013/experiments/EX088_20261012/protocols/plan.json')
    checks=g.read(WORK/'focused_checks.json')
    if checks['status']!='PASS' or g.read(WORK/'audit_checks.json')['status']!='PASS' or g.read(ROOT/'.tmp/s013-new-goal/gate_checks.json')['status']!='PASS':
        raise ValueError('Synthetic methods and new economic contract must PASS first')
    for name,sha in checks['files'].items():
        if g.digest(WORK/name)!=sha:
            raise ValueError('Synthetic checked source drift')
    sources=[str((WORK/name).relative_to(ROOT)).replace('\\','/') for name in ('kernel.py','audit.py','focused_checks.py','focused_checks.json','audit_checks.py','audit_checks.json','driver.py')]
    sources+=['.tmp/s013-new-goal/governance.py','.tmp/s013-new-goal/gates_v2.py','.tmp/s013-new-goal/gate_checks.py','.tmp/s013-new-goal/gate_checks.json',
        '.tmp/s013_confirm_execution.py','research/S013/experiments/EX058_20261011/src/common.py',
        'research/S013/experiments/EX083_20261012/src/kernel.py','research/S013/experiments/EX083_20261012/src/audit.py']
    kernel=g.base.load('calibration_prospective_kernel',WORK/'kernel.py')
    return {'question':'已经发行净预测的成熟误差能否修正乐观偏差，超越相同成熟样本的原预测和近期raw均值？',
       'basis':'EX0842022历史盈利结构与实际结构偏离；EX086/87赚幅局部支持但组合净选择2022负；年度更新可能滞后。EX085近期raw状态无增量，必须与同20raw均值作配对反证。',
       'strongest_counter':'校准等于rawmean+(currentq-pastmeanq)，不是新增市场信息；成熟延迟可能错过风险，当前/过去预测差可能重表达旧确认，更多交易不保证净盈利。',
       'fixed_design':'两族原110净预测，最近20已发行且h4 truth在T成熟；同日成熟可用，无20或当前q缺失NA，不年重置/不回填。四表达historical/matched/rawmean/calibrated；0新fit；48预设时钟，不择相位。',
       'quantities':list(kernel.QUANTITIES),'bootstrap':'500overlap40 originalTaxis seed13;fixedpredictions/masks;20minimum/400valid;LINEAR95CI;not standard32/futureprobability',
       'role_of_component':'已发行预测偏差校准与扣费机会选择；是否支持新独立风险许可仍待证明',
       'label':'原h4HFQ OPEN扣费收益Open[T+5]/Open[T+1]*.999/1.001-1',
       'horizon':'原h4，固定20已成熟issued预测误差窗口，不扫描',
       'controls':'每族历史原控制、同20可得支持matched原q、raw20均值、calibrated；48所有时钟/年度/相位',
       'availability':'当T已知发出的历史q和label_end<=T的真实h4标签；最终年度标签仅验收；无未来y/年度选择',
       'price_basis':'原510500HFQ锚.2803，无现金分红叠加，原1m/lot100/fee10bp/1percent合同',
       'limitations':'同开发池反复研究；残差不是独立信息；价格代理忽略原生限价/整手/现金路径/浮盈亏；不能据此填硬门或32点状态',
       'input_references':{k:previous['input_references'][k] for k in ('labels.csv','prices.csv','scores.csv','prior_statistics.json','prior_verification.json')},
       'source_files':{name:g.digest(ROOT/name) for name in sources},
       'resources':{'new_annual_models':0,'new_accounts_component':0,'provider_calls':0,'schedules':48,'bootstrap':500},
       'new_goal':'v2 pooledpositivefrequency replaces allpoolfrequency;center+32 must passnew4',
       'stop_or_followup':'证据不足则停止固定20校准，不扫窗口或选年份/相位；有明确增量和经济余量则同轮可另冻结native中心反证，只有新中心四门合格才标准32及独立费检查',
       'objective_achieved':False}


def inputs(plan):
    def frame(key):
        f=pd.read_csv(g.public(plan['input_references'][key]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    labels,prices,full=frame('labels.csv'),frame('prices.csv'),frame('scores.csv')
    labels['label_end_return_4']=pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    expected=tuple(f'{family}_{bits:03b}' for family in ('confirmation','original14') for bits in range(8))
    if tuple(full.columns)!=expected or len(full)!=1635 or not full.index.equals(prices.index[1:-1]):
        raise ValueError('Exact original16 forecasts and1635signal axis required')
    raw=prices['open'].shift(-5)/prices['open'].shift(-1)*(.999/1.001)-1
    maturity=pd.Series(prices.index,index=prices.index).shift(-5)
    np.testing.assert_allclose(labels.return_4,raw.reindex(full.index),atol=2e-13,rtol=2e-11,equal_nan=True)
    np.testing.assert_array_equal(labels.label_end_return_4.to_numpy(),maturity.reindex(full.index).to_numpy())
    previous=g.read(g.public(plan['input_references']['prior_verification.json']))
    if previous['status']!='PASS' or previous['EX084_EX086_controls']!='EXACT':
        raise ValueError('Frozen source forecast controls not audited')
    return full.loc[:,['confirmation_110','original14_110']],labels


def declare():
    plan=frozen_plan()
    checks=g.read(WORK/'focused_checks.json')
    exp,plan,refs=g.allocate(NUMBER,title='已发行净预测的成熟偏差校准',question=plan['question'],plan=plan,checks=checks)
    mandate=g.publish_mandate(exp,refs)
    OUT.mkdir(parents=True,exist_ok=True)
    g.write(OUT/'declaration.json',{'experiment':exp.to_dict(),'mandate':mandate.to_dict(),'slot':1})
    print({'experiment':exp.experiment_id,'MANDATE':7,'new_accounts':0,'slot':1},flush=True)


def study():
    exp,path,plan,refs=g.stage(NUMBER)
    g.write(OUT/'study_attempt.json',{'status':'STARTED','analyze_calls_maximum':1,'new_annual_models':0,'new_accounts':0})
    scores,labels=inputs(plan)
    kernel=g.base.load('calibration_primary',WORK/'kernel.py')
    clock=g.base.load('calibration_frozen_clock',ROOT/'research/S013/experiments/EX083_20261012/src/kernel.py')
    states,signals,result=kernel.analyze(scores,labels,clock)
    previous=g.read(g.public(plan['input_references']['prior_statistics.json']))
    for family in kernel.FAMILIES:
        if result['schedules'][family+'_historical']!=previous['schedules'][family+'_110']:
            raise ValueError('Original historical schedules differ from EX087')
    for name,frame in (('states.csv',states),('forecasts.csv',signals)):
        with (OUT/name).open('x',encoding='utf-8',newline='\n') as stream:
            frame.to_csv(stream,index_label='signal_date',float_format='%.17g')
    g.write(OUT/'statistics.json',result)
    g.write(OUT/'input_checks.json',{'status':'PASS','signals':len(scores),'HFQ_OPEN_labels':'EXACT','issued_scores':'EX087_EXACT',
          'historical_schedules':'EX087_EXACT','provider_calls':0,'new_accounts':0,'new_models':0,'actual_analyze_calls':1})
    c=g.base.common()
    resultrefs={name:g.put(c.context(1),exp,OUT/name) for name in ('states.csv','forecasts.csv','statistics.json','input_checks.json')}
    g.write(path/'protocols/result_references.json',resultrefs)
    assert not c.SOURCE_CALLS
    print({'experiment':exp.experiment_id,'status':'STUDY_COMPLETE','new_accounts':0},flush=True)


def audit():
    exp,path,plan,refs=g.stage(NUMBER)
    results=g.read(path/'protocols/result_references.json')
    scores,labels=inputs(plan)
    def frame(key):
        f=pd.read_csv(g.public(results[key]),index_col='signal_date',float_precision='round_trip')
        f.index=pd.to_datetime(f.index).as_unit('ns')
        return f
    oracle=g.base.load('calibration_independent',WORK/'audit.py')
    clock=g.base.load('calibration_clock_audit',ROOT/'research/S013/experiments/EX083_20261012/src/audit.py')
    proof=oracle.verify(scores,labels,frame('states.csv'),frame('forecasts.csv'),g.read(g.public(results['statistics.json'])),clock)
    proof['result_references']=results
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
