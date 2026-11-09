"""Verify the S018-v1 explanation revision in isolation against retained inputs."""
# ruff: noqa: E402
from collections import Counter
from dataclasses import replace
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRIOR = HERE.parents[1] / 'experiments/EX069_20261108'
FROZEN = ROOT / 'strategies/S018/releases/v1/src/strategy_runtime'
sys.path.insert(0, str(PRIOR / 'src'))

from czsc_trader.application import RepositoryContext, EquityInspectionReplay
from czsc_trader.application.equity_inspection import replay_account
from dataflows import EquityDataRequest, TimeInterval
from data_inputs import build_data_context
from paper_trading_engine.execution_reference import ExecutionReferenceBinding
from strategy_manager.freeze_contracts import InspectionCoordinate
from strategy_runtime import EquityInputBinding, EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
from test_equivalence import context, fixture


def load_step(name, directory):
    spec = importlib.util.spec_from_file_location(name, directory / 'strategy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.step


def verify_branches():
    old = load_step('s018_original_explanations', FROZEN)
    new = load_step('s018_revised_explanations', HERE / 'src')
    examples = (
        ('wait', 102., 205., 0, False, False, '当日收盘反弹'),
        ('entry', 100., 205., 0, False, False, '连续两个交易日收跌'),
        ('hold_before_add', 103., 205., 2, False, False, '尚未到第 3 个交易日'),
        ('hold_at_confirmation_boundary', 101., 202., 3, False, False, '加仓确认条件尚未满足'),
        ('hold_just_above_exit', 100.5001, 205., 3, False, False, '加仓确认条件尚未满足'),
        ('increase', 101.0001, 202.0001, 3, False, False, '确认条件已满足'),
        ('hold_after_increase', 103., 205., 4, True, False, '延续本轮目标仓位'),
        ('exit_price', 100. * (1+.005), 205., 3, False, False, '未超过退出线'),
        ('exit_time', 103., 205., 5, False, False, '最长持有期'),
        ('exit_remaining', 103., 205., 3, True, True, '仍确认有剩余持仓'),
    )
    verified = {}
    for name, price, sector, held, promoted, exiting, reason in examples:
        candidate, prepared, _, _ = fixture(price=price, sector_price=sector)
        _, inputs, state = context(candidate, prepared, held=held, promoted=promoted, exiting=exiting)
        before, after = old(inputs, state), new(inputs, state)
        assert replace(after, decision=replace(after.decision, explanation=before.decision.explanation)) == before, name
        explanation = after.decision.explanation
        assert reason in explanation.basis[0].text, (name, explanation.basis[0].text)
        assert explanation.case_key == ('long' if after.decision.target else 'flat'), name
        verified[name] = {'target': after.decision.target, **explanation.to_dict()}
    return verified


def economic_value(value, *, normalize):
    """Remove only explanation and implementation-derived IDs from the comparison."""
    if isinstance(value, dict):
        return {key: economic_value(item, normalize=normalize) for key, item in value.items()
                if key != 'explanation'}
    if isinstance(value, list):
        return [economic_value(item, normalize=normalize) for item in value]
    return normalize.get(value, value)


def compare_replay(before, after):
    left, right = before['facts'], after['facts']
    normalize = {after['content_sha256']: before['content_sha256'],
                 'candidate:S018:C9396:' + after['content_sha256']: 'candidate:S018:C9396:' + before['content_sha256']}
    for old, new in zip(left['decisions'], right['decisions'], strict=True):
        assert normalize.setdefault(new['plan']['plan_identity'], old['plan']['plan_identity']) == old['plan']['plan_identity']
    for table, key in (('decisions', 'decision_id'), ('orders', 'order_id'),
                       ('fills', 'fill_id'), ('trades', 'cycle_id'), ('account_points', 'cycle_id')):
        for old, new in zip(left[table], right[table], strict=True):
            old_key, new_key = old[key], new[key]
            assert (old_key is None) == (new_key is None), (table, key)
            if isinstance(new_key, str) and new_key != old_key:
                assert normalize.setdefault(new_key, old_key) == old_key, (table, key)
    for name, rows in right.items():
        actual = economic_value(rows, normalize=normalize)
        expected = economic_value(left[name], normalize={})
        for index, (old_row, new_row) in enumerate(zip(expected, actual, strict=True)):
            differences = {key: (old_row.get(key), new_row.get(key))
                           for key in old_row.keys() | new_row.keys() if old_row.get(key) != new_row.get(key)}
            assert not differences, (name, index, differences)
    # Source/build identity deliberately changes, state and cursor must agree.
    for key in ('revision', 'account', 'cycle', 'event_cursor'):
        assert economic_value(after['final_state'][key], normalize=normalize) == before['final_state'][key], key
    return {name: len(rows) for name, rows in right.items()}


def main():
    tested = verify_branches()
    print(f'Branch and boundary checks passed: {len(tested)}', flush=True)
    version = json.loads((ROOT/'strategies/S018/versions/v1.json').read_text(encoding='utf-8'))
    definition = EquityStrategyDefinition.from_dict(version['strategy_payload']['equity_definition'])
    original = EquityStrategyCandidate('S018', 'C9396', definition, FROZEN)
    source = HERE / 'src'
    revised = replace(original, definition=replace(definition, source_sha256=equity_source_hash(source, ('strategy.py',))),
                      source_root=source)
    original.verify()
    revised.verify()
    repo = RepositoryContext.discover(ROOT)
    research, _, _ = build_data_context(repo, definition.execution_spec)
    binding = EquityInputBinding.from_dict(json.loads((PRIOR/'others/prepared_binding.json').read_text(encoding='utf-8')))
    retained = json.loads((PRIOR/'others/pte_verification.json').read_text(encoding='utf-8'))
    requests = tuple(dict.fromkeys(EquityDataRequest(p.instrument, p.source, p.query) for _, p in binding.request_bindings))
    zone = ZoneInfo('America/New_York')
    replay = EquityInspectionReplay(InspectionCoordinate('MU_DEVELOPMENT', 'STANDARD'), binding, requests,
        TimeInterval(datetime(2023, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone)),
        100000., .001, execution_reference=ExecutionReferenceBinding.from_dict(retained['raw_binding']))
    old = replay_account(original, research.data, replay)
    new = replay_account(revised, research.data, replay)
    counts = compare_replay(old, new)
    decisions = new['facts']['decisions']
    branch_counts = Counter(row['explanation']['judgment'] for row in decisions if row['explanation'])
    summary = {'status': 'PASS', 'original_content': original.content_identity.content_sha256,
               'revised_content': revised.content_identity.content_sha256,
               'counts': counts, 'historical_judgments': branch_counts, 'branch_examples': tested}
    output = ROOT / '.tmp/s018-v1-decision-explanation/result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: val for key, val in summary.items() if key != 'branch_examples'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
