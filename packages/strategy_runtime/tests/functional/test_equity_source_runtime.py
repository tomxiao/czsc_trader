"""One source snapshot and module namespace per replay account."""
import builtins
from dataclasses import replace
import io
import os
from pathlib import Path
import sys

import pandas as pd
import pytest
from strategy_runtime import PreparedReplay, ReplayFailure, equity_source_hash, run_replay
from test_equity_v3_kernel import SOURCE, candidate, inputs


def replay(value, bars, constraints, executor):
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    return run_replay(prepared, value, executor,
        start=bars.BarStart.iloc[1].to_pydatetime(), end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)


def set_source(value, source, files=('strategy.py',)):
    (value.source_root / 'strategy.py').write_text(source, encoding='utf-8')
    return replace(value, definition=replace(value.definition, source_files=files,
        source_sha256=equity_source_hash(value.source_root, files)))


def multifile_candidate(root):
    value = candidate(root)
    source = ('import sys\nimport types\n'
        'sys.modules[__package__ + ".manual"] = types.ModuleType(__package__ + ".manual")\n'
        'sys.modules[__package__ + ".manual.deep"] = types.ModuleType(__package__ + ".manual.deep")\n'
        + SOURCE.replace('def step(ctx, state):', 'counter = 0\ndef step(ctx, state):'))
    source = source.replace('    close = ctx.features',
        '    global counter\n    counter += 1\n'
        '    expected_threshold, helper_count = 10., 0\n'
        '    if counter > 1:\n'
        '        from .rules import threshold\n'
        '        expected_threshold, helper_count = threshold()\n'
        '    close = ctx.features')
    source = source.replace('close >= 10.', 'close >= expected_threshold')
    source = source.replace('facts={"held":held,',
        'facts={"module_count":counter,"helper_count":helper_count,"held":held,')
    (root / 'rules').mkdir()
    (root / 'rules/__init__.py').write_text('from .levels import threshold\n', encoding='utf-8')
    (root / 'rules/levels.py').write_text(
        'COUNT = 0\nTHRESHOLD = 10.\ndef threshold():\n'
        ' global COUNT\n COUNT += 1\n return THRESHOLD, COUNT\n', encoding='utf-8')
    return set_source(value, source, ('rules/__init__.py', 'rules/levels.py', 'strategy.py'))


def namespace_state():
    return {name for name in sys.modules if name.startswith('_equity_')}, tuple(sys.meta_path)


def assert_counts(outcome, expected_bytes, count):
    assert outcome.statistics.decisions == count
    assert outcome.statistics.source_checks == 0
    assert outcome.statistics.source_bytes_read == expected_bytes
    assert outcome.statistics.module_loads == 1
    facts = [{item['key']: item['text'] for item in explanation['basis']}
             for explanation in outcome.execution_result.decisions.explanation]
    assert [int(row['module_count']) for row in facts] == list(range(1, count + 1))
    assert [int(row['helper_count']) for row in facts] == list(range(count))


def test_module_globals_persist_within_account_and_are_isolated_between_accounts(tmp_path):
    value = multifile_candidate(tmp_path / 'source')
    expected_bytes = sum(len((value.source_root / name).read_bytes()) for name in value.definition.source_files)
    existing = namespace_state()
    outcomes = []
    for _ in range(2):
        bars, constraints, executor = inputs(value)
        outcome = replay(value, bars, constraints, executor)
        assert_counts(outcome, expected_bytes, len(bars) - 1)
        assert namespace_state() == existing
        outcomes.append(outcome)
    pd.testing.assert_frame_equal(outcomes[0].execution_result.decisions,
                                  outcomes[1].execution_result.decisions, check_exact=True)


