"""Explicitly post-hoc parent/recovery and event-episode counterevidence."""
import json
import pandas as pd
from inputs import EXPERIMENT, RUN


def main():
    if (EXPERIMENT / "others/cap_diagnostics_result.json").exists():
        raise RuntimeError("Preserve completed diagnostic")
    features = pd.read_csv(RUN / "features.csv")
    predictions = pd.read_csv(RUN / "predictions.csv")
    mature = predictions.loc[predictions.horizon.isin([3, 5, 10])]
    rows, removals = [], []
    for (h, year), part in mature.groupby(["horizon", "year"]):
        touch = part.loc[part.lower_touch.eq(1)].sort_values("signal").copy()
        control = part.loc[part.lower_touch.eq(0) & part.ret1.le(part.q10)]
        a, b = touch.loc[touch.lower_recovery.eq(1)], touch.loc[touch.lower_close.eq(1)]
        rows.append({"horizon": int(h), "year": int(year), "touch_n": len(touch), "recovery_n": len(a),
            "closed_lower_n": len(b), "control_n": len(control),
            "recovery_mean": float(a.net_return.mean()) if len(a) else None,
            "closed_lower_mean": float(b.net_return.mean()) if len(b) else None,
            "recovery_increment": float(a.net_return.mean() - b.net_return.mean()) if len(a) and len(b) else None,
            "touch_control_difference": float(touch.net_return.mean() - control.net_return.mean()) if len(touch) and len(control) else None})
        if not len(touch):
            continue
        touch["episode"] = touch.signal.diff().gt(10).fillna(True).cumsum()
        for episode, cluster in touch.groupby("episode"):
            retained = touch.loc[touch.episode.ne(episode)]
            removals.append({"horizon": int(h), "year": int(year), "removed_dates": cluster.signal_date.tolist(),
                "removed_n": len(cluster), "remaining_n": len(retained),
                "remaining_touch_mean": float(retained.net_return.mean()) if len(retained) else None,
                "difference_control": float(retained.net_return.mean() - control.net_return.mean()) if len(retained) and len(control) else None})
    full = features.loc[features.signal.ge(60)]
    result = {"kind":"POSTHOC_DESCRIPTIVE", "annual":rows, "leave_episode_out":removals,
        "full_window_sessions":len(features), "lower_touch_signal_count":int(full.lower_touch.sum()),
        "lower_recovery_signal_count":int(full.lower_recovery.sum()),
        "sole_touch_frequency_upper_bound":60 * int(full.lower_touch.sum()) / len(features),
        "sole_recovery_frequency_upper_bound":60 * int(full.lower_recovery.sum()) / len(features),
        "source_calls":0,"strategy_accounts":0,
        "limits":"All endpoint signals counted for an upper bound, not necessarily executable/mature. Descriptive means after inspecting initial outcomes, not independent hypothesis confirmation or actual account frequency."}
    (EXPERIMENT / "others/cap_diagnostics_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('annual','leave_episode_out')},ensure_ascii=False))


if __name__ == "__main__":
    main()
