"""Authorized fixed-candidate coverage; no strategy search or parameter edits."""
# ruff: noqa: E402
import argparse
from datetime import date
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import zipfile
from collections.abc import Mapping
from dataclasses import asdict

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import numpy as np
import pandas as pd
from czsc_trader.application import (
    RepositoryContext, create_research_context, load_candidate, publish_evidence,
    open_research_execution, publish_evidence_many,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
    EvaluationEvidenceWrite, ExecutionCheckpointRequest, CheckpointMode,
)
from strategy_manager import CandidateKey, canonical_sha256, StrategyRegistry

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX013_20261023')
EROOT = EX.resolve(ROOT)


def read(path):
    return json.loads(path.read_bytes())


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def candidate_hash(value):
    return canonical_sha256(plain(value.payload))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8', newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
                                   resources=ExecutionResources(8, 1, 13))


def material(ctx, name, path):
    return publish_evidence(ctx, MaterialEvidenceWrite(EX, name, path.read_bytes(),
        {'json': 'application/json', 'py': 'text/x-python', 'csv': 'text/csv'}[path.suffix[1:]], path.suffix[1:]))


def authenticated_delivery(stage, revision):
    receipt = read(ROOT / f'research/S015/deliveries/{stage}/{revision}/receipt.json')
    path = ROOT / f'research/S015/assets/deliveries/{stage}/{revision}/delivery.json'
    expected = next(x['sha256'] for x in receipt['files'] if x['path'] == 'delivery.json')
    assert sha256(path.read_bytes()).hexdigest() == expected
    return read(path), receipt['reference']


def candidate(cid):
    return load_candidate(RepositoryContext.discover(ROOT), CandidateKey('S015', cid))


def prepare():
    assert not (EROOT / 'protocols/fixed_set.json').exists()
    old, oldref = authenticated_delivery('ASSESSMENT', 1)
    mandate, mandref = authenticated_delivery('MANDATE', 3)
    checks_ref = EvidenceRef.from_dict(next(x for x in old['content']['evidence'] if x['name'] == 'final_checks'))
    checks = read(checks_ref.resolve(ROOT))
    ids = [r['candidate_id'] for r in checks['rows'] if r['aggregate_acceptance'] == 'PASSED']
    assert len(ids) == len(set(ids)) == 86 and 'C0031' in ids
    identities = {cid: candidate_hash(candidate(cid)) for cid in ids}
    accepted = old['content']['payload']['comparison']['rows']
    original = {r['candidate']['candidate_id'].removeprefix('S015-'): r['candidate']['content_sha256']
                for r in accepted if r['acceptance_status'] == 'PASSED'}
    registered = {cid: StrategyRegistry(ROOT / 'research/registrations').get_candidate_registration(
        CandidateKey('S015', cid)).content_sha256 for cid in ids}
    assert registered == original
    gate_path = ROOT / 'research/S015/experiments/EX009_20261022/protocols/comparative_gate.json'
    gate = read(gate_path)
    gate_refs = [EvidenceRef.from_dict(x) for x in mandate['content']['evidence'] if x['sha256'] == sha256(gate_path.read_bytes()).hexdigest()]
    assert len(gate_refs) == 1
    gate_refs[0].resolve(ROOT)
    archives = read(ROOT / 'research/S015/experiments/EX008_20261022/others/account_archives.json')
    for ref in archives.values():
        EvidenceRef.from_dict(ref).resolve(ROOT)
    protocol = {
        'authorization': '用户同意并要求自主执行：固定原86个全通过候选，复用有效434日证据，补齐415日独立账户，双窗口AND。',
        'stage': 'ASSESSMENT_COVERAGE', 'source_assessment': oldref, 'source_mandate': mandref,
        'source_checks': checks_ref.to_dict(), 'comparative_gate': gate_refs[0].to_dict(),
        'candidates': identities, 'registered_content_hashes': registered,
        'count': 86, 'original_window_sessions': 434,
        'comparison_start': '2025-02-06', 'comparison_end': '2026-10-21', 'comparison_sessions': 415,
        'initial_cash': 100000, 'initial_quantity': 0, 'one_way_cost': .001,
        'execution': 'DAILY_RANGE_V3', 'price_basis': 'HFQ_RESEARCH', 'force_end_liquidation': False,
        'gate': gate, 'archive_reuse': archives,
        'budget': {'new_fixed_center_accounts': 85, 'conditional_max_if_C0031_not_reusable': 86,
                   'precheck_repeated_C0031': 2, 'max_workers': 8, 'native_threads': 1},
        'precheck': 'C0031 serial versus batch five ledgers and hash; archived C0031 account/fees/path equivalence before reuse. Repeats counted separately.',
        'scope': 'No candidate creation, tuning, new data, changed dates or extra economic gates. All 86 identities retained even if behavior duplicates.',
        'ranking': 'Only joint-pass candidates eligible; preserve original434 declared ranking policy and original ranking evidence. No new weighted score.',
        'limitations': ['Development history already observed; not independent validation.',
                       'Default runtime clock20:31; historical17:30 publication/revision chain not certified; inherited limitation.',
                       'New415 strict comparison is RSCH explicit gate; technical report validation is not economic acceptance.'],
    }
    save(EROOT / 'protocols/fixed_set.json', protocol)
    ctx = context()
    ref = material(ctx, 'fixed_set_protocol', EROOT / 'protocols/fixed_set.json')
    save(EROOT / 'others/protocol_ref.json', ref.to_dict())
    print({'protocol': 'FROZEN', 'candidates': len(ids)}, flush=True)


