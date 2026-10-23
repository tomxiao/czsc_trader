"""Fixed, causal price-information census. No labels, tuning or accounts.

Every zero-denominator expression has a defined zero-information value of 0.
This is a mathematical convention for observed flat prices, never imputation.
Daily windows use adjusted prices; eight-bar paths use same-day raw prices.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TIMES = ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00')
FEATURES = {
    'direction_efficiency': ['drift5_scaled', 'efficiency5', 'intraday_efficiency', 'step_persistence'],
    'up_down_asymmetry': ['semivariance_balance', 'largest_step_balance', 'post_drop_recovery', 'run_length_balance'],
    'location_response': ['prior_range_position', 'close_location', 'open_side_occupation', 'wick_rejection'],
    'volatility_transition': ['range_expansion', 'prior_range_compression', 'shock_concentration', 'gap_energy_share'],
    'temporal_order': ['return_time_balance', 'extrema_order', 'excursion_balance', 'halfday_balance'],
    'scale_relationship': ['direction_alignment', 'drift_acceleration', 'intraday_daily_energy', 'nested_range_ratio'],
}


def _meta(definition, role, mechanism, counterexample, limitations):
    return dict(definition=definition, role=role, mechanism=mechanism,
                counterexample=counterexample, limitations=limitations)


METADATA = {
 'drift5_scaled': _meta('sum(r[-5:])/(abs(sum(r[-5:]))+sqrt(5)*population_std(r[-20:])); r=log adjusted close returns', 'opportunity,state', 'Multi-day displacement may describe unfinished repricing.', 'Post-fill returns reverse, or displacement has no incremental information.', 'A plain momentum control; not a newly independent price-path mechanism.'),
 'efficiency5': _meta('sum(r[-5:])/sum(abs(r[-5:]))', 'opportunity,state', 'Less reversal for the same displacement may indicate persistent demand.', 'Benefit disappears conditional on five-day return and volatility.', 'Strongly related to momentum; endpoint-controlled comparison required.'),
 'intraday_efficiency': _meta('sum(u)/sum(abs(u)); u[0]=log(Cbar[0]/day_open), u[j]=log(Cbar[j]/Cbar[j-1])', 'opportunity,state', 'Smooth same-day progress may persist after next-session execution.', 'Information expires before next-day fill or predicts reversal instead.', 'Includes between-bar jumps; cannot resolve within-bar paths.'),
 'step_persistence': _meta('mean(sign(u[:-1])*sign(u[1:])); zero moves have sign zero', 'state,opportunity', 'Persistence versus alternation may distinguish sustained movement from churn.', 'Any apparent effect is explained by endpoint return or variance.', 'Directionless persistence; eight steps provide only seven adjacent pairs.'),
 'semivariance_balance': _meta('(sum(max(u,0)^2)-sum(min(u,0)^2))/sum(u^2)', 'risk,opportunity', 'Unequal upward and downward shocks may identify asymmetric risk.', 'Magnitude and direction controls explain the entire relation.', 'Not net buying; correlated with signed daily displacement.'),
 'largest_step_balance': _meta('(max(max(u,0))-max(max(-u,0)))/(max(max(u,0))+max(max(-u,0)))', 'risk,opportunity', 'The strongest opposing moves may identify fragility or persistence.', 'Largest moves are transitory noise with no post-fill information.', 'Sensitive to one 30-minute interval; no participant interpretation.'),
 'post_drop_recovery': _meta('After the earliest negative u within absolute 1e-12 log-return of min(u), sum(remaining u)/sum(abs(remaining u)); 0 if no negative step or no remaining movement', 'risk,opportunity', 'Response after an adverse move may reveal resilience rather than the drop alone.', 'Recovery merely consumes the future upside before entry.', 'Zero also denotes no observed negative shock or no subsequent movement; report these structural cases separately. The fixed 1e-12 tie tolerance makes equivalent log-price steps invariant to floating-point price-unit rounding.'),
 'run_length_balance': _meta('(longest strictly positive u run-longest strictly negative u run)/8; zeros break runs', 'state,opportunity', 'Directional duration may differ even when final returns match.', 'Run effects disappear after controlling endpoint and efficiency.', 'Only nine possible run lengths; correlated with persistence and efficiency.'),
 'prior_range_position': _meta('(2*C-H20prev-L20prev)/(abs(2*C-H20prev-L20prev)+(H20prev-L20prev)); H/L exclude current day', 'state,opportunity', 'Relative location may condition remaining reward and risk across the whole range.', 'Only prior returns explain its apparent usefulness.', 'Continuous all-day location, not a breakout event; bounded compression discards absolute range size.'),
 'close_location': _meta('(2*C-H-L)/(H-L) on adjusted current daily OHLC', 'opportunity,risk', 'Retention of the day range may describe acceptance or late rejection.', 'Current-day strength does not survive the next-session execution delay.', 'No ordering of daily high and low is inferred; familiar range-position expression.'),
 'open_side_occupation': _meta('mean(sign(eight bar closes-first bar Open))', 'state,opportunity', 'Time spent above versus below the opening reference may add information beyond final close.', 'Occupation has no value after conditioning on open-to-close return.', 'Eight equally weighted snapshots, not exact time occupancy or traded volume.'),
 'wick_rejection': _meta('sum(min(O,C)-L-(H-max(O,C)))/sum(H-L) over eight bars', 'risk,opportunity', 'Asymmetric return from bar extremes may indicate failure to sustain one direction.', 'Wicks reflect ordinary volatility and contain no incremental forward information.', 'No within-bar high-low order; raw OHLC does not prove rejection by an identified participant.'),
 'range_expansion': _meta('(TRtoday-mean(TR[-21:-1]))/(TRtoday+mean(TR[-21:-1])); TR=max(H-L,abs(H-prevC),abs(L-prevC))', 'risk,sizing,state', 'A sudden change in activity may forecast future risk or available space.', 'Range expansion forecasts only already-realized movement.', 'Unsigned risk descriptor; positive expected return is not assumed.'),
 'prior_range_compression': _meta('(mean(TR previous5)-mean(TR previous20))/(mean(TR previous5)+mean(TR previous20)); excludes current day', 'state,risk', 'Recent compression or expansion may condition future movement size.', 'Compression has no incremental size information versus baseline volatility.', 'Does not assign a direction; related to rolling volatility states.'),
 'shock_concentration': _meta('max(u^2)/sum(u^2); 0 when every observed step is zero', 'risk,state', 'One-shock movement may differ from movement distributed over the session.', 'Concentration effects are explained by magnitude or gap exposure.', 'Range [1/8,1] for non-flat days; flat-day 0 is a distinct observed state.'),
 'gap_energy_share': _meta('g^2/(g^2+sum(u^2)); g=log(adjusted day Open/previous adjusted Close)', 'risk,execution', 'Overnight-dominated movement may leave different executable daytime opportunity.', 'All information is realized before the allowed order can execute.', 'Gap is adjusted, intraday is raw dimensionless; one historical price snapshot does not certify historical publication time.'),
 'return_time_balance': _meta('dot(linspace(-1,1,8),u)/sum(abs(u))', 'opportunity,execution', 'Timing of signed movement may distinguish early adjustment from ongoing repricing.', 'Time weighting is redundant with endpoint return or half-day contrast.', 'Linear full-session weighting; not a tail-only rule; no intraday trading authorization.'),
 'extrema_order': _meta('(earliest argmax(bar High)-earliest argmin(bar Low))/7; 0 when same bar', 'state,opportunity', 'Low-before-high and high-before-low paths may imply different residual movement.', 'Order supplies no information after endpoint and volatility controls.', 'Same-bar order is unknown and encoded zero, not asserted simultaneous; ties choose earliest observed bar.'),
 'excursion_balance': _meta('(maximum subsequent rise-maximum subsequent fall)/sum(abs(u)) on log path [day Open,eight closes]', 'risk,holding_diagnostic', 'Observed drawup versus drawdown may distinguish path resilience.', 'Excursion balance only restates terminal return or fails on future held-position outcomes.', 'Close-sampled path misses within-bar extremes; entry labels cannot validate a holding/exit rule.'),
 'halfday_balance': _meta('(sum(u[4:])-sum(u[:4]))/sum(abs(u))', 'opportunity,execution', 'Morning and afternoon contribution may differ in persistence to executable next day.', 'Difference vanishes at actual fill or is redundant with return_time_balance.', 'Four bars per half; u[4] includes the transition from morning close to first afternoon close.'),
 'direction_alignment': _meta('efficiency5*intraday_efficiency', 'state,conditional_opportunity', 'Daily and intraday directional agreement may condition continuation or exhaustion.', 'Interaction adds nothing beyond its two constituent signals.', 'Derived interaction, explicitly not a third independent information source; symmetric in simultaneous sign reversal.'),
 'drift_acceleration': _meta('(mean(r last5)-mean(r preceding15))/(abs(mean(r last5)-mean(r preceding15))+population_std(r last20))', 'state,opportunity', 'Recent drift relative to the preceding background may identify a changing adjustment process.', 'Acceleration is only another representation of ordinary momentum.', 'Overlapping observations across days; baseline return controls and chronology required.'),
 'intraday_daily_energy': _meta('(sum(u^2)-mean(r last20 squared))/(sum(u^2)+mean(r last20 squared))', 'risk,sizing,state', 'Current intraday movement energy relative to daily background may forecast risk regime changes.', 'Scale difference is mechanical or adds nothing beyond range expansion.', 'Different return sampling scales; daily mean-square includes gaps and drift, not a formal variance decomposition.'),
 'nested_range_ratio': _meta('(current H-L)/(current H-L+max(H previous5)-min(L previous5))', 'risk,state', 'Current daily excursion compared with broader space may reveal scale expansion.', 'Nested-range information is redundant with TR expansion or range position.', 'Unsigned adjusted-price range comparison; does not infer breakout or profitable direction.'),
}


def _ratio(a: float, b: float) -> float:
    """Observed zero movement has zero information by definition."""
    if not np.isfinite(a) or not np.isfinite(b) or b < 0:
        raise ValueError('Invalid ratio operands; missing data are not imputed')
    if b == 0:
        if a != 0:
            raise ValueError('Nonzero numerator with zero denominator')
        return 0.0
    return float(a / b)


def _longest(signs: np.ndarray, wanted: int) -> int:
    current = longest = 0
    for value in signs:
        current = current + 1 if value == wanted else 0
        longest = max(longest, current)
    return longest


def _validate(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    needed = ['Date', 'Open', 'High', 'Low', 'Close']
    if any(k not in frame for k in needed):
        raise ValueError(f'{name}: missing required OHLC fields')
    out = frame[needed].copy()
    out.attrs = {}
    out['Date'] = pd.to_datetime(out.Date, errors='raise')
    if out.Date.isna().any() or out.Date.duplicated().any() or not out.Date.is_monotonic_increasing:
        raise ValueError(f'{name}: invalid, duplicated or unsorted timestamps')
    values = out[['Open', 'High', 'Low', 'Close']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f'{name}: missing, nonfinite or nonpositive OHLC')
    o, h, low, c = values.T
    tolerance = 1e-10 * np.maximum(h, 1.0)
    if ((h + tolerance < np.maximum(o, c)) | (low - tolerance > np.minimum(o, c)) | (h < low)).any():
        raise ValueError(f'{name}: inconsistent OHLC bounds')
    out[['Open', 'High', 'Low', 'Close']] = values
    return out


def build(adj: pd.DataFrame, raw: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Return date, position and 24 columns, 434 rows on the frozen full input.

    Aligned prefixes with 75 warmup days are accepted for causal prefix audits.
    No indicator needs intraday data before the first development date.
    """
    adj, raw, bars = (_validate(f, n) for f, n in ((adj, 'adj'), (raw, 'raw'), (bars, 'bars')))
    if not 76 <= len(adj) <= 509 or len(adj) != len(raw) or not adj.Date.equals(raw.Date):
        raise ValueError('Expected aligned daily input with 75 warmup rows and 1..434 development rows')
    if not adj.Date.eq(adj.Date.dt.normalize()).all():
        raise ValueError('Daily timestamps must be midnight session dates')
    dates = adj.Date.iloc[75:].dt.strftime('%Y-%m-%d').tolist()
    if dates[0] != '2025-01-02' or (len(adj) == 509 and dates[-1] != '2026-10-21'):
        raise ValueError('Unexpected frozen development window')
    if len(bars) != 8 * len(dates):
        raise ValueError('Exactly eight intraday bars are required per development day')
    groups = list(bars.groupby(bars.Date.dt.strftime('%Y-%m-%d'), sort=False))
    if [d for d, _ in groups] != dates:
        raise ValueError('Intraday and development dates differ')
    a = adj[['Open', 'High', 'Low', 'Close']].to_numpy(float)
    r = np.r_[np.nan, np.diff(np.log(a[:, 3]))]
    tr = np.empty(len(a)); tr[0] = a[0, 1] - a[0, 2]
    tr[1:] = np.maximum.reduce([a[1:, 1]-a[1:, 2], np.abs(a[1:, 1]-a[:-1, 3]), np.abs(a[1:, 2]-a[:-1, 3])])
    rows = []
    for position, (date, frame) in enumerate(groups):
        if tuple(frame.Date.dt.strftime('%H:%M')) != TIMES or not frame.Date.dt.second.eq(0).all():
            raise ValueError(f'{date}: unexpected 30-minute bar times')
        i = position + 75
        bo, bh, bl, bc = frame[['Open', 'High', 'Low', 'Close']].to_numpy(float).T
        # Only dimensionless same-day quantities cross adjusted/raw sources.
        path = np.log(np.r_[bo[0], bc]); u = np.diff(path)
        signs = np.sign(u); variation = float(np.abs(u).sum()); energy = float(np.square(u).sum())
        up, down = np.maximum(u, 0), np.maximum(-u, 0)
        r5, r20 = r[i-4:i+1], r[i-19:i+1]
        drift = float(r5.sum()); sigma = float(r20.std(ddof=0))
        efficiency = _ratio(drift, float(np.abs(r5).sum()))
        intraday_efficiency = _ratio(float(u.sum()), variation)
        largest_up, largest_down = float(up.max()), float(down.max())
        recovery = 0.0
        if (u < 0).any():
            # Equal economic returns may differ by machine rounding after
            # changing price units. Declare ties before choosing the first.
            k = int(np.flatnonzero((u < 0) & (u <= u.min()+1e-12))[0])
            remainder = u[k+1:]
            recovery = _ratio(float(remainder.sum()), float(np.abs(remainder).sum()))
        high20, low20 = float(a[i-20:i, 1].max()), float(a[i-20:i, 2].min())
        o, high, low, close = a[i]
        location = float(2*close-high20-low20)
        prior20, prior5 = float(tr[i-20:i].mean()), float(tr[i-5:i].mean())
        gap = float(np.log(o/a[i-1, 3])); gap2 = gap*gap
        drawup = float(np.max(path-np.minimum.accumulate(path)))
        drawdown = float(np.max(np.maximum.accumulate(path)-path))
        acceleration = float(r5.mean()-r[i-19:i-4].mean())
        daily_energy = float(np.square(r20).mean())
        prior_range5 = float(a[i-5:i, 1].max()-a[i-5:i, 2].min())
        row = dict(date=date, position=position,
          drift5_scaled=_ratio(drift, abs(drift)+np.sqrt(5)*sigma),
          efficiency5=efficiency, intraday_efficiency=intraday_efficiency,
          step_persistence=float(np.mean(signs[:-1]*signs[1:])),
          semivariance_balance=_ratio(float(np.square(up).sum()-np.square(down).sum()), energy),
          largest_step_balance=_ratio(largest_up-largest_down, largest_up+largest_down),
          post_drop_recovery=recovery,
          run_length_balance=(_longest(signs, 1)-_longest(signs, -1))/8,
          prior_range_position=_ratio(location, abs(location)+high20-low20),
          close_location=_ratio(float(2*close-high-low), float(high-low)),
          open_side_occupation=float(np.sign(bc-bo[0]).mean()),
          wick_rejection=_ratio(float((np.minimum(bo,bc)-bl-(bh-np.maximum(bo,bc))).sum()), float((bh-bl).sum())),
          range_expansion=_ratio(float(tr[i]-prior20), float(tr[i]+prior20)),
          prior_range_compression=_ratio(prior5-prior20, prior5+prior20),
          shock_concentration=_ratio(float(np.square(u).max()), energy),
          gap_energy_share=_ratio(gap2, gap2+energy),
          return_time_balance=_ratio(float(np.dot(np.linspace(-1,1,8),u)), variation),
          extrema_order=(int(np.argmax(bh))-int(np.argmin(bl)))/7,
          excursion_balance=_ratio(drawup-drawdown, variation),
          halfday_balance=_ratio(float(u[4:].sum()-u[:4].sum()), variation),
          direction_alignment=efficiency*intraday_efficiency,
          drift_acceleration=_ratio(acceleration, abs(acceleration)+sigma),
          intraday_daily_energy=_ratio(energy-daily_energy, energy+daily_energy),
          nested_range_ratio=_ratio(float(high-low), float(high-low+prior_range5)))
        rows.append(row)
    columns = [c for names in FEATURES.values() for c in names]
    if len(columns) != 24 or set(columns) != set(METADATA):
        raise AssertionError('Feature registry and metadata must agree')
    result = pd.DataFrame(rows)[['date', 'position', *columns]]
    if len(result) != len(dates) or not np.isfinite(result[columns].to_numpy(float)).all():
        raise ValueError('Nonfinite feature output is an error, not a fill request')
    return result
