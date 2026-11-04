from pathlib import Path
import json
from decimal import Decimal, ROUND_FLOOR
import numpy as np
import pandas as pd


def main():
    work=Path(__file__).resolve().parents[1]; family=work.parents[1]
    raw=pd.DataFrame(json.loads((family/'experiments/EX044_20261104/others/analysis_MU_frozen_raw.json').read_text()))
    limit=np.array([float((Decimal(str(float(c)))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01')) for c in raw.Close])
    op=raw.Open.shift(-1).to_numpy();lo=raw.Low.shift(-1).to_numpy()
    fill=np.where(op<=limit,op,np.where(lo<limit,limit,np.nan))
    pred=pd.DataFrame({'signal_date':pd.to_datetime(raw.Date).dt.strftime('%Y-%m-%d'),
        'proxy':raw.Open.shift(-2).to_numpy()*.999/(fill*1.001)-1,'proxy_entry':fill})
    events=pd.read_json(family/'experiments/EX039_20261104/others/analysis_events_enriched.json')
    closed=events[(events.horizon==1)&(events.status=='CLOSED')].merge(pred,on='signal_date',validate='one_to_one')
    assert len(closed)==835
    assert np.isfinite(closed.proxy).all()
    assert np.allclose(closed.proxy_entry,closed.entry_price,rtol=0,atol=1e-8)
    diff=closed.proxy-closed.net_return
    output={'closed_events':len(closed),'exact_fill_price':'835/835 within1e-8','max_abs_return_difference':float(diff.abs().max()),
        'mean_abs_return_difference':float(diff.abs().mean()),'events_difference_above_1e_8':int((diff.abs()>1e-8).sum()),
        'label_positive_sign_differences':int(((closed.proxy>0)!=(closed.net_return>0)).sum()),
        'limits':'Price-only proxy is not the formal net economic label; held dividends can differ. All four live models use identical proxy, account performance includes actual actions. Comparison is diagnostic and does not prove forecast signs invariant.',
        'differences':closed.loc[diff.abs()>1e-8,['signal_date','proxy','net_return']].to_dict('records')}
    (work/'others/analysis_training_proxy.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print({k:v for k,v in output.items() if k!='differences'})


if __name__=='__main__':main()
