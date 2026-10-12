"""EX090 maturity-aware expanding daily probability/gain update.

No new information or feature is introduced. Frozen EX084 probability and EX086
gain solvers are called unchanged. Loss is the mature training nonpositive mean,
not the failed conditional loss model. All schedules remain price proxies.
"""
import numpy as np
import pandas as pd

FEATURES = ('momentum20', 'range_position60', 'acf1', 'volatility20', 'intraday_return',
            'overnight_gap', 'intraday_energy20', 'intraday_rms20', 'confirmation_score',
            'daily_close_location', 'feature_intraday_down_energy20', 'feature_overnight_down_energy20',
            'turnover20', 'volume_ratio20')
INPUTS = ('confirmation_110', 'original14_110')
FAMILIES = ('confirmation', 'original14')
KINDS = ('historical', 'matched', 'training_mean', 'online_pg')
MODELS = tuple(f'{family}_{kind}' for family in FAMILIES for kind in KINDS)
SUFFIXES = ('net_mse_improvement_vs_matched', 'net_mse_improvement_vs_training_mean',
            'online_positive_mean', 'online_positive_minus_matched',
            'online_positive_minus_training_mean', 'online_greedy_minus_matched_greedy')
QUANTITIES = tuple(f'{family}_{suffix}' for family in FAMILIES for suffix in SUFFIXES)


def validate(features, labels, old_scores):
    axis = features.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()):
        raise ValueError('Unique ordered naive midnight signal dates')
    if tuple(features.columns) != FEATURES or tuple(old_scores.columns) != INPUTS or not all(frame.index.equals(axis) for frame in (labels, old_scores)) or len(axis) < 40:
        raise ValueError('Exact original14 and frozen PG columns with shared axis at least40')
    if labels.columns.has_duplicates or not {'return_4', 'label_end_return_4'}.issubset(labels.columns):
        raise ValueError('Paired return_4 and label_end_return_4 required')
    x, y, old = features.to_numpy(float), labels.return_4.to_numpy(float), old_scores.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()):
        raise ValueError('Naive midnight label maturity dates')
    finite = np.isfinite(y)
    if any(np.isinf(value).any() for value in (x, y, old)) or not np.array_equal(finite, ends.notna()):
        raise ValueError('Finite or missing values and paired truth/maturity')
    if (y[finite] <= -1).any() or (ends[finite].to_numpy() <= axis[finite].to_numpy()).any() or np.isfinite(old[axis.year < 2021]).any():
        raise ValueError('Positive factors, future maturity, no pre2021 frozen forecast')
    return axis, x, y, old, ends


