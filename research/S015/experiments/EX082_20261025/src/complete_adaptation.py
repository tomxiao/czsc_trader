"""Continue the two baseline accounts with authenticated identity-aware signals."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

import adapt as a


def inspect_pair(old, reference):
    left_data = a.read(old.baseline.evidence.resolve(a.ROOT))
    right_data = a.read(reference.resolve(a.ROOT))
    a.validate_evaluation_evidence(left_data)
    a.validate_evaluation_evidence(right_data)
    left, = left_data['runs']
    right, = right_data['runs']
    assert left['identity']['candidate'] == a.PARENT.to_dict()
    assert left['identity']['content_sha256'] == a.PARENT_CONTENT
    assert right['identity']['candidate'] == a.KEY.to_dict()
    assert right['identity']['content_sha256'] == a.read(a.OUT / 'identity.json')['content_sha256']
    comparison = a.compare_ledgers(a.LedgerComparisonRequest(a.ReplayEvidence.from_dict(left['replay_evidence']),
        a.ReplayEvidence.from_dict(right['replay_evidence']), a.LedgerComparisonMode.ECONOMIC, 0.0))
    assert comparison.status is a.LedgerComparisonStatus.EQUIVALENT and comparison.economic_sha256
    assert left['signals']['schema'] == right['signals']['schema']
    assert left['signal_dtypes'] == right['signal_dtypes'] and left['signal_window'] == right['signal_window']
    assert left['buyhold'] == right['buyhold']
    mapping = []
    for x, y in zip(left['signals']['data'], right['signals']['data'], strict=True):
        assert set(x) == set(y)
        assert {k: v for k, v in x.items() if k != 'decision_id'} == {k: v for k, v in y.items() if k != 'decision_id'}
        # Independent implementation of the pre-existing identity formula in srt_bridge.py.
        for candidate, row in ((a.PARENT, x), (a.KEY, y)):
            target = row['target_position']
            token = int(target) if target in (0, 1) else target
            raw = f"{candidate.strategy_id}-{candidate.candidate_id}|{row['signal_date'][:10]}|{token}".encode()
            assert row['decision_id'] == 'DEC-' + sha256(raw).hexdigest()[:20].upper()
        mapping.append({'signal_date': x['signal_date'], 'old': x['decision_id'], 'new': y['decision_id']})
    assert len(mapping) == 434
    assert len({x['old'] for x in mapping}) == len({x['new'] for x in mapping}) == 434
    return {'scenario_id': old.coordinate.scenario_id, 'evidence': reference.to_dict(),
        'old_baseline': old.baseline.to_dict(), 'comparison': comparison.to_dict(),
        'signal_business_fields_equal': True, 'signal_schema_dtypes_window_equal': True, 'buyhold_equal': True,
        'decision_ids': {'count': 434, 'formula_checked_both_sides': True, 'mapping': mapping},
        'identity_difference': 'Candidate-specific decision IDs change by their documented hash formula; every other signal field is byte-value equal.'}


def prepare():
    assert not (a.OUT / 'continuation_prepared.json').exists()
    prior = a.read(a.OUT / 'comparison_standard.json')
    assert prior['comparison']['status'] == 'EQUIVALENT' and not prior['signals_equal'] and prior['buyhold_equal']
    correction = {'status': 'SIGNAL_COMPARISON_ASSERTION_CORRECTED',
        'original_assertion': 'Raw full signal objects equal across distinct candidate identities',
        'original_observation': 'Standard account economic comparison EQUIVALENT with no differences; raw signals differ solely in all434 decision_id values.',
        'cause': 'decision_id hashes candidate reference, signal date and target. Identity change necessarily changes it.',
        'scope': 'Preserve first failure and account. Compare all other signal fields exactly and independently authenticate both sets of decision IDs. No economic tolerance or strategy changes.',
        'basis': 'src/czsc_trader/backtesting/srt_bridge.py:77-81',
        'new_accounts': 'Reuse the published standard account; run only the remaining fee_x2 account.',
        'not_a_search': True}
    a.save(a.OUT / 'comparison_attempt1.json', correction)
    protocol = {'method': 'Signal fields exact except identity-derived decision_id; both IDs must independently match documented hash and form a 434-row bijection.',
        'economic_comparison': 'Public ECONOMIC, zero tolerance, all economic ledger facts and metrics.',
        'schema_dtypes_window_buyhold': 'Exact equality', 'stop': 'Any other difference fails; no more exclusions.',
        'old_baseline': prior['old_baseline'], 'new_standard': prior['evidence']}
    path = a.HOME / 'protocols/signal_comparison.json'
    a.save(path, protocol)
    ctx = a.context()
    files = [Path(__file__), path, a.OUT / 'comparison_attempt1.json', a.OUT / 'comparison_standard.json',
             a.ROOT / 'src/czsc_trader/backtesting/srt_bridge.py']
    a.save(a.OUT / 'continuation_prepared.json', {
        'references': {p.relative_to(a.ROOT).as_posix(): a.material(ctx, p).to_dict() for p in files},
        'source_hashes': {p.relative_to(a.ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in files}})
    print('IDENTITY_AWARE_COMPARISON_PREPARED', flush=True)


def run():
    assert not (a.OUT / 'results.json').exists()
    for filename in ('prepared.json', 'continuation_prepared.json'):
        for path, digest in a.read(a.OUT / filename)['source_hashes'].items():
            assert sha256((a.ROOT / path).read_bytes()).hexdigest() == digest, path
    snapshot = a.EvidenceRef.from_dict(a.read(a.OUT / 'prepared.json')['requests'])
    requests = a.cloudpickle.loads(snapshot.resolve(a.ROOT).read_bytes())
    ctx, rows = a.context(), []
    for request, old in zip(requests, a.old_replays(), strict=True):
        if old.coordinate.scenario_id == 'standard':
            reference = a.EvidenceRef.from_dict(a.read(a.OUT / 'comparison_standard.json')['evidence'])
        else:
            result = ctx.evaluation.evaluate(request)
            reference = a.publish_evidence(ctx, a.EvaluationEvidenceWrite(a.EX, 'fee_x2', request, result))
            a.save(a.OUT / 'fee_x2_evidence.json', reference.to_dict())
        row = inspect_pair(old, reference)
        rows.append(row)
        a.save(a.OUT / ('equivalence_' + old.coordinate.scenario_id + '.json'), row)
        print('EXACT_ECONOMIC_AND_SIGNAL_PASS', old.coordinate.scenario_id, flush=True)
    a.save(a.OUT / 'results.json', {'status': 'PASS', 'rows': rows, 'new_baseline_accounts': 2,
        'reused_completed_standard_accounts': 1, 'new_search_trials': 0, 'original_failed_assertion_preserved': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    {'prepare': prepare, 'run': run}[parser.parse_args().mode]()
