"""Explicit prospective round allocation and immutable per-round closeout."""
import argparse
from datetime import date
from hashlib import sha256
from pathlib import Path

from suite import ROOT,HOME,SOURCE,read,save,context,material,ExperimentRef,EvidenceRef
from czsc_trader.application import RepositoryContext,create_experiment,ExperimentRequest,publish_evidence,validate_experiment
from czsc_trader.research_tools import ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope


def configurations(number):
    base={'entry':0.,'exit':.005,'hold':3}
    if number==2:
        return '试探仓与后续确认', '以少量仓位承接首次卖压，随后同时满足压力改善和价格不低于建立周期时再加至全仓；竞争解释是一般降仓或买晚。',[
            {'registered_control':'C0203'},*[{'mode':'staged',**base,'probe':w} for w in (.25,.5,.75)],{'mode':'delayed',**base}]
    if number==3:
        return '背景趋势与短期卖压交互','已有趋势线性预测失败，不等同于正/负背景中相同卖压机会的实际兑现相同；以20日自然正负边界配对，防止年份规则。',[
            {'mode':m,**base,'lookback':20} for m in ('trend_up','trend_down')]+[
            {'mode':'trend_weight',**base,'lookback':20,'low_weight':w} for w in (.25,.5,.75)]
    if number==4:
        return '持有中反弹状态记忆','原回撤主要发生在入场日，退出改进预期有限；固定检验未起效即退出与已起效才延长，保留反证。',[
            {'mode':'failed_rebound',**base},*[{'mode':'extend_rebound',**base,'extension':e} for e in (1,2,3)]]
    if number==5:
        return '按近期振幅归一化的卖压','原振幅一刀切过滤损害收益，归一化的是卖压强度和退出强度，不是高振幅直接禁入；检验一致尺度的短期冲击。',[
            {'mode':'normalized','entry':e,'exit':x,'hold':h,'lookback':lb}
            for lb in (5,20) for e in (0.,.1,.25) for x in (0.,.1) for h in (2,3)]
    if number==6:
        return '累积卖压与单日冲击的区别','负向单日反转不保证多日坏消息后反弹；把多日平均卖压作为同单位状态，对比原单日，完整账户观察盈利机会代价。',[
            {'mode':'cumulative','entry':e,'exit':x,'hold':h,'lookback':lb}
            for lb in (2,3,5) for e in (0.,.0025) for x in (0.,.005) for h in (2,3)]
    if number==7:
        return '连续风险预算而非两档振幅过滤','已知振幅有连续预测价值；用固定每日期望价格振幅预算连续调整目标仓位，对比已有一般降仓结论，检验是否只损害收益。',[
            {'mode':'adaptive_risk',**base,'lookback':lb,'risk_budget':b}
            for lb in (5,20) for b in (.01,.02,.03,.04)]+[{'registered_control':'C0203'},{'registered_control':'C0204'}]
    if number==8:
        return '压力恶化入场的退出交互','首轮压力恶化组相对原规则收益改善但回撤不降；直接检验改善是否只来自继续承接持续下跌，以及持有期限/压力恢复能否改变取舍。',[
            {'mode':'deteriorate','entry':e,'exit':x,'hold':h}
            for e in (0.,.0025) for x in (0.,.0025,.005) for h in (1,2,3,5)]
    if number==9:
        return '价格确认与压力方向的竞争解释','同日负卖压内部是否已有价格反弹可见？检验价格已收涨再承接卖压，配合正卖压延续的反向完整账户；不是继续拟合入场日预测标签。',[
            {'mode':m,'entry':e,'exit':x,'hold':h}
            for m in ('price_confirm','momentum') for e in (0.,.0025) for x in (0.,.005) for h in (1,2,3)]
    raise ValueError('Round10 reserved for evidence-driven followup/validation, requires explicit design')


def design(number):
    assert 2<=number<=10
    title,hypothesis,configs=configurations(number)
    if number>2:
        previous=ROOT/f'research/S015/experiments/EX{14+number:03d}_20261023/others/results.json'
        assert previous.exists(),'sequential rounds require previous account results'
    ex=create_experiment(context(),ExperimentRequest(title,hypothesis,date(2026,10,23)))
    assert ex.experiment_id==f'EX{15+number:03d}_20261023'
    here=ex.resolve(ROOT)
    protocol={'round':number,'title':title,'hypothesis':hypothesis,'configurations':configs,
        'budget':{'configurations':len(configs),'account_scenarios':2*len(configs),'parameter_search':'finite prospectively queued Optuna ask/tell; no posthoc deletion'},
        'references':{'budget':read(HOME/'protocols/ten_round_budget.json'),
            'previous_rounds':[f'EX{15+i:03d}_20261023' for i in range(1,number)]},
        'controls':'EX016 base control retained; same strategy source, fees, independent434/415 accounts. Registered control points retain original identity and are repeated measurements, not new candidates.',
        'stopping':'All original gates; individual center failures kept. Only center-dual-qualified go to32point+pressure. Round10 reserved for concrete new evidence; do not spend blindly.',
        'selection':'Question chosen after earlier completed rounds and all historical experiments; entirely seen development data.'}
    save(here/'protocols/round.json',protocol)
    refs=[material(ex,name,p).to_dict() for name,p in (
        ('round_protocol',here/'protocols/round.json'),('pressure_path',SOURCE/'strategies/pressure_path.py'),
        ('execution_suite_v4',HOME/'src/suite.py'),('round_allocator',Path(__file__)),
        ('signal_checks',HOME/'others/signal_checks.json'))]
    save(here/'others/protocol_refs.json',refs)
    print({'round':number,'experiment':ex.experiment_id,'configurations':len(configs),'protocol':'PUBLISHED'},flush=True)


