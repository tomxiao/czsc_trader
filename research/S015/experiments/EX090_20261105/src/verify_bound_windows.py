"""Additional read-only signal-validity and fresh-window verification."""
from pathlib import Path
from hashlib import sha256
import json
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity
ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]

def main():
    rows=[]
    for item in json.loads((HOME/'others/bound_results.json').read_text(encoding='utf-8'))['accounts']:
        oldref=EvidenceRef.from_dict(item['old_reference']);oldcontent=oldref.resolve(ROOT).read_bytes()
        assert sha256(oldcontent).hexdigest()==oldref.sha256
        old=next(r for r in json.loads(oldcontent)['runs'] if r['window_id']==item['window'])
        ref=EvidenceRef.from_dict(item['reference']);path=ref.resolve(ROOT)
        content=path.read_bytes(); assert sha256(content).hexdigest()==ref.sha256
        full=materialize_equity(content,lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload
        new=full['runs']['candidate']
        valid_differences=[]
        for i,(a,b) in enumerate(zip(old['signals']['data'],new['decisions'],strict=True)):
            if a['valid_session'][:10]!=pd.Timestamp(b['execution_start']).tz_convert('Asia/Shanghai').date().isoformat():valid_differences.append(i)
        assert not valid_differences
        first=new['account_daily'][0]
        assert first['quantity']==0 and first['cash']==100000 and first['equity']==100000
        rows.append({'candidate_id':item['candidate_id'],'window':item['window'],'valid_session_differences':valid_differences,'first_account':first})
    (HOME/'others/bound_window_audit.json').write_text(json.dumps({'status':'PASS','accounts':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print('SIGNAL_VALID_SESSION_AND_FRESH_OPENING_PASS',len(rows))
if __name__=='__main__':main()
