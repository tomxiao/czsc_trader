"""Describe retained LITE price changes; never run an account or alter a rule.

This post-design description uses only run.context() and the existing request's
PreparedDataRef via public DFLS fetch. No prepare, vendor download, account replay,
2026 price, fee-free strategy, causal attribution, or candidate selection occurs.
The 2018 warmup is fetched for identity/grid verification but excluded from every
price-change statistic. The path starts at the first 2019 session's opening-bar
Open and ends at the last 2025 session's closing-bar Close.

For session t, intraday_log = log(C_t/O_t); overnight_log = log(O_t/C_previous).
The first development session's overnight is excluded, even though 2018 prices
are present. Across calendar years an overnight belongs to its ARRIVAL session:
therefore years after 2019 start at the previous year's last Close. The annual
contributions add exactly to the full-period firstOpen-to-lastClose log change.
All sums are natural-log PRICE changes, not percentage-point trading returns.
Neither exp(component_sum)-1 nor any frictionless account is reported.

Independent SESSIONS evidence supplies the exact 30-minute grid, including short
sessions. Grid mismatch is an error. Existing MISSING rows stay missing: no
forward fill, interpolation, day dropping, or bridging a missing session. An
endpoint price is known only when its own row is OBSERVED or ZERO_VOLUME and
finite/positive. Internal gaps do not invalidate known Open/Close endpoints, but
are counted separately; endpoint-known must not be called fully observed. Prices
on zero-volume or ExecutionBlocked rows imply no executability. Missing endpoints
yield null components and explicit unknown counts. Partial known-component sums
are labelled as such; a complete reconciliation is PASS only when every required
component and both anchors are known. Otherwise output is INCOMPLETE and main
raises after saving the diagnostic. A numeric identity failure raises directly.

Output others/session_price_description.json preserves prepared reference,
original product content hashes, independent calendar hash, exact requests,
per-session endpoint facts, yearly/full-period counts and reconciliation. It is
an explanation of where observed price movement occurred, not why it occurred,
and cannot itself explain achievable strategy performance, costs, limit fills,
or the timing of exposure. The frozen EX011 rules remain unchanged.
"""
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import json
import math
from pathlib import Path

from dataflows import BarFrequency, TimeInterval, TradingSession

from run import (WORK, SPEC, DATA_READINESS, candidate, configurations, context,
                 read, request, save)


START = date(2019, 1, 1)
END = date(2025, 12, 31)
TOLERANCE = 1e-10


def calendar(metadata):
    """Reconstitute public TradingSession values from retained source evidence."""
    sessions = tuple(TradingSession(
        date.fromisoformat(row['session_date']), row['timezone'],
        tuple(TimeInterval(datetime.fromisoformat(seg['start']),
                           datetime.fromisoformat(seg['end'])) for seg in row['segments']))
        for row in metadata['sessions'])
    days = [item.session_date for item in sessions]
    if not sessions or days != sorted(set(days)):
        raise ValueError('independent sessions must be nonempty, unique and ordered')
    if any(item.timezone != 'America/New_York' or not date(2018, 11, 1) <= item.session_date <= END
           for item in sessions):
        raise ValueError('session scope exceeds authorized warmup/development prices')
    return sessions


def endpoint(row, field):
    if row['BarStatus'] not in {'OBSERVED', 'ZERO_VOLUME'}:
        return None
    value = float(row[field])
    return value if math.isfinite(value) and value > 0 else None


def sign_counts(values):
    known = [value for value in values if value is not None]
    return {'known': len(known), 'unknown': len(values)-len(known),
            'positive': sum(value > 0 for value in known),
            'negative': sum(value < 0 for value in known),
            'zero': sum(value == 0 for value in known),
            'known_component_log_sum': math.fsum(known),
            'complete_log_sum': math.fsum(known) if len(known) == len(values) else None}


def ratio_log(end, start):
    return None if end is None or start is None else math.log(end/start)


