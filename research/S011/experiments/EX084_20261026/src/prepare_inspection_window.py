"""Prepare a cutoff-bounded S011 inspection without new prices or evaluations."""
from pathlib import Path
from dataclasses import replace
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import sys
import cloudpickle
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,load_candidate,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExecutionResources,EvaluationWindow,ExperimentRef,MaterialEvidenceWrite
from dataflows import ProviderBinding,ProviderConfig,canonical_frame_sha256,PreparePolicy,Dataset
from strategy_runtime import canonical_sha256
from strategy_manager import CandidateKey

ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
EX=ExperimentRef("S011",HOME.name)
CUTOFF=date(2026,9,30)


def run():
    sys.dont_write_bytecode=True
    repo=RepositoryContext.discover(ROOT)
    readctx=create_research_context(repo,ResearchBatchRef("S011"),resources=ExecutionResources(1,1,42),providers=ProviderConfig(bindings={}))
    baseline=ROOT/".tmp/observation-v4-upgrade/S011-v1-baseline.pkl"
    old=cloudpickle.loads(baseline.read_bytes())
    sources={};provenance=[]
    groups=[(next(iter(old.input_bindings.values())).plan.requests,next(iter(old.input_bindings.values())).prepared),(old.execution_data.requests,old.execution_data.prepared)]
    for requests,prepared in groups:
        for name,request in requests.items():
            result=readctx.data.fetch(request,prepared=prepared)
            assert result.ready, (name,result.error)
            assert canonical_frame_sha256(result.dataframe)==result.identity.content_sha256
            key=(request.dataset,request.symbol,request.frequency)
            sources.setdefault(key,[]).append((request,result))
            provenance.append({"role":name,"request":{"dataset":str(request.dataset),"symbol":request.symbol,"frequency":request.frequency,"start":request.start,"end":request.end},"content_sha256":result.identity.content_sha256})
    def source(request):
        candidates=[(original,result) for original,result in sources.get((request.dataset,request.symbol,request.frequency),[])
            if request.parameters==original.parameters and pd.Timestamp(request.start)>=pd.Timestamp(original.start) and pd.Timestamp(request.end)<=pd.Timestamp(original.end)]
        if not candidates:
            raise ValueError("inspection slice exceeds authenticated input: "+str(request))
        parts=[]
        for original,result in candidates:
            times=pd.to_datetime(result.dataframe["Date"])
            frame=result.dataframe.loc[(times>=pd.Timestamp(request.start))&(times<pd.Timestamp(request.end)+pd.Timedelta(days=1))].copy().reset_index(drop=True)
            metadata=deepcopy(dict(result.identity.metadata))
            if request.dataset is Dataset.SECURITY_PRICE_LIMITS:
                # Slice original calendar proof along with its price-limit rows.
                coverage=metadata["daily_session_coverage"]
                calendar=pd.DataFrame(coverage["calendar"])
                dates=pd.to_datetime(calendar.Date)
                calendar=calendar.loc[(dates>=pd.Timestamp(request.start))&(dates<=pd.Timestamp(request.end))].reset_index(drop=True)
                coverage["calendar"]=calendar.to_dict("list")
                digest=sha256()
                digest.update(repr([(str(column),str(dtype)) for column,dtype in calendar.dtypes.items()]).encode("utf-8"))
                digest.update(pd.util.hash_pandas_object(calendar,index=True).values.tobytes())
                coverage["calendar_sha256"]=digest.hexdigest()
                coverage["start_date"]=request.start
                coverage["end_date"]=request.end
                coverage["expected_dates"]=[day for day in coverage["expected_dates"] if request.start<=day<=request.end]
                coverage["verified_sessions"]=len(coverage["expected_dates"])
                coverage["suspended_dates"]=[day for day in coverage.get("suspended_dates",[]) if request.start<=day<=request.end]
                coverage["suspension_evidence"]=[item for item in coverage.get("suspension_evidence",[]) if request.start<=item["date"]<=request.end]
            parts.append((frame,metadata))
        hashes={canonical_frame_sha256(frame) for frame,_ in parts}
        if len(hashes)!=1:
            raise ValueError("overlapping authenticated input slices disagree")
        return parts[0]
    providers=ProviderConfig(bindings={dataset:ProviderBinding("s011-v4-authenticated-cutoff-slice","1",source) for dataset,_,_ in sources})
    ctx=create_research_context(repo,ResearchBatchRef("S011"),resources=ExecutionResources(1,1,42),providers=providers)
    candidate=load_candidate(repo,CandidateKey("S011","C9950"))
    # Preserve the authenticated execution calendar's exact original start.
    # Automatic fresh preparation asks for an extra calendar month that is not
    # available in this historical input; no new calendar facts are invented.
    execution_requests={name:replace(item,end=CUTOFF.isoformat(),required_cutoff=CUTOFF.isoformat())
        for name,item in old.execution_data.requests.items()}
    preparation=ctx.data.prepare(tuple(execution_requests.values()),policy=PreparePolicy.REUSE)
    assert preparation.reference is not None, [(str(item.request.dataset),str(item.error)) for item in preparation.items if item.error]
    execution_results={name:ctx.data.fetch(item,prepared=preparation.reference) for name,item in execution_requests.items()}
    assert all(item.ready for item in execution_results.values()),{key:str(item.error) for key,item in execution_results.items() if not item.ready}
    def prices(frame):
        result=frame.rename(columns={"Date":"dt","Open":"open","High":"high","Low":"low","Close":"close","Volume":"vol","Amount":"amount"}).copy()
        result["dt"]=pd.to_datetime(result["dt"],errors="raise")
        result=result[["dt","open","high","low","close","vol","amount"]]
        result.attrs=deepcopy(frame.attrs)
        return result
    adjusted=prices(execution_results["adjusted_daily"].dataframe)
    raw=prices(execution_results["execution_daily"].dataframe)
    execution_daily=old.execution_data.pricing.apply(raw,raw_daily=raw,adjusted_daily=adjusted)
    adjusted.insert(1,"symbol",old.execution_data.symbol)
    empty=pd.DataFrame({"dt":pd.Series(dtype="datetime64[ns]"),**{key:pd.Series(dtype=float) for key in ("open","high","low","close","vol","amount")}})
    calendar=execution_results["trading_calendar"].dataframe
    sessions=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1),"Date"]))
    rules=replace(old.execution_data.market_rules,
        sessions=tuple(item for item in old.execution_data.market_rules.sessions if item.session<=CUTOFF),
        suspended_sessions=tuple(day for day in old.execution_data.market_rules.suspended_sessions if day<=CUTOFF))
    identities={name:item.identity.content_sha256 for name,item in execution_results.items()}
    fingerprint=canonical_sha256({"symbol":old.execution_data.symbol,"asset_type":old.execution_data.asset_type,
        "evaluation_start":sessions[0].date().isoformat(),"evaluation_end":sessions[-1].date().isoformat(),
        "inputs":identities,"pricing":old.execution_data.pricing.to_dict(),"market_rules":rules.to_dict()})
    execution=replace(old.execution_data,adjusted_daily=adjusted,execution_daily=execution_daily,
        execution_intraday=empty,raw_execution_daily=raw,execution_five_minute=None,
        fingerprint=fingerprint,cutoff=CUTOFF,evaluation_sessions=sessions,requests=execution_requests,
        prepared=preparation.reference,input_identities=identities,strategy_bindings={},market_rules=rules)
    request=replace(old,experiment_id=EX.experiment_id,strategy=candidate,
        runtime_binding={"candidate_id":candidate.reference_id,"source_files":list(candidate.payload["runtime"]["source_files"]),"implementation_sha256":candidate.payload["runtime"]["source_sha256"]},
        windows=(EvaluationWindow("inspection",old.windows[0].start,CUTOFF),),data_cutoff=CUTOFF,
        execution_data=execution,input_bindings={},lineage=None)
    request=ctx.evaluation.prepare(request)
    assert request.execution_data.cutoff==CUTOFF
    assert max(request.execution_data.evaluation_sessions).date()<=CUTOFF
    binding=request.input_bindings["inspection"]
    assert binding.plan.tradable_window.end==CUTOFF
    checks=[]
    for requests,prepared in [(binding.plan.requests,binding.prepared),(request.execution_data.requests,request.execution_data.prepared)]:
        for name,item in requests.items():
            result=ctx.data.fetch(item,prepared=prepared);expected,_=source(item)
            assert result.ready and result.identity.content_sha256==canonical_frame_sha256(expected),(name,"slice identity mismatch")
            checks.append({"role":name,"sha256":result.identity.content_sha256,"end":item.end})
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EX,"inspection_cutoff_window_request",cloudpickle.dumps(request),"application/octet-stream","pkl"))
    target=HOME/"others/inspection_window_request_ref.json"
    assert not target.exists()
    target.write_text(json.dumps(ref.to_dict(),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (HOME/"others/inspection_window_design.json").write_text(json.dumps({"status":"PREPARED_NOT_EVALUATED","reason":"Technical inspection must not exceed original frozen selection cutoff 2026-09-30", "window":{"start":str(request.windows[0].start),"end":str(CUTOFF)},"baseline_pickle_sha256":sha256(baseline.read_bytes()).hexdigest(),"original_415day_evidence":"UNCHANGED","source_inputs":provenance,"prepared_slice_checks":checks,"request_reference":ref.to_dict(),"session_count":len(request.execution_data.evaluation_sessions),"network_access":False,"new_evaluations":0},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("S011_CUTOFF_REQUEST_PREPARED",len(request.execution_data.evaluation_sessions),ref.sha256,flush=True)


if __name__=="__main__":run()