def request(ctx, cid):
    protocol = read(EROOT / 'protocols/fixed_set.json')
    c = candidate(cid)
    assert candidate_hash(c) == protocol['candidates'][cid]
    req = EvaluationRequest(ROOT, EX.experiment_id, c, {
        'candidate_id': c.reference_id, 'source_files': list(c.payload['runtime']['source_files']),
        'implementation_sha256': c.payload['runtime']['source_sha256']}, '159326.SZ', 'etf',
        (EvaluationWindow('s011_common', date(2025, 2, 6), date(2026, 10, 21)),), date(2026, 10, 21),
        100000., (EvaluationCost('standard', .001),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .001, .1, 1000000)))
    return ctx.evaluation.prepare(req)


def archived(label):
    ref = EvidenceRef.from_dict(read(EROOT / 'protocols/fixed_set.json')['archive_reuse'][label])
    with zipfile.ZipFile(ref.resolve(ROOT)) as archive:
        result = {}
        for name in ('account_daily', 'decisions', 'orders', 'fills', 'trades'):
            member = next(x for x in archive.namelist() if x.endswith('/' + name + '.csv') or x == name + '.csv')
            result[name] = pd.read_csv(io.BytesIO(archive.read(member)), float_precision='round_trip')
        manifest = next(x for x in archive.namelist() if x.endswith('manifest.json'))
        result['manifest'] = json.loads(archive.read(manifest))
        return result


def stats(execution):
    a, f, t = execution.account_daily, execution.fills, execution.trades
    assert len(a) == 415 and str(a.date.iloc[0])[:10] == '2025-02-06' and str(a.date.iloc[-1])[:10] == '2026-10-21'
    assert float(a.cash_before.iloc[0]) == 100000 and int(a.quantity_before.iloc[0]) == 0
    np.testing.assert_allclose(f.fees.astype(float), f.quantity.astype(float) * f.price.astype(float) * .001, rtol=1e-12, atol=1e-8)
    eq = np.r_[100000., a.equity.to_numpy(dtype=float)]
    net = float(eq[-1] / 100000 - 1)
    dd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    gate = read(EROOT / 'protocols/fixed_set.json')['gate']['conditions']
    ret_pass, dd_pass = net > gate[0]['baseline_value'], dd < gate[1]['baseline_value']
    return {'net_return': net, 'maximum_drawdown': dd, 'annualized_return': (1 + net) ** (252 / 415) - 1,
            'fees': float(f.fees.sum()), 'closed_trades': int(t.status.eq('CLOSED').sum()),
            'final_equity': float(eq[-1]), 'terminal_quantity': int(a.quantity.iloc[-1]),
            'return_pass': ret_pass, 'drawdown_pass': dd_pass, 'joint_pass': ret_pass and dd_pass}


