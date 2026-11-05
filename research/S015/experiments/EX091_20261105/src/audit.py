"""Read saved accounts and public typed contracts; do not replay or modify accounts."""
from dataclasses import fields
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
from pathlib import Path
import inspect
import json

import pandas as pd
from czsc_trader.research_tools import EvidenceRef, EquityEvaluationRequest
from strategy_runtime.account_strategy import AccountStepContext
from strategy_runtime import account_replay

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    output = HOME / 'others/fee_contract_audit.json'
    assert not output.exists(), 'completed audit is immutable'
    raw = pd.read_parquet(ROOT / 'research/S015/experiments/EX087_20261105/others/raw_complete.parquet')
    prior = Decimal(str(raw.loc[pd.to_datetime(raw.Date).dt.date.astype(str) == '2025-01-09', 'Close'].iloc[0]))
    limit = (prior * Decimal('1.01') / Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.001')
    rows = read(ROOT / 'research/S015/experiments/EX082_20261025/others/results.json')['rows']
    accounts = []
    for row in rows:
        ref = EvidenceRef.from_dict(row['evidence'])
        content = ref.resolve(ROOT).read_bytes()
        assert sha256(content).hexdigest() == ref.sha256
        account = json.loads(content)['runs'][0]['replay_evidence']
        first = next(d for d in account['decisions'] if d['entry_signal'])
        budget = json.loads(first['entry_cycle_after'])
        fill = account['fills'][0]
        fee = Decimal('.001') if row['scenario_id'] == 'standard' else Decimal('.002')
        expected = int(Decimal(budget['cash_budget']) / (limit * (1 + fee)) / 100) * 100
        assert budget['target_quantity'] == expected == fill['quantity']
        assert first['signal_date'].startswith('2025-01-09')
        accounts.append({'scenario': row['scenario_id'], 'reference': ref.to_dict(),
                         'fee_rate': str(fee), 'raw_reference_close': str(prior),
                         'entry_limit_price': str(limit), 'locked_quantity_formula': expected,
                         'first_entry_decision': first, 'first_fill': fill,
                         'fill_count': len(account['fills'])})
    assert accounts[0]['first_entry_decision']['signal_identity'] == accounts[1]['first_entry_decision']['signal_identity']
    assert accounts[0]['locked_quantity_formula'] == 93800
    assert accounts[1]['locked_quantity_formula'] == 93700
    context_fields = [x.name for x in fields(AccountStepContext)]
    request_fields = [x.name for x in fields(EquityEvaluationRequest)]
    assert 'fee_rate' not in context_fields
    assert 'fee_rate' in request_fields and 'initial_state' not in request_fields
    replay_source = inspect.getsource(account_replay.run_account_v4)
    assert replay_source.index('proposal=candidate.account_step(ctx,state)') < replay_source.index('return plan_account_decision(proposal.decision')
    paths = (
        'packages/strategy_runtime/src/strategy_runtime/account_strategy.py',
        'packages/strategy_runtime/src/strategy_runtime/account_replay.py',
        'packages/strategy_runtime/src/strategy_runtime/execution_rules.py',
        'packages/strategy_runtime/src/strategy_runtime/equity_definition.py',
        'src/czsc_trader/research_tools/equity_evaluation.py',
        'packages/strategy_evaluator/src/strategy_evaluator/research_assessment.py',
        'research/S015/experiments/EX076_20261024/report.md',
        'research/S015/experiments/EX087_20261105/src/strategy.py',
        'research/S015/experiments/EX089_20261105/src/strategy.py',
    )
    payload = {'status': 'CONFIRMED_PUBLIC_CONTEXT_GAP', 'accounts': accounts,
               'account_step_context_fields': context_fields, 'evaluation_request_fields': request_fields,
               'actual_fee_planning_occurs_after_strategy_step': True,
               'source_hashes': {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
               'new_account_replays': 0,
               'scope': 'Original signal_cash_fraction quantity lock under same-candidate fee-only stress; not a claim that all V4 strategies fail stress.'}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status': payload['status'], 'standard_quantity': 93800,
                      'stress_quantity': 93700, 'limit_price': str(limit), 'new_replays': 0}))


if __name__ == '__main__':
    main()
