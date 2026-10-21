"""Disclosed EX002 follow-up: timing decomposition, genuine ablation and counterchecks."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
import json
import os

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from component_study import (load_data, make_labels, fold_indices, standardize,
                             ridge, corr, bootstrap_indices, ratio_sum_ci, evaluate_label,
                             save_json)

HERE = Path(__file__).resolve().parent.parent
WORK = Path.cwd() / "research/S015/assets/runs/EX002_20261021/daily_information"


def check_model(x, columns, y, end, baseline_names, full_names, dates, label):
    chosen = list(dict.fromkeys(baseline_names + full_names))
    ci = [columns.index(s) for s in chosen]
    bi = [chosen.index(s) for s in baseline_names]
    actual, predicted, baseline, row_dates, fold_ids = [], [], [], [], []
    for fi, (train, test) in enumerate(fold_indices(y, end)):
        tx, vx = standardize(x[train][:, ci], x[test][:, ci])
        actual.extend(y[test])
        predicted.extend(ridge(tx, y[train], vx))
        baseline.extend(ridge(tx[:, bi], y[train], vx[:, bi]))
        row_dates.extend(dates[test])
        fold_ids.extend(np.full(len(test), fi))
    yy, p, b = map(np.asarray, (actual, predicted, baseline))
    date_array, fi_array = np.asarray(row_dates), np.asarray(fold_ids)
    bl, pl = (b-yy)**2, (p-yy)**2
    num = bl-pl
    def record(mask):
        return {"n": int(mask.sum()), "gain": float(num[mask].sum()/bl[mask].sum())}
    # Diagnostic exclusion, explicitly post-selection; never a strategy date filter.
    retain = np.ones(len(yy), dtype=bool)
    retain[np.argsort(np.abs(yy))[-5:]] = False
    years = {year: record(np.char.startswith(date_array.astype(str), year)) for year in ("2025", "2026")}
    return {"label": label, "baseline_features": baseline_names, "added_features": full_names,
        "n": len(yy), "gain": float(num.sum()/bl.sum()),
        "ci10": ratio_sum_ci(num, bl, bootstrap_indices(len(yy),10)),
        "ci20": ratio_sum_ci(num, bl, bootstrap_indices(len(yy),20)),
        "years": years, "folds": [record(fi_array==fi) for fi in range(4)],
        "without_largest_5_labels": record(retain)}


def ablation(job):
    label, x, columns, y, end, dates, groups = job
    with threadpool_limits(limits=1):
        simple = ["range20"] if label=="range3" else ["vol20"] if label=="downside3" else ["ret5","vol20"]
        all_names = list(dict.fromkeys(simple + sum(groups.values(), [])))
        rows=[]
        for name, removed in groups.items():
            # Keep mandatory simple baseline even if it overlaps removed mechanism group.
            remaining=[s for s in all_names if s not in removed or s in simple]
            result=check_model(x,columns,y,end,remaining,all_names,dates,label)
            result["removed_group"]=name
            result["meaning"]="Positive gain means restoring the removed group improves the full model versus all-minus-group."
            rows.append(result)
        return rows


def main():
    for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
        os.environ[key]="1"
    d,_=load_data()
    features=pd.read_csv(WORK/"features.csv").drop(columns="Date")
    columns=features.columns.tolist()
    x=features.iloc[75:].to_numpy()
    dates=d.Date.astype(str).str[:10].to_numpy()[75:]
    labels,ends=make_labels(d)
    labels=labels.iloc[75:].reset_index(drop=True)
    ends={k:v[75:] for k,v in ends.items()}
    gap=(d.Open.shift(-1)/d.Close-1).to_numpy()[75:]
    common=(d.Open.shift(-2)/d.Close-1).to_numpy()[75:]
    valid=np.isfinite(common)
    np.testing.assert_allclose(common[valid],(1+gap[valid])*(1+labels.open1.to_numpy()[valid])-1,rtol=1e-12,atol=1e-14)
    jobs=[("entry_gap",x,columns,gap,np.arange(len(d),dtype=float)[75:]+1,dates),
          ("common_exit1",x,columns,common,np.arange(len(d),dtype=float)[75:]+2,dates)]
    output={}
    with ProcessPoolExecutor(max_workers=8,mp_context=get_context("spawn")) as pool:
        for name,result,arrays in pool.map(evaluate_label,jobs):
            output[name]=result
            np.savez_compressed(WORK/f"followup_oos_{name}.npz",**arrays)
    group_defs={
        "continuation":["ret5","ret20","ret60","efficiency20","efficiency60","ma_dev20"],
        "reversal":["ret1","body","gap","close_location","vwap_dev","ma_dev5"],
        "risk":["vol5","vol20","range_value","range20","amount_z20","volume_change1"],
        "limited_tsfresh":[s for s in columns if s.startswith("ts20__") and any(k in s for k in ("autocorrelation","skewness","linear_trend"))],
    }
    jobs=[(label,x,columns,labels[label].to_numpy(),ends[label],dates,group_defs)
          for label in ("open1","open3","open5","open10","range3","downside3")]
    with ProcessPoolExecutor(max_workers=8,mp_context=get_context("spawn")) as pool:
        abl=[r for part in pool.map(ablation,jobs) for r in part]
    counter=[]
    model_checks=[
        ("open1",["ret5","vol20","ret1"],["vwap_dev"]),
        ("open1",["ret5","vol20","ret1","body","close_location"],["vwap_dev"]),
        ("open1",["ret5","vol20","vwap_dev"],["body","ret1","close_location"]),
        ("range3",["range20","vol20"],["range5"]),
        ("range3",["range20","vol20","range5"],["range_value"]),
        ("downside3",["vol20","range20"],["range5"]),
        ("open3",["ret5","vol20"],["ts20__range__linear_trend__attr_\"slope\""]),
        ("open5",["ret5","vol20"],["ts20__range__linear_trend__attr_\"slope\""]),
    ]
    for label,base,added in model_checks:
        counter.append(check_model(x,columns,labels[label].to_numpy(),ends[label],base,added,dates,label))
    # Neighbour features are diagnosed as one information family, not new independent discoveries.
    extra=pd.DataFrame(index=features.index)
    for n in (3,5,7,10):
        extra[f"follow_range{n}"]=((d.High-d.Low)/d.Close).rolling(n).mean()
    for n in (1,2,3):
        extra[f"follow_pressure{n}"]=features.vwap_dev.rolling(n).mean()
    extended=pd.concat([features,extra],axis=1)
    xx=extended.iloc[75:].to_numpy()
    cc=extended.columns.tolist()
    neighbour=[]
    for name in extra:
        label="range3" if "range" in name else "open1"
        base=["range20"] if label=="range3" else ["ret5","vol20"]
        neighbour.append(check_model(xx,cc,labels[label].to_numpy(),ends[label],base,[name],dates,label))
    # Fixed training orientations, contrasts centered inside each fold reduce between-fold drift.
    contrast=[]
    for label,names in (("open1",["vwap_dev","body","ret1","close_location"]),
                        ("range3",["range_value","range5","range20"]),
                        ("downside3",["range5","range10","range20"])):
        data=np.load(WORK/f"oos_{label}.npz")
        yy=data["y"]
        for name in names:
            j=columns.index(name)
            fold_rows=[]
            for fi in range(4):
                mask=data["fold"]==fi
                high=mask&(data["groups"][:,j]==1)
                low=mask&(data["groups"][:,j]==-1)
                fold_rows.append({"fold":fi,"n":int(mask.sum()),"high_n":int(high.sum()),"low_n":int(low.sum()),
                    "delta":float(yy[high].mean()-yy[low].mean()) if high.sum() and low.sum() else None,
                    "raw_spearman":corr(data["scores"][mask,j],yy[mask])})
            valid_rows=[r for r in fold_rows if r["delta"] is not None]
            avg=sum(r["n"]*r["delta"] for r in valid_rows)/sum(r["n"] for r in valid_rows)
            contrast.append({"label":label,"feature":name,"folds":fold_rows,"within_fold_weighted_delta":float(avg)})
    original=json.loads((WORK/"study_results.json").read_text(encoding="utf-8"))
    all_rows=[r for result in list(original["results"].values())+list(output.values()) for r in result["rows"]]
    p=np.array([r["raw_shift_p"] for r in all_rows])
    order=np.argsort(p)
    q=np.empty(len(p))
    q[order]=np.minimum(1,np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1])
    adjusted=[{"label":r["label"],"feature":r["feature"],"q_all_1092":float(v)} for r,v in zip(all_rows,q,strict=True)]
    result={"additional_labels":output,"timing_decomposition":"common_exit1=(1+entry_gap)*(1+open1)-1 verified exactly on common finite dates; pooled close/open label difference alone cannot locate timing.",
        "ablation":abl,"countermodels":counter,"neighbours":neighbour,"within_fold_contrasts":contrast,
        "combined_feature_label_tests":len(all_rows),"combined_q":adjusted,
        "extra_model_comparisons":len(abl)+len(counter)+len(neighbour),
        "caveat":"All follow-up choices disclosed after the first 910 comparisons. No independent confirmation. Added model comparisons increase selection history beyond feature-label q-values."}
    save_json(WORK/"followup_results.json",result)
    print(json.dumps({"followup_completed":True,"combined_feature_label_tests":len(all_rows),"extra_models":result["extra_model_comparisons"]}))


if __name__=="__main__":
    with threadpool_limits(limits=1):
        main()
