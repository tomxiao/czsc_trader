"""Render the completed, authenticated S017 economic panel without new evaluations.

Requires all six explicit experiment analyses to be PASS. Rebind original public
account bytes and identities, compare every analysis summary to its account,
and retain identical primary contracts and buy-and-hold paths. This presentation
check reuses the public diagnoses recorded by analysis; it does not repeat their
economic audit or replace final delivery validation. Never reads checkpoints.
Outputs: others/return_drawdown_panel.png and return_drawdown_panel_sources.json.
"""
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math
import os

from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from analyze import (CONTROL, CONTROL_ID, ECONOMIC_FIELDS, PRIMARY,
                     verify_contracts, verify_hold_path, summarize_run, goals)
from publish import read_account_views
from run import SPEC


ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
os.environ['MPLCONFIGDIR'] = str(ROOT / '.tmp/s017-research/matplotlib-panel')


EXPERIMENTS = {
    'EX011_20261029': (('C0036', 'C0037'), ('C0013',)),
    'EX012_20261029': (('C0038', 'C0039'), ('C0013',)),
    'EX013_20261029': (('C0040', 'C0041', 'C0042'), ('C0013',)),
    'EX014_20261029': (('C0043',), ('C0013', 'C0040')),
    'EX015_20261029': (('C0044',), ('C0013', 'C0036')),
    'EX016_20261029': (('C0045',), ('C0013', 'C0043')),
}
GROUPS = {
    'Intraday ORB': (('C0036', 'C0037'), '#2878B5'),
    'Intraday market reversal': (('C0038', 'C0039'), '#8E5AA9'),
    'Trend with context gates': (('C0040', 'C0041', 'C0042'), '#D5781B'),
    'Trend with entry context': (('C0043', 'C0045'), '#38965B'),
    'Overnight ORB': (('C0044',), '#148D95'),
}


def digest(content):
    return sha256(content).hexdigest()


def local_json(path):
    content = path.read_bytes()
    return json.loads(content), digest(content)


def analysis_inputs():
    """Fail before opening any account or figure when even one analysis is absent."""
    paths = {name: ROOT / 'research/S017/experiments' / name / 'others/analysis.json'
             for name in EXPERIMENTS}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError('all six completed analyses are required: ' + ', '.join(missing))
    decoded = {name: local_json(path) for name, path in paths.items()}
    incomplete = [name for name, (value, _) in decoded.items()
                  if value.get('status') != 'PASS' or value.get('experiment') != name]
    if incomplete:
        raise ValueError('all six analyses must be PASS before account reads: ' + ', '.join(incomplete))
    analyses, source_files, references = {}, {}, {}
    origins = {CONTROL_ID: CONTROL}
    for name, (keys, _) in EXPERIMENTS.items():
        origins.update({key: ExperimentRef('S017', name) for key in keys})
    for name, path in paths.items():
        value, analysis_sha = decoded[name]
        keys, controls = EXPERIMENTS[name]
        expected = set(keys + controls)
        work = path.parents[1]
        source_sha = digest((work / 'src/analyze.py').read_bytes())
        if (value['status'] != 'PASS' or value['experiment'] != name
                or value['analysis_source_sha256'] != source_sha
                or set(value['source_accounts']) != expected or set(value['summaries']) != expected):
            raise ValueError('incomplete or changed analysis: ' + name)
        configs, _ = local_json(work / 'protocols/configurations.json')
        accounts, accounts_sha = local_json(work / 'others/accounts.json')
        if (set(configs) != set(keys) or set(accounts) != set(keys)
                or any(row['execution_status'] != 'SUCCEEDED' or row['publication_status'] != 'PUBLISHED'
                       for row in accounts.values())):
            raise ValueError('formal account publication differs from the fixed experiment: ' + name)
        configured_pairs, comparisons_sha = local_json(work / 'protocols/comparisons.json')
        pairs = tuple(dict.fromkeys(((key, CONTROL_ID) for key in keys)))
        pairs = tuple(dict.fromkeys((*pairs, *(tuple(pair) for pair in configured_pairs))))
        expected_names = {subject + '_vs_' + control for subject, control in pairs}
        coverage = value['public_audit_coverage']
        if (set(value['diagnostics']) != expected_names
                or value['new_configurations'] != len(keys) or value['formal_requests'] != len(keys)
                or value['account_replays'] != 2 * len(keys) or value['public_diagnoses'] != len(pairs)
                or coverage['status'] != 'PASS' or set(coverage['required_accounts']) != expected
                or set(coverage['diagnoses_by_account']) != expected
                or any(not coverage['diagnoses_by_account'][key] for key in expected)
                or any(item['status'] != 'COMPUTED' or item['sources_match'] is not True
                       for item in value['diagnostics'].values())):
            raise ValueError('completed public diagnosis coverage is required: ' + name)
        for key in expected:
            valid = {subject + '_vs_' + control for subject, control in pairs if key in (subject, control)}
            if not set(coverage['diagnoses_by_account'][key]) <= valid:
                raise ValueError('account diagnosis coverage has a different subject or control: ' + key)
        for key, encoded in value['source_accounts'].items():
            ref = EvidenceRef.from_dict(encoded)
            if ref.experiment != origins[key] or (key in references and references[key] != ref):
                raise ValueError('repeated control/account reference differs: ' + key)
            references[key] = ref
        analyses[name] = value
        source_files[name] = {'path': path.relative_to(ROOT).as_posix(), 'sha256': analysis_sha,
            'analysis_source_sha256': source_sha, 'accounts_manifest_sha256': accounts_sha,
            'comparisons_sha256': comparisons_sha,
            'diagnoses': {label: item['evidence'] for label, item in value['diagnostics'].items()}}
    return analyses, source_files, references, origins


