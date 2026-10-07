from datetime import datetime,timezone,timedelta
import json
from common import ROOT,WORK,BASE,save,cache_read,cache_write,context
from economics import summarize
from search import configuration_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef

rows=json.loads((WORK/'search_results.json').read_text(encoding='utf-8'))['rows']
if not any(r['candidate_id']=='C0001' for r in rows):
    _,result=cache_read(ROOT/'.tmp/s013-stage3/precheck.pkl.gz')
    row=summarize(result)
    row.update(parameters=BASE,config_hash=configuration_hash(BASE),search='precheck',trial=0,status='SUCCEEDED')
    rows.append(row)
    cache_write(ROOT/'.tmp/s013-stage3/C0001.pkl.gz',result)
    save('search_results.json',{'rows':rows,'resources':{'max_workers':8,'native_threads':1,'request_workers':1}})
configurations=[]
for entry in (.25,.30,.35,.40,.45,.50,.60,.70):
    for hold in (3,4,5,6,8,10):
        configurations.append({'label':f'entry-{entry}-hold-{hold}',
            'parameters':dict(BASE,entry=entry,max_hold=hold)})
for entry in (.80,.85):
    for hold in (4,6,8):
        configurations.append({'label':f'expanded-entry-{entry}-hold-{hold}',
            'parameters':dict(BASE,entry=entry,exit=.95,max_hold=hold)})
save('holding_grid_plan.json',{'name':'holding-grid','reason':'首个7.42%账户频率不足，初始搜索未覆盖其局部联合持有期；检验频率与净收益冲突及入场上边界',
    'configurations':configurations})
valid=[r for r in rows if r['status']=='SUCCEEDED']
note={'recorded_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
    'initial_successful_search_evaluations':sum(r['search'].startswith('initial-') for r in valid),
    'initial_qualifying_configurations':sum(r['qualified'] for r in valid),
    'decision':'继续阶段三：固定持有期对照54项，扩展Optuna联合搜索，各机制64次提议',
    'expanded_domains':{'entry':[.05,.85],'exit':'max(0.50, entry+gap), gap 0.05..0.40, upper0.99',
        'max_hold':[1,30],'range_window':[30,40,60,90,120],'acf_min':[-.60,.50],
        'stop_loss':[.005,.18],'trailing_stop':[.01,.20],'cooldown':[0,5]},
    'explanation':'扩大高入场阈值增加候选触发机会，缩短持有期直接检验费用及频率代价；改变区间长度检验机会定义对当前窗口的依赖；更紧损失控制检验下跌年修复能力',
    'history_scope':'扩展窗口只读取同标的实际需要的最小历史，不计入开发池统计',
    'no_economic_target_change':True,'max_workers':8,'native_threads':1,
    'price_role_limitation':'复权与未复权收益差异及未独立计入权益事件已保存，未改变既定基准合同'}
note['dependency_binding']='初始评价的依赖版本在平台环境身份中保存；后续请求显式声明numpy/pandas/strategy-runtime版本。初始入选配置交接前将用显式依赖新身份复算，保持原评价证据。'
save('expansion_decision.json',note)
research=context()
ref=publish_evidence(research,MaterialEvidenceWrite(ExperimentRef('S013','EX003_20261007'),
    'search-domain-expansion',(WORK/'expansion_decision.json').read_bytes(),'application/json','json'))
save('expansion_reference.json',ref.to_dict())
print('FOLLOWUP_PLANS_AND_EXPANSION_EVIDENCE_READY')
