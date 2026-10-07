"""Causal S013 phase-two component definitions (no strategy/order simulation)."""
from pathlib import Path
import numpy as np
import pandas as pd
from expr_codegen import codegen_exec
from tsfresh import extract_features

FC_PARAMETERS = {
    'linear_trend': [{'attr': 'slope'}, {'attr': 'rvalue'}],
    'autocorrelation': [{'lag': 1}, {'lag': 2}, {'lag': 5}],
    'mean_change': None,
    'absolute_sum_of_changes': None,
    'skewness': None,
    'standard_deviation': None,
    'change_quantiles': [{'ql': 0.2, 'qh': 0.8, 'isabs': False, 'f_agg': 'mean'}],
}
EXPRESSIONS = '''
ma_gap_5 = Close / MA5 - 1
ma_gap_20 = Close / MA20 - 1
ma_gap_60 = Close / MA60 - 1
volume_ratio_5_20 = VMA5 / VMA20 - 1
turnover_ratio_20 = Amount / AMA20 - 1
range_compression_5_20 = RANGE5 / RANGE20
close_location = (2 * Close - High - Low) / (High - Low)
overnight_gap = Open / PreviousClose - 1
intraday_return = Close / Open - 1
trend_x_volume = MOM20 * (VMA5 / VMA20 - 1)
pullback_x_trend = MOM5 * MOM60
'''

def manual_features(frame: pd.DataFrame, output_file: Path) -> pd.DataFrame:
    df = frame.copy().reset_index(drop=True)
    df['Date'] = pd.to_datetime(df.Date)
    df['asset'] = '510500.SH'
    c, v, a = df.Close, df.Volume, df.Amount
    returns = c.pct_change(fill_method=None)
    day_range = (df.High - df.Low) / c
    assert (df.High > df.Low).all(), 'zero-range day needs explicit treatment'
    for w in (5, 20, 60):
        df[f'MA{w}'] = c.rolling(w).mean()
        df[f'momentum_{w}'] = c / c.shift(w) - 1
    df['PreviousClose'] = c.shift(1)
    df['VMA5'], df['VMA20'] = v.rolling(5).mean(), v.rolling(20).mean()
    df['AMA20'] = a.rolling(20).mean()
    df['RANGE5'], df['RANGE20'] = day_range.rolling(5).mean(), day_range.rolling(20).mean()
    df['MOM5'], df['MOM20'], df['MOM60'] = [df[f'momentum_{w}'] for w in (5, 20, 60)]
    result = codegen_exec(df.copy(), EXPRESSIONS, style='pandas', over_null=None,
                          date='Date', asset='asset', output_file=str(output_file), run_file=True)
    references = {
        'ma_gap_5': c / df.MA5 - 1, 'ma_gap_20': c / df.MA20 - 1, 'ma_gap_60': c / df.MA60 - 1,
        'volume_ratio_5_20': df.VMA5 / df.VMA20 - 1,
        'turnover_ratio_20': a / df.AMA20 - 1,
        'range_compression_5_20': df.RANGE5 / df.RANGE20,
        'close_location': (2*c-df.High-df.Low)/(df.High-df.Low),
        'overnight_gap': df.Open / df.PreviousClose - 1, 'intraday_return': c / df.Open - 1,
        'trend_x_volume': df.MOM20 * (df.VMA5/df.VMA20-1),
        'pullback_x_trend': df.MOM5 * df.MOM60,
    }
    for key, reference in references.items():
        np.testing.assert_allclose(result[key], reference, rtol=1e-12, atol=1e-12, equal_nan=True)
    features = pd.DataFrame({f'momentum_{w}': df[f'momentum_{w}'] for w in (5,20,60)})
    for key in references:
        features[key] = result[key].to_numpy()
    for w in (5,20):
        features[f'volatility_{w}'] = returns.rolling(w).std(ddof=1)
    for w in (20,60):
        lowest, highest = df.Low.rolling(w).min(), df.High.rolling(w).max()
        features[f'range_position_{w}'] = (c-lowest)/(highest-lowest)
    features['signed_volume_5'] = (np.sign(returns)*v).rolling(5).sum()/v.rolling(5).sum()
    features.index = df.index
    return features

def tsfresh_features(frame: pd.DataFrame, positions=None, workers=8) -> pd.DataFrame:
    returns = frame.Close.pct_change(fill_method=None).to_numpy()
    if positions is None:
        positions = range(20, len(frame))
    windows = pd.concat([pd.DataFrame({'id': i, 'order': range(20), 'return': returns[i-19:i+1]})
                         for i in positions], ignore_index=True)
    assert np.isfinite(windows['return']).all()
    result = extract_features(windows, column_id='id', column_sort='order',
        default_fc_parameters=FC_PARAMETERS, n_jobs=workers, chunksize=40,
        disable_progressbar=True, show_warnings=False)
    return result.rename(columns={k: 'tsfresh20_' + k.split('__',1)[1] for k in result.columns})

def labels(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.reset_index(drop=True)
    n = len(df)
    result = pd.DataFrame(index=df.index)
    for h in (5,10,20):
        result[f'return_{h}'] = df.Open.shift(-h-1)/df.Open.shift(-1)-1
        result[f'end_{h}'] = pd.to_datetime(df.Date).shift(-h-1)
    low = df.Low.to_numpy()
    downside = np.full(n, np.nan)
    for i in range(n-20):
        downside[i] = max(0.0, 1 - float(low[i+1:i+21].min())/float(df.Open.iloc[i+1]))
    result['downside_20'] = downside
    result['end_downside_20'] = pd.to_datetime(df.Date).shift(-20)
    return result
