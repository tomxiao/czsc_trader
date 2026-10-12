"""No real inputs, market IO or published experimental fits."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import stage2_models as m


def fixture():
    rng = np.random.default_rng(13)
    axis = pd.bdate_range("2020-01-02", "2022-12-30")
    f = pd.DataFrame(rng.normal(size=(len(axis),14)), index=axis, columns=m.FEATURES)
    f["g1"], f["g2"] = rng.normal(size=(2,len(axis)))
    l = pd.DataFrame(index=axis)
    l["l0"] = rng.normal(.001,.02,len(axis))
    l["l1"] = l.l0 * .9 + .0001
    for c in ("end_l0","end_l1"):
        l[c] = pd.Series(axis,index=axis).shift(-5)
    l.loc[l.end_l0.isna(),["l0","l1"]] = np.nan
    a = pd.DataFrame({"release_date":l.end_l1,"filled":True,"closed":l.l1.notna(),"occupation_days":5},index=axis)
    return f,l,a


def run():
    checks = []
    def check(name, predicate):
        if not predicate:
            raise AssertionError(name)
        checks.append(name)
    f,l,a = fixture()
    ref = m.forecasts(f,l,groups=("A","B","C","D"),common_groups=("B","C"))
    check("exact_two_labels_four_groups_two_year_16_fits",ref["fit_count"] == 16)
    check("strict_maturity_shared_training",all(pd.Timestamp(item["latest_maturity"])<pd.Timestamp(item["first_test_T"]) for item in ref["fit_years"].values() if item.get("train_n")))
    check("tail_prediction_ignores_unknown_label",ref["scores"].iloc[-1].notna().all())
    f2,l2 = f.copy(),l.copy()
    future = f.index >= "2022-02-01"
    f2.loc[future] *= -4000
    l2.loc[future,["l0","l1"]] *= -4000
    changed = m.forecasts(f2,l2,groups=("A","B","C","D"),common_groups=("B","C"))
    pd.testing.assert_frame_equal(ref["scores"].loc[~future],changed["scores"].loc[~future])
    check("future_feature_and_label_change_preserves_past_predictions",True)
    short = f.index <= "2022-02-01"
    prefix = m.forecasts(f.loc[short],l.loc[short],groups=("A","B","C","D"),common_groups=("B","C"))
    pd.testing.assert_frame_equal(ref["scores"].loc[short],prefix["scores"])
    check("prefix_has_same_predictions_no_future_test_count_gate",True)
    nan_future = f.copy()
    nan_future.loc[f.index >= "2022-01-04",:] = np.nan
    sparse = m.forecasts(nan_future,l,groups=("A",),common_groups=())
    check("one_valid_test_T_does_not_block_training_or_prediction",sparse["scores"].loc["2022-01-03"].notna().all())
    missing = f.copy()
    missing.loc["2021-04-01","g2"] = np.nan
    missing_result = m.forecasts(missing,l,groups=("A","C"),common_groups=("C",))
    check("missing_new_data_not_imputed_A_can_predict",missing_result["scores"].loc["2021-04-01","A0"] == ref["scores"].loc["2021-04-01","A0"] and pd.isna(missing_result["scores"].loc["2021-04-01","C0"]))
    # NaN introduced in the test year changes no training row of that year.
    # Independently reconstruct training dates, including both strict maturity masks.
    train_expected = ((f.index.year==2020) & (l.end_l0<pd.Timestamp("2021-01-01"))
                      & (l.end_l1<pd.Timestamp("2021-01-01")) & l[["l0","l1"]].notna().all(axis=1))
    check("training_rows_shared_across_labels_and_groups",ref["fit_years"]["2021"]["train_dates"]==[d.isoformat() for d in f.index[train_expected]])
    tx = np.array([[0.,1.],[1.,1.],[2.,1.]])
    yy = np.array([1.,2.,4.])
    pred, coef = m.ridge(tx,yy,tx)
    z = np.column_stack([np.ones(3),tx])
    penal = np.diag([0.,10.,10.])
    explicit = np.linalg.solve(z.T@z+penal,z.T@yy)
    np.testing.assert_allclose(pred,z@explicit,rtol=0,atol=1e-14)
    check("ridge_alpha10_intercept_unpenalized",True)
    np.testing.assert_array_equal(m.ecdf(np.array([1.,1.,2.,4.]),np.array([0.,1.,3.,5.])),[0.,.25,.75,1.])
    check("train_only_ECDF_ties_and_extremes",True)
    t,v = m.design(f.iloc[:80],f.iloc[80:90],"D")
    check("two_prespecified_interactions_no_fullpool_transform",t.shape==(80,18) and v.shape==(10,18))
    np.testing.assert_allclose(t[:,16],(t[:,14]-.5)*(t[:,1]-.5))
    check("interaction_uses_ranked_centered_range60",True)
    axis = pd.bdate_range("2021-01-01",periods=12)
    positive = pd.Series(1.,index=axis)
    attempts = pd.DataFrame({"release_date":pd.Series(axis,index=axis).shift(-3),"filled":True,"closed":True},index=axis)
    attempts.loc[axis[-3:],"closed"] = False
    choices = m.select_attempts(positive,attempts)
    check("occupation_and_release_day_no_reentry",choices.index[choices.selected].tolist()==[axis[0],axis[4],axis[8]])
    cancelled = attempts.copy()
    cancelled.loc[axis[0],["filled","closed"]] = False
    cancelled.loc[axis[0],"release_date"] = axis[1]
    c = m.select_attempts(positive,cancelled)
    check("unfilled_attempt_still_occupies_until_cancel",c.index[c.selected][1]==axis[2])
    unknown = attempts.copy()
    unknown.loc[axis[0],"release_date"] = pd.NaT
    check("unknown_release_no_fake_end_close",m.select_attempts(positive,unknown).selected.sum()==1)
    for phase in range(5):
        choices = m.select_attempts(positive,attempts,phase)
        check(f"fixed_phase_{phase}_does_not_choose_other_phase",all(np.flatnonzero(choices.selected)%5==phase))
    bad = l.copy()
    bad.iloc[0,bad.columns.get_loc("end_l1")] = bad.index[0]
    try:
        m.forecasts(f,bad)
    except ValueError:
        check("maturity_on_signal_T_rejected",True)
    else:
        raise AssertionError("invalid maturity accepted")
    pan, choices = m.panels(ref["scores"],l,ref["means"],a)
    common = pd.Series(True,index=f.index)
    common.loc["2021-04-01"] = False
    _,masked_choices = m.panels(ref["scores"],l,ref["means"],a,eligible=common)
    check("common_input_mask_precedes_selection_without_future_labels",not masked_choices["A0"]["greedy"].loc["2021-04-01","positive"])
    paired = m.paired_panels(ref["scores"],l,ref["means"],choices,[("A1","A0")])
    check("paired_panels_use_shared_forecast_support",paired["A1-A0"]["all"]["new"]["positive"]["score_n"]==paired["A1-A0"]["all"]["old"]["positive"]["score_n"])
    try:
        m.forecasts(f,l,groups=("A",),max_fits=0)
    except ValueError:
        check("zero_fit_quota_blocks_first_fit",True)
    else:
        raise AssertionError("fitting quota accepted")
    boot = m.paired_bootstrap(ref["scores"],l,ref["means"],choices,[("A1","A0"),("B1","A1")])
    check("bootstrap_500_shared_blocks_without_refits",boot["refits"]==0 and len(boot["pairs"]["A1-A0"]["records"])==500)
    second = m.paired_bootstrap(ref["scores"],l,ref["means"],choices,[("A1","A0")])
    check("bootstrap_fixed_seed_determinism",boot["pairs"]["A1-A0"]==second["pairs"]["A1-A0"])
    return {"status":"PASS","checks":checks,"n":len(checks),"synthetic_only":True,
            "real_data_reads":0,"real_model_fits":0,"full_accounts":0}


if __name__ == "__main__":
    out = run()
    path = Path(__file__).with_name("synthetic_checks.json")
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False))