def authenticated_points():
    analyses, source_files, references, origins = analysis_inputs()
    baseline_rows, baseline_refs = read_account_views(CONTROL.resolve(ROOT), CONTROL, (CONTROL_ID,))
    baseline = baseline_rows[CONTROL_ID]
    if baseline_refs[CONTROL_ID] != references[CONTROL_ID]:
        raise ValueError('C0013 analysis reference differs from the original manifest')
    request = baseline['request']
    zone = ZoneInfo('America/New_York')
    if (request['fee_rate'] != .001 or request['initial_cash'] != 100000.
            or request['specification_hash'] != SPEC.fingerprint
            or request['drawdown_basis'] != 'BAR_CLOSE' or request['frequency_window_days'] != 60
            or request['instrument'] != {'market': 'US', 'asset_class': 'STOCK', 'symbol': 'LITE'}
            or request['history_start'] != '2018-11-01'
            or datetime.fromisoformat(request['window']['start'].replace('Z', '+00:00'))
                != datetime(2019, 1, 2, 9, 30, tzinfo=zone)
            or datetime.fromisoformat(request['window']['end'].replace('Z', '+00:00'))
                != datetime(2025, 12, 31, 16, tzinfo=zone)):
        raise ValueError('plot title or goals would not match the fixed economic contract')
    summaries, identities = {}, {}
    # Retain only one new account at a time; baseline is the common exact control.
    for key, origin in origins.items():
        if key == CONTROL_ID:
            payload, actual = baseline, baseline_refs[CONTROL_ID]
        else:
            rows, refs = read_account_views(origin.resolve(ROOT), origin, (key,))
            payload, actual = rows[key], refs[key]
        if actual != references[key]:
            raise ValueError('analysis did not use the original authenticated account: ' + key)
        verify_contracts({CONTROL_ID: baseline, key: payload})
        verify_hold_path({CONTROL_ID: baseline, key: payload})
        own = summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])
        benchmark = summarize_run(payload['runs']['buy_hold'], payload['request']['initial_cash'])
        checks = goals(own, benchmark)
        expected = {'candidate': own, 'benchmark': benchmark, 'goals': checks,
                    'all_goals_met': all(checks.values())}
        for name, analysis in analyses.items():
            if key in analysis['summaries'] and analysis['summaries'][key] != expected:
                raise ValueError('analysis metrics differ from the published account: ' + name + '/' + key)
        summaries[key] = expected
        identities[key] = {'evaluation_identity': payload['evaluation_identity'],
                           'evaluation_id': payload['evaluation_id'], 'evidence': actual.to_dict()}
        if key != CONTROL_ID:
            del payload, rows, refs
    points = {key: {'annualized_return': row['candidate']['annualized_return'],
                    'bar_max_drawdown': row['candidate']['bar_max_drawdown']}
              for key, row in summaries.items()}
    benchmark = summaries[CONTROL_ID]['benchmark']
    points['BUY_HOLD'] = {field: benchmark[field] for field in ('annualized_return', 'bar_max_drawdown')}
    for key, point in points.items():
        if (any(type(number) not in (float, int) or not math.isfinite(number) for number in point.values())
                or not 0 <= point['bar_max_drawdown'] <= 1):
            raise ValueError('nonfinite or invalid plotting metrics: ' + key)
    targets = {'absolute_drawdown': .25, 'relative_drawdown': .8 * benchmark['bar_max_drawdown'],
               'annualized_return': 1.5 * benchmark['annualized_return'] if benchmark['annualized_return'] > 0 else 0.,
               'annualized_comparison': '>=' if benchmark['annualized_return'] > 0 else '>'}
    manifest = {'schema': 's017-return-drawdown-panel-sources/v1', 'status': 'PASS',
        'experiments': list(EXPERIMENTS), 'analyses': source_files, 'accounts': identities,
        'benchmark': {'source_candidate': CONTROL_ID, 'run': 'buy_hold',
                      'evidence': references[CONTROL_ID].to_dict()},
        'points': points, 'targets': targets,
        'economic_contract': {field: request[field] for field in ECONOMIC_FIELDS},
        'primary_inputs': {product: baseline['data'][product] for product in PRIMARY},
        'contract_checks': 'Exact economic fields, primary four product metadata/hashes and embedded BH paths match C0013.',
        'metric_checks': 'Every summary, including controls repeated across experiments, equals the authenticated account-derived summary.',
        'audit_scope': 'Presentation identity and summary checks only; each completed analysis retains COMPUTED public diagnoses. No new replay, diagnosis or economic audit.',
        'limitations': ['Economic two-dimensional view; original frequency goals remain separate.',
            'No positional score, automatic selection or qualification.',
            'Repeatedly seen development data and adaptive designs; not independent validation.'],
        'helpers': {name: digest((WORK / 'src' / name).read_bytes())
                    for name in ('publish.py', 'analyze.py', 'run.py')}}
    return points, targets, manifest


