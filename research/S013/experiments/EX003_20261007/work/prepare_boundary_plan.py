import json
from datetime import datetime,timezone,timedelta
from common import WORK,save,context
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef

rows=json.loads((WORK/'search_results.json').read_text(encoding='utf-8'))['rows']
center=next(r for r in rows if r['candidate_id']=='C0205')
p=center['parameters']
configurations=[]
for window in (120,150,180):
    for entry in (.80,.85,.90,.95):
        for hold in (7,8,9,10,11,12):
            configurations.append({'label':f'boundary-window-{window}-entry-{entry}-hold-{hold}',
                'parameters':dict(p,range_window=window,entry=entry,max_hold=hold)})
for acf in (-.5,-.4,-.3,-.2,-.1,0,.1,.2):
    configurations.append({'label':f'center-acf-{acf}','parameters':dict(p,acf_min=acf)})
for loss in (.005,.01,.02,.03,.05,.08):
    configurations.append({'label':f'center-loss-{loss}','parameters':dict(p,stop_loss=loss)})
for trail in (.01,.02,.03,.05,.08):
    configurations.append({'label':f'center-trail-{trail}','parameters':dict(p,trailing_stop=trail)})
for momentum in (-.10,-.05,-.025,0,.025,.05):
    configurations.append({'label':f'center-momentum-{momentum}','parameters':dict(p,momentum_min=momentum)})
for exit_level in (.95,.975,1.0):
    configurations.append({'label':f'center-exit-{exit_level}','parameters':dict(p,exit=exit_level)})
note={'source_center':'C0205','center_metrics':{k:center[k] for k in ('net_cagr','closed_trades','annual_dd_margins')},
    'reason':'入场0.85、区间120日均在扩展上边界，净收益只差0.6826个百分点；继续外扩与局部联合对照，不以既定提议预算停止。',
    'hypothesis_for_direction_filter':'ACF高值也可来自持续下跌；20日动量仅用于区分价格方向，不将其当成已证实Alpha。阶段二已保留该组件和控变量证据。',
    'domains':{'range_window':[120,150,180],'entry':[.8,.85,.9,.95],'max_hold':[7,8,9,10,11,12],
        'exit':[.95,.975,.99,1.],'acf_min':[-.5,-.4,-.3,-.2,-.1,0,.1,.2],
        'loss':[.005,.01,.02,.03,.05,.08],'trailing':[.01,.02,.03,.05,.08],
        'momentum20_min':[-.10,-.05,-.025,0,.025,.05]},
    'configurations':len(configurations),'economic_gates_unchanged':True,
    'recorded_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')}
save('boundary_search_plan.json',{'name':'boundary-and-controls','decision':note,'configurations':configurations})
ref=publish_evidence(context(),MaterialEvidenceWrite(ExperimentRef('S013','EX003_20261007'),
    'boundary-expansion-and-controls',(WORK/'boundary_search_plan.json').read_bytes(),'application/json','json'))
save('boundary_plan_reference.json',ref.to_dict())
print('BOUNDARY_AND_CONTROL_PLAN_READY',len(configurations))