def forecasts(features, labels, old_scores, prob_core, gain_core, *, families=FAMILIES):
    axis, x, y, old, ends = validate(features, labels, old_scores)
    families = tuple(families)
    if not families or len(set(families)) != len(families) or any(family not in FAMILIES for family in families):
        raise ValueError('Nonempty unique subset of the two fixed families required')
    if tuple(prob_core.FEATURES) != FEATURES or tuple(gain_core.FEATURES) != FEATURES:
        raise ValueError('Frozen solver feature identity mismatch')
    complete = np.isfinite(x).all(axis=1)
    positions = np.arange(len(axis))
    columns_to_return = tuple(f'{family}_{kind}' for family in families for kind in KINDS)
    scores = pd.DataFrame(np.nan, index=axis, columns=columns_to_return)
    traces = []
    for family in families:
        column = FAMILIES.index(family)
        columns = [8] if family == 'confirmation' else list(range(14))
        scores[family + '_historical'] = old[:, column]
        for i, date in enumerate(axis):
            train = complete & np.isfinite(y) & (axis.year >= 2020) & (positions < i) & (ends <= date).to_numpy()
            wins, losses = train & (y > 0), train & (y <= 0)
            n, nw, nl = int(train.sum()), int(wins.sum()), int(losses.sum())
            available = date.year >= 2021 and complete[i] and n >= 40 and nw >= 20 and nl >= 20
            status = ('AVAILABLE' if available else 'PRE2021_UNAVAILABLE' if date.year < 2021 else
                      'CURRENT_FEATURES_MISSING' if not complete[i] else 'INSUFFICIENT_MATURE_TRAINING')
            row = {'family': family, 'signal_date': date.isoformat(), 'position': i, 'columns': columns,
                   'train_n': n, 'win_n': nw, 'nonpositive_n': nl, 'zero_net_n': int((train & (y == 0)).sum()),
                   'train_positions': [int(j) for j in np.flatnonzero(train)],
                   'max_maturity': ends[train].max().isoformat() if n else None,
                   'current_features_complete': bool(complete[i]), 'available': bool(available), 'status': status,
                   'training_mean': None, 'loss_mean': None, 'probability': None, 'gain': None, 'online_pg': None,
                   'probability_fit': None, 'gain_fit': None, 'future_test_count_gate': False}
            if available:
                tr = np.column_stack([gain_core.rank(x[train, j], x[train, j]) for j in range(14)])
                te = np.column_stack([gain_core.rank(x[train, j], x[i:i + 1, j]) for j in range(14)])
                win_in_train = y[train] > 0
                probability, probability_fit = prob_core.fit(tr[:, columns], win_in_train.astype(float), te[:, columns])
                gain, gain_fit = gain_core.fit(tr[win_in_train][:, columns], y[train][win_in_train], te[:, columns])
                probability, gain = float(probability[0]), float(gain[0])
                loss, mean = float(-y[losses].mean()), float(y[train].mean())
                net = probability * gain - (1 - probability) * loss
                if not np.isfinite(net) or not np.isfinite(loss) or loss < 0:
                    raise ValueError('Finite online PG and nonnegative actual training loss mean required')
                scores.loc[date, family + '_matched'] = old[i, column]
                scores.loc[date, family + '_training_mean'] = mean
                scores.loc[date, family + '_online_pg'] = net
                row.update({'training_mean': mean, 'loss_mean': loss, 'probability': probability,
                            'gain': gain, 'online_pg': net, 'probability_fit': probability_fit, 'gain_fit': gain_fit})
            traces.append(row)
    return scores, traces


