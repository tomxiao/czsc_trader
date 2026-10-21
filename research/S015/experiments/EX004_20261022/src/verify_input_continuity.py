"""Compare stage-three bound daily inputs to the retained stage-one development pool."""
import json
from pathlib import Path
from uuid import UUID
import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderConfig, PreparedDataRef, DataRequest, Dataset
from strategy_runtime import StrategyInputBinding
from run_supplement import ROOT, EROOT, WORK, save


def main():
    audit=json.loads((ROOT/'research/S015/experiments/EX001_20261021/others/data_audit.json').read_text(encoding='utf-8'))
    original=audit['prepared_reference']
    ref=PreparedDataRef(UUID(original['space_id']),UUID(original['preparation_id']),original['manifest_sha256'])
    pilot=json.loads((WORK/'precheck.json').read_text(encoding='utf-8'))
    binding=StrategyInputBinding.from_mapping(pilot['input_bindings']['full'])
    flows=Dataflows(base_dir=ROOT,space=DataSpace(Path('research/S015/assets/data')),providers=ProviderConfig(bindings={}))
    checks=[]
    for name,dataset in [('market',Dataset.ETF_OHLCV),('execution',Dataset.ETF_UNADJUSTED_DAILY)]:
        request=next(x for x in audit['requests'] if x['dataset']==dataset.value)
        old=flows.fetch(DataRequest(**{**request,'dataset':dataset}),prepared=ref)
        new=flows.fetch(binding.plan.requests[name],prepared=binding.prepared)
        if not old.ready or not new.ready:
            raise RuntimeError('retained input could not be authenticated')
        cols=['Date','Open','High','Low','Close','Volume','Amount']
        left=old.dataframe[cols].copy()
        right=new.dataframe[cols].copy()
        left['Date']=pd.to_datetime(left['Date'])
        right['Date']=pd.to_datetime(right['Date'])
        left=left[left.Date.isin(right.Date)].reset_index(drop=True)
        pd.testing.assert_frame_equal(left,right.reset_index(drop=True),check_exact=True)
        checks.append({'input':name,'rows':len(right),'retained_original_sha256':old.identity.content_sha256,
                       'bound_sha256':new.identity.content_sha256,'comparison':'exact values including all OHLCVA'})
    save(EROOT/'others/input_continuity.json',{'status':'PASS','checks':checks,
        'scope':'precheck-bound daily inputs match the prior pool on their full overlap; no provider call'})
    print('daily input continuity PASS')


if __name__=='__main__':
    main()
