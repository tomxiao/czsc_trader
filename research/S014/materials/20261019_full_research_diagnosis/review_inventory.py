"""S014 evidence inventory and existing-account population coverage; no fitting."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BATCH = ROOT / 'research/S014'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def published_frame(experiment, relative):
    folder = BATCH / 'experiments' / experiment
    source = folder / relative
    result = read(folder / 'others/result.json')
    expected = digest(source)
    matches = [v for v in result['evidence'].values()
               if isinstance(v, dict) and v.get('type') == 'EvidenceRef' and v.get('sha256') == expected]
    if not matches:
        raise ValueError('No explicitly declared evidence reference for ' + str(source))
    ref = EvidenceRef.from_dict(matches[0])
    content = ref.resolve(ROOT).read_bytes()
    if content != source.read_bytes():
        raise ValueError('Working bytes differ from published evidence')
    return pd.read_csv(BytesIO(content)), {
        'path': source.relative_to(ROOT).as_posix(), 'sha256': expected,
        'reference': ref.to_dict(), 'bytes': len(content)}


def inventory():
    items = []
    for folder in sorted((BATCH / 'experiments').iterdir()):
        if not folder.is_dir() or not folder.name.startswith('EX'):
            continue
        result_path = folder / 'others/result.json'
        result = read(result_path) if result_path.exists() else {}
        entry = {'experiment': folder.name, 'result_present': result_path.exists(),
                 'status': result.get('status'), 'conclusion': result.get('conclusion'),
                 'next_step': result.get('next_step'), 'delivery': result.get('delivery'),
                 'notes': (folder / 'notes.md').read_text(encoding='utf-8-sig') if (folder / 'notes.md').exists() else None,
                 'counts': {k: result[k] for k in ('new_accounts','new_diagnostic_accounts','new_fits','formal_fits',
                            'failed_fits','new_data_calls','new_source_calls','new_labels','new_supported_components') if k in result},
                 'report_paths': []}
        candidates = [folder / 'others/report.md', folder / 'protocols/report.md', folder / 'protocols/account_report.md']
        for path in candidates:
            if path.exists():
                entry['report_paths'].append({'path':path.relative_to(ROOT).as_posix(),'sha256':digest(path),'bytes':path.stat().st_size})
        copy_path = folder / 'protocols/report_copy_verification.json'
        if copy_path.exists():
            entry['copy_verification_saved'] = read(copy_path)
        delivery = result.get('delivery')
        if isinstance(delivery, dict) and 'stage' in delivery and 'revision' in delivery:
            formal = BATCH / 'deliveries' / delivery['stage'] / str(delivery['revision']) / 'report.md'
            if formal.exists():
                mirrors = [p for p in candidates if p.exists() and p.read_bytes() == formal.read_bytes()]
                entry['formal_report'] = {'path':formal.relative_to(ROOT).as_posix(),'sha256':digest(formal),
                                         'byte_identical_local_mirrors':[p.relative_to(ROOT).as_posix() for p in mirrors]}
                if (folder / 'others/report.md').exists() and folder.name != 'EX001_20261016' and not mirrors:
                    raise ValueError('Formal/local report differs: ' + folder.name)
        if result_path.exists():
            entry['result_sha256'] = digest(result_path)
        items.append(entry)
    if len(items) != 39:
        raise ValueError('Expected existing EX001 through EX039 without creating experiments')
    write(OUT / 'experiment_inventory.json', {'scope':'S014_ONLY','experiments':items,'count':len(items),
          'not_independent_mechanism_count':True,'new_fits':0,'new_return_labels':0,'new_accounts':0,'new_market_data_calls':0})


def population():
    inputs, input_source = published_frame('EX032_20261018', 'others/inputs.csv')
    if inputs.date.duplicated().any() or inputs.signal.duplicated().any():
        raise ValueError('Duplicate source dates or signal positions')
    inputs = inputs.sort_values('signal').reset_index(drop=True)
    if not np.array_equal(inputs.signal.to_numpy(), np.arange(len(inputs))):
        raise ValueError('Nonconsecutive inherited signal calendar')
    dates = pd.to_datetime(inputs.date)
    # T decision -> T+1 execution under the frozen one-session order contract.
    by_entry = {day: i - 1 for i,day in enumerate(dates) if i > 0}
    source_refs = [input_source]
    records, summaries = [], {}
    targets = [('EX023_20261018','support_exit_reserve_H10','S014-C0056'),
               ('EX024_20261018','support_first_profit_exit_H10','S014-C0057')]
    # Exact variant strings are verified against the old report/CSV inventory.
    available = {}
    for ex, variant, candidate in targets:
        frame, source = published_frame(ex, 'others/path_cycles.csv')
        available[ex] = sorted(frame.variant.unique().tolist())
        source_refs.append(source)
        if variant not in set(frame.variant):
            raise ValueError('Unexpected variant, inspect inventory before correcting: '+json.dumps(available))
        selected = frame.loc[frame.variant.eq(variant) & frame.cutoff.eq('2026-10-15') & frame.window.eq('ALL')].copy()
        if (len(selected) != 138 or selected.entry_date.duplicated().any()
                or not selected.status.isin(['CLOSED','MARKED_OPEN_NO_EXIT_FEE']).all()):
            raise ValueError('Expected exact 138 unique entry cycles with declared closed/marked states')
        source_total = float(selected.cycle_log.sum())
        annual = {}
        for row in selected.itertuples():
            entry = pd.Timestamp(row.entry_date)
            idx = by_entry.get(entry)
            if idx is None:
                raise ValueError('Entry is not in inherited executable calendar')
            parent = inputs.iloc[idx]
            value = str(parent.A).lower()
            if value not in ('true','false'):
                raise ValueError('Missing/invalid A state')
            rec = {'candidate':candidate,'variant':variant,'cycle_id':row.cycle_id,'entry_date':row.entry_date,
                   'decision_date':str(dates.iloc[idx].date()),'entry_year':int(row.entry_year),
                   'in_A_population':value=='true','status':row.status,
                   'existing_cycle_log':float(row.cycle_log)}
            records.append(rec)
        own = pd.DataFrame([r for r in records if r['candidate']==candidate])
        for year,g in own.groupby('entry_year'):
            annual[str(year)] = {'entries':len(g),'A_true':int(g.in_A_population.sum()),'A_false':int((~g.in_A_population).sum())}
        total = float(own.existing_cycle_log.sum())
        if abs(total-source_total)>1e-12:
            raise ValueError('Cycle contributions changed')
        summaries[candidate] = {'entries':len(own),'closed':int(own.status.eq('CLOSED').sum()),
            'marked_open_no_exit_fee':int(own.status.eq('MARKED_OPEN_NO_EXIT_FEE').sum()),
            'A_true':int(own.in_A_population.sum()),
            'A_false':int((~own.in_A_population).sum()),'outside_A_fraction':float((~own.in_A_population).mean()),
            'A_true_existing_log_sum':float(own.loc[own.in_A_population,'existing_cycle_log'].sum()),
            'A_false_existing_log_sum':float(own.loc[~own.in_A_population,'existing_cycle_log'].sum()),
            'existing_total_cycle_log':total,'cycle_log_reconciliation_return':float(np.expm1(total)),
            'entry_year_counts_not_annual_pnl':annual}
    pd.DataFrame(records).to_csv(OUT / 'entry_population_members.csv',index=False,lineterminator='\n')
    write(OUT / 'population_coverage.json', {'status':'VERIFIED_EXISTING_EVIDENCE_ARITHMETIC_ONLY',
          'sources':source_refs,'summaries':summaries,'mapping':'Actual entry E mapped to immediately preceding pinned stock session D under original T+1 one-shot order contract',
          'limitations':['A/H3 population gap is coverage evidence, not evidence a new signal works',
                        'Grouped old cycle logs cannot be added/subtracted to simulate a filtered account',
                        'Entry-year counts and cycle-log grouping are not calendar-year account returns',
                        'Chosen representative accounts and historical outcomes were already seen'],
          'new_fits':0,'new_market_data_calls':0,'new_return_labels':0,'new_accounts':0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('inventory','population','all'), default='all', nargs='?')
    args = parser.parse_args()
    def blocked(*args, **kwargs):
        raise RuntimeError('Offline existing-evidence diagnosis forbids network access')
    socket.socket.connect = blocked
    socket.create_connection = blocked
    if args.mode in ('inventory','all'):
        inventory()
    if args.mode in ('population','all'):
        population()
    print('EXISTING_EVIDENCE_INVENTORY_AND_POPULATION_PASS')
