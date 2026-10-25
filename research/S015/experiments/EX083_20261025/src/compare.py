"""Reconcile fresh accounts, chart performance, and preserve complete results."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import os
import zipfile

import run as task

os.environ['MPLCONFIGDIR'] = str(task.ROOT / '.tmp/matplotlib-s015-ex083')
os.environ['MPLBACKEND'] = 'Agg'
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import pandas as pd

from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome, EvidenceRef,
    ExperimentValidationRequest, ExperimentValidationScope,
)

LABELS = ('S011-v1', 'C9700')


def drawdown(frame):
    values = np.r_[100000., frame.equity.to_numpy(float)]
    highs = np.maximum.accumulate(values)
    dd = values / highs - 1
    trough = int(np.argmin(dd))
    peak = int(np.flatnonzero(values[:trough+1] == highs[trough])[-1])
    later = np.flatnonzero(values[trough+1:] >= highs[trough])
    dates = ['INITIAL_CAPITAL', *frame.date.tolist()]
    return {'magnitude': float(-dd[trough]), 'peak': dates[peak], 'trough': dates[trough],
            'recovery': dates[trough + 1 + later[0]] if len(later) else None}


def analyze():
    assert not (task.OUT / 'assessment.json').exists()
    protocol = task.read(task.HOME / 'protocols/comparison.json')
    assert task.identities() == protocol['identities']
    stats, accounts, manifests, hashes, monthly = {}, {}, {}, {}, {}
    for label in LABELS:
        root = task.ROOT / task.read(task.OUT / f'{label}_run.json')['data']['output_dir']
        account = pd.read_csv(root / 'account_daily.csv', float_precision='round_trip')
        trades = pd.read_csv(root / 'trades.csv', float_precision='round_trip')
        fills = pd.read_csv(root / 'fills.csv', float_precision='round_trip')
        audit = task.read(root / 'audit.json')
        assert audit['status'] == 'PASS' and all(v['status'] == 'PASS' for v in audit['benchmarks'].values())
        metrics = task.read(root / 'metrics.json')['strategy']['metrics']
        manifests[label] = task.read(root / 'manifest.json')
        assert account.date.iloc[0] == '2026-01-05' and account.date.iloc[-1] == '2026-10-21'
        assert account.cash_before.iloc[0] == 100000 and account.quantity_before.iloc[0] == 0
        assert np.allclose(fills.fees, fills.quantity * fills.price * .001, atol=1e-10, rtol=0)
        net = float(account.equity.iloc[-1] / 100000 - 1)
        dd = drawdown(account)
        assert abs(net - metrics['return']) < 1e-12 and abs(dd['magnitude'] + metrics['max_drawdown']) < 1e-12
        closed = trades[trades.status.eq('CLOSED')]
        assert len(closed) == metrics['closed_trades']
        assert float(closed.net_return.gt(0).mean()) == metrics['win_rate']
        prior = account.equity.shift(1, fill_value=100000)
        monthly[label] = []
        for month, group in account.groupby(account.date.str[:7], sort=True):
            start = float(prior.loc[group.index[0]])
            monthly[label].append({'month': month, 'start': group.date.iloc[0], 'end': group.date.iloc[-1],
                                  'sessions': len(group), 'return': float(group.equity.iloc[-1] / start - 1)})
        stats[label] = {'metrics': metrics, 'net_return': net, 'net_profit': float(account.equity.iloc[-1] - 100000),
            'final_equity': float(account.equity.iloc[-1]), 'annualized_return': float((1 + net) ** (252 / len(account)) - 1),
            'sessions': len(account), 'drawdown': dd, 'fees': float(fills.fees.sum()),
            'fill_count': len(fills), 'terminal_quantity': int(account.quantity.iloc[-1]),
            'terminal_cash': float(account.cash.iloc[-1]), 'held_close_sessions': int(account.quantity.gt(0).sum()),
            'held_close_fraction': float(account.quantity.gt(0).mean()), 'audit': 'PASS',
            'first_fill': str(fills.fill_time.iloc[0]), 'last_fill': str(fills.fill_time.iloc[-1]),
            'output_dir': root.relative_to(task.ROOT).as_posix()}
        accounts[label] = account
        hashes[label] = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir()) if p.is_file()}
    assert accounts['S011-v1'].date.equals(accounts['C9700'].date)
    assert manifests['S011-v1']['request'] == manifests['C9700']['request']
    assert manifests['S011-v1']['execution_data'] == manifests['C9700']['execution_data']
    s, c = stats['S011-v1'], stats['C9700']
    result = {'status': 'PASS', 'window': protocol['window'], 'statistics': stats, 'monthly': monthly,
        'return_advantage_pp': 100 * (c['net_return'] - s['net_return']),
        'drawdown_reduction_pp': 100 * (s['drawdown']['magnitude'] - c['drawdown']['magnitude']),
        'final_equity_advantage': c['final_equity'] - s['final_equity'],
        'higher_return_and_lower_drawdown': c['net_return'] > s['net_return'] and c['drawdown']['magnitude'] < s['drawdown']['magnitude'],
        'same_request_and_execution_data': True, 'execution_fingerprint': manifests['C9700']['execution_data']['fingerprint'],
        'source_hashes': hashes, 'strategy_files_unchanged': True,
        'limit': 'New standalone accounts on previously observed history. This requested window does not replace earlier whole-period qualification or authorize freezing.'}
    task.save(task.OUT / 'assessment.json', result)
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    for label, color in zip(LABELS, ('#6B7280', '#117A65'), strict=True):
        account = accounts[label]
        days = pd.to_datetime(account.date)
        axes[0].plot(days, account.equity / 100000, label=label, color=color, linewidth=1.8)
        dd = account.equity / account.equity.cummax().clip(lower=100000) - 1
        axes[1].plot(days, 100 * dd, color=color, linewidth=1.4)
    axes[0].set_title('2026-01-05 至 2026-10-21：两个新账户的净值与回撤', fontproperties=font, loc='left', fontsize=14)
    axes[0].set_ylabel('账户净值（初始=1）', fontproperties=font)
    axes[1].set_ylabel('回撤（%）', fontproperties=font)
    axes[0].legend(frameon=False)
    for axis in axes:
        axis.grid(alpha=.18)
        axis.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(task.HOME / 'comparison.png', dpi=150)
    plt.close(fig)
    print({k: result[k] for k in ('return_advantage_pp', 'drawdown_reduction_pp', 'final_equity_advantage')})
    print(stats)


def publish():
    assert not (task.HOME / 'report_ref.json').exists()
    assessment = task.read(task.OUT / 'assessment.json')
    assert assessment['status'] == 'PASS'
    assert task.identities() == task.read(task.HOME / 'protocols/comparison.json')['identities']
    review = task.read(task.OUT / 'independent_review.json')
    assert review['status'] == 'PASS'
    raw = (task.HOME / 'report.md').read_bytes()
    assert 'Status: COMPLETE' in raw.decode('utf-8')
    ctx, refs, archives = task.context(), [], {}
    for label in LABELS:
        root = task.ROOT / assessment['statistics'][label]['output_dir']
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, expected in assessment['source_hashes'][label].items():
                path = root / name
                assert sha256(path.read_bytes()).hexdigest() == expected
                archive.writestr(name, path.read_bytes())
        ref = publish_evidence(ctx, MaterialEvidenceWrite(task.EX, label + '_complete_backtest', buffer.getvalue(), 'application/zip', 'zip'))
        archives[label] = ref.to_dict()
        refs.append(ref)
    task.save(task.OUT / 'account_archives.json', archives)
    paths = [task.HOME / 'comparison.png', task.HOME / 'notes.md', *sorted((task.HOME / 'src').glob('*.py')),
             *sorted((task.HOME / 'protocols').glob('*.json')), *sorted(task.OUT.glob('*.json'))]
    for path in paths:
        refs.append(task.material(ctx, path))
    refs.extend(EvidenceRef.from_dict(r) for r in task.read(task.OUT / 'prepared.json')['references'])
    report_ref = publish_evidence(ctx, ExperimentReportWrite(task.EX, sha256(raw).hexdigest(), ExperimentOutcome.COMPLETED,
                                                           tuple(dict.fromkeys(refs))))
    validation = validate_experiment(ctx.repository, ExperimentValidationRequest(task.EX, ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status.value == 'PASS'
    task.save(task.OUT / 'publication_receipt.json', {'status': 'PASS', 'report': report_ref.to_dict(),
        'validation': validation.to_dict(), 'archives': archives, 'freeze': 'NOT_REQUESTED'})
    print('COMPARISON_REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('analyze', 'publish'))
    {'analyze': analyze, 'publish': publish}[parser.parse_args().mode]()
