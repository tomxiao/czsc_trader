"""Read existing authenticated PreparedDataRef only; no prepare/provider or data publication."""
from datetime import datetime, time
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys
from uuid import UUID

from dataflows import DataRequest, Dataset, PreparedDataRef
import pandas as pd
import requests
from strategy_runtime.pricing import ExecutionPricing
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT = Path.cwd()
sys.path.append(str(ROOT / 'research/S014/experiments/EX017_20261017/src'))
from pinned_inputs import get_context  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parent))
from audit_accounts import published, read, day  # noqa: E402

ATTEMPTS = []

def prohibited(*args, **kwargs):
    ATTEMPTS.append('network')
    raise RuntimeError('Only authenticated existing prepared fetch allowed')

requests.sessions.Session.request = prohibited
socket.socket.connect = prohibited
socket.create_connection = prohibited

def main():
    base = ROOT / 'research/S014/experiments/EX042_20261019'
    binding = published(read(base / 'others/accounts/run-000.json')['binding_ref'])
    rawref = binding['execution_prepared']
    prepared = PreparedDataRef(UUID(rawref['space_id']), UUID(rawref['preparation_id']), rawref['manifest_sha256'])
    ctx = get_context()
    frames, identities = {}, {}
    for name in ['execution_daily', 'adjusted_daily', 'price_limits', 'trading_status']:
        item = binding['execution_requests'][name]
        request = DataRequest(Dataset(item['dataset']), item['symbol'], item['start'], item['end'], item['required_cutoff'], item['frequency'])
        result = ctx.data.fetch(request, prepared=prepared)
        assert result.ready and result.identity.content_sha256 == binding['execution_identities'][name]
        frames[name] = result.dataframe.copy(deep=True)
        identities[name] = {'request': item, 'content_sha256': result.identity.content_sha256, 'rows': len(result.dataframe)}
    original = published(read(ROOT / 'research/S014/experiments/EX023_20261018/others/account_results.json')['records'][0]['evidence'])
    pricing = ExecutionPricing.from_dict(original['request_identity']['pricing'])
    rename = {'Date': 'dt', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'vol'}
    raw_numeric, adjusted_numeric = [frames[name].rename(columns=rename) for name in ['execution_daily', 'adjusted_daily']]
    execution = pricing.apply(raw_numeric.copy(), raw_daily=raw_numeric, adjusted_daily=adjusted_numeric).rename(columns={v: k for k, v in rename.items()})
    tables = {name: frame.set_index(pd.to_datetime(frame.Date)) for name, frame in frames.items()}
    execution = execution.set_index(pd.to_datetime(execution.Date))
    count = 0
    max_price_error = max_close_error = 0.
    joint_execution_facts = []
    for record in read(base / 'others/accounts_index.json')['records']:
        if record['status'] != 'SUCCEEDED':
            continue
        account = published(record['evidence'])
        ledgers = account['runs'][0]['ledgers']
        fills = {f['order_id']: f for f in ledgers['fills']['data']}
        for row in ledgers['account_daily']['data']:
            error = abs(row['close'] - execution.loc[pd.Timestamp(day(row['date'])), 'Close'])
            max_close_error = max(max_close_error, error)
            assert error <= 1e-7
            count += 1
        for order in ledgers['orders']['data']:
            stamp = pd.Timestamp(day(order['execution_date']))
            quote = execution.loc[stamp]
            raw = tables['execution_daily'].loc[stamp]
            bounds = tables['price_limits'].loc[stamp]
            scale = float(quote.Close / raw.Close)
            state = tables['trading_status'].loc[stamp, 'Status']
            fill = fills.get(order['order_id'])
            if state == 'SUSPENDED':
                assert fill is None and order['status'] != 'FILLED'
            else:
                assert state == 'TRADING'
                spec = OrderSpec(order['side'], order['order_type'], order['quantity'], order['limit_price']) if order['side'] == 'BUY' else OrderSpec('SELL', 'MARKET', order['quantity'])
                limits = SessionPriceLimits(stamp.date(), float(bounds.DownLimit * scale), float(bounds.UpLimit * scale), float(.01 * scale))
                expected = resolve_fill(spec, session_open=float(quote.Open), session_time=datetime.combine(stamp.date(), time(9, 30)),
                                        intraday_touches=(), daily_quote=DailyQuote(float(quote.Low), float(quote.High)), session_limits=limits)
                assert bool(expected.filled) == bool(fill)
                if fill:
                    # Re-derived price is arithmetic in the frozen execution representation.
                    error = abs(float(expected.price) - fill['price'])
                    max_price_error = max(max_price_error, error)
                    assert error <= 1e-7
                    assert quote.Low - 1e-7 <= fill['price'] <= quote.High + 1e-7
                    if order['side'] == 'BUY':
                        assert fill['price'] <= order['limit_price'] + 1e-7
                    if day(fill['fill_time']) in ['2025-06-16', '2025-06-20']:
                        joint_execution_facts.append({'mode': record['mode'], 'side': fill['side'], 'actual_price': fill['price'], 'quantity': fill['quantity'],
                                               'raw_Open': float(raw.Open), 'projected_Open': float(quote.Open), 'scale': scale,
                                               'projected_DownLimit': limits.down_limit, 'projected_UpLimit': limits.up_limit})
            count += 1
    assert not ATTEMPTS
    result = dict(status='PASS_EXISTING_PREPARED_EXECUTION_CONSTRAINTS', checks=count, existing_prepared=rawref,
                  fetched_inputs=identities, pricing=original['request_identity']['pricing'],
                  maximum_derived_price_error=max_price_error, maximum_projected_close_error=max_close_error,
                  arithmetic_currency_tolerance=1e-7, joint_execution_facts=joint_execution_facts,
                  limitation='Reapply original public resolve_fill contract; this is execution consistency, not independent market authenticity validation.',
                  new_preparations=0, supplier_calls=0, new_account_dispatches=0, market_data_copies_or_publications=0, network_attempts=ATTEMPTS,
                  source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    out = Path(__file__).with_name('independent_joint_execution_constraints.json')
    with out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
