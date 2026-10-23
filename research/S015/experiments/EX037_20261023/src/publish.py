"""Preserve both functional forms before role-specific attribution."""
from hashlib import sha256
from followup import ROOT,HERE,EX,read,save,context,material
from czsc_trader.application import RepositoryContext,publish_evidence,validate_experiment
from czsc_trader.research_tools import EvidenceRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope
def main():
    assert not (HERE/'others/published_refs.json').exists();assert read(HERE/'others/independent_audit.json')['status']=='PASS'
    r=read(HERE/'others/results.json');families=['direction_efficiency','up_down_asymmetry','location_response','volatility_transition','temporal_order','scale_relationship','all']
    out=['# S015 强基线与非线性表达反证','', 'Status: COMPLETED','',
      '用户不限轮数阶段二授权下的后续实验。已见EX036结果后，固定对全部六家族及整体作对称检验，不仅尝试优胜家族。新增126个规格、504次前推拟合；没有新数据、账户或策略候选。','',
      '线性：在原量价基线（含pressure，持有标签含已知浮盈）中增加家族，检验真正嵌套增量。分箱：同一基线加入训练期三分位的两个哑变量，支持非单调关系；边界训练期确定，测试固定。正则仍为10。切分、标签清除、金额及执行语义全部继承EX036。','',
      '## 全部增量结果','', '数字为相对历史量价基线的MSE下降百分比，正数改善，不是收益。','', '| 标签/表达 | 方向效率 | 上下不对称 | 位置响应 | 波动转换 | 时间顺序 | 尺度关系 | 全部 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for t,z in r.items():
        for mode in ('linear','binned'):out.append('| '+f'{t}/{mode} | '+' | '.join(f"{100*z[f'{mode}/{f}']['mse_gain_vs_legacy']:.3f}%" for f in families)+' |')
    out+=['','## 研究判断与续研理由','',
      '时间顺序在线性net3用途上保留2.1652%的嵌套增量，四折均有小幅改善；入场日用途并未改善，不能从三日预测外推为识别买入当天亏损。分箱时间顺序反而变差，支持受到表达方式限制。','',
      '波动转换在线性loss3/drawdown3上分别改善2.8609%/2.8889%，尺度关系在分箱表达上改善4.5362%/3.4417%；但风险模型误差减少并不等于减少亏损时不会漏掉更多盈利，尚需用途反证。持有/退出预测增量普遍较弱，成交失败样本稀少。','',
      '这些是在大量相关比较中出现的开发池线索，探索性区间不校正选择历史，不能直接判定为稳定可交易组件。单一表达/家族有效不代表全部堆叠有效；全体分箱模型在全部九目标上恶化。','',
      '下一实验将检验有利用途的逐信号归因、删一信号反证，以及仅用训练信息确定的风险参与规则。必须报告省下的亏损与遗漏盈利，不用整折排序当实时策略。后续仍在阶段二，不构造连续账户或放宽目标。','',
      '独立审计通过76,844项核对：504新增拟合、108基线复现、864组训练边界、全部2922行预测及用途分母；方法的有效性不由审计PASS代替。','',
      '证据：[协议](protocols/expression_checks.json)、[结果](others/results.json)、[预测](others/predictions.csv)、[分箱边界](others/cutpoints.json)、[独立审计](others/independent_audit.json)。']
    (HERE/'report.md').write_text('\n'.join(out)+'\n',encoding='utf-8',newline='\n');refs=[];materials={};inp=read(HERE/'others/input_refs.json')
    for v in [*inp['evidence'].values(),inp['dictionary']]:refs.append(EvidenceRef.from_dict(v))
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix in ('.py','.json','.csv','.md'):
                ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    v=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert v.status.value=='PASS',v.issues
    save(HERE/'others/published_refs.json',{'report':rr.to_dict(),'materials':materials,'validation':v.to_dict()});print('EX037_PUBLISHED',flush=True)
if __name__=='__main__':main()
