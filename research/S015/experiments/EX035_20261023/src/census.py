"""Outcome-blind inventory and causal checks of the price information dictionary."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,importlib.util,json
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,validate_experiment,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;EX=ExperimentRef('S015',HERE.name)
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
def material(p):return publish_evidence(context(),MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def data():
    r=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/protocol_refs.json')['study.py']);r.resolve(ROOT)
    p=BASE/'EX026_20261023/src/study.py';assert sha256(p.read_bytes()).hexdigest()==r.sha256
    old=module(p,'authenticated_ex026');refs=old.sources();adj,raw,bars,rules,ids=old.inputs(refs)
    for f in (adj,raw,bars):f.attrs={}
    return adj,raw,bars,{'loader':r.to_dict(),'source_inputs':{k:v.to_dict() for k,v in refs.items()},'identities':ids}
def prepare():
    assert not (HERE/'others/protocol_refs.json').exists()
    f=module(HERE/'src/features.py','dictionary_only')
    save(HERE/'protocols/signal_dictionary.json',{'families':f.FEATURES,'signals':f.METADATA,'purpose':'普查时不查看新特征与收益关系；先固定表达，不挑选赢者。'})
    paths=[HERE/'protocols/research_plan.md',HERE/'protocols/signal_dictionary.json',HERE/'src/features.py',Path(__file__)]
    refs={p.name:material(p).to_dict() for p in paths};save(HERE/'others/protocol_refs.json',refs)
    repo=RepositoryContext.discover(ROOT);intent=read(ROOT/'research/registrations/S015/family.json')['research_intent']
    intent.update(current_experiment=EX.to_dict(),current_phase='阶段二第一性原理重建：已冻结研究计划，先普查价格信息、再验证组件职责',experiment_budget={'unlimited':True,'authorized':None,'completed':0,'remaining':None,'source':refs['research_plan.md']},next_gate='在已获准数据/目标下自主完成阶段二，不限实验轮数；阶段三仍在组件交付后另批。')
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户明确批准重建价格信号普查及组件验证设计，并返回阶段二自主执行，实验预算不限制。')
    print('PLAN_AND_DICTIONARY_FROZEN',flush=True)
def run():
    assert not (HERE/'others/census.json').exists()
    refs=read(HERE/'others/protocol_refs.json')
    for name in ('features.py','census.py'):assert EvidenceRef.from_dict(refs[name]).resolve(ROOT).read_bytes()==(HERE/'src'/name).read_bytes()
    f=module(HERE/'src/features.py','price_dictionary');adj,raw,bars,inputs=data();x=f.build(adj,raw,bars)
    columns=[c for v in f.FEATURES.values() for c in v];assert len(columns)==24 and len(set(columns))==24
    assert len(x)==434 and x.position.tolist()==list(range(434)) and x.date.is_unique
    assert np.isfinite(x[columns].to_numpy(float)).all()
    x.to_csv(HERE/'others/features.csv',index=False);save(HERE/'others/input_refs.json',inputs)
    counts=0
    for i in range(434):
        a=f.build(adj.iloc[:76+i],raw.iloc[:76+i],bars.iloc[:8*(i+1)]).iloc[-1]
        pd.testing.assert_series_equal(a,x.iloc[i],check_names=False,rtol=1e-11,atol=1e-12);counts+=1
    pairs=[];corr=x[columns].corr(method='spearman')
    for i,a in enumerate(columns):
        for b in columns[i+1:]:pairs.append({'a':a,'b':b,'spearman':float(corr.loc[a,b]) if pd.notna(corr.loc[a,b]) else None})
    pairs.sort(key=lambda z:abs(z['spearman']) if z['spearman'] is not None else -1,reverse=True)
    out={'rows':434,'families':6,'expressions':24,'prefix_checks':counts,'outcome_checks':0,'columns':{},'correlations':pairs,'note':'相关性只诊断重复，不作为经济硬门或自动删信号。'}
    for c in columns:
        s=x[c];out['columns'][c]={'finite_n':int(np.isfinite(s).sum()),'unique_n':int(s.nunique()),'zero_n':int((s==0).sum()),'min':float(s.min()),'max':float(s.max()),'mean':float(s.mean()),'std':float(s.std()),'quantiles':{str(q):float(s.quantile(q)) for q in (.05,.25,.5,.75,.95)}}
    save(HERE/'others/census.json',out);print({'rows':434,'signals':24,'prefix_checks':counts,'outcome_selection':0},flush=True)
def publish():
    r=read(HERE/'others/census.json');dic=read(HERE/'protocols/signal_dictionary.json');out=['# S015 价格行为六维信号普查','', 'Status: COMPLETED','',
      '已冻结研究计划和24个连续价格表达，再完成434日覆盖与逐日前缀核验。此实验没有查看新信号的收益效果，没有新增有效组件或候选。用户授权阶段二不限轮数，接续组件验证，不进入阶段三。','',
      '所有数据来自既有认证快照，日线75日预热、开发434日，30分钟每天8根。没有新增源或日期。零分母按字典定义中性值；不补缺行。高低点在同根内部的先后未知，不能解释成逐笔交易行为。','',
      '## 信号字典与数据普查','', '| 家族/信号 | 定义 | 唯一值数 | 零值数 |','| --- | --- | ---: | ---: |']
    for fam,cols in dic['families'].items():
        for c in cols:
            v=dic['signals'][c];out.append(f"| {fam}/{c} | {v['definition']} | {r['columns'][c]['unique_n']} | {r['columns'][c]['zero_n']} |")
    out+=['','## 重复信息与边界','', '全部24列有434条有限值；434个逐日截断重算与完整数据特征一致。相关性仅揭示表达重叠，不证明有效性或独立信息。最大的10组绝对秩相关如下：','','| 表达A | 表达B | Spearman |','| --- | --- | ---: |']
    for p in r['correlations'][:10]:out.append(f"| {p['a']} | {p['b']} | {p['spearman']:.4f} |")
    out+=['','日OHLC和30分钟OHLC只提供价格路径的粗观测，不证明主动资金、订单簿深度或投资者身份；历史发布时点与HFQ版本可得性仍是既有局限。','',
      '## 后续验证设计','', '按[研究计划](protocols/research_plan.md)和[信号字典](protocols/signal_dictionary.json)开展入场收益、入场风险、未来持仓浮亏、同仓位持有价值和成交概率的分职责验证。先以纯价格基线检验家族增量，同时保留历史量价参考；逐信号训练内三分位提供可解释性，前推训练严格清除尚未知标签。','',
      '此处只完成定义与可计算性，不将24个表达称为24个有效或独立组件。历史实验资格不变。原双窗口收益、回撤、频率和稳健性目标不变，合格策略0。已有434日已反复观察，任何重切均非独立验证。','',
      '证据：[普查结果](others/census.json)、[特征表](others/features.csv)、[输入认证](others/input_refs.json)、[定义源码](src/features.py)。']
    (HERE/'report.md').write_text('\n'.join(out)+'\n',encoding='utf-8',newline='\n')
    refs=[];materials={}
    inp=read(HERE/'others/input_refs.json')
    for v in [inp['loader'],*inp['source_inputs'].values()]:refs.append(EvidenceRef.from_dict(v))
    for sub in ('src','protocols','others'):
        for p in sorted((HERE/sub).glob('*')):
            if p.suffix in ('.py','.json','.csv','.md'):
                ref=material(p);materials[f'{sub}/{p.name}']=ref.to_dict();refs.append(ref)
    rr=publish_evidence(context(),ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    check=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert check.status.value=='PASS',check.issues
    save(HERE/'others/published_refs.json',{'report':rr.to_dict(),'materials':materials,'validation':check.to_dict()});print('CENSUS_PUBLISHED',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run','publish']);{'prepare':prepare,'run':run,'publish':publish}[p.parse_args().mode]()
