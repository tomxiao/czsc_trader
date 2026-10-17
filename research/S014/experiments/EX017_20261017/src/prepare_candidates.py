"""Build bounded historical candidate closures from authenticated S014 evidence."""
from pathlib import Path
from hashlib import sha256
from io import BytesIO
import json
import pandas as pd
import numpy as np
from strategy_runtime import StrategyCandidate,StrategyRuntime,implementation_sha256
from czsc_trader.research_tools import EvidenceRef
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1];PACKAGE=EX/'src/strategy_runtime'
VARIANTS=('parent_H1','parent_H3','high_H3','high_H3_low_H1')

def main():
    refs=json.loads((ROOT/'research/S014/experiments/EX013_20261017/others/result.json').read_text(encoding='utf-8'))['evidence'];sources={}
    def read(name):
        ref=EvidenceRef.from_dict(refs[name]);raw=ref.resolve(ROOT).read_bytes();assert sha256(raw).hexdigest()==ref.sha256;sources[name]=ref.to_dict();return pd.read_csv(BytesIO(raw))
    features=read('ex013-corrected-features-csv').set_index('signal');labels=read('ex013-corrected-labels-csv');date_map=pd.to_datetime(labels.drop_duplicates('signal').set_index('signal').signal_date)
    # Labels cover nearly the whole date grid; final mature exit can be a final input date.
    import importlib.util
    spec=importlib.util.spec_from_file_location('s014_inputs',ROOT/'research/S014/experiments/EX013_20261017/src/inputs.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    _,dates,*_=mod.load()
    q=labels.loc[labels.horizon.eq(3)&labels.maturity.ge(0)].copy()
    assert np.isfinite(features.loc[q.signal].to_numpy(float)).all()
    samples=pd.DataFrame({'signal_date':dates[q.signal.to_numpy(int)].strftime('%Y-%m-%d'),'maturity_date':dates[q.maturity.to_numpy(int)].strftime('%Y-%m-%d'),'gap_autocorr':features.loc[q.signal,'gap_autocorr'].to_numpy()})
    samples.to_csv(PACKAGE/'strategies/calibration_samples.csv',index=False,lineterminator='\n')
    files=('strategies/repair.py','strategies/calibration_samples.csv');digest=implementation_sha256(files,source_root=PACKAGE);identities=[]
    for i,variant in enumerate(VARIANTS,1):
        payload={'runtime':{'module':'strategy_runtime.strategies.repair','qualname':'RepairStrategy','contract_version':1,'source_files':list(files),'source_sha256':digest},'parameters':{'variant':variant}}
        c=StrategyCandidate('S014',f'C{i:04}',payload,PACKAGE);d=StrategyRuntime().describe(c)
        (EX/'protocols'/f'payload_{variant}.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8',newline='\n')
        identities.append({'candidate':c.reference_id,'variant':variant,'runtime_sha256':d.runtime_sha256,'source_sha256':digest})
    (EX/'others/candidate_preparation.json').write_text(json.dumps({'sources':sources,'samples':len(samples),'identities':identities,'account_runs':0,'new_source_calls':0,'historical_scope_only':True},indent=2)+'\n',encoding='utf-8',newline='\n')
    print('CANDIDATES_LOAD',len(identities),'CALIBRATION_ROWS',len(samples))

if __name__=='__main__':main()
