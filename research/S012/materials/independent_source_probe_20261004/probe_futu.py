from pathlib import Path
import json,logging.handlers
from unittest.mock import patch
root=Path.cwd();out=root/'.tmp/s012/independent';factory=logging.handlers.TimedRotatingFileHandler
# Redirect only SDK log creation; never redirect system profile variables.
with patch('logging.handlers.TimedRotatingFileHandler',side_effect=lambda filename,*a,**kw:factory(out/'futu_sdk.log',*a,**kw)):
 from futu import OpenQuoteContext,KLType,AuType,RET_OK
ctx=OpenQuoteContext(host='127.0.0.1',port=11111);records=[]
try:
 for day in ['2020-06-10','2020-09-17','2023-07-07']:
  ret,data,key=ctx.request_history_kline('SH.518850',start=day,end=day,ktype=KLType.K_1M,autype=AuType.NONE,max_count=1000)
  item={'source':'futu','day':day,'return_code':ret}
  if ret==RET_OK:
   data.to_parquet(out/f'futu_518850_{day}_1m.parquet');item.update(rows=len(data),head=data.head(3).to_dict('records'),has_next_page=key is not None)
  else:item['error']=str(data)
  records.append(item);print(json.dumps(item,ensure_ascii=False,default=str),flush=True)
  if ret!=RET_OK:break
finally:
 ctx.close();(out/'futu_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