def precheck():
    assert not (EROOT / 'others/precheck.json').exists()
    ctx = context()
    req = request(ctx, 'C0031')
    serial = ctx.evaluation.evaluate(req)
    print({'serial': 'COMPLETE', 'stats': stats(serial.runs[0].execution)}, flush=True)
    with open_research_execution(ctx, experiment=EX, checkpoint=ExecutionCheckpointRequest('precheck', CheckpointMode.CREATE)) as session:
        outputs = ctx.evaluation.evaluate_many((req,), execution=session)
        assert outputs[0].status.value == 'SUCCEEDED', outputs[0].error
        result = outputs[0].result
        for name in ('account_daily', 'decisions', 'orders', 'fills', 'trades'):
            pd.testing.assert_frame_equal(getattr(serial.runs[0].execution, name), getattr(result.runs[0].execution, name))
        assert serial.result_hash == result.result_hash
        pub = publish_evidence_many(ctx, (EvaluationEvidenceWrite(EX, 'C0031_precheck_repeat', req, result),), execution=session)[0]
        assert pub.status.value == 'PUBLISHED', pub.error
    old = archived('C0031')
    new = result.runs[0].execution
    checks = {}
    for name, columns in {'account_daily': ['cash_before', 'quantity_before', 'cash', 'quantity', 'equity', 'close', 'target_position'],
                          'fills': ['quantity', 'price', 'fees']}.items():
        actual, expected = getattr(new, name), old[name]
        assert len(actual) == len(expected)
        for column in columns:
            np.testing.assert_allclose(actual[column].astype(float), expected[column].astype(float), rtol=1e-12, atol=1e-8)
        checks[name] = {'rows': len(actual), 'numeric_columns': columns}
    assert list(new.account_daily.date.astype(str).str[:10]) == list(old['account_daily'].date.astype(str).str[:10])
    evidence = {'status': 'PASS', 'serial_batch_all_five_ledgers_equal': True, 'serial_batch_result_hash_equal': True,
        'archive_equivalence': checks, 'physical_evaluations': 2, 'new_candidate_identities': 0,
        'C0031_reusable': True, 'repeat_reference': pub.reference.to_dict(), 'stats': stats(new),
        'input_bindings': {k: v.to_dict() for k, v in req.input_bindings.items()},
        'request_hash': result.request_hash, 'result_hash': result.result_hash,
        'run_identity': result.runs[0].identity.to_dict(), 'archive_manifest': old['manifest']}
    save(EROOT / 'others/precheck.json', evidence)
    print({'precheck': 'PASS', 'C0031_reusable': True}, flush=True)


