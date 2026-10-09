"""Group observed S013 account paths after removing declared decision diagnostics."""
from copy import deepcopy
from hashlib import sha256
import json

from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

from common import CACHE, RUNS, cache_read, read, write
from economic_equivalence import ID_FIELDS, LEDGERS, SEMANTIC_FIELDS


DECISION_DIAGNOSTICS = frozenset({
    'acf1', 'bear_range_position', 'bull_range_position', 'momentum20',
    'range_position', 'regime', 'regime_momentum', 'signal_reason',
    'confirmation_acf', 'confirmation_exit_context', 'confirmation_opportunity',
    'confirmation_pass', 'confirmation_score', 'confirmation_turnover',
    'confirmation_volume', 'opportunity_confirmation_score',
    'opportunity_confirmation_applies', 'opportunity_confirmation_pass',
})
REQUIRED = {
    'decisions': {'decision_id', 'signal_date', 'valid_session', 'target_position',
                  'plan_mode', 'action', 'close'},
    'orders': {'order_id', 'decision_id', 'cycle_id', 'signal_date', 'execution_date',
               'side', 'quantity', 'order_type', 'limit_price', 'status'},
    'fills': {'fill_id', 'order_id', 'decision_id', 'cycle_id', 'signal_date',
              'fill_time', 'side', 'quantity', 'price', 'fees', 'trigger'},
    'account_daily': {'date', 'signal_date', 'target_position', 'cash_before',
                      'quantity_before', 'cash', 'quantity', 'close', 'equity'},
    'trades': {'cycle_id', 'status', 'entry_date', 'exit_date', 'quantity',
               'entry_price', 'exit_price', 'net_return'},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def project_table(name, table, registries):
    columns = [field['name'] for field in table['schema']['fields']]
    assert len(columns) == len(set(columns))
    assert REQUIRED[name].issubset(columns), (name, 'required economic fields missing')
    excluded = [column for column in columns
                if name == 'decisions' and column in DECISION_DIAGNOSTICS]
    selected = [column for column in columns if column not in excluded]
    # Retain every unknown column: an unclassified new price/quantity field cannot disappear.
    schema = deepcopy(table['schema'])
    schema.pop('pandas_version', None)
    schema['fields'] = [field for field in schema['fields'] if field['name'] in selected]
    data = []
    for source_row in table['data']:
        assert set(source_row) == set(columns)
        row = {column: deepcopy(source_row[column]) for column in selected}
        for key in ID_FIELDS & row.keys():
            value = row[key]
            if value is None or value == '':
                continue
            registry = registries.setdefault(key, {})
            registry.setdefault(value, f'{key}:{len(registry)}')
            row[key] = registry[value]
        data.append(row)
    projection = {'schema': schema, 'dtypes': {key: table['dtypes'][key] for key in selected},
                  'data': data}
    return projection, {'selected_columns': selected, 'excluded_columns': excluded,
                        'rows': len(data)}


def project_evidence(evidence):
    request = {key: deepcopy(evidence['request_identity'][key]) for key in SEMANTIC_FIELDS}
    runs, disclosures = [], []
    coordinates = set()
    for run in sorted(evidence['runs'], key=lambda item: (item['window_id'], item['scenario_id'])):
        coordinate = (run['window_id'], run['scenario_id'])
        assert coordinate not in coordinates
        coordinates.add(coordinate)
        ids, tables, columns = {}, {}, {}
        for name in LEDGERS:
            tables[name], columns[name] = project_table(name, run['ledgers'][name], ids)
        runs.append({'window_id': coordinate[0], 'scenario_id': coordinate[1], 'ledgers': tables})
        disclosures.append({'window_id': coordinate[0], 'scenario_id': coordinate[1], 'tables': columns})
    return {'request_semantics': request, 'runs': runs}, disclosures


def self_check():
    """Two actual controls plus diagnostic, ID-link and exact monetary mutation checks."""
    sources = []
    projections = []
    for identifier in ('C3000', 'C3001'):
        bound, result = cache_read(CACHE / (identifier + '.pkl.gz'))
        evidence = serialize_evaluation_evidence(bound, result)
        sources.append(evidence)
        projections.append(project_evidence(evidence)[0])
    original_snapshot = canonical(sources[0])
    assert canonical(projections[0]) != canonical(projections[1])
    diagnostic_change = deepcopy(sources[0])
    decision = diagnostic_change['runs'][0]['ledgers']['decisions']['data'][0]
    decision['confirmation_score'] = .499
    decision['signal_reason'] = 'diagnostic-only-change'
    assert canonical(project_evidence(diagnostic_change)[0]) == canonical(projections[0])
    renamed = deepcopy(sources[0])
    for run in renamed['runs']:
        for name in LEDGERS:
            for row in run['ledgers'][name]['data']:
                for key in ID_FIELDS & row.keys():
                    if row[key] not in (None, ''):
                        row[key] = 'RENAMED-' + row[key]
    assert canonical(project_evidence(renamed)[0]) == canonical(projections[0])
    monetary_change = deepcopy(sources[0])
    monetary_change['runs'][0]['ledgers']['fills']['data'][0]['fees'] += .01
    assert canonical(project_evidence(monetary_change)[0]) != canonical(projections[0])
    link_change = deepcopy(sources[0])
    link_change['runs'][0]['ledgers']['fills']['data'][0]['decision_id'] = 'ORPHAN-DECISION'
    assert canonical(project_evidence(link_change)[0]) != canonical(projections[0])
    assert canonical(project_evidence(sources[0])[0]) == canonical(projections[0])
    assert canonical(sources[0]) == original_snapshot
    return {'status': 'PASS', 'actual_accounts': ['C3000', 'C3001'],
            'checks': ['different actual paths remain different', 'diagnostic values excluded',
                       'consistent relational ID rename neutral', 'one-cent fee change distinguished',
                       'broken relational reference distinguished', 'input evidence unchanged']}


def main():
    paths = sorted(RUNS.glob('cost_confirmation_*.json'))
    assert paths, 'No search records'
    rows = []
    for path in paths:
        search = read(path)
        if 'rows' not in search:
            continue
        assert search['status'] == 'COMPLETE', f'Search incomplete: {path.name}'
        rows.extend(search['rows'])
    successful = [row for row in rows if row['status'] == 'SUCCEEDED']
    assert len({row['candidate_id'] for row in successful}) == len(successful)
    assert {'C3000', 'C3001'}.issubset({row['candidate_id'] for row in successful})
    proofs = self_check()
    groups, seen, disclosures = [], {}, []
    for row in successful:
        identifier = row['candidate_id']
        bound, result = cache_read(CACHE / (identifier + '.pkl.gz'))
        assert result.result_hash == row['result_hash']
        projection, columns = project_evidence(serialize_evaluation_evidence(bound, result))
        serialized = canonical(projection)
        digest = sha256(serialized.encode()).hexdigest()
        if digest not in seen:
            seen[digest] = (serialized, len(groups))
            groups.append({'group_id': f'PATH-{len(groups)+1:03}',
                           'economic_projection_sha256': digest, 'members': []})
        previous, index = seen[digest]
        assert previous == serialized, 'Projection digest collision'
        extra = row['parameters'].get('opportunity_confirmation')
        groups[index]['members'].append({
            'candidate_id': identifier, 'label': row['label'], 'qualified': row['qualified'],
            'control': identifier in ('C3000', 'C3001'),
            'confirmation_enabled': row['parameters']['confirmation']['enabled'],
            'opportunity_confirmation_enabled': None if extra is None else extra['enabled'],
            'config_hash': row['config_hash'], 'result_hash': row['result_hash']})
        disclosures.append({'candidate_id': identifier, 'runs': columns})
    for group in groups:
        group['technical_identity_count'] = len(group['members'])
        group['contains_control'] = any(member['control'] for member in group['members'])
        group['enabled_complement_count'] = sum(
            member['opportunity_confirmation_enabled'] is True for member in group['members'])
        group['qualified_identity_count'] = sum(member['qualified'] for member in group['members'])
    result = {
        'status': 'PASS', 'successful_configurations': len(successful),
        'failed_configurations': len(rows) - len(successful), 'economic_path_groups': len(groups),
        'qualified_economic_path_groups': sum(group['qualified_identity_count'] > 0 for group in groups),
        'groups': groups, 'column_disclosures': disclosures, 'self_check': proofs,
        'comparison': 'Exact canonical serialized economic rows, retained dtypes/schema and request '
                      'semantics; no numeric tolerance; IDs normalized jointly across the five ledgers '
                      'with references preserved; digest matches additionally require string equality.',
        'metadata_excluded': ['schema.pandas_version'],
        'evidence_outside_projection': ['signals', 'signal_dtypes', 'signal_support', 'signal_data_identity',
                                       'signal_window', 'observation', 'identity', 'replay_evidence', 'buyhold',
                                       'candidate_id', 'implementation/source/parameter identity'],
        'interpretation': 'Same observed economic path technical identities are not independent discoveries. '
                          'This groups only observed accounts on the reused S013 developer pool and is not '
                          'complete strategy-policy equivalence or unseen-data equivalence. All account_daily '
                          'columns and all orders/fills/trades columns are retained; only explicitly named '
                          'decision diagnostics are removed. Source ledgers remain unchanged.'}
    write(RUNS / 'behavior_groups.json', result)
    print({'status': result['status'], 'successful_configurations': len(successful),
           'economic_path_groups': len(groups)}, flush=True)


if __name__ == '__main__':
    main()
