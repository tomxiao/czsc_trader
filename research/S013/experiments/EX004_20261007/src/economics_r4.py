"""Four user-confirmed gates; annual profit uses continuous net equity."""
from economics import summarize as original_summary


def apply_constraint(row):
    result = dict(row)
    if row['status'] != 'SUCCEEDED':
        return result
    negative = [y for y, v in row['buyhold_annual'].items() if v['return'] < 0]
    profit = all(row['annual'][y]['return'] > 0 for y in negative)
    result['gates'] = {**row['gates'], 'negative_buyhold_year_profit': profit}
    result['qualified'] = all(result['gates'].values())
    result['negative_buyhold_years'] = negative
    # Heuristic guides Optuna only; the four exact Boolean gates decide eligibility.
    result['deficit'] = (
        max(0., (row['return_threshold'] - row['net_cagr']) / max(abs(row['return_threshold']), .01))
        + sum(max(0., -margin) / max(row['buyhold_annual'][y]['max_drawdown_magnitude'], .01)
              for y, margin in row['annual_dd_margins'].items())
        + max(0., (4 - row['frequency60']) / 4)
        + sum(max(0., -row['annual'][y]['return']) / max(abs(row['buyhold_annual'][y]['return']), .01)
              for y in negative)
    )
    return result


def summarize(result):
    return apply_constraint({'status': 'SUCCEEDED', **original_summary(result)})


def search_value(row):
    return -row['deficit'] + .001 * row['net_cagr']
