"""Supplement raw-price floor evidence with conservative full-calendar bounds."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from inputs import ROOT, EXPERIMENT, RUN, load


def main():
    target = EXPERIMENT / "others/cap_audit.json"
    if target.exists():
        raise RuntimeError("Preserve completed supplement")
    data, _, _, _, _, _ = load()
    raw, limits = data["stock.unadjusted_daily"], data["security.price_limits"]
    touch = raw.Low.le(limits.DownLimit + .005)
    recovery = touch & (raw.Close - limits.DownLimit).abs().gt(.005)
    market = pd.read_csv(RUN / "features.csv")
    assert np.array_equal(touch, market.lower_touch.eq(1))
    assert np.array_equal(recovery, market.lower_recovery.eq(1))
    result = json.loads((EXPERIMENT / "others/cap_diagnostics_result.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(RUN / "predictions.csv")
    for row in result["annual"]:
        p = predictions.loc[predictions.horizon.eq(row["horizon"]) & predictions.year.eq(row["year"])]
        a, b = p.loc[p.lower_recovery.eq(1)], p.loc[p.lower_close.eq(1)]
        if len(a) and len(b):
            assert abs(a.net_return.mean() - b.net_return.mean() - row["recovery_increment"]) < 1e-12
        assert row["touch_n"] == int(p.lower_touch.sum())
    first_episodes = []
    for (h, year), p in predictions.loc[predictions.horizon.isin([3, 5, 10]) & predictions.lower_touch.eq(1)].groupby(["horizon", "year"]):
        p = p.sort_values("signal")
        episode = p.signal.diff().gt(10).cumsum()
        first = p.groupby(episode).head(1)
        first_episodes.append({"horizon":int(h),"year":int(year),"episodes":len(first),
            "first_origins":first.signal_date.tolist(),"first_touch_net_mean":float(first.net_return.mean())})
    for row in result["leave_episode_out"]:
        p = predictions.loc[predictions.horizon.eq(row["horizon"]) & predictions.year.eq(row["year"]) & predictions.lower_touch.eq(1)]
        retained = p.loc[~p.signal_date.isin(row["removed_dates"])]
        assert len(retained) == row["remaining_n"]
        if len(retained):
            assert abs(retained.net_return.mean() - row["remaining_touch_mean"]) < 1e-12
    output = {"status":"PASS","checks":["full_raw_price_floor_flags","parent_recovery_differences","leave_episode_out_means","full_calendar_entry_count_bounds"],
        "all_calendar_signals":len(market),"all_lower_touch_count":int(touch.sum()),"all_lower_recovery_count":int(recovery.sum()),
        "all_touch_sole_entry_frequency_bound":60*int(touch.sum())/len(market),
        "all_recovery_sole_entry_frequency_bound":60*int(recovery.sum())/len(market),
        "warmup_note":"Original descriptive result counts38/20after60session warmup. This audit additionally includes all first60sessions to make the strongest conservative count upper bound40/21; both counts preserved.",
        "first_touch_per_episode":first_episodes,
        "qualification":"Bound assumes each new entry requires a fresh event on completedT. It does not reject combining this event with other entries and is not an account frequency measurement.",
        "manifest":[{"path":p.relative_to(ROOT).as_posix(),"sha256":sha256(p.read_bytes()).hexdigest()} for p in
            (EXPERIMENT/'protocols/cap_diagnostics.json',EXPERIMENT/'src/cap_diagnostics.py',EXPERIMENT/'others/cap_diagnostics_result.json')]}
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in output.items() if k not in ('manifest','first_touch_per_episode')},ensure_ascii=False))


if __name__ == "__main__":
    main()
