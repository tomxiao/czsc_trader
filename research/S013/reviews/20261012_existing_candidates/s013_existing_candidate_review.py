"""Read existing S013 registrations and account evidence; no evaluation or publication."""
from pathlib import Path
from collections import Counter
import hashlib
import importlib.util
import json
import sys

from strategy_manager import StrategyRegistry, CandidateKey
from strategy_evaluator import AssessmentEvidence
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.tmp/s013-existing-candidate-review'
CONTRACT = '7c751496de5bc7cf108e28067a859666d42fd7687f37e08253778f49c7dc7099'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref_path(ref):
    assert ref['experiment']['strategy_id'] == 'S013'
    path = ROOT / 'research/S013/assets/evidence' / ref['experiment']['experiment_id'] / ref['evidence_id']
    assert digest(path) == ref['sha256'], path
    return path


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/name).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    source = ROOT / 'research/S013/experiments/EX074_20261011/src/economics_reference.py'
    spec = importlib.util.spec_from_file_location('existing_economics', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    registry = StrategyRegistry(ROOT/'research/registrations')
    registrations = {}
    for path in sorted((ROOT/'research/registrations/S013/candidates').glob('*.json')):
        record = registry.get_candidate(CandidateKey('S013', path.stem), evidence_root=ROOT/'research/S013')
        registrations[path.stem] = record
    latest, evidence_refs, metadata = {}, {}, {}
    for folder in sorted((ROOT/'research/S013/assets/deliveries/CANDIDATES').iterdir(), key=lambda p: int(p.name)):
        d = read(folder/'delivery.json')
        for candidate in d['content']['payload']['candidates']:
            cid = candidate['identity']['key']['candidate_id']
            assert cid in registrations and registrations[cid].content_sha256 == candidate['identity']['content_sha256']
            latest[cid] = candidate
        for ref in d['content']['evidence']:
            if ref.get('schema') == 'account_evaluation':
                evidence_refs[ref['sha256']] = ref
            elif ref.get('media_type') == 'application/json':
                metadata[ref['sha256']] = ref
    rows = []
    for cid, record in registrations.items():
        if cid in latest:
            support = latest[cid]['evaluations'][0]['evidence']
            path = ref_path(support)
        else:
            support = record.origin.evidence[0].to_dict()
            path = ROOT/'research/S013'/support['path']
            assert digest(path) == support['sha256']
        evidence = read(path)
        row = {'candidate_id': cid, 'content_sha256': record.content_sha256,
               'source': path.relative_to(ROOT).as_posix(), 'source_sha256': digest(path),
               'registration_authenticated': True, 'schema_version': evidence.get('schema_version')}
        if evidence.get('schema_version') != 6:
            row['status'] = 'HISTORICAL_SCHEMA_NOT_CURRENT'
            rows.append(row)
            continue
        validate_evaluation_evidence(evidence)
        assert len(evidence['assessment_evidence']) == 1
        a = evidence['assessment_evidence'][0]
        assert a['candidate']['candidate_id'] == 'S013-'+cid and a['candidate']['content_sha256'] == record.content_sha256
        economics = module.economics(AssessmentEvidence.from_dict(a))
        assert len(a['account']) == 1636 and a['account'][0]['session'] == '2020-01-02' and a['account'][-1]['session'] == '2026-09-30'
        current = a['scenario_context']['benchmark_contract_sha256'] == CONTRACT and a['scenario_context']['one_way_cost'] == .001
        years = [y for y,v in economics['benchmark_annual'].items() if v['return'] > 0]
        sessions = sum(economics['annual'][y]['sessions'] for y in years)
        trades = sum(economics['annual'][y]['closed_cycles'] for y in years)
        row.update(status='CURRENT_CONTRACT' if current else 'DIFFERENT_BENCHMARK_CONTRACT',
                   current_contract=current, request_hash=evidence['request_hash'], result_hash=evidence['result_hash'],
                   economics=economics, positive_buyhold_years=years,
                   positive_year_sessions=sessions, positive_year_closed_trades=trades,
                   positive_year_frequency60=60*trades/sessions,
                   positive_year_frequency_pass=15*trades >= sessions,
                   current_four_gates_pass=current and economics['qualified'])
        rows.append(row)
    save('centres.json', {'source_sha256': digest(source), 'registrations': len(registrations), 'rows': rows})
    save('account_reference_index.json', list(evidence_refs.values()))
    save('metadata_reference_index.json', list(metadata.values()))
    print(json.dumps({'registered':len(registrations), 'status_counts':dict(Counter(r['status'] for r in rows)),
        'current_four_gate_centres':[r['candidate_id'] for r in rows if r.get('current_four_gates_pass')],
        'current_four_plus_positive_frequency':[r['candidate_id'] for r in rows if r.get('current_four_gates_pass') and r['positive_year_frequency_pass']],
        'accounts_indexed':len(evidence_refs),'metadata_indexed':len(metadata)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
