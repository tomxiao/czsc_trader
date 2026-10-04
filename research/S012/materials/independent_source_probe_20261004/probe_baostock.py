from pathlib import Path
import sys,socket,json
import pandas as pd
root=Path.cwd();sys.path.insert(0,str(next((root/'.tmp/s012/baostock').glob('*.whl'))));socket.setdefaulttimeout(20)
import baostock as bs
out=root/'.tmp/s012/independent';out.mkdir(exist_ok=True);records=[]
login=bs.login();print('login',login.error_code,login.error_msg,flush=True)
try:
 if login.error_code=='0':
  for day in ['2020-06-10','2020-09-17','2023-07-07']:
   for freq in ['5','d']:
    fields='date,time,code,open,high,low,close,volume,amount,adjustflag' if freq=='5' else 'date,code,open,high,low,close,volume,amount,adjustflag'
    r=bs.query_history_k_data_plus('sh.518850',fields,start_date=day,end_date=day,frequency=freq,adjustflag='3');rows=[]
    while r.error_code=='0' and r.next():rows.append(r.get_row_data())
    frame=pd.DataFrame(rows,columns=r.fields);frame.to_parquet(out/f'baostock_518850_{day}_{freq}.parquet');item={'source':'baostock','day':day,'frequency':freq,'error_code':r.error_code,'error_message':r.error_msg,'rows':len(frame),'head':frame.head(3).to_dict('records')};records.append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
 else:records.append({'source':'baostock','status':'LOGIN_FAILED','error':login.error_msg})
finally:
 bs.logout();(out/'baostock_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
