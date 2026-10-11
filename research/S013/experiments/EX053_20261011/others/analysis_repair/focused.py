"""Pure fake-ledger fixtures and AST conservation; no account reads."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS
import ast
import importlib.util
import json

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
checks = []
refusals = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


original = load('original_reference', HERE / 'original_analysis_reference.py')
corrected = load('corrected_reference', HERE / 'analysis_reference_corrected.py')


def check(name, condition):
    assert condition, name
    checks.append(name)


def refuse(name, fn):
    try:
        fn()
    except (AssertionError, ValueError, KeyError):
        refusals.append(name)
    else:
        raise AssertionError(name)


before = ast.parse((HERE / 'original_analysis_reference.py').read_text(encoding='utf-8'))
after = ast.parse((HERE / 'analysis_reference_corrected.py').read_text(encoding='utf-8'))


class RemoveAddedEnum(ast.NodeTransformer):
    count = 0

    def visit_Tuple(self, node):
        if any(isinstance(item, ast.Constant) and item.value == 'RAW_BEAR_TIME_BELOW_CLOSE' for item in node.elts):
            assert any(isinstance(item, ast.Constant) and item.value == 'MEAN_BEAR_TIME_BELOW_CLOSE' for item in node.elts)
            node.elts = [item for item in node.elts if not (isinstance(item, ast.Constant) and item.value == 'RAW_BEAR_TIME_BELOW_CLOSE')]
            self.count += 1
        return self.generic_visit(node)


remove = RemoveAddedEnum()
reversed_ast = remove.visit(after)
check('only one existing classification tuple amended', remove.count == 1)
check('whole module AST identical after deleting added enum', ast.dump(before, include_attributes=False) == ast.dump(reversed_ast, include_attributes=False))


def fixture(mechanism='RAW_BEAR_TIME_BELOW_CLOSE'):
    dates = pd.bdate_range('2020-01-02', '2026-09-30')
    # Exactly the original fixed evaluation length/endpoints, synthetic calendar.
    dates = dates[[*range(1635), len(dates) - 1]]
    equity = 1_000_000 * np.power(1.0001, np.arange(1, 1637))
    bhequity = 1_000_000 * np.power(1.00004, np.arange(1, 1637))
    own = pd.DataFrame({'date': dates, 'equity': equity, 'quantity': 0})
    bh = pd.DataFrame({'date': dates, 'equity': bhequity, 'quantity': 0})
    frame = pd.DataFrame({'signal_date': dates, 'confirmation_opportunity': False,
        'confirmation_score': 0., 'confirmation_pass': True, 'regime': 'bear',
        'entry_signal_close': 100., 'previous_signal_close': 100., 'entry_signal_open': 99.,
        'entry_direction_up': False, 'last_exit_reason': None, 'last_exit_route': None,
        'last_exit_category': None, 'entry_direction_gate_applies': False,
        'signal_reason': 'flat'})
    # Category, route/reason and equality fixtures on genuine synthetic flat opportunities.
    for i, (category, rawroute, exroute, reason, rise, passed, opp) in enumerate([
        ('BELOW', 'bear', 'bear', 'time', False, True, True),
        ('BELOW', 'bear', 'bear', 'time', True, True, True),
        ('EQUAL', 'bear', 'bear', 'time', False, True, True),
        ('ABOVE', 'bear', 'bear', 'time', False, True, True),
        ('BELOW', 'bull', 'bear', 'time', False, True, True),
        ('BELOW', 'bear', 'bear', 'range', False, True, True),
        ('BELOW', 'bear', 'bull', 'time', False, True, True),
        ('BELOW', 'bear', 'bear', 'time', False, True, False),
        ('BELOW', 'bear', 'bear', 'time', True, False, True),
        ('BELOW', 'bear', 'bear', 'time', False, False, True),
    ]):
        gate = opp and rawroute == 'bear' and exroute == 'bear' and reason == 'time' and category == 'BELOW'
        signal_reason = ('flat' if not opp else 'entry_direction_rejected' if gate and not rise
                         else 'entry' if passed else 'confirmation_rejected')
        frame.loc[i, ['confirmation_opportunity', 'regime', 'last_exit_reason', 'last_exit_route',
                      'last_exit_category', 'entry_direction_gate_applies', 'entry_direction_up',
                      'confirmation_score', 'confirmation_pass', 'entry_signal_close', 'signal_reason']] = [
            opp, rawroute, reason, exroute, category, gate, rise, 0. if passed else -.4,
            passed, 101. if rise else 100., signal_reason]
    execution = NS(account_daily=own, trades=pd.DataFrame({'status': ['CLOSED'] * 3}), decisions=frame,
                   fills=pd.DataFrame({'side': ['BUY'], 'fees': [10.]}), orders=pd.DataFrame({'status': ['FILLED']}))
    bexecution = NS(account_daily=bh)
    run = NS(execution=execution, buyhold=NS(account_daily=bh, execution=bexecution),
             observation=NS(net_cagr=float((equity[-1] / 1_000_000) ** (252 / 1636) - 1)))
    result = NS(runs=[run], request_hash='synthetic-request', result_hash='synthetic-result')
    bound = NS(input_bindings={'synthetic': NS(to_dict=lambda: {'synthetic': True})})

    def annual_paths(account):
        return [{'year': year, 'account_return': row['return']} for year, row in original.annual(account).items()]

    paths = {'cycles': [{}, {}, {}], 'annual_account': annual_paths(own)}
    ledger = NS(inspect_run=lambda run: deepcopy(paths), verify_account=lambda bound, result: {'status': 'SYNTHETIC'},
                annual_account=lambda execution: (annual_paths(execution.account_daily), None))
    config = {'mode': 'M1', 'mechanism': mechanism, 'payload': {'parameters': {'confirmation': {'threshold': -.2}}},
              'index': 0, 'background': 'SYNTHETIC', 'candidate_id': 'SYNTHETIC',
              'content_sha256': 'synthetic-content', 'existing_identity': None}
    return bound, result, config, ledger


args = fixture()
row, frame = corrected.summarize(*args)
check('classified RAW synthetic summary passes', row['gate_counts']['state_rejected_opportunities'] == 2)
check('score only rejection after state gate', row['gate_counts']['rejected_opportunities'] == 1)
check('equal and above categories do not gate', not frame.entry_direction_gate_applies.iloc[2:4].any())
check('wrong current route does not gate', not frame.entry_direction_gate_applies.iloc[4])
check('other exit reason does not gate', not frame.entry_direction_gate_applies.iloc[5])
check('wrong held exit route does not gate', not frame.entry_direction_gate_applies.iloc[6])
check('failed original eligibility does not gate', not frame.entry_direction_gate_applies.iloc[7])
refuse('original omission reproduced synthetic only', lambda: original.summarize(*fixture()))
old_args = fixture('MEAN_BEAR_TIME_BELOW_CLOSE')
old_row, old_frame = original.summarize(*old_args)
new_row, new_frame = corrected.summarize(*old_args)
check('existing MEAN summary economic and diagnostics exact', old_row == new_row)
pd.testing.assert_frame_equal(old_frame, new_frame, check_exact=True)
checks.append('existing MEAN returned frame exact')
check('RAW addition preserves all economic calculations', row == new_row)
for name, value in [('entry_direction_up', True), ('entry_direction_gate_applies', False),
                    ('last_exit_category', 'COUNTERFEIT'), ('confirmation_pass', False),
                    ('signal_reason', 'entry')]:
    args = fixture()
    args[1].runs[0].execution.decisions.loc[0, name] = value
    refuse('counterfeit ' + name, lambda args=args: corrected.summarize(*args))
args = fixture()
args[1].runs[0].execution.decisions.loc[8, 'signal_reason'] = 'entry_direction_rejected'
refuse('score refusal cannot become direction refusal', lambda: corrected.summarize(*args))
args = fixture()
args[1].runs[0].execution.decisions.loc[9, 'signal_reason'] = 'confirmation_rejected'
refuse('direction refusal priority before score remains', lambda: corrected.summarize(*args))

proof = {'status': 'PASS', 'checks': checks, 'check_count': len(checks), 'refusals': refusals,
         'refusal_count': len(refusals), 'ast_added_literal_only': True,
         'source_sha256': sha256((HERE / 'analysis_reference_corrected.py').read_bytes()).hexdigest(),
         'wrapper_sha256': sha256((HERE / 'run_analysis_corrected.py').read_bytes()).hexdigest(),
         'native_account_reads': 0, 'market_reads': 0, 'new_evaluations': 0,
         'financial_calls': [], 'qualification_changes': 0}
(HERE / 'focused.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(proof, indent=2))
