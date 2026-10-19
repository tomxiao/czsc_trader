"""Independent audit of fixed opportunity diagnostic, never invokes original analysis."""
import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import socket

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = ROOT / 'research/S014/materials/20261019_full_research_diagnosis'
METRICS = ['A9', 'L9', 'O9']
ESTIMATORS = ['node_mean', 'fixed_common_strata', 'within_group_cluster_equal']
checks = []
sources = []

def blocked(*args, **kwargs):
    raise RuntimeError('Independent audit forbids network calls')

socket.socket.connect = blocked
socket.create_connection = blocked

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def verify(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

def pub(value):
    ref = EvidenceRef.from_dict(value)
    verify('S014 reference only: ' + ref.evidence_id, ref.experiment.strategy_id == 'S014')
    data = ref.resolve(ROOT).read_bytes()
    verify('published hash: ' + ref.evidence_id, sha256(data).hexdigest() == ref.sha256)
    sources.append(ref.to_dict())
    return data

def close(name, actual, expected, tol=1e-12):
    if expected is None:
        verify(name + ' null preserved', actual is None)
    else:
        verify(name, actual is not None and math.isclose(actual, expected, abs_tol=tol, rel_tol=0))

class IndependentScope:
    """Aggregate cluster sufficient statistics; original code weights raw node rows."""
    def __init__(self, rows, all_cluster_ids):
        self.rows = rows
        self.K = len(all_cluster_ids)
        groups = [(int(x.year), bool(x.P), bool(x.D)) for x in rows.itertuples()]
        self.strata_keys = sorted(set(groups))
        self.counts = np.zeros((self.K, 2))
        self.sums = np.zeros((self.K, 2, 3))
        self.state_counts = np.zeros((len(self.strata_keys), self.K, 2))
        self.state_sums = np.zeros((len(self.strata_keys), self.K, 2, 3))
        for row, key in zip(rows.itertuples(), groups):
            c = all_cluster_ids.index(row.cluster_id)
            x = int(row.X)
            s = self.strata_keys.index(key)
            y = np.array([getattr(row, m) for m in METRICS])
            self.counts[c, x] += 1
            self.sums[c, x] += y
            self.state_counts[s, c, x] += 1
            self.state_sums[s, c, x] += y
        totals = self.state_counts.sum(axis=1)
        self.common_weights = totals.min(axis=1)
        self.common = self.common_weights > 0
        self.cluster_group_means = np.divide(self.sums, self.counts[..., None],
            out=np.full_like(self.sums, np.nan), where=self.counts[..., None] > 0)

    def estimate(self, w):
        counts = np.einsum('c,cg->g', w, self.counts)
        sums = np.einsum('c,cgm->gm', w, self.sums)
        raw = (sums[1] / counts[1] - sums[0] / counts[0]) if np.all(counts > 0) else None
        adjusted = None
        if self.common.any():
            cs = np.einsum('c,scg->sg', w, self.state_counts[self.common])
            ss = np.einsum('c,scgm->sgm', w, self.state_sums[self.common])
            if np.all(cs > 0):
                differences = ss[:, 1] / cs[:, 1, None] - ss[:, 0] / cs[:, 0, None]
                adjusted = np.average(differences, axis=0, weights=self.common_weights[self.common])
        equal_means = []
        for x in (0, 1):
            seen = (self.counts[:, x] > 0) & (w > 0)
            if not seen.any():
                equal_means = []
                break
            equal_means.append(np.average(self.cluster_group_means[seen, x], axis=0, weights=w[seen]))
        equal = equal_means[1] - equal_means[0] if equal_means else None
        return dict(zip(ESTIMATORS, (raw, adjusted, equal)))

def run(output_path=None):
    lock = read(OUT / 'opportunity_diagnostic_lock_v2.json')
    published = {key: pub(value) for key, value in lock.items()}
    for key, filename in [('source', 'opportunity_diagnostic_v2.py'), ('design', 'opportunity_diagnostic_plan.json'),
                          ('feasibility_rows', 'opportunity_feasibility_verified_rows.csv'),
                          ('feasibility_summary', 'opportunity_feasibility_verified.json')]:
        verify(key + ' locked bytes unchanged', published[key] == (OUT / filename).read_bytes())
    feasibility = json.loads(published['feasibility_summary'])
    original = [pub(value) for value in feasibility['source_references']]
    # Recreate past-only opportunity exposure from the saved original policy ledger.
    events = pd.read_csv(BytesIO(original[0]))
    account = json.loads(original[1])
    receipt = json.loads(original[2])
    calendar = pd.read_csv(BytesIO(original[3]))
    verify('original no-intervention account identity', account['request_identity']['strategy_reference'] == 'S014-C9000')
    verify('original no-op audit', receipt['audit']['status'] == 'PASS' and receipt['audit']['kind'] == 'NOOP_FULL_ACCOUNT_EQUIVALENCE')
    ledgers = account['runs'][0]['ledgers']
    decisions = pd.DataFrame(ledgers['decisions']['data'])
    decisions['date'] = pd.to_datetime(decisions.signal_date).dt.normalize()
    decisions = decisions.sort_values('date').reset_index(drop=True)
    pinned = pd.to_datetime(calendar.date)
    verify('original session calendar complete', pd.to_datetime(decisions.valid_session).dt.normalize().tolist() == pinned.tolist())
    verify('signal dates strictly previous session', decisions.date.iloc[1:].tolist() == pinned.iloc[:-1].tolist())
    verify('original account no intervention flags', not decisions.intervention_done.any() and not decisions.intervention_today.any())
    eligible = [bool(x.ready) and x.parent == 1 and x.high == 1 for x in decisions.itertuples()]
    pos = {x: i for i, x in enumerate(decisions.date)}
    orders = pd.DataFrame(ledgers['orders']['data'])
    buys = orders.loc[orders.side.eq('BUY') & orders.status.eq('FILLED')].copy()
    buys['entry_day'] = pd.to_datetime(buys.execution_date).dt.normalize()
    verify('filled BUY dates unique', not buys.entry_day.duplicated().any())
    buys = buys.set_index('entry_day')
    feature = pd.read_csv(BytesIO(published['feasibility_rows']))
    by_feature = feature.set_index('cycle_id')
    verify('145 existing EX035 nodes and features', len(events) == len(feature) == 145 and set(events.cycle_id) == set(feature.cycle_id))
    for event in events.itertuples():
        day, entry = pd.Timestamp(event.decision_date), pd.Timestamp(event.entry_date)
        i, e = pos[day], pos[entry]
        order = buys.loc[entry]
        feature_row = by_feature.loc[event.cycle_id]
        own = e - 1
        verify(event.cycle_id + ' causal exact entry order trigger',
               pd.Timestamp(order.signal_date).normalize() == decisions.date.iloc[own]
               and order.decision_id == decisions.iloc[own].decision_id
               and decisions.iloc[own].entry_signal and eligible[own] and i - 6 <= own < i)
        verify(event.cycle_id + ' past six minus own exact feature',
               sum(eligible[i-6:i]) - 1 == feature_row.additional_prior_opportunities
               and feature_row.latest_feature_session == str(decisions.date.iloc[i-1].date()))
    rows_path = OUT / 'opportunity_diagnostic_rows.csv'
    output = read(OUT / 'opportunity_diagnostic.json')
    verify('parent-confirmed fixed result identity', digest(OUT / 'opportunity_diagnostic.json') == '8e6af6167aee4b960dfc6c0494b2c2a984d15403f30d9b0ba59aaa38c3737bfd')
    verify('executed v2 source identity', output['source_sha256'] == digest(OUT / 'opportunity_diagnostic_v2.py'))
    rows = pd.read_csv(rows_path)
    verify('output rows hash bound', digest(rows_path) == output['rows_sha256'])
    verify('published original 145 row identities', set(rows.cycle_id) == set(events.cycle_id) and not rows.cycle_id.duplicated().any())
    for key in ['entry_date', 'decision_date', 'terminal_date', 'cluster_id', *METRICS]:
        old = events.set_index('cycle_id')[key].sort_index()
        new = rows.set_index('cycle_id')[key].sort_index()
        if key in METRICS:
            verify('existing ' + key + ' unchanged', np.allclose(old.to_numpy(float), new.to_numpy(float), rtol=0, atol=1e-15))
        else:
            verify('existing ' + key + ' unchanged', old.tolist() == new.tolist())
    states_ref = output['source_references']['states']
    states = pd.read_csv(BytesIO(pub(states_ref))).set_index('cycle_id')
    for row in rows.itertuples():
        state = states.loc[row.cycle_id]
        verify(row.cycle_id + ' known state unchanged',
               row.entry_date == state.entry_date and row.decision_date == state.decision_date
               and row.P == (state.P_value > 0) and row.D == (state.D_value > 0)
               and abs(row.P_value - (row.decision_close / (row.entry_price * 1.001) - 1)) < 1e-12
               and abs(row.D_value - (row.decision_close / row.previous_close - 1)) < 1e-12)
        verify(row.cycle_id + ' accounting identity retained', abs(row.A9 - row.L9 + row.O9) < 1e-10)
        f = by_feature.loc[row.cycle_id]
        verify(row.cycle_id + ' joined exposure and cutoff',
               row.X == (f.additional_prior_opportunities >= 1)
               and row.without2026 == (row.decision_date <= '2025-12-31' and row.terminal_date <= '2025-12-31'))
    cluster_ids = sorted(rows.cluster_id.unique().tolist())
    verify('59 original clusters retained', len(cluster_ids) == 59)
    verify('expected 60 none / 85 extra', Counter(rows.X) == Counter({False: 60, True: 85}))
    # Verify connected interval partition without changing its labels.
    reconstructed = []
    current, endpoint = -1, ''
    for row in rows.sort_values(['decision_date', 'cycle_id']).itertuples():
        if row.decision_date > endpoint:
            current += 1
        endpoint = max(endpoint, row.terminal_date)
        reconstructed.append((current, row.cluster_id))
    verify('original connected interval clusters reproduced',
           len(set(reconstructed)) == 59 and len({x[0] for x in reconstructed}) == 59)
    masks = {'ALL': np.ones(len(rows), bool), 'WITHOUT2026': rows.without2026.to_numpy(bool)}
    masks.update({str(y): rows.year.eq(y).to_numpy(bool) for y in sorted(rows.year.unique())})
    scopes = {key: IndependentScope(rows.loc[mask], cluster_ids) for key, mask in masks.items()}
    verify('nine fixed scopes only', set(output['scopes']) == set(scopes) and len(scopes) == 9)
    ones = np.ones(59, int)
    recomputed = {}
    for key, obj in scopes.items():
        actual = obj.estimate(ones)
        recomputed[key] = {kind: {m: None if value is None else float(value[j]) for j, m in enumerate(METRICS)} for kind, value in actual.items()}
        declared = output['scopes'][key]
        for kind in ESTIMATORS:
            for j, metric in enumerate(METRICS):
                close(key + '/' + kind + '/' + metric, declared['differences_extra_minus_none'][kind][metric], None if actual[kind] is None else float(actual[kind][j]))
        expected_states = []
        for index, state_key in enumerate(obj.strata_keys):
            counts = obj.state_counts[index].sum(axis=0).astype(int)
            expected_states.append({'year': state_key[0], 'P': state_key[1], 'D': state_key[2],
                                    'none_n': int(counts[0]), 'extra_n': int(counts[1]),
                                    'weight': int(counts.min()), 'common_support': bool(counts.min())})
        verify(key + ' all state strata / exclusions / fixed weights retained', declared['population']['strata'] == expected_states)
        verify(key + ' common coverage matches', declared['population']['common_support_nodes'] == int(obj.state_counts[obj.common].sum()))
        for x, group in [(0, 'none'), (1, 'extra')]:
            verify(key + '/' + group + ' nodes / observed clusters', declared['population'][group]['nodes'] == int(obj.counts[:, x].sum())
                   and declared['population'][group]['clusters'] == int((obj.counts[:, x] > 0).sum()))
    verify('all original clusters left out exactly once', [r['omitted_original_cluster'] for r in output['leave_one_original_cluster_out']] == cluster_ids)
    for index, saved in enumerate(output['leave_one_original_cluster_out']):
        w = ones.copy()
        w[index] = 0
        for key, obj in scopes.items():
            vals = obj.estimate(w)
            for kind, v in vals.items():
                for j, metric in enumerate(METRICS):
                    close('LOO/' + str(index) + '/' + key + '/' + kind + '/' + metric,
                          saved['scopes'][key][kind][metric], None if v is None else float(v[j]))
    random = np.random.default_rng(13)
    distributions = {s: {k: [] for k in ESTIMATORS} for s in scopes}
    for _ in range(2000):
        selected = random.integers(0, 59, size=59)
        w = np.array([np.count_nonzero(selected == i) for i in range(59)])
        for key, obj in scopes.items():
            for kind, val in obj.estimate(w).items():
                distributions[key][kind].append([np.nan] * 3 if val is None else val)
    for key in scopes:
        for kind in ESTIMATORS:
            values = np.asarray(distributions[key][kind])
            valid = np.isfinite(values).all(axis=1)
            declared = output['scopes'][key]['joint_cluster_bootstrap'][kind]
            verify(key + '/' + kind + ' valid/null bootstrap replicates', declared['valid_draws'] == int(valid.sum()) and declared['null_draws'] == int((~valid).sum()))
            for j, metric in enumerate(METRICS):
                interval = np.quantile(values[valid, j], [.025, .975]) if valid.any() else None
                expected = declared['ordinary_descriptive_95_interval'][metric]
                if interval is None:
                    verify(key + '/' + kind + '/' + metric + ' null interval retained', expected is None)
                else:
                    verify(key + '/' + kind + '/' + metric + ' bootstrap interval', np.allclose(expected, interval, rtol=0, atol=1e-12))
    result = {
        'status': 'PASS_INDEPENDENT_EXISTING_EVIDENCE_AUDIT',
        'scope': 'One locked prior-six-session opportunity-density contrast, existing 145 EX035 events; no new experiments',
        'method': 'Independent cluster/group/stratum sufficient-statistic aggregation; original analysis code not imported or executed',
        'assertion_count': len(checks), 'checks': checks,
        'source_references': sources,
        'reviewed_sha256': {name: digest(OUT / name) for name in ['opportunity_diagnostic_plan.json', 'opportunity_diagnostic_lock.json', 'opportunity_diagnostic_lock_v2.json', 'opportunity_diagnostic.py', 'opportunity_diagnostic_v2.py', 'opportunity_diagnostic.json', 'opportunity_diagnostic_rows.csv']},
        'review_script': {'path': Path(__file__).relative_to(ROOT).as_posix(), 'sha256': digest(Path(__file__))},
        'independent_differences_extra_minus_none': recomputed,
        'interpretation_limits': [
            'Historical eligible signal density includes pre-entry signals; it is not actual future missed orders, a new independent source, or a causal treatment.',
            'Cluster-equal contrast averages each groups observed clusters, not a paired-common-cluster effect.',
            'Year/P/D common-support estimand concerns only overlapping strata with pre-fixed min-count weights; missing required resample strata are null, not silently dropped.',
            'Original 59 interval clusters and joint resampling preserve measured overlap; they do not prove independent shocks or correct all historical selection bias.',
            'All local values inherit EX035 E9 and W_D, cannot be summed into continuous account returns or transfer directly to C0056.',
            'Intervals and direction diagnostics do not change original yearly return/drawdown/frequency acceptance.'
        ],
        'new_fits': 0, 'new_return_labels': 0, 'new_accounts': 0,
        'new_market_data_calls': 0, 'new_matching_or_replay_calls': 0,
    }
    if output_path is not None:
        with output_path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
    print(json.dumps({'status': result['status'], 'assertions': len(checks),
                      'output_path': None if output_path is None else str(output_path),
                      'output_sha256': None if output_path is None else digest(output_path),
                      'ALL': recomputed['ALL'], 'WITHOUT2026': recomputed['WITHOUT2026']}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        help='Optional new audit JSON path; existing files are never overwritten. Default: stdout only.')
    run(parser.parse_args().output)
