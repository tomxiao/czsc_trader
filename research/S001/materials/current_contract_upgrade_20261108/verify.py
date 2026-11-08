"""Check current S001 target projections against authenticated completed-week evidence."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import StateRecord, StrategyRuntime

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
_adapter_spec = importlib.util.spec_from_file_location('s001_target_adapter', HERE / 'adaptation.py')
adaptation = importlib.util.module_from_spec(_adapter_spec)
_adapter_spec.loader.exec_module(adaptation)


def retained_inputs():
    """Read retained export bytes only after published evidence binds their hashes."""
    report = ROOT / 'research/S001/experiments/EX004_20261106/others'
    summary_ref = EvidenceRef.from_dict(json.loads((report / 'signal_summary.json').read_bytes())['full_evidence'])
    summary = json.loads(summary_ref.resolve(ROOT).read_bytes())
    identity_ref = EvidenceRef.from_dict(json.loads((report / 'input_identity.json').read_bytes())['full_evidence'])
    identity = json.loads(identity_ref.resolve(ROOT).read_bytes())
    exports = ROOT / '.tmp/s001-v4-correction/inputs'
    frames = {}
    for name in ('daily', 'm30', 'weekly', 'raw_daily', 'calendar'):
        path = exports / (name + '.parquet')
        expected = summary['files_sha256'][path.name]
        assert expected == identity['inputs'][name]['parquet_sha256']
        assert sha256(path.read_bytes()).hexdigest() == expected, name
        frames[name] = pd.read_parquet(path)
        frames[name]['Date'] = pd.to_datetime(frames[name].Date)
    return frames, {'signal_evidence': summary_ref.to_dict(), 'input_evidence': identity_ref.to_dict(),
                    'identity': identity, 'files_sha256': summary['files_sha256']}, summary


def retained_execution_inputs():
    """Fetch the authenticated 588080 RAW/limit/calendar assets via public DFLS."""
    from dataflows import (Dataflows, DataSpace, ProviderConfig, DataRequest, Dataset,
                          DataCoverageRequirement, PreparedDataRef)

    preparation = json.loads((ROOT / '.tmp/rsch-frozen-v4-upgrade/s003_s007_data/preparation.json').read_bytes())
    flow = Dataflows(base_dir=ROOT, space=DataSpace(Path('.tmp/rsch-frozen-v4-upgrade/s003_s007-data-space')),
                    providers=ProviderConfig(bindings={}, equity_bindings={}))
    coverage = DataCoverageRequirement(maximum_start_lag_days=None)
    queries = {
        'raw_daily': ('s007_raw_daily', DataRequest(Dataset.ETF_UNADJUSTED_DAILY, '588080.SH',
            '2026-08-01', '2026-11-05', None, 'daily', coverage=coverage)),
        'limits': ('s007_limits', DataRequest(Dataset.SECURITY_PRICE_LIMITS, '588080.SH',
            '2026-08-01', '2026-11-05', None, 'daily', coverage=coverage)),
        'calendar': ('calendar_aug_nov', DataRequest(Dataset.TRADING_CALENDAR, 'SSE',
            '2026-08-01', '2026-11-06', None, 'daily')),
    }
    frames, provenance = {}, {}
    for name, (key, query) in queries.items():
        record = preparation[key]
        ref = record['reference']
        prepared = PreparedDataRef(UUID(ref['space_id']), UUID(ref['preparation_id']), ref['manifest_sha256'])
        fetched = flow.fetch(query, prepared=prepared)
        assert fetched.identity.content_sha256 == record['identity']['content_sha256']
        frames[name] = fetched.dataframe
        provenance[name] = record
    limits = frames['limits']
    assert len(limits) == 63 and not limits.Date.duplicated().any()
    assert {'DownLimit', 'UpLimit'}.issubset(limits.columns)
    return frames, provenance


def compact_provenance(provenance):
    identity = provenance['identity']
    return {'signal_evidence': provenance['signal_evidence'], 'input_evidence': provenance['input_evidence'],
            'files_sha256': provenance['files_sha256'], 'prepared_ref': identity['prepared_ref'],
            'inputs': {name: {'rows': value['rows'], 'parquet_sha256': value['parquet_sha256'],
                'content_sha256': value['identity']['content_sha256'], 'asset_id': value['asset_id']}
                       for name, value in identity['inputs'].items()},
            'note': 'Full original metadata remains in the hash-bound input_evidence; not duplicated here.'}


def main():
    frames, provenance, previous = retained_inputs()
    source = adaptation.ORIGINAL_ROOTS['v1'] / 'S001/releases/v1/src/strategy_runtime/signal_math.py'
    old_math_hash = sha256(source.read_bytes()).hexdigest()
    assert old_math_hash == previous['math_source_sha256']['research\\S001\\runtime_upgrade_v4\\signal_math.py']
    spec = importlib.util.spec_from_file_location('unchanged_s001_math', source)
    math = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(math)
    daily, intraday, weekly, calendar = [frames[k] for k in ('daily', 'm30', 'weekly', 'calendar')]
    open_days = calendar.loc[calendar.IsOpen.eq(1), 'Date']
    ends = open_days.groupby(open_days.dt.to_period('W-SUN')).max()
    weekly_ends = weekly.Date.dt.to_period('W-SUN').map(ends)
    complete = weekly.loc[weekly.Date.eq(weekly_ends)]
    assert pd.Timestamp('2026-09-30') in set(complete.Date)
    assert pd.Timestamp('2026-11-05') not in set(complete.Date)
    original_signals = math._signals
    # EX004 authenticated the unchanged kernel's prefix identity at Sep02,
    # Sep30 and Nov05. Reuse that causal cache result, not a fitted signal table.
    full = {tag: original_signals(math._ohlcv(frame, '588080.SH'), freq, config, init, tag)
            for tag, frame, freq, config, init in (
                ('30m', intraday, '30分钟', math._INTRADAY_CONFIG, 500),
                ('daily', daily, '日线', math._DAILY_CONFIG, 30))}
    weekly_cache = {}

    def signals(frame, freq, configs, init, tag):
        if tag in full:
            return full[tag].loc[:frame.dt.max()].copy()
        key = sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()
        if key not in weekly_cache:
            weekly_cache[key] = original_signals(frame, freq, configs, init, tag)
        return weekly_cache[key].copy()

    prior = {(r['version'], r['signal_day']): r for r in previous['native_step_checks']}
    checks = []
    candidates = {}
    for version, candidate_id in (('v1', 'C9990'), ('v2', 'C9991')):
        output = ROOT / '.tmp/s001-current-contract-cycle-verification' / version / 'strategy_runtime'
        candidate = adaptation.build(version, candidate_id, output)
        assert (output / 'signal_math.py').read_bytes() == source.read_bytes()
        StrategyRuntime().describe(candidate)
        candidates[version] = {'content_sha256': candidate.content_identity.content_sha256,
                               'definition': candidate.definition.to_dict()}
        with candidate.bind_replay() as invocation:
            step = invocation.function
            kernel = step.__globals__['calculate_s001_history']
            kernel.__globals__['_signals'] = signals
            for day in daily.loc[daily.Date.between('2026-09-02', '2026-11-05'), 'Date']:
                observations = {name: SimpleNamespace(to_frame=lambda f=f: f.copy()) for name, f in (
                    ('adjusted_daily', daily.loc[daily.Date <= day]),
                    ('adjusted_30m', intraday.loc[intraday.Date.dt.normalize() <= day]),
                    ('adjusted_weekly', complete.loc[complete.Date <= day]))}
                ctx = SimpleNamespace(parameters=json.loads(candidate.definition.parameters_json),
                    observations=observations,
                    history=SimpleNamespace(last=lambda day=day: {'Date': day.tz_localize('Asia/Shanghai') + pd.Timedelta(hours=15)}))
                # Deliberately no cash, quantity, planning or execution quote in
                # this context: strategy projection cannot depend on them.
                result = step(ctx, None)
                candidate.definition.state_schema.validate_record(result.account, scope='account')
                assert type(result.cycle_values) is StateRecord
                candidate.definition.state_schema.validate_record(result.cycle_values, scope='cycle')
                facts = {item.key: item.text for item in result.decision.explanation.basis}
                old = prior[(version, day.date().isoformat())]
                assert result.decision.target == old['native_target']
                assert float(facts['factor_score']) == old['native_score']
                assert facts['regime'] == old['native_regime']
                checks.append({'version': version, 'signal_day': day.date().isoformat(),
                               'target': result.decision.target, 'status': 'PASS'})
        print(version, 'PASS', flush=True)
    result = {'status': 'PASS', 'financial_signal_checks': checks, 'count': len(checks),
        'unchanged_signal_math_sha256': old_math_hash, 'provenance': compact_provenance(provenance),
        'candidates': candidates, 'completed_week_only': True,
        'cash_and_quantity_access': False, 'typed_empty_cycle_state': True,
        'scope': '82 current step projections vs published prior completed-week prefix signals; identical financial kernel and parameters',
        'limits': ['No old/new account-economic equivalence claim',
                   'Historical locked entry quantity replaced by current-account-equity target semantics',
                   'Retained 2026-11-05 vendor snapshot is not every historical vendor revision',
                   'Reuse EX004 causal raw-factor prefix proof on byte-identical math; no account replay performed here']}
    (HERE / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'count': len(checks),
                      'targets': sorted({c['target'] for c in checks})}, ensure_ascii=False))


if __name__ == '__main__':
    main()
