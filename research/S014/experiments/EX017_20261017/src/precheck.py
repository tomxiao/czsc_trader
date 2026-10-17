"""Causal prefixes and original state identity before any full account result."""
from pathlib import Path
from hashlib import sha256
import json
import importlib.util
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    target=EX/'others/precheck.json'
    if target.exists():raise RuntimeError('Preserve precheck evidence')
    m=module('repair_source',EX/'src/strategy_runtime/strategies/repair.py');old=module('s014_inputs',ROOT/'research/S014/experiments/EX013_20261017/src/inputs.py')
    data,dates,*_=old.load();samples=pd.read_csv(EX/'src/strategy_runtime/strategies/calibration_samples.csv');checks=[]
    def check(name,value):assert bool(value),name;checks.append(name)
    expected=pd.read_csv(ROOT/'research/S014/assets/runs/EX016_20261017/annual_observations.csv')
    frames={k:data[k] for k in ['stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status']}
    args=list(frames.values())
    for variant in m.VARIANTS:
        h=m.history(*args,samples,variant)
        check('state '+variant,np.array_equal(h.loc[dates[expected.signal],'high'],expected.high) and np.allclose(h.loc[dates[expected.signal],'threshold'],expected.threshold,atol=1e-12))
        check('startup '+variant,not h.ready.iloc[:185].any() and h.ready.iloc[185])
        check('unfilled cycle reset '+variant,h.loc[h.failed_buy_reset,'target_position'].eq(0).all())
        check('H1 entry day exit intent '+variant,variant!='parent_H1' or h.loc[h.buy_filled_today,'target_position'].eq(0).all())
        for stop in (186,500,1000,1500):
            prefix=m.history(*[x.iloc[:stop] for x in args],samples,variant)
            pd.testing.assert_frame_equal(h.iloc[:stop],prefix);check(f'prefix {variant}/{stop}',True)
        # Future calibration observations and future prices cannot change earlier signals.
        altered=[x.copy() for x in args]
        for x in altered[:2]:x.loc[1000:,['Open','High','Low','Close']]*=1.2
        altered[2].loc[1000:,['DownLimit','UpLimit']]*=1.2
        future=samples.copy();future.loc[pd.to_datetime(future.maturity_date)>=dates[1000],'gap_autocorr']=.999
        ph=m.history(*altered,future,variant)
        pd.testing.assert_frame_equal(h.iloc[:1000],ph.iloc[:1000]);check('future perturbation '+variant,True)
    # A split in the price scale must be handled in consistent HFQ units.
    check('raw tick and guard',abs(m.buy_limit(10.,2.)-20.2)<1e-12 and abs(m.buy_limit(4.18,1.)-4.22)<1e-12)
    result={'status':'PASS','checks':checks,'check_count':len(checks),'account_runs':0,'new_source_calls':0,'source_sha256':sha256((EX/'src/strategy_runtime/strategies/repair.py').read_bytes()).hexdigest(),'pending':['首日预窗口数据授权及准备','实际连续账户逐日持仓/计划一致性','四方案完整账本及年度硬门']}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print('PRECHECK_PASS',len(checks))

if __name__=='__main__':main()