def render(points, targets, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    plt.rcParams['font.family'] = 'DejaVu Sans'
    fig, ax = plt.subplots(figsize=(13, 8))
    fig.subplots_adjust(left=.09, right=.77, top=.82, bottom=.18)
    offsets = {'C0036': (-10, -22), 'C0037': (10, 12), 'C0038': (-12, 14),
        'C0039': (12, -22), 'C0040': (-12, 12), 'C0041': (12, 16),
        'C0042': (-12, -24), 'C0043': (12, 12), 'C0044': (12, -22), 'C0045': (12, -24),
        'C0013': (-12, 14), 'BUY_HOLD': (12, 14)}
    for label, (keys, color) in GROUPS.items():
        ax.scatter([points[key]['bar_max_drawdown'] for key in keys],
                   [points[key]['annualized_return'] for key in keys],
                   s=65, color=color, edgecolors='white', linewidths=.8, label=label, zorder=4)
    for key, marker, color, size, label in (
        ('C0013', 'D', '#20252A', 105, 'C0013: retained slow trend'),
        ('BUY_HOLD', '*', '#B78608', 230, 'Buy and hold: same contract')):
        point = points[key]
        ax.scatter(point['bar_max_drawdown'], point['annualized_return'], s=size, marker=marker,
                   color=color, edgecolors='white', linewidths=.9, label=label, zorder=5)
    for key, point in points.items():
        dx, dy = offsets[key]
        ax.annotate('BH' if key == 'BUY_HOLD' else key,
            (point['bar_max_drawdown'], point['annualized_return']), xytext=(dx, dy),
            textcoords='offset points', ha='left' if dx > 0 else 'right', fontsize=9,
            fontweight='bold' if key in ('C0013', 'BUY_HOLD') else 'normal',
            arrowprops={'arrowstyle': '-', 'color': '#7B838B', 'lw': .65}, zorder=6)
    ax.axvline(targets['absolute_drawdown'], color='#6A6E73', linestyle='--', lw=1.1,
               label='Absolute DD limit: 25%')
    ax.axvline(targets['relative_drawdown'], color='#989DA3', linestyle=':', lw=1.1,
               label='Relative DD limit: 0.8 x BH')
    return_label = ('Return target: 1.5 x BH' if targets['annualized_comparison'] == '>='
                    else 'Return target: strictly above 0')
    ax.axhline(targets['annualized_return'], color='#446471', linestyle='--', lw=1.1,
               label=return_label)
    annual = [point['annualized_return'] for point in points.values()] + [targets['annualized_return'], 0.]
    span = max(max(annual) - min(annual), .1)
    ax.set_ylim(min(annual) - .14 * span, max(annual) + .14 * span)
    ax.set_xlim(0, min(1.05, max(point['bar_max_drawdown'] for point in points.values()) + .12))
    ax.xaxis.set_major_formatter(PercentFormatter(1.))
    ax.yaxis.set_major_formatter(PercentFormatter(1.))
    ax.set_xlabel('Maximum drawdown (BAR_CLOSE, positive magnitude)', labelpad=10)
    ax.set_ylabel('Net annualized return', labelpad=10)
    ax.grid(alpha=.19)
    ax.set_axisbelow(True)
    ax.legend(loc='upper left', bbox_to_anchor=(1.015, 1.), fontsize=8.3,
              frameon=False, labelspacing=1.15)
    fig.suptitle('LITE 2019-2025 | 0.1% per side | +1% fixed buy-limit premium',
                 fontsize=14, fontweight='bold', y=.96)
    fig.text(.09, .895, 'Economic dimensions only. Frequency goals are reviewed separately; no positional score.',
             fontsize=10, color='#424B52')
    fig.text(.09, .07, 'Ten new prototypes, retained C0013 and the same-contract benchmark.\n'
             'Repeatedly seen development data; adaptive designs; not independent validation.',
             fontsize=9, color='#545E66', linespacing=1.5)
    fig.savefig(destination, dpi=180, facecolor='white')
    plt.close(fig)


def main():
    source_bytes = Path(__file__).read_bytes()
    points, targets, manifest = authenticated_points()
    # Recheck analysis/helper bytes before writing so the figure has a pinned input set.
    for row in manifest['analyses'].values():
        if digest((ROOT / row['path']).read_bytes()) != row['sha256']:
            raise ValueError('analysis changed during plotting input verification')
    for name, expected in manifest['helpers'].items():
        if digest((WORK / 'src' / name).read_bytes()) != expected:
            raise ValueError('presentation helper changed during verification')
    output = WORK / 'others/return_drawdown_panel.png'
    output.parent.mkdir(parents=True, exist_ok=True)
    render(points, targets, output)
    manifest['script'] = {'path': Path(__file__).relative_to(ROOT).as_posix(), 'sha256': digest(source_bytes)}
    manifest['image'] = {'path': output.relative_to(ROOT).as_posix(), 'sha256': digest(output.read_bytes())}
    (WORK / 'others/return_drawdown_panel_sources.json').write_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))
    print('PANEL_PLOT_VERIFIED', output.relative_to(ROOT).as_posix(), flush=True)


if __name__ == '__main__':
    main()
