"""One fixed relative-lag mechanism; descriptive events, not an account strategy."""
import numpy as np
import pandas as pd

FEE = .001
THRESHOLD = np.log((1 + FEE) / (1 - FEE))


def daily_index(frame):
    out = frame.copy()
    out["Date"] = pd.to_datetime(out.Date).dt.normalize()
    if out.Date.duplicated().any():
        raise ValueError("duplicate daily date")
    return out.set_index("Date").sort_index()


def closes_1400(frame):
    data = frame.copy()
    data["Date"] = pd.to_datetime(data.Date)
    data["AvailableDate"] = pd.to_datetime(data.AvailableDate)
    sample = data.loc[data.Date.dt.strftime("%H:%M:%S").eq("14:00:00")].copy()
    decision = sample.Date.dt.normalize() + pd.Timedelta(hours=17)
    sample["valid"] = (sample.Volume.gt(0) & sample.Close.gt(0)
                       & sample.AvailableDate.le(decision))
    sample["Date"] = sample.Date.dt.normalize()
    if sample.Date.duplicated().any():
        raise ValueError("duplicate 14:00 close")
    return sample.set_index("Date")[["Close", "valid"]]


def features(target, peer, target_minutes, peer_minutes):
    daily = daily_index(target)
    ref = daily_index(peer).reindex(daily.index)
    t14 = closes_1400(target_minutes).reindex(daily.index)
    p14 = closes_1400(peer_minutes).reindex(daily.index)
    out = pd.DataFrame(index=daily.index)
    out["target_last_hour"] = np.log(daily.Close / t14.Close)
    out["peer_last_hour"] = np.log(ref.Close / p14.Close)
    out["lag"] = out.target_last_hour - out.peer_last_hour
    out["target_feature_valid"] = t14.valid.fillna(False) & out.target_last_hour.notna()
    out["feature_valid"] = (out.target_feature_valid & p14.valid.fillna(False)
                            & out.peer_last_hour.notna())
    out["event"] = out.feature_valid & out.lag.lt(-THRESHOLD) & out.peer_last_hour.ge(0)
    out["absolute_control"] = out.target_feature_valid & out.target_last_hour.lt(-THRESHOLD)
    return out


def nonoverlap(mask, horizon):
    selected, next_allowed = [], 0
    for i in np.flatnonzero(mask.to_numpy(copy=True)):
        if i >= next_allowed:
            selected.append(int(i))
            next_allowed = i + horizon
    return selected


def scalar_mean(series):
    return float(series.mean()) if len(series) else None


def net(ratio):
    return ratio * (1 - FEE) / (1 + FEE) - 1


def summarize(frame, event_col, horizon, denominator):
    eligible = frame.eligible & frame["net"].notna()
    selected = eligible & frame[event_col]
    events = frame.loc[selected]
    # Year-matched controls are retrospective diagnostics, never signal inputs.
    baseline = frame.loc[eligible].groupby(frame.loc[eligible].index.year)["gross"].mean()
    differences = events["net"] - pd.Series(events.index.year, index=events.index).map(baseline)
    chosen = nonoverlap(selected, horizon)
    filled_chosen = frame.iloc[chosen].limit_net.dropna()
    return {"eligible_sessions": int(eligible.sum()), "events": len(events),
            "net_mean": scalar_mean(events["net"]), "year_matched_excess": scalar_mean(differences),
            "positive_fraction": float(events["net"].gt(0).mean()) if len(events) else None,
            "nonoverlap_events": len(chosen), "events_per60": len(chosen) * 60 / denominator,
            "limit_fills": int(events.limit_net.notna().sum()),
            "limit_net_mean": scalar_mean(events.limit_net.dropna()),
            "nonoverlap_limit_fills": len(filled_chosen), "limit_fills_per60": len(filled_chosen) * 60 / denominator,
            "nonoverlap_limit_net_mean": scalar_mean(filled_chosen),
            "missed_open_net_mean": scalar_mean(events.loc[events.limit_net.isna(), "net"]),
            "event_dates": [str(v.date()) for v in events.index]}


def analyze(target, f, o01, inaccurate_dates):
    daily = daily_index(target)
    if not daily.index.equals(f.index):
        raise ValueError("feature index differs from daily anchor")
    out, summaries = f.copy(), []
    out["o01"] = o01.reindex(out.index).eq(1)
    out["union"] = out.event | out.o01
    bad = set(inaccurate_dates)
    annual = []
    for horizon in (1, 3, 5):
        x = out.copy()
        entry, exit_ = daily.Open.shift(-1), daily.Open.shift(-horizon-1)
        x["gross"] = exit_ / entry - 1
        x["net"] = net(exit_ / entry)
        limit = np.floor((daily.Close + 1e-10) / .001) * .001
        fill = entry.where(entry.le(limit), limit.where(daily.Low.shift(-1).le(limit)))
        x["limit_net"] = net(exit_ / fill)
        x["eligible"] = entry.notna() & exit_.notna()
        # Predeclared conservative exclusion covers decision, entry and all label dates.
        invalid = np.array([str(d.date()) in bad for d in x.index], dtype=bool)
        contaminated = np.zeros(len(x), dtype=bool)
        for offset in range(horizon + 2):
            contaminated[:len(x)-offset] |= invalid[offset:]
        x["clean"] = ~contaminated
        denominator = len(daily)
        for name in ("event", "absolute_control", "o01", "union"):
            for sensitivity in ("all", "exclude_quality_anomalies"):
                z = x.copy()
                if name == "event":
                    z["eligible"] &= z.feature_valid
                elif name == "absolute_control":
                    z["eligible"] &= z.target_feature_valid
                if sensitivity != "all":
                    z["eligible"] &= z.clean
                row = summarize(z, name, horizon, denominator)
                row.update(signal=name, horizon=horizon, sensitivity=sensitivity,
                           denominator_sessions=denominator, tail_loss=horizon+1)
                summaries.append(row)
        x["eligible"] &= x.feature_valid
        chosen_all = nonoverlap(x.eligible & x.event & x["net"].notna(), horizon)
        for year in sorted(set(x.index.year)):
            z = x.loc[x.index.year == year].copy()
            # Annual counts divide by all evaluation dates in that year, including invalid features.
            denominator_year = len(z)
            if denominator_year:
                row = summarize(z, "event", horizon, denominator_year)
                chosen_year = x.iloc[[i for i in chosen_all if x.index[i].year == year]]
                row.update(nonoverlap_events=len(chosen_year),
                           events_per60=len(chosen_year) * 60 / denominator_year,
                           nonoverlap_limit_fills=int(chosen_year.limit_net.notna().sum()),
                           limit_fills_per60=int(chosen_year.limit_net.notna().sum()) * 60 / denominator_year,
                           nonoverlap_limit_net_mean=scalar_mean(chosen_year.limit_net.dropna()))
                row.update(year=int(year), horizon=horizon)
                annual.append(row)
        out[f"net_{horizon}"] = x["net"]
        out[f"limit_net_{horizon}"] = x.limit_net
        out[f"clean_{horizon}"] = x.clean
    return out, summaries, annual
