"""Frozen, zero-fit conjunction diagnostics for two fixed S015 component pairs."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef, MaterialEvidenceWrite

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parent
EX = ExperimentRef('S015', HERE.name)
SOURCE_ITEMS = {
    'EX039_20261023': ('src/standalone.py', 'others/predictions.csv', 'others/thresholds.json', 'others/independent_audit.json'),
    'EX038_20261023': ('src/attribution.py', 'others/predictions.csv', 'others/thresholds.json', 'others/independent_audit.json'),
    'EX036_20261023': ('src/validate.py', 'others/model_features.csv', 'others/labels.csv'),
}
POLICIES = ('all', 'legacy', 'A/path', 'A/risk', 'A/AND', 'B/path', 'B/risk', 'B/AND')

def read(path):
    return json.loads(path.read_bytes())

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')

def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(1, 1, 13))

def material(path):
    media = {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}
    return publish_evidence(context(), MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media[path.suffix], path.suffix[1:]))

def prepare():
    assert not (HERE / 'others/protocol_refs.json').exists()
    refs = {}
    for experiment, keys in SOURCE_ITEMS.items():
        source = read(BASE / experiment / 'others/published_refs.json')
        assert source['validation']['status'] == 'PASS'
        for key in keys:
            ref = EvidenceRef.from_dict(source['materials'][key]); ref.resolve(ROOT)
            refs[experiment + '/' + key] = ref.to_dict()
    old = read(BASE / 'EX038_20261023/others/input_refs.json')
    events = EvidenceRef.from_dict(old['events']); events.resolve(ROOT)
    refs['original_events'] = events.to_dict()
    protocol = {
        'authorization': '用户已批准不限轮次阶段二；EX035–039结果已见，据此选择本次有限合成问题。无阶段三授权。',
        'pairs': {'A': 'EX039 path/net3 keep AND volatility/loss3 keep; no old r1/r5/pressure model controls',
                  'B': 'EX038 net3/temporal_order/linear full keep AND loss3/volatility_transition/linear full keep; nested legacy controls retained'},
        'rules': list(POLICIES),
        'population': 'Exactly the common 323 CLOSED net3 events, positions in existing four forward folds. Same positions and fold IDs for every policy; original entry label on those same events.',
        'thresholds': 'Reuse published boolean decisions; net3 >=0 and loss3 <= its own training-fitted median per fold. No recomputation or choice of thresholds; no new fit.',
        'diagnostics': 'Net3 and same-event entry selected/excluded amount/count/mean; all four folds and all four r1>0/nonpositive x r5>0/nonpositive states; remove the same five largest absolute net3 payoff positions for all policies and both labels.',
        'paired_conjunction': 'For A and B, compare AND separately with path and risk. Report newly excluded count, avoided losses, foregone profits and net retained amount increment. Paired mean-per-common-event CI uses full434 axis, block20, 499 draws, seed13, no multiple-selection correction. Also report differences from legacy and all.',
        'frequency': 'Reuse original recorded entry and actual exit dates: maximum compatible CLOSED event intervals, same-day switch allowed, 275 exit-day windows end159:433. Optimistic opportunity upper bound only; not actual strategy trades or full434 frequency acceptance.',
        'amount_unit': 'Source payoffs normalized by independent initial100000; cash-equivalent amounts multiply by100000. Overlapping events cannot be summed as account PnL or compounded.',
        'limits': 'No OR, weight, threshold or state search. No new fitting, accounts, candidates, data or dates. Entry label deducts buy fee only. State analysis is descriptive and not a new trading condition. Original goals unchanged.',
        'stop': 'After independent audit and publication, integrate stage2 with both supportive and adverse results; no further conjunction tuning from these results.',
        'source_refs': refs,
    }
    save(HERE / 'protocols/composition.json', protocol)
    save(HERE / 'others/protocol_refs.json', {path.name: material(path).to_dict() for path in (HERE / 'protocols/composition.json', Path(__file__))})
    print('EX040_PROTOCOL_FROZEN', flush=True)

def inputs():
    frozen = read(HERE / 'others/protocol_refs.json')
    for name, folder in (('composition.py', 'src'), ('composition.json', 'protocols')):
        assert EvidenceRef.from_dict(frozen[name]).resolve(ROOT).read_bytes() == (HERE / folder / name).read_bytes()
    refs = read(HERE / 'protocols/composition.json')['source_refs']
    paths = {key: EvidenceRef.from_dict(value).resolve(ROOT) for key, value in refs.items()}
    modules = {}
    for key, name in (('EX036_20261023/src/validate.py', 'amount40'), ('EX038_20261023/src/attribution.py', 'bound40'), ('EX039_20261023/src/standalone.py', 'interval40')):
        original = BASE / key
        assert original.read_bytes() == paths[key].read_bytes(), 'Original import bytes differ from authenticated source'
        spec = importlib.util.spec_from_file_location(name, original)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        modules[name] = module
    for key in ('EX038_20261023/others/independent_audit.json', 'EX039_20261023/others/independent_audit.json'):
        assert read(paths[key])['status'] == 'PASS'
    save(HERE / 'others/input_refs.json', refs)
    return paths, modules

def keep_values(frame, column):
    assert frame[column].notna().all()
    assert set(frame[column].unique()).issubset({True, False})
    return frame[column].to_numpy(bool)

def load_population(paths):
    p39 = pd.read_csv(paths['EX039_20261023/others/predictions.csv'])
    p38 = pd.read_csv(paths['EX038_20261023/others/predictions.csv'])
    labels = pd.read_csv(paths['EX036_20261023/others/labels.csv'])
    features = pd.read_csv(paths['EX036_20261023/others/model_features.csv'])
    events = pd.read_csv(paths['original_events'])
    groups = {
        'a_path': p39[p39.target.eq('net3')].sort_values('position'),
        'a_risk': p39[p39.target.eq('loss3')].sort_values('position'),
        'b_path': p38[p38['case'].eq('net3/temporal_order/linear')].sort_values('position'),
        'b_risk': p38[p38['case'].eq('loss3/volatility_transition/linear')].sort_values('position'),
    }
    a = groups['a_path']
    assert len(a) == 323 and a.position.is_unique
    p = a[['date', 'position', 'fold', 'r1', 'r5']].copy().reset_index(drop=True)
    for group in groups.values():
        assert group.position.tolist() == p.position.tolist() and group.fold.tolist() == p.fold.tolist()
        assert group.date.tolist() == p.date.tolist()
        np.testing.assert_allclose(group.payoff, a.y, rtol=0, atol=1e-14)
    net = labels[labels.target.eq('net3')].set_index('position').loc[p.position]
    entry = labels[labels.target.eq('entry')].set_index('position').loc[p.position]
    assert net.y.notna().all() and entry.y.notna().all()
    np.testing.assert_allclose(net.y, a.y, rtol=0, atol=1e-14)
    p['net3'] = net.y.to_numpy(); p['entry'] = entry.y.to_numpy()
    p['keep/all'] = True
    p['keep/legacy'] = keep_values(a, 'keep/legacy')
    np.testing.assert_allclose(a.legacy, groups['b_path'].baseline, rtol=1e-9, atol=1e-12)
    assert np.array_equal(p['keep/legacy'], keep_values(groups['b_path'], 'keep/baseline'))
    p['keep/A/path'] = keep_values(a, 'keep/path')
    p['keep/A/risk'] = keep_values(groups['a_risk'], 'keep/volatility')
    p['keep/B/path'] = keep_values(groups['b_path'], 'keep/full')
    p['keep/B/risk'] = keep_values(groups['b_risk'], 'keep/full')
    for pair in ('A', 'B'):
        p['keep/' + pair + '/AND'] = p['keep/' + pair + '/path'] & p['keep/' + pair + '/risk']
    h3 = events[events.horizon.eq(3)].set_index('position').loc[p.position]
    h1 = events[events.horizon.eq(1)].set_index('position').loc[p.position]
    assert h3.status.eq('CLOSED').all()
    for column in ('entry_date', 'buy_price', 'quantity'):
        assert h3[column].tolist() == h1[column].tolist(), 'Entry label must describe the same entered lot'
    np.testing.assert_allclose(h3.net / 100000, p.net3, rtol=0, atol=1e-12)
    np.testing.assert_allclose(h1.entry_net / 100000, p.entry, rtol=0, atol=1e-12)
    assert len(features) == 434
    return p, events, features.date.tolist()

def summarize(p, policy, outcome, old):
    keep = p['keep/' + policy].to_numpy(bool); y = p[outcome].to_numpy(float)
    positive = np.maximum(y, 0); negative = np.maximum(-y, 0)
    return {'n': len(p), 'selected': old.amount(y[keep]), 'excluded': old.amount(y[~keep]),
            'caught_loss_fraction': old.ratio(negative[~keep].sum(), negative.sum()),
            'missed_profit_fraction': old.ratio(positive[~keep].sum(), positive.sum()),
            'retained_event_sum': float(y[keep].sum()), 'retained_amount': float(y[keep].sum() * 100000)}

def difference(p, current, reference, outcome, interval):
    keep = p['keep/' + current].to_numpy(bool); before = p['keep/' + reference].to_numpy(bool)
    y = p[outcome].to_numpy(float); gain = (keep.astype(int) - before.astype(int)) * y
    removed = before & ~keep; added = keep & ~before
    return {'n': len(p), 'removed_n': int(removed.sum()), 'added_n': int(added.sum()),
            'removed_loss_amount': float(np.maximum(-y[removed], 0).sum() * 100000),
            'removed_profit_amount': float(np.maximum(y[removed], 0).sum() * 100000),
            'added_event_amount': float(y[added].sum() * 100000),
            'net_retained_amount_increment': float(gain.sum() * 100000),
            'mean_per_common_event': float(gain.mean()), 'ci95_mean_per_common_event': interval(p, gain)}

def run():
    assert not (HERE / 'others/results.json').exists()
    paths, modules = inputs(); old = modules['amount40']; attr = modules['bound40']; interval = modules['interval40'].interval
    p, events, dates = load_population(paths)
    omit = p.net3.abs().nlargest(5).index
    groups = {'all': p, 'omit_largest5_net3': p.drop(omit)}
    groups.update({'fold/' + str(fold): group for fold, group in p.groupby('fold')})
    for a in (False, True):
        for b in (False, True):
            name = f'state/r1_{"positive" if a else "nonpositive"}/r5_{"positive" if b else "nonpositive"}'
            groups[name] = p[p.r1.gt(0).eq(a) & p.r5.gt(0).eq(b)]
    result = {'population_n': len(p), 'omitted_positions': p.loc[omit, 'position'].astype(int).tolist(), 'policies': {}, 'paired': {}}
    for policy in POLICIES:
        result['policies'][policy] = {'outcomes': {outcome: {group: summarize(frame, policy, outcome, old) for group, frame in groups.items()} for outcome in ('net3', 'entry')},
                                     'frequency_upper_bound': attr.bound(p, policy, events, 3, dates)}
    for pair in ('A', 'B'):
        for reference in (pair + '/path', pair + '/risk', 'legacy', 'all'):
            key = pair + '/AND vs ' + reference
            result['paired'][key] = {outcome: {group: difference(frame, pair + '/AND', reference, outcome, interval) for group, frame in groups.items()} for outcome in ('net3', 'entry')}
    p.to_csv(HERE / 'others/decisions.csv', index=False)
    save(HERE / 'others/results.json', result)
    save(HERE / 'others/design_counts.json', {'pairs': 2, 'policies': 8, 'common_closed_net3_events': 323,
         'outcomes': 2, 'groups': len(groups), 'paired_comparisons': 8, 'bootstrap_repetitions': 499,
         'frequency_windows_per_policy': 275, 'new_model_fits': 0, 'continuous_accounts': 0, 'parameter_search': 0,
         'frozen_source_imports_verified_before_execution': True})
    for pair in ('A', 'B'):
        print(pair, {key: result['policies'][pair + '/' + key]['outcomes']['net3']['all']['selected']['n'] for key in ('path', 'risk', 'AND')}, flush=True)
    print('EX040_COMPUTED_AWAITING_INDEPENDENT_AUDIT', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=('prepare', 'run'))
    {'prepare': prepare, 'run': run}[parser.parse_args().mode]()
