"""Replace the zero-result technical attempt with fully declared strategy state."""
from datetime import date
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig

ROOT=Path.cwd()
BATCH=ROOT/'research/S019'
OLD=BATCH/'experiments/EX042_20261110'
WORK=BATCH/'experiments/EX043_20261110'
def read(path):
    return json.loads(path.read_bytes())
def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

assert not WORK.exists()
prior=read(OLD/'others/results.json')
assert prior['status']=='STOPPED' and not prior['accounts']
repo=RepositoryContext.discover(ROOT)
batch=d.ResearchBatchRef('S019')
intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
assert intent['joint_search_budget']['used_rounds']==4 and intent['joint_search_budget']['remaining_rounds']==6
ctx=create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
exp=create_experiment(ctx,ExperimentRequest('退出机制辨别：完整状态声明后的19配置对照',
    '承接EX042零有效账户的技术尝试，补齐状态契约，以新身份执行同一19配置机制问题。',date(2026,11,10)))
assert exp.resolve(ROOT)==WORK
(WORK/'src/setup.py').write_bytes(Path(__file__).read_bytes())
spec=read(OLD/'protocols/specs.json')
spec['candidate_start']=641
schema=read(OLD/'others/hard_center_definition.json')['state_schema']
schema['cycle_fields'].extend([{'key':'risk_fraction','value_type':'float','nullable':False},
    {'key':'breach_count','value_type':'int','nullable':False}])
spec['state_schema']=schema
save(WORK/'protocols/specs.json',spec)
plan=(OLD/'protocols/plan.md').read_text(encoding='utf-8')
plan+='\n## 技术替代记录\n\nEX042首次三控制执行因遗漏两个状态字段声明而失败，未产生有效账户；并行异常呈现为BrokenProcessPool，八个未知任务保留。清单容器类型修正后仍发生同类失败，故保留全部旧身份C0622—C0640。本次补齐risk_fraction(float)与breach_count(int)声明，沿用完全相同19个参数配置与策略源码，改用C0641—C0659，并通过三条hard原账户parity先核金融行为。EX042不扣研究轮次，本轮仍为原总第5轮、本次第1轮；6轮额度保持至本轮正常收口。\n\n授权见[原始批准](../../EX042_20261110/protocols/authorization.md)，技术诊断见[失败诊断](../../EX042_20261110/others/technical_failure_diagnosis.json)。\n'
(WORK/'protocols/plan.md').write_bytes(plan.encode())
save(WORK/'protocols/technical_predecessor.json',{'experiment':'EX042_20261110',
    'results':'research/S019/experiments/EX042_20261110/others/results.json',
    'valid_accounts':0,'unknown_tasks':8,'debited_rounds':0,
    'authorization':read(OLD/'others/authorization.json'),
    'financial_parameters_unchanged':True,'strategy_source_unchanged':True,
    'definition_change':'Add the two already-used cycle state fields to the explicit SRT state schema.'})
for name in ('strategy.py','semantic_audit.py'):
    (WORK/'src'/name).write_bytes((OLD/'src'/name).read_bytes())
(WORK/'report.md').write_bytes('# S019退出机制对照\n\nStatus: IN_PROGRESS\n\n补齐状态声明后执行原19配置；额度保持。\n'.encode())
intent.update(stage='STAGE_TWO',mechanism_research_status='ROUND_ONE_PREPARING',active_experiment=exp.to_dict(),
    technical_failed_experiments=[*intent.get('technical_failed_experiments',[]),'EX042_20261110'],
    active_round_budget={'round':5,'allocated_mechanism_rounds':6,'mechanism_round':1,'remaining_after_completion':5},
    next_action='补齐状态字段声明后以新身份执行同一19配置，三个原控制严格等价后继续12进程结构对照。')
update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
    reason='保留零有效账户的技术失败尝试，补齐研究定义状态契约并换新身份，原授权/方案/六轮额度保持。')
print('EX043_CREATED',len(spec['specs']),flush=True)
