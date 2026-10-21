"""Observed 30-minute order checks; no account mutation or counterfactual ledger."""
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, time
from hashlib import sha256
import json
import math
from pathlib import Path
from uuid import UUID

import pandas as pd
from dataflows import Dataflows, DataRequest, DataSpace, PreparedDataRef, ProviderConfig
from strategy_runtime import ExecutionPricing
from trading_execution_engine import DailyQuote, MarketExecutionRules, OrderSpec, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/S015/assets/evidence/EX003_20261021'


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    audit = json.loads((EXPERIMENT / 'others/execution_data_audit.json').read_text(encoding='utf-8'))
    raw_reference = audit['prepared']['reference']
    prepared = PreparedDataRef(UUID(raw_reference['space_id']), UUID(raw_reference['preparation_id']),
                               raw_reference['manifest_sha256'])
    raw_request = audit['request']
    request = DataRequest(raw_request['dataset'], raw_request['symbol'], raw_request['start'],
                          raw_request['end'], raw_request['required_cutoff'], raw_request['frequency'])
    flows = Dataflows(base_dir=ROOT, space=DataSpace(Path('research/S015/assets/data')),
                      providers=ProviderConfig(bindings={}))
    fetched = flows.fetch(request, prepared=prepared)
    minute = fetched.dataframe.copy()
    # The admitted original retains its audit attributes. Strip them only from
    # this numerical projection to avoid pandas deep-copying the full quality
    # evidence whenever a column is selected inside the order loop.
    minute.attrs = {}
    minute['Date'] = pd.to_datetime(minute['Date'])
    if len(minute) != 3472 or not minute['Date'].is_monotonic_increasing:
        raise ValueError('unexpected authorized minute coverage or ordering')
    grouped = {day: frame for day, frame in minute.groupby(minute['Date'].dt.date)}
    evidence_files = sorted(EVIDENCE.glob('*.json'))
    checked = []
    all_counts = Counter()
    unique_conditions = set()
    unique_conditions_by_role = defaultdict(set)
    differences = {}
    opening_differences = {}
    cross_frequency_differences = {}
    reach_failures = []
    daily_mismatches = []
    volume_exceptions = []
    max_volume_ratio = 0.
    price_scales = set()
    evaluations = set()
    cache = {}
    for path in evidence_files:
        content = path.read_bytes()
        data = json.loads(content)
        if data.get('schema_version') != 7 or not {'request_identity', 'runs', 'assessment_evidence'} <= data.keys():
            continue
        digest = sha256(content).hexdigest()
        if path.stem != digest:
            raise ValueError(f'evidence filename/hash mismatch: {path.name}')
        pricing = ExecutionPricing.from_dict(data['request_identity']['pricing'])
        rules = MarketExecutionRules.from_dict(data['request_identity']['market_rules'])
        rules_identity = rules.fingerprint
        checked.append({'evidence_id': path.name, 'sha256': digest,
                        'request_hash': data['request_hash'], 'result_hash': data['result_hash'],
                        'pricing': pricing.to_dict()})
        if len(checked) % 10 == 0:
            print(json.dumps({'account_evidence_progress': len(checked)}), flush=True)
        for run in data['runs']:
            matches = [item for item in data['assessment_evidence']
                       if item['window_id'] == run['window_id']
                       and item['scenario_id'] == run['scenario_id']
                       and item['candidate']['candidate_id'] == 'S015-' + run['candidate_id']]
            if len(matches) != 1:
                raise ValueError('evaluation identity is not unique')
            evaluation_id = matches[0]['evaluation_id']
            evaluations.add(evaluation_id)
            daily = {pd.Timestamp(row['date']).date(): row
                     for row in run['replay_evidence']['execution_daily']}
            account_counts = Counter()
            for role, ledger in (('strategy', run['ledgers']), ('benchmark', run['buyhold']['execution'])):
                fills = defaultdict(list)
                for fill in ledger['fills']['data']:
                    fills[fill['order_id']].append(fill)
                for order in ledger['orders']['data']:
                    day = pd.Timestamp(order['execution_date']).date()
                    quote = daily[day]
                    scale = float(quote['price_scale'])
                    if not math.isfinite(scale) or scale <= 0:
                        raise ValueError('invalid authenticated price scale')
                    if not close(quote['close'], float(quote['unadjusted_close']) * scale):
                        raise ValueError('daily price scale differs from raw close')
                    price_scales.add(scale)
                    bars = grouped[day]
                    lows = bars['Low'].to_numpy(float) * scale
                    highs = bars['High'].to_numpy(float) * scale
                    opens = bars['Open'].to_numpy(float) * scale
                    volumes = bars['Volume'].to_numpy(float) / scale
                    aggregate = {'open': float(opens[0]), 'high': float(max(highs)),
                                 'low': float(min(lows)), 'close': float(bars['Close'].iloc[-1]) * scale}
                    unequal = [field for field in aggregate if not close(aggregate[field], quote[field])]
                    if unequal:
                        cross_frequency_differences[(day.isoformat(), scale)] = {
                            'date': day.isoformat(), 'price_scale': scale, 'different_fields': unequal,
                            'formal_daily': {field: quote[field] for field in aggregate},
                            'minute_aggregate': aggregate,
                        }
                    limit = float(order['limit_price']) if order['order_type'] == 'LIMIT' else None
                    spec = OrderSpec(order['side'], order['order_type'], float(order['quantity']), limit)
                    condition = (day.isoformat(), order['side'], order['order_type'], limit)
                    unique_conditions.add(condition)
                    unique_conditions_by_role[role].add(condition)
                    key = (condition, scale, rules_identity)
                    if key not in cache:
                        touch_values = lows if order['side'] == 'BUY' else highs
                        touches = tuple(zip((x.to_pydatetime() for x in bars['Date']), touch_values, strict=True))
                        common = {'session_open': float(quote['open']),
                                  'session_time': datetime.combine(day, time(9, 30)),
                                  'session_limits': rules.for_session(day)}
                        daily_result = resolve_fill(spec, intraday_touches=(),
                            daily_quote=DailyQuote(float(quote['low']), float(quote['high'])), **common)
                        strict = resolve_fill(spec, intraday_touches=touches, inclusive_touch=False, **common)
                        inclusive = resolve_fill(spec, intraday_touches=touches, inclusive_touch=True, **common)
                        minute_open = resolve_fill(spec, intraday_touches=touches, inclusive_touch=False,
                            **{**common, 'session_open': float(opens[0])})
                        cache[key] = (daily_result, strict, inclusive, minute_open)
                    daily_result, strict, inclusive, minute_open = cache[key]
                    actual_fills = fills[order['order_id']]
                    actual_filled = bool(actual_fills)
                    matched_daily = actual_filled == daily_result.filled
                    filled_quantity = sum(float(item['quantity']) for item in actual_fills)
                    if actual_filled:
                        matched_daily &= close(filled_quantity, order['quantity'])
                        matched_daily &= all(close(item['price'], daily_result.price) for item in actual_fills)
                    detail = {'evidence_id': path.name, 'evaluation_id': evaluation_id,
                              'role': role, 'candidate_id': run['candidate_id'],
                              'order_id': order['order_id'], 'condition': list(condition),
                              'quantity': order['quantity'], 'status': order['status']}
                    opening_changed = strict.filled != minute_open.filled or (
                        strict.filled and minute_open.filled and not close(strict.price, minute_open.price))
                    if opening_changed:
                        opening_item = opening_differences.setdefault(condition, {
                            'condition': list(condition), 'strict_with_formal_daily_open': asdict(strict),
                            'strict_with_first_minute_bar_open': asdict(minute_open),
                            'order_occurrences': 0, 'examples': [],
                        })
                        opening_item['order_occurrences'] += 1
                        if len(opening_item['examples']) < 8:
                            opening_item['examples'].append(detail)
                        account_counts[f'{role}_minute_open_differences'] += 1
                    if not matched_daily:
                        daily_mismatches.append({**detail, 'daily_resolved': asdict(daily_result),
                                                 'actual_fills': actual_fills})
                    for fill in actual_fills:
                        price = float(fill['price'])
                        tolerance = abs(price) * 1e-10
                        eligible = (lows <= price + tolerance) & (highs >= price - tolerance)
                        if fill['trigger'] in {'OPEN', 'OPEN_MARKET'}:
                            eligible[1:] = False
                        reachable = bool(eligible.any())
                        if not reachable:
                            reach_failures.append({**detail, 'fill': fill,
                                                   'scaled_minute_low': float(min(lows)),
                                                   'scaled_minute_high': float(max(highs))})
                        observed_volume = float(volumes[eligible].sum())
                        ratio = float(fill['quantity']) / observed_volume if observed_volume else None
                        if ratio is not None:
                            max_volume_ratio = max(max_volume_ratio, ratio)
                        if ratio is None or ratio > 1:
                            volume_exceptions.append({**detail, 'fill_quantity': fill['quantity'],
                                                      'eligible_bar_volume': observed_volume,
                                                      'ratio': ratio})
                    different = daily_result.filled != strict.filled or (
                        daily_result.filled and strict.filled and not close(daily_result.price, strict.price))
                    if different:
                        opening_limit = strict.reason in {'OPEN_UP_LIMIT_BUY_BLOCKED', 'OPEN_DOWN_LIMIT_SELL_BLOCKED'}
                        category = 'OPEN_PRICE_LIMIT_RULE' if opening_limit else (
                            'STRICT_VS_INCLUSIVE_TOUCH' if inclusive.filled == daily_result.filled and
                            (not inclusive.filled or close(inclusive.price, daily_result.price)) else
                            'OTHER_EXECUTION_RULE_DIFFERENCE')
                        diffkey = (condition, category)
                        item = differences.setdefault(diffkey, {
                            'condition': list(condition), 'category': category,
                            'daily': asdict(daily_result), 'strict_30m': asdict(strict),
                            'inclusive_30m': asdict(inclusive),
                            'session_limits': rules.for_session(day).to_dict(),
                            'daily_quote': {key: quote[key] for key in ('open', 'high', 'low', 'close', 'price_scale')},
                            'raw_bars': bars[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].to_dict('records'),
                            'order_occurrences': 0, 'examples': [],
                        })
                        item['order_occurrences'] += 1
                        if len(item['examples']) < 8:
                            item['examples'].append(detail)
                        account_counts[f'{role}_strict_differences'] += 1
                    account_counts[f'{role}_orders'] += 1
                    account_counts[f'{role}_filled_orders'] += int(actual_filled)
                    account_counts[f'{role}_unfilled_orders'] += int(not actual_filled)
            all_counts.update(account_counts)
            checked[-1].setdefault('runs', []).append({'evaluation_id': evaluation_id,
                'candidate_id': run['candidate_id'], 'counts': dict(account_counts)})
    status = 'PASS_WITH_EXECUTION_SENSITIVITY' if differences or opening_differences else 'PASS'
    if daily_mismatches or reach_failures:
        status = 'OBSERVED_INCONSISTENCY'
    result = {
        'status': status, 'scope': 'All account_evaluation schema 7 artifacts present at initial EX003 directory scan',
        'prepared_minute_reference': raw_reference,
        'minute_content_sha256': fetched.identity.content_sha256,
        'minute_rows': len(minute), 'minute_sessions': len(grouped),
        'account_evidence_files': len(checked), 'unique_evaluation_ids': len(evaluations),
        'counts_with_cross_account_repetition': dict(all_counts),
        'unique_date_side_order_type_limit_conditions': len(unique_conditions),
        'unique_conditions_by_role': {role: len(values) for role, values in unique_conditions_by_role.items()},
        'unique_difference_conditions': len(differences),
        'difference_categories': dict(Counter(x['category'] for x in differences.values())),
        'cross_frequency_ohlc_differences_on_order_days': list(cross_frequency_differences.values()),
        'unique_minute_open_sensitivity_conditions': len(opening_differences),
        'minute_open_sensitivity': list(opening_differences.values()),
        'authenticated_daily_price_scales': sorted(price_scales),
        'daily_contract_mismatches': daily_mismatches,
        'filled_price_not_observed_in_30m': reach_failures,
        'quantity_exceeds_eligible_observed_bar_volume': volume_exceptions,
        'maximum_quantity_to_eligible_observed_bar_volume': max_volume_ratio,
        'differences': list(differences.values()), 'evidence_checked': checked,
        'limits': [
            'Repeated orders across candidates and repeated benchmark accounts are not independent market observations.',
            'Thirty-minute OHLC reachability and aggregate volume do not prove queue priority, opening auction liquidity or full quantity fillability.',
            'Quantity volume checks use eligible bars containing the actual fill price; full bar volume is not volume traded exactly at that price.',
            'Strict sensitivity evaluates each retained order independently; it does not rebuild later cash, positions, signals or returns after a changed fill.',
            'Main strict crossing comparison retains the formal daily open to isolate execution rules; a separate sensitivity substitutes the observed first 30-minute bar open.',
            'DAILY_RANGE_V3 includes limit touches and can differ from strict crossing and opening price-limit handling.',
            'Minute bar-end timestamps only bound intrabar triggering; historical publication and revision times remain unverified.',
            'No account evaluation, provider preparation, supplier refresh or original ledger changes were performed.',
        ],
    }
    destination = EXPERIMENT / 'others/minute_order_validation.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                           encoding='utf-8', newline='\n')
    print(json.dumps({key: result[key] for key in ('status', 'account_evidence_files',
        'unique_evaluation_ids', 'unique_date_side_order_type_limit_conditions',
        'unique_difference_conditions', 'difference_categories')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