def selected(y, prediction, mask):
    eligible = mask & np.isfinite(prediction)
    positive = eligible & (prediction > 0)
    mature = positive & np.isfinite(y)
    n = int(mature.sum())
    return {'forecasts': int(eligible.sum()), 'positive_forecasts': int(positive.sum()), 'mature_positive': n,
            'missing_positive_truth': int((positive & ~np.isfinite(y)).sum()),
            'positive_mean': float(y[mature].mean()) if n >= 20 else None,
            'hit_rate': float((y[mature] > 0).mean()) if n >= 20 else None,
            'false_positive_rate': float((y[mature] <= 0).mean()) if n >= 20 else None,
            'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}


def selector_masks(scores, clock):
    masks = {}
    for family in FAMILIES:
        matched, mean, online = [scores[family + '_' + kind].to_numpy(float) for kind in KINDS[1:]]
        masks[family] = np.column_stack((online > 0, matched > 0, mean > 0,
                                        clock.entries(online, 'greedy'), clock.entries(matched, 'greedy')))
    return masks


def paired_errors(y, scores, ids, family):
    predictions = scores.loc[:, [family + '_' + kind for kind in KINDS[1:]]].to_numpy(float)[ids]
    yy = y[ids]
    finite = np.isfinite(yy) & np.isfinite(predictions).all(axis=1)
    n = int(finite.sum())
    errors = ((predictions[finite] - yy[finite, None]) ** 2).mean(axis=0) if n >= 20 else np.full(3, np.nan)
    result = {'paired_mature': n, 'matched_mse': float(errors[0]) if n >= 20 else None,
              'training_mean_mse': float(errors[1]) if n >= 20 else None,
              'online_pg_mse': float(errors[2]) if n >= 20 else None,
              'status': 'AVAILABLE' if n >= 20 else 'INSUFFICIENT_DATA'}
    for j, other in enumerate(('matched', 'training_mean')):
        valid = n >= 20 and errors[j] > 0
        result['net_mse_improvement_vs_' + other] = float((errors[j] - errors[2]) / errors[j]) if valid else None
        result['improvement_status_vs_' + other] = ('AVAILABLE' if valid else 'ZERO_CONTROL_ERROR' if n >= 20 else 'INSUFFICIENT_DATA')
    return result


def quantities(y, scores, masks, ids):
    out = {}
    for family, mask in masks.items():
        yy, mm = y[ids], mask[ids]
        finite = np.isfinite(yy)
        means = [float(yy[finite & mm[:, j]].mean()) if (finite & mm[:, j]).sum() >= 20 else None for j in range(5)]

        def difference(a, b):
            return means[a] - means[b] if means[a] is not None and means[b] is not None else None

        error = paired_errors(y, scores, ids, family)
        values = (error['net_mse_improvement_vs_matched'], error['net_mse_improvement_vs_training_mean'],
                  means[0], difference(0, 1), difference(0, 2), difference(3, 4))
        out.update({family + '_' + suffix: value for suffix, value in zip(SUFFIXES, values)})
    return out


def bootstrap(y, scores, masks):
    n, rng = len(y), np.random.default_rng(13)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    ids = (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]
    original = quantities(y, scores, masks, np.arange(n))
    records = [quantities(y, scores, masks, row) for row in ids]
    summary = {}
    for key, value in original.items():
        good = [record[key] for record in records if record[key] is not None]
        available = value is not None and len(good) >= 400
        summary[key] = {'value': value, 'valid_replicates': len(good),
                        'ci95': np.quantile(good, [.025, .975], method='linear').tolist() if available else None,
                        'status': 'AVAILABLE' if available else 'INSUFFICIENT_DATA'}
    return {'summary': summary, 'records': records, 'blocks': 40, 'repetitions': 500, 'seed': 13,
            'refitted_models': 0, 'clock_resimulation_within_replicates': False, 'fixed_forecasts_and_entry_masks': True}


def summarize(scores, labels, traces, clock):
    axis = scores.index
    if not isinstance(axis, pd.DatetimeIndex) or axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing or not axis.equals(axis.normalize()) or len(axis) < 40:
        raise ValueError('Ordered shared midnight axis at least40 for summary')
    if tuple(scores.columns) != MODELS or not labels.index.equals(axis) or np.isinf(scores.to_numpy(float)).any():
        raise ValueError('All eight family-ordered scores, shared labels and no infinity')
    if len(traces) != 2 * len(axis) or [(row['family'], row['signal_date']) for row in traces] != [(family, date.isoformat()) for family in FAMILIES for date in axis]:
        raise ValueError('Complete family-ordered per-T fit traces required')
    axis, y = scores.index, labels.return_4.to_numpy(float)
    groups = {'all': np.ones(len(y), bool),
              **{'year_' + str(year): axis.year == year for year in range(2020, 2027)},
              **{'phase_' + str(k): np.arange(len(y)) % 5 == k for k in range(5)}}
    panels = {key: {name: selected(y, scores[name].to_numpy(float), mask) for name in MODELS}
              for key, mask in groups.items()}
    schedules = {name: {kind: clock.schedule(axis, scores[name].to_numpy(float), y, kind) for kind in clock.CLOCKS}
                 for name in MODELS}
    masks = selector_masks(scores, clock)
    quality = {key: quantities(y, scores, masks, np.flatnonzero(mask)) for key, mask in groups.items()}
    errors = {key: {family: paired_errors(y, scores, np.flatnonzero(mask), family) for family in FAMILIES}
              for key, mask in groups.items()}
    fit_count = sum(2 for row in traces if row['available'])
    return {'signals': len(y), 'fit_trace': traces, 'panels': panels, 'schedules': schedules,
            'selection_quality': quality, 'paired_prediction_errors': errors,
            'bootstrap': bootstrap(y, scores, masks), 'schedule_count': len(MODELS) * len(clock.CLOCKS),
            'new_daily_models': fit_count, 'new_annual_models': 0, 'new_accounts': 0, 'provider_calls': 0,
            'historical_forecasts_unchanged': True, 'new_independent_market_information': False,
            'training_rule': 'expanding mature original14 from2020; strict earlier T; label_end<=currentT',
            'objective_achieved': False}


def analyze(features, labels, old_scores, prob_core, gain_core, clock):
    scores, traces = forecasts(features, labels, old_scores, prob_core, gain_core)
    return scores, summarize(scores, labels, traces, clock)
