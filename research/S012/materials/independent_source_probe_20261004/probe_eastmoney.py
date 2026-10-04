from pathlib import Path
import json,requests,concurrent.futures
root=Path.cwd();out=root/'.tmp/s012/independent';rows=[]
def fetch(spec):
 day,freq=spec;params={'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61','ut':'7eea3edcaed734bea9cbfc24409ed989','klt':freq,'fqt':'0','secid':'1.518850','beg':day.replace('-',''),'end':day.replace('-','')}
 try:
  r=requests.get('https://push2his.eastmoney.com/api/qt/stock/kline/get',params=params,timeout=20);r.raise_for_status();raw=r.json();(out/f'eastmoney_{day}_{freq}.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');bars=(raw.get('data') or {}).get('klines',[]);return {'source':'eastmoney','day':day,'frequency':freq,'rows':len(bars),'head':bars[:2]}
 except Exception as e:return {'source':'eastmoney','day':day,'frequency':freq,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for x in pool.map(fetch,[(d,f) for d in ['2020-06-10','2020-09-17','2023-07-07'] for f in ['5','101']]):rows.append(x);print(json.dumps(x,ensure_ascii=False),flush=True)
(out/'eastmoney_probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
