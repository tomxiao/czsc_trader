"""Assemble the first-principles stage-two panel without advancing strategies."""
import json
from pathlib import Path
from hashlib import sha256
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,assemble_delivery,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def published(n):return read(BASE/f'EX{n:03}_20261023/others/published_refs.json')
def ref(n,k):
    r=EvidenceRef.from_dict(published(n)['materials'][k]);r.resolve(ROOT);return r
def data(n,k='others/results.json'):return read(ref(n,k).resolve(ROOT))
def test(n,tid,protocol,status,explanation):
    return d.ComponentTestResult(tid,f'EX{n:03}_20261023',ref(n,protocol),status,explanation,(ref(n,'others/results.json'),ref(n,'others/independent_audit.json')))
def entry(cid,n,source,role,tests,judgment):
    return d.ComponentEntry(cid,d.ExperimentDefinitionRef(ref(n,source),'run'),role,
      '实际成交后净收益、入场日买费后损益、三日亏损/收盘浮亏、同仓位延迟卖出增量；按各测试职责区分',
      'h1/h3/h5、入场日与持有1/3日；标签实际已知日净化',
      '训练均值、旧价格/量价基线，4折前推；固定表达/归因/独立用途对照',
      'T收盘信息、T+1执行；历史发布时点及价格修订PIT未认证',
      'HFQ_RESEARCH；公共TXE原1%限价、DAILY_RANGE_V3与原费用/限价保护',
      '已反复观察434日；重叠独立事件不是账户；区间和分段是诊断而非新经济硬门',judgment,tuple(tests))
