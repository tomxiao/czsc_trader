"""Pure synthetic independent agreement proof; no data/provider or accounts."""
import copy
from hashlib import sha256
import importlib
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

WORK = Path(__file__).resolve().parent
ROOT = next(p for p in WORK.parents if (p/"pyproject.toml").exists())
PREFIX = "_s013_agreement_independent"
package = types.ModuleType(PREFIX)
package.__path__ = [str(WORK)]
sys.modules[PREFIX] = package
audit = importlib.import_module(PREFIX+".audit_agreement")
primary = importlib.import_module(PREFIX+".agreement_kernel")
native_prefix = PREFIX+"_native"
for name, directory in ((native_prefix, WORK/"strategy_runtime"), (native_prefix+".strategies", WORK/"strategy_runtime/strategies")):
    mod = types.ModuleType(name)
    mod.__path__ = [str(directory)]
    sys.modules[name] = mod
native = importlib.import_module(native_prefix+".strategies.model_agreement")


def fixture():
    rng = np.random.default_rng(8098)
    days = pd.DatetimeIndex([day for year in range(2020, 2027) for day in pd.bdate_range(str(year)+"-01-02", periods=90 if year == 2020 else 45)])
    features = pd.DataFrame(rng.normal(size=(len(days), 14)), index=days, columns=audit.FEATURES)
    target = .003+.004*features.iloc[:, 0].to_numpy()+rng.normal(0, .005, len(days))
    ends = pd.Series(days, index=days).shift(-5)
    target[-5:] = np.nan
    labels = pd.DataFrame({"return_4": target, "label_end_return_4": ends}, index=days)
    labels.iloc[87, 1] = days[91]  # deliberately late old observation
    features.iloc[103, 4] = np.nan
    return features, labels


def history_from_scores(features, scores, traces, H):
    # Primary original clock is called only to produce synthetic test evidence;
    # the independent audit itself never calls primary model/clock code.
    frame = native.episode_history(scores.vote_score, features.index, H)
    yearly = {row["year"]: row for row in traces["joint_ridge"]}
    frame["common14_available"] = features.notna().all(axis=1)
    frame["confirmation_score"] = features.confirmation_score
    frame["train_n"] = [yearly.get(t.year, {}).get("train_n", 0) for t in frame.index]
    frame["train_max_maturity"] = [yearly.get(t.year, {}).get("max_maturity") for t in frame.index]
    frame["all_models_available"] = scores.all_available
    frame["positive_vote_count"] = scores.positive_votes
    frame["agreement_entry_score"] = scores.vote_score
    for name in audit.MODELS:
        frame[name+"_score"] = scores[name]
        frame[name+"_available"] = np.isfinite(scores[name])
    return frame