@pytest.mark.parametrize('change', ('modify', 'delete'))
def test_startup_snapshot_survives_source_changes_and_late_import_without_source_io(tmp_path, monkeypatch, change):
    value = multifile_candidate(tmp_path / 'source')
    bars, constraints, reference_executor = inputs(value)
    original = replay(value, bars, constraints, reference_executor)
    _, _, executor = inputs(value)
    expected_bytes = sum(len((value.source_root / name).read_bytes()) for name in value.definition.source_files)
    execute = executor.execute
    existing = namespace_state()
    root = os.path.normcase(os.path.abspath(value.source_root))

    def guarded(original_call):
        def call(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                normalized = os.path.normcase(os.path.abspath(os.fsdecode(path)))
                if normalized == root or normalized.startswith(root + os.sep):
                    raise AssertionError('hot loop accessed source filesystem: ' + normalized)
            return original_call(path, *args, **kwargs)
        return call

    def change_after_first(*args, **kwargs):
        result = execute(*args, **kwargs)
        if result.revision == 1:
            for name in value.definition.source_files:
                path = value.source_root / name
                if change == 'delete':
                    path.unlink()
                else:
                    path.write_text('raise RuntimeError("changed source must not be loaded")\n', encoding='utf-8')
            # The relative helper has not been imported yet. Neither it nor the
            # entry source may be read/stat'ed in later decisions or cleanup.
            monkeypatch.setattr(builtins, 'open', guarded(builtins.open))
            monkeypatch.setattr(io, 'open', guarded(io.open))
            monkeypatch.setattr(os, 'stat', guarded(os.stat))
            monkeypatch.setattr(Path, 'read_bytes', guarded(Path.read_bytes))
        return result

    monkeypatch.setattr(executor, 'execute', change_after_first)
    outcome = replay(value, bars, constraints, executor)
    assert_counts(outcome, expected_bytes, len(bars) - 1)
    for name in ('decisions', 'orders', 'fills', 'corporate_action_entries', 'account_points', 'account_daily', 'trades'):
        pd.testing.assert_frame_equal(getattr(original.execution_result, name),
                                      getattr(outcome.execution_result, name), check_exact=True)
    assert namespace_state() == existing
    monkeypatch.undo()


@pytest.mark.parametrize('failure', ('load', 'step'))
def test_namespace_and_import_finder_cleanup_after_failure(tmp_path, failure):
    value = candidate(tmp_path / 'source')
    register = ('namespace = __package__\n'
        'sys.modules[namespace + ".manual"] = types.ModuleType(namespace + ".manual")\n'
        'sys.modules[namespace + ".manual.deep"] = types.ModuleType(namespace + ".manual.deep")\n')
    source = 'import sys\nimport types\n' + register
    if failure == 'load':
        source += 'raise RuntimeError("synthetic module load failure")\n'
    source += SOURCE
    if failure == 'step':
        source = source.replace('    close = ctx.features',
            '    raise RuntimeError("synthetic step failure")\n    close = ctx.features')
    value = set_source(value, source)
    bars, constraints, executor = inputs(value)
    existing = namespace_state()
    expected = ReplayFailure if failure == 'step' else RuntimeError
    with pytest.raises(expected, match='synthetic .* failure'):
        replay(value, bars, constraints, executor)
    assert executor.revision == 0
    assert namespace_state() == existing


def test_replay_loads_once_without_repeating_source_identity_verification(tmp_path, monkeypatch):
    from strategy_runtime import equity_definition

    value = candidate(tmp_path / 'source')
    bars, constraints, executor = inputs(value)
    path = value.source_root / 'strategy.py'
    path.write_text(SOURCE + '\n# edited after preparation\n', encoding='utf-8')
    expected_bytes = len(path.read_bytes())

    def forbidden(*args, **kwargs):
        raise AssertionError('replay repeated source identity verification')

    monkeypatch.setattr(type(value), 'verify', forbidden)
    monkeypatch.setattr(equity_definition, 'equity_source_hash', forbidden)
    monkeypatch.setattr(equity_definition, '_read_equity_sources', forbidden)
    existing = namespace_state()
    outcome = replay(value, bars, constraints, executor)
    assert outcome.statistics.source_checks == 0
    assert outcome.statistics.source_bytes_read == expected_bytes
    assert outcome.statistics.module_loads == 1
    assert executor.revision == len(bars) - 1
    assert namespace_state() == existing