def main():
    repo=RepositoryContext.discover(ROOT);batch=ResearchBatchRef('S015');ctx=create_research_context(repo,batch,resources=ExecutionResources(1,1,13))
    assert not (HERE/'others/integrated_delivery.json').exists()
    for n in range(35,42):assert published(n)['validation']['status']=='PASS'
    receipt=read(ROOT/'research/S015/deliveries/COMPONENTS/11/receipt.json');p=ROOT/'research/S015/assets/deliveries/COMPONENTS/11/delivery.json'
    assert sha256(p.read_bytes()).hexdigest()==next(v['sha256'] for v in receipt['files'] if v['path']=='delivery.json')
    old=d.ComponentPanel.from_dict(read(p)['content']['payload']);assert len(old.components)==26 and sum(len(c.tests) for c in old.components)==169
    family=data(35,'protocols/signal_dictionary.json')['families'];r36=data(36);r37=data(37);r38=data(38);r39=data(39);entries=[]
    for name in [*family,'all']:
        tests=[]
        for target in r36:
            z=r36[target]['models'][name];gain=z['mse_gain_vs_price']
            status=d.ComponentTestStatus.INSUFFICIENT_DATA if gain>0 or target=='fill' else d.ComponentTestStatus.INEFFECTIVE
            tests.append(test(36,f'{name}-{target}-price-linear','protocols/component_validation.json',status,f'固定表达相对价格基线误差变化{gain:.8f}；正向误差观察尚不足以确证决策用途，负向仅否定本次改善用途；fill仅7个未成交，不宣称总体无信息。'))
            for mode in ('linear','binned'):
                z=r37[target][f'{mode}/{name}'];gain=z['mse_gain_vs_legacy'];status=d.ComponentTestStatus.INSUFFICIENT_DATA if gain>0 or target=='fill' else d.ComponentTestStatus.INEFFECTIVE
                tests.append(test(37,f'{name}-{target}-legacy-{mode}','protocols/expression_checks.json',status,f'旧量价基线上固定{mode}表达误差变化{gain:.8f}；这只是职责筛选证据；后续用途归因单列，不能以误差正负替代经济门槛。'))
        entries.append(entry('price_census_'+name,36,'src/validate.py','六维普查表达的九职责筛选：'+name,tests,'保留全部线性/分箱结果；不得把27个相关比较视为27个独立信号。关键用途由后继归因证据限定。'))
    supported={'net3/temporal_order/linear','loss3/volatility_transition/linear','drawdown3/volatility_transition/linear'}
    for case,variants in r38.items():
        tests=[]
        for name,z in variants.items():
            status=d.ComponentTestStatus.NOT_APPLICABLE if name=='baseline' else d.ComponentTestStatus.INSUFFICIENT_DATA
            if name=='full' and case in supported:status=d.ComponentTestStatus.SUPPORTED
            elif name=='full' and case.startswith('loss3/scale_relationship'):status=d.ComponentTestStatus.INEFFECTIVE
            note='仅支持已见开发池中的三日条件筛选或风险辅助用途；不同职责不能互换，无稳定性/账户/独立机制保证。' if status==d.ComponentTestStatus.SUPPORTED else '固定归因观察；单项/删项结果不自动变成已确认组件，基线仅参照；尺度loss3全组虽改善误差但遗漏更多盈利、保留净额更差。'
            tests.append(test(38,case.replace('/','-')+'-'+name.replace('/','-'),'protocols/attribution.json',status,note))
        entries.append(entry('price_attribution_'+case.replace('/','_'),38,'src/attribution.py','用途及逐表达归因：'+case,tests,'SUPPORTED仅限full明确职责；所有变体、亏损/盈利机会成本和最强反证均保留。'))
    for name in ('path','volatility','combined'):
        tests=[]
        for target,zs in r39.items():
            status=d.ComponentTestStatus.SUPPORTED if (name,target) in {('path','net3'),('volatility','loss3')} else d.ComponentTestStatus.INSUFFICIENT_DATA
            if name=='volatility' and target=='hold3':status=d.ComponentTestStatus.INEFFECTIVE
            tests.append(test(39,f'standalone-{name}-{target}','protocols/standalone.json',status,
              '去掉旧涨跌/压力控制，信息并非仅修补旧模型；支持限于开发条件下指定筛选用途。末折仍亏损、块区间跨0，不能声称机制稳定。' if status==d.ComponentTestStatus.SUPPORTED else '独立表达固定检验，全部职责和四背景保留；不从有利子格倒造规则，不升级为稳定入场保护或退出。'))
        entries.append(entry('price_standalone_'+name,39,'src/standalone.py','移除旧控制后的独立信息用途：'+name,tests,'2个家族的用途线索；路径含方向信息，不能以无r1/r5列宣称与S011行为独立。'))
    # Final two experiment entries are appended from reviewed, explicit judgments.
    extra=read(HERE/'others/final_component_judgments.json')
    for item in extra:
        tests=[test(item['experiment'],q['id'],item['protocol'],d.ComponentTestStatus(q['status']),q['explanation']) for q in item['tests']]
        entries.append(entry(item['id'],item['experiment'],item['source'],item['role'],tests,item['judgment']))
    panel=d.ComponentPanel((*old.components,*entries),'第一性原理阶段二完成。价格路径三日筛选与波动风险辅助有用途受限证据；共同信息非独立策略机制，当前合格候选仍0。全部反证和补充合成/时序普查见报告。')
    report=(HERE/'others/stage2_synthesis.md').read_text(encoding='utf-8');refs=[]
    for n in range(35,42):
        doc=published(n);refs.extend(EvidenceRef.from_dict(v) for v in doc['materials'].values());refs.append(EvidenceRef.from_dict(doc['report']))
    for path in (Path(__file__),HERE/'others/final_component_judgments.json',HERE/'others/stage2_synthesis.md'):
        refs.append(publish_evidence(ctx,MaterialEvidenceWrite(ExperimentRef('S015',HERE.name),path.stem,path.read_bytes(),{'.py':'text/x-python','.json':'application/json','.md':'text/markdown'}[path.suffix],path.suffix[1:])))
    assembled=assemble_delivery(repo,d.DeliveryDefinition(batch,d.DeliveryStage.COMPONENTS,12,(d.DeliveryReference.from_dict(receipt['reference']),)),d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(dict.fromkeys(refs))))
    assert assembled.validation.status.value=='PASS',assembled.validation.issues
    intent=read(ROOT/'research/registrations/S015/family.json')['research_intent'];original_candidates=intent.get('current_candidates')
    intent.update(current_components=assembled.receipt.reference.to_dict(),current_experiment=ExperimentRef('S015','EX041_20261023').to_dict(),
      experiment_budget={'unlimited':True,'authorized':None,'completed':7,'remaining':None,'source':ref(35,'protocols/research_plan.md').to_dict()},
      current_phase='第一性原理阶段二完成：信号普查、职责验证、归因反证及固定合成已交付；2个信息家族有限用途，资格0',
      qualified_candidate_count=0,pending_selection_candidate_count=0,pending_freeze_candidate_count=0,
      next_gate='当前阶段二额度不限且没有耗尽；本轮因关键问题已得到证据收口。请用户决定阶段三固定策略账户研究、补证或调整目标。未经阶段三授权不构建完整账户。')
    assert intent.get('current_candidates')==original_candidates
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='完成用户批准的第一性原理价格行为研究重建和不限轮数阶段二；保留全部正负证据、历史候选与原目标，交付有限用途组件。')
    save(HERE/'others/integrated_delivery.json',{'reference':assembled.receipt.reference.to_dict(),'validation':assembled.validation.to_dict(),'preserved_entries':26,'new_entries':len(entries),'total_entries':len(panel.components),'preserved_tests':169,'new_tests':sum(len(c.tests) for c in entries),'total_tests':sum(len(c.tests) for c in panel.components),'new_supported_tests':sum(t.status==d.ComponentTestStatus.SUPPORTED for c in entries for t in c.tests),'qualified_candidates':0,'experiments_completed':7,'budget_unlimited':True})
    print('COMPONENTS12_PASS',len(panel.components),sum(len(c.tests) for c in panel.components),flush=True)
if __name__=='__main__':main()
