"""Select fixed matched-period cases before reading any announcements."""
from hashlib import sha256
import json
from pathlib import Path
import random
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]


def main():
    target=EXPERIMENT/'others/blinded_cases.json'
    if target.exists():
        raise RuntimeError('Preserve fixed sample')
    previous=json.loads((ROOT/'research/S014/experiments/EX010_20261017/others/result.json').read_text(encoding='utf-8'))
    ref=EvidenceRef.from_dict(previous['evidence']['run-predictions'])
    path=ref.resolve(ROOT)
    assert sha256(path.read_bytes()).hexdigest()==ref.sha256
    all_rows=pd.read_csv(path)
    mapping=all_rows.drop_duplicates('signal').set_index('signal').signal_date.to_dict()
    rows=all_rows.loc[all_rows.horizon.eq(1)&all_rows.status.eq('CLOSED')].copy()
    rows['date']=pd.to_datetime(rows.signal_date)
    design=json.loads((EXPERIMENT/'protocols/design.json').read_text(encoding='utf-8'))
    cases=[];missing=[]
    for anchor in design['sampling']['anchors']:
        stamp=pd.Timestamp(anchor)
        pool=rows.loc[rows.year.eq(stamp.year)].copy()
        pool['distance']=(pool.date-stamp).abs().dt.days
        pool=pool.loc[pool.distance.le(30)].sort_values(['distance','date'])
        masks={'repair_positive':pool.gap_down_repair.eq(1)&pool.net_return.gt(0),
            'repair_nonpositive':pool.gap_down_repair.eq(1)&pool.net_return.le(0),
            'ordinary':pool.gap_down_repair.eq(0)}
        for group,mask in masks.items():
            selected=pool.loc[mask]
            if selected.empty:
                missing.append({'anchor':anchor,'group':group});continue
            r=selected.iloc[0]
            cases.append({'anchor':anchor,'group':group,'signal':int(r.signal),'signal_date':r.date.strftime('%Y-%m-%d'),
                'entry_date':str(mapping[int(r.entry)])[:10],'exit_date':str(mapping[int(r.maturity)])[:10],
                'lookback_start':(r.date-pd.Timedelta(days=14)).strftime('%Y-%m-%d'),
                'net_return':float(r.net_return),
                **{k:float(r[k]) for k in ('prediction_ridge_stock','prediction_ridge_market','gap','intraday','ret5','ret20','range','volume_ratio')}})
    random.Random(12017).shuffle(cases)
    for i,r in enumerate(cases):
        r['case_id']=f'C{i+1:02d}'
    blinded=[{k:r[k] for k in ('case_id','signal_date','entry_date','exit_date','lookback_start')} for r in cases]
    result={'source':ref.to_dict(),'cases':cases,'missing_groups':missing,'selection_bias':'Outcome-stratified,disclosure-enriched,seen development pool;not performance estimation.'}
    for p,data in [(target,blinded),(EXPERIMENT/'others/sealed_outcomes.json',result)]:
        p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'blinded_cases':blinded,'missing_groups':len(missing)},ensure_ascii=False))


if __name__=='__main__':
    main()
