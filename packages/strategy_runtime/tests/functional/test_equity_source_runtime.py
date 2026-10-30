"""Real per-step source changes remain observable with run-scoped readers."""
import os
from dataclasses import replace
import sys

import pandas as pd
import pytest
from strategy_runtime import PreparedReplay, ReplayFailure, equity_source_hash, run_replay
from test_equity_v3_kernel import SOURCE, candidate, inputs


def replay(value, bars, constraints, executor):
    prepared = PreparedReplay.from_frames(bars, constraints, value.definition.feature_graph)
    return run_replay(prepared, value, executor,
        start=bars.BarStart.iloc[1].to_pydatetime(), end=bars.Date.iloc[-1].to_pydatetime(), fee_rate=.001)


def test_source_bytes_change_rejected_even_when_size_and_timestamp_are_preserved(tmp_path, monkeypatch):
    value = candidate(tmp_path/'source')
    bars, constraints, executor = inputs(value)
    path = value.source_root/'strategy.py'
    original, metadata = path.read_bytes(), path.stat()
    execute = executor.execute

    def change_after_first(*args, **kwargs):
        result = execute(*args, **kwargs)
        if result.revision == 1:
            changed = original.replace(b'close >= 10.', b'close >= 11.')
            assert changed != original and len(changed) == len(original)
            path.write_bytes(changed)
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        return result

    monkeypatch.setattr(executor, 'execute', change_after_first)
    with pytest.raises(ReplayFailure, match='source closure changed') as failure:
        replay(value, bars, constraints, executor)
    assert executor.revision == failure.value.committed_state.revision == 1
    assert len(executor.rows['decisions']) == 1


def test_atomic_same_content_replacement_keeps_exact_result_and_namespace_isolation(tmp_path, monkeypatch):
    value = candidate(tmp_path/'source')
    bars, constraints, original_executor = inputs(value)
    original = replay(value, bars, constraints, original_executor)
    _, _, executor = inputs(value)
    path = value.source_root/'strategy.py'
    content = path.read_bytes()
    execute = executor.execute

    def replace_after_first(*args, **kwargs):
        result = execute(*args, **kwargs)
        if result.revision == 1:
            replacement = path.with_suffix('.replacement')
            replacement.write_bytes(content)
            os.replace(replacement, path)
        return result

    monkeypatch.setattr(executor, 'execute', replace_after_first)
    replaced = replay(value, bars, constraints, executor)
    for name in ('decisions', 'orders', 'fills', 'corporate_action_entries', 'account_points', 'account_daily', 'trades'):
        pd.testing.assert_frame_equal(getattr(original.execution_result, name), getattr(replaced.execution_result, name), check_exact=True)
    # Source defines a global counter which must be one in every new namespace.
    assert len(replaced.execution_result.decisions) == len(bars)-1
    path.unlink()  # Binding scope released all source handles on successful exit.


def test_deleted_source_cannot_be_hidden_by_an_open_reader(tmp_path, monkeypatch):
    value = candidate(tmp_path/'source')
    bars, constraints, executor = inputs(value)
    path = value.source_root/'strategy.py'
    execute = executor.execute

    def delete_after_first(*args, **kwargs):
        result = execute(*args, **kwargs)
        if result.revision == 1:
            path.unlink()
        return result

    monkeypatch.setattr(executor, 'execute', delete_after_first)
    with pytest.raises(ReplayFailure, match='source disappeared'):
        replay(value, bars, constraints, executor)
    assert executor.revision == 1


def multifile_candidate(root):
    value = candidate(root)
    source = 'from .rules import threshold\n' + SOURCE
    source = source.replace('    close = ctx.features', '    expected_threshold = threshold()\n    close = ctx.features')
    source = source.replace('close >= 10.', 'close >= expected_threshold')
    (root / 'strategy.py').write_text(source, encoding='utf-8')
    (root / 'rules').mkdir()
    (root / 'rules/__init__.py').write_text('from .levels import threshold\n', encoding='utf-8')
    (root / 'rules/levels.py').write_text(
        'COUNT = 0\nTHRESHOLD = 10.\ndef threshold():\n'
        ' global COUNT\n COUNT += 1\n'
        ' if COUNT != 1:\n  raise ValueError("relative module globals leaked")\n'
        ' return THRESHOLD\n', encoding='utf-8')
    files = ('rules/__init__.py', 'rules/levels.py', 'strategy.py')
    return replace(value, definition=replace(value.definition, source_files=files,
                                             source_sha256=equity_source_hash(root, files)))


def test_multifile_relative_imports_have_fresh_globals_and_every_file_is_read(tmp_path):
    value = multifile_candidate(tmp_path / 'source')
    bars, constraints, executor = inputs(value)
    existing = {name for name in sys.modules if name.startswith('_equity_')}
    meta_path = tuple(sys.meta_path)
    outcome = replay(value, bars, constraints, executor)
    assert outcome.statistics.source_checks == outcome.statistics.decisions == len(bars) - 1
    expected_bytes = sum(len((value.source_root / name).read_bytes()) for name in value.definition.source_files)
    assert outcome.statistics.source_bytes_read == outcome.statistics.decisions * expected_bytes
    assert {name for name in sys.modules if name.startswith('_equity_')} == existing
    assert tuple(sys.meta_path) == meta_path


def test_mutated_relative_dependency_is_rejected_before_next_account_transition(tmp_path, monkeypatch):
    value = multifile_candidate(tmp_path / 'source')
    bars, constraints, executor = inputs(value)
    path = value.source_root / 'rules/levels.py'
    content = path.read_bytes()
    metadata = path.stat()
    execute = executor.execute

    def change_dependency_after_first(*args, **kwargs):
        outcome = execute(*args, **kwargs)
        if outcome.revision == 1:
            path.write_bytes(content.replace(b'THRESHOLD = 10.', b'THRESHOLD = 11.'))
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        return outcome

    monkeypatch.setattr(executor, 'execute', change_dependency_after_first)
    with pytest.raises(ReplayFailure, match='source closure changed') as failed:
        replay(value, bars, constraints, executor)
    assert failed.value.committed_state.revision == executor.revision == 1
    assert len(executor.rows['decisions']) == 1


@pytest.mark.parametrize('raise_during_step', [False, True])
def test_user_registered_namespace_children_are_removed_on_success_and_failure(tmp_path, raise_during_step):
    value = candidate(tmp_path / 'source')
    register = ('    namespace = __package__\n'
        '    sys.modules[namespace + ".manual"] = types.ModuleType(namespace + ".manual")\n'
        '    sys.modules[namespace + ".manual.deep"] = types.ModuleType(namespace + ".manual.deep")\n')
    if raise_during_step:
        register += '    raise RuntimeError("synthetic step failed after module registration")\n'
    source = 'import sys\nimport types\n' + SOURCE.replace('    close = ctx.features', register + '    close = ctx.features')
    (value.source_root / 'strategy.py').write_text(source, encoding='utf-8')
    value = replace(value, definition=replace(value.definition,
        source_sha256=equity_source_hash(value.source_root, ('strategy.py',))))
    bars, constraints, executor = inputs(value)
    existing = {name for name in sys.modules if name.startswith('_equity_')}
    meta_path = tuple(sys.meta_path)
    if raise_during_step:
        with pytest.raises(ReplayFailure, match='synthetic step failed'):
            replay(value, bars, constraints, executor)
        assert executor.revision == 0
    else:
        assert replay(value, bars, constraints, executor).statistics.decisions == len(bars) - 1
    assert {name for name in sys.modules if name.startswith('_equity_')} == existing
    assert tuple(sys.meta_path) == meta_path
