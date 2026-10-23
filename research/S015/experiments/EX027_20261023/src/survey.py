"""Funding dataset admission through the existing public DFLS contract."""
import json
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from pathlib import Path
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources, ExperimentRef, MaterialEvidenceWrite
from dataflows import DataRequest, Dataset, PreparePolicy, DataCoverageRequirement

ROOT=Path(__file__).resolve().parents[5]
HERE=Path(__file__).resolve().parents[1]
def serial(value):
    if is_dataclass(value): return {f.name:serial(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value, Mapping): return {str(k):serial(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [serial(v) for v in value]
    return value
def save(name,value):
    (HERE/'others'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')

def run():
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
    p=HERE/'protocols/coverage_resolution.json'
    ref=publish_evidence(ctx,MaterialEvidenceWrite(ExperimentRef('S015',HERE.name),'coverage_resolution',p.read_bytes(),'application/json','json'))
    save('coverage_resolution_ref.json',ref.to_dict())
    req=DataRequest(Dataset.ETF_SHARE_SIZE,'159326.SZ','2024-09-10','2026-10-21','2026-10-21',coverage=DataCoverageRequirement(maximum_start_lag_days=0,minimum_observations=508,minimum_sessions=508))
    result=ctx.data.prepare((req,),policy=PreparePolicy.REUSE)
    save('own_share_preparation_resolved.json',serial(result))
    print('PREPARATION',result.status,flush=True)
    if result.reference is None:
        print([(v.status,str(v.error)) for v in result.items],flush=True)
        return
    result2=ctx.data.fetch(req,prepared=result.reference)
    assert result2.ready, result2.error
    save('own_share_identity.json',serial(result2.identity))
    frame=result2.dataframe
    frame.to_csv(HERE/'others/own_shares.csv',index=False)
    print({'rows':len(frame),'start':str(frame.Date.min()),'end':str(frame.Date.max()),'columns':list(frame.columns)},flush=True)

if __name__=='__main__': run()
