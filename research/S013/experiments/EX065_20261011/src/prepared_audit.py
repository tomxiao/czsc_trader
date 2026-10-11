"""Future real-prepared-input adapter. Never claims PURE_FIXTURE is authentication."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from dataflows import Dataset, canonical_frame_sha256
from strategy_runtime import canonical_sha256
import state_oracle
import state_audit


def fetched_input(ctx, binding, name, pins):
    request = binding.plan.requests[name]
    if binding.prepared is None:
        raise ValueError('Explicit public prepared input required')
    value = ctx.data.fetch(request, prepared=binding.prepared)
    if (not value.ready or value.identity.dataset != str(request.dataset)
            or value.identity.symbol != request.symbol
            or canonical_frame_sha256(value.dataframe) != value.identity.content_sha256):
        raise ValueError('Public prepared identity/content/request mismatch')
    public_request = binding.plan.to_dict()['requests'][name]
    pin = pins.get(canonical_sha256(public_request))
    if (pin is None or pin['request'] != public_request
            or pin['identity'] != identity_record(value.identity)
            or pin['space_id'] != str(binding.prepared.space_id)):
        raise ValueError('Prepared input not exactly covered by public pinned subset manifest')
    return value


def dates(values):
    result = pd.DatetimeIndex(pd.to_datetime(values, errors='raise')).normalize().as_unit('ns')
    if result.hasnans or result.tz is not None or not result.is_unique or not result.is_monotonic_increasing:
        raise ValueError('Ordered unique naive dates required')
    return result


def calendar_contract(bound, binding, frame, daily, calendar):
    """Full prepared calendar, previous-session relation, signal and execution mapping."""
    plan = binding.plan
    request = plan.requests[plan.calendar_name]
    days = dates(calendar.Date)
    pd.testing.assert_index_equal(days, pd.date_range(request.start, request.end).as_unit('ns'), check_names=False)
    if not calendar.IsOpen.isin((0, 1)).all():
        raise ValueError('Invalid calendar open flag')
    opened = days[calendar.IsOpen.to_numpy() == 1]
    pd.testing.assert_index_equal(opened, dates(plan.calendar_dates), check_names=False)
    previous = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), 'PreviousTradingDate'])).normalize().as_unit('ns')
    pd.testing.assert_index_equal(previous[1:], opened[:-1], check_names=False)
    if not np.all(previous < opened):
        raise ValueError('Strict previous trading relation required')
    window = plan.tradable_window
    valid = opened[(opened >= pd.Timestamp(window.start)) & (opened <= pd.Timestamp(window.end))]
    locations = opened.get_indexer(valid)
    if not len(valid) or not np.all(locations > 0):
        raise ValueError('First signal predecessor missing')
    signals = opened[locations - 1]
    pd.testing.assert_index_equal(dates(frame.signal_date), signals, check_names=False)
    pd.testing.assert_index_equal(dates(frame.valid_session), valid, check_names=False)
    expected = {v.date(): s.date() for s, v in zip(signals, valid, strict=True)}
    if dict(plan.signal_dates) != expected:
        raise ValueError('Complete public signal calendar mapping differs')
    execution = dates(bound.execution_data.execution_daily.dt)
    pd.testing.assert_index_equal(execution, signals.union(valid).sort_values(), check_names=False)
    pd.testing.assert_index_equal(dates(bound.execution_data.evaluation_sessions), valid, check_names=False)
    daily_dates = dates(daily.Date)
    pd.testing.assert_index_equal(daily_dates.intersection(execution), signals, check_names=False)
    if daily_dates[-1] != signals[-1]:
        raise ValueError('Signal OHLC must end at final T; no future signal price')
    return tuple(signals), tuple(zip(signals, valid, strict=True))


def audit_prepared(ctx, request, result, bridge, pins):
    """Read only already bound public data; caller authenticates entire native pair first."""
    helper, _, _ = bridge.capabilities()
    audit, oracle = state_audit, state_oracle
    if request.symbol != '510500.SH' or set(request.input_bindings) != {'full'}:
        raise ValueError('Fixed full S013 input contract required')
    binding = request.input_bindings['full']
    if binding.plan.requests['daily'].dataset != Dataset.ETF_OHLCV:
        raise ValueError('Signal formulas require original ADJUSTED/HFQ ETF OHLCV')
    if (request.execution_data.pricing.basis != request.price_basis
            or request.price_basis.value != 'HFQ_RESEARCH'):
        raise ValueError('Original public execution pricing/factor/anchor contract required')
    daily = fetched_input(ctx, binding, 'daily', pins)
    calendar = fetched_input(ctx, binding, binding.plan.calendar_name, pins)
    if calendar.identity.content_sha256 != binding.plan.calendar_sha256:
        raise ValueError('Public bound calendar hash mismatch')
    frame = result.runs[0].execution.decisions.copy()
    sessions, pairs = calendar_contract(request, binding, frame, daily.dataframe, calendar.dataframe)
    p = json.loads(json.dumps(dict(request.strategy.payload['parameters']), default=dict, allow_nan=False))
    state_audit.policy_for(p)
    feature_view = dict(p)
    if p['mechanism'] == state_audit.GAP:
        feature_view['mechanism'] = state_audit.ORIGINAL
    typed = helper.C8880Parameters.from_parameters(feature_view)
    certificate = helper.certify_features(helper.FeatureCertificateRequest(daily.dataframe, sessions, typed))
    content = bridge.bindings(daily.dataframe, sessions, feature_view, pairs)
    bridge.validate_certificate(certificate, typed, content, helper)
    independent = certificate.features
    native = frame.set_index(pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).as_unit('ns'))
    pd.testing.assert_index_equal(native.index, independent.index.as_unit('ns'), check_names=False)
    fields = {'close': 'Close', 'acf1': 'acf20', 'bear_acf_raw': 'acf20', 'momentum20': 'momentum20',
              'bull_range_position': 'bull_range_position', 'bear_range_position': 'bear_range_position',
              'regime_momentum': 'regime_momentum', 'previous_regime_momentum': 'previous_regime_momentum',
              'entry_signal_close': 'Close', 'entry_signal_open': 'Open', 'previous_signal_close': 'previous_close',
              'confirmation_score': 'confirmation_score', 'confirmation_acf': 'confirmation_acf',
              'confirmation_turnover': 'confirmation_turnover', 'confirmation_volume': 'confirmation_volume'}
    for name, other in fields.items():
        observed = native[name].to_numpy(dtype=float)
        if not np.isfinite(observed).all() or not np.allclose(observed, independent[other].to_numpy(),
                atol=helper.NUMERIC_ATOL, rtol=helper.NUMERIC_RTOL):
            raise ValueError('Independent full feature mismatch: ' + name)
    if p['mechanism'] == state_audit.GAP:
        condition = (independent.Open < independent.previous_close) & (independent.Close > independent.Open)
        if native['gap_repair_condition'].dtype != np.dtype(bool) or not np.array_equal(native['gap_repair_condition'].to_numpy(), condition.to_numpy()):
            raise ValueError('Independent gap-repair OHLC condition differs')
    for name in ('regime', 'previous_regime'):
        if not np.array_equal(native[name].to_numpy(), independent[name].to_numpy()):
            raise ValueError('Discrete route mismatch: ' + name)
    boundary = (independent.regime == 'bull') & (independent.previous_regime == 'bear')
    for name, expected in (('entry_direction_up', independent.body_up), ('entry_direction_gate_applies', boundary)):
        if native[name].dtype != np.dtype(bool) or not np.array_equal(native[name].to_numpy(), expected.to_numpy()):
            raise ValueError('Discrete BODY/boundary mismatch: ' + name)
    features = tuple(oracle.Feature(str(r.regime), str(r.previous_regime), float(r.Close), float(r.Open),
        float(r.bull_range_position), float(r.bear_range_position), float(r.acf20), float(r.momentum20),
        float(r.confirmation_score), float(r.previous_close)) for r in independent.itertuples())
    rows = tuple({**row, 'signal_date': pair[0], 'execution_date': pair[1]}
                 for row, pair in zip(native.to_dict('records'), pairs, strict=True))
    # These booleans are derived after public prepared fetch/content/calendar authentication;
    # there is no caller-supplied certification bool or PURE_FIXTURE receipt on this path.
    state = audit.audit_signal_rows(p, rows, features,
        audit.FeatureCertificate(bridge.FEATURE_SHA, content['daily_required_columns_sha256'], True, True))
    # Audit original eligibility/context diagnostics too; no tolerance or score substitution
    # is permitted for discrete decisions, including thresholds close to independent floats.
    policy = audit.policy_for(p)
    bull, bear, threshold = audit.rules(p)
    before = oracle.State()
    for row, feature in zip(rows, features, strict=True):
        outcome = oracle.step(policy, before, feature, bull, bear, threshold)
        manager = outcome.management_route
        rule = bull if manager == 'bull' else bear
        position = feature.bull_position if manager == 'bull' else feature.bear_position
        acf_pass = rule.acf_min is None or feature.acf >= rule.acf_min
        eligible = (position <= rule.entry and (rule.momentum_min is None or feature.momentum >= rule.momentum_min)
            and (acf_pass or outcome.recovered))
        for name, expected in (('entry_eligible', eligible), ('entry_acf_pass', acf_pass),
                ('confirmation_exit_context', before.last_reason or 'initial')):
            if row[name] != expected:
                raise ValueError('Independent eligibility/context mismatch: ' + name)
        for name, expected in (('range_position', position), ('entry_acf_value', feature.acf)):
            if not np.isfinite(row[name]) or not np.isclose(row[name], expected, atol=helper.NUMERIC_ATOL, rtol=helper.NUMERIC_RTOL):
                raise ValueError('Independent selected-route feature mismatch: ' + name)
        before = outcome.next_state
    return {'status': 'PASS', 'scope': 'Real prepared input plus independent features and full signal state',
            'daily_identity': identity_record(daily.identity), 'calendar_identity': identity_record(calendar.identity),
            'prepared_reference': {'space_id': str(binding.prepared.space_id),
                'preparation_id': str(binding.prepared.preparation_id), 'manifest_sha256': binding.prepared.manifest_sha256},
            'content_bindings': content,
            'certificate_provenance': dict(certificate.provenance), 'state_audit': state,
            'actual_parameters_sha256': canonical_sha256(p),
            'feature_certificate_view': {'parameters_sha256': canonical_sha256(feature_view),
                'only_category_mapping': None if p == feature_view else {'mechanism': {'before': p['mechanism'], 'after': feature_view['mechanism']}},
                'scope': 'Only mechanism enum label mapped for unchanged numeric formulas; actual native/state/source parameters remain exact'},
            'pricing': {'basis': request.price_basis.value, 'anchor_date': request.execution_data.pricing.anchor_date.isoformat(),
                'anchor_factor': request.execution_data.pricing.anchor_factor,
                'fingerprint': request.execution_data.pricing.fingerprint},
            'adapter_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'cash_audit_is_separate': True}


def identity_record(value):
    return {name: getattr(value, name) for name in ('dataset', 'source', 'symbol', 'data_start', 'data_cutoff', 'content_sha256')} | {'metadata': dict(value.metadata)}