def summarize(rows, previous_close, *, first_period):
    intraday = sign_counts([row['intraday_log'] for row in rows])
    overnight = sign_counts([row['overnight_log'] for row in rows
                             if not row['overnight_excluded']])
    overnight['excluded_first_development_session'] = sum(row['overnight_excluded'] for row in rows)
    combined = sign_counts([row['combined_log'] for row in rows])
    anchor = rows[0]['open'] if first_period else previous_close
    direct = ratio_log(rows[-1]['close'], anchor)
    reconstructed = (None if intraday['unknown'] or overnight['unknown'] else
                     math.fsum((intraday['complete_log_sum'], overnight['complete_log_sum'])))
    residual = None if direct is None or reconstructed is None else reconstructed-direct
    if residual is not None and abs(residual) > TOLERANCE:
        raise ValueError('price decomposition does not telescope to its declared anchors')
    return {'first_session': rows[0]['session_date'], 'last_session': rows[-1]['session_date'],
            'sessions': len(rows), 'grid_complete_sessions': len(rows),
            'fully_observed_sessions': sum(row['fully_observed'] for row in rows),
            'sessions_with_missing_rows': sum(row['missing_bars'] > 0 for row in rows),
            'sessions_with_zero_volume_rows': sum(row['zero_volume_bars'] > 0 for row in rows),
            'sessions_with_execution_blocked_rows': sum(row['execution_blocked_bars'] > 0 for row in rows),
            'sessions_with_both_endpoints_known': sum(row['open'] is not None and row['close'] is not None for row in rows),
            'missing_bars': sum(row['missing_bars'] for row in rows),
            'zero_volume_bars': sum(row['zero_volume_bars'] for row in rows),
            'execution_blocked_bars': sum(row['execution_blocked_bars'] for row in rows),
            'intraday': intraday, 'overnight': overnight, 'combined': combined,
            'anchor_kind': 'FIRST_DEVELOPMENT_OPEN' if first_period else 'PREVIOUS_YEAR_LAST_CLOSE',
            'anchor_price': anchor, 'first_session_open': rows[0]['open'],
            'last_session_close': rows[-1]['close'], 'direct_anchor_to_last_close_log': direct,
            'component_sum_log': reconstructed, 'reconciliation_residual': residual,
            'reconciliation': 'PASS' if residual is not None else 'INCOMPLETE'}


def describe(bars, sessions):
    expected = tuple(bar for session in sessions for bar in session.bars(BarFrequency.M30))
    if (len(bars) != len(expected)
            or tuple(bars.BarStart) != tuple(bar.start for bar in expected)
            or tuple(bars.Date) != tuple(bar.end for bar in expected)):
        raise ValueError('retained bars differ from the independent exact session grid')
    if not set(bars.BarStatus).issubset({'OBSERVED', 'ZERO_VOLUME', 'MISSING'}):
        raise ValueError('unknown observation status')
    rows, offset, previous_close = [], 0, None
    for session in sessions:
        count = len(session.bars(BarFrequency.M30))
        part = bars.iloc[offset:offset+count]
        offset += count
        if session.session_date < START:
            continue
        opening, close = endpoint(part.iloc[0], 'Open'), endpoint(part.iloc[-1], 'Close')
        excluded = not rows
        intraday = ratio_log(close, opening)
        overnight = None if excluded else ratio_log(opening, previous_close)
        combined = (intraday if excluded else None if intraday is None or overnight is None
                    else math.fsum((intraday, overnight)))
        statuses = Counter(part.BarStatus)
        rows.append({'session_date': session.session_date.isoformat(), 'expected_bars': count,
                     'grid_complete': True, 'fully_observed': statuses['OBSERVED'] == count,
                     'missing_bars': statuses['MISSING'], 'zero_volume_bars': statuses['ZERO_VOLUME'],
                     'execution_blocked_bars': int(part.ExecutionBlocked.sum()),
                     'open_status': str(part.BarStatus.iloc[0]), 'close_status': str(part.BarStatus.iloc[-1]),
                     'open': opening, 'close': close, 'previous_development_session_close': previous_close,
                     'overnight_excluded': excluded, 'intraday_log': intraday,
                     'overnight_log': overnight, 'combined_log': combined})
        # Preserve adjacency even when an endpoint is unknown; never skip a day.
        previous_close = close
    if not rows or rows[0]['session_date'] != '2019-01-02' or rows[-1]['session_date'] != '2025-12-31':
        raise ValueError('description must cover the exact retained development endpoints')
    yearly, previous_close = {}, None
    for year in range(2019, 2026):
        selected = [row for row in rows if row['session_date'].startswith(str(year))]
        if not selected:
            raise ValueError('an entire development year is absent')
        yearly[str(year)] = summarize(selected, previous_close, first_period=year == 2019)
        previous_close = selected[-1]['close']
    full = summarize(rows, None, first_period=True)
    additive = None
    if full['reconciliation'] == 'PASS' and all(item['reconciliation'] == 'PASS' for item in yearly.values()):
        additive = math.fsum(item['component_sum_log'] for item in yearly.values())-full['component_sum_log']
        if abs(additive) > TOLERANCE:
            raise ValueError('annual contributions do not sum to the full-period decomposition')
    return {'status': 'PASS' if additive is not None else 'INCOMPLETE',
            'annual_additivity_residual': additive, 'absolute_log_tolerance': TOLERANCE,
            'full_period': full, 'by_year': yearly, 'sessions': rows,
            'warmup_sessions_excluded': sum(session.session_date < START for session in sessions),
            'warmup_and_development_grid_bars': len(expected)}


