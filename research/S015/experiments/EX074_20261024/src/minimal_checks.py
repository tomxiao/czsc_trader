"""Causal prefixes, active parameter boundaries and exact economic equivalence."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
from pathlib import Path
import importlib.util, json, sys
import pandas as pd

H=Path(__file__).resolve().parents[1]; B=H.parent
def mod(p,n):
    spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def signals():
    loader=mod(B/'EX051_20261024/src/study.py','loader');old,_=loader.loader()
    adj,raw,bars,rules,ids=old.inputs(old.sources())
    new=mod(H/'src/strategy_runtime/strategies/price_process.py','new')
    prev=mod(B/'EX070_20261024/src/strategy_runtime/strategies/price_process.py','prev')
    configs=read(H/'protocols/accounts.json')['configurations'];count=0
    for p,cid in zip(configs,['C7001','C7005'],strict=True):
        f=new.causal_features(adj,raw,bars,p['lookback'],p['center_kind']);out=new.intentions(f,p)
        prior=read(B/f'EX070_20261024/others/{cid}_payload.json')['parameters']
        expected=prev.intentions(prev.causal_features(adj,raw,bars,p['lookback'],p['center_kind']),prior)
        cols=['target_position','entry_allocation_fraction','entry_signal','exit_signal','permission','m','p','center_gain','feature_ready']
        pd.testing.assert_frame_equal(out[cols],expected[cols])
        for stop in [75,76,77,79,80,120,200,300,400,509]:
            part=new.causal_features(adj.iloc[:stop],raw.iloc[:stop],bars.iloc[:max(0,stop-75)*8],p['lookback'],p['center_kind'])
            pd.testing.assert_frame_equal(part,f.iloc[:len(part)]);count+=1
        for stop in [1,2,3,4,5,10,20,50,100,200,300,435]:
            pd.testing.assert_frame_equal(new.intentions(f.iloc[:stop],p),out.iloc[:stop]);count+=1
        # A long uncompleted opportunity must not expire after three or thirty days.
        fake=pd.DataFrame({'m':[2.]*40,'p':[1.5]*40,'center_gain':[1.]*40,'feature_ready':[True]*40},index=pd.bdate_range('2025-01-02',periods=40))
        assert new.intentions(fake,p).target_position.eq(1).all()
        for bad in [dict(p,hold=3),dict(p,lookback=True),dict(p,lookback=1),dict(p,allocation=0),dict(p,allocation=True),dict(p,center_kind='daily_mid')]:
            try:new.validate_parameters(bad)
            except ValueError:pass
            else:raise AssertionError(bad)
    save(H/'others/runtime_checks.json',{'status':'PASS','prefix_checks':count,'old_signal_equivalence':True,'no_holding_expiry_40_sessions':True,'invalid_parameter_cases':12,'input_ids':ids})
    print('MINIMAL_SIGNALS_PASS',count,flush=True)

def accounts():
    checks=[]
    for old,new in [('C7001','C7400'),('C7005','C7401')]:
        for w in ['full','s011_common']:
            tables=['account_daily','decisions','orders','fills','trades']
            aa={t:pd.read_csv(B/f'EX070_20261024/others/{old}_{w}_{t}.csv') for t in tables}
            bb={t:pd.read_csv(H/f'others/{new}_{w}_{t}.csv') for t in tables}
            ids={'decision_id','order_id','fill_id','cycle_id','entry_cycle_id','plan_identity','signal_identity'}
            mapping={};reverse={}
            for table in tables:
                assert len(aa[table])==len(bb[table])
                for col in ids.intersection(aa[table].columns):
                    for v,z in zip(aa[table][col],bb[table][col],strict=True):
                        if pd.isna(v) or pd.isna(z):
                            assert pd.isna(v) and pd.isna(z);continue
                        assert mapping.setdefault(v,z)==z and reverse.setdefault(z,v)==v
            def rename(v):
                if isinstance(v,dict):return {k:rename(z) for k,z in v.items()}
                if isinstance(v,list):return [rename(z) for z in v]
                return mapping.get(v,v) if isinstance(v,str) else v
            for table in ['account_daily','decisions','orders','fills','trades']:
                a=aa[table].copy();b=bb[table].copy()
                # Content-derived identifiers are bijectively renamed consistently
                # across all five ledgers and nested cycle states. No economic field changes.
                excluded=[]
                for col in ids.intersection(a.columns):a[col]=a[col].map(lambda v:mapping.get(v,v) if not pd.isna(v) else v)
                for col in {'entry_cycle','entry_cycle_before','entry_cycle_after'}.intersection(a.columns):
                    a[col]=a[col].map(lambda v:json.dumps(rename(json.loads(v)),sort_keys=True) if isinstance(v,str) else v)
                    b[col]=b[col].map(lambda v:json.dumps(json.loads(v),sort_keys=True) if isinstance(v,str) else v)
                if table=='decisions':
                    cols=list(a.columns[:a.columns.get_loc('action')+1])+['target_position','entry_allocation_fraction','entry_signal','exit_signal','permission','m','p','center_gain','feature_ready']
                    cols=list(dict.fromkeys(c for c in cols if c not in excluded))
                else:cols=list(a.columns)
                pd.testing.assert_frame_equal(a[cols],b[cols],check_exact=True)
                checks.append({'old':old,'new':new,'window':w,'table':table,'rows':len(a),'compared_columns':cols,'bijective_identity_pairs':len(mapping),'old_only_observations':list(set(a.columns)-set(b.columns))})
    save(H/'others/equivalence.json',{'status':'PASS','economic_ledgers_exact':True,'checks':checks,'scope':'All financial, state and execution fields exact after consistent bijective identity renaming; inactive observations differ intentionally. Not byte-identical raw account identity.'})
    print('ECONOMIC_EQUIVALENCE_PASS',len(checks),flush=True)

if __name__=='__main__':
    {'signals':signals,'accounts':accounts}[sys.argv[1]]()
