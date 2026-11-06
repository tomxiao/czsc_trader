from pathlib import Path
from hashlib import sha256
import sqlite3,json,pickle
root=Path.cwd();out=root/'.tmp/s001-v4-correction/inputs'
prod=Path('D:/CZSC-PTE/shared')
c=sqlite3.connect((prod/'state/runtime.db').as_uri()+'?mode=ro',uri=True);c.execute('pragma query_only=on')
d=json.loads(c.execute("select payload from decisions where account_id='s001-v1' order by generated_at desc limit 1").fetchone()[0]);c.close()
r=d['prepared_data_reference'];c=sqlite3.connect((prod/'data/market/assets.sqlite3').as_uri()+'?mode=ro',uri=True);c.execute('pragma query_only=on')
h,m=c.execute('select manifest_sha256,manifest from preparations where preparation_id=?',(r['preparation_id'],)).fetchone();assert sha256(m.encode()).hexdigest()==h==r['manifest_sha256'];entries=json.loads(m)
meta={'prepared_ref':r,'decision_id':d['decision_id'],'signal_date':d['signal_date'],'inputs':{}}
for e in entries:
 q=e['request'];name= ('calendar' if q['dataset']=='calendar.trading_sessions' else 'raw_daily' if q['dataset']=='etf.unadjusted_daily' else {'daily':'daily','30m':'m30','weekly':'weekly'}[q['frequency']])
 bh,b,acq=c.execute('select payload_sha256,payload,acquired_at from assets where asset_id=?',(e['asset_id'],)).fetchone();assert sha256(b).hexdigest()==bh
 f,i,w=pickle.loads(b);f.to_parquet(out/(name+'.parquet'),index=False)
 role={'daily':'adjusted_daily','m30':'adjusted_30m','weekly':'adjusted_weekly','raw_daily':'execution_daily','calendar':'trading_calendar'}[name]
 assert i['content_sha256']==d['input_identity_hashes'][role]
 meta['inputs'][name]={'request':q,'asset_id':e['asset_id'],'payload_sha256':bh,'acquired_at':acq,'identity':i,'warnings':w,'rows':len(f),'parquet_sha256':sha256((out/(name+'.parquet')).read_bytes()).hexdigest()}
 print(name,len(f),str(f.Date.iloc[0]),str(f.Date.iloc[-1]))
(out/'input_identity.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2,default=str),encoding='utf-8');c.close()
original={v:json.loads((root/f'strategies/S001/versions/{v}.json').read_text(encoding='utf-8')) for v in ['v1','v2']}
(root/'.tmp/s001-v4-correction/original_versions.json').write_text(json.dumps(original,ensure_ascii=False,indent=2),encoding='utf-8')