def parallel_precheck():
    """Explicit recovery: the original one-item batch used the serial fast path."""
    assert not (EROOT / 'others/parallel_precheck.json').exists()
    ctx = context()
    protocol = read(EROOT / 'protocols/fixed_set.json')
    first = next(c for c in protocol['candidates'] if c != 'C0031')
    reqs = [request(ctx, c) for c in ('C0031', first)]
    old = read(EROOT / 'others/precheck.json')
    with open_research_execution(ctx, experiment=EX,
            checkpoint=ExecutionCheckpointRequest('actual_parallel_precheck', CheckpointMode.CREATE)) as session:
        outcomes = ctx.evaluation.evaluate_many(tuple(reqs), execution=session)
        assert all(o.status.value == 'SUCCEEDED' for o in outcomes), [(o.status.value, str(o.error)) for o in outcomes]
        assert outcomes[0].result.result_hash == old['result_hash']
        previous = read(EvidenceRef.from_dict(old['repeat_reference']).resolve(ROOT))
        for name in ('account_daily', 'decisions', 'orders', 'fills', 'trades'):
            current = getattr(outcomes[0].result.runs[0].execution, name)
            previous_table = previous['runs'][0]['ledgers'][name]
            expected = pd.DataFrame({k: pd.Series([r[k] for r in previous_table['data']], dtype=v)
                                     for k, v in previous_table['dtypes'].items()})
            expected = expected[[f['name'] for f in previous_table['schema']['fields']]]
            pd.testing.assert_frame_equal(current, expected)
        pubs = publish_evidence_many(ctx, tuple(EvaluationEvidenceWrite(EX, c + '_actual_parallel_precheck', q, o.result)
            for c, q, o in zip(('C0031', first), reqs, outcomes, strict=True)), execution=session)
        assert all(p.status.value == 'PUBLISHED' for p in pubs)
        req, out, pub = reqs[1], outcomes[1], pubs[1]
        save(EROOT / 'others/results' / (first + '.json'), {
            'candidate_id': first, 'source_hash': candidate_hash(req.strategy),
            'evidence': pub.reference.to_dict(), 'request_hash': out.result.request_hash,
            'result_hash': out.result.result_hash, 'stats': stats(out.result.runs[0].execution),
            'input_bindings': {k: v.to_dict() for k, v in req.input_bindings.items()}})
    assert session.stats.pool_starts == 1
    save(EROOT / 'others/parallel_precheck.json', {'status': 'PASS', 'physical_evaluations': 2,
        'new_accounts': 1, 'repeated_C0031': 1, 'five_ledgers_and_result_hash_equal': True,
        'references': [p.reference.to_dict() for p in pubs], 'execution_stats': asdict(session.stats)})
    print({'actual_parallel_precheck': 'PASS', 'new_account': first}, flush=True)


def run():
    assert read(EROOT / 'others/precheck.json')['status'] == 'PASS'
    ctx = context()
    assert read(EROOT / 'others/parallel_precheck.json')['status'] == 'PASS'
    ids = [c for c in read(EROOT / 'protocols/fixed_set.json')['candidates'] if c != 'C0031']
    assert len(ids) == 85
    ids = [c for c in ids if not (EROOT / 'others/results' / (c + '.json')).exists()]
    assert len(ids) == 84
    requests = [request(ctx, cid) for cid in ids]
    print({'prepared': len(requests)}, flush=True)
    with open_research_execution(ctx, experiment=EX, checkpoint=ExecutionCheckpointRequest('fixed85', CheckpointMode.RESUME)) as session:
        for start in range(0, len(ids), 8):
            batch = requests[start:start + 8]
            outcomes = ctx.evaluation.evaluate_many(tuple(batch), execution=session)
            if not all(o.status.value == 'SUCCEEDED' for o in outcomes):
                save(EROOT / 'others/batch_failure.json', [{'candidate_id': c, 'status': o.status.value,
                    'error': str(o.error)} for c, o in zip(ids[start:start + 8], outcomes, strict=True)])
            assert all(o.status.value == 'SUCCEEDED' for o in outcomes), [(o.status.value, str(o.error)) for o in outcomes]
            writes = tuple(EvaluationEvidenceWrite(EX, cid + '_common415', req, out.result)
                           for cid, req, out in zip(ids[start:start + 8], batch, outcomes, strict=True))
            pubs = publish_evidence_many(ctx, writes, execution=session)
            assert all(p.status.value == 'PUBLISHED' for p in pubs), [(p.status.value, str(p.error)) for p in pubs]
            for cid, req, out, pub in zip(ids[start:start + 8], batch, outcomes, pubs, strict=True):
                row = {'candidate_id': cid, 'source_hash': candidate_hash(req.strategy),
                       'evidence': pub.reference.to_dict(), 'request_hash': out.result.request_hash,
                       'result_hash': out.result.result_hash, 'stats': stats(out.result.runs[0].execution),
                       'input_bindings': {k: v.to_dict() for k, v in req.input_bindings.items()}}
                save(EROOT / 'others/results' / (cid + '.json'), row)
            print({'completed': min(start + 8, 84) + 1, 'total': 85}, flush=True)
    save(EROOT / 'others/execution_stats.json', asdict(session.stats))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'precheck', 'parallel_precheck', 'run'))
    args = parser.parse_args()
    {'prepare': prepare, 'precheck': precheck, 'parallel_precheck': parallel_precheck, 'run': run}[args.mode]()
