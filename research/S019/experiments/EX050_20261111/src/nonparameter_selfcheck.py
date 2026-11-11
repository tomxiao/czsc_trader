"""Run the approved EX050 non-parameter checks on six published accounts."""

from dataclasses import replace
from hashlib import sha256
from math import isclose
from time import perf_counter
from uuid import uuid4

import assess as ex
import numpy as np


def checked_archive():
    receipt = ex.read(ex.OUT / 'statistics_verification.json')
    if receipt['status'] != 'PASSED':
        raise ValueError('existing statistics have no successful verification receipt')
    artifacts = {}
    for name in ('statistics_temporal.json', 'statistics_bootstrap.json',
                 'statistics_summary.json', 'temporal_s018_reference.json'):
        path = ex.OUT / name
        if sha256(path.read_bytes()).hexdigest() != receipt['artifacts'][name]:
            raise ValueError('statistics artifact differs from the verified receipt: ' + name)
        artifacts[name] = ex.read(path)
    return receipt, artifacts


def main():
    started = perf_counter()
    output = ex.OUT / 'nonparameter_selfcheck.json'
    if output.exists():
        raise FileExistsError('preserve the existing partial self-check record')
    source_rows = ex.read(ex.WORK / 'protocols/centers.json')
    expected = tuple(ex.read(ex.WORK / 'protocols/scope.json')['selected'])
    if tuple(row['id'] for row in source_rows) != expected:
        raise ValueError('center evidence differs from the approved candidate set')
    receipt, archive = checked_archive()
    facts, centers, source_refs = [], [], {}
    for row in source_rows:
        references = {}
        for label, key, fee in (('STANDARD', 'center_account', .001), ('STRESS', 'stress_account', .002)):
            value, header, ref = ex.fact(row[key])
            if (value.candidate.candidate_id != 'S019-' + row['id']
                    or value.candidate.content_sha256 != row['content_hash']
                    or value.scenario_id != label or value.scenario_context.one_way_cost != fee
                    or value.parent is not None or header['request']['window_id'] != 'FULL'):
                raise ValueError('published account has a different candidate or evaluation contract')
            facts.append(value)
            references[label] = ref.to_dict()
            if label == 'STANDARD':
                centers.append(value.candidate)
        source_refs[row['id']] = references
    design = ex.m.ParameterNeighborhoodDesign.from_dict(ex.read(ex.WORK / f'protocols/{expected[0]}_design.json'))
    protocol = ex.m.NeighborhoodSelfCheckProtocol('s019-ex050-nonparameter-selfcheck-v1',
        'FULL', 'STANDARD', 'STRESS', 252, 21, ex.m.QuantileMethod.LINEAR,
        1, 10000, 21, 20261110, 1e-8, design.protocol, frequency_min_closed_cycles=3)
    request = ex.m.CandidateAssessmentRequest(tuple(centers), protocol, (), tuple(facts))
    panel = ex.assess_candidates(request)
    full_targets = ex.target_set()
    deferred, = (item for item in full_targets.requirements if type(item) is ex.m.ParameterNeighborhoodTarget)
    targets = replace(full_targets, requirements=tuple(item for item in full_targets.requirements if item is not deferred))
    comparison = ex.compare_candidates(ex.m.CandidateComparisonRequest(tuple(centers), targets, panel,
                                                                           ex.native_acceptance_policy()))

    bootstrap = archive['statistics_bootstrap.json']['comparisons']
    temporal = {row['candidate_id']: row for row in archive['statistics_temporal.json']['candidates']}
    summary = archive['statistics_summary.json']
    reference = {row['candidate_id']: row for row in archive['temporal_s018_reference.json']['candidates']}
    checked = {row.candidate: row for row in comparison.rows}
    results = []
    for row in panel.rows:
        cid = row.candidate.candidate_id.removeprefix('S019-')
        metrics = {item.metric.value: item.value for item in row.diagnostics}
        interval, = (item for item in bootstrap if item['champion_id'] == cid and item['comparator_id'] == 'MU_BUY_HOLD')
        old_windows = temporal[cid]['rolling']
        if len(old_windows) != 46 or len(reference[cid]['rolling']) != 46:
            raise ValueError('archived rolling windows differ from the approved protocol')
        if (row.uncertainty.lower_95, row.uncertainty.upper_95) != (interval['cagr']['lower_95'], interval['cagr']['upper_95']):
            raise ValueError('native confidence interval differs from the archived bootstrap')
        if not isclose(metrics['PROFIT_CONCENTRATION'], temporal[cid]['concentration'], rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError('native concentration differs from the archived diagnosis')
        if not isclose(metrics['ROLLING_EXCESS_Q10'], float(np.quantile([item['nar_excess'] for item in old_windows], .1)),
                       rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError('native rolling excess differs from the archived diagnosis')
        checks = checked[row.candidate].target_checks
        failed = [item.target_id for item in checks if item.status is ex.m.TargetCheckStatus.FAILED]
        unresolved = [item.target_id for item in checks if item.status is ex.m.TargetCheckStatus.INDETERMINATE]
        results.append({'candidate_id': cid, 'sources': source_refs[cid],
            'decision': 'EXCLUDE' if failed else 'PENDING_EVIDENCE' if unresolved else 'KEEP_FOR_PARAMETER_CHECK',
            'failed_targets': failed, 'unresolved_targets': unresolved, 'target_checks': [item.to_dict() for item in checks],
            'standard': {'nar': metrics['NET_ANNUAL_RETURN'],
                         'calmar': metrics['NET_ANNUAL_RETURN'] / metrics['DRAWDOWN_MAGNITUDE'],
                         'mdd': metrics['DRAWDOWN_MAGNITUDE'], 'frequency_median': metrics['FREQUENCY_MEDIAN'],
                         'frequency_coverage': row.frequency_coverage.to_dict()},
            'pressure': {**row.stress_performance.to_dict(),
                         'calmar': row.stress_performance.annual_return / row.stress_performance.drawdown},
            'rolling': {'windows': len(old_windows), 'nar_below_buy_hold': sum(item['nar_excess'] < 0 for item in old_windows),
                        'calmar_below_buy_hold': sum(item['calmar_excess'] < 0 for item in old_windows),
                        'nar_excess_q10': metrics['ROLLING_EXCESS_Q10']},
            'concentration': metrics['PROFIT_CONCENTRATION'], 'paired_intervals': interval,
            'native_archive_crosscheck': 'PASS'})
    report = {'status': 'NONPARAMETER_SELFCHECK_COMPLETE', 'full_stage_four_status': 'PENDING_PARAMETER_SENSITIVITY',
        'deferred_target': deferred.target_id, 'checked_target_count': len(targets.requirements),
        'account_replays': 0, 'neighbor_accounts_read': 0, 'existing_account_evidence': len(facts),
        'seconds': perf_counter() - started, 'protocol': protocol.to_dict(),
        'original_targets_sha256': full_targets.sha256, 'checked_targets_sha256': targets.sha256,
        'native_panel_sha256': panel.sha256, 'native_comparison_sha256': comparison.sha256,
        'archive_sha256': {name: receipt['artifacts'][name] for name in archive}, 'candidates': results,
        'family_selection_history': summary['selection_summary'],
        'family_actual_adaptive_selection_bias': summary['actual_nar_gated_adaptive_selection_bias']}
    temp = ex.SCRATCH / f'nonparameter-selfcheck-{uuid4().hex}.json'
    ex.save(temp, report)
    temp.rename(output)
    for result in results:
        print(result['candidate_id'], result['decision'], result['pressure']['calmar'], flush=True)


if __name__ == '__main__':
    main()