def close(experiment,judgment):
    ex=ExperimentRef('S015',experiment)
    here=ex.resolve(ROOT)
    assert not (here/'others/publication_validation.json').exists()
    p=read(here/'protocols/round.json')
    r=read(here/'others/results.json')
    text=f'''# S015 十轮预算第{r['round']}轮：{p.get('title',p.get('question'))}

Status: COMPLETED

RSCH，2026-10-23。第{r['round']}/10轮研究账户计算与诊断完成，中心双窗口同时达标{r['qualified_centers']}个。此处中心达标仍需原434日32点联合扰动、压力和正式阶段四证据；没有预先宣布合格策略。

{judgment}

本轮{r['new_configurations']}个配置、{r['account_scenarios']}个独立账户场景（434日和415日各一个），另有{r['technical_precheck_extra_scenarios']}个串并行技术重复场景。第1轮还有汇总字段错误前已计算但未保留的2个技术场景，单列于技术恢复记录，不算新配置或新一轮。旧登记控制复测仍保留旧身份，不增加登记候选数。

## 完整结果

| 身份 | 参数/模式 | 434日净收益 | 434日年化 | 434日回撤 | 434日频率中位/达标窗口 | 原中心全部门 | 415日净收益 | 415日回撤 | 415收益优于 | 415回撤更小 | 中心联合 |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- | --- | --- |
'''
    for row in r['rows']:
        a,b=row['runs']['full'],row['runs']['s011_common']
        text+=f"| {row['candidate_id']} | {row['parameters']} | {a['net_return']:.4%} | {a['cagr']:.4%} | {a['dd']:.4%} | {a['frequency_median']:.1f}/{a['frequency_good']}/{a['frequency_windows']} | {a['center_pass']} | {b['net_return']:.4%} | {b['dd']:.4%} | {b['return_superior']} | {b['dd_superior']} | {row['both_center_pass']} |\n"
    text+='''
## 证据、范围与下一步

全部配置由Optuna管理提议及回填，正式账户通过公共TDR完整执行；没有用价格标签或预测误差替代账户。每个窗口独立10万元、零持仓，标准单边0.1%、1%限价买入、市价退出、期末估值不强平。最大回撤包含初始本金；434日375个完整60日频率窗，至少338窗达标且中位数至少6。

415日收益严格大于0.9158029150000013且最大回撤严格小于0.07248663749114126，使用未四舍五入值；两者与原434日全部中心目标AND。原32点及费用压力尚未执行时仅称中心，不称合格。未设置年度、预测或额外回撤门。

原开发池及预热、固定S011比较基线和现有ETF数据范围保持。全部历史已被多轮观察，搜索和两个窗口高度重叠，不是独立验证。正式日价格区间、不考虑容量、历史17:30供应商发布链等已知限制保留。研究目标追求合格候选；预算不是合格保证。

每一配置的两个完整账户、完整结果、实际源码和协议显式关联正式报告。原历史证据和资格不修改。按有依据的问题继续当前10轮预算；若出现完整中心双优，优先转入原参数扰动、费用压力和证据验收。冻结、PTE及生产另行批准，不在此范围。
'''
    (here/'report.md').write_text(text,encoding='utf-8',newline='\n')
    refs=[EvidenceRef.from_dict(x) for x in read(here/'others/protocol_refs.json')]
    refs += [EvidenceRef.from_dict(x['evidence']) for x in r['rows']]
    refs.append(material(ex,'round_results',here/'others/results.json'))
    refs.append(material(ex,'round_closeout_source',Path(__file__)))
    if r['round']==1:
        refs.append(material(ex,'signal_checks',HOME/'others/signal_checks.json'))
    ref=publish_evidence(context(),ExperimentReportWrite(ex,sha256((here/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs)))
    check=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(ex,ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status.value=='PASS',check.issues
    save(here/'others/publication_validation.json',{'status':check.status.value,'report':ref.to_dict(),'validation':check.to_dict()})
    progress=[]
    for folder in sorted((ROOT/'research/S015/experiments').glob('EX0*')):
        path=folder/'others/results.json'
        if path.exists():
            value=read(path)
            if isinstance(value,dict) and 'account_scenarios' in value:
                progress.append({'experiment':folder.name,'round':value['round'],'configurations':value['new_configurations'],
                    'scenarios':value['account_scenarios'],'center_qualified':value['qualified_centers']})
    save(HOME/'others/budget_progress.json',{'maximum_rounds':10,'completed_rounds':progress,'remaining':10-len(progress)})
    print({'round':r['round'],'report':'PASS','remaining':10-len(progress)},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('design','close'))
    parser.add_argument('--round',type=int)
    parser.add_argument('--experiment')
    parser.add_argument('--judgment')
    a=parser.parse_args()
    if a.mode=='design':
        design(a.round)
    else:
        close(a.experiment,a.judgment)
