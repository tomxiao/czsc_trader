"""Offline SDK argument probe; no quote context and no network request."""
from pathlib import Path
from importlib.metadata import version
import json
import sys
import types
import socket

ROOT=Path(__file__).resolve().parents[5]
def blocked(*args,**kwargs):
    raise AssertionError('Network is forbidden in this offline probe')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
name='futu.common.ft_logger'
p=ROOT/'.venv/Lib/site-packages/futu/common/ft_logger.py'
code=p.read_text(encoding='utf-8')
marker='__LogPathName__ = "com.futunn.FutuOpenD/Log"'
assert code.count(marker)==1
mod=types.ModuleType(name);mod.__file__=str(p);mod.__package__='futu.common'
sys.modules[name]=mod
exec(compile(code.replace(marker,'__LogPathName__ = '+repr(str(ROOT/'.tmp/s018-futu-enum-logs'))),str(p),'exec'),mod.__dict__)
import futu as ft
from futu.quote.quote_query import RequestHistoryKlineQuery
ft.SysConfig.enable_console_log(False)
rows=[]
for autype,session in [('HFQ','RTH'),('hfq','RTH'),('QFQ','RTH'),('qfq','RTH'),('None','RTH'),('hfq','N/A')]:
    result=RequestHistoryKlineQuery.pack_req(code='US.SOXX',start_date='2022-01-03',end_date='2026-10-30',
        ktype='K_DAY',autype=autype,fields=[ft.KL_FIELD.ALL],max_num=1000,conn_id=0,next_req_key=None,
        extended_time=False,session=session)
    rows.append({'autype':autype,'session':session,'autype_valid':ft.AuType.if_has_key(autype),
        'session_valid':ft.Session.if_has_key(session),'ret':result[0],'message':result[1],
        'serialized_bytes':len(result[2]) if result[2] is not None else None,'protocol_id':result[3]})
out={'scope':'Offline installed SDK pack_req only; no OpenQuoteContext, no market data, sockets blocked',
    'futu_version':version('futu-api'),'constants':{'NONE':ft.AuType.NONE,'FORWARD':ft.AuType.QFQ,
        'BACKWARD':ft.AuType.HFQ,'RTH':ft.Session.RTH,'DEFAULT_SESSION':ft.Session.NONE,'DAILY':ft.KLType.K_DAY},
    'cases':rows}
assert [x['ret'] for x in rows]==[-1,0,-1,0,0,0]
target=Path(__file__).resolve().parents[1]/'others/analysis_sdk_enum_probe.json'
target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