def run():
    checks, refusals, certificates, policy_certificates = [], [], [], []
    def reject(name, call):
        try:
            call()
        except (ValueError, TypeError):
            refusals.append(name)
        else:
            raise AssertionError("accepted invalid: "+name)
    rng = np.random.default_rng(98)
    tx = rng.uniform(-.5, .5, (180, 14))
    tx[:, 8] = 0
    target = .02+.03*tx[:, 0]-.02*tx[:, 13]+rng.normal(0, .003, 180)
    for alpha in (1., 10., 100.):
        pred, proof = primary.fit_joint(tx, target, tx[:15], alpha)
        certificates.append(audit.verify_joint_fit(tx, target, tx[:15], pred, proof, alpha))
        assert proof["coefficients"][9] == 0
        assert abs(proof["coefficients"][1]) > .001 and abs(proof["coefficients"][14]) > .001
    for value in (-.003, 0., .003):
        pred, proof = primary.fit_joint(tx, np.full(180, value), tx[:15])
        certificates.append(audit.verify_joint_fit(tx, np.full(180, value), tx[:15], pred, proof))
    checks.append("joint all14 unpenalized intercept, scalar stationarity/prediction, alpha endpoints and constant targets")
    pred, proof = primary.fit_joint(tx, target, tx[:15])
    for key in ("coefficients", "gradient", "objective", "ridge_alpha", "intercept_penalized", "feature_count"):
        corrupt = copy.deepcopy(proof)
        if key in ("coefficients", "gradient"):
            corrupt[key][0] += .01
        elif key == "intercept_penalized":
            corrupt[key] = True
        else:
            corrupt[key] += 1
        reject("joint_corrupt_"+key, lambda c=corrupt: audit.verify_joint_fit(tx, target, tx[:15], pred, c))
    reject("joint_train39", lambda: primary.fit_joint(tx[:39], target[:39], tx[:1]))
    reject("joint_13features", lambda: primary.fit_joint(tx[:, :13], target, tx[:1, :13]))
    checks.append("independent final proof rejects beta, all gradients, penalty and objective tampering")
    combinations = list(itertools.product((-1., 0., 1., np.nan), repeat=3))
    axis = pd.bdate_range("2021-01-04", periods=len(combinations))
    model = pd.DataFrame(combinations, index=axis, columns=audit.MODELS)
    voted = primary.aggregate(model)
    certificates.append(audit.verify_votes(voted))
    for i, values in enumerate(combinations):
        finite = all(np.isfinite(values))
        assert bool(voted.all_available.iloc[i]) is finite
        if finite:
            assert voted.positive_votes.iloc[i] == sum(v > 0 for v in values)
        else:
            assert pd.isna(voted.vote_score.iloc[i])
    false_vote = voted.copy()
    false_vote.loc[axis[-1], ["positive_votes", "vote_score"]] = [2., 1.]
    reject("two_of_three_rescue_when_third_NA", lambda: audit.verify_votes(false_vote))
    false_vote = voted.copy()
    zero = next(i for i, row in enumerate(combinations) if row == (0., 0., 0.))
    false_vote.loc[axis[zero], ["positive_votes", "vote_score"]] = [3., 1.]
    reject("zero_vote_not_positive", lambda: audit.verify_votes(false_vote))
    checks.append("64 strict-positive/all3-availability truth cells; no two-available fallback or zero-as-positive")
    features, labels = fixture()
    scores, traces = primary.forecasts(features, labels)
    certificates.append(audit.verify(features, labels, scores, traces))
    assert scores.loc[features.index.year == 2020, list(audit.MODELS)].isna().all().all()
    assert scores.iloc[-5:].all_available.all()
    for H in (1, 4, 60):
        history = history_from_scores(features, scores, traces, H)
        policy_certificates.append(audit.verify_policy(history, scores, features, traces, None, H))
    checks.append("six independent mature annual all14 ECDFs plus full CART/Huber audits, common H endpoints and unknown-truth tail admission")
    for year in (2021, 2024, 2026):
        first = features.index[features.index.year == year][0]
        keep = features.index <= first
        pf, pl = features.loc[keep], labels.loc[keep]
        ps, pt = primary.forecasts(pf, pl)
        certificates.append(audit.verify(pf, pl, ps, pt))
        pd.testing.assert_frame_equal(ps, scores.loc[keep], check_exact=False, atol=1e-14, rtol=0)
        np.testing.assert_array_equal(ps.vote_score, scores.loc[keep].vote_score)
        ph = history_from_scores(pf, ps, pt, 4)
        policy_certificates.append(audit.verify_policy(ph, ps, pf, pt, None, 4))
        fullh = history_from_scores(features, scores, traces, 4)
        pd.testing.assert_frame_equal(ph, fullh.loc[keep], check_exact=False, atol=1e-14, rtol=0)
    first = features.index[features.index.year == 2024][0]
    keep = features.index <= first
    future_labels = labels.copy()
    future_labels.loc[future_labels.label_end_return_4 >= first, "return_4"] = .7
    altered, at = primary.forecasts(features.loc[keep], future_labels.loc[keep])
    certificates.append(audit.verify(features.loc[keep], future_labels.loc[keep], altered, at))
    pd.testing.assert_frame_equal(altered, scores.loc[keep], check_exact=False, atol=1e-14, rtol=0)
    future_features = features.copy()
    future_features.loc[features.index > first] *= -99
    changed, ct = primary.forecasts(future_features, labels)
    certificates.append(audit.verify(future_features, labels, changed, ct))
    pd.testing.assert_frame_equal(changed.loc[keep], scores.loc[keep], check_exact=True)
    checks.append("prefix exact admission and policy; future truth/current future features cannot change earlier model/vote")
    for alpha, multiple, depth, leaf in ((1., .5, 1, 20), (100., 3., 4, 120)):
        ss, st = primary.forecasts(features, labels, ridge_alpha=alpha, huber_multiple=multiple, tree_depth=depth, minimum_leaf=leaf)
        certificates.append(audit.verify(features, labels, ss, st, ridge_alpha=alpha, huber_multiple=multiple, tree_depth=depth, minimum_leaf=leaf))
        if leaf == 120:
            assert ss.loc[features.index.year == 2021, "joint_ridge"].notna().any()
            assert ss.loc[features.index.year == 2021, "cart_net"].isna().all()
            assert ss.loc[features.index.year == 2021, "vote_score"].isna().all()
    # Explicit zero-scale varied Huber: the two available models cannot rescue it.
    zero_mad = labels.copy()
    zero_mad.return_4 = np.where(np.arange(len(labels)) % 20 == 0, .02, .003)
    zero_mad.loc[zero_mad.label_end_return_4.isna(), "return_4"] = np.nan
    zs, zt = primary.forecasts(features, zero_mad)
    certificates.append(audit.verify(features, zero_mad, zs, zt))
    assert zs.loc[features.index.year > 2020, "huber_net"].isna().all()
    assert zs.vote_score.isna().all()
    # Featureless current year is never a future test-count eligibility condition.
    missing = features.copy()
    missing.loc[missing.index.year == 2021] = np.nan
    ms, mt = primary.forecasts(missing, labels)
    certificates.append(audit.verify(missing, labels, ms, mt))
    assert mt["joint_ridge"][0]["available"] and mt["huber_net"][0]["available"]
    assert ms.loc[features.index.year == 2021].vote_score.isna().all()
    checks.append("full parameter endpoint support, variedMAD0 all-NA vote, and no future current-year count gate")
    # Direct pattern exercises missing/negative votes while held, positive expiry
    # and cross-year age: none creates individual member positions.
    pa = pd.bdate_range("2020-12-30", periods=75)
    pf = pd.DataFrame(np.ones((75, 14)), index=pa, columns=audit.FEATURES)
    raw = pd.DataFrame(np.ones((75, 3)), index=pa, columns=audit.MODELS)
    raw.iloc[4] = [-1., -1., -1.]
    raw.iloc[5, 2] = np.nan
    ps = primary.aggregate(raw)
    pt = {name: [{"year": year, "train_n": 50, "max_maturity": "2020-12-29T00:00:00"} for year in range(2021, 2027)] for name in audit.MODELS}
    for H in (1, 4, 60):
        ph = history_from_scores(pf, ps, pt, H)
        policy_certificates.append(audit.verify_policy(ph, ps, pf, pt, None, H))
        assert ph.iloc[:2].target_position.eq(0).all()
        if H == 4:
            assert ph.iloc[4].signal_reason == "hold" and ph.iloc[5].signal_reason == "hold"
            assert ph.iloc[6].signal_reason == "expiry" and ph.iloc[7].signal_reason == "entry"
        fake = ph.copy()
        fake.iloc[3, fake.columns.get_loc("policy_age")] += 1
        reject("wrong_clock_age_H"+str(H), lambda f=fake, h=H: audit.verify_policy(f, ps, pf, pt, None, h))
    ph = history_from_scores(pf, ps, pt, 4)
    daily = pd.DataFrame({"Date": pa, "Close": 10.+np.arange(75)*.01})
    ph["close"] = daily.Close.to_numpy()
    policy_certificates.append(audit.verify_policy(ph, ps, pf, pt, {"daily": daily}, 4))
    reject("close_missing_source", lambda: audit.verify_policy(ph, ps, pf, pt, None, 4))
    fake = ph.copy()
    fake.loc[pa[6], "target_position"] = 1.
    reject("same_expiryday_reentry", lambda: audit.verify_policy(fake, ps, pf, pt, {"daily": daily}, 4))
    checks.append("one causal H age across years, hold through missing/negative scores, positive expiry has no reentry, emitted close independently mapped")
    for name, modify in (("cdf", lambda t: t["joint_ridge"][0]["train_cdfs"][0].__setitem__(0, -999.)),
                         ("maturity", lambda t: t["joint_ridge"][0].__setitem__("max_maturity", "2030-01-01T00:00:00")),
                         ("futuretestgate", lambda t: t["joint_ridge"][0].__setitem__("future_test_count_gate", True)),
                         ("cartthreshold", lambda t: t["cart_net"][0]["tree"]["candidates"][0].__setitem__("threshold", 99.)),
                         ("huberdelta", lambda t: t["huber_net"][0]["fit"].__setitem__("delta", .9))):
        bad = copy.deepcopy(traces)
        modify(bad)
        reject("trace_"+name, lambda b=bad: audit.verify(features, labels, scores, b))
    for values in ((1,1.345,2,40),(0.,1.345,2,40),(101.,1.345,2,40),(10.,.49,2,40),(10.,3.1,2,40),(10.,1.345,True,40),(10.,1.345,0,40),(10.,1.345,5,40),(10.,1.345,2,19),(10.,1.345,2,121)):
        a, m, d, leaf_size = values
        reject("typed_domain_"+str(values), lambda a=a,m=m,d=d,leaf_size=leaf_size: audit.verify(features, labels, scores, traces, ridge_alpha=a,huber_multiple=m,tree_depth=d,minimum_leaf=leaf_size))
    bad_labels = labels.copy()
    bad_labels.iloc[0, 1] = labels.index[0]
    reject("nonfuture_maturity", lambda: audit.verify(features, bad_labels, scores, traces))
    bad_labels = labels.copy()
    bad_labels.iloc[0, 1] = pd.NaT
    reject("unpaired_label", lambda: audit.verify(features, bad_labels, scores, traces))
    bad_features = features.copy()
    bad_features.iloc[0, 0] = np.inf
    reject("infinite_feature", lambda: audit.verify(bad_features, labels, scores, traces))
    reject("feature_order", lambda: audit.verify(features.iloc[:, ::-1], labels, scores, traces))
    reject("duplicate_dates", lambda: audit.verify_votes(pd.concat([voted.iloc[:1], voted])))
    reject("tzdates", lambda: audit.verify_votes(voted.set_axis(voted.index.tz_localize("UTC"))))
    reject("intraday_axis", lambda: audit.verify_votes(voted.set_axis(voted.index+pd.Timedelta(hours=1))))
    reject("score_schema", lambda: audit.verify_votes(voted.iloc[:, ::-1]))
    reject("booldtype", lambda: audit.verify_votes(voted.assign(all_available=voted.all_available.astype(int))))
    reject("Hbool", lambda: audit.verify_policy(ph, ps, pf, pt, {"daily": daily}, True))
    checks.append("tampered models/training provenance/availability/clock rejected; finite typed domains and exact dates/schema enforced")
    # Reuse only the explicitly synthetic fixture generator, then audit actual
    # native prepare/history/calculate outputs with the independent verifiers.
    spec = importlib.util.spec_from_file_location(PREFIX+"_fixture", WORK/"native_checks.py")
    synthetic_fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synthetic_fixture)
    daily_native, execution_native, bars_native, signals_native = synthetic_fixture.fixture()
    execution_raw, bars_raw = execution_native.copy(), bars_native.copy()
    for col in ("Open", "High", "Low", "Close"):
        execution_raw[col] /= .2803
        bars_raw[col] /= .2803
    nativeinputs = {"daily":daily_native,"execution":execution_raw,"intraday":bars_raw}
    nativeparams = dict(native.PARAMETERS)
    nf, price = native.model_inputs(nativeinputs, signals_native, nativeparams)
    nh, nl, ns, nt = native.history_from_model(nf, price, signals_native, nativeparams)
    certificates.append(audit.verify(nf, nl, ns, nt))
    policy_certificates.append(audit.verify_policy(nh, ns, nf, nt, None, 4))
    actualh = native.AgreementNet(ParameterSet(nativeparams)).calculate_history(nativeinputs, signals_native)
    policy_certificates.append(audit.verify_policy(actualh, ns, nf, nt, nativeinputs, 4))
    pd.testing.assert_frame_equal(actualh.drop(columns="close"), nh, check_exact=True)
    for H in (1, 4, 60):
        reported = native.net_labels(price, signals_native, H)
        observed = price.index.tolist()
        locations = {day:i for i, day in enumerate(observed)}
        opens = price.Open.tolist()
        for i, day in enumerate(signals_native):
            pos = locations[day]
            end = pos+1+H
            if end < len(observed):
                assert reported.label_end_return_4.iloc[i] == observed[end]
                assert reported.return_4.iloc[i] == float(opens[end]/opens[pos+1]*(.999/1.001)-1)
            else:
                assert pd.isna(reported.return_4.iloc[i]) and pd.isna(reported.label_end_return_4.iloc[i])
    checks.append("actual native synthetic model_inputs/history/calculate independently audited, OPEN T+1+H fee labels exact, runtime full table equality")
    copies = {"audit_tree.py": ROOT/".tmp/s013-new-goal/cart_net/audit_tree.py", "audit_huber.py": ROOT/".tmp/s013-new-goal/huber_net/audit_huber.py",
              "tree_kernel.py": ROOT/".tmp/s013-new-goal/cart_net/tree_kernel.py", "huber_kernel.py": ROOT/".tmp/s013-new-goal/huber_net/huber_kernel.py"}
    for name, path in copies.items():
        assert (WORK/name).read_bytes() == path.read_bytes()
    for name in ("tree_kernel.py", "huber_kernel.py", "agreement_kernel.py"):
        assert (WORK/name).read_bytes() == (WORK/"strategy_runtime/strategies"/name).read_bytes()
    checks.append("frozen96/97 independent verifiers and primary kernels byteexact; runtime joint/aggregate exact")
    output = {"status":"PASS", "synthetic_only":True,"real_inputs_read":0,"new_accounts":0,"experiments_allocated":0,
              "checks":checks,"check_count":len(checks),"rejections":refusals,"rejection_count":len(refusals),"truth_cells":64,
              "model_audit_cases":len(certificates),"policy_audit_cases":len(policy_certificates),
              "source_sha256":{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ("audit_agreement.py","audit_checks.py","audit_tree.py","audit_huber.py","agreement_kernel.py","tree_kernel.py","huber_kernel.py")},
              "adapter_sha256":sha256((WORK/"strategy_runtime/strategies/model_agreement.py").read_bytes()).hexdigest(),
              "copied_sha256":{name:sha256(path.read_bytes()).hexdigest() for name,path in copies.items()},
              "limitations":["Synthetic only; no forecast efficacy, alpha or economic gate result", "Huber final stationarity/provenance only, no full IRLS trajectory or unique-intercept claim", "Same14 inputs correlate model votes; vote1 is admission not expected net return", "EX018 virtual holding votes are different from currentforecast votes plus one shared H clock", "Original features and OPEN labels need frozen EX080 audit before model audit"],
              "certificates":certificates,"policy_certificates":policy_certificates}
    (WORK/"audit_checks.json").write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print({"status":"PASS","checks":len(checks),"rejections":len(refusals),"models":len(certificates),"policy":len(policy_certificates),"real_inputs":0})


if __name__ == "__main__":
    run()
