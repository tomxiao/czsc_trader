"""Check the declared residual quote errors against actual research orders."""
import json
import pandas as pd
from common import ROOT, RUNS, cache_read, save


def main():
    bound, baseline = cache_read(ROOT / '.tmp/s013-stage3-hfq/precheck.pkl.gz')
    data = bound.execution_data
    raw = data.raw_execution_daily.set_index('dt')
    normalized = data.execution_daily.set_index('dt')
    date = pd.Timestamp('2020-12-01')
    intraday = data.execution_intraday
    actual_minimum = float(intraday.loc[
        pd.to_datetime(intraday.dt).dt.normalize().eq(date), 'low'].min())
    scale = float(normalized.loc[date, 'close'] / raw.loc[date, 'close'])
    assert abs(float(raw.loc[date, 'low']) - 6.961) < 1e-12
    assert abs(actual_minimum / scale - 6.967) < 1e-12
    lower, upper = 6.961 * scale, 6.967 * scale
    affected_dates = pd.to_datetime(['2020-03-17', '2020-10-22', '2020-12-01',
                                     '2021-02-25', '2021-03-02'])
    rows = json.loads((RUNS / 'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    records = []
    for row in rows:
        if row['status'] != 'SUCCEEDED':
            continue
        result = baseline if row['candidate_id'] == 'C0001' else cache_read(
            ROOT / f'.tmp/s013-stage3-hfq/{row["candidate_id"]}.pkl.gz')
        assert result.result_hash == row['result_hash']
        orders = result.runs[0].execution.orders
        selected = orders.loc[pd.to_datetime(orders.execution_date).dt.normalize().isin(affected_dates)].copy()
        for order in selected.to_dict('records'):
            when = pd.Timestamp(order['execution_date']).normalize()
            potential = (when == date and order['side'] == 'BUY'
                         and order['order_type'] == 'LIMIT'
                         and order['status'] == 'UNFILLED'
                         and lower < float(order['limit_price']) <= upper)
            records.append({'candidate_id': row['candidate_id'],
                'execution_date': when.date().isoformat(),
                'side': order['side'], 'order_type': order['order_type'],
                'status': order['status'], 'limit_price': order['limit_price'],
                'potential_economic_change_from_low_error': potential})
    result = {
        'source': 'COMPONENTS/1 数据质量证据和报告中的五个残余异常，原件不修复',
        'scope': 'EX004全部成功配置的实际订单，不推断未知分钟发生时点',
        'successful_configurations': sum(row['status'] == 'SUCCEEDED' for row in rows),
        'execution_data_identity': data.fingerprint,
        'pricing': data.pricing.to_dict(),
        'high_error_dates': [value.date().isoformat() for value in affected_dates if value != date],
        'high_error_use': '买入LIMIT只消费Open/Low；卖出MARKET只消费Open，四个High偏差不影响当前撮合规则',
        'low_error': {'date': date.date().isoformat(), 'raw_daily_low': 6.961,
                      'raw_intraday_minimum': 6.967, 'price_scale': scale,
                      'normalized_lower': lower, 'normalized_upper': upper,
                      'rule': '严格Low<限价；已按Open或分钟Low成交的订单不会因更低Low改变成交金额'},
        'orders_on_error_dates': records,
        'potential_economic_change_count': sum(item['potential_economic_change_from_low_error'] for item in records),
        'limitations': ['仅检查已声明High/Low偏差；没有重建未知分钟修复轨迹或供应商历史发布记录'],
    }
    save('quality_impact_r4.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'orders_on_error_dates'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
