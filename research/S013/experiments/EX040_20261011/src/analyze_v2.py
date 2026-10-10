"""Audit four complete direction accounts and two immutable native controls."""
from hashlib import sha256
import json
from statistics import mean

import pandas as pd
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
import ledger_reference as ledger
from account_reference import verify_account
from analysis_reference import summarize, paired
from common import ROOT, PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, read, write, cache_read, context
from direction_oracle_v2 import audit_direction
from technical_validation import technical_check


GATES = {'return', 'annual_drawdown', 'frequency', 'negative_buyhold_year_profit'}


def reused_account(config):
    """Preserve the public original reference; trace cache reuse without cloning."""
    experiment, label = config['reuse_from'], config['reuse_label']
    reference = EvidenceRef.from_dict(read(ROOT / f'research/S013/assets/runs/{experiment}/account_references.json')[label])
    seen = set()
    while True:
        identity = (experiment, label)
        assert identity not in seen, 'Cyclic reuse chain'
        seen.add(identity)
        path = ROOT / '.tmp' / ('s013-mechanism-' + experiment[:5]) / (label + '.pkl.gz')
        if path.exists():
            bound, result = cache_read(path)
            break
        previous = read(ROOT / f'research/S013/experiments/{experiment}/protocols/plan.json')
        parent = next(row for row in previous['controls'] if row['label'] == label)
        assert parent['candidate_id'] == config['candidate_id'] and parent['content_sha256'] == config['content_sha256']
        experiment, label = parent['reuse_from'], parent['reuse_label']
    assert reference.experiment.strategy_id == 'S013'
    location = reference.resolve(ROOT).resolve()
    assert location.is_relative_to((ROOT / 'research/S013').resolve())
    assert sha256(location.read_bytes()).hexdigest() == reference.sha256
    formal = read(location)
    validate_evaluation_evidence(formal)
    assert serialize_evaluation_evidence(bound, result) == formal, 'Full native reused account must remain exact'
    return bound, result, reference


def holding_diagnostic(row):
    closed = [cycle for cycle in row['paths']['cycles'] if cycle['status'] == 'CLOSED']
    return {'mean_closed_sessions': mean(cycle['holding_sessions'] for cycle in closed) if closed else None,
            'max_closed_sessions': max((cycle['holding_sessions'] for cycle in closed), default=None),
            'bear_closed_cycles': sum(cycle['entry_route'] == 'bear' for cycle in closed),
            'bear_time_exits': sum(cycle['entry_route'] == 'bear' and cycle['exit_reason'] == 'time' for cycle in closed),
            'open_tail_cycles': [cycle for cycle in row['paths']['cycles'] if cycle['status'] != 'CLOSED']}


def main():
    technical_check()
    matrix = read(RUNS / 'matrix.json')
    assert matrix['status'] == 'COMPLETE'
    assert len(matrix['rows']) == 4 and all(row['status'] == 'SUCCEEDED' for row in matrix['rows'])
    assert matrix['new_account_evaluations'] == 5 and matrix['new_business_configurations'] == 4
    assert not matrix['provider_calls'] and not SOURCE_CALLS
    plan = read(PROTOCOLS / 'plan.json')
    assert [cfg['label'] for cfg in plan['controls']] == ['B0-TIME', 'B0-MEAN']
    assert [cfg['label'] for cfg in plan['configurations']] == ['N0', 'N1', 'N2', 'N3']
    ledger.verify_account = verify_account
    ctx = context(1)
    rows, reuse, bound_results = {}, {}, {}
    for config in plan['controls'] + plan['configurations']:
        label = config['label']
        if config['reused']:
            bound, result, reference = reused_account(config)
            reuse[label] = {'reference': reference.to_dict(), 'comparison': 'EXACT_EQUAL entire serialized native account',
                            'request_hash': result.request_hash, 'result_hash': result.result_hash}
        else:
            bound, result = cache_read(CACHE / (label + '.pkl.gz'))
            matrix_row = next(row for row in matrix['rows'] if row['label'] == label)
            assert result.request_hash == matrix_row['request_hash'] and result.result_hash == matrix_row['result_hash']
        assert len(result.runs) == 1 and bound.strategy.candidate_id == config['candidate_id']
        assert result.runs[0].identity.content_sha256 == config['content_sha256']
        assert json.loads(json.dumps(dict(bound.strategy.payload), default=dict)) == config['payload']
        identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
        assert identity.content_sha256 == config['content_sha256']
        assert identity.source_sha256 == config['payload']['runtime']['source_sha256']
        row, history = summarize(bound, result, config, ledger)
        assert set(row['gates']) == GATES and row['qualified'] == all(row['gates'].values())
        if not config['reused']:
            row['direction_audit'] = audit_direction(ctx, bound, history, config['payload']['parameters'])
            assert row['direction_audit']['status'] == 'PASS'
            assert row['direction_audit']['signal_days'] == len(history)
        row.update(label=label, mechanism=config['mechanism'], reused=config['reused'], key=config.get('key'))
        assert row['account_audit']['known_low_error_potential_orders'] == 0
        row['holding_diagnostic'] = holding_diagnostic(row)
        rows[label], bound_results[label] = row, (bound, result)
    assert rows['B0-TIME']['candidate_id'] == 'C2132' and rows['B0-TIME']['qualified']
    benchmark = bound_results['B0-TIME'][1].runs[0].buyhold.execution
    for _, result in bound_results.values():
        own = result.runs[0].buyhold.execution
        for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            pd.testing.assert_frame_equal(getattr(benchmark, field), getattr(own, field), check_exact=True)
    comparisons = [paired(rows[parent], rows[label], label + ' versus original complete ' + parent)
                   for label, parent in (('N0', 'B0-TIME'), ('N1', 'B0-TIME'), ('N2', 'B0-MEAN'), ('N3', 'B0-MEAN'))]
    comparisons += [paired(rows[first], rows[second], label) for first, second, label in (
        ('N0', 'N1', 'RAW CLOSE versus BODY'), ('N2', 'N3', 'MEAN CLOSE versus BODY'),
        ('N0', 'N2', 'MEAN increment with CLOSE direction'), ('N1', 'N3', 'MEAN increment with BODY direction'),
        ('B0-TIME', 'B0-MEAN', 'Original RAW versus MEAN background'))]
    cells = [{**cell, **{key: rows[cell['label']][key] for key in
                        ('net_cagr', 'drawdown', 'closed_trades', 'qualified', 'gates')}} for cell in plan['cells']]
    assert not SOURCE_CALLS
    write(RUNS / 'analysis.json', ledger.plain({'status': 'PASS', 'rows': rows, 'cells': cells,
        'paired_comparisons': comparisons, 'control_reuse': reuse, 'benchmark_ledgers': 'EXACT_EQUAL all 6 accounts, 5 ledgers',
        'new_business_configurations': 4, 'new_account_evaluations': 5, 'historical_controls_reused': 2,
        'data_scope': 'Existing repeatedly seen S013 development pool; no independent validation.',
        'qualification_policy': 'Exactly four original economic gates; direction/state diagnostics add no veto or qualification.',
        'comparison_scope': 'Differences between complete native accounts with actual holdings/orders/fills/fees/cash. No deleted historical trade PnL or one-step predicate treated as mechanism profit.',
        'provider_calls': matrix['provider_calls']}))
    print({'analysis': 'PASS', 'summary': [{key: row[key] for key in
        ('label', 'net_cagr', 'drawdown', 'closed_trades', 'qualified', 'gates')} for row in rows.values()]}, flush=True)


if __name__ == '__main__':
    main()
