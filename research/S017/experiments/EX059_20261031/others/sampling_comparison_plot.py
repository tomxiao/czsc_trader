import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file() and (p/'research/S017').is_dir())
parser = argparse.ArgumentParser()
parser.add_argument('--include-single-joint', action='store_true')
args = parser.parse_args()
OUT = ROOT / '.tmp/s017-sampling-comparison'
OUT.mkdir(parents=True, exist_ok=True)
os.environ['MPLCONFIGDIR'] = str(OUT / 'matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def read(name):
    work = ROOT / 'research/S017/experiments' / name / 'others'
    path = work / 'search_trials.json'
    publication = json.loads((work / 'search_publication.json').read_bytes())
    ref = publication['family']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ref['sha256']
    result = json.loads(path.read_bytes())
    assert result['status'] == 'COMPLETED_PARAMETER_SEARCH'
    return result, ref

old, old_ref = read('EX057_20261031')
new, new_ref = read('EX058_20261031')
third, third_ref = read('EX059_20261031') if args.include_single_joint else (None, None)
plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei'], 'axes.unicode_minus': False})
fig, ax = plt.subplots(figsize=(10, 7), layout='constrained')
groups = [
    ('复用参照', old['warm_imported_results'], '#455466', 'D'),
    ('固定退出锚点及原匹配', [r for r in old['unique_results'] if r['proposal_kind'] != 'MODEL_TPE'], '#8b95a4', '^'),
    ('原五约束采样', [r for r in old['unique_results'] if r['proposal_kind'] == 'MODEL_TPE'], '#d88935', 'o'),
    ('四约束双目标采样', [r for r in new['unique_results'] if r['proposal_kind']=='MODEL_TPE'], '#2879ad', 'o'),
    ('四约束必要匹配', [r for r in new['unique_results'] if r['proposal_kind']!='MODEL_TPE'], '#2879ad', 's'),
]
if third is not None:
    groups.extend([
        ('收益目标联合采样', [r for r in third['unique_results'] if r['proposal_kind']=='MODEL_TPE'], '#7751aa', 'o'),
        ('联合采样必要匹配', [r for r in third['unique_results'] if r['proposal_kind']!='MODEL_TPE'], '#7751aa', 's'),
    ])
points = old['warm_imported_results'] + old['unique_results'] + new['unique_results'] + ([] if third is None else third['unique_results'])
seen = set()
for label, rows, color, marker in groups:
    rows = [r for r in rows if r['status'] == 'SUCCEEDED']
    for complete in (True, False):
        subset = [r for r in rows if all(r['goals'][k] for k in ('frequency_median', 'frequency_coverage')) == complete]
        if not subset:
            continue
        ax.scatter([100*r['metrics']['bar_max_drawdown'] for r in subset],
                   [100*r['metrics']['annualized_return'] for r in subset],
                   color=color if complete else 'none', edgecolor=color, marker=marker,
                   s=43, alpha=.83, linewidth=.9,
                   label=f'{label}（{len(rows)}点）' if label not in seen else None)
        seen.add(label)
base = {r['candidate_id']: r for r in old['warm_imported_results']}
for cid, text, marker in [('C0220', 'C179 静态参照', 'D'), ('C0222', 'C222 背景参照', '*')]:
    row = base[cid]
    x, y = 100*row['metrics']['bar_max_drawdown'], 100*row['metrics']['annualized_return']
    ax.scatter([x], [y], color='#202c39', marker=marker, s=105, zorder=5)
    ax.annotate(text, (x, y), xytext=(8, -15 if cid=='C0220' else 10), textcoords='offset points', fontsize=9)
target = 150*old['warm_imported_results'][0]['benchmark_metrics']['annualized_return']
ax.axvline(25, color='#578c68', linestyle='--', linewidth=1.3)
ax.axhline(target, color='#578c68', linestyle='--', linewidth=1.3, label='原收益 / 绝对回撤门槛')
qualified = [r for r in points if r['status']=='SUCCEEDED' and r['all_goals_met']]
if qualified:
    ax.scatter([100*r['metrics']['bar_max_drawdown'] for r in qualified],
               [100*r['metrics']['annualized_return'] for r in qualified],
               s=150, facecolor='none', edgecolor='#188347', linewidth=1.6, label='五门同时通过')
pool = [r for r in points if r['status']=='SUCCEEDED' and all(v for k,v in r['goals'].items() if k!='annualized_return')]
best = sorted(pool, key=lambda r:(-r['metrics']['annualized_return'],r['candidate_id']))[0]
if best['candidate_id'] not in ('C0220', 'C0222'):
    x, y = 100*best['metrics']['bar_max_drawdown'], 100*best['metrics']['annualized_return']
    ax.annotate(f"{best['candidate_id']}：{y:.2f}% / {x:.2f}%", (x,y), xytext=(8,10), textcoords='offset points', fontsize=9)
highest = sorted([r for r in points if r['status']=='SUCCEEDED'], key=lambda r:(-r['metrics']['annualized_return'],r['candidate_id']))[0]
if highest['candidate_id'] != best['candidate_id']:
    x, y = 100*highest['metrics']['bar_max_drawdown'], 100*highest['metrics']['annualized_return']
    ax.annotate(f"{highest['candidate_id']}：{y:.2f}% / {x:.2f}%", (x,y), xytext=(-12,-18),
                textcoords='offset points', horizontalalignment='right', fontsize=9)
ax.set(xlabel='最大回撤（BAR_CLOSE，%）', ylabel='扣费后年化收益（%）',
       title='同一策略参数族：原采样与修正采样的实际评价')
ax.grid(alpha=.17)
ax.legend(loc='best', fontsize=9)
fig.supxlabel('2024—2025重复训练；实心为两项频率均通过，空心为频率未全通过。复用与相关配置不是独立样本。', fontsize=9)
path = OUT / 'sampling_comparison.png'
fig.savefig(path, dpi=180)
plt.close(fig)
provenance = {'status':'GENERATED_PENDING_VISUAL_QA', 'old_family':old_ref, 'new_family':new_ref, 'single_joint_family':third_ref,
              'include_single_joint':args.include_single_joint,
              'strategy_source_sha256':old['source_sha256'], 'economic_qualification_unchanged':True,
              'matplotlib_version':matplotlib.__version__, 'rows_plotted':len(points), 'joint_count':len(qualified), 'figure_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
(OUT/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(provenance,ensure_ascii=False))
