from datetime import datetime,timezone,timedelta
import json
from common import ROOT,RUNS,context,save, PROTOCOLS
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef

research=context()
authorization={'source':'当前会话真实用户明确批准',
    'user_answer':'批准，请你主导推进阶段三',
    'recorded_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
    'role':'RSCH','stage_three_authorized':True,'stage_four_authorized':False,
    'reviewed_delivery':json.loads((ROOT/'research/S013/materials/stage2_components_reference_20261007.json').read_text(encoding='utf-8')),
    'reviewed_proposal':['区间回归完整策略','增加lag1自相关状态确认，检验真实增量','增加退出和损失控制，检验收益与保护权衡'],
    'economic_mandate':json.loads((ROOT/'research/S013/materials/stage1_mandate_reference_r2_20261007.json').read_text(encoding='utf-8')),
    'autonomy':'研究员主导方法、参数域、预算、调度和停止判断，保存完整证据及反证',
    'explicit_exclusions':['其他批次研究内容','新增数据源或依赖','阶段四交付','冻结','生产变更','合并master','tag','推送']}
content=(json.dumps(authorization,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
(ROOT/'research/S013/materials/stage3_authorization_20261007.json').write_bytes(content)
ref=publish_evidence(research,MaterialEvidenceWrite(ExperimentRef('S013','EX003_20261007'),
    'stage3-authorization',content,'application/json','json'))
save('authorization_reference.json',ref.to_dict(), directory=PROTOCOLS)
print('S013 STAGE_THREE_AUTHORIZATION_PUBLISHED')