def main():
    params = configurations()['C0036']
    cand = candidate('C0036', params)
    definition = json.loads(json.dumps(cand.definition.to_dict(), default=str))
    if read(WORK/'protocols/definitions.json')['C0036'] != definition:
        raise ValueError('current definition differs from frozen EX011 definition')
    req = request(cand)
    queries = dict(req.request_items(SPEC))
    research = context(workers=1)
    retained = read(DATA_READINESS)
    original = {item['key']: item['sha256'] for item in retained['products']}
    products = {}
    identities = {}
    for key in ('bars', 'sessions'):
        query = queries[key]
        if (query.parameters.instrument.symbol != 'LITE'
                or query.parameters.query.start != date(2018, 11, 1)
                or query.parameters.query.end != END
                or query.parameters.query.frequency is not BarFrequency.M30):
            raise ValueError('read request exceeds fixed LITE scope')
        item = research.data.fetch(query, prepared=req.prepared)
        if not item.ready:
            raise RuntimeError(str(item.error))
        original_key = f'LITE:{BarFrequency.M30.value}:{key.upper()}'
        if item.identity.content_sha256 != original[original_key]:
            raise ValueError('original retained LITE product hash changed')
        products[key] = item
        identities[key] = {'content_sha256': item.identity.content_sha256,
                           'request': asdict(query), 'rows': len(item.dataframe)}
    sessions = calendar(products['sessions'].identity.metadata)
    if tuple(products['sessions'].dataframe.SessionDate) != tuple(str(s.session_date) for s in sessions):
        raise ValueError('session rows and independent session metadata disagree')
    if sessions != calendar(products['bars'].identity.metadata):
        raise ValueError('bars and independent session product calendars disagree')
    result = describe(products['bars'].dataframe, sessions)
    result.update(schema='S017_SESSION_PRICE_DESCRIPTION_V1', instrument='LITE',
        units='NATURAL_LOG_PRICE_CHANGE', price_basis='RAW_RTH_30M_ENDPOINTS',
        prepared=asdict(req.prepared), products=identities,
        script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        scope={'fetched': ['2018-11-01', '2025-12-31'], 'described': ['2019-01-02', '2025-12-31'],
               'first_development_overnight': 'EXCLUDED', 'annual_overnight_assignment': 'ARRIVAL_SESSION_YEAR'},
        limitations=['PRICE_DESCRIPTION_NOT_TRADABLE_RETURN', 'NO_CAUSAL_ATTRIBUTION',
                     'NO_FEES_OR_EXECUTION_MODEL_APPLIED', 'RAW_PRICE_NOT_TOTAL_SHAREHOLDER_RETURN',
                     'INTERNAL_GAPS_AND_ENDPOINT_KNOWLEDGE_REPORTED_SEPARATELY',
                     'FROZEN_STRATEGY_UNCHANGED', 'NO_2026_PRICE_ACCESS'])
    save(WORK/'others/session_price_description.json', result)
    if result['status'] != 'PASS':
        raise RuntimeError('unknown endpoint components prevent complete price decomposition; diagnostic saved')
    print('SESSION_PRICE_DESCRIPTION_PASS', flush=True)


if __name__ == '__main__':
    main()
