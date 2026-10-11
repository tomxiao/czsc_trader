"""Native center four gates, authenticated path contrast, independent funds."""
import pandas as pd
from strategy_runtime import canonical_sha256
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
import ledger_reference as ledger
from account_reference import verify_account
from analysis_reference import summarize, paired
from raw_recovery_oracle import audit_raw_recovery
import importlib.util
from common import ROOT, RUNS, CACHE, SOURCE_CALLS, context, read, write, cache_read, file_hash
from precheck import source_check


GATES = {'return', 'annual_drawdown', 'frequency', 'negative_buyhold_year_profit'}


def reused_account(config):
    if config['label'] == 'B0-RAW-BODY':
        bound, result = cache_read(ROOT / '.tmp/s013-mechanism-EX054/N0.pkl.gz')
        reference = read(ROOT / 'research/S013/assets/runs/EX054_20261011/account_references.json')['N0']
    else:
        native_label = 'B0-TIME' if config['label'] == 'B0-TIME' else 'N0'
        prepared = cache_read(ROOT / '.tmp/s013-mechanism-EX043/parameters/prepared.pkl.gz')
        transport = next(row for row in prepared if row['label'] == native_label)
        bound, result = transport['center'], transport['result']
        reference = read(ROOT / 'research/S013/assets/runs/EX043_20261011/account_references.json')[native_label]
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    formal = read(ref.resolve(ROOT))
    validate_evaluation_evidence(formal)
    assert serialize_evaluation_evidence(bound, result) == formal
    return bound, result, ref


def old_coupled_oracle():
    path = ROOT / 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    spec = importlib.util.spec_from_file_location('s013_ex055_old_coupled', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit_direction


def old_raw_body_oracle():
    path = ROOT / 'research/S013/experiments/EX054_20261011/src/raw_body_oracle.py'
    spec = importlib.util.spec_from_file_location('s013_ex055_old_raw_body', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit_raw_body


def main():
    plan = source_check()
    assert not (RUNS / 'analysis.json').exists()
    assert read(RUNS / 'precheck.json')['status'] == 'PASS'
    ledger.verify_account = verify_account
    ctx, rows, reuse, accounts = context(1), {}, {}, {}
    for cfg in plan['controls'] + plan['diagnostic_controls'] + plan['configurations']:
        label = cfg['label']
        if cfg['reused']:
            bound, result, ref = reused_account(cfg)
            assert ref.to_dict() == plan['control_references'][label]
            reuse[label] = {'reference': ref.to_dict(), 'request_hash': result.request_hash,
                'result_hash': result.result_hash, 'serialized_native': 'EXACT_EQUAL'}
        else:
            bound, result = cache_read(CACHE / (label + '.pkl.gz'))
        assert len(result.runs) == 1 and bound.strategy.candidate_id == cfg['candidate_id']
        assert canonical_sha256(bound.strategy.payload) == canonical_sha256(cfg['payload'])
        identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
        assert identity.content_sha256 == cfg['content_sha256'] == result.runs[0].identity.content_sha256
        assert identity.source_sha256 == cfg['payload']['runtime']['source_sha256']
        row, frame = summarize(bound, result, cfg, ledger)
        assert set(row['gates']) == GATES and row['qualified'] == all(row['gates'].values())
        assert row['account_audit']['known_low_error_potential_orders'] == 0
        if label != 'B0-TIME':
            auditor = audit_raw_recovery if label == 'N0' else old_raw_body_oracle() if label == 'B0-RAW-BODY' else old_coupled_oracle()
            row['direction_audit'] = auditor(ctx, bound, frame, cfg['payload']['parameters'])
            assert row['direction_audit']['status'] == 'PASS'
        row.update(label=label, mechanism=cfg['mechanism'], reused=cfg['reused'])
        rows[label], accounts[label] = row, (bound, result)
        print({'audited_center': label, 'qualified': row['qualified']}, flush=True)
    assert rows['B0-TIME']['qualified'] and rows['B0-COUPLED']['qualified']
    benchmark = accounts['B0-TIME'][1].runs[0].buyhold.execution
    for _, result in accounts.values():
        for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            pd.testing.assert_frame_equal(getattr(benchmark, field), getattr(result.runs[0].buyhold.execution, field), check_exact=True)
    old, new = accounts['B0-TIME'][1].runs[0], accounts['N0'][1].runs[0]
    assert accounts['N0'][0].strategy.payload['parameters']['confirmation']['lookback'] == 120
    # Only conditional bear TIME BELOW reentry direction changes; original causal numerical features exact.
    feature_fields = ('signal_date', 'valid_session', 'close', 'acf1', 'regime', 'regime_momentum',
        'momentum20', 'bull_range_position', 'bear_range_position', 'confirmation_score', 'confirmation_acf',
        'confirmation_turnover', 'confirmation_volume')
    pd.testing.assert_frame_equal(old.execution.decisions.loc[:, feature_fields], new.execution.decisions.loc[:, feature_fields], check_exact=True)
    old_frame, new_frame = old.execution.decisions, new.execution.decisions
    assert set(old_frame.columns).issubset(new_frame.columns)
    assert not {'bear_acf_baseline', 'bear_acf_centered', 'previous_regime', 'previous_regime_momentum'}.intersection(new_frame.columns)
    target_changed = old_frame.target_position.ne(new_frame.target_position)
    reason_changed = old_frame.signal_reason.ne(new_frame.signal_reason)
    path_contrast = {'signal_days': len(old_frame), 'target_different_days': int(target_changed.sum()),
        'reason_different_days': int(reason_changed.sum()),
        'first_target_divergence': (None if not target_changed.any() else str(old_frame.loc[target_changed, 'signal_date'].iloc[0])),
        'changed_signal_days': [str(x) for x in old_frame.loc[target_changed | reason_changed, 'signal_date']],
        'basis': 'Two distinct authenticated complete native policies; inherited cash and decisions propagate separately. No trade deletion or counterfactual cash replay.'}
    assert not SOURCE_CALLS
    write(RUNS / 'analysis.json', ledger.plain({'status': 'PASS', 'rows': rows, 'control_reuse': reuse,
        'paired_comparisons': [paired(rows['B0-TIME'], rows['N0'], 'Local RAW ACF recovery versus original'),
            paired(rows['B0-RAW-BODY'], rows['N0'], 'Local ACF eligibility recovery versus BODY entry restriction'),
            paired(rows['B0-COUPLED'], rows['N0'], 'Historical coupled MEAN CLOSE multiple-change countercontrol')],
        'background_matrix': {'status': 'PASS', 'rows': {'original': 'B0-TIME', 'historical-coupled': 'B0-COUPLED', 'raw-body-gate': 'B0-RAW-BODY', 'raw-local-acf-recovery': 'N0'}, 'basis': 'Four authenticated complete native policies, descriptive differences only'},
        'center_expectation': {'status': 'PASS', 'causal_input_fields_exact': list(feature_fields),
                              'path_contrast': path_contrast,
                              'distinct_identity': 'Own new public full evaluation; prior identity not relabeled'},
        'new_business_configurations': 1, 'new_account_evaluations': 2, 'historical_controls_reused': 3,
        'qualification_policy': 'Exactly original4gates; no diagnostic veto', 'provider_calls': SOURCE_CALLS}))
    print({'center_analysis': 'PASS', 'rows': {label: {key: row[key] for key in
        ('net_cagr', 'drawdown', 'closed_trades', 'qualified', 'gates')} for label, row in rows.items()}}, flush=True)


if __name__ == '__main__':
    main()
