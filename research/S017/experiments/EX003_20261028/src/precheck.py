"""Check buffer boundaries and zero-buffer agreement with the retained baseline."""
from types import SimpleNamespace
from datetime import date
from uuid import UUID
import importlib.util
import pandas as pd
from dataflows import PreparedDataRef, EquityDataRequest, EquityQuery, EquityProduct
from strategy import decide
from run import ROOT, WORK, SOURCE, INSTRUMENT, context, read, save, configurations, candidate


def check():
    h=pd.DataFrame({'Close':[100.]*261,'High':[101.]*261,'Low':[99.]*261})
    p={'trend_bars':260,'vol_bars':13,'entry_atr':1.,'exit_atr':1.}
    def result(hist,quantity,params=p):
        return decide(SimpleNamespace(history=hist,parameters=params,portfolio=SimpleNamespace(quantity=quantity)))
    assert result(h,0).target==0
    assert result(h,1).target==1
    h.iloc[-1]=[105,106,104]
    assert result(h,0).target==1
    h.iloc[-1]=[95,96,94]
    assert result(h,1).target==0
    spec=importlib.util.spec_from_file_location('s017_old_baseline',ROOT/'research/S017/experiments/EX002_20261028/src/strategy.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old_p=read(ROOT/'research/S017/experiments/EX002_20261028/protocols/definitions.json')['C0001']['parameters_json']
    import json
    old_p=json.loads(old_p)
    r=read(ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json')['reference']
    prepared=PreparedDataRef(UUID(r['space_id']),UUID(r['preparation_id']),r['manifest_sha256'])
    fetched=context().data.fetch(EquityDataRequest(INSTRUMENT,SOURCE,EquityQuery(EquityProduct.BARS,date(2018,11,1),date(2025,12,31))),prepared=prepared)
    assert fetched.ready,fetched.error
    frame=fetched.dataframe
    zero={**p,'entry_atr':0.,'exit_atr':0.}
    count=0
    for end in range(508,len(frame),401):
        for quantity in (0,1):
            hist=frame.iloc[:end]
            a=result(hist,quantity,zero)
            b=mod.decide(SimpleNamespace(history=hist,parameters=old_p,portfolio=SimpleNamespace(quantity=quantity)))
            assert a.target==b.target
            count+=1
    for key,params in configurations().items():
        c=candidate(key,params)
        assert c.definition.from_dict(c.definition.to_dict())==c.definition
    save(WORK/'others/precheck.json',{'status':'PASS','synthetic_boundary_checks':4,'zero_buffer_causal_spot_checks':count,
        'scope':'decision-branch agreement only; not a second full baseline replay'})
    print('PASS',count)


if __name__=='__main__':
    check()
