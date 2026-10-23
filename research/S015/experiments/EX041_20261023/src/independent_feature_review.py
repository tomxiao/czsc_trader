"""Second-agent scalar/formula audit of all observed tsfresh feature values."""
from uuid import UUID
import numpy as np
import pandas as pd
from dataflows import DataRequest,Dataset,PreparedDataRef
import study as s
def main():
    s.frozen();inputs=s.read(s.resolve('price_input_refs'));ref=s.EvidenceRef.from_dict(inputs['source_inputs']['inputs']);facts=s.read(ref.resolve(s.ROOT));p=facts['minute_prepared']
    prep=PreparedDataRef(UUID(p['space_id']),UUID(p['preparation_id']),p['manifest_sha256'])
    fetched=s.context().data.fetch(DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY,'159326.SZ','2025-01-02','2026-10-21','2026-10-21',frequency='30m'),prepared=prep)
    assert fetched.ready and fetched.identity.content_sha256==facts['identities'][Dataset.ETF_UNADJUSTED_INTRADAY.value]['content_sha256']
    bars=fetched.dataframe.sort_values('Date').reset_index(drop=True);bars.attrs={};actual=pd.read_csv(s.HERE/'others/features.csv');rows=[]
    for date,g in bars.groupby(pd.to_datetime(bars.Date).dt.strftime('%Y-%m-%d'),sort=True):
        c=g.Close.to_numpy(float);o=float(g.Open.iloc[0]);u=np.diff(np.log(np.r_[o,c]));q=np.log(c/o);m=float(u.mean());v=float(np.mean((u-m)**2))
        def rough(x):
            sd=float(x.std());return 0. if sd==0 else float(np.sqrt(np.sum(np.diff((x-x.mean())/sd)**2)))
        values=[float(np.mean((u[:-1]-m)*(u[1:]-m))/v) if v>0 else np.nan,rough(u),int(np.count_nonzero(np.diff(u>0))),float(np.sum(u[4:]**2)/np.sum(u**2)) if np.sum(u**2)>0 else np.nan,int(np.count_nonzero(np.diff(q>0))),rough(q)]
        rows.append((date,values))
    assert actual.date.tolist()==[r[0] for r in rows]
    expected=np.asarray([r[1] for r in rows]);np.testing.assert_allclose(actual[s.ep.FEATURES],expected,rtol=1e-11,atol=1e-11,equal_nan=True)
    census=s.read(s.HERE/'others/census.json');assert census['complete_case_n']==434 and all(v==0 for v in census['missing'].values())
    s.save(s.HERE/'others/independent_feature_review.json',{'status':'PASS','independent_analyst':True,'actual_feature_cells':int(expected.size),'max_absolute_error':float(np.nanmax(np.abs(actual[s.ep.FEATURES].to_numpy()-expected))),'method':'Independent NumPy formulas, no tsfresh calculator used; authenticated raw snapshot, all434datesx6columns. Source review checked training-only transforms, label known-date purging, matching model cohorts and original execution labels. Fit/summary numeric audit remains separately documented same-author alternate-algorithm audit.','limits':'No independent audit of DFLS or TXE internals; no performance qualification.'})
    print('INDEPENDENT_FEATURE_REVIEW_PASS',expected.size,flush=True)
if __name__=='__main__':main()
