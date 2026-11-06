"""Explicit, bounded economic facts supplied by the operational data owner.

This adapter authenticates bytes and declared coverage, not the truth of an
upstream assertion. A verified receipt must be reviewed before installation.
Missing dates never become tradable rules or a no-action assertion.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .contract import EquityDataRequest, ProviderBinding
from .equity_contracts import EquityProduct, MarketId, PriceAdjustment, ProviderKey, SourceRef
from .equity_data import equity_metadata, sessions_from_metadata, validate_equity_frame
from .errors import DataContractError, IncompleteDataError


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise DataContractError(f'invalid economic evidence {label} fields')


def _asset(root, ref):
    _exact(ref, ('path', 'sha256'), 'asset')
    if type(ref['path']) is not str or not ref['path'] or Path(ref['path']).is_absolute():
        raise DataContractError('economic evidence asset requires a relative path')
    path = (root / ref['path']).resolve()
    if not path.is_relative_to(root):
        raise DataContractError('economic evidence asset escapes its manifest directory')
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != ref['sha256']:
        raise DataContractError('economic evidence asset hash mismatch', path=ref['path'])
    return payload


def _frame(payload):
    rows = json.loads(payload)
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise DataContractError('economic evidence data requires JSON row objects')
    result = pd.DataFrame(rows)
    for name in ('Date', 'AvailableDate', 'PayAt', 'BuySellableAt', 'SettlementAt'):
        if name in result:
            values = result[name]
            for value in values.dropna():
                stamp = pd.Timestamp(value)
                if pd.isna(stamp) or stamp.tzinfo is None:
                    raise DataContractError('economic evidence timestamps must be explicit and aware', field=name)
            result[name] = pd.to_datetime(values, utc=True)
    return result


def equity_evidence_bindings(*, source: SourceRef, market: MarketId,
        manifest_path: Path, session_binding: ProviderBinding) -> dict[ProviderKey, ProviderBinding]:
    """Bind exact-source actions and dated rules for either market.

    The manifest may be extended with new verified facts, without changing
    already-published assets. Each request reads the current manifest; existing
    PreparedDataRef objects remain pinned by DFLS. No network fallback exists.
    """
    if type(source) is not SourceRef or type(market) is not MarketId:
        raise TypeError('economic evidence requires SourceRef and MarketId')
    if not isinstance(manifest_path, Path) or type(session_binding) is not ProviderBinding:
        raise TypeError('economic evidence requires a Path and independent session ProviderBinding')
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent

    def fetch(request):
        p = request.parameters
        if p.source != source or p.instrument.market is not market:
            raise DataContractError('MARKET_CONTRACT_MISMATCH: economic evidence source differs')
        if p.query.product not in (EquityProduct.ACTIONS, EquityProduct.CONSTRAINTS):
            raise DataContractError('economic evidence provides only actions and constraints')
        if p.query.adjustment is not PriceAdjustment.NONE:
            raise DataContractError('economic facts require RAW price units')
        payload = manifest_path.read_bytes()
        manifest = json.loads(payload)
        _exact(manifest, ('schema_version', 'source', 'market', 'instruments'), 'manifest')
        if (type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
                or manifest['source'] != asdict(source) or manifest['market'] != market.value
                or type(manifest['instruments']) is not list):
            raise DataContractError('economic evidence manifest identity differs')
        matches = []
        seen = set()
        for item in manifest['instruments']:
            _exact(item, ('instrument', 'actions', 'constraints'), 'instrument')
            identity = json.dumps(item['instrument'], sort_keys=True)
            if identity in seen:
                raise DataContractError('duplicate economic evidence instrument')
            seen.add(identity)
            if item['instrument'] == asdict(p.instrument):
                matches.append(item)
        if len(matches) != 1:
            raise IncompleteDataError('no explicit economic evidence for instrument', symbol=p.instrument.symbol)
        item = matches[0]
        if p.query.product is EquityProduct.ACTIONS:
            declared = item['actions']
            _exact(declared, ('start', 'end', 'complete', 'data', 'evidence'), 'actions')
            if declared['complete'] is not True:
                raise IncompleteDataError('complete economic-event evidence is required')
        else:
            if type(item['constraints']) is not dict or not set(item['constraints']).issubset({'daily', '30m'}):
                raise DataContractError('invalid economic evidence frequencies')
            declared = item['constraints'].get(p.query.frequency.value)
            if declared is None:
                raise IncompleteDataError('no explicit dated trading rules for requested frequency')
            _exact(declared, ('start', 'end', 'data', 'evidence'), 'constraints')
        first, last = date.fromisoformat(declared['start']), date.fromisoformat(declared['end'])
        if first > last or p.query.start < first or p.query.end > last:
            raise IncompleteDataError('request exceeds verified economic evidence coverage',
                start=declared['start'], end=declared['end'])
        receipt = _asset(root, declared['evidence'])
        if not receipt.strip():
            raise DataContractError('economic evidence receipt is empty')
        original = _frame(_asset(root, declared['data']))
        calendar_request = EquityDataRequest(p.instrument, source,
            replace(p.query, product=EquityProduct.SESSIONS, start=first, end=last))
        calendar_frame, calendar_metadata = session_binding.fetch(calendar_request)
        validate_equity_frame(calendar_frame, calendar_request, calendar_metadata)
        sessions = sessions_from_metadata(calendar_metadata)
        whole_request = EquityDataRequest(p.instrument, source, replace(p.query, start=first, end=last))
        proof = json.dumps({'manifest_sha256': sha256(payload).hexdigest(),
            'data': declared['data'], 'evidence': declared['evidence'],
            'declared_start': first.isoformat(), 'declared_end': last.isoformat()}, sort_keys=True)
        meta = {'coverage_evidence': proof, 'coverage_evidence_sha256': sha256(proof.encode()).hexdigest(),
                'evidence_basis': 'EXPLICIT_OWNER_VERIFIED_FILES',
                'economic_price_basis': 'RAW',
                'constraint_contract': 'DATED_EQUITY_RULES_V1'}
        if p.query.product is EquityProduct.ACTIONS:
            meta['action_history_complete'] = True
            if original.empty:
                stamp = sessions[0].segments[0].start
                original = pd.DataFrame([dict(Date=stamp, AvailableDate=stamp,
                    EventId='verified-empty:' + declared['data']['sha256'], Kind='NONE',
                    Ratio=1., CashPerShare=0., PayAt=None)])
                meta['no_actions_verified'] = True
            elif 'Kind' in original and original.Kind.eq('NONE').any():
                raise DataContractError('supply empty verified event list, not a manufactured NONE row')
        validate_equity_frame(original, whole_request,
            equity_metadata(whole_request, sessions, availability_basis='EXPLICIT_EVIDENCE_TIMESTAMPS') | meta)
        local_days = pd.to_datetime(original.Date).dt.tz_convert(p.instrument.timezone).dt.date
        if not local_days.between(first, last).all():
            raise DataContractError('economic rows exceed their declared coverage')
        selected = original.loc[local_days.between(p.query.start, p.query.end)].copy().reset_index(drop=True)
        selected_sessions = tuple(s for s in sessions if p.query.start <= s.session_date <= p.query.end)
        if not selected_sessions:
            raise IncompleteDataError('economic evidence interval has no trading session')
        if p.query.product is EquityProduct.ACTIONS and (selected.empty or selected.Kind.eq('NONE').all()):
            stamp = selected_sessions[0].segments[0].start
            selected = pd.DataFrame([dict(Date=stamp, AvailableDate=stamp,
                EventId='verified-empty:' + declared['data']['sha256'] + ':' + p.query.start.isoformat(),
                Kind='NONE', Ratio=1., CashPerShare=0., PayAt=None)])
            meta['no_actions_verified'] = True
        metadata = equity_metadata(request, selected_sessions, availability_basis='EXPLICIT_EVIDENCE_TIMESTAMPS') | meta
        validate_equity_frame(selected, request, metadata)
        return selected, metadata

    return {ProviderKey(product, market, source): ProviderBinding(source.provider, source.revision, fetch)
            for product in (EquityProduct.ACTIONS, EquityProduct.CONSTRAINTS)}
