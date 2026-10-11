"""Root pre-account freeze for authorized EX080 realization check."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution as d

work = d.WORK
focused = d.read(work / 'focused_checks.json')
if focused['status'] != 'PASS':
    raise ValueError('Focused synthetic checks not passed')
for name, value in focused['source_sha256'].items():
    if d.digest(work / name) != value:
        raise ValueError('Synthetic source drift')
audit_dir = ROOT / '.tmp/s013-confirm-net-execution-audit'
audit = d.read(audit_dir / 'freeze.json')
for name, value in audit['files'].items():
    if d.digest(audit_dir / name) != value:
        raise ValueError('Independent source drift')
prior_dir = ROOT / 'research/S013/experiments/EX079_20261012/protocols'
if d.read(prior_dir / 'delivery_validation.json') != {'type': 'DeliveryValidation', 'status': 'PASS', 'scope': 'FULL', 'issues': []}:
    raise ValueError('EX079 FULL required')
prior_plan = d.read(prior_dir / 'plan.json')
refs79 = d.read(prior_dir / 'closeout_references.json')
refs66 = d.read(ROOT / 'research/S013/experiments/EX066_20261011/protocols/result_references.json')
budget = d.read(d.public(refs79['budget_receipt.json']))
if (budget['started'], budget['completed'], budget['remaining'], budget['next_allowed']) != (1, 1, 9, 'EX080'):
    raise ValueError('Quota not at slot2')
source_names = [
    '.tmp/s013_confirm_execution.py', '.tmp/s013_confirm_freeze.py',
    '.tmp/s013-confirm-net-execution/confirm_kernel.py',
    '.tmp/s013-confirm-net-execution/confirm_net.py',
    '.tmp/s013-confirm-net-execution/focused_checks.py',
    '.tmp/s013-confirm-net-execution/focused_checks.json',
    '.tmp/s013-confirm-net-execution/scientific_plan.json',
    '.tmp/s013-confirm-net-execution/original_binding_metadata.json',
    '.tmp/s013-confirm-net-execution-audit/audit.py',
    '.tmp/s013-confirm-net-execution-audit/synthetic.py',
    '.tmp/s013-confirm-net-execution-audit/synthetic.json',
    '.tmp/s013-confirm-net-execution-audit/freeze.json',
    'research/S013/experiments/EX058_20261011/src/common.py',
    'research/S013/experiments/EX066_20261011/src/opportunity_statistics.py',
    *['research/S013/experiments/EX074_20261011/src/' + n + '.py' for n in ('economics_reference', 'account_reference', 'execution_links')],
]
plan = {
    'status': 'ROOT_FROZEN_BEFORE_ALLOCATION_PREPARATION_AND_ACCOUNT',
    'question': 'EX079 unchanged confirmation-only positive net forecast under original executable nonoverlapping h4 capital policy',
    'budget_slot': 2, 'new_centre_accounts': 1, 'no_automatic_financial_repeat': True,
    'source_files': {name: d.digest(ROOT / name) for name in source_names},
    'native_cache_sha256': d.digest(ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz'),
    'input_references': {
        'features.csv': refs66['features.csv'], 'net_statistics.json': refs79['statistics.json'],
        'prior_review.json': refs79['root_review.json'], 'prior_budget.json': refs79['budget_receipt.json'],
        'prior_verification.json': refs79['verification.json'],
    },
    'predecessors': prior_plan['predecessors'],
    'continuation_budget_reference': prior_plan['continuation_budget_reference'],
    'report_copy': prior_plan['report_copy'],
    'parameters': {'confirmation_lookback': 120, 'holding_sessions': 4, 'ridge_alpha': 10.0},
    'effective_parameter_domains': d.read(work / 'scientific_plan.json')['effective_parameter_domain_draft']['parameters'],
    'fixed_method': 'Original ADJUSTED120 EQUAL_BLOCKS score; original14 allfinite; annual strictly mature2020+ train ECDF ridge10 with train>=40; score>0;2020cash; h4 policy clock independent of fills; expiry blocks same-signal reentry; full1636 acceptance',
    'causality': 'No future test-count runtime gate; actual historical common14/forecasts/strict positive flags must equal EX079 before account; original exact prepared five requests only; no provider',
    'acceptance': 'Original overall CAGR>=1.5BH positive CAGR, each natural-year DD strictly<BH including prior close, >=4 actual closed/60 full sessions, actual BH-negative year strategy strictlypositive. No gate changed.',
    'stop': 'Any centre gate failure stops this expression; no new32,fee,neighbor,threshold,horizon or ridge rescue. If centre passes, separately prospectively declare standard32 and fee under these pre-frozen effective domains.',
    'diagnostics': 'Three existing-ledger checks permitted;32/fee unavailable until actually run; never claim all five complete or robust objective achieved.',
    'science_limit': 'EX079 weak same seen-pool support with all CIs crossingzero, 2022/2026 selectionmean negative; one executable realization test, not new statistical alpha proof.',
}
for ref in (*plan['input_references'].values(), plan['continuation_budget_reference']):
    d.public(ref)
if (work / 'prospective.json').exists():
    if (ROOT / 'research/S013/experiments/EX080_20261012').exists():
        raise ValueError('Never overwrite allocated prospective plan')
    d.write(work / 'prospective_preallocation_v1.json', d.read(work / 'prospective.json'))
    (work / 'prospective.json').write_text(__import__('json').dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
else:
    d.write(work / 'prospective.json', plan)
print({'status': plan['status'], 'sources': len(source_names), 'slot': 2, 'accounts_before': 0}, flush=True)
