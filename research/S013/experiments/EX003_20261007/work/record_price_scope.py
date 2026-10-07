from datetime import datetime,timezone,timedelta
import json
from common import ROOT,WORK,context,save
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef

record={'source':'当前会话真实用户选项答复',
    'question':'S013现有账户未单独计入派息等权益事件，这会影响BuyHold及策略收益比较。阶段三如何处理这项口径？现有机制搜索可以继续，但更改平台账本属于DEV范围，需要你的明确授权。',
    'user_answer':'先完成现口径研究，将权益事件影响列为阶段四前待解决项（推荐）',
    'decision':'继续完成现有公共SRT/TXE价格与现金账本的阶段三研究；保持费用、基准、年度回撤和频率约定。',
    'stage_four_precondition':'先查明权益事件影响并解决账户口径，再复核实际绩效。',
    'dev_write_authorized':False,'stage_four_authorized':False,
    'qualification_scope':'当前价格及现金账本口径，不宣称完整含派息等权益事件净收益。',
    'recorded_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')}
content=(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
(ROOT/'research/S013/materials/stage3_price_scope_confirmation_20261007.json').write_bytes(content)
ref=publish_evidence(context(),MaterialEvidenceWrite(ExperimentRef('S013','EX003_20261007'),
    'price-account-scope-confirmation',content,'application/json','json'))
save('price_scope_reference.json',ref.to_dict())
print('CONFIRMED_PRICE_SCOPE_PUBLISHED')
