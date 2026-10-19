"""Reproduce saved predictions and diagnostics without solving/fitting models."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path.cwd()
EX=ROOT/"research/S014/experiments/EX039_20261019"
OUT=EX/"others"
FIXED=OUT/"fixed_analysis"


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def truth(values):
    return values.astype("string").str.lower().map({"true":True,"false":False,"1":True,"0":False,"1.0":True,"0.0":False}).fillna(False).astype(bool)


def close(actual,expected):
    if actual is None or expected is None:
        assert actual is None and expected is None
    else:
        np.testing.assert_allclose(actual,expected,rtol=0,atol=2e-12)


model=pd.read_csv(OUT/"model_inputs.csv").set_index("signal",drop=False)
model["date"]=pd.to_datetime(model.date)
model["entry_filled"]=truth(model.entry_filled)
model["L"]=np.maximum(-model.Y3,0)
calendar=pd.read_csv(OUT/"calendar.csv").set_index("signal")
dates=pd.to_datetime(calendar.date)
model["maturity_date"]=pd.to_datetime(model.maturity.map(dates))
analysis=read(FIXED/"analysis.json")
predictions=pd.read_csv(FIXED/"predictions.csv")
assert analysis["reserved_slots"]==analysis["completed_fits"]==28
assert analysis["technical_failures"]==0 and analysis["continuous_accounts"]==0
slots=sorted((FIXED/"fit_slots").glob("*.json"))
assert len(slots)==28
results={}
score_checks=0
prediction_keys=set()
normal_equation_max=0.
for path in slots:
    record=read(path)
    assert record["status"]=="SUCCESS" and record["fit_attempted"] is True
    family,name,year=record["family"],record["model"],record["year"]
    train=model.loc[record["train_signals"]]
    test=model.loc[record["test_signals"]]
    assert truth(train.A).all() and truth(test.A).all()
    jan=pd.Timestamp(year,1,1)
    assert (train.date<jan).all() and (train.maturity_date<jan).all()
    assert test.date.dt.year.eq(year).all()
    columns=record["columns"]
    x=train[columns].to_numpy(float)
    xt=test[columns].to_numpy(float)
    y=train.L.to_numpy(float)
    assert np.isfinite(x).all() and np.isfinite(xt).all() and np.isfinite(y).all()
    mean,scale=x.mean(0),x.std(0,ddof=0)
    scale[scale<1e-12]=1.
    close(record["means"],mean)
    close(record["scales"],scale)
    close(record["intercept"],y.mean())
    z=(x-mean)/scale
    coefficient=np.array(record["standardized_coefficients"])
    # Verification of the saved solution, with no solve/fit operation.
    normal_equation_max=max(normal_equation_max,float(np.abs(z.T@(z@coefficient-(y-y.mean()))+10*coefficient).max()))
    assert normal_equation_max<1e-9
    score=(xt-mean)/scale@coefficient+y.mean()
    threshold=float(np.quantile(z@coefficient+y.mean(),.75,method="linear"))
    close(record["scores"],score)
    close(record["threshold_q75"],threshold)
    np.testing.assert_array_equal(record["keep"],score<threshold)
    csv=predictions.loc[(predictions.family==family)&(predictions.model==name)&(predictions.year==year)]
    np.testing.assert_array_equal(csv.signal,record["test_signals"])
    close(csv.score,score)
    close(csv.Y3,test.Y3)
    close(csv.L,test.L)
    np.testing.assert_array_equal(truth(csv.keep),record["keep"])
    prediction_keys.update((family,name,year,int(signal)) for signal in test.signal)
    results[(family,name,year)]=record
    score_checks+=len(test)
assert len(prediction_keys)==len(predictions) and not predictions.duplicated(["family","model","year","signal"]).any()


def own_metrics(frame,base,new,weights=None):
    w=np.ones(len(frame)) if weights is None else np.asarray(weights,float)
    def avg(values,mask=None):
        mask=np.ones(len(frame),bool) if mask is None else mask
        return None if not w[mask].sum() else float(np.dot(np.asarray(values)[mask],w[mask])/w[mask].sum())
    y=frame.Y3.to_numpy(float)
    loss=np.maximum(-y,0)
    kb=frame["keep_"+base].to_numpy(bool)
    kn=frame["keep_"+new].to_numpy(bool)
    sb=frame["score_"+base].to_numpy(float)
    sn=frame["score_"+new].to_numpy(float)
    removed=kb&~kn
    added=kn&~kb
    return {"n":len(frame),"weight":float(w.sum()),"mse_improvement":avg((loss-sb)**2-(loss-sn)**2),"allocation_difference_per_evaluable_A":avg(y*(kn.astype(int)-kb.astype(int))),"base_allocation":avg(y*kb),"new_allocation":avg(y*kn),"base_keep_rate":avg(kb.astype(float)),"new_keep_rate":avg(kn.astype(float)),"reduced_losses_removed":avg(np.maximum(-y,0)*removed),"foregone_positive_removed":avg(np.maximum(y,0)*removed),"added_positive":avg(np.maximum(y,0)*added),"added_losses":avg(np.maximum(-y,0)*added),"removed_n":int(removed.sum()),"added_n":int(added.sum()),"base_selected_mean":avg(y,kb),"new_selected_mean":avg(y,kn),"base_selected_negative_rate":avg((y<0).astype(float),kb),"new_selected_negative_rate":avg((y<0).astype(float),kn),"raw_loss_mean":avg(loss),"raw_Y3_mean":avg(y),"raw_negative_rate":avg((y<0).astype(float))}


def own_clusters(frame):
    membership={}
    cluster_number=0
    end=None
    # Filled entry-to-exit inclusive intervals determine connected components.
    for row in frame.loc[frame.entry_filled].sort_values(["entry","maturity","signal"]).itertuples(index=False):
        if end is None or row.entry>end:
            cluster_number+=1
            end=row.maturity
        else:
            end=max(end,row.maturity)
        membership[row.signal]=cluster_number
    for signal in frame.loc[~frame.entry_filled,"signal"]:
        cluster_number+=1
        membership[signal]=cluster_number
    return frame.signal.map(membership).to_numpy(int)


diagnostic_checks=0
ci_zero={}


def compare_metrics(observed,expected):
    for key,value in expected.items():
        close(observed[key],value)


def audit_diagnostic(frame,base,new,reported,all_a,exposure,key):
    global diagnostic_checks
    frame=frame.reset_index(drop=True)
    m=own_metrics(frame,base,new)
    compare_metrics(reported,m)
    assert reported["all_A_count"]==all_a
    close(reported["allocation_difference_per_all_A"],None if not all_a else m["allocation_difference_per_evaluable_A"]*len(frame)/all_a)
    if not len(frame):
        return
    state=frame[exposure].to_numpy(float)>0
    assert reported["state_counts"]=={"positive":int(state.sum()),"other":int((~state).sum())}
    residual=frame.L-frame["score_"+base]
    close(reported["residual_positive_state_minus_other"],None if state.all() or not state.any() else float(residual[state].mean()-residual[~state].mean()))
    ids=own_clusters(frame)
    clusters=np.unique(ids)
    assert reported["cluster_count"]==len(clusters)
    assert len(reported["leave_one_cluster_out"])==len(clusters)
    for c,observed in zip(clusters,reported["leave_one_cluster_out"]):
        assert observed["omitted"]==c
        compare_metrics(observed,own_metrics(frame.loc[ids!=c],base,new))
    values=frame.Y3.to_numpy(float)*(frame["keep_"+new].to_numpy(int)-frame["keep_"+base].to_numpy(int))
    contribution=np.array([values[ids==c].sum() for c in clusters])
    share=None if not abs(contribution).sum() else float(abs(contribution).max()/abs(contribution).sum())
    close(reported["largest_cluster_share_of_absolute_allocation_contribution"],share)
    largest=clusters[abs(contribution).argmax()]
    assert reported["largest_absolute_allocation_cluster_removed"]["omitted_cluster"]==largest
    compare_metrics(reported["largest_absolute_allocation_cluster_removed"],own_metrics(frame.loc[ids!=largest],base,new))
    eq=np.array([1/(ids==c).sum() for c in ids])
    compare_metrics(reported["equal_cluster"],own_metrics(frame,base,new,eq))
    keep=[]
    last=-np.inf
    for row in frame.sort_values("signal",kind="stable").itertuples(index=False):
        if not row.entry_filled:
            keep.append(row.signal)
        elif row.entry>last:
            keep.append(row.signal)
            last=row.maturity
    assert reported["chronological_nonoverlap"]["signals"]==keep
    compare_metrics(reported["chronological_nonoverlap"],own_metrics(frame.loc[frame.signal.isin(keep)],base,new))
    # Same fixed paired cluster resampling, implemented from weighted per-row
    # differences, with no model/helper reuse and no new predictions.
    y=frame.Y3.to_numpy(float)
    l=np.maximum(-y,0)
    mse=(l-frame["score_"+base].to_numpy(float))**2-(l-frame["score_"+new].to_numpy(float))**2
    cluster_sizes=np.array([(ids==c).sum() for c in clusters])
    mse_sums=np.array([mse[ids==c].sum() for c in clusters])
    alloc_sums=np.array([values[ids==c].sum() for c in clusters])
    rng=np.random.default_rng(13)
    bootstrap_mse=[]
    bootstrap_alloc=[]
    for _ in range(2000):
        chosen=rng.choice(clusters,len(clusters),replace=True)
        count=np.array([(chosen==c).sum() for c in clusters])
        denominator=np.dot(count,cluster_sizes)
        bootstrap_mse.append(float(np.dot(count,mse_sums)/denominator))
        bootstrap_alloc.append(float(np.dot(count,alloc_sums)/denominator))
    intervals=reported["cluster_bootstrap"]["intervals"]
    close(intervals["mse_improvement"],np.quantile(bootstrap_mse,[.025,.975]))
    close(intervals["allocation_difference_per_evaluable_A"],np.quantile(bootstrap_alloc,[.025,.975]))
    ci_zero[key]={name:bool(interval[0]<=0<=interval[1]) for name,interval in intervals.items()}
    matched=np.zeros(len(frame),bool)
    for _,group in frame.groupby(frame.date.dt.year):
        count=int(group["keep_"+new].sum())
        chosen=group.sort_values(["score_"+base,"signal"],kind="stable").index[:count]
        matched[frame.index.get_indexer(chosen)]=True
    assert reported["posthoc_matched_participation"]["count"]==matched.sum()
    close(reported["posthoc_matched_participation"]["new_minus_matched_allocation"],float((y*(frame["keep_"+new].to_numpy(int)-matched.astype(int))).mean()))
    # Independent accounting identity for removed/added returns.
    close(m["allocation_difference_per_evaluable_A"],m["reduced_losses_removed"]-m["foregone_positive_removed"]+m["added_positive"]-m["added_losses"])
    diagnostic_checks+=1


summary={}
for family,models,pairs,exposure in [("ETF",["E0","E1","E2"],[("E0","E1"),("E0","E2")],"etf_z"),("OPTION",["O0","O1"],[("O0","O1")],"opt_delta_put"),("JOINT",["J0","J1"],[("J0","J1")],"opt_delta_put")]:
    frames=[]
    for year in [2023,2024,2025,2026]:
        saved=[results[(family,name,year)] for name in models]
        testids=saved[0]["test_signals"]
        assert all(r["test_signals"]==testids for r in saved)
        assert all(r["train_signals"]==saved[0]["train_signals"] for r in saved)
        frame=model.loc[testids].copy().reset_index(drop=True)
        for name,record in zip(models,saved):
            frame["score_"+name]=record["scores"]
            frame["keep_"+name]=record["keep"]
        all_a=int((truth(model.A)&model.date.dt.year.eq(year)).sum())
        reported=analysis["families"][family]["years"][str(year)]
        for base,new in pairs:
            key=f"{family}/{year}/{new}-{base}"
            audit_diagnostic(frame,base,new,reported["comparisons"][new+"_minus_"+base],all_a,"etf_z_late" if new=="E2" else exposure,key)
        frames.append(frame)
    full=pd.concat(frames,ignore_index=True)
    views={"all_evaluation":full,"without_2026":full.loc[full.date.dt.year<2026],"filled_only":full.loc[full.entry_filled]}
    if family in {"OPTION","JOINT"}:
        views["exclude_roll"]=full.loc[~truth(full.opt_roll)]
        views["active_pair_only"]=full.loc[truth(full.opt_active_pair)]
        assert len(views["exclude_roll"])==len(full)
        assert len(views["active_pair_only"])==1
    for view,frame in views.items():
        all_a=int((truth(model.A)&model.date.dt.year.isin(frame.date.dt.year.unique())).sum())
        for base,new in pairs:
            key=f"{family}/{view}/{new}-{base}"
            audit_diagnostic(frame,base,new,analysis["families"][family]["comparisons"][view][new+"_minus_"+base],all_a,"etf_z_late" if new=="E2" else exposure,key)
    summary[family]={"n":len(full),"without_2026_n":len(views["without_2026"]),"active_pair_n":len(views["active_pair_only"]) if "active_pair_only" in views else None,"roll_exclusion_changes_sample":False if "exclude_roll" in views else None,"main":{new+"_minus_"+base:{k:analysis["families"][family]["comparisons"]["all_evaluation"][new+"_minus_"+base][k] for k in ["mse_improvement","allocation_difference_per_evaluable_A","base_allocation","new_allocation","base_keep_rate","new_keep_rate","cluster_count","cluster_bootstrap"]} for base,new in pairs}}
option_coefs={str(year):float(dict(zip(results[("OPTION","O1",year)]["columns"],results[("OPTION","O1",year)]["standardized_coefficients"]))["opt_delta_put"]) for year in [2023,2024,2025,2026]}
assert all(v<0 for v in option_coefs.values())
required=[EX/"protocols/design.json",EX/"src/analyze_fixed.py",EX/"src/build_option_features.py",EX/"src/prepare_etf.py",EX/"src/resume_etf.py",EX/"src/run_fixed.py",EX/"src/assemble_inputs.py",FIXED/"analysis.json",FIXED/"predictions.csv",OUT/"model_inputs.csv",OUT/"calendar.csv",OUT/"labels.csv",OUT/"option_features.csv",OUT/"option_prepared.json",OUT/"source_quality_audit.json",OUT/"option_feature_audit.json",EX/"protocols/input_runner_review.json",EX/"protocols/published_run_inputs.json",OUT/"model_input_preflight.json",OUT/"model_input_lineage.json",*slots]
source_hashes={p.relative_to(ROOT).as_posix():digest(p) for p in required}
run_lock=read(EX/"protocols/published_run_inputs.json")
for path in [EX/"src/run_fixed.py",EX/"src/assemble_inputs.py",EX/"src/analyze_fixed.py",EX/"src/build_option_features.py",OUT/"model_inputs.csv"]:
    assert digest(path)==run_lock[path.relative_to(ROOT).as_posix()]["sha256"]
report={"status":"PASS", "scope":"Independent saved-result reconstruction only; no refitting/source acquisition", "source_hashes":source_hashes,"checks":{"fit_slots":28,"success":28,"technical_failures":0,"saved_prediction_rows_reconstructed":score_checks,"diagnostic_comparisons_recomputed":diagnostic_checks,"normal_equation_max_abs_saved_coef_residual":normal_equation_max,"means_scales_intercept_train_scores_q75_keep_test_scores_csv":"MATCH","annual_source_and_maturity_cutoffs":"STRICTLY_BEFORE_JAN1","identical_family_train_test_rows":"MATCH","all_metric_return_decompositions_counts_views":"MATCH","cluster_bootstrap_2000_seed13_intervals":"MATCH","LOO_equalcluster_largestcluster_nonoverlap_matched_participation":"MATCH","published_run_source_and_inputs_hashes":"MATCH"},"summary":summary,"option_feature_coefficients":option_coefs,"interval_contains_zero":ci_zero,"interpretation_constraints":["ETF E2 is only the prespecified timing counterevidence; cannot choose it as a replacement winner after observing results.","Option O1 delta-put coefficients are negative in all4years, contrary to prespecified larger-delta predicts greater loss; fixed positive-direction mechanism is not supported even if a saved diagnostic allocation point estimate is positive.","J1 adds ETF and option jointly; its increment does not isolate either input's marginal contribution.","Option and joint active-pair-only views have1opportunity and1cluster; these cannot support independent active-liquidity validation.","No-roll view equals full available sample and is not independent replication or meaningful robustness variation.","Intervals are descriptive development intervals under adaptive selection; historical publication/adjustment chains remain unverified.","Attempt-return allocation decompositions are not continuous-account returns or annual economic-goal acceptance."],"new_fits":0,"new_source_calls":0,"new_return_labels":0,"blocking_issues":[],"review_script":Path(__file__).relative_to(ROOT).as_posix(),"review_script_sha256":digest(__file__)}
with (OUT/"independent_review.json").open("x",encoding="utf-8",newline="\n") as stream:
    json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
    stream.write("\n")
print(json.dumps({"status":"PASS","slots":28,"prediction_rows":score_checks,"diagnostic_checks":diagnostic_checks,"option_coefficients":option_coefs,"main_interval_contains_zero":{k:v for k,v in ci_zero.items() if "/all_evaluation/" in k},"n":{k:v["n"] for k,v in summary.items()}}))
